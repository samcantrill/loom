"""Python controller entrypoints for queue dispatch loops."""

from __future__ import annotations

import time
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable
from uuid import uuid4

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_timestamp

from .errors import QueueServiceError
from .models import (
    DispatchHandle,
    QueueItem,
    QueueItemStatus,
    QueuePool,
    QueuePoolMode,
    QueueRecoveryRecord,
)
from .selection import (
    _QueueSelectionPolicyBinding,
    _bind_selection_policy,
    QueueSelectionDisposition,
    QueueSelectionDecision,
    QueueSelectionPolicy,
    _evaluate_selection,
)
from .service import QueueService

_SELECTION_LIMIT = 32
_POLICY_STOPPED_REASON_CODE = "queue_selection.policy_stopped"
_SELECTION_LIMIT_EXHAUSTED_REASON_CODE = "queue_selection.selection_limit_exhausted"
_SAFE_REASON_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class QueueDispatchDisposition(StrEnum):
    """Canonical externally observable dispatch outcomes."""

    STARTED = "started"
    COMPLETED = "completed"
    NOT_STARTED = "not_started"
    START_UNCERTAIN = "start_uncertain"


class QueueDispatchNonStartCause(StrEnum):
    """Confirmed reason a dispatch adapter did not start work."""

    CAPACITY = "capacity"
    INVALID_OR_UNSUPPORTED = "invalid_or_unsupported"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"
    OWNERSHIP_LOST = "ownership_lost"
    INTERNAL = "internal"


class QueuePreStartCleanupStatus(StrEnum):
    """Adapter fact about resources acquired before a confirmed non-start."""

    NOT_REQUIRED = "not_required"
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class QueueDispatchResult:
    """Result returned by a queue dispatch adapter."""

    disposition: QueueDispatchDisposition | str | None = None
    handle_id: str | None = None
    status: QueueItemStatus = QueueItemStatus.UNKNOWN
    reason_code: str = "queue_dispatch.result"
    evidence: Mapping[str, PlainData] = field(default_factory=dict)
    non_start_cause: QueueDispatchNonStartCause | str | None = None
    cleanup_status: QueuePreStartCleanupStatus | str | None = None
    next_maintenance_at: str | None = None

    def __post_init__(self) -> None:
        try:
            status = QueueItemStatus(self.status)
            if self.disposition is None:
                raise QueueServiceError("dispatch result disposition is required")
            disposition = QueueDispatchDisposition(self.disposition)
            cause = (
                None
                if self.non_start_cause is None
                else QueueDispatchNonStartCause(self.non_start_cause)
            )
            cleanup = (
                None
                if self.cleanup_status is None
                else QueuePreStartCleanupStatus(self.cleanup_status)
            )
        except ValueError as exc:
            raise QueueServiceError("invalid dispatch result factual value") from exc
        has_handle = isinstance(self.handle_id, str) and bool(self.handle_id)
        if disposition in {
            QueueDispatchDisposition.STARTED,
            QueueDispatchDisposition.COMPLETED,
        }:
            if not has_handle:
                raise QueueServiceError(
                    "started or completed dispatch result requires a non-empty handle_id"
                )
            if cause is not None or cleanup is not None:
                raise QueueServiceError(
                    "started or completed dispatch result cannot assert non-start facts"
                )
        elif self.handle_id is not None:
            raise QueueServiceError("non-start dispatch result cannot have a handle_id")
        if disposition is QueueDispatchDisposition.STARTED:
            if status is not QueueItemStatus.DISPATCHED:
                raise QueueServiceError(
                    "started dispatch result status must be DISPATCHED"
                )
        elif disposition is QueueDispatchDisposition.COMPLETED:
            if status not in {
                QueueItemStatus.SUCCEEDED,
                QueueItemStatus.FAILED,
                QueueItemStatus.UNKNOWN,
            }:
                raise QueueServiceError(
                    "completed dispatch result status must be SUCCEEDED, FAILED, or UNKNOWN"
                )
        elif disposition is QueueDispatchDisposition.NOT_STARTED:
            if (
                status is not QueueItemStatus.UNKNOWN
                or cause is None
                or cleanup is None
            ):
                raise QueueServiceError(
                    "not-started dispatch result requires UNKNOWN status, cause, and cleanup status"
                )
        elif disposition is QueueDispatchDisposition.START_UNCERTAIN:
            if (
                status is not QueueItemStatus.UNKNOWN
                or cause is not None
                or cleanup is not None
            ):
                raise QueueServiceError(
                    "start-uncertain dispatch result requires UNKNOWN status without non-start facts"
                )
        if (
            disposition is not QueueDispatchDisposition.STARTED
            and self.next_maintenance_at is not None
        ):
            raise QueueServiceError(
                "only started dispatch result may include next_maintenance_at"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "non_start_cause", cause)
        object.__setattr__(self, "cleanup_status", cleanup)
        object.__setattr__(self, "reason_code", _safe_reason_code(self.reason_code))
        try:
            evidence = freeze_plain_data(self.evidence, path="evidence")
        except PlainDataError as exc:
            raise QueueServiceError(str(exc)) from exc
        if not isinstance(evidence, Mapping):
            raise QueueServiceError("evidence must be a mapping")
        object.__setattr__(self, "evidence", evidence)
        if self.next_maintenance_at is not None:
            if not isinstance(self.next_maintenance_at, str):
                raise QueueServiceError(
                    "next_maintenance_at must be a timestamp string or None"
                )
            object.__setattr__(
                self,
                "next_maintenance_at",
                utc_timestamp(parse_timestamp(self.next_maintenance_at)),
            )

    @property
    def is_safe_capacity_non_start(self) -> bool:
        """Whether a controller may requeue this confirmed non-start."""

        return (
            self.disposition is QueueDispatchDisposition.NOT_STARTED
            and self.non_start_cause is QueueDispatchNonStartCause.CAPACITY
            and self.cleanup_status
            in {
                QueuePreStartCleanupStatus.NOT_REQUIRED,
                QueuePreStartCleanupStatus.CONFIRMED,
            }
        )


class QueueDispatchAdapter(Protocol):
    """Minimal dispatch adapter contract for queue controllers."""

    adapter_name: str

    def dispatch(self, item: QueueItem) -> QueueDispatchResult: ...


@dataclass(frozen=True, slots=True)
class QueueDispatchInspection:
    """Adapter observation for an already-dispatched queue item."""

    status: QueueItemStatus
    reason: str
    evidence: Mapping[str, PlainData] = field(default_factory=dict)
    terminal: bool = False
    handoff_complete: bool = False
    next_maintenance_at: str | None = None
    degraded: bool = False

    def __post_init__(self) -> None:
        status = QueueItemStatus(self.status)
        if not isinstance(self.handoff_complete, bool):
            raise QueueServiceError("handoff_complete must be a boolean")
        if not isinstance(self.degraded, bool):
            raise QueueServiceError("degraded must be a boolean")
        if self.terminal:
            if status not in {
                QueueItemStatus.SUCCEEDED,
                QueueItemStatus.FAILED,
                QueueItemStatus.UNKNOWN,
                QueueItemStatus.CANCELLED,
            }:
                raise QueueServiceError(
                    "terminal dispatch inspection must use a terminal status"
                )
            if self.handoff_complete:
                raise QueueServiceError(
                    "terminal dispatch inspection cannot be handoff-complete"
                )
        elif status is not QueueItemStatus.DISPATCHED:
            raise QueueServiceError("active dispatch inspection must use DISPATCHED")
        object.__setattr__(self, "status", status)
        if not isinstance(self.reason, str) or not self.reason:
            raise QueueServiceError("reason must be a non-empty string")
        try:
            evidence = freeze_plain_data(self.evidence, path="evidence")
        except PlainDataError as exc:
            raise QueueServiceError(str(exc)) from exc
        if not isinstance(evidence, Mapping):
            raise QueueServiceError("evidence must be a mapping")
        object.__setattr__(self, "evidence", evidence)
        if self.next_maintenance_at is not None:
            if not isinstance(self.next_maintenance_at, str):
                raise QueueServiceError(
                    "next_maintenance_at must be a timestamp string or None"
                )
            object.__setattr__(
                self,
                "next_maintenance_at",
                utc_timestamp(parse_timestamp(self.next_maintenance_at)),
            )


@dataclass(frozen=True, slots=True)
class QueueDispatchCancellation:
    """Adapter evidence returned before queue-local cancellation is recorded."""

    reason: str
    evidence: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason:
            raise QueueServiceError("reason must be a non-empty string")
        try:
            evidence = freeze_plain_data(self.evidence, path="evidence")
        except PlainDataError as exc:
            raise QueueServiceError(str(exc)) from exc
        if not isinstance(evidence, Mapping):
            raise QueueServiceError("evidence must be a mapping")
        object.__setattr__(self, "evidence", evidence)


@runtime_checkable
class QueueInspectableDispatchAdapter(QueueDispatchAdapter, Protocol):
    """Optional adapter contract for active status reconciliation."""

    def inspect(self, item: QueueItem) -> QueueDispatchInspection: ...


@runtime_checkable
class QueueCancellableDispatchAdapter(QueueDispatchAdapter, Protocol):
    """Optional adapter contract for active cancellation."""

    def cancel(
        self,
        item: QueueItem,
        *,
        requested_by: str,
        reason: str,
    ) -> QueueDispatchCancellation: ...


class FakeQueueDispatchAdapter:
    """Synchronous fake adapter used by Python queue control tests."""

    adapter_name = "fake"

    def dispatch(self, item: QueueItem) -> QueueDispatchResult:
        return QueueDispatchResult(
            disposition=QueueDispatchDisposition.COMPLETED,
            handle_id=f"fake:{item.queue_item_id}:{item.dispatch_attempt}",
            status=QueueItemStatus.SUCCEEDED,
            reason_code="queue_dispatch.fake_completed",
            evidence={"queue_item_id": item.queue_item_id},
        )


@dataclass(frozen=True, slots=True)
class QueueControllerStep:
    """One daemon-style controller iteration result."""

    outcome: str
    item: QueueItem | None = None
    dispatch_handle: DispatchHandle | None = None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "outcome": self.outcome,
            "item": None if self.item is None else self.item.to_dict(),
            "dispatch_handle": None
            if self.dispatch_handle is None
            else self.dispatch_handle.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class QueueDrainResult:
    """Foreground-drain compatibility result."""

    steps: tuple[QueueControllerStep, ...]
    recovery_records: tuple[QueueRecoveryRecord, ...]

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "recovery_records": [record.to_dict() for record in self.recovery_records],
        }


@dataclass(frozen=True, slots=True)
class QueueCycleResult:
    """Plain-data result of reconciling and filling one selected pool."""

    reconciliation_steps: tuple[QueueControllerStep, ...]
    dispatch_steps: tuple[QueueControllerStep, ...]
    active_count: int
    capacity_blocked: bool
    next_maintenance_at: str | None
    selection_stop_reason: str | None = None

    def __post_init__(self) -> None:
        allowed = {
            "queue_selection.policy_stopped",
            "queue_selection.policy_error",
            "queue_selection.invalid_decision",
            "queue_selection.selection_limit_exhausted",
        }
        if self.selection_stop_reason is not None and (
            self.selection_stop_reason not in allowed
        ):
            raise QueueServiceError("invalid queue cycle selection_stop_reason")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "reconciliation_steps": [
                step.to_dict() for step in self.reconciliation_steps
            ],
            "dispatch_steps": [step.to_dict() for step in self.dispatch_steps],
            "active_count": self.active_count,
            "capacity_blocked": self.capacity_blocked,
            "next_maintenance_at": self.next_maintenance_at,
            "selection_stop_reason": self.selection_stop_reason,
        }


@dataclass(frozen=True, slots=True)
class QueueRecoveryClassification:
    """Current-controller versus other-session recovery work for one pool."""

    current_items: tuple[QueueItem, ...]
    foreign_items: tuple[QueueItem, ...]


@dataclass(frozen=True, slots=True)
class _QueueSelectionAttempt:
    """One bounded select-then-own result for either pool mode."""

    item: QueueItem | None
    decision: QueueSelectionDecision
    steps_used: int
    capacity_blocked: bool
    stop_reason: str | None


@dataclass(frozen=True, slots=True)
class _QueueDispatchTransition:
    """One controller-owned queue transition for factual adapter output."""

    step: QueueControllerStep
    continue_cycle: bool
    capacity_blocked: bool = False


class QueueController:
    """Claim queued items and dispatch them through injected adapters."""

    def __init__(
        self,
        service: QueueService,
        *,
        adapters: Mapping[str, QueueDispatchAdapter] | None = None,
        selection_policies: Mapping[str, QueueSelectionPolicy] | None = None,
        owner_id: str | None = None,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        self._service = service
        self._adapters = (
            dict(adapters)
            if adapters is not None
            else {"fake": FakeQueueDispatchAdapter()}
        )
        self._owner_id = owner_id or service.spec.controller.owner_id
        self._clock = clock
        self._session_id = uuid4().hex
        self._owned_handle_ids: set[str] = set()
        self._pending_start_compensations: dict[str, QueueItem] = {}
        self._selection_policies = self._selection_policies_by_pool(selection_policies)
        self._selection_reader, self._selection_claimer = (
            self._bind_selection_repository_capabilities()
        )

    def run_cycle(self, *, pool_name: str) -> QueueCycleResult:
        """Reconcile one pool then fill it within its controller-local budgets."""
        if not isinstance(pool_name, str) or not pool_name:
            raise QueueServiceError("run_cycle requires one non-empty pool_name")
        reconciliation, degraded, deadlines = self._reconcile_all(pool_name)
        active_count = self._active_count(pool_name)
        dispatch_steps: list[QueueControllerStep] = []
        capacity_blocked = False
        selection_stop_reason: str | None = None
        attempted_item_ids: set[str] = set()
        if not degraded:
            limit = self._service.spec.controller.max_active_items
            budget = self._service.spec.controller.max_dispatches_per_cycle or limit
            selection_steps_remaining = _SELECTION_LIMIT
            while active_count < limit and len(dispatch_steps) < budget:
                if selection_steps_remaining <= 0:
                    selection_stop_reason = _SELECTION_LIMIT_EXHAUSTED_REASON_CODE
                    break
                selection = self._select_and_acquire_for_pool(
                    pool_name,
                    selection_limit=selection_steps_remaining,
                    attempted_item_ids=attempted_item_ids,
                )
                selection_steps_remaining -= selection.steps_used
                if selection.item is None:
                    capacity_blocked = capacity_blocked or selection.capacity_blocked
                    selection_stop_reason = selection.stop_reason
                    break
                item = selection.item
                attempted_item_ids.add(item.queue_item_id)
                result = self._safe_dispatch(item)
                transition = self._apply_dispatch_result(item, result, deadlines)
                dispatch_steps.append(transition.step)
                capacity_blocked = capacity_blocked or transition.capacity_blocked
                if result.disposition is QueueDispatchDisposition.STARTED:
                    active_count += 1
                if not transition.continue_cycle:
                    break
        return QueueCycleResult(
            reconciliation_steps=tuple(reconciliation),
            dispatch_steps=tuple(dispatch_steps),
            active_count=self._active_count(pool_name),
            capacity_blocked=capacity_blocked,
            next_maintenance_at=min(deadlines) if deadlines else None,
            selection_stop_reason=selection_stop_reason,
        )

    def classify_recovery(self, *, pool_name: str) -> QueueRecoveryClassification:
        """Classify active selected-pool work without inspecting or mutating it."""

        if not isinstance(pool_name, str) or not pool_name:
            raise QueueServiceError(
                "classify_recovery requires one non-empty pool_name"
            )
        current: list[QueueItem] = []
        foreign: list[QueueItem] = []
        for item in self._service.recovery_items():
            if item.pool_name != pool_name:
                continue
            (current if self._owned_by_current_session(item) else foreign).append(item)
        return QueueRecoveryClassification(tuple(current), tuple(foreign))

    def reconcile_current_session(self, *, pool_name: str) -> QueueCycleResult:
        """Reconcile all current-session work without claiming queued items."""

        if not isinstance(pool_name, str) or not pool_name:
            raise QueueServiceError(
                "reconcile_current_session requires one non-empty pool_name"
            )
        reconciliation, degraded, deadlines = self._reconcile_all(pool_name)
        classification = self.classify_recovery(pool_name=pool_name)
        return QueueCycleResult(
            reconciliation_steps=tuple(reconciliation),
            dispatch_steps=(),
            active_count=len(classification.current_items),
            capacity_blocked=degraded,
            next_maintenance_at=min(deadlines) if deadlines else None,
        )

    def run_once(
        self,
        *,
        pool_name: str | None = None,
        stop_on_handoff: bool = False,
    ) -> QueueControllerStep:
        active = self.reconcile_active(pool_name=pool_name)
        if active.outcome != "idle":
            if active.outcome != "handoff" or stop_on_handoff:
                return active
            handoff = active
        else:
            handoff = None
        for candidate_pool in self._candidate_pools(pool_name):
            selection = self._select_and_acquire_for_pool(candidate_pool)
            if selection.item is None:
                continue
            item = selection.item
            result = self._safe_dispatch(item)
            return self._apply_dispatch_result(item, result, []).step
        return QueueControllerStep(outcome="idle") if handoff is None else handoff

    def reconcile_active(self, *, pool_name: str | None = None) -> QueueControllerStep:
        for item in self._service.recovery_items():
            if pool_name is not None and item.pool_name != pool_name:
                continue
            if not self._owned_by_current_session(item):
                continue
            if item.queue_item_id in self._pending_start_compensations:
                return self._reconcile_pending_start(item, [])
            if QueueItemStatus(item.status) is QueueItemStatus.CLAIMED:
                return self._complete_unknown(
                    item,
                    reason="queue item was claimed but no dispatch handle was recorded",
                    evidence={"recovery_needed": True, "recovery_status": "claimed"},
                )
            if QueueItemStatus(item.status) is not QueueItemStatus.DISPATCHED:
                continue
            adapter = self._adapters.get(item.launch_contract.adapter)
            if adapter is None or not isinstance(
                adapter, QueueInspectableDispatchAdapter
            ):
                return self._complete_unknown(
                    item,
                    reason=f"adapter status unavailable: {item.launch_contract.adapter}",
                    evidence={
                        "adapter": item.launch_contract.adapter,
                        "recovery_needed": True,
                    },
                )
            inspection = adapter.inspect(item)
            if not inspection.terminal:
                if inspection.handoff_complete:
                    return QueueControllerStep(outcome="handoff", item=item)
                return QueueControllerStep(outcome="active", item=item)
            if inspection.status is QueueItemStatus.CANCELLED:
                cancelled = self._service.cancel_item(
                    item.queue_item_id,
                    requested_by=self._owner_id,
                    reason=inspection.reason,
                    evidence=_thaw_evidence(inspection.evidence),
                    expected=item,
                )
                return QueueControllerStep(outcome="cancelled", item=cancelled)
            completed = self._service.complete_item(
                item.queue_item_id,
                status=inspection.status,
                reason=inspection.reason,
                expected=item,
            )
            return QueueControllerStep(outcome="completed", item=completed)
        return QueueControllerStep(outcome="idle")

    def cancel_item(
        self,
        queue_item_id: str,
        *,
        requested_by: str | None = None,
        reason: str = "controller-requested",
    ) -> QueueControllerStep:
        requested_by = requested_by or self._owner_id
        item = self._service.read_item(queue_item_id)
        if item is None:
            raise QueueServiceError(f"unknown queue item: {queue_item_id}")
        if queue_item_id in self._pending_start_compensations:
            step = self._reconcile_pending_start(item, [])
            if step.outcome in {"active", "degraded"}:
                return QueueControllerStep(outcome="cancelling", item=item)
            return step
        evidence: Mapping[str, PlainData] = {}
        if QueueItemStatus(item.status) is QueueItemStatus.DISPATCHED:
            adapter = self._adapters.get(item.launch_contract.adapter)
            if adapter is not None and isinstance(
                adapter, QueueCancellableDispatchAdapter
            ):
                cancellation = adapter.cancel(
                    item,
                    requested_by=requested_by,
                    reason=reason,
                )
                evidence = cancellation.evidence
                reason = cancellation.reason
                if cancellation.evidence.get("exit_observed") is False:
                    return QueueControllerStep(outcome="cancelling", item=item)
        evidence = _thaw_evidence(evidence)
        cancelled = self._service.cancel_item(
            queue_item_id,
            requested_by=requested_by,
            reason=reason,
            evidence=evidence,
            expected=item,
        )
        return QueueControllerStep(outcome="cancelled", item=cancelled)

    def drain_foreground(
        self,
        *,
        pool_name: str | None = None,
        max_items: int | None = None,
        poll_interval_seconds: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> QueueDrainResult:
        if max_items is not None and max_items < 0:
            raise QueueServiceError("max_items must be non-negative or None")
        if poll_interval_seconds < 0:
            raise QueueServiceError("poll_interval_seconds must be non-negative")
        steps: list[QueueControllerStep] = []
        while max_items is None or len(steps) < max_items:
            step = self.run_once(pool_name=pool_name, stop_on_handoff=True)
            if step.outcome == "idle":
                break
            steps.append(step)
            if step.outcome == "handoff":
                break
            if step.outcome == "active" and poll_interval_seconds > 0:
                sleep(poll_interval_seconds)
        return QueueDrainResult(
            steps=tuple(steps),
            recovery_records=self._service.scan_recovery(),
        )

    def _candidate_pools(self, pool_name: str | None) -> tuple[str, ...]:
        if pool_name is not None:
            return (pool_name,)
        if self._service.spec.controller.default_pool_name is not None:
            return (self._service.spec.controller.default_pool_name,)
        return self._service.spec.pool_names

    def _selection_policies_by_pool(
        self, policies: Mapping[str, QueueSelectionPolicy] | None
    ) -> Mapping[str, _QueueSelectionPolicyBinding]:
        if policies is None:
            return {}
        if not isinstance(policies, Mapping):
            raise QueueServiceError("selection_policies must be a mapping")
        validated: dict[str, _QueueSelectionPolicyBinding] = {}
        pools_by_name = {pool.pool_name: pool for pool in self._service.spec.pools}
        for pool_name, policy in policies.items():
            if not isinstance(pool_name, str) or pool_name not in pools_by_name:
                raise QueueServiceError(f"unknown selection policy pool: {pool_name}")
            if pools_by_name[pool_name].mode is not QueuePoolMode.MANAGED:
                raise QueueServiceError(
                    f"selection policy pool is not managed: {pool_name}"
                )
            try:
                validated[pool_name] = _bind_selection_policy(policy)
            except Exception as exc:
                raise QueueServiceError(
                    f"invalid selection policy for pool: {pool_name}"
                ) from exc
        return validated

    def _bind_selection_repository_capabilities(
        self,
    ) -> tuple[Callable[..., object], Callable[..., object]]:
        """Bind the private bounded-read and exact-ownership seam once."""

        reader = getattr(self._service.repository, "_read_selection_candidates", None)
        claimer = getattr(self._service.repository, "_claim_selection_candidate", None)
        if not callable(reader) or not callable(claimer):
            raise QueueServiceError(
                "repository does not support bounded selection and exact ownership"
            )
        return reader, claimer

    def _select_and_acquire_for_pool(
        self,
        pool_name: str,
        *,
        selection_limit: int = _SELECTION_LIMIT,
        attempted_item_ids: set[str] | None = None,
    ) -> _QueueSelectionAttempt:
        pool = self._pool(pool_name)
        self._service._ensure_running()
        if selection_limit <= 0:
            raise QueueServiceError("selection_limit must be a positive integer")
        attempted_item_ids = attempted_item_ids or set()
        policy = self._selection_policies.get(pool.pool_name)
        decision = QueueSelectionDecision(
            QueueSelectionDisposition.STOPPED,
            _SELECTION_LIMIT_EXHAUSTED_REASON_CODE,
        )
        for step in range(1, selection_limit + 1):
            candidates = tuple(
                candidate
                for candidate in self._read_selection_candidates(pool.pool_name)
                if candidate.queue_item_id not in attempted_item_ids
            )
            evaluation = _evaluate_selection(
                candidates,
                pool_name=pool.pool_name,
                advisory_available_resources=(
                    self._advisory_available_resources(pool)
                    if pool.mode is QueuePoolMode.MANAGED
                    else {}
                ),
                policy=policy,
                filter_resources=pool.mode is QueuePoolMode.MANAGED,
            )
            decision = evaluation.decision
            if decision.disposition is QueueSelectionDisposition.STOPPED:
                return _QueueSelectionAttempt(
                    item=None,
                    decision=decision,
                    steps_used=step,
                    capacity_blocked=(
                        pool.mode is QueuePoolMode.MANAGED
                        and evaluation.source_had_candidates
                        and not evaluation.has_eligible_candidates
                    ),
                    stop_reason=(
                        (
                            decision.reason_code
                            if decision.reason_code
                            in {
                                "queue_selection.invalid_decision",
                                "queue_selection.policy_error",
                            }
                            else _POLICY_STOPPED_REASON_CODE
                        )
                        if evaluation.has_eligible_candidates
                        else None
                    ),
                )
            queue_item_id = decision.queue_item_id
            if queue_item_id is None:
                raise QueueServiceError(
                    "selected queue decision lost its queue_item_id"
                )
            candidate = next(
                candidate
                for candidate in candidates
                if candidate.queue_item_id == queue_item_id
            )
            claimed = self._claim_selection_candidate(
                queue_item_id,
                pool_name=pool.pool_name,
                expected_dispatch_attempt=candidate.dispatch_attempt,
                owner_id=self._owner_id,
                claim_id=self._next_claim_id(),
                preference_id=evaluation.preference_id,
                reason_code=decision.reason_code,
            )
            if claimed is not None:
                return _QueueSelectionAttempt(
                    item=claimed,
                    decision=decision,
                    steps_used=step,
                    capacity_blocked=False,
                    stop_reason=None,
                )
        return _QueueSelectionAttempt(
            item=None,
            decision=decision,
            steps_used=selection_limit,
            capacity_blocked=False,
            stop_reason=_SELECTION_LIMIT_EXHAUSTED_REASON_CODE,
        )

    def _read_selection_candidates(self, pool_name: str) -> tuple[QueueItem, ...]:
        candidates = self._selection_reader(pool_name, limit=_SELECTION_LIMIT)
        if not isinstance(candidates, tuple) or not all(
            isinstance(candidate, QueueItem) for candidate in candidates
        ):
            raise QueueServiceError("repository returned invalid selection candidates")
        return candidates

    def _claim_selection_candidate(
        self,
        queue_item_id: str,
        *,
        pool_name: str,
        expected_dispatch_attempt: int,
        owner_id: str,
        claim_id: str,
        preference_id: str,
        reason_code: str,
    ) -> QueueItem | None:
        item = self._selection_claimer(
            queue_item_id,
            pool_name=pool_name,
            expected_dispatch_attempt=expected_dispatch_attempt,
            owner_id=owner_id,
            claim_id=claim_id,
            preference_id=preference_id,
            reason_code=reason_code,
        )
        if item is not None and not isinstance(item, QueueItem):
            raise QueueServiceError("repository returned invalid selection claim")
        return item

    @staticmethod
    def _require_compensated_pre_start_deferral(
        claimed: QueueItem, deferred: QueueItem
    ) -> None:
        """Reject continuation unless the guarded pre-start requeue is complete."""

        if (
            QueueItemStatus(deferred.status) is not QueueItemStatus.QUEUED
            or deferred.claim is not None
            or deferred.dispatch_handle is not None
            or deferred.dispatch_attempt != claimed.dispatch_attempt
            or deferred.enqueued_at != claimed.enqueued_at
        ):
            raise QueueServiceError(
                "managed selection cannot continue after an unproven pre-start deferral"
            )

    def _advisory_available_resources(self, pool: QueuePool) -> Mapping[str, int]:
        available = dict(pool.resources)
        for item in self._service.recovery_items():
            if item.pool_name != pool.pool_name or QueueItemStatus(item.status) not in {
                QueueItemStatus.CLAIMED,
                QueueItemStatus.DISPATCHED,
            }:
                continue
            for resource_name, amount in item.launch_contract.resources.items():
                available[resource_name] = max(
                    0, available.get(resource_name, 0) - amount
                )
        return available

    def _pool(self, pool_name: str) -> QueuePool:
        for pool in self._service.spec.pools:
            if pool.pool_name == pool_name:
                return pool
        raise QueueServiceError(f"unknown pool: {pool_name}")

    def _dispatch(self, item: QueueItem) -> QueueDispatchResult:
        adapter = self._adapters.get(item.launch_contract.adapter)
        if adapter is None:
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.NOT_STARTED,
                status=QueueItemStatus.UNKNOWN,
                reason_code="queue_dispatch.adapter_unavailable",
                evidence={"adapter": item.launch_contract.adapter, "available": False},
                non_start_cause=QueueDispatchNonStartCause.INVALID_OR_UNSUPPORTED,
                cleanup_status=QueuePreStartCleanupStatus.NOT_REQUIRED,
            )
        result = adapter.dispatch(item)
        if not isinstance(result, QueueDispatchResult):
            raise QueueServiceError("dispatch adapter returned an invalid result type")
        return result

    def _safe_dispatch(self, item: QueueItem) -> QueueDispatchResult:
        try:
            return self._dispatch(item)
        except Exception as exc:  # noqa: BLE001
            return QueueDispatchResult(
                disposition=QueueDispatchDisposition.START_UNCERTAIN,
                status=QueueItemStatus.UNKNOWN,
                reason_code="queue_dispatch.adapter_exception",
                evidence={
                    "adapter": item.launch_contract.adapter,
                    "exception_type": type(exc).__name__,
                },
            )

    def _apply_dispatch_result(
        self,
        item: QueueItem,
        result: QueueDispatchResult,
        deadlines: list[str],
    ) -> _QueueDispatchTransition:
        """Persist one factual adapter result and decide the sole queue transition."""

        if result.is_safe_capacity_non_start:
            deferred = self._service.defer_item(
                item.queue_item_id, reason_code=result.reason_code, expected=item
            )
            self._require_compensated_pre_start_deferral(item, deferred)
            return _QueueDispatchTransition(
                QueueControllerStep("deferred", deferred),
                continue_cycle=True,
                capacity_blocked=True,
            )
        if result.disposition is QueueDispatchDisposition.NOT_STARTED:
            assert result.non_start_cause is not None
            assert result.cleanup_status is not None
            invalid = (
                result.non_start_cause
                is QueueDispatchNonStartCause.INVALID_OR_UNSUPPORTED
            )
            completed = self._service.complete_item(
                item.queue_item_id,
                status=QueueItemStatus.FAILED if invalid else QueueItemStatus.UNKNOWN,
                reason=result.reason_code,
                expected=item,
                evidence=self._completion_evidence(result),
            )
            safe_invalid = invalid and (
                result.cleanup_status
                in {
                    QueuePreStartCleanupStatus.NOT_REQUIRED,
                    QueuePreStartCleanupStatus.CONFIRMED,
                }
            )
            return _QueueDispatchTransition(
                QueueControllerStep("failed" if safe_invalid else "unknown", completed),
                continue_cycle=safe_invalid,
            )
        if result.disposition is QueueDispatchDisposition.START_UNCERTAIN:
            completed = self._service.complete_item(
                item.queue_item_id,
                status=QueueItemStatus.UNKNOWN,
                reason=result.reason_code,
                expected=item,
                evidence=self._completion_evidence(result),
            )
            return _QueueDispatchTransition(
                QueueControllerStep("unknown", completed), continue_cycle=False
            )
        handle = DispatchHandle(
            adapter=item.launch_contract.adapter,
            handle_id=cast(str, result.handle_id),
            dispatched_at=self._clock(),
            dispatch_attempt=item.dispatch_attempt,
            evidence=_thaw_evidence(result.evidence),
        )
        try:
            persisted = self._service.record_dispatch_handle(
                item.queue_item_id, handle, expected=item
            )
        except Exception:
            self._compensate_uncommitted_start(item, handle)
            raise
        if result.disposition is QueueDispatchDisposition.COMPLETED:
            completed = self._service.complete_item(
                item.queue_item_id,
                status=result.status,
                reason=result.reason_code,
                expected=persisted,
            )
            return _QueueDispatchTransition(
                QueueControllerStep("dispatched", completed, handle),
                continue_cycle=result.status is not QueueItemStatus.UNKNOWN,
            )
        self._owned_handle_ids.add(handle.handle_id)
        if result.next_maintenance_at is not None:
            deadlines.append(result.next_maintenance_at)
        return _QueueDispatchTransition(
            QueueControllerStep("dispatched", persisted, handle), continue_cycle=True
        )

    @staticmethod
    def _completion_evidence(result: QueueDispatchResult) -> Mapping[str, PlainData]:
        evidence = dict(_thaw_evidence(result.evidence))
        evidence["queue_dispatch"] = {
            "disposition": result.disposition.value,
            "non_start_cause": None
            if result.non_start_cause is None
            else result.non_start_cause.value,
            "cleanup_status": None
            if result.cleanup_status is None
            else result.cleanup_status.value,
        }
        return evidence

    def _reconcile_all(
        self, pool_name: str
    ) -> tuple[list[QueueControllerStep], bool, list[str]]:
        steps: list[QueueControllerStep] = []
        degraded = False
        deadlines: list[str] = []
        for item in self._service.recovery_items():
            if item.pool_name != pool_name:
                continue
            if not self._owned_by_current_session(item):
                continue
            try:
                step = self._reconcile_item(item, deadlines)
            except Exception:  # an item-local failure is recorded and fill is stopped
                degraded = True
                steps.append(QueueControllerStep("degraded", item))
                continue
            steps.append(step)
            if step.outcome in {"unknown", "degraded"}:
                degraded = True
        return steps, degraded, deadlines

    def _reconcile_item(
        self, item: QueueItem, deadlines: list[str]
    ) -> QueueControllerStep:
        if item.queue_item_id in self._pending_start_compensations:
            return self._reconcile_pending_start(item, deadlines)
        if QueueItemStatus(item.status) is QueueItemStatus.CLAIMED:
            return self._complete_unknown(
                item,
                reason="queue item was claimed but no dispatch handle was recorded",
                evidence={"recovery_needed": True, "recovery_status": "claimed"},
            )
        adapter = self._adapters.get(item.launch_contract.adapter)
        if adapter is None or not isinstance(adapter, QueueInspectableDispatchAdapter):
            return self._complete_unknown(
                item,
                reason=f"adapter status unavailable: {item.launch_contract.adapter}",
                evidence={
                    "adapter": item.launch_contract.adapter,
                    "recovery_needed": True,
                },
            )
        inspection = adapter.inspect(item)
        if inspection.next_maintenance_at is not None:
            deadlines.append(inspection.next_maintenance_at)
        if not inspection.terminal:
            if inspection.degraded:
                return QueueControllerStep("degraded", item)
            return QueueControllerStep(
                "handoff" if inspection.handoff_complete else "active", item
            )
        if inspection.status is QueueItemStatus.CANCELLED:
            return QueueControllerStep(
                "cancelled",
                self._service.cancel_item(
                    item.queue_item_id,
                    requested_by=self._owner_id,
                    reason=inspection.reason,
                    evidence=_thaw_evidence(inspection.evidence),
                    expected=item,
                ),
            )
        return QueueControllerStep(
            "completed",
            self._service.complete_item(
                item.queue_item_id,
                status=inspection.status,
                reason=inspection.reason,
                expected=item,
            ),
        )

    def _active_count(self, pool_name: str) -> int:
        return sum(
            1
            for item in self._service.recovery_items()
            if item.pool_name == pool_name
            and QueueItemStatus(item.status)
            in {QueueItemStatus.CLAIMED, QueueItemStatus.DISPATCHED}
        )

    def _owned_by_current_session(self, item: QueueItem) -> bool:
        if QueueItemStatus(item.status) is QueueItemStatus.CLAIMED:
            return (
                item.claim is not None
                and item.claim.owner_id == self._owner_id
                and f":{self._session_id}:" in item.claim.claim_id
            )
        if item.dispatch_handle is None:
            return False
        if item.launch_contract.adapter != "local":
            # Scheduler and other durable adapters retain their established
            # cross-controller recovery behavior.  Session fencing is needed
            # only for the in-memory managed-local process owner.
            return True
        managed = item.dispatch_handle.evidence.get("managed_local")
        if not isinstance(managed, Mapping):
            return item.dispatch_handle.handle_id in self._owned_handle_ids
        adapter = self._adapters.get(item.launch_contract.adapter)
        session_id = getattr(adapter, "session_id", None)
        return isinstance(session_id, str) and managed.get("session_id") == session_id

    def _compensate_uncommitted_start(
        self, item: QueueItem, handle: DispatchHandle
    ) -> None:
        adapter = self._adapters.get(item.launch_contract.adapter)
        if adapter is None or not isinstance(adapter, QueueCancellableDispatchAdapter):
            return
        live_item = replace(
            item,
            status=QueueItemStatus.DISPATCHED,
            dispatch_handle=handle,
            updated_at=handle.dispatched_at,
        )
        self._pending_start_compensations[item.queue_item_id] = live_item
        try:
            cancellation = adapter.cancel(
                live_item,
                requested_by=self._owner_id,
                reason="queue-handle-commit-failed",
            )
        except Exception:  # cleanup remains owned for later reconciliation
            return
        if cancellation.evidence.get("exit_observed") is not False:
            self._pending_start_compensations.pop(item.queue_item_id, None)

    def _reconcile_pending_start(
        self, item: QueueItem, deadlines: list[str]
    ) -> QueueControllerStep:
        live_item = self._pending_start_compensations[item.queue_item_id]
        adapter = self._adapters.get(live_item.launch_contract.adapter)
        if adapter is None or not isinstance(adapter, QueueInspectableDispatchAdapter):
            return QueueControllerStep("degraded", item)
        inspection = adapter.inspect(live_item)
        if inspection.next_maintenance_at is not None:
            deadlines.append(inspection.next_maintenance_at)
        if not inspection.terminal:
            return QueueControllerStep(
                "degraded" if inspection.degraded else "active", item
            )
        if inspection.evidence.get("resource_leases_released") is False:
            return QueueControllerStep("degraded", item)
        handle = live_item.dispatch_handle
        if handle is None:
            raise QueueServiceError("pending start compensation lost its handle")
        self._pending_start_compensations.pop(item.queue_item_id, None)
        persisted = self._service.record_dispatch_handle(
            item.queue_item_id, handle, expected=item
        )
        if inspection.status is QueueItemStatus.CANCELLED:
            terminal = self._service.cancel_item(
                item.queue_item_id,
                requested_by=self._owner_id,
                reason=inspection.reason,
                evidence=_thaw_evidence(inspection.evidence),
                expected=persisted,
            )
            return QueueControllerStep("cancelled", terminal, handle)
        terminal = self._service.complete_item(
            item.queue_item_id,
            status=inspection.status,
            reason=inspection.reason,
            expected=persisted,
        )
        return QueueControllerStep("completed", terminal, handle)

    def _complete_unknown(
        self,
        item: QueueItem,
        *,
        reason: str,
        evidence: Mapping[str, PlainData],
    ) -> QueueControllerStep:
        if QueueItemStatus(item.status) is QueueItemStatus.CLAIMED:
            handle = DispatchHandle(
                adapter=item.launch_contract.adapter,
                handle_id=f"recovery-needed:{item.queue_item_id}:{item.dispatch_attempt}",
                dispatched_at=self._clock(),
                dispatch_attempt=item.dispatch_attempt,
                evidence=evidence,
            )
            item = self._service.record_dispatch_handle(
                item.queue_item_id, handle, expected=item
            )
        completed = self._service.complete_item(
            item.queue_item_id,
            status=QueueItemStatus.UNKNOWN,
            reason=reason,
            expected=item,
        )
        return QueueControllerStep(outcome="unknown", item=completed)

    def _next_claim_id(self) -> str:
        return f"{self._owner_id}:claim:{self._session_id}:{uuid4().hex}"


def _thaw_evidence(evidence: Mapping[str, PlainData]) -> Mapping[str, PlainData]:
    thawed = thaw_plain_data(evidence, path="evidence")
    if not isinstance(thawed, Mapping):
        raise QueueServiceError("evidence must be a mapping")
    return cast(Mapping[str, PlainData], thawed)


def _safe_reason_code(value: object) -> str:
    if not isinstance(value, str) or _SAFE_REASON_CODE_RE.fullmatch(value) is None:
        raise QueueServiceError("reason_code must be a 1-128 character safe ASCII code")
    return value


__all__ = [
    "FakeQueueDispatchAdapter",
    "QueueCancellableDispatchAdapter",
    "QueueController",
    "QueueCycleResult",
    "QueueRecoveryClassification",
    "QueueControllerStep",
    "QueueDispatchAdapter",
    "QueueDispatchCancellation",
    "QueueDispatchDisposition",
    "QueueDispatchInspection",
    "QueueDispatchNonStartCause",
    "QueueDispatchResult",
    "QueueDrainResult",
    "QueueInspectableDispatchAdapter",
    "QueuePreStartCleanupStatus",
]
