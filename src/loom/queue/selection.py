"""Import-light public values and private evaluation for queue selection."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, cast

from loom.timestamps import parse_timestamp

from .errors import QueueValidationError
from .models import QueueItem, QueueItemStatus, validate_queue_id

_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DEFAULT_PREFERENCE_ID = "queue_selection.default"
_DEFAULT_REASON_CODE = "queue_selection.default_oldest_eligible"
_NO_ELIGIBLE_REASON_CODE = "queue_selection.no_eligible_candidate"
_INVALID_DECISION_REASON_CODE = "queue_selection.invalid_decision"
_POLICY_ERROR_REASON_CODE = "queue_selection.policy_error"


class QueueSelectionDisposition(StrEnum):
    """The two possible outcomes of one policy preference."""

    SELECTED = "selected"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class QueueSelectionCandidate:
    """Restricted immutable facts for one currently eligible queue item."""

    queue_item_id: str
    enqueued_at: str
    dispatch_attempt: int
    resources: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "queue_item_id",
            validate_queue_id(self.queue_item_id, "queue_item_id"),
        )
        if not isinstance(self.enqueued_at, str) or not self.enqueued_at:
            raise QueueValidationError("enqueued_at must be an ISO-8601 timestamp")
        try:
            parse_timestamp(self.enqueued_at)
        except ValueError as exc:
            raise QueueValidationError(
                "enqueued_at must be an ISO-8601 timestamp"
            ) from exc
        object.__setattr__(
            self,
            "dispatch_attempt",
            _positive_int(self.dispatch_attempt, "dispatch_attempt"),
        )
        object.__setattr__(
            self,
            "resources",
            _non_negative_resources(self.resources, "resources"),
        )


@dataclass(frozen=True, slots=True)
class QueueSelectionContext:
    """Restricted immutable selection input supplied to one policy."""

    pool_name: str
    candidates: tuple[QueueSelectionCandidate, ...]
    advisory_available_resources: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pool_name", validate_queue_id(self.pool_name, "pool_name")
        )
        candidates = tuple(self.candidates)
        candidate_ids: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, QueueSelectionCandidate):
                raise QueueValidationError(
                    "candidates must contain QueueSelectionCandidate records"
                )
            if candidate.queue_item_id in candidate_ids:
                raise QueueValidationError("candidates must have unique queue_item_id values")
            candidate_ids.add(candidate.queue_item_id)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(
            self,
            "advisory_available_resources",
            _non_negative_resources(
                self.advisory_available_resources, "advisory_available_resources"
            ),
        )


@dataclass(frozen=True, slots=True)
class QueueSelectionDecision:
    """One policy preference, validated before any ownership mutation."""

    disposition: QueueSelectionDisposition | str
    reason_code: str
    queue_item_id: str | None = None

    def __post_init__(self) -> None:
        try:
            disposition = QueueSelectionDisposition(self.disposition)
        except (TypeError, ValueError) as exc:
            raise QueueValidationError(
                "disposition must be 'selected' or 'stopped'"
            ) from exc
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "reason_code", _safe_code(self.reason_code, "reason_code"))
        if disposition is QueueSelectionDisposition.SELECTED:
            object.__setattr__(
                self,
                "queue_item_id",
                validate_queue_id(self.queue_item_id, "queue_item_id"),
            )
        elif self.queue_item_id is not None:
            raise QueueValidationError("stopped decisions must not include queue_item_id")


class QueueSelectionPolicy(Protocol):
    """A structural preference hook for one managed queue pool."""

    policy_id: str

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision: ...


@dataclass(frozen=True, slots=True)
class _QueueSelectionPolicyBinding:
    """Construction-time snapshot of a custom preference implementation."""

    policy_id: str
    implementation: QueueSelectionPolicy


@dataclass(frozen=True, slots=True)
class _QueueSelectionEvaluation:
    """Private evaluator result with stable evidence ownership."""

    decision: QueueSelectionDecision
    preference_id: str
    source_had_candidates: bool
    has_eligible_candidates: bool


def _bind_selection_policy(policy: object) -> _QueueSelectionPolicyBinding:
    """Validate and freeze the small injected policy shape at construction."""

    try:
        policy_id = policy.policy_id  # type: ignore[union-attr]
        selector = policy.select_next  # type: ignore[union-attr]
    except AttributeError as exc:
        raise QueueValidationError(
            "selection policy must define policy_id and select_next(context)"
        ) from exc
    policy_id = _safe_code(policy_id, "policy_id")
    if not callable(selector):
        raise QueueValidationError("selection policy select_next must be callable")
    return _QueueSelectionPolicyBinding(
        policy_id=policy_id,
        implementation=cast(QueueSelectionPolicy, policy),
    )


def _evaluate_selection(
    items: tuple[QueueItem, ...],
    *,
    pool_name: str,
    advisory_available_resources: Mapping[str, int],
    policy: _QueueSelectionPolicyBinding | None,
    filter_resources: bool = True,
) -> _QueueSelectionEvaluation:
    """Apply fixed eligibility and one default or injected preference."""

    context = QueueSelectionContext(
        pool_name=pool_name,
        candidates=tuple(
            QueueSelectionCandidate(
                queue_item_id=item.queue_item_id,
                enqueued_at=item.enqueued_at,
                dispatch_attempt=item.dispatch_attempt,
                resources=item.launch_contract.resources,
            )
            for item in items
            if _is_eligible(
                item,
                pool_name=pool_name,
                advisory_available_resources=advisory_available_resources,
                filter_resources=filter_resources,
            )
        ),
        advisory_available_resources=advisory_available_resources,
    )
    if not context.candidates:
        return _QueueSelectionEvaluation(
            decision=QueueSelectionDecision(
                QueueSelectionDisposition.STOPPED,
                _NO_ELIGIBLE_REASON_CODE,
            ),
            preference_id=_DEFAULT_PREFERENCE_ID if policy is None else policy.policy_id,
            source_had_candidates=bool(items),
            has_eligible_candidates=False,
        )
    if policy is None:
        return _QueueSelectionEvaluation(
            decision=QueueSelectionDecision(
                QueueSelectionDisposition.SELECTED,
                _DEFAULT_REASON_CODE,
                context.candidates[0].queue_item_id,
            ),
            preference_id=_DEFAULT_PREFERENCE_ID,
            source_had_candidates=True,
            has_eligible_candidates=True,
        )
    preference_id = policy.policy_id
    try:
        decision = policy.implementation.select_next(context)
    except Exception:  # policy failures are safe stop evidence, never mutation
        return _QueueSelectionEvaluation(
            decision=QueueSelectionDecision(
                QueueSelectionDisposition.STOPPED,
                _POLICY_ERROR_REASON_CODE,
            ),
            preference_id=preference_id,
            source_had_candidates=True,
            has_eligible_candidates=True,
        )
    if not isinstance(decision, QueueSelectionDecision) or (
        decision.disposition is QueueSelectionDisposition.SELECTED
        and decision.queue_item_id
        not in {candidate.queue_item_id for candidate in context.candidates}
    ):
        return _QueueSelectionEvaluation(
            decision=QueueSelectionDecision(
                QueueSelectionDisposition.STOPPED,
                _INVALID_DECISION_REASON_CODE,
            ),
            preference_id=preference_id,
            source_had_candidates=True,
            has_eligible_candidates=True,
        )
    return _QueueSelectionEvaluation(
        decision=decision,
        preference_id=preference_id,
        source_had_candidates=True,
        has_eligible_candidates=True,
    )
def _is_eligible(
    item: QueueItem,
    *,
    pool_name: str,
    advisory_available_resources: Mapping[str, int],
    filter_resources: bool,
) -> bool:
    return (
        item.pool_name == pool_name
        and QueueItemStatus(item.status) is QueueItemStatus.QUEUED
        and (
            not filter_resources
            or all(
                amount <= advisory_available_resources.get(resource_name, 0)
                for resource_name, amount in item.launch_contract.resources.items()
            )
        )
    )


def _non_negative_resources(value: Mapping[str, int], field_name: str) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise QueueValidationError(f"{field_name} must be a mapping")
    resources: dict[str, int] = {}
    for resource_name, amount in value.items():
        resource_name = validate_queue_id(resource_name, f"{field_name} key")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise QueueValidationError(
                f"{field_name}.{resource_name} must be a non-negative integer"
            )
        resources[resource_name] = amount
    return MappingProxyType(resources)


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise QueueValidationError(f"{field_name} must be a positive integer")
    return value


def _safe_code(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_CODE_RE.fullmatch(value) is None:
        raise QueueValidationError(
            f"{field_name} must be a 1-128 character safe ASCII code"
        )
    return value


__all__ = [
    "QueueSelectionCandidate",
    "QueueSelectionContext",
    "QueueSelectionDecision",
    "QueueSelectionDisposition",
    "QueueSelectionPolicy",
]
