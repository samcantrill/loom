"""Python controller entrypoints for queue dispatch loops."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable
from uuid import uuid4

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_timestamp

from .errors import QueueServiceError
from .models import DispatchHandle, QueueItem, QueueItemStatus, QueueRecoveryRecord
from .service import QueueService


class QueueDispatchDisposition(StrEnum):
    """Canonical externally observable dispatch outcomes."""

    STARTED = "started"
    COMPLETED = "completed"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class QueueDispatchResult:
    """Result returned by a queue dispatch adapter."""

    handle_id: str | None = None
    status: QueueItemStatus = QueueItemStatus.SUCCEEDED
    reason: str = "fake-dispatch-completed"
    evidence: Mapping[str, PlainData] = field(default_factory=dict)
    complete: bool = True
    disposition: QueueDispatchDisposition | str | None = None
    next_maintenance_at: str | None = None

    def __post_init__(self) -> None:
        status = QueueItemStatus(self.status)
        disposition = (
            (
                QueueDispatchDisposition.COMPLETED
                if self.complete
                else QueueDispatchDisposition.STARTED
            )
            if self.disposition is None
            else QueueDispatchDisposition(self.disposition)
        )
        if disposition is QueueDispatchDisposition.DEFERRED:
            if self.handle_id is not None:
                raise QueueServiceError(
                    "deferred dispatch result cannot have a handle_id"
                )
            if not self.complete or status is QueueItemStatus.DISPATCHED:
                raise QueueServiceError(
                    "deferred dispatch result must be complete before start"
                )
        elif not isinstance(self.handle_id, str) or not self.handle_id:
            raise QueueServiceError(
                "dispatch result handle_id must be a non-empty string"
            )
        if disposition is QueueDispatchDisposition.COMPLETED:
            if not self.complete:
                raise QueueServiceError("completed dispatch result must be complete")
            if status not in {
                QueueItemStatus.SUCCEEDED,
                QueueItemStatus.FAILED,
                QueueItemStatus.UNKNOWN,
            }:
                raise QueueServiceError(
                    "completed dispatch result status must be SUCCEEDED, FAILED, or UNKNOWN"
                )
        elif disposition is QueueDispatchDisposition.STARTED and (
            self.complete or status is not QueueItemStatus.DISPATCHED
        ):
            raise QueueServiceError("active dispatch result status must be DISPATCHED")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "disposition", disposition)
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
            handle_id=f"fake:{item.queue_item_id}:{item.dispatch_attempt}",
            status=QueueItemStatus.SUCCEEDED,
            reason="fake-dispatch-completed",
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

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "reconciliation_steps": [
                step.to_dict() for step in self.reconciliation_steps
            ],
            "dispatch_steps": [step.to_dict() for step in self.dispatch_steps],
            "active_count": self.active_count,
            "capacity_blocked": self.capacity_blocked,
            "next_maintenance_at": self.next_maintenance_at,
        }


@dataclass(frozen=True, slots=True)
class QueueRecoveryClassification:
    """Current-controller versus other-session recovery work for one pool."""

    current_items: tuple[QueueItem, ...]
    foreign_items: tuple[QueueItem, ...]


class QueueController:
    """Claim queued items and dispatch them through injected adapters."""

    def __init__(
        self,
        service: QueueService,
        *,
        adapters: Mapping[str, QueueDispatchAdapter] | None = None,
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

    def run_cycle(self, *, pool_name: str) -> QueueCycleResult:
        """Reconcile one pool then fill it within its controller-local budgets."""
        if not isinstance(pool_name, str) or not pool_name:
            raise QueueServiceError("run_cycle requires one non-empty pool_name")
        reconciliation, degraded, deadlines = self._reconcile_all(pool_name)
        active_count = self._active_count(pool_name)
        dispatch_steps: list[QueueControllerStep] = []
        capacity_blocked = False
        if not degraded:
            limit = self._service.spec.controller.max_active_items
            budget = self._service.spec.controller.max_dispatches_per_cycle or limit
            while active_count < limit and len(dispatch_steps) < budget:
                claim = self._service.claim_next(
                    pool_name, owner_id=self._owner_id, claim_id=self._next_claim_id()
                )
                if claim is None:
                    break
                item = claim.item
                result = self._safe_dispatch(item)
                if result.disposition is QueueDispatchDisposition.DEFERRED:
                    deferred = self._service.defer_item(
                        item.queue_item_id, reason_code=result.reason, expected=item
                    )
                    dispatch_steps.append(QueueControllerStep("deferred", deferred))
                    capacity_blocked = True
                    break
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
                    persisted = self._service.complete_item(
                        item.queue_item_id,
                        status=result.status,
                        reason=result.reason,
                        expected=persisted,
                    )
                else:
                    active_count += 1
                    self._owned_handle_ids.add(handle.handle_id)
                    if result.next_maintenance_at is not None:
                        deadlines.append(result.next_maintenance_at)
                dispatch_steps.append(
                    QueueControllerStep("dispatched", persisted, handle)
                )
                if result.status is QueueItemStatus.UNKNOWN:
                    break
        return QueueCycleResult(
            reconciliation_steps=tuple(reconciliation),
            dispatch_steps=tuple(dispatch_steps),
            active_count=self._active_count(pool_name),
            capacity_blocked=capacity_blocked,
            next_maintenance_at=min(deadlines) if deadlines else None,
        )

    def classify_recovery(self, *, pool_name: str) -> QueueRecoveryClassification:
        """Classify active selected-pool work without inspecting or mutating it."""

        if not isinstance(pool_name, str) or not pool_name:
            raise QueueServiceError("classify_recovery requires one non-empty pool_name")
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
            claim = self._service.claim_next(
                candidate_pool,
                owner_id=self._owner_id,
                claim_id=self._next_claim_id(),
            )
            if claim is None:
                continue
            item = claim.item
            result = self._safe_dispatch(item)
            if result.disposition is QueueDispatchDisposition.DEFERRED:
                deferred = self._service.defer_item(
                    item.queue_item_id, reason_code=result.reason, expected=item
                )
                return QueueControllerStep(outcome="deferred", item=deferred)
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
                    reason=result.reason,
                    expected=persisted,
                )
            else:
                self._owned_handle_ids.add(handle.handle_id)
                completed = self._service.read_item(item.queue_item_id)
                if completed is None:
                    raise QueueServiceError(
                        f"queue item disappeared after dispatch: {item.queue_item_id}"
                    )
            return QueueControllerStep(
                outcome="dispatched",
                item=completed,
                dispatch_handle=handle,
            )
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

    def _dispatch(self, item: QueueItem) -> QueueDispatchResult:
        adapter = self._adapters.get(item.launch_contract.adapter)
        if adapter is None:
            return QueueDispatchResult(
                handle_id=f"unavailable:{item.queue_item_id}:{item.dispatch_attempt}",
                status=QueueItemStatus.UNKNOWN,
                reason=f"adapter unavailable: {item.launch_contract.adapter}",
                evidence={"adapter": item.launch_contract.adapter, "available": False},
            )
        return adapter.dispatch(item)

    def _safe_dispatch(self, item: QueueItem) -> QueueDispatchResult:
        try:
            return self._dispatch(item)
        except Exception as exc:  # noqa: BLE001
            return QueueDispatchResult(
                handle_id=f"dispatch-error:{item.queue_item_id}:{item.dispatch_attempt}",
                status=QueueItemStatus.UNKNOWN,
                reason="adapter dispatch failed",
                evidence={
                    "adapter": item.launch_contract.adapter,
                    "exception_type": type(exc).__name__,
                },
            )

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
    "QueueDispatchResult",
    "QueueDrainResult",
    "QueueInspectableDispatchAdapter",
]
