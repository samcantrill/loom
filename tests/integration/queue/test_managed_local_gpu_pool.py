"""Real-SQLite integration coverage for the local GPU pool composition helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.queue import QueueEnqueueRequest, QueueItemStatus, QueueServiceError
from loom.queue.assignments import (
    ResourceAssignmentDisposition,
    ResourceAssignmentRequest,
)
from loom.queue.gpu import (
    LocalGpuDevice,
    LocalGpuInventory,
    build_managed_local_gpu_runtime,
    ensure_local_gpu_pool_limits,
    plan_local_gpu_pool,
    shares_per_gpu,
    whole_gpus,
)
from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores import LifecycleReason
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore


def _inventory() -> LocalGpuInventory:
    return LocalGpuInventory(
        (LocalGpuDevice("uuid-a", "0"), LocalGpuDevice("uuid-b", "1"))
    )


def _request(plan, session_id: str = "session") -> ResourceAssignmentRequest:
    return ResourceAssignmentRequest(
        consumer_id="item",
        pool_name=plan.pool_name,
        owner_id="owner",
        session_id=session_id,
        resources={plan.resource_name: 1},
        admitted_lease_ids=("logical",),
        lease_ttl_seconds=30,
    )


def test_runtime_requires_preprovisioned_plan_limits_without_mutating(
    tmp_path: Path,
) -> None:
    plan = plan_local_gpu_pool(
        _inventory(), whole_gpus(), db_path=str(tmp_path / "queue.sqlite")
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace"))

    with pytest.raises(QueueServiceError, match="resource limits"):
        build_managed_local_gpu_runtime(
            plan, workspace_id="workspace", coordination_store=store
        )
    assert store.read_resource_limit("workspace", plan.resource_name) is None

    ensure_local_gpu_pool_limits(plan, store, workspace_id="workspace")
    runtime = build_managed_local_gpu_runtime(
        plan, workspace_id="workspace", coordination_store=store
    )

    assert runtime.pool_name == plan.pool_name


def test_whole_runtime_launches_distinct_devices_then_releases_exactly(
    tmp_path: Path,
) -> None:
    plan = plan_local_gpu_pool(
        _inventory(), whole_gpus(), db_path=str(tmp_path / "queue.sqlite")
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace"))
    ensure_local_gpu_pool_limits(plan, store, workspace_id="workspace")
    processes = [_Process(101), _Process(102)]
    runner = _Runner(processes)
    runtime = build_managed_local_gpu_runtime(
        plan,
        workspace_id="workspace",
        coordination_store=store,
        process_runner=runner,
    )
    runtime.start()
    for index in range(2):
        runtime.service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=f"item-{index}",
                queue_name=plan.queue_name,
                run_uri=f"file:///runs/item-{index}",
                adapter="local",
                resources={plan.resource_name: 1},
                snapshot={"argv": ["fake"]},
            )
        )

    runtime.run_cycle()

    assert runner.environments == [
        {"CUDA_VISIBLE_DEVICES": "0"},
        {"CUDA_VISIBLE_DEVICES": "1"},
    ]
    assert all(
        runtime.service.read_item(f"item-{index}").status  # type: ignore[union-attr]
        is QueueItemStatus.DISPATCHED
        for index in range(2)
    )
    assert all(
        store.read_resource_limit("workspace", key).value  # type: ignore[union-attr]
        == limit
        for key, limit in plan.required_limits.items()
    )

    for process in processes:
        process.returncode = 0
    runtime.run_cycle()

    assert all(
        runtime.service.read_item(f"item-{index}").status  # type: ignore[union-attr]
        is QueueItemStatus.SUCCEEDED
        for index in range(2)
    )
    assert all(
        store.read_resource_limit("workspace", key).value == 0  # type: ignore[union-attr]
        for key in plan.required_limits
    )


def test_share_leases_peak_at_capacity_then_release_exactly(tmp_path: Path) -> None:
    plan = plan_local_gpu_pool(_inventory(), shares_per_gpu(2))
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace"))
    ensure_local_gpu_pool_limits(plan, store, workspace_id="workspace")
    provider = plan.assignment_provider(store, workspace_id="workspace")

    decisions = [
        provider.acquire(_request(plan, f"session-{index}")) for index in range(5)
    ]

    assert [decision.disposition for decision in decisions] == [
        ResourceAssignmentDisposition.ASSIGNED,
        ResourceAssignmentDisposition.ASSIGNED,
        ResourceAssignmentDisposition.ASSIGNED,
        ResourceAssignmentDisposition.ASSIGNED,
        ResourceAssignmentDisposition.DEFERRED,
    ]
    for decision in decisions[:4]:
        assert decision.assignment is not None
        provider.release(decision.assignment, reason=LifecycleReason(code="complete"))
    assert all(
        store.read_resource_limit("workspace", key).value == 0  # type: ignore[union-attr]
        for key in plan.required_limits
    )


class _Process:
    def __init__(self, pid: int) -> None:
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
        self._processes = list(processes)
        self.environments: list[dict[str, str]] = []

    def start(
        self,
        argv,  # noqa: ANN001
        *,
        cwd=None,  # noqa: ANN001
        env=None,  # noqa: ANN001
        stdout_path=None,  # noqa: ANN001
        stderr_path=None,  # noqa: ANN001
    ):  # noqa: ANN201
        self.environments.append(dict(env or {}))
        return self._processes.pop(0)
