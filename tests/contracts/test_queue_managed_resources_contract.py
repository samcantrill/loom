"""Contract coverage for managed queue resource validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loom.pipeline.stores import WorkspaceIdentity
from loom.serialization import PlainData
from loom.queue import normalize_queue_spec
from loom.queue.resources import reconcile_managed_pool_limits
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_managed_pool_reconciliation_contract_shape() -> None:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    store.set_resource_limit("workspace-1", "gpu", limit=2)
    spec = normalize_queue_spec(
        {
            "pools": [{"pool_name": "local", "mode": "managed", "resources": {"gpu": 2}}],
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
