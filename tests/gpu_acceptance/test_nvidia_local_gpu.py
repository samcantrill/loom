"""Opt-in acceptance coverage for an explicitly selected local NVIDIA host."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time

import pytest

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import QueueEnqueueRequest, QueueItemStatus
from loom.queue.gpu import (
    build_managed_local_gpu_runtime,
    ensure_local_gpu_pool_limits,
    plan_local_gpu_pool,
    whole_gpus,
)
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider


pytestmark = [pytest.mark.gpu, pytest.mark.e2e]


@pytest.mark.skipif(
    os.environ.get("LOOM_TEST_NVIDIA_GPU") != "1",
    reason="set LOOM_TEST_NVIDIA_GPU=1 to observe an explicitly selected NVIDIA host",
)
def test_real_nvidia_inventory_prepares_runs_and_releases_one_environment_only_item(
    tmp_path: Path,
) -> None:
    inventory = NvidiaSmiGpuInventoryProvider().discover()
    plan = plan_local_gpu_pool(
        inventory, whole_gpus(), db_path=str(tmp_path / "queue.sqlite")
    )
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("gpu-acceptance"))
    ensure_local_gpu_pool_limits(plan, store, workspace_id="gpu-acceptance")
    runtime = build_managed_local_gpu_runtime(
        plan, workspace_id="gpu-acceptance", coordination_store=store
    )
    runtime.start()
    runtime.service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="environment-only",
            queue_name=plan.queue_name,
            run_uri="file:///gpu-acceptance/environment-only",
            adapter="local",
            resources={plan.resource_name: 1},
            snapshot={
                "argv": [
                    sys.executable,
                    "-c",
                    "import os; assert os.environ['CUDA_VISIBLE_DEVICES']",
                ]
            },
        )
    )
    deadline = time.monotonic() + 5
    while True:
        runtime.run_cycle()
        item = runtime.service.read_item("environment-only")
        if item is not None and item.status is QueueItemStatus.SUCCEEDED:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("environment-only NVIDIA acceptance item timed out")
        time.sleep(0.01)

    assert all(
        store.read_resource_limit("gpu-acceptance", key).value == 0  # type: ignore[union-attr]
        for key in plan.required_limits
    )
    safe_status = repr(runtime.status().to_dict())
    assert all(device.device_id not in safe_status for device in inventory.devices)
    assert all(device.binding_value not in safe_status for device in inventory.devices)
