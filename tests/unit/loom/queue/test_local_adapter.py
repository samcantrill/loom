"""Unit coverage for local managed queue dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from loom.serialization import thaw_plain_data
from loom.timestamps import utc_timestamp
from loom.pipeline.stores import (
    CoordinationFailureKind,
    CoordinationStoreError,
    WorkspaceIdentity,
)
from loom.queue import (
    LaunchContract,
    QueueItem,
    QueueItemStatus,
    RunIntent,
)
from loom.queue.local import LocalProcessRunner, LocalQueueDispatchAdapter
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
    cancellation_evidence = thaw_plain_data(cancellation.evidence, path="evidence")
    assert isinstance(cancellation_evidence, dict)
    assert cancellation_evidence["released_resource_leases"] == [
        {
            "resource_key": "gpu",
            "lease_id": "workspace-lease-3",
            "amount": 1,
            "released": True,
        }
    ]
    _assert_no_private_launch_evidence(cancellation.evidence)


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
    terminal = adapter.inspect(dispatched)
    assert process.killed is True
    assert terminal.status is QueueItemStatus.CANCELLED
    assert terminal.terminal is True
    assert _active_amount(store, "gpu") == 0


def test_local_adapter_redacts_released_leases_after_process_start_failure() -> None:
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    adapter = _adapter(store, _FailingRunner())

    result = adapter.dispatch(_item("item-1", resources={"gpu": 1}))

    assert result.status is QueueItemStatus.FAILED
    result_evidence = thaw_plain_data(result.evidence, path="evidence")
    assert isinstance(result_evidence, dict)
    assert result_evidence["released_resource_leases"] == [
        {
            "resource_key": "gpu",
            "lease_id": "workspace-lease-3",
            "amount": 1,
            "released": True,
        }
    ]
    assert "message" not in result_evidence
    _assert_no_private_launch_evidence(result.evidence)


def test_local_adapter_renews_scalar_lease_at_half_ttl() -> None:
    store = _RenewalStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    clock = _MutableClock("2020-01-01T00:00:00Z")
    process = _FakeProcess(pid=107, pgid=107)
    adapter = _adapter(store, _FakeRunner(process), lease_ttl_seconds=10, clock=clock)
    item, dispatched = _dispatch_item(adapter, "item-1")
    assert item.queue_item_id == "item-1"

    store.advance_time(5)
    clock.value = "2020-01-01T00:00:05Z"
    inspection = adapter.inspect(dispatched)

    assert inspection.terminal is False
    assert inspection.degraded is False
    assert inspection.next_maintenance_at == "2020-01-01T00:00:10Z"
    assert store.renew_calls == 1
    assert process.terminated is False
    assert _active_amount(store, "gpu") == 1


def test_local_adapter_schedules_maintenance_from_earliest_scalar_lease() -> None:
    store = _StaggeredAcquisitionStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.set_resource_limit("workspace-1", "cpu", limit=1)
    adapter = _adapter(
        store,
        _FakeRunner(_FakeProcess(pid=111, pgid=111)),
        lease_ttl_seconds=10,
        clock=_MutableClock("2020-01-01T00:00:00Z"),
    )

    result = adapter.dispatch(_item("item-1", resources={"gpu": 1, "cpu": 1}))

    assert result.next_maintenance_at == "2020-01-01T00:00:05Z"


def test_local_adapter_retries_transient_renewal_before_safety_deadline() -> None:
    store = _RenewalStore(
        failure_kind=CoordinationFailureKind.UNAVAILABLE, failures_remaining=1
    )
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    clock = _MutableClock("2020-01-01T00:00:00Z")
    process = _FakeProcess(pid=108, pgid=108)
    adapter = _adapter(store, _FakeRunner(process), lease_ttl_seconds=10, clock=clock)
    _item_record, dispatched = _dispatch_item(adapter, "item-1")

    store.advance_time(5)
    clock.value = "2020-01-01T00:00:05Z"
    unavailable = adapter.inspect(dispatched)
    store.advance_time(2)
    clock.value = "2020-01-01T00:00:07Z"
    recovered = adapter.inspect(dispatched)

    assert unavailable.degraded is True
    assert unavailable.next_maintenance_at == "2020-01-01T00:00:08Z"
    assert process.terminated is False
    assert recovered.degraded is False
    assert recovered.next_maintenance_at == "2020-01-01T00:00:12Z"
    assert store.renew_calls == 2


def test_local_adapter_terminates_immediately_on_ownership_loss_then_kills() -> None:
    store = _RenewalStore(failure_kind=CoordinationFailureKind.OWNERSHIP_LOST)
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    clock = _MutableClock("2020-01-01T00:00:00Z")
    process = _FakeProcess(pid=109, pgid=109, exit_on_terminate=False)
    adapter = _adapter(store, _FakeRunner(process), lease_ttl_seconds=10, clock=clock)
    _item_record, dispatched = _dispatch_item(adapter, "item-1")

    store.advance_time(5)
    clock.value = "2020-01-01T00:00:05Z"
    lost = adapter.inspect(dispatched)
    clock.value = "2020-01-01T00:00:06Z"
    terminal = adapter.inspect(dispatched)

    assert lost.degraded is True
    assert process.terminated is True
    assert process.killed is True
    assert terminal.terminal is True
    assert terminal.status is QueueItemStatus.FAILED
    assert _active_amount(store, "gpu") == 0


def test_local_adapter_escalates_unresolved_outage_at_safety_deadline() -> None:
    store = _RenewalStore(failure_kind=CoordinationFailureKind.UNAVAILABLE)
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    clock = _MutableClock("2020-01-01T00:00:00Z")
    process = _FakeProcess(pid=110, pgid=110, exit_on_terminate=False)
    adapter = _adapter(store, _FakeRunner(process), lease_ttl_seconds=10, clock=clock)
    _item_record, dispatched = _dispatch_item(adapter, "item-1")

    store.advance_time(5)
    clock.value = "2020-01-01T00:00:05Z"
    before_deadline = adapter.inspect(dispatched)
    terminated_before_deadline = process.terminated
    store.advance_time(3)
    clock.value = "2020-01-01T00:00:08Z"
    at_deadline = adapter.inspect(dispatched)
    clock.value = "2020-01-01T00:00:09Z"
    terminal = adapter.inspect(dispatched)

    assert before_deadline.degraded is True
    assert terminated_before_deadline is False
    assert process.terminated is True
    assert at_deadline.degraded is True
    assert process.killed is True
    assert terminal.terminal is True
    assert _active_amount(store, "gpu") == 0


def test_local_adapter_retries_release_before_reporting_terminal() -> None:
    store = _ReleaseStore(failures_remaining=1)
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _FakeProcess(pid=112, pgid=112)
    adapter = _adapter(store, _FakeRunner(process))
    _item_record, dispatched = _dispatch_item(adapter, "item-1")
    process.returncode = 0

    pending = adapter.inspect(dispatched)
    terminal = adapter.inspect(dispatched)

    assert pending.terminal is False
    assert pending.degraded is True
    assert pending.evidence["release_failure_kind"] == "unavailable"
    assert terminal.terminal is True
    assert terminal.status is QueueItemStatus.SUCCEEDED
    assert store.release_calls == 2
    assert _active_amount(store, "gpu") == 0


def test_local_adapter_attempts_every_release_after_ownership_loss() -> None:
    store = _OwnershipLostReleaseStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.set_resource_limit("workspace-1", "cpu", limit=1)
    process = _FakeProcess(pid=113, pgid=113)
    adapter = _adapter(store, _FakeRunner(process))
    item = _item("item-1", resources={"gpu": 1, "cpu": 1})
    result = adapter.dispatch(item)
    assert result.handle_id is not None
    dispatched = _with_dispatch_handle(item, result.handle_id, result.evidence)
    process.returncode = 0

    terminal = adapter.inspect(dispatched)

    assert terminal.terminal is True
    assert terminal.evidence["release_failure_kind"] == "ownership_lost"
    assert store.release_calls == 2
    assert _active_amount(store, "gpu") == 0
    assert _active_amount(store, "cpu") == 0


def test_local_adapter_checks_drift_before_resource_admission() -> None:
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
    def __init__(self, process: _FakeProcess) -> None:
        self.process = process
        self.argv: tuple[str, ...] | None = None

    def start(self, argv, *, cwd=None, env=None):  # noqa: ANN001, ANN201
        self.argv = tuple(argv)
        return self.process


class _FailingRunner:
    def start(self, argv, *, cwd=None, env=None):  # noqa: ANN001, ANN201
        raise RuntimeError("process start failed")


@dataclass(slots=True)
class _MutableClock:
    value: str

    def __call__(self) -> str:
        return self.value


class _RenewalStore(InMemoryWorkspaceCoordinationStore):
    def __init__(
        self,
        *,
        failure_kind: CoordinationFailureKind | None = None,
        failures_remaining: int | None = None,
    ) -> None:
        super().__init__()
        self.failure_kind = failure_kind
        self.failures_remaining = failures_remaining
        self.renew_calls = 0

    def renew_lease(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self.renew_calls += 1
        should_fail = self.failure_kind is not None and (
            self.failures_remaining is None or self.failures_remaining > 0
        )
        if should_fail:
            if self.failures_remaining is not None:
                self.failures_remaining -= 1
            raise CoordinationStoreError(
                "injected renewal failure", kind=self.failure_kind
            )
        return super().renew_lease(*args, **kwargs)


class _StaggeredAcquisitionStore(_RenewalStore):
    def __init__(self) -> None:
        super().__init__()
        self.acquire_calls = 0

    def acquire_resource_lease(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        lease = super().acquire_resource_lease(*args, **kwargs)
        self.acquire_calls += 1
        if self.acquire_calls == 1:
            self.advance_time(2)
        return lease


class _ReleaseStore(_RenewalStore):
    def __init__(self, *, failures_remaining: int) -> None:
        super().__init__()
        self.failures_remaining = failures_remaining
        self.release_calls = 0

    def release_lease(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self.release_calls += 1
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise CoordinationStoreError(
                "injected release failure",
                kind=CoordinationFailureKind.UNAVAILABLE,
            )
        return super().release_lease(*args, **kwargs)


class _OwnershipLostReleaseStore(_RenewalStore):
    def __init__(self) -> None:
        super().__init__()
        self.release_calls = 0

    def release_lease(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        released = super().release_lease(*args, **kwargs)
        self.release_calls += 1
        if self.release_calls == 1:
            raise CoordinationStoreError(
                "injected ownership loss",
                kind=CoordinationFailureKind.OWNERSHIP_LOST,
            )
        return released


def _adapter(
    store: InMemoryWorkspaceCoordinationStore,
    runner: LocalProcessRunner,
    *,
    current_drift_inputs: dict[str, str] | None = None,
    lease_ttl_seconds: int = 30,
    clock: Callable[[], str] | None = None,
) -> LocalQueueDispatchAdapter:
    return LocalQueueDispatchAdapter(
        workspace_id="workspace-1",
        coordination_store=store,
        owner_id="controller-1",
        process_runner=runner,
        current_drift_inputs={"config": "expected"}
        if current_drift_inputs is None
        else current_drift_inputs,
        lease_ttl_seconds=lease_ttl_seconds,
        clock=utc_timestamp if clock is None else clock,
    )


def _dispatch_item(
    adapter: LocalQueueDispatchAdapter, item_id: str
) -> tuple[QueueItem, QueueItem]:
    item = _item(item_id, resources={"gpu": 1})
    result = adapter.dispatch(item)
    assert result.handle_id is not None
    return item, _with_dispatch_handle(item, result.handle_id, result.evidence)


def _assert_no_private_launch_evidence(value: object) -> None:
    forbidden = {"fencing_token", "argv", "command", "cwd", "env", "environment"}
    if isinstance(value, Mapping):
        assert forbidden.isdisjoint(value)
        for nested in value.values():
            _assert_no_private_launch_evidence(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_private_launch_evidence(nested)


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
