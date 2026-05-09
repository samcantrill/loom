"""Generic prepared-run and stage-job continuation APIs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.errors import StageContractError
from loom.pipeline.planning import (
    ExecutionPlan,
    PlanAction,
    StageFingerprintRecord,
    build_stage_fingerprint,
)
from loom.pipeline.specs import parse_pipeline_config
from loom.pipeline.submitted import (
    SUBMITTED_OPERATION_METADATA_KEY,
    SubmittedOperationRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthorityStoreError,
    LocalArtifactStore,
    LocalRunStorePaths,
    RunStore,
)
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.errors import ArtifactStoreError, StoreError
from loom.serialization import PlainData, ensure_plain_data, json_loads
from loom.timestamps import utc_timestamp

from .errors import OutputValidationError, PipelineExecutionError, PlanExecutionError
from .eventing import emit_run_event, emit_stage_event
from .lifecycle import (
    commit_stage_execution_result,
    record_stage_failure_and_failed_run,
    write_run_status,
    write_stage_running,
)
from .logs import traceback_log_path
from .models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    STAGE_WORKER_REQUEST_SCHEMA_VERSION,
    ExecutionFailure,
    StageRunResult,
)
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
    _validate_prepared_plan_summary(
        run_store=run_store, run_uri=run_uri, prepared=prepared
    )
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
    _validate_upstream_ready(
        run_store=run_store,
        run_uri=request.run_uri,
        plan=plan,
        stage_name=request.stage_name,
    )
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
        submitted_status = run_store.read_stage_status(
            request.run_uri, request.stage_name
        )
        if (
            submitted_status is not None
            and submitted_status.status == StageStatus.SUBMITTED
            and run_store.read_stage_worker_request(
                request.run_uri,
                request.stage_name,
                attempt=submitted_status.attempt,
            )
            is None
        ):
            attempt = submitted_status.attempt
        else:
            try:
                attempt = _infer_stage_job_attempt(
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
    _materialize_submitted_worker_request_if_needed(
        run_store=run_store,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
        plan=plan,
        stage_plan=stage_plan,
        runtime=runtime,
        continuation_executor=request.executor,
        clock=clock,
    )
    worker_request = _read_worker_request(
        run_store=run_store,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
    )
    _validate_worker_request_identity(
        worker_request=worker_request,
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
        worker_request=worker_request,
        continuation_executor=request.executor,
    )
    _validate_worker_runtime_environment(worker_request)
    run_status_before = _require_run_status(run_store, request.run_uri)
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
    except StageContractError as exc:
        started_at = clock()
        failure = _failure_from_stage_job_exception(
            run_uri=request.run_uri,
            stage_name=request.stage_name,
            attempt=attempt,
            executor=request.executor,
            stdout_path=Path(worker_request.stdout_path),
            stderr_path=Path(worker_request.stderr_path),
            traceback_path=Path(worker_request.traceback_path),
            exc=exc,
            clock=clock,
        )
        failure = record_stage_failure_and_failed_run(
            run_store,
            run_uri=request.run_uri,
            stage_name=request.stage_name,
            attempt=attempt,
            started_at=started_at,
            created_at=run_status_before.created_at,
            run_started_at=run_status_before.started_at or run_status_before.updated_at,
            failure=failure,
            executor_name=request.executor,
            clock=clock,
        )
        return StageJobRunResult(
            schema_version=STAGE_JOB_RUN_RESULT_SCHEMA_VERSION,
            run_uri=request.run_uri,
            stage_name=request.stage_name,
            attempt=attempt,
            status=StageStatus.FAILED,
            run_status=RunStatus.FAILED,
            outputs={},
            failure=failure,
            started_at=started_at,
            finished_at=failure.failed_at,
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

    try:
        execution_result = LocalExecutor(capture_stdout_stderr=True).execute(
            exec_request
        )
        stage_result = commit_stage_execution_result(
            run_store,
            run_uri=request.run_uri,
            stage=exec_request.stage,
            stage_plan=stage_plan,
            attempt=attempt,
            inputs=exec_request.inputs,
            fingerprint=cast(
                StageFingerprintRecord, exec_request.fingerprint
            ).to_dict(),
            artifact_store=artifact_store_factory(
                cast(LocalRunStorePaths, run_store).local_artifact_root(request.run_uri)
            ),
            created_at=run_status_before.created_at,
            run_started_at=run_status_before.started_at or run_status_before.updated_at,
            execution_result=execution_result,
            executor_name=request.executor,
            clock=clock,
        )
    except Exception as exc:
        failure = _failure_from_stage_job_exception(
            run_uri=request.run_uri,
            stage_name=request.stage_name,
            attempt=attempt,
            executor=request.executor,
            stdout_path=exec_request.stdout_path,
            stderr_path=exec_request.stderr_path,
            traceback_path=exec_request.traceback_path,
            exc=exc,
            clock=clock,
        )
        failure = record_stage_failure_and_failed_run(
            run_store,
            run_uri=request.run_uri,
            stage_name=request.stage_name,
            attempt=attempt,
            started_at=running_at,
            created_at=run_status_before.created_at,
            run_started_at=run_status_before.started_at or run_status_before.updated_at,
            failure=failure,
            executor_name=request.executor,
            clock=clock,
        )
        stage_result = StageRunResult(
            stage_name=request.stage_name,
            action=PlanAction.RUN,
            status=StageStatus.FAILED,
            attempt=attempt,
            outputs={},
            failure=failure,
            reasons=stage_plan.reasons,
            started_at=running_at,
            finished_at=failure.failed_at,
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


def _materialize_submitted_worker_request_if_needed(
    *,
    run_store: RunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
    plan: ExecutionPlan,
    stage_plan,
    runtime: Mapping[str, PlainData],
    continuation_executor: str,
    clock: Clock,
) -> None:
    status = run_store.read_stage_status(run_uri, stage_name)
    if (
        status is None
        or status.status != StageStatus.SUBMITTED
        or status.attempt != attempt
        or run_store.read_stage_worker_request(run_uri, stage_name, attempt=attempt)
        is not None
    ):
        return

    status_submission = _require_submitted_stage_metadata(
        status.metadata,
        field="stage status metadata",
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        continuation_executor=continuation_executor,
    )
    record = run_store.read_submitted_operation(
        run_uri,
        cast(str, status_submission["submission_id"]),
    )
    if record is None:
        raise ContinuationStateError(
            "submitted stage has no matching submitted-operation registry record",
            code="execution.stage_job.submitted_registry_missing",
            context={
                "run_uri": run_uri,
                "stage": stage_name,
                "attempt": attempt,
                "submission_id": status_submission["submission_id"],
            },
        )
    _validate_submitted_registry_match(
        record=record,
        submission=status_submission,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
    )

    stage = _stage_spec_from_config_snapshot(run_store, run_uri, stage_name)
    inputs = _bind_stage_job_inputs(
        run_store=run_store,
        run_uri=run_uri,
        stage_plan=stage_plan,
    )
    fingerprint = build_stage_fingerprint(
        stage,
        bound_inputs=inputs,
        fingerprint_context=plan.fingerprint_context,
    )
    local_paths = cast(LocalRunStorePaths, run_store)
    worker_request = StageWorkerRequest(
        schema_version=STAGE_WORKER_REQUEST_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        prepared_at=clock(),
        executor_name=continuation_executor,
        inputs=inputs,
        fingerprint=fingerprint,
        stdout_path=str(
            local_paths.local_stage_log_path(run_uri, stage_name, "stdout")
        ),
        stderr_path=str(
            local_paths.local_stage_log_path(run_uri, stage_name, "stderr")
        ),
        traceback_path=str(
            traceback_log_path(
                run_store=local_paths,
                run_uri=run_uri,
                stage_name=stage_name,
            )
        ),
        result_path=str(
            local_paths.local_stage_worker_result_path(run_uri, stage_name)
        ),
        resolved_runtime=_stage_runtime_metadata(
            runtime=runtime,
            stage_name=stage_name,
            continuation_executor=continuation_executor,
        ),
        executor_metadata={"worker_command": "loom stage-job run"},
        metadata=dict(status.metadata),
    )
    run_store.write_stage_inputs(run_uri, stage_name, inputs, attempt=attempt)
    run_store.write_stage_fingerprint(
        run_uri,
        stage_name,
        fingerprint.to_dict(),
        attempt=attempt,
    )
    run_store.prepare_stage_workspace(run_uri, stage_name)
    run_store.write_stage_worker_request(
        run_uri,
        stage_name,
        worker_request.to_dict(),
        attempt=attempt,
    )


def _stage_spec_from_config_snapshot(
    run_store: RunStore, run_uri: str, stage_name: str
):
    snapshot = run_store.read_config_snapshot(run_uri, "resolved")
    if snapshot is None:
        raise ContinuationStateError(
            "submitted stage cannot be materialized without a safe resolved config snapshot",
            code="execution.stage_job.insufficient_reconstruction_state",
            context={"run_uri": run_uri, "stage": stage_name},
        )
    try:
        decoded = json_loads(snapshot, path="config/resolved.json")
    except Exception as exc:
        raise ContinuationStateError(
            f"safe resolved config snapshot is invalid JSON: {exc}",
            code="execution.stage_job.insufficient_reconstruction_state",
            context={"run_uri": run_uri, "stage": stage_name},
        ) from exc
    if not isinstance(decoded, Mapping) or "pipeline" not in decoded:
        raise ContinuationStateError(
            "safe resolved config snapshot does not contain a pipeline definition",
            code="execution.stage_job.insufficient_reconstruction_state",
            context={"run_uri": run_uri, "stage": stage_name},
        )
    try:
        return parse_pipeline_config(decoded["pipeline"]).get_stage(stage_name)
    except Exception as exc:
        raise ContinuationStateError(
            f"submitted stage cannot be reconstructed from config snapshot: {exc}",
            code="execution.stage_job.insufficient_reconstruction_state",
            context={"run_uri": run_uri, "stage": stage_name},
        ) from exc


def _bind_stage_job_inputs(
    *,
    run_store: RunStore,
    run_uri: str,
    stage_plan,
) -> dict[str, ArtifactRef]:
    inputs: dict[str, ArtifactRef] = {
        name: bound.artifact_ref for name, bound in stage_plan.bound_inputs.items()
    }
    for pending in stage_plan.pending_inputs:
        upstream = run_store.read_stage_outputs(run_uri, pending.source_stage) or {}
        ref = upstream.get(pending.source_output)
        if ref is None:
            raise ContinuationStateError(
                f"upstream output {pending.source_stage}.{pending.source_output} is not ready",
                code="execution.stage_job.upstream_not_ready",
                context={
                    "run_uri": run_uri,
                    "stage": stage_plan.stage_name,
                    "upstream_stage": pending.source_stage,
                    "output": pending.source_output,
                },
            )
        inputs[pending.input_name] = ref
    return inputs


def _stage_runtime_metadata(
    *,
    runtime: Mapping[str, PlainData],
    stage_name: str,
    continuation_executor: str,
) -> Mapping[str, PlainData]:
    stages = runtime.get("stages")
    stage_runtime = (
        stages.get(stage_name)
        if isinstance(stages, Mapping) and isinstance(stages.get(stage_name), Mapping)
        else {}
    )
    return {
        **dict(cast(Mapping[str, PlainData], stage_runtime)),
        "stage_id": stage_name,
        "executor": continuation_executor,
    }


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


def _infer_stage_job_attempt(
    *,
    run_store: RunStore,
    run_uri: str,
    stage_name: str,
) -> int:
    status = run_store.read_stage_status(run_uri, stage_name)
    if status is None:
        raise StageWorkerStateError(
            f"cannot infer attempt for stage {stage_name!r}: no stage status exists"
        )
    if status.status != StageStatus.SUBMITTED:
        return infer_stage_worker_attempt(
            run_store=run_store,
            run_uri=run_uri,
            stage_name=stage_name,
        )
    raw_request = run_store.read_stage_worker_request(
        run_uri,
        stage_name,
        attempt=status.attempt,
    )
    if raw_request is None:
        raise StageWorkerStateError(
            f"cannot infer attempt for stage {stage_name!r}: worker request is missing"
        )
    try:
        StageWorkerRequest.from_dict(raw_request)
    except Exception as exc:
        raise StageWorkerStateError(
            f"cannot infer attempt for stage {stage_name!r}: worker request is invalid: {exc}"
        ) from exc
    return status.attempt


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


def _validate_worker_request_identity(
    *,
    worker_request: StageWorkerRequest,
    run_uri: str,
    stage_name: str,
    attempt: int,
) -> None:
    if (
        worker_request.run_uri != run_uri
        or worker_request.stage_name != stage_name
        or worker_request.attempt != attempt
    ):
        raise ContinuationStateError(
            "prepared worker request identity does not match requested stage-job",
            code="execution.stage_job.insufficient_reconstruction_state",
            context={
                "run_uri": run_uri,
                "stage": stage_name,
                "attempt": attempt,
                "worker_run_uri": worker_request.run_uri,
                "worker_stage": worker_request.stage_name,
                "worker_attempt": worker_request.attempt,
            },
        )


def _validate_worker_attempt_state(
    *,
    run_store: RunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
    worker_request: StageWorkerRequest,
    continuation_executor: str,
) -> None:
    status = run_store.read_stage_status(run_uri, stage_name)
    if status is None or status.attempt != attempt:
        raise ContinuationStateError(
            f"stage {stage_name!r} attempt {attempt} is not the current prepared attempt",
            code="execution.stage_job.missing_required_handoff_state",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )
    if status.status == StageStatus.SUBMITTED:
        _validate_submitted_worker_attempt(
            run_store=run_store,
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            continuation_executor=continuation_executor,
            status_metadata=status.metadata,
            worker_request=worker_request,
        )
    elif status.status not in {StageStatus.PENDING, StageStatus.RUNNING}:
        raise ContinuationStateError(
            f"stage {stage_name!r} attempt {attempt} is {status.status.value}, not PENDING, SUBMITTED, or RUNNING",
            code="execution.stage_job.missing_required_handoff_state",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )
    if (
        run_store.read_stage_worker_result(run_uri, stage_name, attempt=attempt)
        is not None
    ):
        raise ContinuationStateError(
            f"stage {stage_name!r} attempt {attempt} already has a worker result",
            code="execution.stage_job.missing_required_handoff_state",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )


def _validate_submitted_worker_attempt(
    *,
    run_store: RunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
    continuation_executor: str,
    status_metadata: Mapping[str, PlainData],
    worker_request: StageWorkerRequest,
) -> None:
    status_submission = _require_submitted_stage_metadata(
        status_metadata,
        field="stage status metadata",
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        continuation_executor=continuation_executor,
    )
    worker_submission = _require_submitted_stage_metadata(
        worker_request.metadata,
        field="worker request metadata",
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        continuation_executor=continuation_executor,
    )
    if status_submission != worker_submission:
        raise ContinuationStateError(
            "submitted stage status metadata does not match worker request metadata",
            code="execution.stage_job.submitted_identity_mismatch",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )
    record = run_store.read_submitted_operation(
        run_uri,
        cast(str, status_submission["submission_id"]),
    )
    if record is None:
        raise ContinuationStateError(
            "submitted stage has no matching submitted-operation registry record",
            code="execution.stage_job.submitted_registry_missing",
            context={
                "run_uri": run_uri,
                "stage": stage_name,
                "attempt": attempt,
                "submission_id": status_submission["submission_id"],
            },
        )
    _validate_submitted_registry_match(
        record=record,
        submission=status_submission,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
    )


def _require_submitted_stage_metadata(
    metadata: Mapping[str, PlainData],
    *,
    field: str,
    run_uri: str,
    stage_name: str,
    attempt: int,
    continuation_executor: str,
) -> dict[str, PlainData]:
    raw = metadata.get(SUBMITTED_OPERATION_METADATA_KEY)
    if not isinstance(raw, Mapping):
        raise ContinuationStateError(
            f"{field} is missing submitted-operation identity",
            code="execution.stage_job.submitted_identity_missing",
            context={"run_uri": run_uri, "stage": stage_name, "attempt": attempt},
        )
    submission = _plain_mapping(raw, f"{field}.{SUBMITTED_OPERATION_METADATA_KEY}")
    expected: dict[str, object] = {
        "run_uri": run_uri,
        "stage_name": stage_name,
        "attempt": attempt,
        "continuation_executor": continuation_executor,
    }
    mismatches = {
        key: {"expected": value, "actual": submission.get(key)}
        for key, value in expected.items()
        if submission.get(key) != value
    }
    required_strings = (
        "submission_id",
        "backend",
        "mode",
        "manifest_relative_path",
    )
    for key in required_strings:
        if not isinstance(submission.get(key), str) or not submission.get(key):
            mismatches[key] = {
                "expected": "non-empty string",
                "actual": submission.get(key),
            }
    stage_metadata = submission.get("stage_metadata")
    if stage_metadata is not None and not isinstance(stage_metadata, Mapping):
        mismatches["stage_metadata"] = {
            "expected": "mapping or null",
            "actual": type(stage_metadata).__name__,
        }
    if mismatches:
        raise ContinuationStateError(
            f"{field} submitted-operation identity does not match requested stage-job",
            code="execution.stage_job.submitted_identity_mismatch",
            context={
                "run_uri": run_uri,
                "stage": stage_name,
                "attempt": attempt,
                "mismatches": cast(PlainData, mismatches),
            },
        )
    return submission


def _validate_submitted_registry_match(
    *,
    record: SubmittedOperationRecord,
    submission: Mapping[str, PlainData],
    run_uri: str,
    stage_name: str,
    attempt: int,
) -> None:
    expected = {
        "run_uri": run_uri,
        "submission_id": submission["submission_id"],
        "backend": submission["backend"],
        "mode": submission["mode"],
        "manifest_relative_path": submission["manifest_relative_path"],
    }
    actual = {
        "run_uri": record.run_uri,
        "submission_id": record.submission_id,
        "backend": record.backend,
        "mode": record.mode,
        "manifest_relative_path": record.manifest_relative_path,
    }
    mismatches = {
        key: {"expected": expected[key], "actual": actual[key]}
        for key in expected
        if expected[key] != actual[key]
    }
    if mismatches:
        raise ContinuationStateError(
            "submitted-operation registry record does not match stage identity",
            code="execution.stage_job.submitted_registry_mismatch",
            context={
                "run_uri": run_uri,
                "stage": stage_name,
                "attempt": attempt,
                "mismatches": cast(PlainData, mismatches),
            },
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
    _reject_environment_requirements(
        stage_runtime, code="execution.stage_job.missing_environment"
    )


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


def _failure_from_stage_job_exception(
    *,
    run_uri: str,
    stage_name: str,
    attempt: int,
    executor: str,
    stdout_path: Path,
    stderr_path: Path,
    traceback_path: Path,
    exc: Exception,
    clock: Clock,
) -> ExecutionFailure:
    return ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        failed_at=clock(),
        executor=executor,
        failure_type=_failure_type_for_stage_job_exception(exc),
        message=str(exc) or type(exc).__name__,
        exception_type=f"{type(exc).__module__}.{type(exc).__name__}",
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        traceback_path=str(traceback_path),
    )


def _failure_type_for_stage_job_exception(exc: Exception) -> str:
    if isinstance(exc, OutputValidationError):
        return "output_validation"
    if isinstance(exc, StageContractError):
        return "target_construction"
    if isinstance(exc, PlanExecutionError):
        return "plan_execution"
    if isinstance(exc, (StoreError, ArtifactStoreError, AuthorityStoreError)):
        return "store_commit"
    return "executor_infrastructure"


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
