"""Private scheduler-selection helpers for v11 FIFO queues."""

from __future__ import annotations

from collections.abc import Iterable

from .models import QueueItem, QueueItemStatus


def select_fifo_item(
    items: Iterable[QueueItem],
    *,
    pool_name: str | None = None,
) -> QueueItem | None:
    """Return the oldest queued item, optionally within one pool."""

    candidates = [
        item
        for item in items
        if QueueItemStatus(item.status) is QueueItemStatus.QUEUED
        and (pool_name is None or item.pool_name == pool_name)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item.enqueued_at, item.queue_item_id))


__all__ = ["select_fifo_item"]
