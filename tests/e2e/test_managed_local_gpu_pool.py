"""Fake end-to-end grouped local GPU pool coverage."""

from __future__ import annotations

from pathlib import Path

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import QueueEnqueueRequest, QueueItemStatus
from loom.queue.gpu import (
    LocalGpuDevice,
    LocalGpuInventory,
    build_managed_local_gpu_runtime,
    ensure_local_gpu_pool_limits,
    grouped,
    plan_local_gpu_pool,
)


def test_grouped_pool_launches_two_fake_commands_with_disjoint_pair_bindings(
    tmp_path: Path,
) -> None:
    plan = plan_local_gpu_pool(
        LocalGpuInventory(
            tuple(LocalGpuDevice(f"uuid-{index}", str(index)) for index in range(4))
        ),
        grouped(2, grouping="ordered"),
        db_path=str(tmp_path / "queue.sqlite"),
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
        {"CUDA_VISIBLE_DEVICES": "0,1"},
        {"CUDA_VISIBLE_DEVICES": "2,3"},
    ]
    assert all(
        runtime.service.read_item(f"item-{index}").status  # type: ignore[union-attr]
        is QueueItemStatus.DISPATCHED
        for index in range(2)
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
