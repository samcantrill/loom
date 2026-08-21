"""Unit coverage for deterministic local GPU planning."""

from __future__ import annotations

import pytest

from loom.queue import QueueServiceError
from loom.queue.assignments import (
    ResourceAssignmentDisposition,
    ResourceAssignmentRequest,
)
from loom.queue.gpu import (
    LocalGpuDevice,
    LocalGpuInventory,
    plan_local_gpu_pool,
    shares_per_gpu,
    whole_gpus,
)
from loom.pipeline.stores import WorkspaceIdentity
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def _inventory(*values: tuple[str, str]) -> LocalGpuInventory:
    return LocalGpuInventory(tuple(LocalGpuDevice(*value) for value in values))


def test_whole_and_share_plans_have_honest_integer_capacity_and_names() -> None:
    inventory = _inventory(("uuid-b", "1"), ("uuid-a", "0"))

    whole = plan_local_gpu_pool(inventory, whole_gpus())
    shares = plan_local_gpu_pool(inventory, shares_per_gpu(3))

    assert whole.capacity == 2
    assert whole.resource_name == "gpu"
    assert whole.queue_spec.controller.max_active_items == 2
    assert list(whole.required_limits.values()) == [2, 1, 1]
    assert shares.capacity == 6
    assert shares.resource_name == "gpu_share"
    assert shares.queue_spec.controller.max_active_items == 6
    assert list(shares.required_limits.values()) == [6, 3, 3]


def test_plan_is_deterministic_and_safe_summary_excludes_binding_values() -> None:
    left = plan_local_gpu_pool(
        _inventory(
            ("uuid-b", "untrusted-binding-b"), ("uuid-a", "untrusted-binding-a")
        ),
        shares_per_gpu(2),
        pool_name="local",
        queue_name="jobs",
    )
    right = plan_local_gpu_pool(
        _inventory(("uuid-a", "other-a"), ("uuid-b", "other-b")),
        shares_per_gpu(2),
        pool_name="local",
        queue_name="jobs",
    )

    assert left.fingerprint == right.fingerprint
    assert tuple(left.required_limits) == tuple(right.required_limits)
    assert "binding" not in repr(left.safe_summary())
    assert "untrusted-binding-a" not in repr(left.safe_summary())
    assert left.operator_summary()["devices"]


@pytest.mark.parametrize("shares", [0, -1])
def test_layout_rejects_non_positive_shares(shares: int) -> None:
    with pytest.raises(QueueServiceError, match="positive"):
        shares_per_gpu(shares)


def test_inventory_rejects_duplicate_device_or_binding_values() -> None:
    with pytest.raises(QueueServiceError, match="device IDs"):
        _inventory(("uuid-a", "0"), ("uuid-a", "1"))
    with pytest.raises(QueueServiceError, match="binding values"):
        _inventory(("uuid-a", "0"), ("uuid-b", "0"))


def test_share_provider_interleaves_devices_before_second_share() -> None:
    plan = plan_local_gpu_pool(
        _inventory(("uuid-a", "0"), ("uuid-b", "1")), shares_per_gpu(2)
    )
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.ensure_resource_limits("workspace", plan.required_limits)
    provider = plan.assignment_provider(store, workspace_id="workspace")
    request = ResourceAssignmentRequest(
        consumer_id="item",
        pool_name=plan.pool_name,
        owner_id="owner",
        session_id="session",
        resources={plan.resource_name: 1},
        admitted_lease_ids=("logical",),
        lease_ttl_seconds=30,
    )

    assignments = [provider.acquire(request) for _ in range(5)]

    assert [decision.disposition for decision in assignments] == [
        ResourceAssignmentDisposition.ASSIGNED,
        ResourceAssignmentDisposition.ASSIGNED,
        ResourceAssignmentDisposition.ASSIGNED,
        ResourceAssignmentDisposition.ASSIGNED,
        ResourceAssignmentDisposition.DEFERRED,
    ]
    assert [
        decision.assignment.bindings.environment["CUDA_VISIBLE_DEVICES"]
        for decision in assignments[:4]
        if decision.assignment is not None
    ] == ["0", "1", "0", "1"]


def test_whole_provider_leases_distinct_devices_for_integer_amount() -> None:
    plan = plan_local_gpu_pool(
        _inventory(("uuid-a", "0"), ("uuid-b", "1")), whole_gpus()
    )
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.ensure_resource_limits("workspace", plan.required_limits)

    decision = plan.assignment_provider(store, workspace_id="workspace").acquire(
        ResourceAssignmentRequest(
            consumer_id="item",
            pool_name=plan.pool_name,
            owner_id="owner",
            session_id="session",
            resources={plan.resource_name: 2},
            admitted_lease_ids=("logical",),
            lease_ttl_seconds=30,
        )
    )

    assert decision.disposition is ResourceAssignmentDisposition.ASSIGNED
    assert decision.assignment is not None
    assert decision.assignment.bindings.environment["CUDA_VISIBLE_DEVICES"] == "0,1"
    assert len({lease.resource_key for lease in decision.assignment.leases}) == 2
