"""Concrete placement-local preference scorers for managed GPU stages.

These components deliberately stop at utility/band evidence.  The generic
kernel remains the sole owner of weights, tier precedence, fallback and ties.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from loom.scheduling import (
    Candidate,
    PreferenceEvaluationState,
    PreferenceResult,
    PreferenceScore,
    PreferenceSpec,
    ResourceClaim,
    SchedulingComponentDescriptor,
    WorkItem,
)


def _descriptor(kind: str) -> SchedulingComponentDescriptor:
    return SchedulingComponentDescriptor(kind, 1, "1", f"builtin:{kind}:v1", "builtin")


def _ordered_score(value: object, order: object) -> PreferenceResult:
    if not isinstance(order, Sequence) or isinstance(order, (str, bytes)):
        return PreferenceResult(
            PreferenceEvaluationState.INDETERMINATE,
            explanation="preference order is invalid",
        )
    ordered = tuple(order)
    if any(not isinstance(item, str) or not item for item in ordered):
        return PreferenceResult(
            PreferenceEvaluationState.INDETERMINATE,
            explanation="preference order is invalid",
        )
    try:
        position = ordered.index(value)
    except ValueError:
        return PreferenceResult(
            PreferenceEvaluationState.SCORE, PreferenceScore(0, "fallback")
        )
    return PreferenceResult(
        PreferenceEvaluationState.SCORE,
        PreferenceScore(len(ordered) - position, "preferred"),
    )


class OrderedAgentPreferenceScorer:
    descriptor = _descriptor("preferred_agent")

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: PreferenceSpec,
    ) -> PreferenceResult:
        del work, claims
        return _ordered_score(candidate.candidate_id, spec.data.get("agents"))


class GpuModelPreferenceScorer:
    descriptor = _descriptor("gpu_model")

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: PreferenceSpec,
    ) -> PreferenceResult:
        del work
        devices = candidate.inventory.get("gpu")
        if devices is None:
            return PreferenceResult(
                PreferenceEvaluationState.SCORE, PreferenceScore(0, "fallback")
            )
        configured = devices.data.get("devices")
        if not isinstance(configured, tuple):
            return PreferenceResult(
                PreferenceEvaluationState.INDETERMINATE,
                explanation="GPU inventory is invalid",
            )
        models = {
            str(item.get("id")): item.get("model")
            for item in configured
            if isinstance(item, Mapping)
        }
        gpu_claim = next(
            (claim for claim in claims if claim.resource_kind == "gpu"), None
        )
        if gpu_claim is None:
            return PreferenceResult(
                PreferenceEvaluationState.SCORE, PreferenceScore(0, "fallback")
            )
        selected = [models.get(atom.local_capacity_key) for atom in gpu_claim.atoms]
        if (
            not selected
            or any(model is None for model in selected)
            or len(set(selected)) != 1
        ):
            return PreferenceResult(
                PreferenceEvaluationState.SCORE, PreferenceScore(0, "fallback")
            )
        return _ordered_score(selected[0], spec.data.get("models"))


class ResourceAttributePreferenceScorer:
    descriptor = _descriptor("resource_attribute")

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: PreferenceSpec,
    ) -> PreferenceResult:
        del work, claims
        attribute = spec.data.get("attribute")
        if not isinstance(attribute, str) or not attribute:
            return PreferenceResult(
                PreferenceEvaluationState.INDETERMINATE,
                explanation="resource attribute preference is invalid",
            )
        return _ordered_score(
            candidate.attributes.get(attribute), spec.data.get("values")
        )


class PackingPreferenceScorer:
    descriptor = _descriptor("packing")

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: PreferenceSpec,
    ) -> PreferenceResult:
        del work, spec
        claimed = sum(atom.amount.fraction for claim in claims for atom in claim.atoms)
        available = sum(
            atom.amount.fraction
            for envelope in candidate.availability.values()
            for atom in envelope.atoms
        )
        # Prefer a tight fit; only a bounded integer evidence value crosses out.
        utility = -int(available - claimed)
        return PreferenceResult(
            PreferenceEvaluationState.SCORE, PreferenceScore(utility, "preferred")
        )


__all__ = [
    "GpuModelPreferenceScorer",
    "OrderedAgentPreferenceScorer",
    "PackingPreferenceScorer",
    "ResourceAttributePreferenceScorer",
]
