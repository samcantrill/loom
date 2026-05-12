"""Unit coverage for scheduler-ready resource admission helpers."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline.execution import (
    ResourceAdmissionError,
    ResourceAdmissionRequest,
    ResourceAdmissionStatus,
    ResourceLeaseRequest,
    acquire_resource_admission,
    release_resource_admission,
    resource_requests_from_runtime,
)
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.stores import (
    AuthorityClient,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolResult,
    LifecycleReason,
    ServiceWorkspaceCoordinationStore,
    WorkspaceIdentity,
    accepted_authority_response,
)
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


pytestmark = pytest.mark.unit


class _FakeServiceWorkspaceClient:
    """Minimal AuthorityClient-like object for workspace coordination service calls."""

    def __init__(self, store: InMemoryWorkspaceCoordinationStore) -> None:
        self._store = store

    def _response(self, result: AuthorityProtocolResult) -> object:
        metadata = AuthorityProtocolMetadata(
            request_id="unit-test-service-request",
            operation_kind=AuthorityProtocolOperationKind.WORKSPACE_COORDINATION,
        )
        return accepted_authority_response(metadata, result)

    def create_workspace(self, identity: WorkspaceIdentity, **_kwargs) -> object:
        revision = self._store.create_workspace(identity)
        return self._response(AuthorityProtocolResult(workspace=identity, revision=revision))

    def set_resource_limit(
        self, workspace_id: str, resource_key: str, limit: int | None, **_kwargs
    ) -> object:
        counter = self._store.set_resource_limit(workspace_id, resource_key, limit=limit)
        return self._response(
            AuthorityProtocolResult(
                counter=counter,
            )
        )

    def acquire_resource_lease(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        owner_id: str,
        amount: int,
        lease_ttl_seconds: int,
        **_kwargs,
    ) -> object:
        record = self._store.acquire_resource_lease(
            workspace_id,
            resource_key,
            owner_id=owner_id,
            amount=amount,
            lease_ttl_seconds=lease_ttl_seconds,
        )
        return self._response(AuthorityProtocolResult(resource_lease=record))

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: object | None = None,
        **_kwargs,
    ) -> object:
        return self._response(
            AuthorityProtocolResult(
                lease=self._store.release_lease(
                    lease_id,
                    owner_id=owner_id,
                    fencing_token=fencing_token,
                )
            )
        )

    def release_coordination_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: object | None = None,
        **_kwargs,
    ) -> object:
        return self.release_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            reason=reason,
            **_kwargs,
        )


def test_resource_requests_from_runtime_uses_positive_integer_requests() -> None:
    request = ResourceRequest(
        entries={
            "cpu": ResourceEntry(kind="cpu", amount=2),
            "gpu": ResourceEntry(kind="gpu", amount=0),
        }
    )

    assert resource_requests_from_runtime(request) == (
        ResourceLeaseRequest(resource_key="cpu", amount=2),
    )


def test_resource_requests_from_runtime_rejects_non_integer_amounts() -> None:
    request = ResourceRequest(
        entries={
            "memory": ResourceEntry(kind="memory", amount=1.5, unit="GiB"),
        }
    )

    with pytest.raises(ResourceAdmissionError) as exc_info:
        resource_requests_from_runtime(request)

    assert exc_info.value.code == "resource_admission.non_integer_amount"
    assert exc_info.value.context == {"resource_key": "memory", "amount": 1.5}


def test_resource_admission_acquires_and_releases_leases() -> None:
    store = _store_with_workspace()
    store.set_resource_limit("workspace-1", "cpu", limit=2)
    request = _admission_request(ResourceLeaseRequest("cpu", 2))

    decision = acquire_resource_admission(store, request)

    assert decision.status is ResourceAdmissionStatus.ADMITTED
    assert len(decision.leases) == 1
    released = release_resource_admission(
        store,
        decision,
        reason=LifecycleReason(code="unit_release"),
    )
    assert released == decision.leases

    second = acquire_resource_admission(store, request)
    assert second.status is ResourceAdmissionStatus.ADMITTED


def test_resource_admission_fail_fast_rejects_when_capacity_is_unavailable() -> None:
    store = _store_with_workspace()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="existing-worker",
        amount=1,
        lease_ttl_seconds=30,
    )

    decision = acquire_resource_admission(
        store,
        _admission_request(ResourceLeaseRequest("gpu", 1)),
    )

    assert decision.status is ResourceAdmissionStatus.REJECTED
    assert decision.leases == ()
    assert "resource limit" in str(decision.message)


def test_resource_admission_bounded_wait_returns_blocked_after_timeout() -> None:
    store = _store_with_workspace()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="existing-worker",
        amount=1,
        lease_ttl_seconds=30,
    )
    now = 0.0
    sleeps: list[float] = []

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    decision = acquire_resource_admission(
        store,
        _admission_request(
            ResourceLeaseRequest("gpu", 1),
            wait_timeout_seconds=2.0,
            poll_interval_seconds=1.0,
        ),
        monotonic=monotonic,
        sleep=sleep,
    )

    assert decision.status is ResourceAdmissionStatus.BLOCKED
    assert sleeps == [1.0, 1.0]


def test_resource_admission_releases_partial_leases_after_later_failure() -> None:
    store = _store_with_workspace()
    store.set_resource_limit("workspace-1", "cpu", limit=1)
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="existing-worker",
        amount=1,
        lease_ttl_seconds=30,
    )

    decision = acquire_resource_admission(
        store,
        _admission_request(
            ResourceLeaseRequest("cpu", 1),
            ResourceLeaseRequest("gpu", 1),
        ),
    )

    assert decision.status is ResourceAdmissionStatus.REJECTED
    assert acquire_resource_admission(
        store,
        _admission_request(ResourceLeaseRequest("cpu", 1)),
    ).status is ResourceAdmissionStatus.ADMITTED


def test_service_workspace_coordination_store_fails_fast_when_capacity_is_exhausted() -> None:
    store = _service_store_with_workspace()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="existing-worker",
        amount=1,
        lease_ttl_seconds=30,
    )

    decision = acquire_resource_admission(
        store,
        _admission_request(ResourceLeaseRequest("gpu", 1)),
    )

    assert decision.status is ResourceAdmissionStatus.REJECTED
    assert decision.leases == ()
    assert "resource limit exceeded" in str(decision.message)


def test_service_workspace_coordination_store_bounded_wait_returns_blocked_after_timeout() -> None:
    store = _service_store_with_workspace()
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="existing-worker",
        amount=1,
        lease_ttl_seconds=30,
    )
    now = 0.0
    sleeps: list[float] = []

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    decision = acquire_resource_admission(
        store,
        _admission_request(
            ResourceLeaseRequest("gpu", 1),
            wait_timeout_seconds=2.0,
            poll_interval_seconds=1.0,
        ),
        monotonic=monotonic,
        sleep=sleep,
    )

    assert decision.status is ResourceAdmissionStatus.BLOCKED
    assert sleeps == [1.0, 1.0]


def test_service_workspace_coordination_store_releases_partial_leases_after_later_failure() -> None:
    store = _service_store_with_workspace()
    store.set_resource_limit("workspace-1", "cpu", limit=1)
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    store.acquire_resource_lease(
        "workspace-1",
        "gpu",
        owner_id="existing-worker",
        amount=1,
        lease_ttl_seconds=30,
    )

    decision = acquire_resource_admission(
        store,
        _admission_request(
            ResourceLeaseRequest("cpu", 1),
            ResourceLeaseRequest("gpu", 1),
        ),
    )

    assert decision.status is ResourceAdmissionStatus.REJECTED
    assert acquire_resource_admission(
        store,
        _admission_request(ResourceLeaseRequest("cpu", 1)),
    ).status is ResourceAdmissionStatus.ADMITTED


def _store_with_workspace() -> InMemoryWorkspaceCoordinationStore:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity(workspace_id="workspace-1"))
    return store


def _service_store_with_workspace() -> ServiceWorkspaceCoordinationStore:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity(workspace_id="workspace-1"))
    return ServiceWorkspaceCoordinationStore(
        cast(AuthorityClient, _FakeServiceWorkspaceClient(store)),
        workspace_id="workspace-1",
    )


def _admission_request(
    *resources: ResourceLeaseRequest,
    wait_timeout_seconds: float = 0.0,
    poll_interval_seconds: float = 1.0,
) -> ResourceAdmissionRequest:
    return ResourceAdmissionRequest(
        run_uri="file:///runs/r1",
        stage_name="build",
        workspace_id="workspace-1",
        owner_id="runner:build",
        resources=resources,
        lease_ttl_seconds=30,
        wait_timeout_seconds=wait_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
