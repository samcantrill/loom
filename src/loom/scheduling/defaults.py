"""Deterministic hard rules, neutral scoring, and FIFO safe-bypass policy."""

from __future__ import annotations

from collections.abc import Mapping

from .values import (
    Candidate,
    HardConstraintResult,
    HardConstraintSpec,
    HardEvaluationState,
    PolicyContext,
    PolicyDecision,
    PolicyDecisionState,
    PreferenceEvaluationState,
    PreferenceResult,
    PreferenceScore,
    PreferenceSpec,
    ResourceClaim,
    SchedulingComponentDescriptor,
    WorkItem,
    WorkSearchState,
)


def _descriptor(kind: str) -> SchedulingComponentDescriptor:
    return SchedulingComponentDescriptor(
        kind=kind,
        contract_version=1,
        implementation_version="1",
        implementation_fingerprint=f"builtin:{kind}:v1",
        configuration_fingerprint="builtin",
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
        del work, claims
        required = spec.data.get("target")
        if not isinstance(required, str) or not required:
            return HardConstraintResult(
                HardEvaluationState.INDETERMINATE,
                "target constraint requires non-empty data.target",
            )
        if candidate.attributes.get("target") == required:
            return HardConstraintResult(HardEvaluationState.PASS)
        return HardConstraintResult(
            HardEvaluationState.REJECT, "candidate target does not match"
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
        del work, claims
        required = spec.data.get("attributes")
        if not isinstance(required, Mapping):
            return HardConstraintResult(
                HardEvaluationState.INDETERMINATE,
                "attribute constraint requires data.attributes",
            )
        if all(
            candidate.attributes.get(str(key)) == value
            for key, value in required.items()
        ):
            return HardConstraintResult(HardEvaluationState.PASS)
        return HardConstraintResult(
            HardEvaluationState.REJECT, "candidate attributes do not match"
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
        del work, candidate, claims, spec
        return PreferenceResult(
            PreferenceEvaluationState.SCORE,
            PreferenceScore(utility=0, quality_band="preferred"),
        )


class FifoSchedulingPolicy:
    """Select the earliest feasible work, bypassing exhausted/infeasible work."""

    descriptor = _descriptor("fifo_safe_bypass")

    def select(self, context: PolicyContext) -> PolicyDecision:
        for evaluation in context.evaluations:
            if evaluation.state is WorkSearchState.INVALID:
                return PolicyDecision(
                    PolicyDecisionState.WAIT,
                    explanation="an earlier work evaluation is invalid",
                )
            if (
                evaluation.state is not WorkSearchState.COMPLETE
                or not evaluation.candidates
            ):
                continue
            selected = min(
                evaluation.candidates,
                key=lambda item: (
                    tuple(-value for value in item.preference_vector),
                    item.candidate_id,
                    item.stable_claim_key,
                ),
            )
            return PolicyDecision(
                PolicyDecisionState.SELECT,
                stage_work_id=selected.stage_work_id,
                candidate_id=selected.candidate_id,
            )
        return PolicyDecision(
            PolicyDecisionState.WAIT, explanation="no complete feasible work"
        )


__all__ = [
    "AttributeConstraintEvaluator",
    "FifoSchedulingPolicy",
    "NeutralPreferenceScorer",
    "TargetConstraintEvaluator",
]
