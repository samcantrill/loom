"""Contract coverage for managed queue resource validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from loom.pipeline.stores import WorkspaceIdentity
from loom.serialization import PlainData
from loom.queue import (
    NoOpResourceAssignmentProvider,
    QueueServiceError,
    ResourceAssignmentDecision,
    ResourceAssignmentDisposition,
    ResourceAssignmentProvider,
    ResourceAssignmentRequest,
    normalize_queue_spec,
)
from loom.queue.resources import reconcile_managed_pool_limits
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_managed_pool_reconciliation_contract_shape() -> None:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=2)
    spec = normalize_queue_spec(
        {
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 2}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
        }
    )

    report = reconcile_managed_pool_limits(spec, store, workspace_id="workspace-1")

    data = report.to_dict()
    pools = cast(list[Mapping[str, PlainData]], data["pools"])
    pool = pools[0]
    results = cast(list[Mapping[str, PlainData]], pool["results"])
    result = results[0]
    assert data["workspace_id"] == "workspace-1"
    assert data["ok"] is True
    assert pool["pool_name"] == "local"
    assert pool["resources"] == {"gpu": 2}
    assert result["status"] == "success"
    assert result["desired_limit"] == 2
    assert result["actual_limit"] == 2
    assert result["active"] == 0


def test_resource_assignment_provider_decision_contract_is_fakeable_and_safe() -> None:
    provider = NoOpResourceAssignmentProvider()
    request = ResourceAssignmentRequest(
        consumer_id="item-1",
        pool_name="local",
        owner_id="controller-1",
        session_id="session-1",
        resources={"cpu": 1},
        admitted_lease_ids=("scalar-1",),
        lease_ttl_seconds=30,
    )

    decision = provider.acquire(request)

    assert isinstance(provider, ResourceAssignmentProvider)
    assert decision.disposition is ResourceAssignmentDisposition.ASSIGNED
    serialized = decision.to_dict()
    assert serialized["assignment"] == {
        "provider_name": "no-op",
        "safe_evidence": {"slots": []},
        "next_maintenance_at": None,
    }
    assert "live_token" not in str(serialized)

    with pytest.raises(QueueServiceError, match="require an assignment"):
        ResourceAssignmentDecision(disposition=ResourceAssignmentDisposition.ASSIGNED)
    with pytest.raises(QueueServiceError, match="forbid assignments"):
        ResourceAssignmentDecision(
            disposition=ResourceAssignmentDisposition.DEFERRED,
            assignment=decision.assignment,
            reason_code="resource_assignment.capacity_unavailable",
        )
