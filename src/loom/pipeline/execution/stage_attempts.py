"""Parent-side preparation for one durable stage attempt."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.errors import StageContractError
from loom.pipeline.planning import (
    FingerprintContext,
    PlanAction,
    StagePlan,
    build_stage_fingerprint,
)
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.specs import StageSpec
from loom.pipeline.status import StageStatus, StageStatusRecord
from loom.pipeline.stores import LocalRunStorePaths, RunStore
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

from .errors import PipelineExecutionError, PlanExecutionError
from .lifecycle import next_stage_attempt
from .logs import traceback_log_path
from .models import (
    STAGE_WORKER_REQUEST_SCHEMA_VERSION,
    StageWorkerRequest,
    redact_executor_metadata,
)


Clock = Callable[[], str]


def prepare_stage_attempt(
    *,
    run_store: RunStore,
    run_uri: str,
    stage: StageSpec,
    stage_plan: StagePlan,
    produced_outputs: Mapping[str, Mapping[str, ArtifactRef]] | None = None,
    fingerprint_context: FingerprintContext | None = None,
    resolved_runtime: ResolvedStageRuntimeOptions
    | Mapping[str, PlainData]
    | None = None,
    executor_name: str = "local",
    executor_metadata: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
    clock: Clock = utc_timestamp,
) -> StageWorkerRequest:
    """Prepare durable state for one stage attempt without running stage code."""

    if not isinstance(run_store, RunStore):
        raise PipelineExecutionError("prepare_stage_attempt requires RunStore")
    if not isinstance(run_store, LocalRunStorePaths):
        raise PipelineExecutionError(
            "prepare_stage_attempt requires local run-store path helpers"
        )
    if not isinstance(stage, StageSpec):
        raise PlanExecutionError("prepare_stage_attempt.stage must be StageSpec")
    if not isinstance(stage_plan, StagePlan):
        raise PlanExecutionError("prepare_stage_attempt.stage_plan must be StagePlan")
    if stage_plan.stage_name != stage.name:
        raise PlanExecutionError(
            "prepare_stage_attempt.stage_plan.stage_name must match stage.name"
        )
    if stage_plan.action != PlanAction.RUN:
        raise PlanExecutionError(
            f"prepare_stage_attempt requires a RUN stage plan, got {stage_plan.action.value}"
        )
    if not isinstance(executor_name, str) or not executor_name:
        raise PlanExecutionError(
            "prepare_stage_attempt.executor_name must be non-empty"
        )

    attempt = next_stage_attempt(run_store, run_uri, stage.name)
    prepared_at = clock()
    produced = produced_outputs or {}
    inputs = _bind_inputs(stage, stage_plan, produced)
    fingerprint = build_stage_fingerprint(
        stage,
        bound_inputs=inputs,
        fingerprint_context=fingerprint_context or FingerprintContext(),
    )
    request = StageWorkerRequest(
        schema_version=STAGE_WORKER_REQUEST_SCHEMA_VERSION,
        run_uri=run_uri,
        stage_name=stage.name,
        attempt=attempt,
        prepared_at=prepared_at,
        executor_name=executor_name,
        inputs=inputs,
        fingerprint=fingerprint,
        stdout_path=str(run_store.local_stage_log_path(run_uri, stage.name, "stdout")),
        stderr_path=str(run_store.local_stage_log_path(run_uri, stage.name, "stderr")),
        traceback_path=str(
            traceback_log_path(
                run_store=run_store,
                run_uri=run_uri,
                stage_name=stage.name,
            )
        ),
        result_path=str(run_store.local_stage_worker_result_path(run_uri, stage.name)),
        resolved_runtime=_resolved_runtime_metadata(
            resolved_runtime, stage_name=stage.name
        ),
        executor_metadata=redact_executor_metadata(executor_metadata),
        metadata=metadata or {},
    )

    run_store.write_stage_inputs(run_uri, stage.name, inputs, attempt=attempt)
    run_store.write_stage_fingerprint(
        run_uri,
        stage.name,
        fingerprint.to_dict(),
        attempt=attempt,
    )
    run_store.prepare_stage_workspace(run_uri, stage.name)
    run_store.write_stage_worker_request(
        run_uri,
        stage.name,
        request.to_dict(),
        attempt=attempt,
    )
    run_store.write_stage_status(
        run_uri,
        stage.name,
        StageStatusRecord(
            run_uri=run_uri,
            stage_name=stage.name,
            status=StageStatus.PENDING,
            attempt=attempt,
            updated_at=prepared_at,
            owner={"component": "prepare_stage_attempt", "executor": executor_name},
            metadata={
                "prepared": True,
                "action": PlanAction.RUN.value,
                "worker_request": str(
                    run_store.local_stage_worker_request_path(run_uri, stage.name)
                ),
                **dict(metadata or {}),
            },
        ),
    )
    return request


def _bind_inputs(
    stage: StageSpec,
    stage_plan: StagePlan,
    produced_outputs: Mapping[str, Mapping[str, ArtifactRef]],
) -> dict[str, ArtifactRef]:
    inputs: dict[str, ArtifactRef] = {
        name: bound.artifact_ref for name, bound in stage_plan.bound_inputs.items()
    }
    for pending in stage_plan.pending_inputs:
        upstream = produced_outputs.get(pending.source_stage)
        if upstream is None or pending.source_output not in upstream:
            raise PlanExecutionError(
                f"Cannot bind input {stage.name}.{pending.input_name} from "
                f"{pending.source_stage}.{pending.source_output}"
            )
        inputs[pending.input_name] = upstream[pending.source_output]
    expected = set(stage.inputs)
    if set(inputs) != expected:
        missing = expected - set(inputs)
        extra = set(inputs) - expected
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            parts.append(f"extra {', '.join(sorted(extra))}")
        raise PlanExecutionError(
            f"Input binding mismatch for stage {stage.name}: {'; '.join(parts)}"
        )
    return inputs


def _resolved_runtime_metadata(
    value: ResolvedStageRuntimeOptions | Mapping[str, PlainData] | None,
    *,
    stage_name: str,
) -> Mapping[str, PlainData]:
    if value is None:
        return ResolvedStageRuntimeOptions(stage_id=stage_name).to_safe_metadata()
    if isinstance(value, ResolvedStageRuntimeOptions):
        return value.to_safe_metadata()
    if not isinstance(value, Mapping):
        raise StageContractError("resolved_runtime must be resolved runtime metadata")
    return dict(value)


__all__ = ["prepare_stage_attempt"]
