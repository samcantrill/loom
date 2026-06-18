"""Planner action-decision policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from loom.artifacts import ArtifactRef

from .invalidation import InputInvalidationResult, unique_reasons
from .models import (
    FingerprintStatus,
    PlanAction,
    PlanReason,
    ResumeCheck,
    StageFingerprintRecord,
)
from .resume import DirectResumeResult


@dataclass(frozen=True, slots=True)
class StageActionDecision:
    action: PlanAction
    base_action: PlanAction
    fingerprint_status: FingerprintStatus
    fingerprint: StageFingerprintRecord | None
    resume_check: ResumeCheck | None
    reasons: tuple[PlanReason, ...]
    reusable_outputs: Mapping[str, ArtifactRef]


def decide_stage_action(
    *,
    selector_reasons: Sequence[PlanReason],
    eligible_to_run: bool,
    force: bool,
    invalidation: InputInvalidationResult,
    direct_result: DirectResumeResult | None = None,
    fingerprint: StageFingerprintRecord | None = None,
) -> StageActionDecision:
    reasons = (
        *selector_reasons,
        *(input_.reason for input_ in invalidation.pending_inputs),
        *invalidation.invalidated_by,
    )
    if invalidation.blocking_reasons or (invalidation.pending_inputs and not eligible_to_run):
        return StageActionDecision(
            action=PlanAction.BLOCKED,
            base_action=PlanAction.BLOCKED,
            fingerprint_status=FingerprintStatus.PENDING_INPUTS,
            fingerprint=None,
            resume_check=None,
            reasons=unique_reasons(reasons),
            reusable_outputs={},
        )

    if invalidation.invalidating_reasons or invalidation.pending_inputs:
        return StageActionDecision(
            action=PlanAction.RUN if eligible_to_run else PlanAction.BLOCKED,
            base_action=PlanAction.RUN if eligible_to_run else PlanAction.BLOCKED,
            fingerprint_status=FingerprintStatus.PENDING_INPUTS,
            fingerprint=None,
            resume_check=None,
            reasons=unique_reasons(reasons),
            reusable_outputs={},
        )

    if direct_result is None:
        raise ValueError("direct_result is required when no input invalidation remains")
    if fingerprint is None:
        raise ValueError("fingerprint is required when evaluating resume decision")

    action = direct_result.final_action
    base_action = direct_result.base_action
    reusable_outputs: Mapping[str, ArtifactRef] = (
        direct_result.check.outputs if action == PlanAction.REUSE else {}
    )
    if force:
        action = PlanAction.RUN
        reusable_outputs = {}

    return StageActionDecision(
        action=action,
        base_action=base_action,
        fingerprint_status=FingerprintStatus.COMPUTED,
        fingerprint=fingerprint,
        resume_check=direct_result.check,
        reasons=unique_reasons((*selector_reasons, *direct_result.check.reasons)),
        reusable_outputs=reusable_outputs,
    )


__all__ = ["StageActionDecision", "decide_stage_action"]
