"""Unit coverage for managed-local runtime construction and startup checks."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import NoOpResourceAssignmentProvider, QueueServiceError, normalize_queue_spec
from loom.queue.managed_local import ManagedLocalQueueRuntime


def test_runtime_rejects_ambiguous_authored_and_explicit_assignment_provider(tmp_path) -> None:  # noqa: ANN001
    spec = normalize_queue_spec(
        {
            "schema_version": 2,
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
            "adapters": {
                "local": {
                    "assignments": {
                        "local": {
                            "gpu": {
                                "provider": "static-slots",
                                "slots": [
                                    {"id": "gpu-0", "coordination_key": "gpu-0", "value": "0"}
                                ],
                                "binding": {
                                    "type": "environment-list",
                                    "name": "VISIBLE_GPUS",
                                    "separator": ",",
                                },
                            }
                        }
                    }
                }
            },
        }
    )
    store = _store(tmp_path)

    with pytest.raises(QueueServiceError, match="authored local assignments"):
        ManagedLocalQueueRuntime.from_spec(
            spec,
            workspace_id="workspace-1",
            coordination_store=store,
            assignment_provider=NoOpResourceAssignmentProvider(),
        )


def test_runtime_start_validates_limits_before_starting_service(tmp_path) -> None:  # noqa: ANN001
    spec = normalize_queue_spec(
        {
            "db_path": str(tmp_path / "queue.sqlite"),
            "pools": [
                {"pool_name": "local", "mode": "managed", "resources": {"gpu": 1}}
            ],
            "queues": [{"queue_name": "local", "pool_name": "local"}],
        }
    )
    store = _store(tmp_path)
    before = store.set_resource_limit("workspace-1", "gpu", limit=2)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
    )

    with pytest.raises(QueueServiceError, match="resource limits do not match"):
        runtime.start()

    after = store.read_resource_limit("workspace-1", "gpu")
    assert runtime.service.state.value == "stopped"
    assert after is not None and after.revision == before.revision


def _store(tmp_path) -> SQLiteWorkspaceCoordinationStore:  # noqa: ANN001
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    return store
