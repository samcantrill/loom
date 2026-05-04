"""Planner-owned input binding and upstream invalidation policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from loom.pipeline.graph.bindings import ResolvedInputBinding
from loom.pipeline.specs import StageSpec

from .models import (
    BoundInput,
    PlanAction,
    PlanReason,
    PlanReasonCode,
    PendingInput,
    StagePlan,
)


@dataclass(frozen=True, slots=True)
class InputInvalidationResult:
    bound_inputs: Mapping[str, BoundInput]
    pending_inputs: tuple[PendingInput, ...]
    invalidated_by: tuple[PlanReason, ...]

    @property
    def blocking_reasons(self) -> tuple[PlanReason, ...]:
        return _filter_reasons(
            self.invalidated_by,
            {
                PlanReasonCode.UPSTREAM_SKIPPED,
                PlanReasonCode.UPSTREAM_BLOCKED,
                PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT,
            },
        )

    @property
    def invalidating_reasons(self) -> tuple[PlanReason, ...]:
        return _filter_reasons(
            self.invalidated_by,
            {
                PlanReasonCode.UPSTREAM_WILL_RUN,
                PlanReasonCode.UPSTREAM_STALE,
                PlanReasonCode.PENDING_UPSTREAM_INPUT,
            },
        )


def evaluate_input_invalidation(
    *,
    stage: StageSpec,
    bindings: Mapping[str, ResolvedInputBinding],
    prior_plans: Mapping[str, StagePlan],
) -> InputInvalidationResult:
    bound_inputs: dict[str, BoundInput] = {}
    pending_inputs: list[PendingInput] = []
    invalidated_by: list[PlanReason] = []

    for input_name, binding in bindings.items():
        source_plan = prior_plans[binding.source_stage_id]
        source_output = binding.source_output_name
        if (
            source_plan.action == PlanAction.REUSE
            and source_output in source_plan.reusable_outputs
        ):
            bound_inputs[input_name] = BoundInput(
                input_name=input_name,
                source_stage=source_plan.stage_name,
                source_output=source_output,
                artifact_ref=source_plan.reusable_outputs[source_output],
            )
            continue

        reason = _upstream_input_reason(
            stage_name=stage.name,
            input_name=input_name,
            source_plan=source_plan,
            source_stage=binding.source_stage_id,
            source_output=source_output,
        )
        pending_inputs.append(
            PendingInput(
                input_name=input_name,
                source_stage=binding.source_stage_id,
                source_output=source_output,
                reason=reason,
            ),
        )
        invalidated_by.append(reason)

    for dependency in stage.dependencies:
        if dependency not in prior_plans:
            continue
        source_plan = prior_plans[dependency]
        if source_plan.action == PlanAction.REUSE:
            continue
        invalidated_by.append(
            _upstream_reason(
                stage_name=stage.name,
                input_name=None,
                upstream_stage=dependency,
                source_output=None,
                source_action=source_plan.action,
            ),
        )

    return InputInvalidationResult(
        bound_inputs=bound_inputs,
        pending_inputs=tuple(pending_inputs),
        invalidated_by=tuple(invalidated_by),
    )


def _upstream_reason(
    *,
    stage_name: str,
    input_name: str | None,
    upstream_stage: str,
    source_output: str | None,
    source_action: PlanAction,
) -> PlanReason:
    code = {
        PlanAction.RUN: PlanReasonCode.UPSTREAM_WILL_RUN,
        PlanAction.STALE: PlanReasonCode.UPSTREAM_STALE,
        PlanAction.SKIP: PlanReasonCode.UPSTREAM_SKIPPED,
        PlanAction.BLOCKED: PlanReasonCode.UPSTREAM_BLOCKED,
        PlanAction.REUSE: PlanReasonCode.PENDING_UPSTREAM_INPUT,
    }[source_action]
    return PlanReason(
        code=code,
        message=f"upstream stage {upstream_stage!r} action is {source_action.value}",
        stage_name=stage_name,
        upstream_stage=upstream_stage,
        input_name=input_name,
        output_name=source_output,
    )


def _upstream_input_reason(
    *,
    stage_name: str,
    input_name: str,
    source_plan: StagePlan,
    source_stage: str,
    source_output: str,
) -> PlanReason:
    if _is_unavailable_reuse_provider(source_plan):
        return PlanReason(
            code=PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT,
            message=f"upstream input {source_stage}.{source_output} is not reusable",
            stage_name=stage_name,
            upstream_stage=source_stage,
            input_name=input_name,
            output_name=source_output,
        )
    return _upstream_reason(
        stage_name=stage_name,
        input_name=input_name,
        upstream_stage=source_stage,
        source_output=source_output,
        source_action=source_plan.action,
    )


def _is_unavailable_reuse_provider(source_plan: StagePlan) -> bool:
    return (
        source_plan.action == PlanAction.BLOCKED
        and source_plan.resume_check is not None
        and source_plan.base_action in {PlanAction.RUN, PlanAction.STALE}
    )


def _filter_reasons(
    reasons: Iterable[PlanReason],
    reason_codes: set[PlanReasonCode],
) -> tuple[PlanReason, ...]:
    return tuple(reason for reason in reasons if reason.code in reason_codes)


def unique_reasons(reasons: Iterable[PlanReason]) -> tuple[PlanReason, ...]:
    seen: set[tuple[object, ...]] = set()
    unique: list[PlanReason] = []
    for reason in reasons:
        key = (
            reason.code,
            reason.message,
            reason.stage_name,
            reason.upstream_stage,
            reason.input_name,
            reason.output_name,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(reason)
    return tuple(unique)


__all__ = [
    "InputInvalidationResult",
    "evaluate_input_invalidation",
    "unique_reasons",
]
