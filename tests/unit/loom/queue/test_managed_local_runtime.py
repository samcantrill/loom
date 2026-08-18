"""Unit coverage for managed-local runtime construction and startup checks."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import WorkspaceIdentity
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore
from loom.queue import NoOpResourceAssignmentProvider, QueueServiceError, normalize_queue_spec
from loom.queue.controller import QueueCycleResult
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


def test_runtime_start_validates_static_slot_limits_without_mutation(tmp_path) -> None:  # noqa: ANN001
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
                                    {
                                        "id": "gpu-0",
                                        "coordination_key": "gpu-0",
                                        "value": "0",
                                    }
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
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    before = store.set_resource_limit("workspace-1", "gpu-0", limit=2)
    runtime = ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
    )

    with pytest.raises(QueueServiceError, match="static assignment slot limits"):
        runtime.start()

    after = store.read_resource_limit("workspace-1", "gpu-0")
    assert runtime.service.state.value == "stopped"
    assert after is not None and after.revision == before.revision


def test_runtime_degrades_when_startup_recovery_scan_fails(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(runtime.controller, "classify_recovery", _raise_scan_error)

    with pytest.raises(RuntimeError, match="recovery scan unavailable"):
        runtime.start()

    assert runtime.state.value == "DEGRADED"
    assert runtime.service.state.value == "running"


def test_runtime_status_separates_observation_scopes(tmp_path) -> None:  # noqa: ANN001
    runtime = _runtime(tmp_path)

    status = runtime.start().to_dict()

    assert status["observation_scope"] == {
        "runtime_health": "same_process",
        "queue_facts": "persisted",
        "process": "same_session_or_unavailable",
        "hardware_and_lease_liveness": "not_observed",
    }


def test_runtime_degrades_when_cycle_recovery_scan_fails(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    runtime = _runtime(tmp_path)
    runtime.start()
    monkeypatch.setattr(runtime.controller, "classify_recovery", _raise_scan_error)

    with pytest.raises(RuntimeError, match="recovery scan unavailable"):
        runtime.run_cycle()

    assert runtime.state.value == "DEGRADED"


def test_runtime_serve_waits_for_the_earlier_of_poll_and_maintenance_deadline(
    tmp_path, monkeypatch
) -> None:  # noqa: ANN001
    runtime = _runtime(tmp_path, clock=lambda: "2020-01-01T00:00:00Z")
    stop = _StopAfterWait()

    def run_cycle() -> QueueCycleResult:
        result = QueueCycleResult((), (), 0, False, "2020-01-01T00:00:03Z")
        runtime._record_cycle(result)
        return result

    monkeypatch.setattr(runtime, "run_cycle", run_cycle)

    stopped = runtime.serve(stop, poll_interval_seconds=10)

    assert stop.waits == [3.0]
    assert stopped.state.value == "STOPPED"


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("poll_interval_seconds", float("nan")),
        ("poll_interval_seconds", float("inf")),
        ("shutdown_timeout_seconds", float("nan")),
        ("shutdown_timeout_seconds", float("inf")),
    ],
)
def test_runtime_serve_rejects_non_finite_shutdown_timing(
    tmp_path, keyword, value
) -> None:  # noqa: ANN001
    runtime = _runtime(tmp_path)

    with pytest.raises(QueueServiceError, match="finite non-negative"):
        runtime.serve(_StopAfterWait(), **{keyword: value})


def _store(tmp_path) -> SQLiteWorkspaceCoordinationStore:  # noqa: ANN001
    store = SQLiteWorkspaceCoordinationStore(tmp_path / "coordination.sqlite")
    store.create_workspace(WorkspaceIdentity("workspace-1"))
    return store


def _runtime(tmp_path, *, clock=None) -> ManagedLocalQueueRuntime:  # noqa: ANN001
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
    store.set_resource_limit("workspace-1", "gpu", limit=1)
    return ManagedLocalQueueRuntime.from_spec(
        spec,
        workspace_id="workspace-1",
        coordination_store=store,
        clock=clock or (lambda: "2020-01-01T00:00:00Z"),
    )


def _raise_scan_error(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
    raise RuntimeError("recovery scan unavailable")


class _StopAfterWait:
    def __init__(self) -> None:
        self._set = False
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.waits.append(timeout)
        self._set = True
        return True
