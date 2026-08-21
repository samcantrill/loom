"""Unit coverage for queue controller entrypoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from loom.serialization import PlainData
import loom.queue.controller as queue_controller
from loom.queue import (
    FakeQueueDispatchAdapter,
    QueueController,
    QueueDispatchCancellation,
    QueueDispatchDisposition,
    QueueDispatchInspection,
    QueueDispatchResult,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueSelectionContext,
    QueueSelectionDecision,
    QueueSelectionDisposition,
    QueueService,
    QueueServiceError,
    QueueServiceSpec,
    SQLiteQueueRepository,
    normalize_queue_spec,
)


def test_dispatch_result_normalizes_legacy_and_explicit_dispositions() -> None:
    completed = QueueDispatchResult(handle_id="completed")
    started = QueueDispatchResult(
        handle_id="started",
        status=QueueItemStatus.DISPATCHED,
        complete=False,
    )
    deferred = QueueDispatchResult(
        disposition="deferred",
        status=QueueItemStatus.UNKNOWN,
        reason="capacity",
    )

    assert completed.disposition is QueueDispatchDisposition.COMPLETED
    assert started.disposition is QueueDispatchDisposition.STARTED
    assert deferred.disposition is QueueDispatchDisposition.DEFERRED
    assert deferred.handle_id is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "handle_id": "deferred",
                "status": QueueItemStatus.UNKNOWN,
                "disposition": "deferred",
            },
            "cannot have a handle_id",
        ),
        (
            {
                "handle_id": "started",
                "status": QueueItemStatus.SUCCEEDED,
                "complete": False,
                "disposition": "started",
            },
            "active dispatch result status must be DISPATCHED",
        ),
        (
            {
                "handle_id": "completed",
                "status": QueueItemStatus.DISPATCHED,
                "disposition": "completed",
            },
            "completed dispatch result status",
        ),
    ],
)
def test_dispatch_result_rejects_ambiguous_dispositions(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(QueueServiceError, match=message):
        QueueDispatchResult(**kwargs)  # type: ignore[arg-type]


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


def test_managed_selection_uses_oldest_eligible_candidate_and_audits_default(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(10)])
    service = _resource_service(tmp_path, clock=clock, capacity=1)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="b-needs-two",
            queue_name="gpu",
            run_uri="file:///runs/b-needs-two",
            resources={"gpu": 2},
        )
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="a-needs-one",
            queue_name="gpu",
            run_uri="file:///runs/a-needs-one",
            resources={"gpu": 1},
        )
    )

    step = QueueController(service, clock=clock).run_once(pool_name="gpu-pool")

    assert step.item is not None
    assert step.item.queue_item_id == "a-needs-one"
    waiting = service.read_item("b-needs-two")
    assert waiting is not None and waiting.status is QueueItemStatus.QUEUED
    claimed = service.list_audit_events("a-needs-one")[1]
    assert claimed.detail["selection"] == {
        "preference_id": "queue_selection.default",
        "reason_code": "queue_selection.default_oldest_eligible",
    }


def test_managed_selection_policy_is_shared_by_run_once_and_run_cycle(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(30)])
    once_service = _resource_service(tmp_path / "once", clock=clock, capacity=1)
    cycle_service = _resource_service(tmp_path / "cycle", clock=clock, capacity=1)
    for service in (once_service, cycle_service):
        for item_id in ("older", "younger"):
            service.enqueue(
                QueueEnqueueRequest(
                    queue_item_id=item_id,
                    queue_name="gpu",
                    run_uri=f"file:///runs/{item_id}",
                    resources={"gpu": 1},
                )
            )
    once_policy = _NewestPolicy()
    cycle_policy = _NewestPolicy()

    once = QueueController(
        once_service,
        selection_policies={"gpu-pool": once_policy},
        clock=clock,
    ).run_once(pool_name="gpu-pool")
    cycle = QueueController(
        cycle_service,
        selection_policies={"gpu-pool": cycle_policy},
        clock=clock,
    ).run_cycle(pool_name="gpu-pool")

    assert once.item is not None and once.item.queue_item_id == "younger"
    assert [step.item.queue_item_id for step in cycle.dispatch_steps if step.item] == [
        "younger"
    ]
    assert once_policy.calls == cycle_policy.calls == 1


@pytest.mark.parametrize("policy", ["invalid", "raises"])
def test_invalid_or_failing_selection_policy_does_not_claim_item(
    tmp_path: Path, policy: str
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(10)])
    service = _resource_service(tmp_path, clock=clock, capacity=1)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            resources={"gpu": 1},
        )
    )
    selection_policy = (
        _InvalidSelectionPolicy()
        if policy == "invalid"
        else _FailingSelectionPolicy()
    )

    step = QueueController(
        service,
        selection_policies={"gpu-pool": selection_policy},
        clock=clock,
    ).run_once(pool_name="gpu-pool")

    assert step.outcome == "idle"
    item = service.read_item("item-1")
    assert item is not None and item.status is QueueItemStatus.QUEUED
    assert [event.event_type for event in service.list_audit_events("item-1")] == [
        "queue.item.enqueued"
    ]


def test_selection_policy_mapping_rejects_unknown_pool(tmp_path: Path) -> None:
    service = _started_service(tmp_path, clock=_clock("2020-01-01T00:00:00Z"))

    with pytest.raises(QueueServiceError, match="unknown selection policy pool"):
        QueueController(service, selection_policies={"missing": _NewestPolicy()})

    with pytest.raises(QueueServiceError, match="invalid selection policy"):
        QueueController(service, selection_policies={"gpu-pool": _UnsafePolicy()})


def test_selection_policy_mapping_rejects_delegated_pool(tmp_path: Path) -> None:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [{"pool_name": "delegated", "mode": "delegated"}],
            "queues": [{"queue_name": "delegated", "pool_name": "delegated"}],
        }
    )
    service = QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite"),
    )
    service.start()

    with pytest.raises(QueueServiceError, match="not managed"):
        QueueController(service, selection_policies={"delegated": _NewestPolicy()})


def test_controller_rejects_repository_without_private_selection_capabilities(
    tmp_path: Path,
) -> None:
    service = QueueService(_spec(tmp_path), object())  # type: ignore[arg-type]

    with pytest.raises(QueueServiceError, match="bounded selection and exact ownership"):
        QueueController(service)


def test_controller_freezes_policy_identity_but_not_trusted_behavior(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(8)])
    service = _resource_service(tmp_path, clock=clock, capacity=1)
    policy = _MutablePolicy()
    controller = QueueController(
        service,
        selection_policies={"gpu-pool": policy},
        clock=clock,
    )
    policy.policy_id = "test.mutated"
    policy.reason_code = "test.mutated_selected"
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            resources={"gpu": 1},
        )
    )

    step = controller.run_once(pool_name="gpu-pool")

    assert step.item is not None and step.item.status is QueueItemStatus.SUCCEEDED
    assert service.list_audit_events("item-1")[1].detail["selection"] == {
        "preference_id": "test.original",
        "reason_code": "test.mutated_selected",
    }


def test_delegated_selection_uses_shared_fifo_operation_without_resource_filtering(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(8)])
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [{"pool_name": "delegated", "mode": "delegated"}],
            "queues": [{"queue_name": "delegated", "pool_name": "delegated"}],
        }
    )
    service = QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock),
        clock=clock,
    )
    service.start()
    for item_id in ("older", "younger"):
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=item_id,
                queue_name="delegated",
                run_uri=f"file:///runs/{item_id}",
                resources={"gpu": 99},
            )
        )

    step = QueueController(service, clock=clock).run_once(pool_name="delegated")

    assert step.item is not None and step.item.queue_item_id == "older"


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

    assert [
        step.item.queue_item_id for step in result.steps if step.item is not None
    ] == [
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


def test_cycle_defers_fifo_head_once_and_returns_serializable_capacity_result(
    tmp_path: Path,
) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
    )
    service = _started_service(tmp_path, clock=clock)
    for item_id in ("item-1", "item-2"):
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=item_id,
                queue_name="gpu",
                run_uri=f"file:///runs/{item_id}",
                adapter="deferred",
            )
        )
    controller = QueueController(
        service, adapters={"deferred": _DeferredAdapter()}, clock=clock
    )

    result = controller.run_cycle(pool_name="gpu-pool")

    assert [step.outcome for step in result.dispatch_steps] == ["deferred"]
    assert result.capacity_blocked is True
    assert result.active_count == 0
    first_item = service.read_item("item-1")
    second_item = service.read_item("item-2")
    assert first_item is not None
    assert second_item is not None
    assert first_item.status is QueueItemStatus.QUEUED
    assert second_item.status is QueueItemStatus.QUEUED
    assert result.to_dict()["next_maintenance_at"] is None


def test_cycle_bypasses_one_compensated_deferred_item_without_reselecting_it(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(12)])
    service = _started_service(
        tmp_path,
        clock=clock,
        max_active_items=3,
        max_dispatches_per_cycle=3,
    )
    for item_id in ("deferred-head", "next-item"):
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=item_id,
                queue_name="gpu",
                run_uri=f"file:///runs/{item_id}",
                adapter="defer-first",
            )
        )
    adapter = _DeferFirstAdapter()

    result = QueueController(
        service, adapters={adapter.adapter_name: adapter}, clock=clock
    ).run_cycle(pool_name="gpu-pool")

    assert [step.outcome for step in result.dispatch_steps] == [
        "deferred",
        "dispatched",
    ]
    assert adapter.dispatched == ["deferred-head", "next-item"]
    deferred = service.read_item("deferred-head")
    started = service.read_item("next-item")
    assert deferred is not None
    assert deferred.status is QueueItemStatus.QUEUED
    assert deferred.dispatch_attempt == 1
    assert deferred.claim is None and deferred.dispatch_handle is None
    assert started is not None and started.status is QueueItemStatus.SUCCEEDED
    assert result.capacity_blocked is True
    assert result.selection_stop_reason is None


@pytest.mark.parametrize(
    ("policy_name", "expected_reason"),
    [
        ("stopping", "queue_selection.policy_stopped"),
        ("failing", "queue_selection.policy_error"),
        ("invalid", "queue_selection.invalid_decision"),
    ],
)
def test_cycle_exposes_only_allowlisted_selection_stop_reasons(
    tmp_path: Path,
    policy_name: str,
    expected_reason: str,
) -> None:
    service = _resource_service(
        tmp_path,
        clock=_clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(8)]),
        capacity=1,
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            resources={"gpu": 1},
        )
    )

    policy = {
        "stopping": _StoppingSelectionPolicy(),
        "failing": _FailingSelectionPolicy(),
        "invalid": _InvalidSelectionPolicy(),
    }[policy_name]
    result = QueueController(
        service,
        selection_policies={"gpu-pool": policy},
    ).run_cycle(pool_name="gpu-pool")

    assert result.dispatch_steps == ()
    assert result.selection_stop_reason == expected_reason
    assert result.to_dict()["selection_stop_reason"] == expected_reason
    assert "private selection exception" not in str(result.to_dict())
    assert "test.policy_requested_stop" not in str(result.to_dict())


def test_cycle_records_selection_limit_exhaustion_after_lost_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _resource_service(
        tmp_path,
        clock=_clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(8)]),
        capacity=1,
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            resources={"gpu": 1},
        )
    )
    monkeypatch.setattr(queue_controller, "_SELECTION_LIMIT", 2)
    controller = QueueController(service)
    monkeypatch.setattr(controller, "_selection_claimer", lambda *args, **kwargs: None)

    result = controller.run_cycle(pool_name="gpu-pool")

    assert result.dispatch_steps == ()
    assert result.selection_stop_reason == "queue_selection.selection_limit_exhausted"
    item = service.read_item("item-1")
    assert item is not None and item.status is QueueItemStatus.QUEUED


def test_cycle_bounds_synchronous_completions_by_dispatch_budget(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(20)])
    service = _started_service(
        tmp_path,
        clock=clock,
        max_active_items=3,
        max_dispatches_per_cycle=2,
    )
    for item_id in ("item-1", "item-2", "item-3"):
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=item_id,
                queue_name="gpu",
                run_uri=f"file:///runs/{item_id}",
            )
        )

    result = QueueController(service, clock=clock).run_cycle(pool_name="gpu-pool")

    assert [step.item.queue_item_id for step in result.dispatch_steps if step.item] == [
        "item-1",
        "item-2",
    ]
    queued = service.read_item("item-3")
    assert queued is not None
    assert queued.status is QueueItemStatus.QUEUED


def test_cycle_stops_new_starts_at_active_limit(tmp_path: Path) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(20)])
    service = _started_service(
        tmp_path,
        clock=clock,
        max_active_items=2,
        max_dispatches_per_cycle=3,
    )
    for item_id in ("item-1", "item-2", "item-3"):
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=item_id,
                queue_name="gpu",
                run_uri=f"file:///runs/{item_id}",
                adapter="async",
            )
        )

    result = QueueController(
        service, adapters={"async": _AsyncAdapter()}, clock=clock
    ).run_cycle(pool_name="gpu-pool")

    assert len(result.dispatch_steps) == 2
    assert result.active_count == 2
    queued = service.read_item("item-3")
    assert queued is not None
    assert queued.status is QueueItemStatus.QUEUED


def test_cycle_reconciles_later_items_after_one_item_local_failure(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(30)])
    service = _started_service(tmp_path, clock=clock, max_active_items=2)
    for item_id in ("item-1", "item-2", "item-3"):
        service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=item_id,
                queue_name="gpu",
                run_uri=f"file:///runs/{item_id}",
                adapter="item-local-failure",
            )
        )
    adapter = _ItemLocalFailureAdapter()
    controller = QueueController(
        service, adapters={adapter.adapter_name: adapter}, clock=clock
    )
    controller.run_cycle(pool_name="gpu-pool")

    result = controller.run_cycle(pool_name="gpu-pool")

    assert [step.outcome for step in result.reconciliation_steps] == [
        "degraded",
        "completed",
    ]
    assert adapter.inspected == ["item-1", "item-2"]
    assert result.dispatch_steps == ()
    completed = service.read_item("item-2")
    queued = service.read_item("item-3")
    assert completed is not None
    assert completed.status is QueueItemStatus.SUCCEEDED
    assert queued is not None
    assert queued.status is QueueItemStatus.QUEUED


def test_cycle_stops_after_unknown_completion_and_degraded_reconciliation(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(12)])
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="active",
            queue_name="gpu",
            run_uri="file:///runs/active",
            adapter="degrading",
        )
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="queued",
            queue_name="gpu",
            run_uri="file:///runs/queued",
        )
    )
    adapter = _DegradingAdapter()
    controller = QueueController(
        service,
        adapters={"degrading": adapter, "fake": FakeQueueDispatchAdapter()},
        clock=clock,
    )
    controller.run_once(pool_name="gpu-pool")

    degraded = controller.run_cycle(pool_name="gpu-pool")

    assert [step.outcome for step in degraded.reconciliation_steps] == ["degraded"]
    assert degraded.dispatch_steps == ()
    queued = service.read_item("queued")
    assert queued is not None
    assert queued.status is QueueItemStatus.QUEUED


def test_cycle_counts_foreign_dispatch_without_inspecting_or_mutating_it(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(12)])
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="foreign",
            queue_name="gpu",
            run_uri="file:///runs/foreign",
            adapter="local",
        )
    )
    first_adapter = _CountingAdapter(adapter_name="local", session_id="session-1")
    first = QueueController(service, adapters={"local": first_adapter}, clock=clock)
    first.run_once(pool_name="gpu-pool")
    foreign_before = service.read_item("foreign")
    second_adapter = _CountingAdapter(adapter_name="local", session_id="session-2")

    result = QueueController(
        service, adapters={"local": second_adapter}, clock=clock
    ).run_cycle(pool_name="gpu-pool")

    assert result.active_count == 1
    assert result.reconciliation_steps == ()
    assert second_adapter.inspections == 0
    assert service.read_item("foreign") == foreign_before


def test_controller_current_session_reconciliation_does_not_fill(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(12)])
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="active",
            queue_name="gpu",
            run_uri="file:///runs/active",
            adapter="async",
        )
    )
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="queued",
            queue_name="gpu",
            run_uri="file:///runs/queued",
        )
    )
    controller = QueueController(service, adapters={"async": _AsyncAdapter()}, clock=clock)
    controller.run_once(pool_name="gpu-pool")

    result = controller.reconcile_current_session(pool_name="gpu-pool")

    assert result.dispatch_steps == ()
    assert result.active_count == 1
    queued = service.read_item("queued")
    assert queued is not None and queued.status is QueueItemStatus.QUEUED


def test_run_once_compensates_started_handle_when_commit_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _clock("2020-01-01T00:00:00Z", "2020-01-01T00:00:01Z")
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="gpu",
            run_uri="file:///runs/item-1",
            adapter="cancellable",
        )
    )
    adapter = _CancellableStartedAdapter()
    controller = QueueController(
        service, adapters={"cancellable": adapter}, clock=clock
    )

    def reject(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("commit rejected")

    monkeypatch.setattr(service, "record_dispatch_handle", reject)
    with pytest.raises(RuntimeError, match="commit rejected"):
        controller.run_once(pool_name="gpu-pool")

    assert adapter.cancelled is True


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


class _DeferredAdapter:
    adapter_name = "deferred"

    def dispatch(self, item) -> QueueDispatchResult:  # noqa: ANN001
        return QueueDispatchResult(
            disposition="deferred",
            status=QueueItemStatus.UNKNOWN,
            reason="resource_admission.capacity_unavailable",
        )


class _DeferFirstAdapter:
    adapter_name = "defer-first"

    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, item) -> QueueDispatchResult:  # noqa: ANN001
        self.dispatched.append(item.queue_item_id)
        if item.queue_item_id == "deferred-head":
            return QueueDispatchResult(
                disposition="deferred",
                status=QueueItemStatus.UNKNOWN,
                reason="resource_admission.capacity_unavailable",
            )
        return QueueDispatchResult(
            handle_id=f"defer-first:{item.queue_item_id}",
            status=QueueItemStatus.SUCCEEDED,
            reason="completed",
        )


class _DegradingAdapter:
    adapter_name = "degrading"

    def dispatch(self, item) -> QueueDispatchResult:  # noqa: ANN001
        return QueueDispatchResult(
            handle_id=f"degrading:{item.queue_item_id}",
            status=QueueItemStatus.DISPATCHED,
            reason="started",
            complete=False,
        )

    def inspect(self, item) -> QueueDispatchInspection:  # noqa: ANN001
        return QueueDispatchInspection(
            status=QueueItemStatus.DISPATCHED,
            reason="authority unavailable",
            degraded=True,
        )


class _ItemLocalFailureAdapter:
    adapter_name = "item-local-failure"

    def __init__(self) -> None:
        self.inspected: list[str] = []

    def dispatch(self, item) -> QueueDispatchResult:  # noqa: ANN001
        return QueueDispatchResult(
            handle_id=f"item-local-failure:{item.queue_item_id}",
            status=QueueItemStatus.DISPATCHED,
            reason="started",
            complete=False,
        )

    def inspect(self, item) -> QueueDispatchInspection:  # noqa: ANN001
        self.inspected.append(item.queue_item_id)
        if item.queue_item_id == "item-1":
            raise RuntimeError("injected item-local inspection failure")
        return QueueDispatchInspection(
            status=QueueItemStatus.SUCCEEDED,
            reason="completed",
            terminal=True,
        )


class _CountingAdapter:
    def __init__(
        self, *, adapter_name: str = "counting", session_id: str | None = None
    ) -> None:
        self.adapter_name = adapter_name
        self.session_id = session_id
        self.inspections = 0

    def dispatch(self, item) -> QueueDispatchResult:  # noqa: ANN001
        evidence: dict[str, PlainData] = (
            {}
            if self.session_id is None
            else {"managed_local": {"session_id": self.session_id}}
        )
        return QueueDispatchResult(
            handle_id=f"counting:{item.queue_item_id}",
            status=QueueItemStatus.DISPATCHED,
            reason="started",
            evidence=evidence,
            complete=False,
        )

    def inspect(self, item) -> QueueDispatchInspection:  # noqa: ANN001
        self.inspections += 1
        return QueueDispatchInspection(
            status=QueueItemStatus.DISPATCHED, reason="active"
        )


class _CancellableStartedAdapter:
    adapter_name = "cancellable"

    def __init__(self) -> None:
        self.cancelled = False

    def dispatch(self, item) -> QueueDispatchResult:  # noqa: ANN001
        return QueueDispatchResult(
            handle_id=f"cancellable:{item.queue_item_id}",
            status=QueueItemStatus.DISPATCHED,
            reason="started",
            complete=False,
        )

    def cancel(self, item, *, requested_by, reason) -> QueueDispatchCancellation:  # noqa: ANN001
        self.cancelled = True
        return QueueDispatchCancellation(reason=reason)


class _NewestPolicy:
    policy_id = "test.newest"

    def __init__(self) -> None:
        self.calls = 0

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        self.calls += 1
        return QueueSelectionDecision(
            QueueSelectionDisposition.SELECTED,
            "test.newest_selected",
            context.candidates[-1].queue_item_id,
        )


class _MutablePolicy:
    policy_id = "test.original"
    reason_code = "test.original_selected"

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        return QueueSelectionDecision(
            QueueSelectionDisposition.SELECTED,
            self.reason_code,
            context.candidates[0].queue_item_id,
        )

class _InvalidSelectionPolicy:
    policy_id = "test.invalid"

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        return QueueSelectionDecision(
            QueueSelectionDisposition.SELECTED,
            "test.invalid_selected",
            "not-in-context",
        )


class _FailingSelectionPolicy:
    policy_id = "test.failing"

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        raise RuntimeError("private selection exception")


class _StoppingSelectionPolicy:
    policy_id = "test.stopping"

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        return QueueSelectionDecision(
            QueueSelectionDisposition.STOPPED,
            "test.policy_requested_stop",
        )


class _UnsafePolicy:
    policy_id = "not safe"

    def select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision:
        return QueueSelectionDecision(QueueSelectionDisposition.STOPPED, "test.stop")


def _started_service(
    tmp_path: Path,
    *,
    clock,
    max_active_items: int = 1,
    max_dispatches_per_cycle: int | None = None,
) -> QueueService:
    spec = _spec(
        tmp_path,
        max_active_items=max_active_items,
        max_dispatches_per_cycle=max_dispatches_per_cycle,
    )
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


def _resource_service(tmp_path: Path, *, clock, capacity: int) -> QueueService:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {
                    "pool_name": "gpu-pool",
                    "mode": "managed",
                    "resources": {"gpu": capacity},
                }
            ],
            "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
            "controller": {"max_active_items": 1},
        }
    )
    service = QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock),
        clock=clock,
    )
    service.start()
    return service


def _spec(
    tmp_path: Path,
    *,
    max_active_items: int = 1,
    max_dispatches_per_cycle: int | None = None,
) -> QueueServiceSpec:
    return normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [{"pool_name": "gpu-pool", "mode": "managed"}],
            "queues": [{"queue_name": "gpu", "pool_name": "gpu-pool"}],
            "controller": {
                "max_active_items": max_active_items,
                "max_dispatches_per_cycle": max_dispatches_per_cycle,
            },
        }
    )


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
