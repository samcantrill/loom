"""Python controller entrypoints for queue dispatch loops."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from loom.serialization import PlainData, freeze_plain_data
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

    def __post_init__(self) -> None:
        if not isinstance(self.handle_id, str) or not self.handle_id:
            raise QueueServiceError("handle_id must be a non-empty string")
        status = QueueItemStatus(self.status)
        if status not in {
            QueueItemStatus.SUCCEEDED,
            QueueItemStatus.FAILED,
            QueueItemStatus.UNKNOWN,
        }:
            raise QueueServiceError("dispatch result status must be SUCCEEDED, FAILED, or UNKNOWN")
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
    """Minimal dispatch adapter contract for the Phase 6 controller."""

    adapter_name: str

    def dispatch(self, item: QueueItem) -> QueueDispatchResult: ...


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

    def run_once(self, *, pool_name: str | None = None) -> QueueControllerStep:
        for candidate_pool in self._candidate_pools(pool_name):
            claim = self._service.claim_next(
                candidate_pool,
                owner_id=self._owner_id,
                claim_id=self._next_claim_id(),
            )
            if claim is None:
                continue
            item = claim.item
            result = self._dispatch(item)
            handle = DispatchHandle(
                adapter=item.launch_contract.adapter,
                handle_id=result.handle_id,
                dispatched_at=self._clock(),
                dispatch_attempt=item.dispatch_attempt,
                evidence=result.evidence,
            )
            self._service.record_dispatch_handle(item.queue_item_id, handle)
            completed = self._service.complete_item(
                item.queue_item_id,
                status=result.status,
                reason=result.reason,
            )
            return QueueControllerStep(
                outcome="dispatched",
                item=completed,
                dispatch_handle=handle,
            )
        return QueueControllerStep(outcome="idle")

    def drain_foreground(
        self,
        *,
        pool_name: str | None = None,
        max_items: int | None = None,
    ) -> QueueDrainResult:
        if max_items is not None and max_items < 0:
            raise QueueServiceError("max_items must be non-negative or None")
        steps: list[QueueControllerStep] = []
        while max_items is None or len(steps) < max_items:
            step = self.run_once(pool_name=pool_name)
            if step.outcome == "idle":
                break
            steps.append(step)
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

    def _next_claim_id(self) -> str:
        self._claim_counter += 1
        return f"{self._owner_id}:claim:{self._claim_counter}"


__all__ = [
    "FakeQueueDispatchAdapter",
    "QueueController",
    "QueueControllerStep",
    "QueueDispatchAdapter",
    "QueueDispatchResult",
    "QueueDrainResult",
]
