"""Durable one-stage worker execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
import traceback
from typing import cast

from loom.artifacts import ArtifactRef
from loom.serialization._diagnostic_capture import _capture_exception_details
from loom.pipeline.context import ProcessContainmentOwner, StageContext
from loom.pipeline.errors import PipelineValidationError, StageContractError
from loom.pipeline.executors import LocalExecutor
from loom.pipeline.planning import (
    FingerprintStatus,
    PlanAction,
    StageFingerprintRecord,
    StagePlan,
)
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.resources import ResourceValidatorRegistry
from loom.pipeline.specs import (
    OutputSpec,
    StageFactorySpec,
    StageSpec,
)
from loom.pipeline.stage_factory import construct_stage
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    LocalArtifactStore,
)
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

from .errors import PipelineExecutionError, StageReportedFailure
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
from .outputs import validate_stage_outputs

Clock = Callable[[], str]
ArtifactStoreFactory = Callable[[Path], ArtifactStore]


class StageWorkerStateError(PipelineExecutionError):
    """Raised when a worker cannot reconstruct one prepared attempt."""


def execute_resident_stage_worker_request(
    *,
    worker_request: StageWorkerRequest,
    workspace_root: Path,
    process_containment_owner: ProcessContainmentOwner,
    location_resolver: Callable[[object], object] | None = None,
) -> StageWorkerResult:
    """Execute one path-free resident request in an agent-owned workspace.

    This restricted worker boundary has no run-store parameter. The coordinator already prepared and fingerprinted the
    exact stage, while the agent owns only an assignment-local artifact and
    workspace layout. Lifecycle and output authority remain with the caller.
    An optional trusted location resolver materializes typed config/factory
    locations without changing the retained semantic fingerprint.
    """

    if not isinstance(worker_request, StageWorkerRequest):
        raise StageWorkerStateError(
            "resident worker requires one exact StageWorkerRequest"
        )
    root = Path(workspace_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    fingerprint = cast(StageFingerprintRecord, worker_request.fingerprint)
    stage = _stage_spec_from_request(worker_request)
    if location_resolver is not None:
        stage = replace(stage, stage_config=cast(Mapping[str, PlainData], location_resolver(stage.stage_config)),
                        factory=replace(stage.factory, init=cast(Mapping[str, PlainData], location_resolver(stage.factory.init))))
    stage_plan = StagePlan(
        stage_name=worker_request.stage_name,
        action=PlanAction.RUN,
        base_action=PlanAction.RUN,
        fingerprint_status=FingerprintStatus.COMPUTED,
        fingerprint=fingerprint,
        resume_check=None,
        reasons=(),
        bound_inputs={},
        pending_inputs=(),
        reusable_outputs={},
        declared_outputs=fingerprint.payload.declared_outputs,
        upstream_stages=(),
        downstream_stages=(),
        selected_by=(),
        invalidated_by=(),
    )
    artifact_store = LocalArtifactStore(root / "artifacts")
    worker_executor = LocalExecutor(capture_stdout_stderr=True)
    try:
        stage_object = construct_stage(
            factory=stage.factory,
            stage_path="resident_stage",
        )
        context = StageContext(
            run_uri=worker_request.run_uri,
            stage_name=worker_request.stage_name,
            process_containment_owner=process_containment_owner,
            resolved_config=_minimal_resolved_config(stage),
            stage_config=stage.stage_config,
            inputs=worker_request.inputs,
            local_output_dir=artifact_store.local_stage_dir(worker_request.stage_name),
            local_workspace_dir=root / "workspace",
            provenance={},
            metadata={
                "factory_target": stage.factory.target_path,
                "resolved_runtime": dict(worker_request.resolved_runtime),
                "resident_worker_request": True,
            },
            artifact_store=artifact_store,
            output_specs=stage.outputs,
        )
        execution_result = worker_executor.execute(
            StageExecutionRequest(
                run_uri=worker_request.run_uri,
                stage=stage,
                stage_plan=stage_plan,
                stage_object=stage_object,
                context=context,
                inputs=worker_request.inputs,
                fingerprint=fingerprint,
                attempt=worker_request.attempt,
                stdout_path=Path(worker_request.stdout_path),
                stderr_path=Path(worker_request.stderr_path),
                traceback_path=Path(worker_request.traceback_path),
                metadata={"resident_worker_request": True},
                resolved_runtime=_resolved_runtime_for_execution(
                    worker_request,
                    registry=None,
                ),
            )
        )
        if execution_result.status is StageStatus.SUCCEEDED:
            execution_result = replace(
                execution_result,
                outputs=validate_stage_outputs(
                    stage=stage,
                    outputs=execution_result.outputs,
                    artifact_store=artifact_store,
                ),
            )
        return _result_from_execution_result(
            worker_request=worker_request,
            execution_result=execution_result,
        )
    except Exception as exc:
        if isinstance(exc, StageWorkerStateError):
            raise
        return _failed_worker_result_from_exception(
            worker_request=worker_request,
            exc=exc,
            clock=utc_timestamp,
        )


def _stage_spec_from_request(
    request: StageWorkerRequest,
    *,
    registry: ResourceValidatorRegistry | None = None,
) -> StageSpec:
    fingerprint = cast(StageFingerprintRecord, request.fingerprint)
    payload = fingerprint.payload
    resources = request.metadata.get("stage_resources", {})
    if not isinstance(resources, Mapping):
        raise StageWorkerStateError(
            "prepared worker stage_resources metadata must be a mapping"
        )
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
        resources=cast(Mapping[str, PlainData], resources),
        fingerprint_fields=payload.fingerprint_fields,
        validator_registry=registry,
    )


def _resolved_runtime_for_execution(
    request: StageWorkerRequest,
    *,
    registry: ResourceValidatorRegistry | None = None,
) -> ResolvedStageRuntimeOptions:
    executor = request.resolved_runtime.get("executor", request.executor_name)
    if not isinstance(executor, str) or not executor:
        executor = request.executor_name
    resources = request.resolved_runtime.get("resources", {})
    resource_policy = request.resolved_runtime.get("resource_policy", {})
    resource_selection = request.resolved_runtime.get("resource_selection")
    if resource_selection is None:
        raise StageWorkerStateError(
            "worker request resolved runtime lacks resource_selection"
        )
    return ResolvedStageRuntimeOptions(
        stage_id=request.stage_name,
        executor=executor,
        resources=cast(Mapping[str, object], resources),
        resource_policy=cast(Mapping[str, object], resource_policy),
        resource_selection=cast(Mapping[str, object], resource_selection),
        validator_registry=registry,
    )


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
        raise StageWorkerStateError(
            "executor result attempt does not match worker request"
        )
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
        traceback_path=(
            execution_result.traceback_path
            if failure is not None and "domain_failure" in failure.details
            else execution_result.traceback_path or worker_request.traceback_path
        ),
        exit_code=0 if execution_result.status != StageStatus.FAILED else 1,
        executor_metadata={
            "request": worker_request.to_safe_metadata(),
            **execution_result.executor_metadata,
        },
    )


def _failed_worker_result_from_exception(
    *,
    worker_request: StageWorkerRequest,
    exc: BaseException,
    clock: Clock,
) -> StageWorkerResult:
    failed_at = clock()
    reported_failure = exc if isinstance(exc, StageReportedFailure) else None
    if reported_failure is None:
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
        failure_type=(
            "stage_exception"
            if reported_failure is not None
            else _failure_type_for_exception(exc)
        ),
        message=(
            "stage reported a domain failure"
            if reported_failure is not None
            else str(exc) or type(exc).__name__
        ),
        exception_type=(
            "loom.pipeline.execution.StageReportedFailure"
            if reported_failure is not None
            else f"{type(exc).__module__}.{type(exc).__name__}"
        ),
        traceback_path=(
            None if reported_failure is not None else worker_request.traceback_path
        ),
        stdout_path=worker_request.stdout_path,
        stderr_path=worker_request.stderr_path,
        details=(
            {"domain_failure": reported_failure.domain_failure}
            if reported_failure is not None
            else _capture_exception_details(exc)
        ),
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
        traceback_path=(
            None if reported_failure is not None else worker_request.traceback_path
        ),
        exit_code=1,
        executor_metadata={"request": worker_request.to_safe_metadata()},
    )


def _failure_type_for_exception(exc: BaseException) -> str:
    if isinstance(exc, StageContractError):
        return "target_construction"
    if isinstance(exc, PipelineValidationError):
        return "stage_contract"
    return "executor_infrastructure"


__all__ = ["StageWorkerStateError", "execute_resident_stage_worker_request"]
