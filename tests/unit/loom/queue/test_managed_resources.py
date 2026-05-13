"""Unit coverage for managed queue-pool resource reconciliation."""

from __future__ import annotations

import pytest

from loom.pipeline.execution.resource_admission import ResourceLimitReconciliationStatus
from loom.pipeline.stores import WorkspaceIdentity
from loom.queue import QueueServiceError, normalize_queue_spec
from loom.queue.resources import (
    reconcile_managed_pool_limits,
    require_managed_pool_limits,
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


def _store() -> InMemoryWorkspaceCoordinationStore:
    store = InMemoryWorkspaceCoordinationStore()
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    return store
