"""Queue repository contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loom.serialization import PlainData

from .models import (
    CancellationRecord,
    DispatchHandle,
    QueueAuditEvent,
    QueueItem,
    QueueItemStatus,
    QueueRecoveryRecord,
)


@dataclass(frozen=True, slots=True)
class QueuePoolSnapshot:
    """One deterministic repository read of every item in a selected pool."""

    pool_name: str
    items: tuple[QueueItem, ...]


@runtime_checkable
class QueueRepository(Protocol):
    """Repository operations required by the first queue persistence phase."""

    def enqueue(self, item: QueueItem) -> QueueItem: ...

    def read_item(self, queue_item_id: str) -> QueueItem | None: ...

    def read_pool_snapshot(self, pool_name: str) -> QueuePoolSnapshot: ...

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
        evidence: Mapping[str, PlainData] | None = None,
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
    "QueuePoolSnapshot",
    "QueueRepository",
]
