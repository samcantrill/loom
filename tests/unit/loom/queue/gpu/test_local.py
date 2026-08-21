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
    LocalGpuLink,
    grouped,
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
    one_share = plan_local_gpu_pool(inventory, shares_per_gpu(1))
    shares = plan_local_gpu_pool(inventory, shares_per_gpu(3))

    assert whole.capacity == 2
    assert whole.resource_name == "gpu"
    assert whole.queue_spec.controller.max_active_items == 2
    assert list(whole.required_limits.values()) == [2, 1, 1]
    assert one_share.capacity == 2
    assert one_share.resource_name == "gpu_share"
    assert list(one_share.required_limits.values()) == [2, 1, 1]
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


def test_fingerprint_is_structured_and_stable_across_inventory_permutations() -> None:
    combined = plan_local_gpu_pool(_inventory(("a|b", "0")), whole_gpus())
    separate = plan_local_gpu_pool(_inventory(("a", "0"), ("b", "1")), whole_gpus())
    permuted = plan_local_gpu_pool(
        _inventory(("b", "other-b"), ("a", "other-a")), whole_gpus()
    )

    assert combined.fingerprint != separate.fingerprint
    assert separate.fingerprint == permuted.fingerprint


@pytest.mark.parametrize("shares", [0, -1])
def test_layout_rejects_non_positive_shares(shares: int) -> None:
    with pytest.raises(QueueServiceError, match="positive"):
        shares_per_gpu(shares)


def test_inventory_rejects_duplicate_device_or_binding_values() -> None:
    with pytest.raises(QueueServiceError, match="device IDs"):
        _inventory(("uuid-a", "0"), ("uuid-a", "1"))
    with pytest.raises(QueueServiceError, match="binding values"):
        _inventory(("uuid-a", "0"), ("uuid-b", "0"))


def test_device_rejects_cuda_binding_list_separator() -> None:
    with pytest.raises(QueueServiceError, match="CUDA list separator"):
        LocalGpuDevice("uuid-a", "0,1")


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


def test_assignment_safe_evidence_excludes_device_identity_and_binding() -> None:
    device_id = "operator-local-device-id"
    binding_value = "operator-local-binding"
    plan = plan_local_gpu_pool(_inventory((device_id, binding_value)), whole_gpus())
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.ensure_resource_limits("workspace", plan.required_limits)

    decision = plan.assignment_provider(store, workspace_id="workspace").acquire(
        ResourceAssignmentRequest(
            consumer_id="item",
            pool_name=plan.pool_name,
            owner_id="owner",
            session_id="session",
            resources={plan.resource_name: 1},
            admitted_lease_ids=("logical",),
            lease_ttl_seconds=30,
        )
    )

    assert decision.assignment is not None
    assert decision.assignment.safe_evidence == {
        "slots": (
            {
                "resource_name": plan.resource_name,
                "slot_id": "gpu-0",
                "lease_id": decision.assignment.leases[0].lease.lease_id,
                "expires_at": decision.assignment.leases[0].lease.expires_at,
            },
        )
    }
    assert device_id not in repr(decision.assignment.safe_evidence)
    assert binding_value not in repr(decision.assignment.safe_evidence)


def test_explicit_groups_are_disjoint_normalized_and_report_unused_devices() -> None:
    plan = plan_local_gpu_pool(
        _inventory(("gpu-c", "2"), ("gpu-a", "0"), ("gpu-b", "1")),
        grouped(2, groups=(("gpu-b", "gpu-a"),)),
    )

    assert plan.capacity == 1
    assert plan.resource_name == "gpu_group"
    assert plan.queue_spec.pools[0].resources == {"gpu_group": 1}
    assert plan.operator_summary()["groups"] == [("gpu-a", "gpu-b")]
    assert plan.operator_summary()["unused_device_ids"] == ("gpu-c",)


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ((("gpu-a", "gpu-a"),), "disjoint"),
        ((("gpu-a", "gpu-b"), ("gpu-b", "gpu-c")), "disjoint"),
        ((("gpu-a",),), "exact-size"),
    ],
)
def test_explicit_group_layout_rejects_duplicate_or_wrong_size_members(
    groups: tuple[tuple[str, ...], ...], message: str
) -> None:
    with pytest.raises(QueueServiceError, match=message):
        grouped(2, groups=groups)


def test_explicit_groups_reject_unknown_devices_before_plan_is_created() -> None:
    with pytest.raises(QueueServiceError, match="unknown inventory"):
        plan_local_gpu_pool(
            _inventory(("gpu-a", "0"), ("gpu-b", "1")),
            grouped(2, groups=(("gpu-a", "gpu-missing"),)),
        )


def test_ordered_groups_chunk_normalized_inventory_order() -> None:
    plan = plan_local_gpu_pool(
        _inventory(
            ("gpu-d", "3"),
            ("gpu-b", "1"),
            ("gpu-a", "0"),
            ("gpu-c", "2"),
            ("gpu-e", "4"),
        ),
        grouped(2, grouping="ordered"),
    )

    assert plan.operator_summary()["groups"] == [
        ("gpu-a", "gpu-b"),
        ("gpu-c", "gpu-d"),
    ]
    assert plan.operator_summary()["unused_device_ids"] == ("gpu-e",)


def test_topology_groups_choose_ranked_disjoint_pairs_stably() -> None:
    links = (
        LocalGpuLink("gpu-a", "gpu-b", rank=0, kind="fast"),
        LocalGpuLink("gpu-c", "gpu-d", rank=0, kind="fast"),
        LocalGpuLink("gpu-a", "gpu-c", rank=2, kind="slow"),
        LocalGpuLink("gpu-a", "gpu-d", rank=2, kind="slow"),
        LocalGpuLink("gpu-b", "gpu-c", rank=2, kind="slow"),
        LocalGpuLink("gpu-b", "gpu-d", rank=2, kind="slow"),
    )
    left = plan_local_gpu_pool(
        LocalGpuInventory(
            (
                LocalGpuDevice("gpu-d", "3"),
                LocalGpuDevice("gpu-b", "1"),
                LocalGpuDevice("gpu-a", "0"),
                LocalGpuDevice("gpu-c", "2"),
            ),
            links,
        ),
        grouped(2, grouping="topology"),
    )
    right = plan_local_gpu_pool(
        LocalGpuInventory(
            tuple(reversed(left.inventory.devices)), tuple(reversed(links))
        ),
        grouped(2, grouping="topology"),
    )

    assert left.operator_summary()["groups"] == [
        ("gpu-a", "gpu-b"),
        ("gpu-c", "gpu-d"),
    ]
    assert left.fingerprint == right.fingerprint


def test_topology_requires_complete_pairwise_evidence() -> None:
    with pytest.raises(QueueServiceError, match="cannot produce a complete group"):
        plan_local_gpu_pool(
            LocalGpuInventory(
                (LocalGpuDevice("gpu-a", "0"), LocalGpuDevice("gpu-b", "1"))
            ),
            grouped(2, grouping="topology"),
        )


def test_inventory_rejects_unknown_or_duplicate_topology_pairs() -> None:
    devices = (LocalGpuDevice("gpu-a", "0"), LocalGpuDevice("gpu-b", "1"))

    with pytest.raises(QueueServiceError, match="inventory device"):
        LocalGpuInventory(devices, (LocalGpuLink("gpu-a", "missing", 0, "fast"),))
    with pytest.raises(QueueServiceError, match="pairs must be unique"):
        LocalGpuInventory(
            devices,
            (
                LocalGpuLink("gpu-a", "gpu-b", 0, "fast"),
                LocalGpuLink("gpu-b", "gpu-a", 1, "slow"),
            ),
        )
