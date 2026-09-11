"""Durable preparation through native coordinator admission and worker execution."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
from threading import Event

import pytest

from loom.coordinator import CoordinatorClient
from loom.artifacts import ArtifactRef
from loom.serialization import ensure_plain_data, stable_json_bytes
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.cleanup import (
    CleanupManagedRoot,
    CleanupSafetyReason,
    CleanupTargetKind,
    CleanupTargetRef,
    assess_local_target_safety,
)
from loom.preparation import CoordinatorPreparation
from loom.queue import (
    CoordinatorSchedulingReload,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonSocketClient,
    LocalDaemonSocketServer,
)
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.preparation import PreparationSource, PrepareRunRequest
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue._preparation_operations import PreparationNotAccepted


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _service(tmp_path: Path):
    pytest.importorskip("weave")
    repository = Path(__file__).resolve().parents[3]
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "pipeline.yaml").write_text(
        json.dumps(
            {
                "pipeline": {
                    "name": "example",
                    "stages": [
                        {
                            "name": "produce",
                            "factory": {
                                "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                            },
                            "config": {"value": 41},
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
                        }
                    ],
                },
                "runtime": {"executor": "local"},
            }
        )
    )
    agent = tmp_path / "agent.json"
    agent.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.local-agent-service",
                "agent_root": "deployment/agent",
                "resident_profiles": [
                    {
                        "descriptor": {
                            "profile_id": "existing",
                            "revision": "v1",
                            "project_fingerprint": "project",
                            "environment_fingerprint": "environment",
                            "executor_fingerprint": "executor",
                        },
                        "project_root": str(repository),
                        "python_executable": sys.executable,
                        "cpu_capacity": 1,
                        "memory_capacity_bytes": 0,
                        "gpu_devices": [],
                        "environment": {},
                        "preparation_shared_roots": {"projects": "snapshots"},
                        "readiness": {"imports": ["loom", "loom.preparation", "weave"]},
                    }
                ],
            }
        )
    )
    agent.chmod(0o600)
    coordinator = tmp_path / "coordinator.json"
    coordinator.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.coordinator-service",
                "deployment_root": "deployment",
                "run_store_root": "runs",
                "machine_id": "coordinator",
                "poll_interval_seconds": 0.01,
                "max_accepted_time_step_seconds": 60,
                "local_agent": {"config": "agent.json", "env_file": None},
                "remote_profiles": [],
                "agent_server": None,
                "agent_policy": {
                    "revision": "v1",
                    "agents": [],
                    "principals": [],
                    "local_owner": {
                        "actions": ["scheduling_reload"],
                        "agent_ids": [],
                        "pools": [],
                    },
                },
                "authority": {"kind": "embedded"},
                "preparation": {
                    "source_roots": {
                        "projects": {
                            "path": "projects",
                            "shared_snapshot_root": "snapshots",
                        }
                    },
                    "profiles": {
                        "existing-project": {
                            "resident_profile_id": "existing",
                            "allowed_source_roots": ["projects"],
                            "source_modes": ["shared"],
                            "runtime_options": {"executor": "local"},
                        }
                    },
                },
            }
        )
    )
    coordinator.chmod(0o600)
    return load_coordinator_service_config(coordinator)


def _request() -> PrepareRunRequest:
    return PrepareRunRequest(
        "prepare-1",
        "target-1",
        PreparationSource("shared", "projects", ".", ("pipeline.yaml",)),
        "pipeline.yaml",
        "existing-project",
    )


def test_native_unix_prepare_publish_submit_and_reconnect(tmp_path: Path) -> None:
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    daemon.start()
    server.start()
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            accepted = client.prepare_run(_request())
            assert accepted.state == "pending"
            completed = client.wait_operation(
                accepted.operation_id, timeout_seconds=25
            ).operation
            assert completed.state == "applied", (
                completed.to_dict(),
                daemon._service_error,
            )
            receipt = completed.result["prepared_run"]
            assert completed.result["preflight_status"] == "PASS"
            assert completed.result["report_ref"] is not None
            assert client.prepare_run(_request()) == completed
            store = LocalRunStore(service.daemon.run_store_root)
            assert (
                store.read_stage_worker_result(receipt["run_uri"], "produce", attempt=1)
                is None
            )
            assert completed.result["preparation_admission_id"] != accepted.operation_id
            coordinator_id = completed.result["coordinator_id"]
        with CoordinatorClient.from_unix_socket(
            service.daemon.endpoint, expected_coordinator_id=coordinator_id
        ) as client:
            assert client.operation(accepted.operation_id) == completed
            admitted = client.submit(
                LocalDaemonAdmissionRequest("execute-target", receipt["run_uri"])
            )
            outcome = client.wait("execute-target", timeout_seconds=25)
            assert outcome.state.value == "SUCCEEDED", outcome
            detail = client.admission(admitted.admission_id)
            assert detail.admission.run_uri == receipt["run_uri"]
            worker_result = StageWorkerResult.from_dict(
                store.read_stage_worker_result(receipt["run_uri"], "produce", attempt=1)
            )
            assert LocalArtifactStore(
                store.local_artifact_root(receipt["run_uri"])
            ).load(worker_result.outputs["data"]) == {"value": 41}
    finally:
        server.stop()
        daemon.stop()


def test_cancellation_before_capture_is_durable_and_keeps_the_target_absent(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    try:
        accepted = daemon.prepare_run(_request(), principal_id="caller")
        with pytest.raises(QueueConflictError, match="another operation"):
            daemon.prepare_run(
                replace(_request(), operation_id="prepare-other"), principal_id="caller"
            )
        with pytest.raises(QueueConflictError, match="intent conflicts"):
            daemon.prepare_run(_request(), principal_id="another-caller")
        with pytest.raises(PreparationNotAccepted, match="result_too_large"):
            daemon.prepare_run(
                replace(_request(), operation_id="p" * (64 * 1024), run_name="other"),
                principal_id="caller",
            )
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM preparation_operations").fetchone()[
                    0
                ]
                == 1
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM managed_admissions").fetchone()[0]
                == 0
            )
        assert (
            daemon.cancel_preparation(
                accepted.operation_id, principal_id="caller"
            ).state
            == "pending"
        )
        daemon._preparations._reconcile_lock.release()
        completed = daemon.wait_operation(accepted.operation_id, timeout=10).operation
        assert completed.state == "cancelled"
        assert not (tmp_path / "snapshots").exists()
        assert not (tmp_path / "runs" / "target-1").exists()
        assert daemon.prepare_run(_request(), principal_id="caller") == completed
        with pytest.raises(QueueConflictError, match="intent conflicts"):
            daemon.prepare_run(
                replace(_request(), config_path="changed.yaml"), principal_id="caller"
            )
    finally:
        if daemon._preparations._reconcile_lock.locked():
            daemon._preparations._reconcile_lock.release()
        daemon.stop()


@pytest.mark.parametrize(
    "boundary", ("captured", "child_accepted", "published", "report_unavailable")
)
def test_restart_reuses_capture_and_replays_a_claimed_complete_target(
    tmp_path: Path, boundary: str
) -> None:
    service = _service(tmp_path)
    reached = Event()

    class InterruptedPreparation(CoordinatorPreparation):
        def prepare_child(self, *args, **kwargs):
            if boundary == "captured":
                reached.set()
                raise RuntimeError("injected interruption after durable capture")
            return super().prepare_child(*args, **kwargs)

        def publish_target(self, *args, **kwargs):
            receipt = super().publish_target(*args, **kwargs)
            if boundary in {"published", "report_unavailable"}:
                reached.set()
                raise RuntimeError(
                    f"injected interruption after publication of {receipt.run_uri}"
                )
            return receipt

    class InterruptedDaemon(LocalDaemon):
        def _submit(self, *args, **kwargs):
            admitted = super()._submit(*args, **kwargs)
            if boundary == "child_accepted":
                reached.set()
                raise RuntimeError("injected loss of the child admission response")
            return admitted

    LocalDaemon.initialize_deployment(service.daemon)
    config_path = tmp_path / "coordinator.json"
    daemon = InterruptedDaemon(
        service.daemon,
        preparation=InterruptedPreparation(service),
        trusted_scheduling_loader=lambda: (
            load_coordinator_service_config(config_path, current=service).daemon
        ),
    )
    daemon.start()
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    server.start()
    try:
        daemon.prepare_run(_request(), principal_id="caller")
        assert reached.wait(25), daemon.operation("prepare-1")
        # Protected changes use the same atomic reload as the CLI. Accepted
        # preparation retains its snapshot even after new preparation is disabled.
        config_data = json.loads(config_path.read_text())
        config_data.pop("preparation")
        config_path.write_text(json.dumps(config_data))
        reloaded = LocalDaemonSocketClient(service.daemon.endpoint).reload_scheduling(
            CoordinatorSchedulingReload(
                "disable-preparation",
                daemon.status().scheduling_epoch,
                "disable new preparation while retained work reconciles",
            )
        )
        assert reloaded["state"] == "applied", reloaded
    finally:
        server.stop()
        daemon.stop()
    store = LocalRunStore(service.daemon.run_store_root)
    target = service.daemon.run_store_root / "target-1"
    before = {
        path.relative_to(target): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in target.rglob("*")
        if path.is_file()
    }
    (tmp_path / "projects" / "pipeline.yaml").write_text(
        "invalid edited authoring bytes"
    )
    service = load_coordinator_service_config(config_path)
    report_unavailable, allow_report = Event(), Event()

    class ReopenedPreparation(CoordinatorPreparation):
        def read_report(self, *args, **kwargs):
            if boundary == "report_unavailable" and not allow_report.is_set():
                report_unavailable.set()
                raise QueueServiceError(
                    "injected temporary report-store unavailability"
                )
            return super().read_report(*args, **kwargs)

    resumed = LocalDaemon(service.daemon, preparation=ReopenedPreparation(service))
    resumed.start()
    try:
        if boundary == "report_unavailable":
            assert report_unavailable.wait(25)
            assert resumed._preparations._reconcile_lock.acquire(timeout=5)
            try:
                pending = resumed.operation("prepare-1")
                assert pending.state == "applying"
                assert pending.code == "preparation_unavailable"
            finally:
                resumed._preparations._reconcile_lock.release()
            allow_report.set()
        completed = resumed.wait_operation("prepare-1", timeout=25).operation
        assert completed.state == "applied", completed
        receipt = completed.result["prepared_run"]
        assert json.loads(store.read_config_snapshot(receipt["run_uri"], "resolved"))[
            "pipeline"
        ]["stages"][0]["config"] == {"value": 41}
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM managed_admissions").fetchone()[0]
                == 1
            )
        if boundary in {"published", "report_unavailable"}:
            assert {
                path.relative_to(target): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in target.rglob("*")
                if path.is_file()
            } == before
        managed_root = CleanupManagedRoot(
            "fixture",
            str(tmp_path),
            ownership_key="fixture",
            metadata={"owned_by": "loom"},
        )
        for retained in (
            str(target),
            str(
                tmp_path
                / "snapshots"
                / completed.result["input_receipt"]["reference"]["path"]
            ),
            completed.result["report_ref"]["uri"],
        ):
            decision = assess_local_target_safety(
                CleanupTargetRef(
                    CleanupTargetKind.LOCAL_PATH, retained, ownership_key="fixture"
                ),
                (managed_root,),
            )
            assert (
                decision.reason_code
                is CleanupSafetyReason.RETAINED_PREPARATION_EVIDENCE
            )
        assert resumed.prepare_run(_request(), principal_id="caller") == completed
    finally:
        resumed.stop()


def test_partial_target_is_preserved_as_a_publication_conflict(tmp_path: Path) -> None:
    service = _service(tmp_path)
    target = service.daemon.run_store_root / "target-1"
    target.mkdir(parents=True)
    sentinel = target / "partial-write.json"
    sentinel.write_text("interrupted native publication")
    before = sentinel.read_bytes(), sentinel.stat().st_mtime_ns
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.prepare_run(_request(), principal_id="caller")
        completed = daemon.wait_operation("prepare-1", timeout=25).operation
        assert (completed.state, completed.code) == ("conflict", "publication_conflict")
        assert completed.result["preflight_status"] == "PASS"
        assert completed.result["report_ref"] is not None
        assert completed.result["prepared_run"] is None
        assert (sentinel.read_bytes(), sentinel.stat().st_mtime_ns) == before
        assert tuple(target.iterdir()) == (sentinel,)
        assert (
            daemon.cancel_preparation("prepare-1", principal_id="caller") == completed
        )
    finally:
        daemon.stop()


@pytest.mark.parametrize("boundary", ("before_claim", "after_claim"))
def test_cancel_and_publication_race_uses_the_durable_claim(
    tmp_path: Path, boundary: str
) -> None:
    service = _service(tmp_path)
    entered, release = Event(), Event()

    class PausedPreparation(CoordinatorPreparation):
        def read_report(self, *args, **kwargs):
            report = super().read_report(*args, **kwargs)
            if boundary == "before_claim":
                entered.set()
                assert release.wait(25)
            return report

        def publish_target(self, *args, **kwargs):
            if boundary == "after_claim":
                entered.set()
                assert release.wait(25)
            return super().publish_target(*args, **kwargs)

    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=PausedPreparation(service))
    daemon.start()
    try:
        daemon.prepare_run(_request(), principal_id="caller")
        assert entered.wait(25), daemon.operation("prepare-1")
        assert daemon._cycle_lock.acquire(timeout=1), (
            "publication I/O held the global cycle lock"
        )
        daemon._cycle_lock.release()
        cancellation = daemon.cancel_preparation("prepare-1", principal_id="caller")
        assert cancellation.state == (
            "pending" if boundary == "before_claim" else "applying"
        )
        release.set()
        completed = daemon.wait_operation("prepare-1", timeout=25).operation
        assert completed.state == (
            "cancelled" if boundary == "before_claim" else "applied"
        ), completed
        assert (service.daemon.run_store_root / "target-1").exists() is (
            boundary == "after_claim"
        )
        assert (
            daemon.cancel_preparation("prepare-1", principal_id="caller") == completed
        )
    finally:
        release.set()
        daemon.stop()


@pytest.mark.parametrize("large", ("preflight", "receipt"))
def test_native_report_projection_omits_large_checks_and_rejects_large_receipts_before_publication(
    tmp_path: Path, large: str
) -> None:
    service = _service(tmp_path)
    config_path = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(config_path.read_text())
    if large == "preflight":
        authored["runtime"]["notes"] = ["large native check context " * 5000]
    else:
        template = authored["pipeline"]["stages"][0]
        authored["pipeline"]["stages"] = [
            {**template, "name": f"stage_{index:04d}_" + "x" * 80}
            for index in range(800)
        ]
    config_path.write_text(json.dumps(authored))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.prepare_run(_request(), principal_id="caller")
        completed = daemon.wait_operation("prepare-1", timeout=25).operation
        assert completed.state == ("applied" if large == "preflight" else "failed"), (
            completed
        )
        assert len(stable_json_bytes(completed.to_dict())) <= 64 * 1024
        assert completed.result["preflight_status"] == "PASS"
        reference = ArtifactRef.from_dict(
            ensure_plain_data(completed.result["report_ref"])
        )
        report = LocalArtifactStore(service.daemon.run_store_root).load(reference)
        assert report["preflight"]["status"] == "PASS"
        if large == "preflight":
            assert completed.result["preflight"] is None
            assert len(stable_json_bytes(report["preflight"])) > 64 * 1024
            assert completed.result["prepared_run"] is not None
        else:
            assert completed.code == "result_too_large"
            assert not (service.daemon.run_store_root / "target-1").exists()
    finally:
        daemon.stop()
