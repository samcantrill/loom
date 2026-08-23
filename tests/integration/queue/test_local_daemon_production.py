"""Production local-daemon integration coverage."""

from __future__ import annotations

from collections.abc import Mapping
import importlib
from pathlib import Path
import time
from typing import cast

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.planning import PlanSelectors, plan_pipeline
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
    prepare_managed_local_runtime_record,
)
from loom.serialization import json_dumps_pretty
from loom.queue.local_daemon_execution import load_managed_local_intent


pytestmark = pytest.mark.integration


def test_persisted_preprocess_train_run_completes_without_injected_runtime_objects(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "run-1")
    run_store.create_run(run_uri)
    pipeline_config = {
        "name": "daemon-production",
        "stages": [
            {
                "name": "preprocess",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.JsonProducerStage"
                    )
                },
                "config": {"value": 42},
                "resources": {
                    "entries": {
                        "cpu": {"kind": "cpu", "amount": 1, "unit": "count"}
                    }
                },
                "outputs": {
                    "data": {
                        "artifact_type": "json",
                        "codec_key": "json.v1",
                    }
                },
            },
            {
                "name": "train",
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.TextConsumerStage"
                    )
                },
                "depends_on": ["preprocess"],
                "inputs": {"data": "preprocess.data"},
                "resources": {
                    "entries": {
                        "cpu": {"kind": "cpu", "amount": 1, "unit": "count"}
                    }
                },
                "outputs": {
                    "text": {
                        "artifact_type": "text",
                        "codec_key": "text.v1",
                    }
                },
            },
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(
            run_store.local_artifact_root(run_uri)
        ),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {
                name: {"executor": "local"} for name in spec.stage_names
            },
        },
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store, run_uri=run_uri, plan=plan, pipeline=spec
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)

    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "daemon" / "coordinator",
        agent_root=tmp_path / "daemon" / "agent",
        run_store_root=run_root,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        submitted = client.submit(
            LocalDaemonAdmissionRequest("queue-1", run_uri)
        )
        completed = client.wait("queue-1", timeout_seconds=10)
        status = client.status()

        assert submitted.state is LocalDaemonAdmissionState.PENDING_AUTHORITY
        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        owner_view = status.runs[0]
        assert cast(Mapping[str, object], owner_view["admission"])["owner"] == (
            "coordinator"
        )
        assert cast(Mapping[str, object], owner_view["authority"])["owner"] == (
            "per-run-authority"
        )
        assert cast(Mapping[str, object], owner_view["scheduling"])["owner"] == (
            "coordinator-stage-work"
        )
        assignment_view = cast(Mapping[str, object], owner_view["assignment"])
        assert assignment_view["owner"] == "coordinator-assignments"
        assert len(cast(list[object], assignment_view["assignments"])) == 2
        assert cast(Mapping[str, object], owner_view["execution"])["owner"] == (
            "local-agent"
        )
        assert len(
            cast(
                list[object],
                cast(Mapping[str, object], owner_view["execution"])["journal"],
            )
        ) == 2
        assert status.service_diagnostic is None
        snapshot = authority.open_run(run_uri)
        assert snapshot.status is RunStatus.SUCCEEDED
        assert [stage.stage_name for stage in snapshot.stages] == [
            "preprocess",
            "train",
        ]
        assert all(
            stage.status is StageStatus.SUCCEEDED for stage in snapshot.stages
        )
        assert run_store.read_stage_outputs(run_uri, "preprocess") is None
        assert run_store.read_stage_outputs(run_uri, "train") is None
    finally:
        daemon.stop()


def test_managed_local_hard_cutover_rejects_old_import_and_existing_roots(
    tmp_path: Path,
) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("loom.queue.managed_local")

    coordinator = tmp_path / "legacy-coordinator.sqlite"
    coordinator.write_bytes(b"old-managed-local-state")
    config = LocalDaemonConfig(
        coordinator_root=coordinator,
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
    )
    before = coordinator.read_bytes()
    with pytest.raises(Exception, match="fresh roots"):
        LocalDaemon.initialize(config)
    assert coordinator.read_bytes() == before


def test_admission_digest_covers_the_resolved_pipeline_snapshot(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_store, run_uri, pipeline_config = _persist_single_stage_run(run_root)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
    )
    load_managed_local_intent(config, run_uri)
    stages = cast(list[dict[str, object]], pipeline_config["stages"])
    stages[0]["config"] = {"value": 99}
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )

    with pytest.raises(Exception, match="conflicts with exact runtime record"):
        load_managed_local_intent(config, run_uri)


def test_safe_runtime_metadata_cannot_activate_a_run_without_exact_record(
    tmp_path: Path,
) -> None:
    run_store, run_uri, _pipeline = _persist_single_stage_run(tmp_path / "runs")
    exact = run_store.local_run_dir(run_uri) / "config" / "managed_local_runtime.json"
    exact.unlink()
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
    )

    with pytest.raises(Exception, match="fresh exact runtime record"):
        load_managed_local_intent(config, run_uri)


def test_terminal_authority_truth_wins_a_late_cancellation(
    tmp_path: Path,
) -> None:
    _store, run_uri, _pipeline = _persist_single_stage_run(tmp_path / "runs")
    SQLitePerRunAuthorityStore(run_uri).create_run(run_uri, status=RunStatus.SUCCEEDED)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("late-cancel", run_uri))
        client.cancel("late-cancel")
        assert client.wait("late-cancel", timeout_seconds=10).state is (
            LocalDaemonAdmissionState.SUCCEEDED
        )
    finally:
        daemon.stop()


def test_pending_cancellation_installs_authority_epoch_before_any_stage(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    _run_store, run_uri, _pipeline = _persist_single_stage_run(run_root)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("cancel-before-authority", run_uri))
        requested = client.cancel("cancel-before-authority")
        authority = SQLitePerRunAuthorityStore(run_uri)
        authority.create_run(run_uri, status=RunStatus.RUNNING)
        cancelled = client.wait("cancel-before-authority", timeout_seconds=10)

        assert requested.state is LocalDaemonAdmissionState.CANCELLATION_REQUESTED
        assert cancelled.state is LocalDaemonAdmissionState.CANCELLED
        snapshot = authority.open_run(run_uri)
        assert snapshot.status is RunStatus.CANCELLED
        assert snapshot.stages == ()
    finally:
        daemon.stop()


def test_connected_active_cancellation_withholds_output_commit(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "active-cancel")
    run_store.create_run(run_uri)
    started_marker = tmp_path / "worker-started"
    pipeline_config = {
        "name": "daemon-active-cancel",
        "stages": [
            {
                "name": "slow",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.SleepStage"
                },
                "config": {
                    "seconds": 0.4,
                    "started_marker": str(started_marker),
                },
                "outputs": {
                    "data": {
                        "artifact_type": "json",
                        "codec_key": "json.v1",
                    }
                },
            }
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {"slow": {"executor": "local"}}},
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store, run_uri=run_uri, plan=plan, pipeline=spec
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    server = LocalDaemonSocketServer(daemon, config.endpoint)
    server.start()
    try:
        client = LocalDaemonSocketClient(config.endpoint)
        client.submit(LocalDaemonAdmissionRequest("cancel-active", run_uri))
        deadline = time.monotonic() + 5
        while not started_marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started_marker.exists()
        active = next(
            admission
            for admission in client.status().admissions
            if admission.queue_item_id == "cancel-active"
        )
        assert active.state is LocalDaemonAdmissionState.ACTIVE
        client.cancel("cancel-active")
        cancelled = client.wait("cancel-active", timeout_seconds=10)

        assert cancelled.state is LocalDaemonAdmissionState.CANCELLED
        stage = authority.open_run(run_uri).stages[0]
        assert stage.status is StageStatus.CANCELLED
        assert stage.latest_commit is None
        assert stage.artifact_facts == ()
    finally:
        server.stop()
        daemon.stop()


def test_daemon_overlaps_independent_runs_with_available_capacity(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    marker_dir = tmp_path / "overlap-markers"
    first_uri = _persist_coordinated_run(
        run_root,
        run_name="first-run",
        stage_name="first",
        marker_dir=marker_dir,
    )
    second_uri = _persist_coordinated_run(
        run_root,
        run_name="second-run",
        stage_name="second",
        marker_dir=marker_dir,
    )
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
        cpu_capacity=2,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("first-item", first_uri))
        client.submit(LocalDaemonAdmissionRequest("second-item", second_uri))

        first = client.wait("first-item", timeout_seconds=10)
        second = client.wait("second-item", timeout_seconds=10)

        assert first.state is LocalDaemonAdmissionState.SUCCEEDED
        assert second.state is LocalDaemonAdmissionState.SUCCEEDED
        assert {path.name for path in marker_dir.glob("*.started")} == {
            "first.started",
            "second.started",
        }
        assert SQLitePerRunAuthorityStore(first_uri).open_run(
            first_uri
        ).status is RunStatus.SUCCEEDED
        assert SQLitePerRunAuthorityStore(second_uri).open_run(
            second_uri
        ).status is RunStatus.SUCCEEDED
    finally:
        daemon.stop()


def test_daemon_reconciles_skip_without_creating_an_assignment(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    _store, run_uri, _pipeline = _persist_single_stage_run(run_root, skip=True)
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("skip-item", run_uri))
        completed = client.wait("skip-item", timeout_seconds=10)

        snapshot = authority.open_run(run_uri)
        status = client.status()
        assert completed.state is LocalDaemonAdmissionState.SUCCEEDED
        assert snapshot.status is RunStatus.SUCCEEDED
        assert snapshot.stages[0].status is StageStatus.SKIPPED
        assignment_view = cast(
            Mapping[str, object], status.runs[0]["assignment"]
        )
        assert assignment_view["assignments"] == []
    finally:
        daemon.stop()


def test_daemon_projects_stage_failure_to_authority_run_and_admission(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    _store, run_uri, _pipeline = _persist_single_stage_run(
        run_root,
        factory_target="tests.support.pipeline_execution_stages.FailingStage",
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=run_root,
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("integration-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("failed-item", run_uri))
        completed = client.wait("failed-item", timeout_seconds=10)

        assert completed.state is LocalDaemonAdmissionState.FAILED
        assert authority.open_run(run_uri).status is RunStatus.FAILED
    finally:
        daemon.stop()


def _persist_single_stage_run(
    run_root: Path,
    *,
    skip: bool = False,
    factory_target: str = (
        "tests.support.pipeline_execution_stages.JsonProducerStage"
    ),
) -> tuple[LocalRunStore, str, dict[str, object]]:
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "run-1")
    run_store.create_run(run_uri)
    pipeline_config: dict[str, object] = {
        "name": "daemon-single-stage",
        "stages": [
            {
                "name": "build",
                "factory": {"_target_": factory_target},
                "config": {"value": 1},
                "outputs": {
                    "data": {
                        "artifact_type": "json",
                        "codec_key": "json.v1",
                    }
                },
            }
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        selectors=PlanSelectors(skip_stages=("build",)) if skip else None,
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {"build": {"executor": "local"}}},
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store, run_uri=run_uri, plan=plan, pipeline=spec
    )
    return run_store, run_uri, pipeline_config


def _persist_coordinated_run(
    run_root: Path,
    *,
    run_name: str,
    stage_name: str,
    marker_dir: Path,
) -> str:
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / run_name)
    run_store.create_run(run_uri)
    pipeline_config = {
        "name": run_name,
        "stages": [
            {
                "name": stage_name,
                "factory": {
                    "_target_": (
                        "tests.support.pipeline_execution_stages.CoordinatedStage"
                    )
                },
                "config": {
                    "marker_dir": str(marker_dir),
                    "wait_for": 2,
                    "timeout_seconds": 5,
                },
                "resources": {
                    "entries": {
                        "cpu": {"kind": "cpu", "amount": 1, "unit": "count"}
                    }
                },
                "outputs": {
                    "data": {"artifact_type": "json", "codec_key": "json.v1"}
                },
            }
        ],
    }
    spec = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "stages": {stage_name: {"executor": "local"}}},
    )
    run_store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline_config}),
    )
    prepare_managed_local_runtime_record(
        store=run_store, run_uri=run_uri, plan=plan, pipeline=spec
    )
    SQLitePerRunAuthorityStore(run_uri).create_run(
        run_uri, status=RunStatus.RUNNING
    )
    return run_uri
