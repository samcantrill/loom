"""Parent-side preparation for one durable stage attempt."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.planning import (
    FingerprintContext,
    PlanAction,
    StagePlan,
    build_stage_fingerprint,
)
from loom.pipeline.reliability import StageAttemptTransactionState
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.specs import StageSpec
from loom.pipeline.status import RunStatus, StageStatus, StageStatusRecord
from loom.pipeline.stores import (
    LocalRunStorePaths, RunConfigStore, RunPreparedRunStore, RunReliabilityStore,
    StageStateStore, StageWorkspaceStore,
)
from loom.pipeline.stores.read_models import StageAttempt
from loom.pipeline.stores.input_lineage import AttemptInputBinding, binding_evidence, capture_bindings
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
from .reliability import record_stage_reliability_transition


Clock = Callable[[], str]


def prepare_stage_attempt(
    *,
    stage_state: StageStateStore,
    stage_workspaces: StageWorkspaceStore,
    local_paths: LocalRunStorePaths,
    reliability: RunReliabilityStore,
    prepared_runs: RunPreparedRunStore,
    config: RunConfigStore,
    run_status: RunStatus,
    run_uri: str,
    stage: StageSpec,
    stage_plan: StagePlan,
    produced_outputs: Mapping[str, Mapping[str, ArtifactRef]] | None = None,
    input_bindings: tuple[AttemptInputBinding, ...] | None = None,
    authority_attempt: StageAttempt | None = None,
    fingerprint_context: FingerprintContext | None = None,
    resolved_runtime: ResolvedStageRuntimeOptions
    | Mapping[str, PlainData]
    | None = None,
    executor_name: str = "local",
    executor_metadata: Mapping[str, PlainData] | None = None,
    metadata: Mapping[str, PlainData] | None = None,
    clock: Clock = utc_timestamp,
) -> StageWorkerRequest:
    """Prepare durable request evidence without running stage code.

    Managed callers provide the admitted ``authority_attempt``. Its positive
    attempt number is preserved and no lifecycle projection is written. Standalone
    callers allocate from their explicit stage-state owner. ``run_status`` comes
    from the caller's admitted authority or standalone lifecycle context.
    """

    from loom.pipeline._project_contracts import reject_overrides, worker_contract_metadata

    reject_overrides(metadata)
    for name, service, protocol in (
        ("stage_state", stage_state, StageStateStore),
        ("stage_workspaces", stage_workspaces, StageWorkspaceStore),
        ("local_paths", local_paths, LocalRunStorePaths),
        ("reliability", reliability, RunReliabilityStore),
        ("prepared_runs", prepared_runs, RunPreparedRunStore),
        ("config", config, RunConfigStore),
    ):
        if not isinstance(service, protocol):
            raise PipelineExecutionError(f"prepare_stage_attempt requires {name}")
    if not isinstance(run_status, RunStatus):
        raise PipelineExecutionError("prepare_stage_attempt requires run_status")
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

    if authority_attempt is not None:
        if authority_attempt.run_uri != run_uri or authority_attempt.stage_name != stage.name:
            raise PlanExecutionError("prepared attempt differs from authority identity")
        attempt = authority_attempt.attempt
    else:
        attempt = next_stage_attempt(stage_state, run_uri, stage.name)
    prepared_at = clock()
    produced = produced_outputs or {}
    inputs = _bind_inputs(stage, stage_plan, produced)
    if input_bindings is not None:
        if inputs != {b.input_name: b.artifact for b in input_bindings}:
            raise PlanExecutionError("worker inputs differ from retained attempt bindings")
    else:
        # Standalone preparation retains external refs without inventing a managed
        # producer. Managed preparation supplies the authoritative receipt.
        from dataclasses import replace
        from loom.pipeline.planning.models import BoundInput

        resolved = replace(stage_plan, pending_inputs=(), bound_inputs={
            port.input_name: BoundInput(port.input_name, port.source_stage, port.source_output, inputs[port.input_name])
            for port in (*stage_plan.bound_inputs.values(), *stage_plan.pending_inputs)
        })
        input_bindings = capture_bindings(resolved, {})
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
        stdout_path=str(local_paths.local_stage_log_path(run_uri, stage.name, "stdout")),
        stderr_path=str(local_paths.local_stage_log_path(run_uri, stage.name, "stderr")),
        traceback_path=str(
            traceback_log_path(
                run_store=local_paths,
                run_uri=run_uri,
                stage_name=stage.name,
            )
        ),
        result_path=str(local_paths.local_stage_worker_result_path(run_uri, stage.name)),
        resolved_runtime=_resolved_runtime_metadata(
            resolved_runtime, stage_name=stage.name
        ),
        executor_metadata=redact_executor_metadata(executor_metadata),
        metadata={**dict(metadata or {}), **worker_contract_metadata(prepared_runs, run_uri, stage,
        config=config,
        local_paths=local_paths),
                  "attempt_input_bindings": [binding.to_dict() for binding in input_bindings],
                  "attempt_input_evidence": binding_evidence(input_bindings)},
    )

    stage_state.write_stage_inputs(run_uri, stage.name, inputs, attempt=attempt)
    stage_state.write_stage_fingerprint(
        run_uri,
        stage.name,
        fingerprint.to_dict(),
        attempt=attempt,
    )
    stage_workspaces.prepare_stage_workspace(run_uri, stage.name)
    stage_state.write_stage_worker_request(
        run_uri,
        stage.name,
        request.to_dict(),
        attempt=attempt,
    )
    if authority_attempt is None:
        stage_state.write_stage_status(
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
                        local_paths.local_stage_worker_request_path(run_uri, stage.name)
                    ),
                    **dict(metadata or {}),
                },
            ),
        )
    record_stage_reliability_transition(
        reliability,
        run_status=run_status, run_uri=run_uri,
        stage_name=stage.name,
        attempt=attempt,
        state=StageAttemptTransactionState.PREPARED,
        stage_status=StageStatus.PENDING,
        recorded_at=prepared_at,
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
        return (
            ResolvedStageRuntimeOptions(stage_id=stage_name)
            .for_execution()
            ._to_worker_metadata()
        )
    if isinstance(value, ResolvedStageRuntimeOptions):
        return value.for_execution()._to_worker_metadata()
    if not isinstance(value, Mapping):
        raise PlanExecutionError("resolved_runtime must be resolved runtime metadata")
    return dict(value)


__all__ = ["prepare_stage_attempt"]
