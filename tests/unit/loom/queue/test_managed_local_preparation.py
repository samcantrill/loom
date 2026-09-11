"""Focused coverage for the embedded managed-local preparation facade."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import sys

import pytest

from loom.queue import (
    ManagedLocalPreparationReceipt,
    QueueConflictError,
    QueueServiceError,
    prepare_managed_run,
    prepare_managed_local_run,
)
from loom.queue.deployment import load_coordinator_service_config
from loom.pipeline.orchestration import ExecutionRequirement
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.runtime import CpuResourcePlanner
from weave import RecipeCatalog, compose_config, compose_config_with_catalog


pytestmark = pytest.mark.unit


def test_checked_stateful_recipe_is_published_and_replayed_without_recomposition(
    tmp_path: Path,
) -> None:
    from loom.diagnostics import PreflightRequest, PreflightStatus, run_preflight_composed

    coordinator = _coordinator_config(tmp_path)
    role = json.loads(coordinator.read_text())
    role["local_agent"] = None
    coordinator.write_text(json.dumps(role))
    service = load_coordinator_service_config(coordinator)
    path = _pipeline_config(tmp_path)
    authored = json.loads(path.read_text())
    authored["pipeline"]["stages"][0]["config"] = {"_recipe_": "stateful-value"}
    path.write_text(json.dumps(authored))
    calls = 0

    def stateful_value() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": 40 + calls}

    catalog = RecipeCatalog()
    catalog.register("stateful-value", stateful_value)
    composed = compose_config_with_catalog(path, recipe_catalog=catalog)
    assert calls == 1 and composed.recipe_manifest
    path.unlink()
    checked = run_preflight_composed(
        composed,
        PreflightRequest(
            config_path=path, groups=("config", "pipeline", "selectors", "runtime")
        ),
    )
    assert checked.status is PreflightStatus.PASS
    requirements = {
        "produce": ExecutionRequirement("project-1", "environment-1", "executor-1")
    }
    receipt = prepare_managed_run(
        service, composed, "checked-recipe", execution_requirements=requirements
    )
    store = LocalRunStore(tmp_path / "runs")
    assert store.read_recipe_manifest(receipt.run_uri) == composed.recipe_manifest
    assert store.read_composition_manifest(receipt.run_uri) == composed.manifest.to_dict()
    assert store.read_run_user_metadata(receipt.run_uri) == {
        "config_provenance": composed.provenance.to_dict()
    }
    snapshot = store.read_config_snapshot(receipt.run_uri, "resolved")
    assert snapshot is not None
    resolved = json.loads(snapshot)
    assert resolved["pipeline"]["stages"][0]["config"] == {"value": 41}
    run_dir = store.local_run_dir(receipt.run_uri)
    before = {
        item.relative_to(run_dir): (item.read_bytes(), item.stat().st_mtime_ns)
        for item in run_dir.rglob("*") if item.is_file()
    }
    assert prepare_managed_run(
        service, composed, "checked-recipe", execution_requirements=requirements
    ) == receipt
    assert {
        item.relative_to(run_dir): (item.read_bytes(), item.stat().st_mtime_ns)
        for item in run_dir.rglob("*") if item.is_file()
    } == before
    assert calls == 1


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
    store = LocalRunStore(tmp_path / "runs")
    freshness_before = store.read_run_freshness(fresh.run_uri)
    before = {
        path.relative_to(run_dir): (
            path.read_bytes(),
            path.stat().st_size,
            path.stat().st_mtime_ns,
            path.stat().st_ctime_ns,
        )
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    replay = prepare_managed_local_run(coordinator, pipeline, "starter-1")

    assert replay == fresh
    after = {
        path.relative_to(run_dir): (
            path.read_bytes(),
            path.stat().st_size,
            path.stat().st_mtime_ns,
            path.stat().st_ctime_ns,
        )
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert store.read_run_freshness(fresh.run_uri) == freshness_before
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


def test_preparation_rejects_unsupported_service_families_before_run_creation(
    tmp_path: Path,
) -> None:
    cases: tuple[tuple[Callable[[], Path], str], ...] = (
        (
            lambda: _coordinator_config(
                tmp_path, agent_server=_listener_config()
            ),
            "agent listener",
        ),
        (
            lambda: _coordinator_config(
                tmp_path, remote_profiles=[_descriptor()]
            ),
            "remote profiles",
        ),
        (
            lambda: _coordinator_config(
                tmp_path,
                agent_policy=_remote_agent_policy(include_agents=True),
            ),
            "remote agents or principals",
        ),
        (
            lambda: _coordinator_config(
                tmp_path,
                agent_policy=_remote_agent_policy(include_principals=True),
            ),
            "remote agents or principals",
        ),
        (
            lambda: _coordinator_config(
                tmp_path, slurm_profiles=[_slurm_profile()]
            ),
            "SLURM profiles",
        ),
    )
    for create_config, message in cases:
        coordinator = create_config()
        pipeline = _pipeline_config(tmp_path)

        with pytest.raises(QueueServiceError, match=message):
            prepare_managed_local_run(coordinator, pipeline, "starter-1")

        assert not (tmp_path / "runs" / "starter-1").exists()


def test_preparation_allows_local_owner_policy(tmp_path: Path) -> None:
    coordinator = _coordinator_config(
        tmp_path,
        agent_policy={
            "revision": "policy-1",
            "agents": [],
            "principals": [],
            "local_owner": {
                "actions": ["cancel_active"],
                "agent_ids": [],
                "pools": [],
            },
        },
    )

    receipt = prepare_managed_local_run(
        coordinator, _pipeline_config(tmp_path), "starter-1"
    )

    assert receipt.run_uri == path_to_run_uri(tmp_path / "runs" / "starter-1")


def test_preparation_requires_local_agent_before_run_creation(tmp_path: Path) -> None:
    coordinator = _coordinator_config(tmp_path)
    payload = json.loads(coordinator.read_text())
    payload["local_agent"] = None
    coordinator.write_text(json.dumps(payload))
    with pytest.raises(QueueServiceError, match="requires an embedded local agent"):
        prepare_managed_local_run(
            coordinator, _pipeline_config(tmp_path), "starter-1"
        )
    assert not (tmp_path / "runs" / "starter-1").exists()


def test_composed_preparation_uses_trusted_inputs_without_a_local_agent(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator_config(tmp_path)
    payload = json.loads(coordinator.read_text(encoding="utf-8"))
    payload["local_agent"] = None
    coordinator.write_text(json.dumps(payload), encoding="utf-8")
    coordinator.chmod(0o600)
    service = load_coordinator_service_config(coordinator)
    pipeline = _pipeline_config(tmp_path)
    composed = compose_config(pipeline)
    requirements = {
        "produce": ExecutionRequirement("project-1", "environment-1", "executor-1")
    }

    _pipeline_config(tmp_path, value=43)
    coordinator.write_text("not a deployment config", encoding="utf-8")
    receipt = prepare_managed_run(
        service,
        composed,
        "coordinator-only",
        execution_requirements=requirements,
    )

    store = LocalRunStore(tmp_path / "runs")
    run_dir = store.local_run_dir(receipt.run_uri)
    before = {
        path.relative_to(run_dir): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    resolved_snapshot = store.read_config_snapshot(receipt.run_uri, "resolved")
    assert resolved_snapshot is not None
    assert json.loads(resolved_snapshot)["pipeline"]["stages"][0]["config"]["value"] == 42
    assert (
        prepare_managed_run(
            service,
            composed,
            "coordinator-only",
            execution_requirements=requirements,
        )
        == receipt
    )
    after = {
        path.relative_to(run_dir): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    assert after == before

    with pytest.raises(
        QueueConflictError, match="existing partial, corrupt, or changed"
    ):
        prepare_managed_run(
            service,
            composed,
            "coordinator-only",
            execution_requirements={
                "produce": ExecutionRequirement(
                    "project-1", "environment-2", "executor-1"
                )
            },
        )


def test_composed_preparation_rejects_incomplete_requirements_before_creation(
    tmp_path: Path,
) -> None:
    service = load_coordinator_service_config(_coordinator_config(tmp_path))
    composed = compose_config(_pipeline_config(tmp_path))

    with pytest.raises(QueueServiceError, match="requirements must exactly cover"):
        prepare_managed_run(
            service,
            composed,
            "missing-requirement",
            execution_requirements={},
        )

    assert not (tmp_path / "runs" / "missing-requirement").exists()


def test_preparation_replay_rejects_changed_scheduling_composition(
    tmp_path: Path,
) -> None:
    coordinator = _coordinator_config(tmp_path)
    pipeline = _pipeline_config(tmp_path)
    prepare_managed_local_run(coordinator, pipeline, "starter-1")

    payload = json.loads(coordinator.read_text(encoding="utf-8"))
    payload["scheduling"] = _replay_scheduling()
    coordinator.write_text(json.dumps(payload), encoding="utf-8")
    coordinator.chmod(0o600)

    with pytest.raises(
        QueueConflictError, match="existing partial, corrupt, or changed"
    ):
        prepare_managed_local_run(coordinator, pipeline, "starter-1")


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
    root: Path,
    *,
    remote_profiles: list[dict[str, object]] | None = None,
    agent_policy: dict[str, object] | None = None,
    agent_server: dict[str, object] | None = None,
    scheduling: dict[str, object] | None = None,
    slurm_profiles: list[dict[str, object]] | None = None,
) -> Path:
    agent = root / "agent.yaml"
    agent.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.local-agent-service",
                "agent_root": "deployment/agent",
                "resident_profiles": [
                    {
                        "descriptor": _descriptor(),
                        "project_root": str(root),
                        "python_executable": sys.executable,
                        "cpu_capacity": 1,
                        "memory_capacity_bytes": 0,
                        "gpu_devices": [],
                        "environment": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    agent.chmod(0o600)
    source = root / "coordinator.yaml"
    source.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.coordinator-service",
                "deployment_root": "deployment",
                "run_store_root": "runs",
                "machine_id": "local-machine",
                "poll_interval_seconds": 0.01,
                "max_accepted_time_step_seconds": 60,
                "local_agent": {"config": "agent.yaml", "env_file": None},
                "remote_profiles": remote_profiles or [],
                "agent_policy": agent_policy
                or {"revision": "policy-1", "agents": [], "principals": []},
                "agent_server": agent_server,
                "authority": {"kind": "embedded"},
                **({} if scheduling is None else {"scheduling": scheduling}),
                **(
                    {} if slurm_profiles is None else {"slurm_profiles": slurm_profiles}
                ),
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


def _listener_config() -> dict[str, object]:
    return {
        "host": "127.0.0.1",
        "port": 8443,
        "certificate_path": "server.crt",
        "private_key_path": "server.key",
        "client_ca_path": "ca.crt",
        "credential_fingerprints": {"a" * 64: "agent-credential"},
    }


def _remote_agent_policy(
    *, include_agents: bool = False, include_principals: bool = False
) -> dict[str, object]:
    return {
        "revision": "policy-1",
        "agents": (
            [
                {
                    "credential_id": "agent-credential",
                    "principal_id": "remote-principal",
                    "agent_id": "remote-agent",
                    "pools": ["default"],
                    "capabilities": [],
                    "gpu_devices": [],
                }
            ]
            if include_agents
            else []
        ),
        "principals": (
            [
                {
                    "credential_id": "client-credential",
                    "principal_id": "remote-client",
                    "role": "client",
                    "actions": [],
                    "agent_ids": [],
                    "pools": [],
                }
            ]
            if include_principals
            else []
        ),
    }


def _slurm_profile() -> dict[str, object]:
    return {
        "profile_id": "training",
        "partition": "cpu",
        "max_outstanding": 2,
        "runner": {
            "_target_": "loom.pipeline.executors.slurm.FakeSlurmCommandRunner",
            "unavailable_commands": [],
        },
        "command_adapter_fingerprint": "fake-slurm-v1",
        "bootstrap_principal_id": "slurm-principal",
        "credential_reference": "slurm-credential",
        "coordinator_endpoint": "https://coordinator.example",
        "project_fingerprint": "project-1",
        "environment_fingerprint": "environment-1",
        "executor_fingerprint": "executor-1",
        "job_private_file_provider": {
            "_target_": "loom.pipeline.executors.slurm.ready_stage.SlurmJobPrivateFileProvider",
            "fixed_path": "/run/loom/capability",
            "descriptor": "test-prolog-v1",
            "helper_argv": ["/bin/true"],
        },
    }


def _replay_scheduling() -> dict[str, object]:
    return {
        "priority_resolver": {
            "_target_": "tests.support.stage29_composition.FixedPriorityResolver",
            "priority": 0,
        },
        "components": {
            "planners": [
                {
                    "_target_": "tests.unit.loom.queue.test_managed_local_preparation.ReplayCpuPlanner"
                }
            ],
            "hard_evaluators": [
                {"_target_": "loom.scheduling.TargetConstraintEvaluator"}
            ],
            "preference_scorers": [
                {
                    "_target_": "loom.pipeline.runtime.scheduling_preferences.PackingPreferenceScorer"
                }
            ],
            "policy": {"_target_": "loom.scheduling.FifoSchedulingPolicy"},
        },
    }


class ReplayCpuPlanner(CpuResourcePlanner):
    descriptor = replace(
        CpuResourcePlanner.descriptor,
        implementation_version="managed-local-replay-test-v2",
        implementation_fingerprint="tests.managed-local.replay-cpu-v2",
    )


class ProduceStage:
    pass
