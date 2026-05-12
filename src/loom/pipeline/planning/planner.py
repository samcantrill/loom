"""Topological execution planning and downstream invalidation."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.graph import build_stage_graph, downstream_of, upstream_of
from loom.pipeline.graph.bindings import ResolvedInputBinding, resolve_input_bindings
from loom.pipeline.specs import OutputSpec, PipelineSpec, StageSpec
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.errors import StoreError
from loom.pipeline.stores.run_store import LegacyRunStore
from loom.serialization import PlainData

from .actions import decide_stage_action
from .errors import PlanPersistenceError
from .fingerprints import build_stage_fingerprint
from .models import (
    PLAN_SCHEMA_VERSION,
    BoundInput,
    ExecutionPlan,
    FingerprintContext,
    FingerprintStatus,
    PendingInput,
    PlanAction,
    PlanReason,
    PlanReasonCode,
    PlanSelectors,
    ResumeCheck,
    ResumeOptions,
    StageFingerprintRecord,
    StagePlan,
    summary_for,
)
from .invalidation import evaluate_input_invalidation
from .resume import check_stage_resume
from .selectors import Selection, normalize_selectors, selector_reason


def plan_pipeline(
    spec: PipelineSpec,
    *,
    run_uri: str,
    run_store: LegacyRunStore,
    artifact_store: ArtifactStore,
    selectors: PlanSelectors | None = None,
    resume: ResumeOptions | None = None,
    fingerprint_context: FingerprintContext | None = None,
    persist: bool = False,
) -> ExecutionPlan:
    """Compute a deterministic execution plan for a pipeline spec."""

    graph = build_stage_graph(spec)
    selection = normalize_selectors(selectors, spec=spec, graph=graph)
    resume_options = resume or ResumeOptions()
    context = fingerprint_context or FingerprintContext()
    bindings = resolve_input_bindings(spec)
    plans: dict[str, StagePlan] = {}

    for stage_name in selection.stage_order:
        stage = spec.get_stage(stage_name)
        plans[stage_name] = _plan_stage(
            spec=spec,
            stage=stage,
            run_uri=run_uri,
            run_store=run_store,
            artifact_store=artifact_store,
            selection=selection,
            resume=resume_options,
            fingerprint_context=context,
            graph_upstream=tuple(
                _ordered(upstream_of(graph, stage_name), selection.stage_order)
            ),
            graph_downstream=tuple(
                _ordered(downstream_of(graph, stage_name), selection.stage_order)
            ),
            bindings=bindings[stage_name],
            prior_plans=plans,
        )

    ordered_plans = tuple(plans[name] for name in selection.stage_order)
    plan = ExecutionPlan(
        schema_version=PLAN_SCHEMA_VERSION,
        run_uri=run_uri,
        pipeline_name=spec.name,
        selectors=selection.selectors,
        resume=resume_options,
        fingerprint_context=context,
        stage_order=selection.stage_order,
        stage_plans=ordered_plans,
        reasons=(),
        summary=summary_for(ordered_plans),
    )
    if persist:
        _persist_plan(run_store, run_uri, plan)
    return plan


def _plan_stage(
    *,
    spec: PipelineSpec,
    stage: StageSpec,
    run_uri: str,
    run_store: LegacyRunStore,
    artifact_store: ArtifactStore,
    selection: Selection,
    resume: ResumeOptions,
    fingerprint_context: FingerprintContext,
    graph_upstream: tuple[str, ...],
    graph_downstream: tuple[str, ...],
    bindings: Mapping[str, ResolvedInputBinding],
    prior_plans: Mapping[str, StagePlan],
) -> StagePlan:
    selected_by = selection.reason_for_selection(stage.name)
    selector_reasons = tuple(selector_reason(code, stage.name) for code in selected_by)

    if (
        stage.name in selection.skipped_stages
        or stage.name in selection.outside_only_stages
    ):
        return _stage_plan(
            stage=stage,
            action=PlanAction.SKIP,
            base_action=PlanAction.SKIP,
            fingerprint_status=FingerprintStatus.PENDING_INPUTS,
            fingerprint=None,
            resume_check=None,
            reasons=selector_reasons,
            bound_inputs={},
            pending_inputs=(),
            reusable_outputs={},
            upstream=graph_upstream,
            downstream=graph_downstream,
            selected_by=selected_by,
            invalidated_by=(),
        )

    invalidation = evaluate_input_invalidation(
        stage=stage,
        bindings=bindings,
        prior_plans=prior_plans,
    )
    bound_inputs = invalidation.bound_inputs
    pending_inputs = invalidation.pending_inputs
    invalidated_by = invalidation.invalidated_by
    eligible_to_run = selection.is_eligible(stage.name)
    if (
        invalidation.blocking_reasons
        or invalidation.invalidating_reasons
        or pending_inputs
    ):
        decision = decide_stage_action(
            selector_reasons=selector_reasons,
            eligible_to_run=eligible_to_run,
            force=(
                stage.name in selection.forced_stages
                or selection.selectors.from_stage == stage.name
            ),
            invalidation=invalidation,
        )
    else:
        current_fingerprint = build_stage_fingerprint(
            stage,
            bound_inputs={
                name: bound.artifact_ref for name, bound in bound_inputs.items()
            },
            fingerprint_context=fingerprint_context,
        )
        direct = check_stage_resume(
            stage,
            run_uri=run_uri,
            run_store=run_store,
            artifact_store=artifact_store,
            current_fingerprint=current_fingerprint,
            resume=resume,
            eligible_to_run=eligible_to_run,
        )
        decision = decide_stage_action(
            selector_reasons=selector_reasons,
            eligible_to_run=eligible_to_run,
            force=(
                stage.name in selection.forced_stages
                or selection.selectors.from_stage == stage.name
            ),
            invalidation=invalidation,
            direct_result=direct,
            fingerprint=current_fingerprint,
        )

    if decision.fingerprint_status == FingerprintStatus.PENDING_INPUTS:
        return _stage_plan(
            stage=stage,
            action=decision.action,
            base_action=decision.base_action,
            fingerprint_status=decision.fingerprint_status,
            fingerprint=decision.fingerprint,
            resume_check=decision.resume_check,
            reasons=decision.reasons,
            bound_inputs=bound_inputs,
            pending_inputs=tuple(pending_inputs),
            reusable_outputs=decision.reusable_outputs,
            upstream=graph_upstream,
            downstream=graph_downstream,
            selected_by=selected_by,
            invalidated_by=tuple(invalidated_by),
        )
    return _stage_plan(
        stage=stage,
        action=decision.action,
        base_action=decision.base_action,
        fingerprint_status=decision.fingerprint_status,
        fingerprint=decision.fingerprint,
        resume_check=decision.resume_check,
        reasons=decision.reasons,
        bound_inputs=bound_inputs,
        pending_inputs=(),
        reusable_outputs=decision.reusable_outputs,
        upstream=graph_upstream,
        downstream=graph_downstream,
        selected_by=selected_by,
        invalidated_by=(),
    )


def _stage_plan(
    *,
    stage: StageSpec,
    action: PlanAction,
    base_action: PlanAction,
    fingerprint_status: FingerprintStatus,
    fingerprint: StageFingerprintRecord | None,
    resume_check: ResumeCheck | None,
    reasons: tuple[PlanReason, ...],
    bound_inputs: Mapping[str, BoundInput],
    pending_inputs: tuple[PendingInput, ...],
    reusable_outputs: Mapping[str, ArtifactRef],
    upstream: tuple[str, ...],
    downstream: tuple[str, ...],
    selected_by: tuple[PlanReasonCode, ...],
    invalidated_by: tuple[PlanReason, ...],
) -> StagePlan:
    return StagePlan(
        stage_name=stage.name,
        action=action,
        base_action=base_action,
        fingerprint_status=fingerprint_status,
        fingerprint=fingerprint,
        resume_check=resume_check,
        reasons=reasons,
        bound_inputs=bound_inputs,
        pending_inputs=pending_inputs,
        reusable_outputs=reusable_outputs,
        declared_outputs={
            name: _output_spec_to_dict(output) for name, output in stage.outputs.items()
        },
        upstream_stages=upstream,
        downstream_stages=downstream,
        selected_by=selected_by,
        invalidated_by=invalidated_by,
    )


def _output_spec_to_dict(output: OutputSpec) -> dict[str, PlainData]:
    return {
        "artifact_type": output.artifact_type,
        "codec_key": output.codec_key,
        "schema_version": output.schema_version,
        "metadata": dict(output.metadata),
    }


def _persist_plan(
    run_store: LegacyRunStore, run_uri: str, plan: ExecutionPlan
) -> None:
    try:
        run_store.write_plan(run_uri, plan.to_dict())
        persisted = run_store.read_plan(run_uri)
        if persisted is None:
            raise PlanPersistenceError("plan persistence returned no plan document")
        ExecutionPlan.from_dict(persisted)
    except PlanPersistenceError:
        raise
    except StoreError as exc:
        raise PlanPersistenceError(
            f"could not persist execution plan for run {run_uri!r}: {exc}"
        ) from exc
    except Exception as exc:
        raise PlanPersistenceError(
            f"persisted execution plan for run {run_uri!r} is invalid: {exc}"
        ) from exc


def _ordered(values: set[str], order: tuple[str, ...]) -> list[str]:
    return [stage for stage in order if stage in values]


__all__ = ["plan_pipeline"]
