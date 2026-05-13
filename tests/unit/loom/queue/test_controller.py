"""Unit coverage for queue controller entrypoints."""

from __future__ import annotations

from pathlib import Path

from loom.queue import (
    QueueController,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    QueueServiceSpec,
    SQLiteQueueRepository,
    normalize_queue_spec,
)


def test_controller_run_once_dispatches_one_fake_item(tmp_path: Path) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
    )
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
        )
    )
    controller = QueueController(service, clock=clock)

    step = controller.run_once(pool_name="gpu-pool")

    assert step.outcome == "dispatched"
    assert step.item is not None
    assert step.item.status is QueueItemStatus.SUCCEEDED
    assert step.dispatch_handle is not None
    assert step.dispatch_handle.adapter == "fake"
    assert service.scan_recovery() == ()


def test_foreground_drain_completes_fake_work_without_orphaned_claims(
    tmp_path: Path,
) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
        "2020-01-01T00:00:04Z",
        "2020-01-01T00:00:05Z",
        "2020-01-01T00:00:06Z",
        "2020-01-01T00:00:07Z",
    )
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
        )
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-2",
            queue_name="gpu",
            run_uri="file:///runs/item-2",
        )
    )

    result = QueueController(service, clock=clock).drain_foreground()

    assert [step.item.queue_item_id for step in result.steps if step.item is not None] == [
        "item-1",
        "item-2",
    ]
    assert result.recovery_records == ()


def test_controller_marks_missing_fake_adapter_unknown(tmp_path: Path) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
    )
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            adapter="missing",
        )
    )

    step = QueueController(service, adapters={}, clock=clock).run_once()

    assert step.item is not None
    assert step.item.status is QueueItemStatus.UNKNOWN
    assert service.scan_recovery() == ()


def _started_service(tmp_path: Path, *, clock) -> QueueService:
    spec = _spec(tmp_path)
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock)
    service = QueueService(spec, repository, clock=clock)
    service.start()
    return service


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
