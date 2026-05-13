"""Unit coverage for queue service and client APIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.queue import (
    QueueClient,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    QueueServiceSpec,
    QueueServiceState,
    QueueServiceStateError,
    SQLiteQueueRepository,
    normalize_queue_spec,
)


def test_queue_client_controls_service_and_enqueues_item(tmp_path: Path) -> None:
    service = _service(tmp_path, clock=_clock("2020-01-01T00:00:00Z"))
    client = QueueClient(service)

    assert client.start_service().state is QueueServiceState.RUNNING
    item = client.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            request={"config": "config.yaml"},
            tags={"project": "demo"},
        )
    )
    inspection = client.inspect("item-1")

    assert item.status is QueueItemStatus.QUEUED
    assert item.pool_name == "gpu-pool"
    assert inspection.item == item
    assert [event.event_type for event in inspection.audit_events] == [
        "queue.item.enqueued"
    ]
    assert client.stop_service().state is QueueServiceState.STOPPED


def test_service_rejects_operations_while_stopped(tmp_path: Path) -> None:
    service = _service(tmp_path, clock=_clock("2020-01-01T00:00:00Z"))

    with pytest.raises(QueueServiceStateError, match="not running"):
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id="item-1",
                queue_name="gpu",
                run_uri="file:///runs/item-1",
            )
        )


def test_queue_client_cancel_records_queue_local_evidence(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        clock=_clock(
            "2020-01-01T00:00:00Z",
            "2020-01-01T00:00:01Z",
        ),
    )
    client = QueueClient(service)
    client.start_service()
    client.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
        )
    )

    cancelled = client.cancel(
        "item-1",
        requested_by="tester",
        reason="no-longer-needed",
        evidence={"source": "unit"},
    )

    assert cancelled.status is QueueItemStatus.CANCELLED
    assert cancelled.cancellation is not None
    assert cancelled.cancellation.evidence == {"source": "unit"}


def _service(tmp_path: Path, *, clock) -> QueueService:
    spec = _spec(tmp_path)
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock)
    return QueueService(spec, repository, clock=clock)


def _spec(tmp_path: Path) -> QueueServiceSpec:
    return normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [{"pool_name": "gpu-pool", "mode": "managed"}],
            "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
        }
    )


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
