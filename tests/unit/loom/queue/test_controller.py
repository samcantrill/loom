"""Unit coverage for queue controller entrypoints."""

from __future__ import annotations

from pathlib import Path

from loom.queue import (
    FakeQueueDispatchAdapter,
    QueueController,
    QueueDispatchCancellation,
    QueueDispatchInspection,
    QueueDispatchResult,
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


def test_controller_keeps_non_terminal_dispatch_active_until_adapter_completion(
    tmp_path: Path,
) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
        "2020-01-01T00:00:04Z",
    )
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            adapter="async",
        )
    )
    adapter = _AsyncAdapter()
    controller = QueueController(service, adapters={"async": adapter}, clock=clock)

    dispatched = controller.run_once(pool_name="gpu-pool")
    active = controller.run_once(pool_name="gpu-pool")
    adapter.complete = True
    completed = controller.run_once(pool_name="gpu-pool")

    assert dispatched.item is not None
    assert dispatched.item.status is QueueItemStatus.DISPATCHED
    assert active.outcome == "active"
    assert completed.outcome == "completed"
    assert completed.item is not None
    assert completed.item.status is QueueItemStatus.SUCCEEDED
    assert service.scan_recovery() == ()


def test_controller_cancels_active_dispatch_through_adapter(tmp_path: Path) -> None:
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
            adapter="async",
        )
    )
    adapter = _AsyncAdapter()
    controller = QueueController(service, adapters={"async": adapter}, clock=clock)
    controller.run_once(pool_name="gpu-pool")

    cancelled = controller.cancel_item(
        "item-1",
        requested_by="operator",
        reason="stop",
    )

    assert cancelled.outcome == "cancelled"
    assert cancelled.item is not None
    assert cancelled.item.status is QueueItemStatus.CANCELLED
    assert adapter.cancelled is True
    assert cancelled.item.cancellation is not None
    assert cancelled.item.cancellation.evidence["adapter_cancelled"] is True
    assert service.scan_recovery() == ()


def test_controller_pool_scoped_run_once_ignores_other_pool_active_work(
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
    )
    service = _two_pool_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="gpu-item",
            queue_name="gpu",
            run_uri="file:///runs/gpu-item",
            adapter="async",
        )
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="cpu-item",
            queue_name="cpu",
            run_uri="file:///runs/cpu-item",
        )
    )
    adapter = _AsyncAdapter()
    controller = QueueController(
        service,
        adapters={"async": adapter, "fake": FakeQueueDispatchAdapter()},
        clock=clock,
    )

    gpu = controller.run_once(pool_name="gpu-pool")
    cpu = controller.run_once(pool_name="cpu-pool")

    assert gpu.item is not None
    assert gpu.item.status is QueueItemStatus.DISPATCHED
    assert cpu.item is not None
    assert cpu.item.queue_item_id == "cpu-item"
    assert cpu.item.status is QueueItemStatus.SUCCEEDED


def test_foreground_drain_stops_after_delegated_handoff(tmp_path: Path) -> None:
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
            adapter="delegated",
        )
    )
    adapter = _DelegatedHandoffAdapter()
    controller = QueueController(service, adapters={"delegated": adapter}, clock=clock)

    result = controller.drain_foreground(poll_interval_seconds=0)

    assert [step.outcome for step in result.steps] == ["dispatched", "handoff"]
    assert result.steps[-1].item is not None
    assert result.steps[-1].item.status is QueueItemStatus.DISPATCHED
    assert len(result.recovery_records) == 1


def test_daemon_run_once_continues_after_delegated_handoff_when_more_work_is_queued(
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
    )
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            adapter="delegated",
        )
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-2",
            queue_name="gpu",
            run_uri="file:///runs/item-2",
        )
    )
    controller = QueueController(
        service,
        adapters={
            "delegated": _DelegatedHandoffAdapter(),
            "fake": FakeQueueDispatchAdapter(),
        },
        clock=clock,
    )

    first = controller.run_once(pool_name="gpu-pool")
    second = controller.run_once(pool_name="gpu-pool")
    handoff = controller.run_once(pool_name="gpu-pool")

    assert first.item is not None
    assert first.item.queue_item_id == "item-1"
    assert first.item.status is QueueItemStatus.DISPATCHED
    assert second.item is not None
    assert second.item.queue_item_id == "item-2"
    assert second.item.status is QueueItemStatus.SUCCEEDED
    assert handoff.outcome == "handoff"


class _AsyncAdapter:
    adapter_name = "async"

    def __init__(self) -> None:
        self.complete = False
        self.cancelled = False

    def dispatch(self, item) -> QueueDispatchResult:  # noqa: ANN001
        return QueueDispatchResult(
            handle_id=f"async:{item.queue_item_id}",
            status=QueueItemStatus.DISPATCHED,
            reason="async-dispatched",
            evidence={"queue_item_id": item.queue_item_id},
            complete=False,
        )

    def inspect(self, item) -> QueueDispatchInspection:  # noqa: ANN001
        if self.complete:
            return QueueDispatchInspection(
                status=QueueItemStatus.SUCCEEDED,
                reason="async-completed",
                terminal=True,
            )
        return QueueDispatchInspection(
            status=QueueItemStatus.DISPATCHED,
            reason="async-active",
        )

    def cancel(
        self,
        item,  # noqa: ANN001
        *,
        requested_by: str,
        reason: str,
    ) -> QueueDispatchCancellation:
        self.cancelled = True
        return QueueDispatchCancellation(
            reason=reason,
            evidence={"adapter_cancelled": True, "requested_by": requested_by},
        )


class _DelegatedHandoffAdapter:
    adapter_name = "delegated"

    def dispatch(self, item) -> QueueDispatchResult:  # noqa: ANN001
        return QueueDispatchResult(
            handle_id=f"delegated:{item.queue_item_id}",
            status=QueueItemStatus.DISPATCHED,
            reason="delegated-dispatched",
            evidence={"queue_item_id": item.queue_item_id},
            complete=False,
        )

    def inspect(self, item) -> QueueDispatchInspection:  # noqa: ANN001
        return QueueDispatchInspection(
            status=QueueItemStatus.DISPATCHED,
            reason="delegated-handoff-complete",
            terminal=False,
            handoff_complete=True,
        )


def _started_service(tmp_path: Path, *, clock) -> QueueService:
    spec = _spec(tmp_path)
    repository = SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock)
    service = QueueService(spec, repository, clock=clock)
    service.start()
    return service


def _two_pool_service(tmp_path: Path, *, clock) -> QueueService:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "gpu-pool", "mode": "managed"},
                {"pool_name": "cpu-pool", "mode": "managed"},
            ],
            "queues": [
                {"queue_name": "gpu", "pool_name": "gpu-pool"},
                {"queue_name": "cpu", "pool_name": "cpu-pool"},
            ],
        }
    )
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
