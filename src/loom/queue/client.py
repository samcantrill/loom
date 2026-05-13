"""Queue client facade."""

from __future__ import annotations

from collections.abc import Mapping

from loom.serialization import PlainData

from .models import QueueItem
from .service import (
    QueueEnqueueRequest,
    QueueItemInspection,
    QueueService,
    QueueServiceStatus,
)


class QueueClient:
    """Transport-neutral client facade for one queue service."""

    def __init__(self, service: QueueService) -> None:
        self._service = service

    def start_service(self) -> QueueServiceStatus:
        return self._service.start()

    def stop_service(self) -> QueueServiceStatus:
        return self._service.stop()

    def service_status(self) -> QueueServiceStatus:
        return self._service.status()

    def enqueue(self, request: QueueEnqueueRequest) -> QueueItem:
        return self._service.enqueue(request)

    def inspect(self, queue_item_id: str) -> QueueItemInspection:
        return self._service.inspect_item(queue_item_id)

    def cancel(
        self,
        queue_item_id: str,
        *,
        requested_by: str = "queue-client",
        reason: str = "client-requested",
        evidence: Mapping[str, PlainData] | None = None,
    ) -> QueueItem:
        return self._service.cancel_item(
            queue_item_id,
            requested_by=requested_by,
            reason=reason,
            evidence=evidence,
        )

    def run_controller_once(self, *, pool_name: str | None = None):
        from .controller import QueueController

        return QueueController(self._service).run_once(pool_name=pool_name)

    def drain_foreground(self, *, pool_name: str | None = None, max_items: int | None = None):
        from .controller import QueueController

        return QueueController(self._service).drain_foreground(
            pool_name=pool_name,
            max_items=max_items,
        )


__all__ = ["QueueClient"]
