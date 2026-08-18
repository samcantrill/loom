"""Integration coverage for managed local queue dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.pipeline.stores import (
    CoordinationFailureKind,
    CoordinationStoreError,
    WorkspaceIdentity,
)
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import (
    LaunchContract,
    QueueController,
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueService,
    SQLiteQueueRepository,
    normalize_queue_spec,
)
from loom.queue.local import LocalQueueDispatchAdapter
from loom.queue.assignments import (
    EnvironmentListBinding,
    ResourceAssignmentDisposition,
    ResourceAssignmentRequest,
    StaticSlot,
    StaticSlotAssignmentProvider,
)
from loom.queue.status import inspect_managed_queue_status
from loom.queue.status import build_queue_pool_status
from loom.serialization import thaw_plain_data
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_managed_local_controller_dispatches_one_active_item_at_a_time(
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
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    first_process = _FakeProcess(pid=201, pgid=201)
    second_process = _FakeProcess(pid=202, pgid=202)
    runner = _FakeRunner([first_process, second_process])
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(_request("item-1"))
    service.enqueue(_request("item-2"))
    adapter = LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=runner,
        current_drift_inputs={"config": "expected"},
    )
    controller = QueueController(service, adapters={"local": adapter}, clock=clock)

    first = controller.run_once(pool_name="local-pool")
    active = controller.run_once(pool_name="local-pool")
    statuses = inspect_managed_queue_status(service, adapters={"local": adapter})
    started_while_first_active = [process.pid for process in runner.started]
    active_amount_while_first_active = _active_amount(store, "gpu")
    first_process.returncode = 0
    completed = controller.run_once(pool_name="local-pool")
    second = controller.run_once(pool_name="local-pool")

    assert first.item is not None
    assert first.item.queue_item_id == "item-1"
    assert first.item.status is QueueItemStatus.DISPATCHED
    assert active.outcome == "active"
    assert started_while_first_active == [201]
    assert statuses[0].status is QueueItemStatus.DISPATCHED
    assert statuses[0].authority_evidence == {}
    assert active_amount_while_first_active == 1
    assert completed.item is not None
    assert completed.item.status is QueueItemStatus.SUCCEEDED
    assert second.item is not None
    assert second.item.queue_item_id == "item-2"
    assert second.item.status is QueueItemStatus.DISPATCHED
    assert [process.pid for process in runner.started] == [201, 202]


def test_managed_local_cycle_uses_unique_static_slots_and_queue_relative_logs(
    tmp_path: Path,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(20)])
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=2)
    store.set_resource_limit("workspace-1", "gpu-0", limit=1)
    store.set_resource_limit("workspace-1", "gpu-1", limit=1)
    service = _started_service(
        tmp_path, clock=clock, max_active_items=2, gpu_capacity=2
    )
    service.enqueue(_request("item-1"))
    service.enqueue(_request("item-2"))
    provider = StaticSlotAssignmentProvider(
        store,
        workspace_id="workspace-1",
        slots=(
            StaticSlot("gpu", "slot-0", "gpu-0", "0"),
            StaticSlot("gpu", "slot-1", "gpu-1", "1", "second"),
        ),
        bindings={"gpu": EnvironmentListBinding("gpu", "VISIBLE_GPUS", ",")},
    )
    adapter = LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=_FakeRunner(
            [_FakeProcess(pid=251, pgid=251), _FakeProcess(pid=252, pgid=252)]
        ),
        current_drift_inputs={"config": "expected"},
        assignment_provider=provider,
        log_directory=tmp_path / "queue-state" / "logs",
    )

    cycle = QueueController(
        service, adapters={"local": adapter}, clock=clock
    ).run_cycle(pool_name="local-pool")

    assert len(cycle.dispatch_steps) == 2
    items = [service.read_item(item_id) for item_id in ("item-1", "item-2")]
    managed_records = []
    for item in items:
        assert item is not None and item.dispatch_handle is not None
        managed = thaw_plain_data(
            item.dispatch_handle.evidence["managed_local"], path="managed_local"
        )
        assert isinstance(managed, dict)
        assert set(managed) == {
            "schema_version",
            "owner_id",
            "session_id",
            "pid",
            "pgid",
            "dispatched_at",
            "scalar_leases",
            "assignment",
            "logs",
        }
        managed_records.append(managed)
    assigned_slots: set[str] = set()
    for record in managed_records:
        assignment = record["assignment"]
        assert isinstance(assignment, dict)
        slots = assignment["slots"]
        assert isinstance(slots, list) and isinstance(slots[0], dict)
        assert set(slots[0]) <= {
            "resource_name",
            "slot_id",
            "lease_id",
            "expires_at",
            "label",
        }
        assert {
            "resource_name",
            "slot_id",
            "lease_id",
            "expires_at",
        } <= set(slots[0])
        slot_id = slots[0]["slot_id"]
        assert isinstance(slot_id, str)
        assigned_slots.add(slot_id)
    assert assigned_slots == {"slot-0", "slot-1"}
    for managed in managed_records:
        assert set(managed["assignment"]) == {
            "provider_name",
            "slots",
            "next_maintenance_at",
        }
        assert set(managed["logs"]) == {"stdout_path", "stderr_path"}
        assert str(managed["logs"]["stdout_path"]).startswith("logs/")
        assert "VISIBLE_GPUS" not in str(managed)


def test_static_slots_are_exclusive_across_sqlite_provider_instances(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "coordination.sqlite"
    first_store = SQLiteWorkspaceCoordinationStore(database_path)
    first_store.create_workspace(WorkspaceIdentity("workspace-1"))
    first_store.set_resource_limit("workspace-1", "gpu-0", limit=1)
    first_store.set_resource_limit("workspace-1", "gpu-1", limit=1)
    second_store = SQLiteWorkspaceCoordinationStore(database_path)
    slots = (
        StaticSlot("gpu", "zero", "gpu-0", "0"),
        StaticSlot("gpu", "one", "gpu-1", "1"),
    )
    first_provider = StaticSlotAssignmentProvider(
        first_store, workspace_id="workspace-1", slots=slots
    )
    second_provider = StaticSlotAssignmentProvider(
        second_store, workspace_id="workspace-1", slots=slots
    )

    first = first_provider.acquire(_assignment_request("item-1"))
    second = second_provider.acquire(_assignment_request("item-2"))
    blocked = second_provider.acquire(_assignment_request("item-3"))

    assert first.disposition is ResourceAssignmentDisposition.ASSIGNED
    assert second.disposition is ResourceAssignmentDisposition.ASSIGNED
    assert blocked.disposition is ResourceAssignmentDisposition.DEFERRED
    assert first.assignment is not None
    assert second.assignment is not None
    assert first.assignment.leases[0].resource_key == "gpu-0"
    assert second.assignment.leases[0].resource_key == "gpu-1"


def test_managed_local_controller_cancellation_releases_authority_lease(
    tmp_path: Path,
) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
    )
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.set_resource_limit("workspace-1", "gpu-0", limit=1)
    process = _FakeProcess(pid=203, pgid=203)
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(_request("item-1"))
    adapter = LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=_FakeRunner([process]),
        current_drift_inputs={"config": "expected"},
        assignment_provider=StaticSlotAssignmentProvider(
            store,
            workspace_id="workspace-1",
            slots=(StaticSlot("gpu", "zero", "gpu-0", "0"),),
        ),
    )
    controller = QueueController(service, adapters={"local": adapter}, clock=clock)
    controller.run_once(pool_name="local-pool")

    cancelled = controller.cancel_item(
        "item-1",
        requested_by="operator",
        reason="stop",
    )

    assert cancelled.item is not None
    assert cancelled.item.status is QueueItemStatus.CANCELLED
    assert cancelled.item.cancellation is not None
    _assert_no_private_launch_evidence(cancelled.item.cancellation.evidence)
    assert process.terminated is True
    assert _active_amount(store, "gpu") == 0
    assert _active_amount(store, "gpu-0") == 0


def test_controller_keeps_cancellation_reconcilable_until_local_exit(
    tmp_path: Path,
) -> None:
    clock = _clock(
        "2020-01-01T00:00:00Z",
        "2020-01-01T00:00:01Z",
        "2020-01-01T00:00:02Z",
        "2020-01-01T00:00:03Z",
    )
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _FakeProcess(pid=204, pgid=204, exit_on_terminate=False)
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(_request("item-1"))
    adapter = LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=_FakeRunner([process]),
        current_drift_inputs={"config": "expected"},
    )
    controller = QueueController(service, adapters={"local": adapter}, clock=clock)
    controller.run_once(pool_name="local-pool")

    cancelling = controller.cancel_item(
        "item-1", requested_by="operator", reason="stop"
    )

    assert cancelling.outcome == "cancelling"
    still_active = service.read_item("item-1")
    assert still_active is not None
    assert still_active.status is QueueItemStatus.DISPATCHED
    assert _active_amount(store, "gpu") == 1
    terminal = controller.run_once(pool_name="local-pool")
    assert terminal.outcome == "cancelled"
    assert process.killed is True
    assert _active_amount(store, "gpu") == 0


@pytest.mark.parametrize("operation", ["run_once", "run_cycle"])
def test_controller_reconciles_delayed_exit_after_handle_commit_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(20)])
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.set_resource_limit("workspace-1", "gpu-0", limit=1)
    process = _FakeProcess(pid=205, pgid=205, exit_on_terminate=False)
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(_request("item-1"))
    adapter = LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=_FakeRunner([process]),
        current_drift_inputs={"config": "expected"},
        assignment_provider=StaticSlotAssignmentProvider(
            store,
            workspace_id="workspace-1",
            slots=(StaticSlot("gpu", "zero", "gpu-0", "0"),),
        ),
    )
    controller = QueueController(service, adapters={"local": adapter}, clock=clock)
    record_dispatch_handle = service.record_dispatch_handle

    def reject_commit(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("commit rejected")

    monkeypatch.setattr(service, "record_dispatch_handle", reject_commit)
    with pytest.raises(RuntimeError, match="commit rejected"):
        if operation == "run_once":
            controller.run_once(pool_name="local-pool")
        else:
            controller.run_cycle(pool_name="local-pool")
    monkeypatch.setattr(service, "record_dispatch_handle", record_dispatch_handle)

    claimed = service.read_item("item-1")
    assert claimed is not None
    assert claimed.status is QueueItemStatus.CLAIMED
    assert process.terminated is True
    assert process.killed is False
    assert _active_amount(store, "gpu") == 1

    if operation == "run_once":
        reconciled = controller.run_once(pool_name="local-pool")
        assert reconciled.outcome == "cancelled"
    else:
        cycle = controller.run_cycle(pool_name="local-pool")
        assert [step.outcome for step in cycle.reconciliation_steps] == ["cancelled"]
    terminal = service.read_item("item-1")
    assert terminal is not None
    assert terminal.status is QueueItemStatus.CANCELLED
    assert process.killed is True
    assert _active_amount(store, "gpu") == 0
    assert _active_amount(store, "gpu-0") == 0


def test_controller_cancel_finishes_pending_handle_commit_compensation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _clock(*[f"2020-01-01T00:00:{index:02d}Z" for index in range(20)])
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _FakeProcess(pid=208, pgid=208, exit_on_terminate=False)
    service = _started_service(tmp_path, clock=clock)
    service.enqueue(_request("item-1"))
    adapter = LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=_FakeRunner([process]),
        current_drift_inputs={"config": "expected"},
    )
    controller = QueueController(service, adapters={"local": adapter}, clock=clock)
    record_dispatch_handle = service.record_dispatch_handle

    def reject_commit(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("commit rejected")

    monkeypatch.setattr(service, "record_dispatch_handle", reject_commit)
    with pytest.raises(RuntimeError, match="commit rejected"):
        controller.run_once(pool_name="local-pool")
    monkeypatch.setattr(service, "record_dispatch_handle", record_dispatch_handle)

    cancelled = controller.cancel_item("item-1", requested_by="operator", reason="stop")

    assert cancelled.outcome == "cancelled"
    assert cancelled.item is not None
    assert cancelled.item.status is QueueItemStatus.CANCELLED
    assert process.killed is True
    assert _active_amount(store, "gpu") == 0


def test_renewal_outage_stops_fill_then_releases_and_refills_after_exit(
    tmp_path: Path,
) -> None:
    clock = _MutableClock("2020-01-01T00:00:00Z")
    store = _UnavailableRenewalStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    first_process = _FakeProcess(pid=206, pgid=206, exit_on_terminate=False)
    second_process = _FakeProcess(pid=207, pgid=207)
    runner = _FakeRunner([first_process, second_process])
    service = _started_service(tmp_path, clock=clock, max_active_items=2)
    service.enqueue(_request("item-1"))
    service.enqueue(_request("item-2"))
    adapter = LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=runner,
        current_drift_inputs={"config": "expected"},
        lease_ttl_seconds=10,
        clock=clock,
    )
    controller = QueueController(service, adapters={"local": adapter}, clock=clock)

    first = controller.run_cycle(pool_name="local-pool")
    assert first.capacity_blocked is True
    assert first.next_maintenance_at == "2020-01-01T00:00:05Z"
    assert [process.pid for process in runner.started] == [206]

    store.advance_time(5)
    clock.value = "2020-01-01T00:00:05Z"
    before_deadline = controller.run_cycle(pool_name="local-pool")
    assert [step.outcome for step in before_deadline.reconciliation_steps] == [
        "degraded"
    ]
    assert before_deadline.dispatch_steps == ()
    assert first_process.terminated is False

    store.advance_time(3)
    clock.value = "2020-01-01T00:00:08Z"
    at_deadline = controller.run_cycle(pool_name="local-pool")
    assert at_deadline.dispatch_steps == ()
    assert first_process.terminated is True
    assert first_process.killed is False
    assert _active_amount(store, "gpu") == 1

    store.advance_time(1)
    clock.value = "2020-01-01T00:00:09Z"
    replacement = controller.run_cycle(pool_name="local-pool")

    assert [step.outcome for step in replacement.reconciliation_steps] == ["completed"]
    assert [step.outcome for step in replacement.dispatch_steps] == ["dispatched"]
    assert first_process.killed is True
    assert [process.pid for process in runner.started] == [206, 207]
    first_item = service.read_item("item-1")
    second_item = service.read_item("item-2")
    assert first_item is not None
    assert second_item is not None
    assert first_item.status is QueueItemStatus.FAILED
    assert second_item.status is QueueItemStatus.DISPATCHED
    assert _active_amount(store, "gpu") == 1


def test_sqlite_managed_local_three_slots_refill_after_each_terminal_path(
    tmp_path: Path,
) -> None:
    """Prove FIFO refill across success, failure, and cancellation barriers."""
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    for key in ("gpu", "gpu-0", "gpu-1", "gpu-2"):
        store.set_resource_limit("workspace-1", key, limit=3 if key == "gpu" else 1)
    service = _started_service(tmp_path, clock=_clock("2020-01-01T00:00:00Z"), max_active_items=3, gpu_capacity=3)
    for index in range(1, 13):
        service.enqueue(_request(f"item-{index:02d}"))
    processes = [_FakeProcess(pid=300 + index, pgid=300 + index) for index in range(12)]
    runner = _FakeRunner(processes)
    provider = StaticSlotAssignmentProvider(
        store,
        workspace_id="workspace-1",
        slots=tuple(
            StaticSlot("gpu", f"slot-{index}", f"gpu-{index}", str(index))
            for index in range(3)
        ),
    )
    adapter = LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=runner,
        current_drift_inputs={"config": "expected"},
        assignment_provider=provider,
    )
    controller = QueueController(service, adapters={"local": adapter})

    first = controller.run_cycle(pool_name="local-pool")
    assert [step.item.queue_item_id for step in first.dispatch_steps if step.item] == [
        "item-01", "item-02", "item-03"
    ]
    _assert_three_slot_peak(service)
    assert build_queue_pool_status(service, pool_name="local-pool").counts.queued == 9

    runner.started[0].returncode = 0
    success_refill = controller.run_cycle(pool_name="local-pool")
    assert [step.item.queue_item_id for step in success_refill.dispatch_steps if step.item] == ["item-04"]
    _assert_three_slot_peak(service)

    runner.started[1].returncode = 7
    failed_refill = controller.run_cycle(pool_name="local-pool")
    assert [step.item.queue_item_id for step in failed_refill.dispatch_steps if step.item] == ["item-05"]
    _assert_three_slot_peak(service)

    cancelled = controller.cancel_item("item-03", requested_by="operator", reason="stop")
    assert cancelled.item is not None and cancelled.item.status is QueueItemStatus.CANCELLED
    cancellation_refill = controller.run_cycle(pool_name="local-pool")
    assert [step.item.queue_item_id for step in cancellation_refill.dispatch_steps if step.item] == ["item-06"]
    _assert_three_slot_peak(service)

    while build_queue_pool_status(service, pool_name="local-pool").counts.active:
        for process in runner.started:
            if process.returncode is None:
                process.returncode = 0
        controller.run_cycle(pool_name="local-pool")
        _assert_three_slot_peak(service)

    counts = build_queue_pool_status(service, pool_name="local-pool").counts
    assert (counts.succeeded, counts.failed, counts.cancelled, counts.unknown) == (10, 1, 1, 0)


def _assert_three_slot_peak(service: QueueService) -> None:
    pool = build_queue_pool_status(service, pool_name="local-pool").to_dict()
    attempts = pool["active_attempts"]
    assert pool["counts"]["active"] <= 3
    slots = {
        attempt["assignment"]["slots"][0]["slot_id"]
        for attempt in attempts
        if attempt["assignment"] is not None
    }
    assert len(slots) == len(attempts)


@dataclass(slots=True)
class _FakeProcess:
    pid: int
    pgid: int
    returncode: int | None = None
    terminated: bool = False
    killed: bool = False
    exit_on_terminate: bool = True
    exit_on_kill: bool = True

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.exit_on_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        if self.exit_on_kill:
            self.returncode = -9


class _FakeRunner:
    def __init__(self, processes: list[_FakeProcess]) -> None:
        self._processes = list(processes)
        self.started: list[_FakeProcess] = []

    def start(self, argv, *, cwd=None, env=None):  # noqa: ANN001, ANN201
        process = self._processes.pop(0)
        self.started.append(process)
        return process


@dataclass(slots=True)
class _MutableClock:
    value: str

    def __call__(self) -> str:
        return self.value


class _UnavailableRenewalStore(InMemoryWorkspaceCoordinationStore):
    def renew_lease(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        raise CoordinationStoreError(
            "authority unavailable", kind=CoordinationFailureKind.UNAVAILABLE
        )


def _request(item_id: str) -> QueueEnqueueRequest:
    return QueueEnqueueRequest(
        queue_item_id=item_id,
        queue_name="local",
        run_uri=f"file:///runs/{item_id}",
        launch_contract=LaunchContract(
            adapter="local",
            entrypoint="argv",
            resources={"gpu": 1},
            snapshot={"argv": ["python", "-c", "print('ok')"]},
            drift_inputs={"config": "expected"},
        ),
    )


def _assignment_request(item_id: str) -> ResourceAssignmentRequest:
    return ResourceAssignmentRequest(
        consumer_id=item_id,
        pool_name="local-pool",
        owner_id="controller-1",
        session_id=item_id,
        resources={"gpu": 1},
        admitted_lease_ids=(f"scalar-{item_id}",),
        lease_ttl_seconds=30,
    )


def _started_service(
    tmp_path: Path,
    *,
    clock,
    max_active_items: int = 1,  # noqa: ANN001
    gpu_capacity: int = 1,
) -> QueueService:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {
                    "pool_name": "local-pool",
                    "mode": "managed",
                    "resources": {"gpu": gpu_capacity},
                },
            ],
            "queues": [{"queue_name": "local", "pool_name": "local-pool"}],
            "controller": {"max_active_items": max_active_items},
        }
    )
    service = QueueService(
        spec,
        SQLiteQueueRepository(tmp_path / "queue.sqlite", clock=clock),
        clock=clock,
    )
    service.start()
    return service


def _store() -> InMemoryWorkspaceCoordinationStore:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    return store


def _active_amount(store: InMemoryWorkspaceCoordinationStore, resource_key: str) -> int:
    counter = store.read_resource_limit("workspace-1", resource_key)
    assert counter is not None
    return counter.value


def _assert_no_private_launch_evidence(value: object) -> None:
    forbidden = {"fencing_token", "argv", "command", "cwd", "env", "environment"}
    if isinstance(value, Mapping):
        assert forbidden.isdisjoint(value)
        for nested in value.values():
            _assert_no_private_launch_evidence(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_no_private_launch_evidence(nested)


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
