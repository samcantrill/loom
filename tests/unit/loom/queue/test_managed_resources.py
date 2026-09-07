"""Unit coverage for managed queue-pool resource reconciliation."""

from __future__ import annotations

import pytest

from loom.pipeline.execution.resource_admission import ResourceLimitReconciliationStatus
from loom.pipeline.stores import WorkspaceIdentity
from loom.queue import QueueServiceError, normalize_queue_spec
from loom.queue.resources import (
    EffectiveAgentCapacity,
    require_effective_agent_capacity,
    reconcile_managed_pool_limits,
    require_managed_pool_limits,
)
import loom.queue.resources as queue_resources
from loom.queue._remote_stage_execution import (
    AgentResourceInventory,
    GpuDeviceDescriptor,
    ResidentGpuDevice,
)
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_reconcile_managed_pool_limits_reads_authority_without_mutation() -> None:
    store = _store()
    before = store.set_resource_limit("workspace-1", "gpu", limit=2)
    spec = normalize_queue_spec(
        {
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 2}},
                {"pool_name": "slurm", "mode": "delegated", "resources": {"gpu": 8}},
            ],
            "queues": [
                {"queue_name": "local", "pool_name": "local"},
                {"queue_name": "slurm", "pool_name": "slurm"},
            ],
        }
    )

    report = reconcile_managed_pool_limits(
        spec,
        store,
        workspace_id="workspace-1",
    )

    assert report.ok is True
    assert [pool.pool_name for pool in report.pools] == ["local"]
    assert report.pools[0].results[0].status is ResourceLimitReconciliationStatus.SUCCESS
    after = store.read_resource_limit("workspace-1", "gpu")
    assert after is not None
    assert after.revision == before.revision
    assert after.limit == 2


def test_reconcile_managed_pool_limits_reports_mismatch_and_missing_limits() -> None:
    store = _store()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    spec = normalize_queue_spec(
        {
            "pools": [
                {
                    "pool_name": "local",
                    "mode": "managed",
                    "resources": {"gpu": 2, "cpu": 4},
                },
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
        }
    )

    report = reconcile_managed_pool_limits(spec, store, workspace_id="workspace-1")

    assert report.ok is False
    statuses = {result.resource_key: result.status for result in report.pools[0].results}
    assert statuses == {
        "gpu": ResourceLimitReconciliationStatus.MISMATCH,
        "cpu": ResourceLimitReconciliationStatus.MISSING_LIMIT,
    }
    with pytest.raises(QueueServiceError, match="managed queue pool resource limits"):
        require_managed_pool_limits(spec, store, workspace_id="workspace-1")


def test_reconcile_managed_pool_limits_rejects_zero_resource_expectations() -> None:
    store = _store()
    spec = normalize_queue_spec(
        {
            "pools": [{"pool_name": "local", "mode": "managed", "resources": {"gpu": 0}}],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
        }
    )

    with pytest.raises(QueueServiceError, match="must be positive"):
        reconcile_managed_pool_limits(spec, store, workspace_id="workspace-1")


def test_agent_inventory_is_one_capacity_domain_with_observed_gpu_bindings() -> None:
    inventory = AgentResourceInventory(
        cpu_capacity=32,
        memory_capacity_bytes=128 * 1024**3,
        gpu_devices=tuple(
            ResidentGpuDevice(
                GpuDeviceDescriptor(f"GPU-{index}", "test", 80 * 1024**3),
                f"GPU-{index}",
            )
            for index in range(8)
        ),
    )

    atoms = inventory.capacity_atoms("agent-a")

    assert sum(atom.amount.numerator for atom in atoms if atom.owner_resource_kind == "cpu") == 32
    assert sum(atom.amount.numerator for atom in atoms if atom.owner_resource_kind == "memory") == 128 * 1024**3
    assert [atom.local_capacity_key for atom in atoms if atom.owner_resource_kind == "gpu"] == [
        f"agent-a:GPU-{index}" for index in range(8)
    ]


def test_effective_capacity_rejects_only_proven_overcommit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        queue_resources,
        "observe_effective_agent_capacity",
        lambda: EffectiveAgentCapacity(cpu_capacity=4, memory_capacity_bytes=1024),
    )

    assert require_effective_agent_capacity(cpu_capacity=4, memory_capacity_bytes=1024)
    with pytest.raises(QueueServiceError, match="CPU"):
        require_effective_agent_capacity(cpu_capacity=5, memory_capacity_bytes=0)
    with pytest.raises(QueueServiceError, match="memory"):
        require_effective_agent_capacity(cpu_capacity=1, memory_capacity_bytes=1025)


def _store() -> InMemoryWorkspaceCoordinationStore:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    return store
