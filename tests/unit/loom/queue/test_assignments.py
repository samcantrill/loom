"""Focused unit coverage for queue-local static assignments."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    CoordinationFailureKind,
    CoordinationStoreError,
    LifecycleReason,
    WorkspaceIdentity,
)
from loom.serialization import thaw_plain_data
from loom.queue.assignments import (
    EnvironmentListBinding,
    LaunchEnvironmentBindings,
    ResourceAssignmentDisposition,
    ResourceAssignmentRequest,
    StaticSlot,
    StaticSlotAssignmentProvider,
)
from loom.queue.errors import QueueServiceError
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_public_assignment_request_and_bindings_are_immutable() -> None:
    request = ResourceAssignmentRequest(
        consumer_id="item",
        pool_name="pool",
        owner_id="owner",
        session_id="session",
        resources={"gpu": 1},
        admitted_lease_ids=("scalar",),
        lease_ttl_seconds=30,
    )
    with pytest.raises(TypeError):
        request.resources["gpu"] = 2  # type: ignore[index]

    assigned_bindings = {"VISIBLE_GPUS": "0"}
    normalized = LaunchEnvironmentBindings(environment=assigned_bindings)
    assigned_bindings["VISIBLE_GPUS"] = "secret"

    assert normalized.environment == {"VISIBLE_GPUS": "0"}
    with pytest.raises(TypeError):
        normalized.environment["VISIBLE_GPUS"] = "1"  # type: ignore[index]


@pytest.mark.parametrize(
    "slots, bindings, match",
    [
        (
            (
                StaticSlot("gpu", "zero", "gpu-0", "0"),
                StaticSlot("gpu", "one", "gpu-0", "1"),
            ),
            {},
            "must be unique",
        ),
        (
            (StaticSlot("gpu", "zero", "gpu", "0"),),
            {},
            "must not collide",
        ),
        (
            (StaticSlot("gpu", "zero", "gpu-0", "0,1"),),
            {"gpu": EnvironmentListBinding("gpu", "VISIBLE_GPUS", ",")},
            "safe for their environment-list binding",
        ),
    ],
)
def test_static_provider_rejects_invalid_injected_inventory(
    slots: tuple[StaticSlot, ...],
    bindings: dict[str, EnvironmentListBinding],
    match: str,
) -> None:
    store = InMemoryWorkspaceCoordinationStore()

    with pytest.raises(QueueServiceError, match=match):
        StaticSlotAssignmentProvider(
            store, workspace_id="workspace", slots=slots, bindings=bindings
        )


def test_static_slots_are_ordered_and_release_on_capacity_deferral() -> None:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.set_resource_limit("workspace", "gpu-0", limit=1)
    store.set_resource_limit("workspace", "gpu-1", limit=1)
    provider = StaticSlotAssignmentProvider(
        store,
        workspace_id="workspace",
        slots=(
            StaticSlot("gpu", "zero", "gpu-0", "0", "first"),
            StaticSlot("gpu", "one", "gpu-1", "1"),
        ),
        bindings={"gpu": EnvironmentListBinding("gpu", "VISIBLE_GPUS", ",")},
    )
    request = ResourceAssignmentRequest(
        consumer_id="item",
        pool_name="pool",
        owner_id="owner",
        session_id="session",
        resources={"gpu": 2},
        admitted_lease_ids=("scalar",),
        lease_ttl_seconds=30,
    )

    assigned = provider.acquire(request)

    assert assigned.disposition is ResourceAssignmentDisposition.ASSIGNED
    assert assigned.assignment is not None
    assert assigned.assignment.bindings.environment == {"VISIBLE_GPUS": "0,1"}
    evidence = thaw_plain_data(assigned.assignment.safe_evidence, path="safe_evidence")
    assert isinstance(evidence, dict)
    slots = evidence["slots"]
    assert isinstance(slots, list) and isinstance(slots[0], dict)
    assert slots[0]["slot_id"] == "zero"
    deferred = provider.acquire(request)
    assert deferred.disposition is ResourceAssignmentDisposition.DEFERRED
    for lease in assigned.assignment.leases:
        store.release_lease(
            lease.lease.lease_id,
            owner_id=lease.lease.owner_id,
            fencing_token=lease.lease.fencing_token,
        )
    assert store.read_resource_limit("workspace", "gpu-0").value == 0  # type: ignore[union-attr]
    assert store.read_resource_limit("workspace", "gpu-1").value == 0  # type: ignore[union-attr]


def test_static_slots_compensate_partial_acquisition_on_contention() -> None:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.set_resource_limit("workspace", "gpu-0", limit=1)
    store.set_resource_limit("workspace", "gpu-1", limit=1)
    store.acquire_resource_lease(
        "workspace", "gpu-1", owner_id="other", amount=1, lease_ttl_seconds=30
    )
    provider = StaticSlotAssignmentProvider(
        store,
        workspace_id="workspace",
        slots=(
            StaticSlot("gpu", "zero", "gpu-0", "0"),
            StaticSlot("gpu", "one", "gpu-1", "1"),
        ),
    )

    decision = provider.acquire(
        ResourceAssignmentRequest(
            consumer_id="item",
            pool_name="pool",
            owner_id="owner",
            session_id="session",
            resources={"gpu": 2},
            admitted_lease_ids=("scalar",),
            lease_ttl_seconds=30,
        )
    )

    assert decision.disposition is ResourceAssignmentDisposition.DEFERRED
    assert store.read_resource_limit("workspace", "gpu-0").value == 0  # type: ignore[union-attr]
    assert store.read_resource_limit("workspace", "gpu-1").value == 1  # type: ignore[union-attr]


def test_static_slot_release_prioritizes_unfinished_mixed_outcome() -> None:
    store = _MixedReleaseStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.set_resource_limit("workspace", "gpu-0", limit=1)
    store.set_resource_limit("workspace", "gpu-1", limit=1)
    provider = StaticSlotAssignmentProvider(
        store,
        workspace_id="workspace",
        slots=(
            StaticSlot("gpu", "zero", "gpu-0", "0"),
            StaticSlot("gpu", "one", "gpu-1", "1"),
        ),
    )
    decision = provider.acquire(
        ResourceAssignmentRequest(
            consumer_id="item",
            pool_name="pool",
            owner_id="owner",
            session_id="session",
            resources={"gpu": 2},
            admitted_lease_ids=("scalar",),
            lease_ttl_seconds=30,
        )
    )
    assert decision.assignment is not None
    assignment = decision.assignment
    store.unavailable_lease_id = assignment.leases[0].lease.lease_id
    reason = LifecycleReason(code="test_release", message="test release")

    for _attempt in range(2):
        with pytest.raises(CoordinationStoreError) as raised:
            provider.release(assignment, reason=reason)
        assert raised.value.kind is CoordinationFailureKind.UNAVAILABLE
        assert store.read_resource_limit("workspace", "gpu-0").value == 1  # type: ignore[union-attr]
        assert store.read_resource_limit("workspace", "gpu-1").value == 0  # type: ignore[union-attr]

    with pytest.raises(CoordinationStoreError) as raised:
        provider.release(assignment, reason=reason)
    assert raised.value.kind is CoordinationFailureKind.OWNERSHIP_LOST
    assert store.read_resource_limit("workspace", "gpu-0").value == 0  # type: ignore[union-attr]
    assert store.read_resource_limit("workspace", "gpu-1").value == 0  # type: ignore[union-attr]


class _MixedReleaseStore(InMemoryWorkspaceCoordinationStore):
    def __init__(self) -> None:
        super().__init__()
        self.unavailable_lease_id: str | None = None
        self.unavailable_failures_remaining = 2

    def release_lease(self, lease_id, **kwargs):  # noqa: ANN001, ANN003, ANN201
        if (
            lease_id == self.unavailable_lease_id
            and self.unavailable_failures_remaining > 0
        ):
            self.unavailable_failures_remaining -= 1
            raise CoordinationStoreError(
                "injected release outage",
                kind=CoordinationFailureKind.UNAVAILABLE,
            )
        return super().release_lease(lease_id, **kwargs)
