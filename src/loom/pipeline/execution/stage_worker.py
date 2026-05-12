"""Durable one-stage worker execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import traceback
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.context import StageContext
from loom.pipeline.errors import PipelineValidationError, StageContractError
from loom.pipeline.executors import Executor, LocalExecutor
from loom.pipeline.planning import (
    ExecutionPlan,
    PlanAction,
    StageFingerprintRecord,
    StagePlan,
)
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.specs import OutputSpec, StageFactorySpec, StageSpec
from loom.pipeline.stage_factory import construct_stage
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    AuthorityStoreError,
    LegacyRunStore,
    LocalArtifactStore,
    LocalRunStorePaths,
)
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.serialization import PlainData, json_loads
from loom.serialization.errors import DeserializationError
from loom.timestamps import utc_timestamp

from .errors import PipelineExecutionError
from .logs import write_text_file
from .models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    STAGE_WORKER_RESULT_SCHEMA_VERSION,
    ExecutionFailure,
    StageExecutionRequest,
    StageExecutionResult,
    StageWorkerRequest,
    StageWorkerResult,
)

Clock = Callable[[], str]
ArtifactStoreFactory = Callable[[Path], ArtifactStore]


class StageWorkerStateError(PipelineExecutionError):
    """Raised when a worker cannot reconstruct one prepared attempt."""


@dataclass(frozen=True, slots=True)
class StageWorkerRunRequest:
    """Request to run one prepared stage attempt from durable state."""

    run_uri: str
    stage_name: str
    attempt: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise StageWorkerStateError("StageWorkerRunRequest.run_uri is required")
        if not isinstance(self.stage_name, str) or not self.stage_name:
            raise StageWorkerStateError("StageWorkerRunRequest.stage_name is required")
        if self.attempt is not None and (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt <= 0
        ):
            raise StageWorkerStateError(
                "StageWorkerRunRequest.attempt must be a positive integer"
            )


def run_stage_worker(
    *,
    run_store: LegacyRunStore,
    request: StageWorkerRunRequest,
    executor: Executor | None = None,
    artifact_store_factory: ArtifactStoreFactory | None = None,
    clock: Clock = utc_timestamp,
) -> StageWorkerResult:
    """Run one prepared stage attempt and persist its worker result handoff."""

    if not isinstance(run_store, LegacyRunStore):
        raise StageWorkerStateError("run_stage_worker requires LegacyRunStore")
    if not isinstance(run_store, LocalRunStorePaths):
        raise StageWorkerStateError(
            "run_stage_worker requires local run-store path helpers"
        )
    if not isinstance(request, StageWorkerRunRequest):
        raise StageWorkerStateError(
            "run_stage_worker.request must be StageWorkerRunRequest"
        )

    run_uri = run_store.resolve_run_uri(request.run_uri)
    run_store.open_run(run_uri)
    attempt = request.attempt
    if attempt is None:
        attempt = infer_stage_worker_attempt(
            run_store=run_store,
            run_uri=run_uri,
            stage_name=request.stage_name,
        )

    prepared = _read_prepared_request(
        run_store=run_store,
        run_uri=run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
    )
    _validate_current_attempt_state(
        run_store=run_store,
        run_uri=run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
    )
    _validate_worker_authority_if_supported(
        run_store=run_store,
        run_uri=run_uri,
        stage_name=request.stage_name,
        attempt=attempt,
        worker_request=prepared,
    )
    stage_plan = _read_stage_plan(
        run_store=run_store,
        run_uri=run_uri,
        stage_name=request.stage_name,
    )
    stage_index = _stage_index(
        run_store=run_store,
        run_uri=run_uri,
        stage_name=request.stage_name,
    )
    artifact_factory = artifact_store_factory or LocalArtifactStore
    worker_executor = executor or LocalExecutor(capture_stdout_stderr=True)

    try:
        exec_request = reconstruct_stage_execution_request(
            run_store=run_store,
            worker_request=prepared,
            stage_plan=stage_plan,
            stage_index=stage_index,
            artifact_store_factory=artifact_factory,
        )
        execution_result = worker_executor.execute(exec_request)
        worker_result = _result_from_execution_result(
            worker_request=prepared,
            execution_result=execution_result,
        )
    except Exception as exc:
        if isinstance(exc, StageWorkerStateError):
            raise
        worker_result = _failed_worker_result_from_exception(
            worker_request=prepared,
            exc=exc,
            clock=clock,
        )

    run_store.write_stage_worker_result(
        run_uri,
        request.stage_name,
        worker_result.to_dict(),
        attempt=attempt,
    )
    return worker_result


def infer_stage_worker_attempt(
    *,
    run_store: LegacyRunStore,
    run_uri: str,
    stage_name: str,
) -> int:
    """Infer the only currently prepared or running worker attempt."""

    status = run_store.read_stage_status(run_uri, stage_name)
    if status is None:
        raise StageWorkerStateError(
            f"cannot infer attempt for stage {stage_name!r}: no stage status exists"
        )
    if status.status not in {StageStatus.PENDING, StageStatus.RUNNING}:
        raise StageWorkerStateError(
            f"cannot infer attempt for stage {stage_name!r}: current status is "
            f"{status.status.value}, not PENDING or RUNNING"
        )
    if status.status == StageStatus.PENDING and status.metadata.get("prepared") is not True:
        raise StageWorkerStateError(
            f"cannot infer attempt for stage {stage_name!r}: PENDING status is not a prepared worker attempt"
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


def reconstruct_stage_execution_request(
    *,
    run_store: LegacyRunStore,
    worker_request: StageWorkerRequest,
    stage_plan: StagePlan,
    stage_index: int,
    artifact_store_factory: ArtifactStoreFactory | None = None,
    allow_resolved_config_fallback: bool = True,
) -> StageExecutionRequest:
    """Reconstruct the local execution request for a prepared worker attempt."""

    if not isinstance(run_store, LocalRunStorePaths):
        raise StageWorkerStateError(
            "reconstruct_stage_execution_request requires local run-store path helpers"
        )
    if stage_plan.stage_name != worker_request.stage_name:
        raise StageWorkerStateError(
            "prepared worker request does not match persisted stage plan"
        )
    if stage_plan.action != PlanAction.RUN:
        raise StageWorkerStateError(
            f"prepared worker stage {worker_request.stage_name!r} is not planned to RUN"
        )

    stage = _stage_spec_from_request(worker_request)
    stage_object = construct_stage(
        factory=stage.factory,
        stage_path=f"pipeline.stages[{stage_index}]",
    )
    artifact_factory = artifact_store_factory or LocalArtifactStore
    artifact_store = artifact_factory(run_store.local_artifact_root(worker_request.run_uri))
    context = StageContext(
        run_uri=worker_request.run_uri,
        stage_name=worker_request.stage_name,
        resolved_config=_resolved_config_context(
            run_store,
            worker_request,
            stage,
            allow_resolved_config_fallback=allow_resolved_config_fallback,
        ),
        stage_config=stage.stage_config,
        inputs=worker_request.inputs,
        local_output_dir=run_store.local_stage_artifact_dir(
            worker_request.run_uri,
            worker_request.stage_name,
        ),
        local_workspace_dir=run_store.local_stage_workspace_dir(
            worker_request.run_uri,
            worker_request.stage_name,
        ),
        provenance={},
        metadata={
            "factory_target": stage.factory.target_path,
            "resolved_runtime": dict(worker_request.resolved_runtime),
            "worker_request": True,
        },
        run_store=run_store,
        artifact_store=artifact_store,
        output_specs=stage.outputs,
    )
    return StageExecutionRequest(
        run_uri=worker_request.run_uri,
        stage=stage,
        stage_plan=stage_plan,
        stage_object=stage_object,
        context=context,
        inputs=worker_request.inputs,
        fingerprint=cast(StageFingerprintRecord, worker_request.fingerprint),
        attempt=worker_request.attempt,
        stdout_path=Path(worker_request.stdout_path),
        stderr_path=Path(worker_request.stderr_path),
        traceback_path=Path(worker_request.traceback_path),
        metadata={"worker_request": True},
        resolved_runtime=_resolved_runtime_for_execution(worker_request),
    )


def _read_prepared_request(
    *,
    run_store: LegacyRunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
) -> StageWorkerRequest:
    raw_request = run_store.read_stage_worker_request(
        run_uri,
        stage_name,
        attempt=attempt,
    )
    if raw_request is None:
        raise StageWorkerStateError(
            f"worker request for stage {stage_name!r} attempt {attempt} is missing"
        )
    try:
        return StageWorkerRequest.from_dict(raw_request)
    except Exception as exc:
        raise StageWorkerStateError(
            f"worker request for stage {stage_name!r} attempt {attempt} is invalid: {exc}"
        ) from exc


def _validate_current_attempt_state(
    *,
    run_store: LegacyRunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
) -> None:
    status = run_store.read_stage_status(run_uri, stage_name)
    if status is None:
        raise StageWorkerStateError(
            f"worker stage {stage_name!r} attempt {attempt} has no stage status"
        )
    if status.attempt != attempt:
        raise StageWorkerStateError(
            f"worker stage {stage_name!r} status attempt {status.attempt} does not match requested attempt {attempt}"
        )
    if status.status not in {StageStatus.PENDING, StageStatus.RUNNING}:
        raise StageWorkerStateError(
            f"worker stage {stage_name!r} attempt {attempt} is {status.status.value}, not PENDING or RUNNING"
        )
    existing_result = run_store.read_stage_worker_result(
        run_uri,
        stage_name,
        attempt=attempt,
    )
    if existing_result is not None:
        raise StageWorkerStateError(
            f"worker stage {stage_name!r} attempt {attempt} already has a worker result"
        )


def _validate_worker_authority_if_supported(
    *,
    run_store: LegacyRunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
    worker_request: StageWorkerRequest,
) -> None:
    validator = getattr(run_store, "validate_stage_job_authority", None)
    if not callable(validator):
        return
    try:
        authority = _authority_attempt_metadata(worker_request.metadata)
        validator(
            run_uri,
            stage_name,
            attempt,
            authority_attempt_id=authority["attempt_id"],
            authority_lease_id=authority["lease_id"],
            authority_owner_id=authority["owner_id"],
            authority_fencing_token=authority["fencing_token"],
            worker_metadata=worker_request.metadata,
        )
    except AuthorityStoreError as exc:
        raise StageWorkerStateError(str(exc)) from exc


def _authority_attempt_metadata(metadata: Mapping[str, PlainData]) -> dict[str, str]:
    raw = metadata.get("authority_attempt")
    if not isinstance(raw, Mapping):
        raise AuthorityStoreError("worker request is missing authority_attempt metadata")
    values: dict[str, str] = {}
    for key in ("attempt_id", "lease_id", "owner_id", "fencing_token"):
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise AuthorityStoreError(
                f"worker request authority_attempt.{key} must be a non-empty string"
            )
        values[key] = value
    return values


def _read_stage_plan(
    *,
    run_store: LegacyRunStore,
    run_uri: str,
    stage_name: str,
) -> StagePlan:
    plan = _read_execution_plan(run_store=run_store, run_uri=run_uri)
    for stage_plan in plan.ordered_stage_plans:
        if stage_plan.stage_name == stage_name:
            return stage_plan
    raise StageWorkerStateError(
        f"persisted execution plan has no stage named {stage_name!r}"
    )


def _stage_index(
    *,
    run_store: LegacyRunStore,
    run_uri: str,
    stage_name: str,
) -> int:
    plan = _read_execution_plan(run_store=run_store, run_uri=run_uri)
    try:
        return plan.stage_order.index(stage_name)
    except ValueError as exc:
        raise StageWorkerStateError(
            f"persisted execution plan has no stage named {stage_name!r}"
        ) from exc


def _read_execution_plan(
    *, run_store: LegacyRunStore, run_uri: str
) -> ExecutionPlan:
    raw_plan = run_store.read_plan(run_uri)
    if raw_plan is None:
        raise StageWorkerStateError(
            f"run {run_uri!r} has no persisted execution plan"
        )
    try:
        plan = ExecutionPlan.from_dict(raw_plan)
    except Exception as exc:
        raise StageWorkerStateError(
            f"run {run_uri!r} has an invalid persisted execution plan: {exc}"
        ) from exc
    if plan.run_uri != run_uri:
        raise StageWorkerStateError(
            f"persisted execution plan run_uri {plan.run_uri!r} does not match {run_uri!r}"
        )
    return plan


def _stage_spec_from_request(request: StageWorkerRequest) -> StageSpec:
    fingerprint = cast(StageFingerprintRecord, request.fingerprint)
    payload = fingerprint.payload
    outputs: dict[str, OutputSpec] = {}
    for name, output in payload.declared_outputs.items():
        outputs[name] = OutputSpec.from_config(
            output,
            path=f"StageWorkerRequest.fingerprint.payload.declared_outputs[{name!r}]",
        )
    return StageSpec(
        name=request.stage_name,
        factory=StageFactorySpec(
            target_path=payload.factory_target,
            init=payload.factory_init,
        ),
        outputs=outputs,
        stage_config=payload.stage_config,
        dependencies=(),
        inputs=payload.declared_inputs,
        resources={},
        fingerprint_fields=payload.fingerprint_fields,
    )


def _resolved_config_context(
    run_store: LegacyRunStore,
    request: StageWorkerRequest,
    stage: StageSpec,
    *,
    allow_resolved_config_fallback: bool,
) -> Mapping[str, PlainData]:
    if allow_resolved_config_fallback:
        snapshot = run_store.read_config_snapshot(request.run_uri, "resolved")
        if snapshot is not None:
            try:
                decoded = json_loads(snapshot, path="config/resolved.yaml")
            except DeserializationError as exc:
                raise StageWorkerStateError(
                    f"resolved config snapshot for run {request.run_uri!r} is invalid JSON: {exc}"
                ) from exc
            if not isinstance(decoded, Mapping):
                raise StageWorkerStateError(
                    f"resolved config snapshot for run {request.run_uri!r} must be a mapping"
                )
            return cast(Mapping[str, PlainData], dict(decoded))
    return _minimal_resolved_config(stage)


def _resolved_runtime_for_execution(
    request: StageWorkerRequest,
) -> ResolvedStageRuntimeOptions:
    executor = request.resolved_runtime.get("executor", request.executor_name)
    if not isinstance(executor, str) or not executor:
        executor = request.executor_name
    return ResolvedStageRuntimeOptions(stage_id=request.stage_name, executor=executor)


def _minimal_resolved_config(stage: StageSpec) -> Mapping[str, PlainData]:
    outputs: dict[str, PlainData] = {
        name: _output_spec_to_config(output) for name, output in stage.outputs.items()
    }
    stage_config: dict[str, PlainData] = {
        "name": stage.name,
        "factory": {
            "_target_": stage.factory.target_path,
            "init": dict(stage.factory.init),
        },
        "config": dict(stage.stage_config),
        "inputs": dict(stage.inputs),
        "outputs": outputs,
    }
    return {"pipeline": {"stages": [stage_config]}}


def _output_spec_to_config(output: OutputSpec) -> dict[str, PlainData]:
    return {
        "artifact_type": output.artifact_type,
        "codec_key": output.codec_key,
        "schema_version": output.schema_version,
        "metadata": dict(output.metadata),
    }


def _result_from_execution_result(
    *,
    worker_request: StageWorkerRequest,
    execution_result: StageExecutionResult,
) -> StageWorkerResult:
    if execution_result.stage_name != worker_request.stage_name:
        raise StageWorkerStateError(
            "executor result stage_name does not match worker request"
        )
    if execution_result.attempt != worker_request.attempt:
        raise StageWorkerStateError("executor result attempt does not match worker request")
    failure = execution_result.failure
    if execution_result.status == StageStatus.FAILED and failure is None:
        failure = ExecutionFailure(
            schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
            run_uri=worker_request.run_uri,
            stage_name=worker_request.stage_name,
            attempt=worker_request.attempt,
            failed_at=execution_result.finished_at,
            executor=worker_request.executor_name,
            failure_type="executor_infrastructure",
            message="executor failed without failure metadata",
            stdout_path=execution_result.stdout_path,
            stderr_path=execution_result.stderr_path,
            traceback_path=execution_result.traceback_path,
        )
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=worker_request.run_uri,
        stage_name=worker_request.stage_name,
        attempt=worker_request.attempt,
        status=execution_result.status,
        started_at=execution_result.started_at,
        finished_at=execution_result.finished_at,
        executor_name=worker_request.executor_name,
        outputs=(
            cast(Mapping[str, ArtifactRef], execution_result.outputs)
            if execution_result.status == StageStatus.SUCCEEDED
            else {}
        ),
        failure=failure,
        stdout_path=execution_result.stdout_path or worker_request.stdout_path,
        stderr_path=execution_result.stderr_path or worker_request.stderr_path,
        traceback_path=execution_result.traceback_path or worker_request.traceback_path,
        exit_code=0 if execution_result.status == StageStatus.SUCCEEDED else 1,
        executor_metadata=execution_result.executor_metadata,
    )


def _failed_worker_result_from_exception(
    *,
    worker_request: StageWorkerRequest,
    exc: BaseException,
    clock: Clock,
) -> StageWorkerResult:
    failed_at = clock()
    write_text_file(
        Path(worker_request.traceback_path),
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=worker_request.run_uri,
        stage_name=worker_request.stage_name,
        attempt=worker_request.attempt,
        failed_at=failed_at,
        executor=worker_request.executor_name,
        failure_type=_failure_type_for_exception(exc),
        message=str(exc) or type(exc).__name__,
        exception_type=f"{type(exc).__module__}.{type(exc).__name__}",
        traceback_path=worker_request.traceback_path,
        stdout_path=worker_request.stdout_path,
        stderr_path=worker_request.stderr_path,
    )
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=worker_request.run_uri,
        stage_name=worker_request.stage_name,
        attempt=worker_request.attempt,
        status=StageStatus.FAILED,
        started_at=failed_at,
        finished_at=failed_at,
        executor_name=worker_request.executor_name,
        outputs={},
        failure=failure,
        stdout_path=worker_request.stdout_path,
        stderr_path=worker_request.stderr_path,
        traceback_path=worker_request.traceback_path,
        exit_code=1,
    )


def _failure_type_for_exception(exc: BaseException) -> str:
    if isinstance(exc, StageContractError):
        return "target_construction"
    if isinstance(exc, PipelineValidationError):
        return "stage_contract"
    return "executor_infrastructure"


__all__ = [
    "StageWorkerRunRequest",
    "StageWorkerStateError",
    "infer_stage_worker_attempt",
    "reconstruct_stage_execution_request",
    "run_stage_worker",
]
