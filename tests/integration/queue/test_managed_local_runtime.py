"""Integration coverage for the managed-local runtime facade."""

from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import (
    QueueEnqueueRequest,
    QueueItemStatus,
    QueueServiceError,
    normalize_queue_spec,
)
from loom.queue.managed_local import (
    ManagedLocalQueueRuntime,
    ManagedLocalQueueRuntimeState,
    ManagedLocalShutdownTimeoutError,
)


def test_runtime_gates_restart_recovery_and_drains_without_new_claims(
    tmp_path: Path,
) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    first_process = _Process(pid=101)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([first_process]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))
    runtime.service.enqueue(_request("queued"))
    runtime.run_cycle()

    restarted = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([_Process(pid=102)]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    recovery = restarted.start()

    assert recovery.state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
    assert recovery.foreign_item_ids == ("active",)
    queued = restarted.service.read_item("queued")
    assert queued is not None and queued.status is QueueItemStatus.QUEUED

    first_process.returncode = 0
    stop = Event()
    stop.set()
    stopped = runtime.serve(stop, poll_interval_seconds=0, wait=lambda _timeout: None)
    assert stopped.state is ManagedLocalQueueRuntimeState.STOPPED
    assert stopped.pool_status is not None
    assert stopped.pool_status.counts.queued == 1


def test_runtime_explicitly_resolves_one_contained_foreign_item_without_leases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 2}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 2},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=2)
    first_process = _Process(pid=110)
    first = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([first_process, _Process(pid=111)]),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    first.start()
    first.service.enqueue(_request("active"))
    first.service.enqueue(_request("other"))
    first.run_cycle()

    restarted = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([_Process(pid=112)]),
        clock=lambda: "2020-01-01T00:00:01Z",
    )
    assert restarted.start().state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
    before = store.read_resource_limit("workspace-1", "gpu")
    assert before is not None and before.value == 2
    monkeypatch.setattr(
        restarted.adapter,
        "inspect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("inspect")),
    )
    monkeypatch.setattr(
        restarted.adapter,
        "cancel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cancel")),
    )

    with pytest.raises(QueueServiceError, match="confirmed_stopped=True"):
        restarted.resolve_recovery_unknown(
            "active",
            previous_processes_confirmed_stopped=False,
            requested_by="operator-1",
            reason="contained by supervisor",
        )
    still_active = restarted.service.read_item("active")
    assert (
        still_active is not None and still_active.status is QueueItemStatus.DISPATCHED
    )

    resolved = restarted.resolve_recovery_unknown(
        "active",
        previous_processes_confirmed_stopped=True,
        requested_by="operator-1",
        reason="contained by supervisor",
    )

    assert resolved.status is QueueItemStatus.UNKNOWN
    assert restarted.state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
    assert restarted.status().foreign_item_ids == ("other",)
    restarted.resolve_recovery_unknown(
        "other",
        previous_processes_confirmed_stopped=True,
        requested_by="operator-1",
        reason="contained by supervisor",
    )
    assert restarted.state is ManagedLocalQueueRuntimeState.READY
    after = store.read_resource_limit("workspace-1", "gpu")
    assert after is not None and after.value == 2
    event = restarted.service.inspect_item("active").audit_events[-1]
    assert event.detail == {
        "status": "UNKNOWN",
        "reason": "managed-local-explicit-recovery",
        "evidence": {
            "managed_local_recovery": {
                "action": "explicit_unknown_recovery",
                "requested_by": "operator-1",
                "reason": "contained by supervisor",
                "previous_status": "DISPATCHED",
                "previous_processes_confirmed_stopped": True,
                "previous_session_id": first.adapter.session_id,
            }
        },
    }


def test_runtime_cancel_timeout_keeps_current_item_and_lease_active(
    tmp_path: Path,
) -> None:
    clock = _MutableClock("2020-01-01T00:00:00Z")
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    process = _Process(pid=112, exit_on_terminate=False, exit_on_kill=False)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=_Runner([process]),
        clock=clock,
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))
    runtime.run_cycle()
    stop = Event()
    stop.set()

    with pytest.raises(ManagedLocalShutdownTimeoutError) as error:
        runtime.serve(stop, poll_interval_seconds=1, shutdown_timeout_seconds=0)

    assert error.value.remaining_item_ids == ("active",)
    assert runtime.state is ManagedLocalQueueRuntimeState.CANCELLING
    active = runtime.service.read_item("active")
    assert active is not None and active.status is QueueItemStatus.DISPATCHED
    counter = store.read_resource_limit("workspace-1", "gpu")
    assert counter is not None and counter.value == 1


def test_runtime_degraded_work_blocks_refill_until_a_later_healthy_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    first_process = _Process(pid=101)
    runner = _Runner([first_process, _Process(pid=102)])
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=runner,
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))
    runtime.service.enqueue(_request("queued"))
    runtime.run_cycle()

    inspect = runtime.adapter.inspect

    def unavailable_inspection(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        raise RuntimeError("inspection unavailable")

    monkeypatch.setattr(runtime.adapter, "inspect", unavailable_inspection)
    degraded = runtime.run_cycle()

    assert runtime.state is ManagedLocalQueueRuntimeState.DEGRADED
    assert [step.outcome for step in degraded.reconciliation_steps] == ["degraded"]
    assert degraded.dispatch_steps == ()
    queued = runtime.service.read_item("queued")
    assert queued is not None and queued.status is QueueItemStatus.QUEUED

    monkeypatch.setattr(runtime.adapter, "inspect", inspect)
    first_process.returncode = 0
    recovered = runtime.run_cycle()

    assert runtime.state is ManagedLocalQueueRuntimeState.READY
    assert [step.outcome for step in recovered.reconciliation_steps] == ["completed"]
    assert [
        step.item.queue_item_id for step in recovered.dispatch_steps if step.item
    ] == ["queued"]


def test_runtime_uses_spec_owner_and_authored_static_assignment(tmp_path: Path) -> None:
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "controller": {"owner_id": "runtime-owner", "max_active_items": 1},
            "adapters": {
                "local": {
                    "assignments": {
                        "local": {
                            "gpu": {
                                "provider": "static-slots",
                                "slots": [
                                    {
                                        "id": "gpu-0",
                                        "coordination_key": "gpu-0",
                                        "value": "0",
                                    }
                                ],
                                "binding": {
                                    "type": "environment-list",
                                    "name": "VISIBLE_GPUS",
                                    "separator": ",",
                                },
                            }
                        }
                    }
                }
            },
        }
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.set_resource_limit("workspace-1", "gpu-0", limit=1)
    runner = _Runner([_Process(pid=103)])
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        process_runner=runner,
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    runtime.start()
    runtime.service.enqueue(_request("active"))

    runtime.run_cycle()
    status = runtime.status()

    assert runtime.owner_id == "runtime-owner"
    assert runtime.adapter.owner_id == "runtime-owner"
    item = runtime.service.read_item("active")
    assert item is not None and item.claim is not None
    assert item.claim.owner_id == "runtime-owner"
    assert runner.environments == [{"VISIBLE_GPUS": "0"}]
    assert status.pool_status is not None
    attempt = status.pool_status.active_attempts[0]
    assert attempt.owner_id == "runtime-owner"
    assert attempt.evidence_source == "same_session_live"
    assert attempt.assignment is not None
    assert attempt.assignment["provider_name"] == "static-slots"


def _request(queue_item_id: str) -> QueueEnqueueRequest:
    return QueueEnqueueRequest(
        queue_item_id=queue_item_id,
        queue_name="local",
        run_uri=f"file:///runs/{queue_item_id}",
        adapter="local",
        resources={"gpu": 1},
        snapshot={"argv": ["fake"]},
    )


class _Process:
    def __init__(
        self,
        *,
        pid: int,
        exit_on_terminate: bool = True,
        exit_on_kill: bool = True,
    ) -> None:
        self.pid = pid
        self.pgid = pid
        self.returncode: int | None = None
        self.exit_on_terminate = exit_on_terminate
        self.exit_on_kill = exit_on_kill

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        if self.exit_on_terminate:
            self.returncode = -15

    def kill(self) -> None:
        if self.exit_on_kill:
            self.returncode = -9


class _MutableClock:
    def __init__(self, value: str) -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


class _Runner:
    def __init__(self, processes: list[_Process]) -> None:
        self._processes = processes
        self.environments: list[dict[str, str]] = []

    def start(self, argv, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001, ANN201
        self.environments.append(dict(env or {}))
        return self._processes.pop(0)
