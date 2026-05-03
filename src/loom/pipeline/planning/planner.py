"""Topological execution planning and downstream invalidation."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.graph import build_stage_graph, downstream_of, upstream_of
from loom.pipeline.graph.bindings import resolve_input_bindings
from loom.pipeline.specs import OutputSpec, PipelineSpec, StageSpec
from loom.pipeline.stores.artifact_store import ArtifactStore
from loom.pipeline.stores.errors import StoreError
from loom.pipeline.stores.run_store import RunStore
from loom.serialization import PlainData

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
    ResumeOptions,
    StageFingerprintRecord,
    StagePlan,
    summary_for,
)
from .resume import check_stage_resume
from .selectors import Selection, normalize_selectors, selector_reason


def plan_pipeline(
    spec: PipelineSpec,
    *,
    run_id: str,
    run_store: RunStore,
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
            run_id=run_id,
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
        run_id=run_id,
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
        _persist_plan(run_store, run_id, plan)
    return plan


def _plan_stage(
    *,
    spec: PipelineSpec,
    stage: StageSpec,
    run_id: str,
    run_store: RunStore,
    artifact_store: ArtifactStore,
    selection: Selection,
    resume: ResumeOptions,
    fingerprint_context: FingerprintContext,
    graph_upstream: tuple[str, ...],
    graph_downstream: tuple[str, ...],
    bindings: Mapping[str, object],
    prior_plans: Mapping[str, StagePlan],
) -> StagePlan:
    selected_by = selection.reason_for_selection(stage.name)
    selector_reasons = tuple(selector_reason(code, stage.name) for code in selected_by)

    if (
        stage.name in selection.skipped_stages
        or stage.name in selection.outside_only_stages
    ):
        code = (
            PlanReasonCode.SKIPPED_BY_SELECTOR
            if stage.name in selection.skipped_stages
            else PlanReasonCode.OUTSIDE_ONLY_SELECTION
        )
        reason = selector_reason(code, stage.name)
        return _stage_plan(
            stage=stage,
            action=PlanAction.SKIP,
            base_action=PlanAction.SKIP,
            fingerprint_status=FingerprintStatus.PENDING_INPUTS,
            fingerprint=None,
            resume_check=None,
            reasons=(*selector_reasons, reason),
            bound_inputs={},
            pending_inputs=(),
            reusable_outputs={},
            upstream=graph_upstream,
            downstream=graph_downstream,
            selected_by=selected_by,
            invalidated_by=(),
        )

    bound_inputs, pending_inputs, invalidated_by = _bind_inputs_and_invalidation(
        stage=stage,
        bindings=bindings,
        prior_plans=prior_plans,
    )
    blocking_reasons = [
        pending.reason
        for pending in pending_inputs
        if pending.reason.code
        in {
            PlanReasonCode.UPSTREAM_SKIPPED,
            PlanReasonCode.UPSTREAM_BLOCKED,
            PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT,
        }
    ]
    invalidating_reasons = [
        reason
        for reason in invalidated_by
        if reason.code
        in {
            PlanReasonCode.UPSTREAM_WILL_RUN,
            PlanReasonCode.UPSTREAM_STALE,
            PlanReasonCode.PENDING_UPSTREAM_INPUT,
        }
    ]

    eligible = selection.is_eligible(stage.name)
    force = stage.name in selection.forced_stages

    if blocking_reasons or (pending_inputs and not eligible):
        reasons = (
            *selector_reasons,
            *tuple(pending.reason for pending in pending_inputs),
            *tuple(invalidated_by),
        )
        return _stage_plan(
            stage=stage,
            action=PlanAction.BLOCKED,
            base_action=PlanAction.BLOCKED,
            fingerprint_status=FingerprintStatus.PENDING_INPUTS,
            fingerprint=None,
            resume_check=None,
            reasons=reasons,
            bound_inputs=bound_inputs,
            pending_inputs=tuple(pending_inputs),
            reusable_outputs={},
            upstream=graph_upstream,
            downstream=graph_downstream,
            selected_by=selected_by,
            invalidated_by=tuple(invalidated_by),
        )

    if pending_inputs or invalidating_reasons:
        action = PlanAction.RUN if eligible else PlanAction.BLOCKED
        reasons = (
            *selector_reasons,
            *tuple(pending.reason for pending in pending_inputs),
            *tuple(invalidated_by),
        )
        return _stage_plan(
            stage=stage,
            action=action,
            base_action=PlanAction.RUN if eligible else PlanAction.BLOCKED,
            fingerprint_status=FingerprintStatus.PENDING_INPUTS,
            fingerprint=None,
            resume_check=None,
            reasons=reasons,
            bound_inputs=bound_inputs,
            pending_inputs=tuple(pending_inputs),
            reusable_outputs={},
            upstream=graph_upstream,
            downstream=graph_downstream,
            selected_by=selected_by,
            invalidated_by=tuple(invalidated_by),
        )

    current_fingerprint = build_stage_fingerprint(
        stage,
        bound_inputs={name: bound.artifact_ref for name, bound in bound_inputs.items()},
        fingerprint_context=fingerprint_context,
    )
    direct = check_stage_resume(
        stage,
        run_id=run_id,
        run_store=run_store,
        artifact_store=artifact_store,
        current_fingerprint=current_fingerprint,
        resume=resume,
        eligible_to_run=eligible,
    )
    action = direct.final_action
    reasons = [*selector_reasons, *direct.check.reasons]
    reusable_outputs = direct.check.outputs if action == PlanAction.REUSE else {}
    if force:
        action = PlanAction.RUN
        reusable_outputs = {}
        reasons.append(
            PlanReason(
                code=PlanReasonCode.FORCED_BY_SELECTOR,
                message="stage forced by selector",
                stage_name=stage.name,
            ),
        )
    return _stage_plan(
        stage=stage,
        action=action,
        base_action=direct.base_action,
        fingerprint_status=FingerprintStatus.COMPUTED,
        fingerprint=current_fingerprint,
        resume_check=direct.check,
        reasons=tuple(reasons),
        bound_inputs=bound_inputs,
        pending_inputs=(),
        reusable_outputs=reusable_outputs,
        upstream=graph_upstream,
        downstream=graph_downstream,
        selected_by=selected_by,
        invalidated_by=(),
    )


def _bind_inputs_and_invalidation(
    *,
    stage: StageSpec,
    bindings: Mapping[str, object],
    prior_plans: Mapping[str, StagePlan],
) -> tuple[dict[str, BoundInput], list[PendingInput], list[PlanReason]]:
    bound: dict[str, BoundInput] = {}
    pending: list[PendingInput] = []
    invalidated: list[PlanReason] = []
    for input_name, binding in bindings.items():
        source_stage = binding.source_stage_id  # type: ignore[attr-defined]
        source_output = binding.source_output_name  # type: ignore[attr-defined]
        source_plan = prior_plans[source_stage]
        if (
            source_plan.action == PlanAction.REUSE
            and source_output in source_plan.reusable_outputs
        ):
            bound[input_name] = BoundInput(
                input_name=input_name,
                source_stage=source_stage,
                source_output=source_output,
                artifact_ref=source_plan.reusable_outputs[source_output],
            )
            continue
        reason = _upstream_reason(
            stage.name, input_name, source_stage, source_output, source_plan.action
        )
        pending.append(
            PendingInput(
                input_name=input_name,
                source_stage=source_stage,
                source_output=source_output,
                reason=reason,
            ),
        )
        invalidated.append(reason)

    for dependency in stage.dependencies:
        if dependency not in prior_plans:
            continue
        source_plan = prior_plans[dependency]
        if source_plan.action == PlanAction.REUSE:
            continue
        invalidated.append(
            _upstream_reason(stage.name, None, dependency, None, source_plan.action)
        )
    return bound, pending, invalidated


def _upstream_reason(
    stage_name: str,
    input_name: str | None,
    upstream_stage: str,
    source_output: str | None,
    upstream_action: PlanAction,
) -> PlanReason:
    code = {
        PlanAction.RUN: PlanReasonCode.UPSTREAM_WILL_RUN,
        PlanAction.STALE: PlanReasonCode.UPSTREAM_STALE,
        PlanAction.SKIP: PlanReasonCode.UPSTREAM_SKIPPED,
        PlanAction.BLOCKED: PlanReasonCode.UPSTREAM_BLOCKED,
        PlanAction.REUSE: PlanReasonCode.PENDING_UPSTREAM_INPUT,
    }[upstream_action]
    return PlanReason(
        code=code,
        message=f"upstream stage {upstream_stage!r} action is {upstream_action.value}",
        stage_name=stage_name,
        upstream_stage=upstream_stage,
        input_name=input_name,
        output_name=source_output,
    )


def _stage_plan(
    *,
    stage: StageSpec,
    action: PlanAction,
    base_action: PlanAction,
    fingerprint_status: FingerprintStatus,
    fingerprint: StageFingerprintRecord | None,
    resume_check: object,
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
        resume_check=resume_check,  # type: ignore[arg-type]
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


def _persist_plan(run_store: RunStore, run_id: str, plan: ExecutionPlan) -> None:
    try:
        run_store.write_plan(run_id, plan.to_dict())
        persisted = run_store.read_plan(run_id)
        if persisted is None:
            raise PlanPersistenceError("plan persistence returned no plan document")
        ExecutionPlan.from_dict(persisted)
    except PlanPersistenceError:
        raise
    except StoreError as exc:
        raise PlanPersistenceError(
            f"could not persist execution plan for run {run_id!r}: {exc}"
        ) from exc
    except Exception as exc:
        raise PlanPersistenceError(
            f"persisted execution plan for run {run_id!r} is invalid: {exc}"
        ) from exc


def _ordered(values: set[str], order: tuple[str, ...]) -> list[str]:
    return [stage for stage in order if stage in values]


__all__ = ["plan_pipeline"]
