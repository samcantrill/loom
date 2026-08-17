"""Queue repository contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .models import (
    CancellationRecord,
    DispatchHandle,
    QueueAuditEvent,
    QueueItem,
    QueueItemStatus,
    QueueRecoveryRecord,
)


@dataclass(frozen=True, slots=True)
class QueueClaimResult:
    """Result returned by FIFO queue item claims."""

    item: QueueItem


@runtime_checkable
class QueueRepository(Protocol):
    """Repository operations required by the first queue persistence phase."""

    def enqueue(self, item: QueueItem) -> QueueItem: ...

    def read_item(self, queue_item_id: str) -> QueueItem | None: ...

    def claim_next(
        self,
        pool_name: str,
        *,
        owner_id: str,
        claim_id: str,
    ) -> QueueClaimResult | None: ...

    def record_dispatch_handle(
        self,
        queue_item_id: str,
        handle: DispatchHandle,
        *,
        expected: QueueItem,
    ) -> QueueItem: ...

    def complete_item(
        self,
        queue_item_id: str,
        *,
        status: QueueItemStatus,
        reason: str,
        expected: QueueItem,
    ) -> QueueItem: ...

    def request_cancellation(
        self,
        queue_item_id: str,
        cancellation: CancellationRecord,
        *,
        expected: QueueItem | None = None,
    ) -> QueueItem: ...

    def defer_item(
        self,
        queue_item_id: str,
        *,
        reason_code: str,
        expected: QueueItem,
    ) -> QueueItem: ...

    def scan_recovery(self) -> tuple[QueueRecoveryRecord, ...]: ...

    def list_audit_events(self, queue_item_id: str) -> tuple[QueueAuditEvent, ...]: ...


__all__ = [
    "QueueClaimResult",
    "QueueRepository",
]
