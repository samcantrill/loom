"""Integration coverage for the managed-local runtime facade."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import QueueEnqueueRequest, QueueItemStatus, normalize_queue_spec
from loom.queue.managed_local import (
    ManagedLocalQueueRuntime,
    ManagedLocalQueueRuntimeState,
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
    def __init__(self, *, pid: int) -> None:
        self.pid = pid
        self.pgid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class _Runner:
    def __init__(self, processes: list[_Process]) -> None:
        self._processes = processes

    def start(self, argv, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001, ANN201
        return self._processes.pop(0)
