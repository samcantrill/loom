"""Focused coverage for the project-owned managed-local bundle pattern."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from loom.pipeline.stores import LifecycleReason, WorkspaceIdentity
from loom.queue.assignments import (
    ResourceAssignmentDisposition,
    ResourceAssignmentRequest,
    StaticSlot,
    StaticSlotAssignmentProvider,
)
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


_PROVIDER_PATH = (
    Path(__file__).resolve().parents[4]
    / "examples"
    / "operations"
    / "managed-local-queue"
    / "paired_assignment_provider.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "example_paired_assignment_provider", _PROVIDER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
PairedMemberAssignmentProvider = _MODULE.PairedMemberAssignmentProvider


def test_bundle_contends_with_individual_member_leases() -> None:
    store, members = _store_and_members()
    individual = StaticSlotAssignmentProvider(
        store, workspace_id="workspace", slots=(members[0],)
    )
    bundle = _bundle_provider(store, members)

    single = individual.acquire(_request("individual", {"accelerator": 1}))
    blocked = bundle.acquire(_request("bundle", {"accelerator-pair": 1}))

    assert single.disposition is ResourceAssignmentDisposition.ASSIGNED
    assert blocked.disposition is ResourceAssignmentDisposition.DEFERRED
    assert _value(store, "accelerator-slot-a") == 1
    assert _value(store, "accelerator-slot-b") == 0


def test_bundle_rolls_back_first_member_when_second_member_is_unavailable() -> None:
    store, members = _store_and_members()
    individual = StaticSlotAssignmentProvider(
        store, workspace_id="workspace", slots=(members[1],)
    )
    bundle = _bundle_provider(store, members)
    occupied = individual.acquire(
        _request("individual", {"accelerator": 1}, session_id="b")
    )

    decision = bundle.acquire(_request("bundle", {"accelerator-pair": 1}))

    assert occupied.disposition is ResourceAssignmentDisposition.ASSIGNED
    assert decision.disposition is ResourceAssignmentDisposition.DEFERRED
    assert _value(store, "accelerator-slot-a") == 0
    assert _value(store, "accelerator-slot-b") == 1


def test_bundle_rolls_back_first_member_on_unexpected_second_acquire_failure() -> None:
    store, members = _store_and_members(_UnexpectedSecondAcquireStore())
    bundle = _bundle_provider(store, members)

    decision = bundle.acquire(_request("bundle", {"accelerator-pair": 1}))

    assert decision.disposition is ResourceAssignmentDisposition.FAILED
    assert decision.reason_code == "resource_assignment.internal"
    assert _value(store, "accelerator-slot-a") == 0
    assert _value(store, "accelerator-slot-b") == 0


def test_bundle_renews_and_releases_every_member_with_two_value_binding() -> None:
    store, members = _store_and_members()
    provider = _bundle_provider(store, members)
    decision = provider.acquire(_request("bundle", {"accelerator-pair": 1}))

    assert decision.disposition is ResourceAssignmentDisposition.ASSIGNED
    assert decision.assignment is not None
    assignment = decision.assignment
    assert assignment.bindings.environment == {"LOOM_ASSIGNED_ACCELERATORS": "a,b"}
    assert [lease.resource_key for lease in assignment.leases] == [
        "accelerator-slot-a",
        "accelerator-slot-b",
    ]
    renewed = provider.renew(assignment)
    assert [lease.lease.lease_id for lease in renewed.leases] == [
        lease.lease.lease_id for lease in assignment.leases
    ]
    provider.release(
        renewed,
        reason=LifecycleReason(code="test_release", message="test release"),
    )

    assert _value(store, "accelerator-slot-a") == 0
    assert _value(store, "accelerator-slot-b") == 0


def _store_and_members(
    store: InMemoryWorkspaceCoordinationStore | None = None,
) -> tuple[InMemoryWorkspaceCoordinationStore, tuple[StaticSlot, ...]]:
    store = store or InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace"))
    store.set_resource_limit("workspace", "accelerator-slot-a", limit=1)
    store.set_resource_limit("workspace", "accelerator-slot-b", limit=1)
    return store, (
        StaticSlot("accelerator", "slot-a", "accelerator-slot-a", "a", "slot-a"),
        StaticSlot("accelerator", "slot-b", "accelerator-slot-b", "b", "slot-b"),
    )


def _bundle_provider(
    store: InMemoryWorkspaceCoordinationStore, members: tuple[StaticSlot, ...]
):
    return PairedMemberAssignmentProvider(
        store,
        workspace_id="workspace",
        resource_name="accelerator-pair",
        members=members,
    )


def _request(
    consumer_id: str, resources: dict[str, int], *, session_id: str = "session"
) -> ResourceAssignmentRequest:
    return ResourceAssignmentRequest(
        consumer_id=consumer_id,
        pool_name="local",
        owner_id="owner",
        session_id=session_id,
        resources=resources,
        admitted_lease_ids=(f"scalar-{consumer_id}",),
        lease_ttl_seconds=30,
    )


def _value(store: InMemoryWorkspaceCoordinationStore, resource_key: str) -> int:
    counter = store.read_resource_limit("workspace", resource_key)
    assert counter is not None
    return counter.value


class _UnexpectedSecondAcquireStore(InMemoryWorkspaceCoordinationStore):
    def __init__(self) -> None:
        super().__init__()
        self.acquire_calls = 0

    def acquire_resource_lease(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        self.acquire_calls += 1
        if self.acquire_calls == 2:
            raise RuntimeError("injected second-member failure")
        return super().acquire_resource_lease(*args, **kwargs)
