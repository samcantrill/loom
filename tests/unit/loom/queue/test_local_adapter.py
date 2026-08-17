"""Unit coverage for local managed queue dispatch."""

from __future__ import annotations

from dataclasses import dataclass

from loom.serialization import thaw_plain_data
from loom.pipeline.stores import WorkspaceIdentity
from loom.queue import (
    LaunchContract,
    QueueItem,
    QueueItemStatus,
    RunIntent,
)
from loom.queue.local import LocalQueueDispatchAdapter
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_local_adapter_launches_observes_and_releases_resource_leases() -> None:
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _FakeProcess(pid=101, pgid=101)
    runner = _FakeRunner(process)
    adapter = _adapter(store, runner)
    item = _item("item-1", resources={"gpu": 1})

    result = adapter.dispatch(item)

    assert result.complete is False
    assert result.status is QueueItemStatus.DISPATCHED
    assert runner.argv == ("python", "-c", "print('ok')")
    assert _active_amount(store, "gpu") == 1

    assert result.handle_id is not None
    dispatched = _with_dispatch_handle(item, result.handle_id, result.evidence)
    active = adapter.inspect(dispatched)
    assert active.terminal is False
    assert active.status is QueueItemStatus.DISPATCHED

    process.returncode = 0
    finished = adapter.inspect(dispatched)
    assert finished.terminal is True
    assert finished.status is QueueItemStatus.SUCCEEDED
    assert _active_amount(store, "gpu") == 0


def test_local_adapter_cancel_terminates_process_group_and_releases_leases() -> None:
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _FakeProcess(pid=102, pgid=102)
    adapter = _adapter(store, _FakeRunner(process))
    item = _item("item-1", resources={"gpu": 1})
    result = adapter.dispatch(item)
    assert result.handle_id is not None
    dispatched = _with_dispatch_handle(item, result.handle_id, result.evidence)

    cancellation = adapter.cancel(
        dispatched,
        requested_by="operator",
        reason="operator-request",
    )

    assert cancellation.reason == "operator-request"
    assert cancellation.evidence["terminated_process_group"] is True
    assert process.terminated is True
    assert _active_amount(store, "gpu") == 0


def test_local_adapter_keeps_leases_until_cancelled_process_exit_is_observed() -> None:
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _FakeProcess(pid=106, pgid=106, exit_on_terminate=False)
    adapter = _adapter(store, _FakeRunner(process))
    item = _item("item-1", resources={"gpu": 1})
    result = adapter.dispatch(item)
    assert result.handle_id is not None
    dispatched = _with_dispatch_handle(item, result.handle_id, result.evidence)

    cancelling = adapter.cancel(dispatched, requested_by="operator", reason="stop")

    assert cancelling.evidence["exit_observed"] is False
    assert _active_amount(store, "gpu") == 1
    process.returncode = -15
    terminal = adapter.inspect(dispatched)
    assert terminal.status is QueueItemStatus.CANCELLED
    assert terminal.terminal is True
    assert _active_amount(store, "gpu") == 0


def test_local_adapter_detects_launch_contract_drift_before_resource_admission() -> None:
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    runner = _FakeRunner(_FakeProcess(pid=103, pgid=103))
    adapter = _adapter(store, runner, current_drift_inputs={"config": "changed"})
    item = _item("item-1", resources={"gpu": 1})

    result = adapter.dispatch(item)

    assert result.complete is True
    assert result.status is QueueItemStatus.FAILED
    assert result.evidence["drift_detected"] is True
    assert runner.argv is None
    assert _active_amount(store, "gpu") == 0


def test_local_adapter_reports_admission_rejection_without_launching_process() -> None:
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="existing",
        amount=1,
        lease_ttl_seconds=30,
    )
    runner = _FakeRunner(_FakeProcess(pid=104, pgid=104))
    adapter = _adapter(store, runner)
    item = _item("item-1", resources={"gpu": 1})

    result = adapter.dispatch(item)

    assert result.complete is True
    assert result.status is QueueItemStatus.UNKNOWN
    assert result.evidence["local_process_started"] is False
    assert runner.argv is None


def test_local_adapter_reports_recovery_needed_when_handle_is_not_in_memory() -> None:
    store = _store()
    adapter = _adapter(store, _FakeRunner(_FakeProcess(pid=105, pgid=105)))
    item = _with_dispatch_handle(
        _item("item-1"),
        "local:item-1:1:105",
        {"pid": 105, "pgid": 105},
    )

    inspection = adapter.inspect(item)

    assert inspection.terminal is True
    assert inspection.status is QueueItemStatus.UNKNOWN
    assert inspection.evidence["recovery_needed"] is True


@dataclass(slots=True)
class _FakeProcess:
    pid: int
    pgid: int
    returncode: int | None = None
    terminated: bool = False
    killed: bool = False
    exit_on_terminate: bool = True

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.exit_on_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True


class _FakeRunner:
    def __init__(self, process: _FakeProcess) -> None:
        self.process = process
        self.argv: tuple[str, ...] | None = None

    def start(self, argv, *, cwd=None, env=None):  # noqa: ANN001, ANN201
        self.argv = tuple(argv)
        return self.process


def _adapter(
    store: InMemoryWorkspaceCoordinationStore,
    runner: _FakeRunner,
    *,
    current_drift_inputs: dict[str, str] | None = None,
) -> LocalQueueDispatchAdapter:
    return LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=runner,
        current_drift_inputs={"config": "expected"}
        if current_drift_inputs is None
        else current_drift_inputs,
    )


def _item(item_id: str, *, resources: dict[str, int] | None = None) -> QueueItem:
    run_uri = f"file:///runs/{item_id}"
    return QueueItem(
        queue_item_id=item_id,
        queue_name="local",
        pool_name="local-pool",
        run_uri=run_uri,
        run_intent=RunIntent(run_uri=run_uri),
        launch_contract=LaunchContract(
            adapter="local",
            entrypoint="argv",
            resources={} if resources is None else resources,
            snapshot={"argv": ["python", "-c", "print('ok')"]},
            drift_inputs={"config": "expected"},
        ),
        enqueued_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )


def _with_dispatch_handle(
    item: QueueItem,
    handle_id: str,
    evidence: dict | object,
) -> QueueItem:
    data = item.to_dict()
    data["status"] = QueueItemStatus.DISPATCHED.value
    data["dispatch_handle"] = {
        "schema_version": 1,
        "adapter": "local",
        "handle_id": handle_id,
        "dispatched_at": "2020-01-01T00:00:01Z",
        "dispatch_attempt": item.dispatch_attempt,
        "evidence": thaw_plain_data(evidence, path="evidence"),
    }
    return QueueItem.from_dict(data)


def _store() -> InMemoryWorkspaceCoordinationStore:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    return store


def _active_amount(store: InMemoryWorkspaceCoordinationStore, resource_key: str) -> int:
    counter = store.read_resource_limit("workspace-1", resource_key)
    assert counter is not None
    return counter.value
