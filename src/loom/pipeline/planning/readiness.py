"""One side-effect-free interpretation of persisted stage-plan readiness."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast

from loom.pipeline.status import StageStatus
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .models import PlanAction, StagePlan


class ReadinessAttemptView(Protocol):
    """Minimal authority attempt state consumed by readiness evaluation."""

    @property
    def attempt(self) -> int: ...

    @property
    def attempt_id(self) -> str: ...

    @property
    def status(self) -> StageStatus: ...


@dataclass(frozen=True, slots=True)
class RetryAuthorization:
    """Authority-owned permission to create one exact retry attempt."""

    decision_id: str
    next_attempt: int

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id must be non-empty")
        if isinstance(self.next_attempt, bool) or self.next_attempt < 1:
            raise ValueError("next_attempt must be a positive integer")


@dataclass(frozen=True, slots=True)
class AttemptReadiness:
    """Immutable semantic evidence for one controller action or RUN attempt."""

    stage_plan: StagePlan
    action: PlanAction
    readiness_generation: str
    bound_inputs: Mapping[str, PlainData]
    upstream_commits: Mapping[str, str] = field(default_factory=dict)
    expected_stage_status: StageStatus | None = None
    expected_attempt_id: str | None = None
    next_attempt: int | None = None
    retry_decision_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "bound_inputs", _plain_mapping(self.bound_inputs, "bound_inputs")
        )
        object.__setattr__(
            self,
            "upstream_commits",
            _string_mapping(self.upstream_commits, "upstream_commits"),
        )
        if not self.readiness_generation:
            raise ValueError("readiness_generation must be non-empty")
        if self.action is PlanAction.RUN and self.next_attempt is None:
            raise ValueError("RUN readiness requires next_attempt")

    def evidence_dict(self) -> dict[str, PlainData]:
        """Return the exact evidence covered by the readiness generation."""

        return {
            "stage_name": self.stage_plan.stage_name,
            "action": self.action.value,
            "plan_fingerprint": _plan_fingerprint(self.stage_plan),
            "bound_inputs": thaw_plain_data(self.bound_inputs, path="bound_inputs"),
            "upstream_commits": dict(self.upstream_commits),
            "expected_stage_status": (
                None
                if self.expected_stage_status is None
                else self.expected_stage_status.value
            ),
            "expected_attempt_id": self.expected_attempt_id,
            "next_attempt": self.next_attempt,
            "retry_decision_id": self.retry_decision_id,
        }


def evaluate_attempt_readiness(
    stage_plan: StagePlan,
    *,
    completed_stages: Collection[str] = (),
    successful_stages: Collection[str] | None = None,
    committed_outputs: Mapping[str, str] | None = None,
    current_attempt: ReadinessAttemptView | None = None,
    run_cancelled: bool = False,
    retry_authorization: RetryAuthorization | None = None,
    prepared_generation: str | None = None,
) -> AttemptReadiness | None:
    """Interpret one persisted plan against caller-supplied authority facts.

    ``completed_stages`` is retained for the in-process compatibility runner.
    Durable consumers supply exact commit identities as ``committed_outputs``.
    The predicate never reads a store, allocates, or performs a controller action.
    """

    if run_cancelled:
        return None
    commits = _string_mapping(committed_outputs or {}, "committed_outputs")
    completed = frozenset(completed_stages)
    successful = (
        completed if successful_stages is None else frozenset(successful_stages)
    )
    required = successful if stage_plan.action is PlanAction.RUN else completed
    if any(upstream not in required and upstream not in commits for upstream in stage_plan.upstream_stages):
        return None

    expected_status: StageStatus | None = None
    expected_attempt_id: str | None = None
    next_attempt: int | None = None
    retry_decision_id: str | None = None
    if stage_plan.action is PlanAction.RUN:
        if current_attempt is None:
            next_attempt = 1
        else:
            expected_status = StageStatus(current_attempt.status)
            expected_attempt_id = current_attempt.attempt_id
            if (
                expected_status is StageStatus.PENDING
                and prepared_generation is not None
            ):
                next_attempt = current_attempt.attempt
            elif expected_status is StageStatus.STALE:
                next_attempt = current_attempt.attempt + 1
            elif expected_status is StageStatus.FAILED:
                if (
                    retry_authorization is None
                    or retry_authorization.next_attempt
                    != current_attempt.attempt + 1
                ):
                    return None
                next_attempt = retry_authorization.next_attempt
                retry_decision_id = retry_authorization.decision_id
            else:
                return None

    bound_inputs: dict[str, PlainData] = {
        name: cast(PlainData, bound.to_dict())
        for name, bound in stage_plan.bound_inputs.items()
    }
    evidence: dict[str, PlainData] = {
        "stage_name": stage_plan.stage_name,
        "action": stage_plan.action.value,
        "plan_fingerprint": _plan_fingerprint(stage_plan),
        "bound_inputs": bound_inputs,
        "upstream_commits": dict(sorted(commits.items())),
        "expected_stage_status": (
            None if expected_status is None else expected_status.value
        ),
        "expected_attempt_id": expected_attempt_id,
        "next_attempt": next_attempt,
        "retry_decision_id": retry_decision_id,
    }
    generation = (
        prepared_generation
        if expected_status is StageStatus.PENDING and prepared_generation is not None
        else hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return AttemptReadiness(
        stage_plan=stage_plan,
        action=stage_plan.action,
        readiness_generation=generation,
        bound_inputs=bound_inputs,
        upstream_commits=commits,
        expected_stage_status=expected_status,
        expected_attempt_id=expected_attempt_id,
        next_attempt=next_attempt,
        retry_decision_id=retry_decision_id,
    )


def _plan_fingerprint(stage_plan: StagePlan) -> str:
    if stage_plan.fingerprint is not None:
        return stage_plan.fingerprint.fingerprint
    return hashlib.sha256(
        json.dumps(
            stage_plan.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _plain_mapping(
    value: Mapping[str, PlainData], field_name: str
) -> Mapping[str, PlainData]:
    frozen = freeze_plain_data(value, path=field_name)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return frozen


def _string_mapping(value: Mapping[str, str], field_name: str) -> Mapping[str, str]:
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(item, str)
        or not item
        for key, item in value.items()
    ):
        raise ValueError(f"{field_name} must contain non-empty string pairs")
    return dict(sorted(value.items()))


__all__ = [
    "AttemptReadiness",
    "ReadinessAttemptView",
    "RetryAuthorization",
    "evaluate_attempt_readiness",
]
