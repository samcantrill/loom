"""Shared, side-effect-free interpretation of stage-plan readiness."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from loom.serialization import PlainData

from .models import PlanAction, StagePlan


@dataclass(frozen=True, slots=True)
class AttemptReadiness:
    """The one scheduler/runner interpretation of a planned stage."""

    stage_plan: StagePlan
    action: PlanAction
    readiness_generation: str
    bound_inputs: Mapping[str, PlainData]


def evaluate_attempt_readiness(
    stage_plan: StagePlan,
    *,
    completed_stages: Collection[str],
) -> AttemptReadiness | None:
    """Return readiness only after every declared upstream stage completed.

    This deliberately does not inspect lifecycle state or allocate anything;
    controller actions remain actions rather than becoming runnable work.
    """
    if not all(name in completed_stages for name in stage_plan.upstream_stages):
        return None
    generation = stage_plan.fingerprint.fingerprint if stage_plan.fingerprint else "pending-inputs"
    return AttemptReadiness(
        stage_plan=stage_plan,
        action=stage_plan.action,
        readiness_generation=generation,
        bound_inputs={name: bound.artifact_ref.to_dict() for name, bound in stage_plan.bound_inputs.items()},
    )


__all__ = ["AttemptReadiness", "evaluate_attempt_readiness"]
