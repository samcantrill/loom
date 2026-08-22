"""Deterministic pure default evaluators and FIFO-with-safe-bypass policy."""

# ruff: noqa: F403, F405
from __future__ import annotations
from .values import *


def _descriptor(kind: str) -> SchedulingComponentDescriptor:
    return SchedulingComponentDescriptor(
        kind, 1, "1", f"builtin:{kind}:v1", "builtin", (1,)
    )


class TargetConstraintEvaluator:
    descriptor = _descriptor("target")

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: HardConstraintSpec,
    ) -> HardConstraintResult:
        target = candidate.attributes.get("target")
        required = candidate.attributes.get("required_target")
        return HardConstraintResult(
            HardEvaluationState.PASS
            if required is None or target == required
            else HardEvaluationState.REJECT,
            None if required is None or target == required else "target does not match",
        )


class AttributeConstraintEvaluator:
    descriptor = _descriptor("attribute")

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: HardConstraintSpec,
    ) -> HardConstraintResult:
        required = candidate.attributes.get("required_attributes", {})
        if not isinstance(required, dict):
            return HardConstraintResult(
                HardEvaluationState.INDETERMINATE, "invalid attribute rule"
            )
        return HardConstraintResult(
            HardEvaluationState.PASS
            if all(candidate.attributes.get(k) == v for k, v in required.items())
            else HardEvaluationState.REJECT,
            "attribute requirement not met",
        )


class NeutralPreferenceScorer:
    descriptor = _descriptor("neutral")

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: PreferenceSpec,
    ) -> PreferenceResult:
        return PreferenceResult(PreferenceEvaluationState.SCORE, PreferenceScore(0))


class FifoSchedulingPolicy:
    descriptor = _descriptor("fifo_safe_bypass")

    def select(self, context: PolicyContext) -> PolicyDecision:
        if not context.evaluations:
            return PolicyDecision(
                PolicyDecisionState.WAIT, explanation="no complete feasible work"
            )
        selected = min(
            context.evaluations,
            key=lambda item: (
                item.stage_work_id,
                tuple(-value for value in item.preference_vector),
                item.candidate_id,
            ),
        )
        return PolicyDecision(
            PolicyDecisionState.SELECT, selected.stage_work_id, selected.candidate_id
        )
