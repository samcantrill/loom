"""Exercise NVIDIA discovery without requiring NVIDIA hardware or software."""

from __future__ import annotations

# ruff: noqa: E402

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from collections.abc import Sequence

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import QueueEnqueueRequest, QueueItemStatus
from loom.queue.gpu import (
    build_managed_local_gpu_runtime,
    ensure_local_gpu_pool_limits,
    grouped,
    plan_local_gpu_pool,
    shares_per_gpu,
    whole_gpus,
)
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider


WORKSPACE_ID = "nvidia-example"


def main() -> None:
    output_root = Path(
        os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", Path(__file__).parent / "output")
    )
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="run-", dir=output_root))
    provider = NvidiaSmiGpuInventoryProvider(
        include_topology=True, command_runner=_FakeNvidiaSmi()
    )
    inventory = provider.discover()
    whole = plan_local_gpu_pool(inventory, whole_gpus())
    shares = plan_local_gpu_pool(inventory, shares_per_gpu(2))
    grouped_plan = plan_local_gpu_pool(
        inventory,
        grouped(2, grouping="topology"),
        db_path=str(run_root / "queue.sqlite"),
    )

    store = SQLiteWorkspaceCoordinationStore(run_root / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity(WORKSPACE_ID))
    ensure_local_gpu_pool_limits(grouped_plan, store, workspace_id=WORKSPACE_ID)
    process = _Process(1001)
    runner = _ProcessRunner([process])
    runtime = build_managed_local_gpu_runtime(
        grouped_plan,
        workspace_id=WORKSPACE_ID,
        coordination_store=store,
        process_runner=runner,
    )
    runtime.start()
    runtime.service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="grouped-item",
            queue_name=grouped_plan.queue_name,
            run_uri="file:///example/grouped-item",
            adapter="local",
            resources={grouped_plan.resource_name: 1},
            snapshot={"argv": ["fake"]},
        )
    )
    runtime.run_cycle()
    process.returncode = 0
    runtime.run_cycle()
    item = runtime.service.read_item("grouped-item")
    if item is None or item.status is not QueueItemStatus.SUCCEEDED:
        raise RuntimeError("fake NVIDIA grouped runtime did not complete")
    if any(
        store.read_resource_limit(WORKSPACE_ID, key).value != 0  # type: ignore[union-attr]
        for key in grouped_plan.required_limits
    ):
        raise RuntimeError("fake NVIDIA grouped runtime did not release its leases")

    print(f"whole_capacity: {whole.capacity}")
    print(f"shares_capacity: {shares.capacity}")
    print(f"grouped_capacity: {grouped_plan.capacity}")
    print(f"grouped_binding: {runner.environments[0]['CUDA_VISIBLE_DEVICES']}")
    print(f"safe_summary_has_uuid: {'GPU-' in repr(grouped_plan.safe_summary())}")
    print(f"grouped_status: {item.status.value}")


class _FakeNvidiaSmi:
    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if "--query-gpu=index,uuid,pci.bus_id" in argv:
            stdout = (
                "0, GPU-fake-a, 00000000:01:00.0\n1, GPU-fake-b, 00000000:02:00.0\n"
            )
        elif argv == ("nvidia-smi", "topo", "-m"):
            stdout = "GPU0 GPU1\nGPU0 X NV4\nGPU1 NV4 X\n"
        else:
            raise AssertionError(f"unexpected NVIDIA argv: {argv!r}")
        return subprocess.CompletedProcess(argv, 0, stdout, "")


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


class _ProcessRunner:
    def __init__(self, processes: list[_Process]) -> None:
        self._processes = processes
        self.environments: list[dict[str, str]] = []

    def start(self, argv, *, cwd=None, env=None, stdout_path=None, stderr_path=None):  # noqa: ANN001, ANN201
        self.environments.append(dict(env or {}))
        return self._processes.pop(0)


if __name__ == "__main__":
    main()
