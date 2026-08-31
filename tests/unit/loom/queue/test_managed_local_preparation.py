"""Focused coverage for the embedded managed-local preparation facade."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from loom.queue import (
    ManagedLocalPreparationReceipt,
    QueueConflictError,
    QueueServiceError,
    prepare_managed_local_run,
)
from loom.pipeline.stores import LocalRunStore, path_to_run_uri


pytestmark = pytest.mark.unit


def test_preparation_persists_existing_owners_and_exact_replay_is_read_only(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator_config(tmp_path)
    pipeline = _pipeline_config(tmp_path)

    fresh = prepare_managed_local_run(coordinator, pipeline, "starter-1")

    assert isinstance(fresh, ManagedLocalPreparationReceipt)
    assert fresh.stage_names == ("produce",)
    assert fresh.plan_digest
    assert fresh.runtime_digest
    run_dir = LocalRunStore(tmp_path / "runs").local_run_dir(fresh.run_uri)
    before = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    replay = prepare_managed_local_run(coordinator, pipeline, "starter-1")

    assert replay == fresh
    after = {
        path.relative_to(run_dir): path.read_bytes()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert (run_dir / "config" / "managed_local_runtime.json").is_file()
    assert (run_dir / ".loom" / "authority.sqlite3").is_file()


def test_preparation_rejects_changed_or_partial_existing_state(tmp_path: Path) -> None:
    coordinator = _coordinator_config(tmp_path)
    pipeline = _pipeline_config(tmp_path)
    receipt = prepare_managed_local_run(coordinator, pipeline, "starter-1")

    _pipeline_config(tmp_path, value=43)
    with pytest.raises(
        QueueConflictError, match="existing partial, corrupt, or changed"
    ):
        prepare_managed_local_run(coordinator, pipeline, "starter-1")

    store = LocalRunStore(tmp_path / "runs")
    partial_uri = path_to_run_uri(tmp_path / "runs" / "partial")
    store.create_run(partial_uri)
    with pytest.raises(
        QueueConflictError, match="existing partial, corrupt, or changed"
    ):
        prepare_managed_local_run(coordinator, pipeline, "partial")
    assert receipt.run_uri != partial_uri


def test_preparation_rejects_advanced_service_before_run_creation(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator_config(tmp_path, remote_profiles=[_descriptor()])
    pipeline = _pipeline_config(tmp_path)

    with pytest.raises(QueueServiceError, match="remote profiles"):
        prepare_managed_local_run(coordinator, pipeline, "starter-1")

    assert not (tmp_path / "runs" / "starter-1").exists()


def test_preparation_rejects_conflicting_runtime_root_and_unsafe_name(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator_config(tmp_path)
    pipeline = _pipeline_config(tmp_path, run_store_root=tmp_path / "other-runs")

    with pytest.raises(QueueServiceError, match="run-store root conflicts"):
        prepare_managed_local_run(coordinator, pipeline, "starter-1")
    with pytest.raises(QueueServiceError, match="safe path segment"):
        prepare_managed_local_run(coordinator, pipeline, "..")

    assert not (tmp_path / "runs" / "starter-1").exists()


def _coordinator_config(
    root: Path, *, remote_profiles: list[dict[str, object]] | None = None
) -> Path:
    source = root / "coordinator.yaml"
    source.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "kind": "loom.coordinator-service",
                "deployment_root": "deployment",
                "run_store_root": "runs",
                "machine_id": "local-machine",
                "poll_interval_seconds": 0.01,
                "max_accepted_time_step_seconds": 60,
                "embedded_profile": {
                    "descriptor": _descriptor(),
                    "project_root": str(root),
                    "python_executable": sys.executable,
                    "cpu_capacity": 1,
                    "memory_capacity_bytes": 0,
                    "gpu_devices": [],
                    "environment": {},
                },
                "remote_profiles": remote_profiles or [],
                "agent_policy": {
                    "revision": "policy-1",
                    "agents": [],
                    "principals": [],
                },
                "agent_server": None,
                "authority": {"kind": "embedded"},
            }
        ),
        encoding="utf-8",
    )
    source.chmod(0o600)
    return source


def _pipeline_config(
    root: Path, *, value: int = 42, run_store_root: Path | None = None
) -> Path:
    source = root / "pipeline.yaml"
    source.write_text(
        json.dumps(
            {
                "pipeline": {
                    "name": "starter",
                    "stages": [
                        {
                            "name": "produce",
                            "factory": {
                                "_target_": "tests.unit.loom.queue.test_managed_local_preparation.ProduceStage"
                            },
                            "config": {"value": value},
                            "outputs": {
                                "data": {
                                    "artifact_type": "json",
                                    "codec_key": "json.v1",
                                }
                            },
                        }
                    ],
                },
                "runtime": {
                    "executor": "local",
                    **(
                        {}
                        if run_store_root is None
                        else {"run_store": {"root": str(run_store_root)}}
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    return source


def _descriptor() -> dict[str, object]:
    return {
        "profile_id": "local-profile",
        "revision": "v1",
        "project_fingerprint": "project-1",
        "environment_fingerprint": "environment-1",
        "executor_fingerprint": "executor-1",
    }


class ProduceStage:
    pass
