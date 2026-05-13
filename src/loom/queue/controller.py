"""Python controller entrypoints for queue dispatch loops."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast, runtime_checkable

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import utc_timestamp

from .errors import QueueServiceError
from .models import DispatchHandle, QueueItem, QueueItemStatus, QueueRecoveryRecord
from .service import QueueService


@dataclass(frozen=True, slots=True)
class QueueDispatchResult:
    """Result returned by a queue dispatch adapter."""

    handle_id: str
    status: QueueItemStatus = QueueItemStatus.SUCCEEDED
    reason: str = "fake-dispatch-completed"
    evidence: Mapping[str, PlainData] = field(default_factory=dict)
    complete: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.handle_id, str) or not self.handle_id:
            raise QueueServiceError("handle_id must be a non-empty string")
        status = QueueItemStatus(self.status)
        if self.complete:
            if status not in {
                QueueItemStatus.SUCCEEDED,
                QueueItemStatus.FAILED,
                QueueItemStatus.UNKNOWN,
            }:
                raise QueueServiceError(
                    "completed dispatch result status must be SUCCEEDED, FAILED, or UNKNOWN"
                )
        elif status is not QueueItemStatus.DISPATCHED:
            raise QueueServiceError("active dispatch result status must be DISPATCHED")
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

    def __post_init__(self) -> None:
        status = QueueItemStatus(self.status)
        if not isinstance(self.handoff_complete, bool):
            raise QueueServiceError("handoff_complete must be a boolean")
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
        self._adapters = dict(adapters) if adapters is not None else {"fake": FakeQueueDispatchAdapter()}
        self._owner_id = owner_id or service.spec.controller.owner_id
        self._clock = clock
        self._claim_counter = 0

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
            try:
                result = self._dispatch(item)
            except Exception as exc:  # noqa: BLE001
                result = QueueDispatchResult(
                    handle_id=f"dispatch-error:{item.queue_item_id}:{item.dispatch_attempt}",
                    status=QueueItemStatus.UNKNOWN,
                    reason="adapter dispatch failed",
                    evidence={
                        "adapter": item.launch_contract.adapter,
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    },
                )
            handle = DispatchHandle(
                adapter=item.launch_contract.adapter,
                handle_id=result.handle_id,
                dispatched_at=self._clock(),
                dispatch_attempt=item.dispatch_attempt,
                evidence=_thaw_evidence(result.evidence),
            )
            self._service.record_dispatch_handle(item.queue_item_id, handle)
            if result.complete:
                completed = self._service.complete_item(
                    item.queue_item_id,
                    status=result.status,
                    reason=result.reason,
                )
            else:
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
            if QueueItemStatus(item.status) is QueueItemStatus.CLAIMED:
                return self._complete_unknown(
                    item,
                    reason="queue item was claimed but no dispatch handle was recorded",
                    evidence={"recovery_needed": True, "recovery_status": "claimed"},
                )
            if QueueItemStatus(item.status) is not QueueItemStatus.DISPATCHED:
                continue
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
                )
                return QueueControllerStep(outcome="cancelled", item=cancelled)
            completed = self._service.complete_item(
                item.queue_item_id,
                status=inspection.status,
                reason=inspection.reason,
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
        evidence: Mapping[str, PlainData] = {}
        if QueueItemStatus(item.status) is QueueItemStatus.DISPATCHED:
            adapter = self._adapters.get(item.launch_contract.adapter)
            if adapter is not None and isinstance(adapter, QueueCancellableDispatchAdapter):
                cancellation = adapter.cancel(
                    item,
                    requested_by=requested_by,
                    reason=reason,
                )
                evidence = cancellation.evidence
                reason = cancellation.reason
        evidence = _thaw_evidence(evidence)
        cancelled = self._service.cancel_item(
            queue_item_id,
            requested_by=requested_by,
            reason=reason,
            evidence=evidence,
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
            item = self._service.record_dispatch_handle(item.queue_item_id, handle)
        completed = self._service.complete_item(
            item.queue_item_id,
            status=QueueItemStatus.UNKNOWN,
            reason=reason,
        )
        return QueueControllerStep(outcome="unknown", item=completed)

    def _next_claim_id(self) -> str:
        self._claim_counter += 1
        return f"{self._owner_id}:claim:{self._claim_counter}"


def _thaw_evidence(evidence: Mapping[str, PlainData]) -> Mapping[str, PlainData]:
    thawed = thaw_plain_data(evidence, path="evidence")
    if not isinstance(thawed, Mapping):
        raise QueueServiceError("evidence must be a mapping")
    return cast(Mapping[str, PlainData], thawed)


__all__ = [
    "FakeQueueDispatchAdapter",
    "QueueCancellableDispatchAdapter",
    "QueueController",
    "QueueControllerStep",
    "QueueDispatchAdapter",
    "QueueDispatchCancellation",
    "QueueDispatchInspection",
    "QueueDispatchResult",
    "QueueDrainResult",
    "QueueInspectableDispatchAdapter",
]
