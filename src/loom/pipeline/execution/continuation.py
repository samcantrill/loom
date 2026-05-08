"""Generic prepared-run and stage-job continuation APIs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.planning import ExecutionPlan, PlanAction, StageFingerprintRecord
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStorePaths, RunStore
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.serialization import PlainData, ensure_plain_data
from loom.timestamps import utc_timestamp

from .errors import PipelineExecutionError
from .eventing import emit_run_event, emit_stage_event
from .lifecycle import (
    commit_stage_execution_result,
    write_run_status,
    write_stage_running,
)
from .models import ExecutionFailure, StageRunResult
from .prepared_run import PREPARED_RUN_CONTINUATION_WHOLE_RUN, PreparedRunRecord
from .run_locks import acquire_run_lock, build_lock_owner, release_run_lock
from .stage_worker import (
    StageWorkerStateError,
    infer_stage_worker_attempt,
    reconstruct_stage_execution_request,
)
from .models import StageWorkerRequest

Clock = Callable[[], str]
ArtifactStoreFactory = Callable[[Path], ArtifactStore]

PREPARED_RUN_CONTINUE_RESULT_SCHEMA_VERSION = 1
STAGE_JOB_RUN_RESULT_SCHEMA_VERSION = 1
_SUPPORTED_CONTINUATION_EXECUTORS = frozenset({"local"})


class ContinuationStateError(PipelineExecutionError):
    """Raised when durable continuation state is missing or unsafe."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        context: Mapping[str, PlainData] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})

    def to_dict(self) -> dict[str, object]:
        return {
            "message": str(self),
            "code": self.code,
            "context": dict(self.context),
        }


class UnsupportedContinuationExecutorError(ContinuationStateError):
    """Raised when a continuation command selects a recursive executor."""

    def __init__(self, executor: str) -> None:
        super().__init__(
            f"unsupported continuation executor {executor!r}; supported executors: local",
            code="execution.continuation.unsupported_executor",
            context={"executor": executor, "supported": ["local"]},
        )


class InsufficientPreparedStateError(ContinuationStateError):
    """Raised when whole-run continuation has no safe replay payload."""

    def __init__(self, run_uri: str) -> None:
        super().__init__(
            "prepared run does not contain an explicitly safe whole-run execution payload",
            code="execution.prepared_run.insufficient_prepared_state",
            context={"run_uri": run_uri},
        )


@dataclass(frozen=True, slots=True)
class PreparedRunContinueRequest:
    run_uri: str
    executor: str = "local"

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise ContinuationStateError(
                "PreparedRunContinueRequest.run_uri is required",
                code="execution.prepared_run.invalid_request",
            )
        if not isinstance(self.executor, str) or not self.executor:
            raise ContinuationStateError(
                "PreparedRunContinueRequest.executor is required",
                code="execution.prepared_run.invalid_request",
            )


@dataclass(frozen=True, slots=True)
class PreparedRunContinueResult:
    schema_version: int
    run_uri: str
    status: str
    executor: str
    message: str
    prepared_at: str | None = None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "status": self.status,
            "executor": self.executor,
            "message": self.message,
            "prepared_at": self.prepared_at,
        }


@dataclass(frozen=True, slots=True)
class StageJobRunRequest:
    run_uri: str
    stage_name: str
    executor: str = "local"
    attempt: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise ContinuationStateError(
                "StageJobRunRequest.run_uri is required",
                code="execution.stage_job.invalid_request",
            )
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise ContinuationStateError(
                "StageJobRunRequest.stage_name is required",
                code="execution.stage_job.invalid_request",
            )
        if not isinstance(self.executor, str) or not self.executor:
            raise ContinuationStateError(
                "StageJobRunRequest.executor is required",
                code="execution.stage_job.invalid_request",
            )
        if self.attempt is not None and (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise ContinuationStateError(
                "StageJobRunRequest.attempt must be a positive integer",
                code="execution.stage_job.invalid_request",
            )


@dataclass(frozen=True, slots=True)
class StageJobRunResult:
    schema_version: int
    run_uri: str
    stage_name: str
    attempt: int
    status: StageStatus
    run_status: RunStatus
    outputs: Mapping[str, ArtifactRef] = field(default_factory=dict)
    failure: ExecutionFailure | None = None
    started_at: str | None = None
    finished_at: str | None = None
    executor_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "status": self.status.value,
            "run_status": self.run_status.value,
            "outputs": {name: ref.to_dict() for name, ref in self.outputs.items()},
            "failure": self.failure.to_dict() if self.failure is not None else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "executor_metadata": dict(self.executor_metadata),
        }


def continue_prepared_run(
    *,
    run_store: RunStore,
    request: PreparedRunContinueRequest,
) -> PreparedRunContinueResult:
    """Validate a prepared whole-run continuation and fail before unsafe replay."""

    _validate_executor(request.executor)
    if not isinstance(run_store, RunStore):
        raise ContinuationStateError(
            "continue_prepared_run requires RunStore",
            code="execution.prepared_run.invalid_store",
        )
    run_uri = run_store.resolve_run_uri(request.run_uri)
    run_store.open_run(run_uri)
    prepared = _read_prepared_run(run_store, run_uri)
    _read_execution_plan(run_store=run_store, run_uri=run_uri)
    runtime = run_store.read_runtime_metadata(run_uri)
    if runtime is None:
        raise ContinuationStateError(
            f"run {run_uri!r} has no persisted runtime metadata",
            code="execution.prepared_run.missing_runtime_metadata",
            context={"run_uri": run_uri},
        )
    if prepared.run_uri != run_uri:
        raise ContinuationStateError(
            "prepared-run run_uri does not match requested run",
            code="execution.prepared_run.identity_mismatch",
            context={"run_uri": run_uri, "prepared_run_uri": prepared.run_uri},
        )
    if prepared.continuation_type != PREPARED_RUN_CONTINUATION_WHOLE_RUN:
        raise ContinuationStateError(
            "prepared-run record is not a whole-run continuation",
            code="execution.prepared_run.invalid_continuation_type",
            context={"run_uri": run_uri},
        )
    _validate_prepared_plan_summary(run_store=run_store, run_uri=run_uri, prepared=prepared)
    _validate_prepared_runtime_summary(runtime=runtime, prepared=prepared)
    raise InsufficientPreparedStateError(run_uri)


def run_stage_job(
    *,
    run_store: RunStore,
    request: StageJobRunRequest,
    artifact_store_factory: ArtifactStoreFactory | None = None,
    clock: Clock = utc_timestamp,
) -> StageJobRunResult:
    """Run and finalize one planned stage from durable prepared state."""

    _validate_executor(request.executor)
    if not isinstance(run_store, RunStore):
        raise ContinuationStateError(
            "run_stage_job requires RunStore",
            code="execution.stage_job.invalid_store",
        )
    if not isinstance(run_store, LocalRunStorePaths):
        raise ContinuationStateError(
            "run_stage_job requires local run-store path helpers",
            code="execution.stage_job.invalid_store",
        )

    run_uri = run_store.resolve_run_uri(request.run_uri)
    run_store.open_run(run_uri)
    lock = acquire_run_lock(
        run_store,
        run_uri,
        owner=build_lock_owner(
            component="StageJobRunner",
            run_uri=run_uri,
            executor=request.executor,
        ),
    )
    try:
        return _run_stage_job_locked(
            run_store=run_store,
            request=StageJobRunRequest(
                run_uri=run_uri,
                stage_name=request.stage_name,
                executor=request.executor,
                attempt=request.attempt,
            ),
            artifact_store_factory=artifact_store_factory or LocalArtifactStore,
            clock=clock,
        )
    finally:
        release_run_lock(run_store, lock)


def _run_stage_job_locked(
    *,
    run_store: RunStore,
    request: StageJobRunRequest,
    artifact_store_factory: ArtifactStoreFactory,
    clock: Clock,
) -> StageJobRunResult:
    plan = _read_execution_plan(run_store=run_store, run_uri=request.run_uri)
    stage_plan = _stage_plan(plan, request.stage_name)
    if stage_plan.action != PlanAction.RUN:
        raise ContinuationStateError(
            f"stage {request.stage_name!r} is planned as {stage_plan.action.value}, not RUN",
            code="execution.stage_job.invalid_target_stage",
            context={"run_uri": request.run_uri, "stage": request.stage_name},
        )
    _validate_upstream_ready(run_store=run_store, run_uri=request.run_uri, plan=plan, stage_name=request.stage_name)
    runtime = run_store.read_runtime_metadata(request.run_uri)
    if runtime is None:
        raise ContinuationStateError(
            f"run {request.run_uri!r} has no persisted runtime metadata",
            code="execution.stage_job.missing_runtime_metadata",
            context={"run_uri": request.run_uri},
        )
    _validate_runtime_environment(runtime, request.stage_name)
    attempt = request.attempt
    if attempt is None:
        try:
            attempt = infer_stage_worker_attempt(
                run_store=run_store,
                run_uri=request.run_uri,
                stage_name=request.stage_name,
            )
        except StageWorkerStateError as exc:
            raise ContinuationStateError(
                str(exc),
                code="execution.stage_job.insufficient_reconstruction_state",
                context={"run_uri": request.run_uri, "stage": request.stage_name},
            ) from exc
    worker_request = _read_worker_request(
        run_store=run_store,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
    )
    _validate_executor(worker_request.executor_name)
    _validate_worker_attempt_state(
        run_store=run_store,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
    )
    _validate_worker_runtime_environment(worker_request)
    stage_index = plan.stage_order.index(request.stage_name)
    try:
        exec_request = reconstruct_stage_execution_request(
            run_store=run_store,
            worker_request=worker_request,
            stage_plan=stage_plan,
            stage_index=stage_index,
            artifact_store_factory=artifact_store_factory,
            allow_resolved_config_fallback=False,
        )
    except StageWorkerStateError as exc:
        raise ContinuationStateError(
            str(exc),
            code="execution.stage_job.insufficient_reconstruction_state",
            context={"run_uri": request.run_uri, "stage": request.stage_name},
        ) from exc

    running_at = clock()
    write_stage_running(
        run_store,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
        started_at=running_at,
        metadata={"action": PlanAction.RUN.value, "stage_job": True},
    )
    emit_stage_event(
        run_store,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        event_type="stage.started",
        timestamp=running_at,
        payload={"attempt": attempt, "action": PlanAction.RUN.value, "stage_job": True},
    )

    from loom.pipeline.executors import LocalExecutor

    execution_result = LocalExecutor(capture_stdout_stderr=True).execute(exec_request)
    run_status_before = _require_run_status(run_store, request.run_uri)
    stage_result = commit_stage_execution_result(
        run_store,
        run_uri=request.run_uri,
        stage=exec_request.stage,
        stage_plan=stage_plan,
        attempt=attempt,
        inputs=exec_request.inputs,
        fingerprint=cast(StageFingerprintRecord, exec_request.fingerprint).to_dict(),
        artifact_store=artifact_store_factory(
            cast(LocalRunStorePaths, run_store).local_artifact_root(request.run_uri)
        ),
        created_at=run_status_before.created_at,
        run_started_at=run_status_before.started_at or run_status_before.updated_at,
        execution_result=execution_result,
        executor_name=request.executor,
        clock=clock,
    )
    run_status = _update_stage_job_run_status(
        run_store=run_store,
        run_uri=request.run_uri,
        plan=plan,
        stage_result=stage_result,
        created_at=run_status_before.created_at,
        started_at=run_status_before.started_at or run_status_before.updated_at,
        clock=clock,
    )
    return StageJobRunResult(
        schema_version=STAGE_JOB_RUN_RESULT_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
        status=cast(StageStatus, stage_result.status),
        run_status=run_status,
        outputs=stage_result.outputs,
        failure=stage_result.failure,
        started_at=stage_result.started_at,
        finished_at=stage_result.finished_at,
        executor_metadata=stage_result.executor_metadata,
    )


def _validate_executor(executor: str) -> None:
    if executor not in _SUPPORTED_CONTINUATION_EXECUTORS:
        raise UnsupportedContinuationExecutorError(executor)


def _read_prepared_run(run_store: RunStore, run_uri: str) -> PreparedRunRecord:
    raw = run_store.read_prepared_run(run_uri)
    if raw is None:
        raise ContinuationStateError(
            f"run {run_uri!r} has no prepared-run metadata",
            code="execution.prepared_run.missing_prepared_run",
            context={"run_uri": run_uri},
        )
    try:
        return PreparedRunRecord.from_dict(raw)
    except Exception as exc:
        raise ContinuationStateError(
            f"run {run_uri!r} has invalid prepared-run metadata: {exc}",
            code="execution.prepared_run.invalid_prepared_run",
            context={"run_uri": run_uri},
        ) from exc


def _read_execution_plan(*, run_store: RunStore, run_uri: str) -> ExecutionPlan:
    raw_plan = run_store.read_plan(run_uri)
    if raw_plan is None:
        raise ContinuationStateError(
            f"run {run_uri!r} has no persisted execution plan",
            code="execution.continuation.missing_plan",
            context={"run_uri": run_uri},
        )
    try:
        plan = ExecutionPlan.from_dict(raw_plan)
    except Exception as exc:
        raise ContinuationStateError(
            f"run {run_uri!r} has an invalid persisted execution plan: {exc}",
            code="execution.continuation.invalid_plan",
            context={"run_uri": run_uri},
        ) from exc
    if plan.run_uri != run_uri:
        raise ContinuationStateError(
            "persisted execution plan run_uri does not match requested run",
            code="execution.continuation.plan_identity_mismatch",
            context={"run_uri": run_uri, "plan_run_uri": plan.run_uri},
        )
    return plan


def _stage_plan(plan: ExecutionPlan, stage_name: str):
    for stage_plan in plan.ordered_stage_plans:
        if stage_plan.stage_name == stage_name:
            return stage_plan
    raise ContinuationStateError(
        f"persisted execution plan has no stage named {stage_name!r}",
        code="execution.stage_job.invalid_target_stage",
        context={"stage": stage_name},
    )


def _read_worker_request(
    *,
    run_store: RunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
) -> StageWorkerRequest:
    raw = run_store.read_stage_worker_request(run_uri, stage_name, attempt=attempt)
    if raw is None:
        raise ContinuationStateError(
            f"stage {stage_name!r} attempt {attempt} has no prepared worker request",
            code="execution.stage_job.insufficient_reconstruction_state",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )
    try:
        return StageWorkerRequest.from_dict(raw)
    except Exception as exc:
        raise ContinuationStateError(
            f"stage {stage_name!r} attempt {attempt} has an invalid worker request: {exc}",
            code="execution.stage_job.insufficient_reconstruction_state",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        ) from exc


def _validate_worker_attempt_state(
    *,
    run_store: RunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
) -> None:
    status = run_store.read_stage_status(run_uri, stage_name)
    if status is None or status.attempt != attempt:
        raise ContinuationStateError(
            f"stage {stage_name!r} attempt {attempt} is not the current prepared attempt",
            code="execution.stage_job.missing_required_handoff_state",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )
    if status.status not in {StageStatus.PENDING, StageStatus.RUNNING}:
        raise ContinuationStateError(
            f"stage {stage_name!r} attempt {attempt} is {status.status.value}, not PENDING or RUNNING",
            code="execution.stage_job.missing_required_handoff_state",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )
    if run_store.read_stage_worker_result(run_uri, stage_name, attempt=attempt) is not None:
        raise ContinuationStateError(
            f"stage {stage_name!r} attempt {attempt} already has a worker result",
            code="execution.stage_job.missing_required_handoff_state",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )


def _validate_upstream_ready(
    *,
    run_store: RunStore,
    run_uri: str,
    plan: ExecutionPlan,
    stage_name: str,
) -> None:
    target = _stage_plan(plan, stage_name)
    for pending in target.pending_inputs:
        upstream = _stage_plan(plan, pending.source_stage)
        outputs = dict(upstream.reusable_outputs)
        if not outputs:
            outputs = run_store.read_stage_outputs(run_uri, pending.source_stage) or {}
        if pending.source_output not in outputs:
            raise ContinuationStateError(
                f"upstream output {pending.source_stage}.{pending.source_output} is not ready",
                code="execution.stage_job.upstream_not_ready",
                context={
                    "run_uri": run_uri,
                    "stage": stage_name,
                    "upstream_stage": pending.source_stage,
                    "output": pending.source_output,
                },
            )
        status = run_store.read_stage_status(run_uri, pending.source_stage)
        if upstream.action == PlanAction.REUSE:
            continue
        if status is None or status.status not in {
            StageStatus.SUCCEEDED,
            StageStatus.SKIPPED,
        }:
            raise ContinuationStateError(
                f"upstream stage {pending.source_stage!r} is not terminal-successful",
                code="execution.stage_job.upstream_not_ready",
                context={
                    "run_uri": run_uri,
                    "stage": stage_name,
                    "upstream_stage": pending.source_stage,
                },
            )


def _validate_prepared_plan_summary(
    *,
    run_store: RunStore,
    run_uri: str,
    prepared: PreparedRunRecord,
) -> None:
    plan = _read_execution_plan(run_store=run_store, run_uri=run_uri)
    summary = prepared.plan.get("plan_summary")
    if isinstance(summary, Mapping):
        stage_count = summary.get("stage_count")
        if stage_count is not None and stage_count != len(plan.stage_order):
            raise ContinuationStateError(
                "prepared-run plan summary does not match persisted plan",
                code="execution.prepared_run.identity_mismatch",
                context={"run_uri": run_uri},
            )


def _validate_prepared_runtime_summary(
    *,
    runtime: Mapping[str, PlainData],
    prepared: PreparedRunRecord,
) -> None:
    prepared_stage_count = prepared.runtime.get("stage_count")
    runtime_stages = runtime.get("stages")
    if (
        prepared_stage_count is not None
        and isinstance(runtime_stages, Mapping)
        and prepared_stage_count != len(runtime_stages)
    ):
        raise ContinuationStateError(
            "prepared-run runtime summary does not match persisted runtime metadata",
            code="execution.prepared_run.identity_mismatch",
            context={"prepared_stage_count": prepared_stage_count},
        )


def _validate_runtime_environment(
    runtime: Mapping[str, PlainData],
    stage_name: str,
) -> None:
    stages = runtime.get("stages")
    if not isinstance(stages, Mapping):
        raise ContinuationStateError(
            "runtime metadata does not include stage runtime summaries",
            code="execution.stage_job.missing_runtime_metadata",
        )
    stage_runtime = stages.get(stage_name)
    if not isinstance(stage_runtime, Mapping):
        raise ContinuationStateError(
            f"runtime metadata has no entry for stage {stage_name!r}",
            code="execution.stage_job.missing_runtime_metadata",
            context={"stage": stage_name},
        )
    _reject_environment_requirements(stage_runtime, code="execution.stage_job.missing_environment")


def _validate_worker_runtime_environment(worker_request: StageWorkerRequest) -> None:
    _reject_environment_requirements(
        worker_request.resolved_runtime,
        code="execution.stage_job.missing_environment",
    )


def _reject_environment_requirements(
    value: Mapping[str, object],
    *,
    code: str,
) -> None:
    environment = value.get("environment")
    if not isinstance(environment, Mapping):
        return
    for scope in ("run", "stage"):
        scoped = environment.get(scope)
        if not isinstance(scoped, Mapping):
            continue
        set_count = scoped.get("set_variable_count", 0)
        unset_count = scoped.get("unset_variable_count", 0)
        if set_count or unset_count:
            raise ContinuationStateError(
                "stage-job runtime metadata does not contain environment variable names or values",
                code=code,
                context={"scope": scope},
            )


def _require_run_status(run_store: RunStore, run_uri: str):
    status = run_store.read_run_status(run_uri)
    if status is None:
        raise ContinuationStateError(
            f"run {run_uri!r} has no run status",
            code="execution.stage_job.missing_run_status",
            context={"run_uri": run_uri},
        )
    return status


def _update_stage_job_run_status(
    *,
    run_store: RunStore,
    run_uri: str,
    plan: ExecutionPlan,
    stage_result: StageRunResult,
    created_at: str,
    started_at: str,
    clock: Clock,
) -> RunStatus:
    if stage_result.status == StageStatus.FAILED:
        emit_run_event(
            run_store,
            run_uri=run_uri,
            event_type="run.failed",
            timestamp=clock(),
            payload={
                "status": RunStatus.FAILED.value,
                "failed_stage": stage_result.stage_name,
            },
        )
        return RunStatus.FAILED
    if not _all_planned_stages_terminal_success(
        run_store=run_store,
        run_uri=run_uri,
        plan=plan,
        target_stage=stage_result.stage_name,
    ):
        status = run_store.read_run_status(run_uri)
        return status.status if status is not None else RunStatus.RUNNING
    finished_at = stage_result.finished_at or clock()
    write_run_status(
        run_store,
        run_uri=run_uri,
        status=RunStatus.SUCCEEDED,
        created_at=created_at,
        updated_at=finished_at,
        started_at=started_at,
        finished_at=finished_at,
    )
    emit_run_event(
        run_store,
        run_uri=run_uri,
        event_type="run.completed",
        timestamp=finished_at,
        payload={"status": RunStatus.SUCCEEDED.value},
    )
    return RunStatus.SUCCEEDED


def _all_planned_stages_terminal_success(
    *,
    run_store: RunStore,
    run_uri: str,
    plan: ExecutionPlan,
    target_stage: str,
) -> bool:
    for stage_plan in plan.ordered_stage_plans:
        if stage_plan.stage_name == target_stage:
            continue
        if stage_plan.action == PlanAction.REUSE:
            continue
        status = run_store.read_stage_status(run_uri, stage_plan.stage_name)
        if stage_plan.action == PlanAction.SKIP:
            if status is None or status.status != StageStatus.SKIPPED:
                return False
            continue
        if status is None or status.status != StageStatus.SUCCEEDED:
            return False
    return True


def _plain_mapping(value: object, path: str) -> dict[str, PlainData]:
    normalized = ensure_plain_data(value, path=path)
    if not isinstance(normalized, dict):
        raise ContinuationStateError(
            f"{path} must be mapping plain data",
            code="execution.continuation.invalid_plain_data",
        )
    return normalized


__all__ = [
    "ContinuationStateError",
    "InsufficientPreparedStateError",
    "PREPARED_RUN_CONTINUE_RESULT_SCHEMA_VERSION",
    "PreparedRunContinueRequest",
    "PreparedRunContinueResult",
    "STAGE_JOB_RUN_RESULT_SCHEMA_VERSION",
    "StageJobRunRequest",
    "StageJobRunResult",
    "UnsupportedContinuationExecutorError",
    "continue_prepared_run",
    "run_stage_job",
]
