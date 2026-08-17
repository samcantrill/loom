"""Integration coverage for managed local queue dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loom.pipeline.stores import WorkspaceIdentity
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
from loom.queue.status import inspect_managed_queue_status
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
    process = _FakeProcess(pid=203, pgid=203)
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

    cancelled = controller.cancel_item(
        "item-1",
        requested_by="operator",
        reason="stop",
    )

    assert cancelled.item is not None
    assert cancelled.item.status is QueueItemStatus.CANCELLED
    assert process.terminated is True
    assert _active_amount(store, "gpu") == 0


@dataclass(slots=True)
class _FakeProcess:
    pid: int
    pgid: int
    returncode: int | None = None
    terminated: bool = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        raise AssertionError("kill should not be needed")


class _FakeRunner:
    def __init__(self, processes: list[_FakeProcess]) -> None:
        self._processes = list(processes)
        self.started: list[_FakeProcess] = []

    def start(self, argv, *, cwd=None, env=None):  # noqa: ANN001, ANN201
        process = self._processes.pop(0)
        self.started.append(process)
        return process


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


def _started_service(tmp_path: Path, *, clock) -> QueueService:
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local-pool", "mode": "managed", "resources": {"gpu": 1}},
            ],
            "queues": [{"queue_name": "local", "pool_name": "local-pool"}],
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


def _clock(*values: str):
    remaining = list(values)

    def next_value() -> str:
        if len(remaining) == 1:
            return remaining[0]
        return remaining.pop(0)

    return next_value
