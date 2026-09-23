"""Real preparation and remote execution across independently mapped shared roots."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import os
import sqlite3
import sys
from typing import Any, cast

import pytest

from loom.coordinator import CoordinatorClient
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonAdmissionRequest, LocalDaemonSocketServer
from loom.queue.agent_sessions import AgentRegistration, AgentOffer
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig, AgentTlsServerConfig, LocalDaemonAgentHttpClient,
    LocalDaemonAgentHttpServer, _resident_provider_descriptors,
)
from loom.queue.deployment import load_coordinator_service_config
from loom.queue._remote_stage_execution import (
    ResidentExecutionProfile, ResidentProfileDescriptor,
    REMOTE_EXECUTION_CAPABILITY, REGULAR_FILE_RELAY_CAPABILITY, _ResidentAssignmentWorkspace,
)
from loom.queue.resident_readiness import qualified_resident_profile, ResidentReadinessRequirements
from loom.queue.shared_execution import SHARED_EXECUTION_CAPABILITY
from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint
from tests.integration.queue.test_preparation_operations import _service, _request, _result

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("scenario", ["small", "scientific", "unresolved_restart", "workspace_restart", "started_restart", "cancel_missing"])
def test_shared_prepare_a_execute_b_without_input_relay(tmp_path, monkeypatch, scenario):
    scientific = scenario == "scientific"
    _service(tmp_path)
    first = tmp_path / "nas" / "data"
    second = tmp_path / "mnt" / "lab" / "data"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    payload = b"the same admitted immutable shared bytes"
    (first / "selected.bin").write_bytes(payload)
    (first / "challenge").write_bytes(b"bounded-shared-challenge")
    for name in ("selected.bin", "challenge"):
        os.link(first / name, second / name)
    challenge = hashlib.sha256((first / "challenge").read_bytes()).hexdigest()
    control = tmp_path / "control-payloads"
    control.mkdir()
    (control / "challenge").write_bytes(b"control-challenge")
    def roots(path):
        return {"data": {"host_path": str(path), "container_path": "/loom/data", "access": "ro",
                         "challenge": {"path": "challenge", "sha256": challenge}},
                "control": {"host_path": str(control if path == first else Path("/proc/self/root") / control.relative_to("/")), "container_path": None, "access": "rw",
                    "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"control-challenge").hexdigest()}}}
    location = {"kind": "loom.shared-location", "schema_version": 1, "root_id": "data", "path": "selected.bin"}
    agent_path = tmp_path / "agent.json"
    authored_agent = json.loads(agent_path.read_text())
    authored_agent["resident_profiles"][0]["shared_roots"] = roots(first)
    agent_path.write_text(json.dumps(authored_agent))
    pipeline_path = tmp_path / "projects" / "pipeline.yaml"
    pipeline = json.loads(pipeline_path.read_text())
    stage = pipeline["pipeline"]["stages"][0]
    stage["factory"] = {"_target_": "tests.support.shared_execution_stages.SharedInputConsumer"}
    stage["config"] = {"input": location, "expected": hashlib.sha256(payload).hexdigest()}
    nested = {}
    if scientific:
        nested = {"values": [0.5] * 80, "text": "x" * (140 * 1024)}
        for _ in range(40):
            nested = {"nested": nested}
        stage["config"]["scientific"] = nested
    stage["outputs"] = {"receipt": {"artifact_type": "json", "codec_key": "json.v1"}}
    stage["placement"] = {"target": "worker-b"}
    pipeline_path.write_text(json.dumps(pipeline))
    executor = qualified_resident_profile(ResidentExecutionProfile(
        ResidentProfileDescriptor("execute-profile", "v1", "project", "environment", "executor"),
        Path(__file__).resolve().parents[3], Path(sys.executable),
        readiness_requirements=ResidentReadinessRequirements(imports=("loom", "loom.preparation", "weave")),
        shared_roots=roots(second),
    ))
    # A worker installation needs only the existing shared execution contract;
    # the new host transport capability must not invalidate retained workers.
    assert executor.readiness_result is not None and executor.readiness_result.ok
    assert not any(check.check_id == "packages.shared_assignment" for check in executor.readiness_result.checks)
    missing_roots = replace(executor, descriptor=replace(executor.descriptor, profile_id="missing-roots"), shared_roots={})
    assert not missing_roots.descriptor.shared_roots
    capabilities = ("python", REMOTE_EXECUTION_CAPABILITY, REGULAR_FILE_RELAY_CAPABILITY, SHARED_EXECUTION_CAPABILITY, "shared-assignment-reference-v1")
    config_path = tmp_path / "coordinator.json"
    authored = json.loads(config_path.read_text())
    authored["assignment_payload_root_id"] = "control"
    profile = authored["preparation"]["profiles"]["existing-project"]
    profile.update(configuration_policy="shared", shared_locations=[location], project_processor={
        "schema_version": 1, "callable": "tests.support.shared_execution_stages:inspect_shared",
        "evidence_namespace": "shared-example", "recovery_stage": None,
    })
    authored["remote_profiles"] = [executor.descriptor.to_dict(), missing_roots.descriptor.to_dict()]
    authored["agent_policy"]["agents"] = [{"credential_id": "agent", "principal_id": "worker-b", "agent_id": "worker-b",
        "pools": ["default"], "capabilities": list(capabilities), "gpu_devices": []}]
    config_path.write_text(json.dumps(authored))
    service = load_coordinator_service_config(config_path)
    assert service.daemon.resident_worker_launch_profile is not None
    local = ResidentProfileDescriptor.from_dict(service.daemon.resident_worker_launch_profile.descriptor)
    assert local.project_fingerprint == executor.descriptor.project_fingerprint
    assert local.shared_roots == executor.descriptor.shared_roots
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    credentials = mutual_tls_credentials(tmp_path / "tls")
    daemon.start()
    unix = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    unix.start()
    server = LocalDaemonAgentHttpServer(daemon, AgentTlsServerConfig(
        "localhost", 0, credentials["server"].with_suffix(".crt"), credentials["server"].with_suffix(".key"),
        credentials["ca"].with_suffix(".crt"), {certificate_fingerprint(credentials["agent"].with_suffix(".crt")): "agent"},
    ))
    server.start()
    config = AgentTlsClientConfig(f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"), credentials["agent"].with_suffix(".key"), tmp_path / "remote" / "agent", (executor, missing_roots))
    assert config.agent_root is not None
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    remote = LocalDaemonAgentHttpClient(config)
    try:
        handshake = remote.handshake()
        session = remote.register(AgentRegistration("register-b", str(handshake["coordinator_id"]), str(handshake["coordinator_epoch"]),
            remote.agent_root_id, "config-1", "inventory-1", "availability-1", ("default",), capabilities))
        remote.publish_offer(AgentOffer(session.session_id, session.coordinator_epoch, session.config_revision,
            session.inventory_revision, session.availability_revision, 1, 0, 30,
            _resident_provider_descriptors(executor, session.agent_id), resident_profiles=(missing_roots.descriptor,)), idempotency_key="offer-missing-roots")
        def forbidden(*args, **kwargs):
            raise AssertionError("shared input must never enter staged payload relay")
        monkeypatch.setattr(_ResidentAssignmentWorkspace, "stage_input_chunk", forbidden)
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            client.prepare_run(_request())
            prepared = client.wait_operation("prepare-1", timeout_seconds=25).operation
            assert prepared.state == "applied", prepared
            result = _result(prepared)
            assert result["input_receipt"]["mode"] == "shared"
            child = client.admission(result["preparation_admission_id"]).admission
            assert child.state.value == "SUCCEEDED"
            pipeline_path.write_text("authored files changed after capture")
            target_uri = result["prepared_run"]["run_uri"]
            client.submit(LocalDaemonAdmissionRequest("target", target_uri))
            unavailable = remote.wait_for_work(session.session_id, session.availability_revision, sequence=1, wait_timeout_ms=250)
            assert unavailable["result"] == "wait"
            with sqlite3.connect(service.daemon.execution_database) as conn:
                assert conn.execute("SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ?", (target_uri,)).fetchone()[0] == 0
            remote.publish_offer(AgentOffer(session.session_id, session.coordinator_epoch, session.config_revision,
                session.inventory_revision, session.availability_revision, 1, 0, 30,
                _resident_provider_descriptors(executor, session.agent_id), resident_profiles=(executor.descriptor,)), idempotency_key="offer-qualified")
            payload_backup = None
            payload_path = None
            if scenario in {"unresolved_restart", "cancel_missing"}:
                original_resolve = remote._resolve_delivery
                def missing_payload(sid, raw):
                    nonlocal payload_path, payload_backup
                    payload_path = control / raw["location"]["path"]
                    payload_backup = payload_path.read_bytes()
                    payload_path.unlink()
                    return original_resolve(sid, raw)
                monkeypatch.setattr(remote, "_resolve_delivery", missing_payload)
            elif scenario == "workspace_restart":
                original_resolve = remote._resolve_delivery
                def interrupt_workspace(sid, raw):
                    original_resolve(sid, raw)
                    raise RuntimeError("application restart")
                monkeypatch.setattr(remote, "_resolve_delivery", interrupt_workspace)
            elif scenario == "started_restart":
                def interrupt_result(*args, **kwargs):
                    raise RuntimeError("application restart")
                monkeypatch.setattr(remote, "commit_result", interrupt_result)
            if scenario in {"unresolved_restart", "workspace_restart", "started_restart", "cancel_missing"}:
                from loom.queue.errors import QueueServiceError
                with pytest.raises((QueueServiceError, RuntimeError), match="unavailable|application restart"):
                    remote.execute_one(session.session_id, session.availability_revision, sequence=2, wait_timeout_ms=5000)
                if scenario in {"unresolved_restart", "cancel_missing"}:
                    from loom.queue.errors import QueueConflictError
                    with pytest.raises(QueueConflictError, match="cannot advertise"):
                        remote.publish_offer(AgentOffer(session.session_id, session.coordinator_epoch,
                            session.config_revision, session.inventory_revision, session.availability_revision,
                            1, 0, 30, _resident_provider_descriptors(executor, session.agent_id),
                            resident_profiles=(executor.descriptor,)), idempotency_key="unresolved-offer")
                assert remote._supervisor is not None
                supervisor_id = remote._supervisor.supervisor_id
                remote.close()
                remote = LocalDaemonAgentHttpClient(config)
                assert remote._supervisor is not None
                assert remote._supervisor.supervisor_id == supervisor_id
                if scenario in {"unresolved_restart", "cancel_missing"}:
                    assert remote._require_journal().has_unresolved_assignment_references()
                    if scenario == "cancel_missing":
                        client.cancel("target")
                        def interrupt_decline(*args, **kwargs):
                            raise RuntimeError("before cancellation settlement")
                        monkeypatch.setattr(remote, "decline_assignment", interrupt_decline)
                        with pytest.raises(RuntimeError, match="cancellation settlement"):
                            remote.resume_retained_work()
                        remote.close()
                        remote = LocalDaemonAgentHttpClient(config)
                        remote.resume_retained_work()
                        assert not remote._require_journal().has_unresolved_assignment_references()
                        assert client.wait("target", timeout_seconds=25).state.value == "CANCELLED"
                        return
                    with pytest.raises(QueueServiceError, match="unavailable"):
                        remote.resume_retained_work()
                    assert payload_path is not None and payload_backup is not None
                    payload_path.write_bytes(payload_backup)
                else:
                    with sqlite3.connect(service.daemon.control_database) as conn:
                        reference_json = conn.execute("SELECT reference_json FROM agent_deliveries").fetchone()[0]
                    payload_path = control / json.loads(reference_json)["location"]["path"]
                    payload_backup = payload_path.read_bytes()
                    payload_path.unlink()
                if scenario in {"unresolved_restart", "started_restart"}:
                    import multiprocessing
                    from tests.integration.queue.test_agent_session_transport import _reconcile_remote_agent_application
                    remote.close()
                    context = multiprocessing.get_context("spawn")
                    events = context.Queue()
                    process = context.Process(target=_reconcile_remote_agent_application,
                        args=(config, session.session_id, events))
                    process.start()
                    try:
                        event = events.get(timeout=60)
                        process.join(timeout=20)
                        assert process.exitcode == 0
                        assert event[0] == "replayed", event
                        assert event[1] != os.getpid()
                        assert event[2:5] == (True, True, ("RELEASED",))
                        assert event[5] == supervisor_id
                        executed = {"state": event[4][0]}
                    finally:
                        if process.is_alive():
                            process.kill()
                            process.join()
                        events.close()
                    remote = LocalDaemonAgentHttpClient(config)
                else:
                    (executed,) = remote.resume_retained_work()
                assert remote.resume_retained_work() == ()
                assert payload_path is not None and payload_backup is not None
                payload_path.write_bytes(payload_backup)
                with sqlite3.connect(config.agent_root / "supervisor" / "supervisor.sqlite") as conn:
                    assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 1
            else:
                executed = remote.execute_one(session.session_id, session.availability_revision, sequence=2, wait_timeout_ms=5000)
            assert executed["state"] == "RELEASED", executed
            assert client.wait("target", timeout_seconds=25).state.value == "SUCCEEDED"
            with sqlite3.connect(service.daemon.execution_database) as conn:
                owners = conn.execute("SELECT run_uri, agent_id FROM coordinator_assignments").fetchall()
            assert (child.run_uri, service.daemon.machine_id) in owners
            assert (target_uri, "worker-b") in owners
            from loom.pipeline.stores import LocalRunStore, LocalArtifactStore
            from loom.pipeline.execution.models import StageWorkerResult
            store = LocalRunStore(service.daemon.run_store_root)
            worker_result = StageWorkerResult.from_dict(store.read_stage_worker_result(target_uri, "produce", attempt=1))
            receipt = cast(dict[str, Any], LocalArtifactStore(store.local_artifact_root(target_uri)).load(worker_result.outputs["receipt"]))
            child_result = StageWorkerResult.from_dict(store.read_stage_worker_result(child.run_uri, "prepare", attempt=1))
            report = cast(dict[str, Any], LocalArtifactStore(store.local_artifact_root(child.run_uri)).load(child_result.outputs["report"]))
            assert receipt["digest"] == hashlib.sha256(payload).hexdigest()
            assert receipt["execution_pid"] != report["project_result"]["evidence"]["payload"]["prepared_pid"]
            assert report["schema_version"] == 6
            assert "local_scope" not in report
            workspaces = tuple((config.agent_root / "assignments").glob("*"))
            assert workspaces
            request = _ResidentAssignmentWorkspace(config.agent_root, workspaces[0].name).request()
            assert request.schema_version == 5 and request.inputs == ()
            with sqlite3.connect(service.daemon.control_database) as conn:
                full, reference_json = conn.execute("SELECT request_json, reference_json FROM agent_deliveries WHERE assignment_id = ?", (request.assignment_id,)).fetchone()
            ref = json.loads(reference_json)
            assert ref["kind"] == "loom.shared-assignment-reference"
            assert len(reference_json.encode()) < 4096
            data = (control / ref["location"]["path"]).read_bytes()
            assert data == full.encode()
            assert hashlib.sha256(data).hexdigest() == ref["sha256"]
            assert len(data) == ref["size_bytes"]
            if scientific:
                assert len(data) > 128 * 1024
                assert cast(Any, request.to_dict())["fingerprint"]["payload"]["stage_config"]["scientific"] == nested
            assert "control" not in cast(Any, request.to_dict())["fingerprint"]["payload"]["fingerprint_fields"]["loom.shared_execution"]["roots"]
            assert str(first) not in json.dumps(request.to_dict())
            assert str(second) not in json.dumps(request.to_dict())
    finally:
        remote.close()
        server.stop()
        unix.stop()
        daemon.stop()
