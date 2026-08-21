"""Contract coverage for member-backed local GPU assignments."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    CoordinationFailureKind,
    CoordinationStoreError,
    LifecycleReason,
    WorkspaceIdentity,
)
from loom.queue.assignments import (
    ResourceAssignmentDisposition,
    ResourceAssignmentRequest,
)
from loom.queue.gpu import (
    LocalGpuDevice,
    LocalGpuInventory,
    grouped,
    plan_local_gpu_pool,
)
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_grouped_provider_requires_one_logical_unit_and_hides_bindings() -> None:
    plan, store = _plan_and_store()
    provider = plan.assignment_provider(store, workspace_id="workspace")

    invalid = provider.acquire(_request(plan, amount=2))
    assigned = provider.acquire(_request(plan))

    assert invalid.disposition is ResourceAssignmentDisposition.FAILED
    assert invalid.reason_code == "resource_assignment.group_amount_invalid"
    assert assigned.disposition is ResourceAssignmentDisposition.ASSIGNED
    assert assigned.assignment is not None
    assert assigned.assignment.bindings.environment == {"CUDA_VISIBLE_DEVICES": "0,1"}
    assert assigned.to_dict()["assignment"] == {
        "provider_name": "local-gpu",
        "safe_evidence": {
            "slots": [
                {
                    "resource_name": "gpu_group",
                    "slot_id": "gpu-0",
                    "lease_id": assigned.assignment.leases[0].lease.lease_id,
                    "expires_at": assigned.assignment.leases[0].lease.expires_at,
                },
                {
                    "resource_name": "gpu_group",
                    "slot_id": "gpu-1",
                    "lease_id": assigned.assignment.leases[1].lease.lease_id,
                    "expires_at": assigned.assignment.leases[1].lease.expires_at,
                },
            ]
        },
        "next_maintenance_at": assigned.assignment.next_maintenance_at,
    }
    assert "CUDA_VISIBLE_DEVICES" not in str(assigned.to_dict())
    assert "uuid-a" not in str(assigned.to_dict())


def test_grouped_provider_compensates_unexpected_second_member_failure() -> None:
    plan = plan_local_gpu_pool(
        LocalGpuInventory(
            (LocalGpuDevice("uuid-a", "0"), LocalGpuDevice("uuid-b", "1"))
        ),
        grouped(2, groups=(("uuid-a", "uuid-b"),)),
    )
    store = _UnexpectedSecondAcquireStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.ensure_resource_limits("workspace", plan.required_limits)

    decision = plan.assignment_provider(store, workspace_id="workspace").acquire(
        _request(plan)
    )

    assert decision.disposition is ResourceAssignmentDisposition.FAILED
    assert decision.reason_code == "resource_assignment.internal"
    assert all(
        store.read_resource_limit("workspace", key).value == 0  # type: ignore[union-attr]
        for key in plan.required_limits
    )


def test_grouped_provider_renews_and_releases_every_member() -> None:
    plan, store = _plan_and_store()
    provider = plan.assignment_provider(store, workspace_id="workspace")
    decision = provider.acquire(_request(plan))

    assert decision.assignment is not None
    renewed = provider.renew(decision.assignment)
    assert [lease.resource_key for lease in renewed.leases] == [
        lease.resource_key for lease in decision.assignment.leases
    ]
    assert [slot["expires_at"] for slot in renewed.safe_evidence["slots"]] == [
        lease.lease.expires_at for lease in renewed.leases
    ]
    provider.release(renewed, reason=LifecycleReason(code="test_release"))

    assert all(
        store.read_resource_limit("workspace", key).value == 0  # type: ignore[union-attr]
        for key in plan.required_limits
    )


@pytest.mark.parametrize(
    ("failures", "expected_error"),
    [
        (
            (CoordinationFailureKind.OWNERSHIP_LOST, None),
            CoordinationFailureKind.OWNERSHIP_LOST,
        ),
        (
            (CoordinationFailureKind.OWNERSHIP_LOST, "unfinished release"),
            RuntimeError,
        ),
    ],
)
def test_grouped_provider_release_attempts_every_member_with_existing_precedence(
    failures: tuple[CoordinationFailureKind, str | None],
    expected_error: CoordinationFailureKind | type[RuntimeError],
) -> None:
    plan = plan_local_gpu_pool(
        LocalGpuInventory(
            (LocalGpuDevice("uuid-a", "0"), LocalGpuDevice("uuid-b", "1"))
        ),
        grouped(2, groups=(("uuid-a", "uuid-b"),)),
    )
    store = _ReleaseFailureStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.ensure_resource_limits("workspace", plan.required_limits)
    provider = plan.assignment_provider(store, workspace_id="workspace")
    decision = provider.acquire(_request(plan))

    assert decision.assignment is not None
    store.failures = dict(
        zip(
            (lease.lease.lease_id for lease in reversed(decision.assignment.leases)),
            failures,
            strict=True,
        )
    )

    with pytest.raises(Exception) as raised:
        provider.release(
            decision.assignment, reason=LifecycleReason(code="test_release")
        )

    assert store.release_attempts == [
        lease.lease.lease_id for lease in reversed(decision.assignment.leases)
    ]
    if expected_error is CoordinationFailureKind.OWNERSHIP_LOST:
        assert isinstance(raised.value, CoordinationStoreError)
        assert raised.value.kind is CoordinationFailureKind.OWNERSHIP_LOST
    else:
        assert isinstance(raised.value, expected_error)


def _plan_and_store():  # noqa: ANN201
    plan = plan_local_gpu_pool(
        LocalGpuInventory(
            (LocalGpuDevice("uuid-a", "0"), LocalGpuDevice("uuid-b", "1"))
        ),
        grouped(2, groups=(("uuid-a", "uuid-b"),)),
    )
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.ensure_resource_limits("workspace", plan.required_limits)
    return plan, store


def _request(plan, *, amount: int = 1) -> ResourceAssignmentRequest:  # noqa: ANN001
    return ResourceAssignmentRequest(
        consumer_id="item",
        pool_name=plan.pool_name,
        owner_id="owner",
        session_id="session",
        resources={plan.resource_name: amount},
        admitted_lease_ids=("logical",),
        lease_ttl_seconds=30,
    )


class _UnexpectedSecondAcquireStore(InMemoryWorkspaceCoordinationStore):
    def __init__(self) -> None:
        super().__init__()
        self._acquire_calls = 0

    def acquire_resource_lease(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self._acquire_calls += 1
        if self._acquire_calls == 2:
            raise RuntimeError("injected second-member failure")
        return super().acquire_resource_lease(*args, **kwargs)


class _ReleaseFailureStore(InMemoryWorkspaceCoordinationStore):
    def __init__(self) -> None:
        super().__init__()
        self.failures: dict[str, CoordinationFailureKind | str | None] = {}
        self.release_attempts: list[str] = []

    def release_lease(self, lease_id: str, **kwargs):  # noqa: ANN003, ANN201
        self.release_attempts.append(lease_id)
        failure = self.failures.get(lease_id)
        if failure is CoordinationFailureKind.OWNERSHIP_LOST:
            raise CoordinationStoreError("ownership lost", kind=failure)
        if isinstance(failure, str):
            raise RuntimeError(failure)
        return super().release_lease(lease_id, **kwargs)
