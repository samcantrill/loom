"""Opt-in actual SIF acceptance; no container runtime or image is mocked.

Set LOOM_SUBMITTED_IMAGES to a directory with aaa/image.sif and aab/image.sif,
containing the installed Loom wheel and submitted_probe (values 11 and 29).
The second image alone defines submitted_probe.NewStage.
"""

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from threading import Event
from time import monotonic, sleep

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
from loom.pipeline.execution.models import ExecutionFailure, StageWorkerResult
from loom.pipeline.executors.containers import ContainerMount
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue._submitted_container_policy import SubmittedContainerPolicy
from loom.queue.agent_session_transport import (
    AgentTlsServerConfig, LocalDaemonAgentHttpClient, LocalDaemonAgentHttpServer,
)
from loom.queue.deployment import (
    load_coordinator_service_config, load_outbound_agent_service_config,
    run_outbound_agent_service,
)
from loom.queue.preparation import PreparationSource, PrepareRunRequest
from loom.queue.submitted_execution import (
    SUBMITTED_CONTAINER_WORKER_CONTRACT, SubmittedContainerExecution, SubmittedImage,
)
from tests.integration.queue.test_preparation_operations import _service
from tests.integration.queue.test_submitted_container_agents import CAPABILITIES
from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]
PHYSICAL_CAPABILITIES = (*CAPABILITIES, "preparation-input-v2")


def _root(path, *, target=None, access="ro", publication=False):
    path.mkdir(parents=True, exist_ok=True)
    (path / "challenge").write_bytes(b"submitted-container-acceptance")
    value = {
        "host_path": str(path), "container_path": target, "access": access,
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(
            b"submitted-container-acceptance").hexdigest()},
    }
    if publication:
        value["publication"] = {
            "max_members": 1024, "max_payload_bytes": 16 * 1024 * 1024,
            "max_manifest_bytes": 1024 * 1024,
        }
    return value


def _image(images, name):
    path = images / name / "image.sif"
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return SubmittedContainerExecution(
        "apptainer", SubmittedImage(
            {"kind": "loom.shared-location", "schema_version": 1,
             "root_id": "images", "path": f"{name}/image.sif"},
            digest, path.stat().st_size,
        ),
        "/usr/local/bin/python", SUBMITTED_CONTAINER_WORKER_CONTRACT,
        {"schema_version": 3, "callable": "submitted_probe:inspect",
         "evidence_namespace": "submitted-probe", "target_prefix": "probe-"},
    )


@pytest.mark.parametrize("scenario", [
    "continuity", "lost_launch_reply", "cancel_with_missing_image", "corrupt_new_image",
    "retry_original_image",
])
def test_submitted_images_preserve_execution_ownership(tmp_path, monkeypatch, scenario):
    selected = os.environ.get("LOOM_SUBMITTED_IMAGES")
    if not selected:
        pytest.skip("LOOM_SUBMITTED_IMAGES is required for actual SIF acceptance")
    runtime = shutil.which("apptainer") or shutil.which("singularity")
    assert runtime, "physical acceptance requires Apptainer/Singularity"
    images = Path(selected).resolve()
    if scenario in {"cancel_with_missing_image", "corrupt_new_image"}:
        # Failure injection owns copies; never alter images pinned by another run.
        original_images = images
        images = tmp_path / "images"
        for name in ("aaa", "aab"):
            shutil.copytree(original_images / name, images / name)
    first, second = _image(images, "aaa"), _image(images, "aab")
    lost = Event()
    if scenario == "lost_launch_reply":
        from loom.queue._agent_process_supervisor import (
            AgentProcessSupervisorClient, _SupervisorCommunicationError,
        )
        from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
        launch = AgentProcessSupervisorClient.launch

        def lose_once(self, selected_launch):
            receipt = launch(self, selected_launch)
            request = _ResidentAssignmentWorkspace.read_request(selected_launch.workspace_root)
            if request.stage_name == "produce" and not lost.is_set():
                lost.set()
                raise _SupervisorCommunicationError(possibly_dispatched=True)
            return receipt

        monkeypatch.setattr(AgentProcessSupervisorClient, "launch", lose_once)
    _service(tmp_path)
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    roots = {
        "images": _root(images),
        "control": _root(tmp_path / "control", access="rw"),
        "snapshots": _root(tmp_path / "snapshots", target="/loom/snapshots"),
        "reports": _root(tmp_path / "reports", target="/loom/probe-reports",
                         access="rw", publication=True),
    }
    policy = SubmittedContainerPolicy(
        "containers", {"command": runtime, "no_home": True}, roots, ("images",),
        preparation_shared_roots={"projects": tmp_path / "snapshots"},
        environment={"PROBE_CONTROL": "/probe-control"},
        mounts=(ContainerMount(str(barrier), "/probe-control", "rw"),),
    )
    coordinator_path = tmp_path / "coordinator.json"
    authored = json.loads(coordinator_path.read_text())
    authored.update(
        local_agent=None, shared_roots=roots, assignment_payload_root_id="control",
        container_capabilities=[policy.capability.to_dict()],
    )
    authored["agent_policy"]["agents"] = [{
        "credential_id": "agent", "principal_id": "worker", "agent_id": "worker",
        "pools": ["default"], "capabilities": list(PHYSICAL_CAPABILITIES), "gpu_devices": [],
    }]
    authored["preparation"]["profiles"] = {"containers": {
        "container_policy_id": "containers", "allowed_source_roots": ["projects"],
        "source_modes": ["shared"], "runtime_options": {"executor": "local"},
    }}
    coordinator_path.write_text(json.dumps(authored))
    service = load_coordinator_service_config(coordinator_path)
    credentials = mutual_tls_credentials(tmp_path / "tls")
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    unix = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    unix.start()
    tls = LocalDaemonAgentHttpServer(daemon, AgentTlsServerConfig(
        "localhost", 0, credentials["server"].with_suffix(".crt"),
        credentials["server"].with_suffix(".key"), credentials["ca"].with_suffix(".crt"),
        {certificate_fingerprint(credentials["agent"].with_suffix(".crt")): "agent"},
    ))
    tls.start()
    agent_path = tmp_path / "outbound.json"
    agent_path.write_text(json.dumps({
        "schema_version": 3, "kind": "loom.outbound-agent-service",
        "agent_root": str(tmp_path / "agent"), "url": f"https://localhost:{tls.port}",
        "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
        "certificate_path": str(credentials["agent"].with_suffix(".crt")),
        "private_key_path": str(credentials["agent"].with_suffix(".key")),
        "resident_profiles": [], "container_policies": [policy.to_dict()],
        "reconnect_seconds": 0.1, "max_concurrent_assignments": 2,
        "registration": {"config_revision": "config", "inventory_revision": "inventory",
                         "availability_revision": "available", "pools": ["default"],
                         "capabilities": list(PHYSICAL_CAPABILITIES)},
        "resources": {"cpu_capacity": 2, "memory_capacity_bytes": 0,
                      "gpu": {"provider": "nvidia", "devices": "none"}},
    }))
    agent_path.chmod(0o600)
    agent = load_outbound_agent_service_config(agent_path)
    LocalDaemonAgentHttpClient.initialize_agent_root(agent.client)
    protected = (coordinator_path.read_bytes(), agent_path.read_bytes())
    stop = Event()
    pool = ThreadPoolExecutor(max_workers=1)
    task = pool.submit(run_outbound_agent_service, agent, stop=stop)
    started = monotonic()
    times = {}

    def request(name, execution, *, wait, reconcile=False):
        pipeline = json.loads((tmp_path / "projects" / "pipeline.yaml").read_text())
        stage = pipeline["pipeline"]["stages"][0]
        stage["factory"] = {"_target_": f"submitted_probe.{'Probe' if wait or reconcile else 'NewStage'}"}
        stage["config"] = {"barrier": wait, **({"fail_once": True} if reconcile else {})}
        path = f"{name}.yaml"
        (tmp_path / "projects" / path).write_text(json.dumps(pipeline))
        preparation = PrepareRunRequest(
            f"submit-{name}", None if reconcile else name, PreparationSource("shared", "projects", ".", (path,)),
            path, "containers", execution=execution,
        )
        return RunRequest(preparation, mode="reconcile") if reconcile else RunRequest(preparation, name)

    def identity():
        with sqlite3.connect(tmp_path / "agent" / "supervisor" / "supervisor.sqlite") as conn:
            supervisor = conn.execute("SELECT * FROM metadata ORDER BY key").fetchall()
        with sqlite3.connect(service.daemon.control_database) as conn:
            coordinator = conn.execute("SELECT * FROM root_metadata ORDER BY key").fetchall()
            gate = json.loads(conn.execute(
                "SELECT value FROM daemon_metadata WHERE key = 'maintenance-gate'").fetchone()[0])
        with sqlite3.connect(tmp_path / "agent" / "control.sqlite") as conn:
            agent_identity = conn.execute("SELECT * FROM root_metadata ORDER BY key").fetchall()
        assert gate["state"] == "open" and gate["revision"] == 0
        return supervisor, coordinator, agent_identity

    def value(client, name, attempt=1):
        admission = client.admission_for_queue_item(name)
        store = LocalRunStore(service.daemon.run_store_root)
        result = StageWorkerResult.from_dict(
            store.read_stage_worker_result(admission.run_uri, "produce", attempt=attempt))
        loaded = LocalArtifactStore(store.local_artifact_root(admission.run_uri)).load(
            result.outputs["data"])
        assert isinstance(loaded, dict)
        return loaded

    def prepared(client, name):
        operation = None
        for _ in range(4):
            operation = client.wait_operation(name, timeout_seconds=25).operation
            if operation.state not in {"pending", "applying"}:
                return operation
        assert operation is not None
        return operation

    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            if scenario == "retry_original_image":
                original = request("aaa", first, wait=False, reconcile=True)
                client.start_run(original)
                initial = prepared(client, original.preparation.operation_id)
                assert initial.state == "applied", initial
                assert isinstance(initial.result, Mapping)
                queue_id = initial.result["queue_item_id"]
                assert isinstance(queue_id, str)
                failed = client.wait(queue_id, timeout_seconds=25)
                assert failed.state.value == "FAILED"
                before = identity()
                client.start_run(request("aab", second, wait=False))
                assert prepared(client, "submit-aab").state == "applied"
                assert client.wait("aab", timeout_seconds=25).state.value == "SUCCEEDED"
                assert value(client, "aab")["value"] == 29
                retry = replace(
                    original, preparation=replace(original.preparation, operation_id="retry-aaa"),
                    retry_policy="one_observed_failure",
                )
                client.start_run(retry)
                retried = prepared(client, "retry-aaa")
                assert retried.state == "applied", retried
                completed = client.wait(queue_id, timeout_seconds=25)
                assert completed.state.value == "SUCCEEDED" and completed.run_uri == failed.run_uri
                assert value(client, queue_id, attempt=2)["value"] == 11
                verify = replace(original, preparation=replace(
                    original.preparation, operation_id="verify-aaa"))
                client.start_run(verify)
                verified = prepared(client, "verify-aaa")
                assert verified.state == "applied", verified
                assert isinstance(verified.result, Mapping)
                assert verified.result["queue_item_id"] == queue_id
                client.start_run(retry)
                assert identity() == before
                assert protected == (coordinator_path.read_bytes(), agent_path.read_bytes())
                with sqlite3.connect(tmp_path / "agent/supervisor/supervisor.sqlite") as conn:
                    launches = conn.execute("SELECT launch_json FROM launches").fetchall()
                from loom.queue._agent_process_supervisor import _launch_from_value
                from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace
                stage_images = []
                for (raw,) in launches:
                    retained_launch = _launch_from_value(json.loads(raw))
                    worker = _ResidentAssignmentWorkspace.read_request(retained_launch.workspace_root)
                    if worker.stage_name == "produce":
                        assert worker.submitted_execution is not None
                        stage_images.append(worker.submitted_execution.image.sha256)
                assert stage_images.count(first.image.sha256) == 2
                assert stage_images.count(second.image.sha256) == 1
                (tmp_path / "acceptance.json").write_text(json.dumps({
                    "complete": monotonic() - started, "stage_images": stage_images,
                    "retry_run_uri": completed.run_uri,
                }, indent=2))
                return
            request_a = request("aaa", first, wait=True)
            client.start_run(request_a)
            operation = prepared(client, "submit-aaa")
            assert operation.state == "applied", operation
            deadline = monotonic() + 60
            while not (barrier / "started-a").exists():
                assert not task.done(), task.result() if task.done() else None
                assert monotonic() < deadline, client.admission_for_queue_item("aaa")
                sleep(0.1)
            times["a_running"] = monotonic() - started
            before = identity()
            if scenario == "cancel_with_missing_image":
                (images / "aaa/image.sif").rename(images / "aaa/unavailable.sif")
            if scenario == "corrupt_new_image":
                corrupt = images / "aab/image.sif"
                corrupt.chmod(0o644)
                with corrupt.open("r+b") as stream:
                    stream.seek(-1, os.SEEK_END)
                    last = stream.read(1)
                    stream.seek(-1, os.SEEK_END)
                    stream.write(bytes([last[0] ^ 1]))
                corrupt.chmod(0o444)
            client.start_run(request("aab", second, wait=False))
            operation = prepared(client, "submit-aab")
            if scenario == "corrupt_new_image":
                assert operation.state == "failed" and operation.code == "preparation_child_failed"
                assert isinstance(operation.result, Mapping)
                child_id = operation.result["preparation_admission_id"]
                assert isinstance(child_id, str)
                child = client.admission(child_id).admission
                result = StageWorkerResult.from_dict(
                    LocalRunStore(service.daemon.run_store_root).read_stage_worker_result(
                        child.run_uri, "prepare", attempt=1))
                assert isinstance(result.failure, ExecutionFailure)
                failure = result.failure
                assert failure.details["process_created"] is False
                assert "image bytes" in failure.message
            else:
                assert operation.state == "applied", operation
                assert client.wait("aab", timeout_seconds=25).state.value == "SUCCEEDED"
                times["b_completed"] = monotonic() - started
                assert value(client, "aab")["value"] == 29
            assert not (barrier / "release-a").exists()
            if scenario == "cancel_with_missing_image":
                client.cancel("aaa")
                assert client.wait("aaa", timeout_seconds=25).state.value == "CANCELLED"
            else:
                (barrier / "release-a").touch()
                assert client.wait("aaa", timeout_seconds=25).state.value == "SUCCEEDED"
                assert value(client, "aaa")["value"] == 11
            times["a_completed"] = monotonic() - started
            assert client.start_run(request_a).operation_id == "submit-aaa"
            assert identity() == before
            assert protected == (coordinator_path.read_bytes(), agent_path.read_bytes())
            with sqlite3.connect(tmp_path / "agent" / "supervisor" / "supervisor.sqlite") as conn:
                count = conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0]
            assert count == (2 if scenario == "corrupt_new_image" else 4)
            if scenario == "lost_launch_reply":
                assert lost.is_set()
            (tmp_path / "acceptance.json").write_text(json.dumps(times, indent=2))
    finally:
        (barrier / "release-a").touch()
        # Finish the owned barrier probe before stopping its progress owner.
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            try:
                client.wait("aaa", timeout_seconds=25)
            except (CoordinatorClientError, TimeoutError):
                pass
        stop.set()
        try:
            task.result(timeout=30)
        finally:
            pool.shutdown(wait=True)
            cleanup = LocalDaemonAgentHttpClient(agent.client)
            if cleanup._supervisor is not None:
                from loom.queue._agent_process_supervisor import _launch_from_value
                with sqlite3.connect(tmp_path / "agent" / "supervisor" / "supervisor.sqlite") as conn:
                    launches = conn.execute("SELECT launch_json FROM launches").fetchall()
                for (raw,) in launches:
                    cleanup._supervisor.contain(_launch_from_value(json.loads(raw)))
                cleanup._supervisor.shutdown_for_test()
            cleanup.close()
            tls.stop()
            unix.stop()
            daemon.stop()
