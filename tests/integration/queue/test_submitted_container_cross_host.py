"""Opt-in two-host SIF execution with a real exclusive GPU when selected."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import sqlite3
import subprocess
import tempfile
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest

from loom.coordinator import CoordinatorClient
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.executors.containers import ContainerMount
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue._agent_process_supervisor import _launch_from_value
from loom.queue._submitted_container_policy import SubmittedContainerPolicy
from loom.queue.agent_session_transport import (
    AgentTlsServerConfig, LocalDaemonAgentHttpClient, LocalDaemonAgentHttpServer,
)
from loom.queue.deployment import (
    load_coordinator_service_config, load_outbound_agent_service_config,
    run_outbound_agent_service,
)
from loom.queue.preparation import PreparationSource, PrepareRunRequest
from loom.queue.run import RunRequest
from tests.integration.queue.test_preparation_operations import _service
from tests.integration.queue.test_submitted_container_physical import (
    PHYSICAL_CAPABILITIES, _image, _root,
)
from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("gpu", [False, True])
def test_prepare_here_execute_on_other_host(tmp_path, gpu):
    required = ("LOOM_SUBMITTED_IMAGES", "LOOM_SUBMITTED_SHARED",
                "LOOM_SUBMITTED_REMOTE", "LOOM_SUBMITTED_REMOTE_PYTHON")
    if not all(os.environ.get(key) for key in required):
        pytest.skip("cross-host SIF acceptance requires explicit images, shared root, host and Python")
    gpu_uuid = os.environ.get("LOOM_SUBMITTED_GPU")
    if gpu and not gpu_uuid:
        pytest.skip("select an idle remote GPU UUID with LOOM_SUBMITTED_GPU")
    images = Path(os.environ["LOOM_SUBMITTED_IMAGES"])
    remote = os.environ["LOOM_SUBMITTED_REMOTE"]
    python = os.environ["LOOM_SUBMITTED_REMOTE_PYTHON"]
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

    def remote_json(code):
        return json.loads(subprocess.check_output(
            [*ssh, remote, shlex.join([python, "-I", "-c", code])], text=True, timeout=30,
        ))

    host_info = remote_json(
        "import json,socket,shutil; s=socket.socket(); s.bind(('127.0.0.1',0)); "
        "print(json.dumps({'host':socket.gethostname(),'port':s.getsockname()[1],"
        "'runtime':shutil.which('apptainer') or shutil.which('singularity')}))"
    )
    assert host_info["host"] != socket.gethostname()
    shared = Path(tempfile.mkdtemp(prefix="cross-host-", dir=os.environ["LOOM_SUBMITTED_SHARED"]))
    resources = {"cpu_capacity": 2, "memory_capacity_bytes": 0,
                 "gpu": {"provider": "nvidia", "devices": gpu_uuid if gpu else "none"}}
    devices = remote_json(
        "import json; from loom.queue.deployment import _agent_resource_inventory; "
        f"inventory,_ = _agent_resource_inventory({resources!r}); "
        "print(json.dumps([device.descriptor.to_dict() for device in inventory.gpu_devices]))"
    )
    _service(tmp_path)
    barrier = shared / "barrier"
    barrier.mkdir()
    roots = {
        "images": _root(images),
        "control": _root(shared / "control", access="rw"),
        "snapshots": _root(shared / "snapshots", target="/loom/snapshots"),
        "reports": _root(shared / "reports", target="/loom/probe-reports",
                         access="rw", publication=True),
    }
    runtime = shutil.which("apptainer") or shutil.which("singularity")
    assert runtime and host_info["runtime"]
    policy = SubmittedContainerPolicy(
        "containers", {"command": runtime, "no_home": True, "nv": gpu}, roots, ("images",),
        preparation_shared_roots={"projects": shared / "snapshots"},
        environment={"PROBE_CONTROL": "/probe-control"},
        mounts=(ContainerMount(str(barrier), "/probe-control", "rw"),),
    )
    # Alternate real path spelling on the other host must not enter implementation identity.
    remote_roots = {name: {**root, "host_path": "/proc/self/root" + root["host_path"]}
                    for name, root in roots.items()}
    remote_policy = replace(
        policy, runtime_options={**policy.runtime_options, "command": host_info["runtime"]},
        shared_roots=remote_roots,
        preparation_shared_roots={"projects": Path("/proc/self/root" + str(shared / "snapshots"))},
        mounts=(ContainerMount("/proc/self/root" + str(barrier), "/probe-control", "rw"),),
    )
    assert remote_policy.capability == policy.capability
    coordinator_path = tmp_path / "coordinator.json"
    authored = json.loads(coordinator_path.read_text())
    authored.update(local_agent=None, shared_roots=roots, assignment_payload_root_id="control",
                    container_capabilities=[policy.capability.to_dict()])
    authored["preparation"]["source_roots"]["projects"]["shared_snapshot_root"] = str(shared / "snapshots")
    authored["preparation"]["profiles"] = {"containers": {
        "container_policy_id": "containers", "allowed_source_roots": ["projects"],
        "source_modes": ["shared"], "runtime_options": {"executor": "local"},
    }}
    authored["agent_policy"]["agents"] = [{
        "credential_id": credential, "principal_id": name, "agent_id": name,
        "pools": ["default"], "capabilities": list(capabilities), "gpu_devices": gpu_devices,
    } for credential, name, capabilities, gpu_devices in (
        ("agent", "prepare-host", PHYSICAL_CAPABILITIES, []),
        ("other", "execute-host", tuple(c for c in PHYSICAL_CAPABILITIES
                                       if c != "preparation-input-v2"), devices),
    )]
    coordinator_path.write_text(json.dumps(authored))
    service = load_coordinator_service_config(coordinator_path)
    credentials = mutual_tls_credentials(shared / "tls")
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    unix = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    unix.start()
    tls = LocalDaemonAgentHttpServer(daemon, AgentTlsServerConfig(
        "localhost", 0, credentials["server"].with_suffix(".crt"),
        credentials["server"].with_suffix(".key"), credentials["ca"].with_suffix(".crt"),
        {certificate_fingerprint(credentials[name].with_suffix(".crt")): name
         for name in ("agent", "other")},
    ))
    tls.start()

    def agent_config(path, selected_policy, credential, root, port, inventory, capabilities):
        path.write_text(json.dumps({
            "schema_version": 3, "kind": "loom.outbound-agent-service",
            "agent_root": str(root), "url": f"https://localhost:{port}",
            "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
            "certificate_path": str(credentials[credential].with_suffix(".crt")),
            "private_key_path": str(credentials[credential].with_suffix(".key")),
            "resident_profiles": [], "container_policies": [selected_policy.to_dict()],
            "reconnect_seconds": 0.1, "max_concurrent_assignments": 2,
            "registration": {"config_revision": "config", "inventory_revision": "inventory",
                             "availability_revision": "available", "pools": ["default"],
                             "capabilities": list(capabilities)},
            "resources": inventory,
        }))
        path.chmod(0o600)

    local_path, remote_path = shared / "prepare.json", shared / "execute.json"
    agent_config(local_path, policy, "agent", tmp_path / "agent", tls.port,
                 {**resources, "gpu": {"provider": "nvidia", "devices": "none"}},
                 PHYSICAL_CAPABILITIES)
    remote_agent_root = Path("/tmp") / ("loom-submitted-" + uuid4().hex)
    remote_capabilities = tuple(c for c in PHYSICAL_CAPABILITIES if c != "preparation-input-v2")
    agent_config(remote_path, remote_policy, "other", remote_agent_root, host_info["port"],
                 resources, remote_capabilities)
    agent = load_outbound_agent_service_config(local_path)
    LocalDaemonAgentHttpClient.initialize_agent_root(agent.client)
    protected = {p: p.read_bytes() for p in (coordinator_path, local_path, remote_path)}
    stop, remote_stop = Event(), shared / "stop-remote"
    pool = ThreadPoolExecutor(max_workers=1)
    task = pool.submit(run_outbound_agent_service, agent, stop=stop)
    helper = Path(__file__).resolve().parents[2] / "support/submitted_agent_runner.py"
    log = (shared / "remote.log").open("w")
    process = subprocess.Popen([
        *ssh, "-o", "ExitOnForwardFailure=yes", "-R",
        f"127.0.0.1:{host_info['port']}:localhost:{tls.port}", remote,
        shlex.join([python, "-I", str(helper), str(remote_path), str(remote_stop)]),
    ], stdout=log, stderr=log)
    started = monotonic()
    times = {}

    def request(name, wait):
        pipeline = json.loads((tmp_path / "projects/pipeline.yaml").read_text())
        stage = pipeline["pipeline"]["stages"][0]
        stage["factory"] = {"_target_": f"submitted_probe.{'Probe' if wait else 'NewStage'}"}
        stage["placement"] = {"target": "execute-host"}
        stage["config"] = {"barrier": wait, "gpu_compute": gpu}
        if gpu:
            pipeline["runtime"]["resource_policy"] = {"account_for": "all", "enforce": ["gpu"]}
            stage["resources"]["entries"]["gpu"] = {
                "kind": "gpu", "amount": 1, "unit": "count",
                "attributes": {"allocation_mode": "exclusive"},
            }
        (tmp_path / "projects" / f"{name}.yaml").write_text(json.dumps(pipeline))
        return RunRequest(PrepareRunRequest(
            f"submit-{name}", name, PreparationSource("shared", "projects", ".", (f"{name}.yaml",)),
            f"{name}.yaml", "containers", execution=_image(images, name),
        ), name)

    def wait_for(predicate, label):
        deadline = monotonic() + 90
        while monotonic() < deadline:
            assert process.poll() is None, (shared / "remote.log").read_text()
            if predicate():
                return
            sleep(0.1)
        raise AssertionError(f"{label} timed out; remote evidence: {shared}")

    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            first = request("aaa", True)
            client.start_run(first)
            wait_for(lambda: (barrier / "started-a").exists(), "first stage")
            times["a_running"] = monotonic() - started
            second = request("aab", False)
            client.start_run(second)
            wait_for(lambda: client.operation("submit-aab").state == "applied", "second preparation")
            if gpu:
                # Preparation completes while A owns the GPU; B must not start until release.
                count = remote_json(
                    "import json,sqlite3; "
                    f"c=sqlite3.connect({str(remote_agent_root / 'supervisor/supervisor.sqlite')!r}); "
                    "print(json.dumps(c.execute('SELECT COUNT(*) FROM launches').fetchone()[0]))"
                )
                assert count == 1
                assert client.admission_for_queue_item("aab").state.value != "SUCCEEDED"
                times["b_prepared_while_gpu_held"] = monotonic() - started
            else:
                assert client.wait("aab", timeout_seconds=45).state.value == "SUCCEEDED"
                times["b_completed_while_a_running"] = monotonic() - started
            (barrier / "release-a").touch()
            for name, expected in (("aaa", 11), ("aab", 29)):
                assert client.wait(name, timeout_seconds=45).state.value == "SUCCEEDED"
                admission = client.admission_for_queue_item(name)
                store = LocalRunStore(service.daemon.run_store_root)
                result = StageWorkerResult.from_dict(
                    store.read_stage_worker_result(admission.run_uri, "produce", attempt=1))
                value = LocalArtifactStore(store.local_artifact_root(admission.run_uri)).load(result.outputs["data"])
                assert isinstance(value, dict)
                assert value["value"] == expected
                assert value["prepared_host"] == socket.gethostname()
                assert value["execution_host"] == host_info["host"]
                if gpu:
                    assert value["gpu"] == {"device_count": 1, "device_uuid": gpu_uuid,
                                             "values": [0, 1, 4, 9]}
            assert client.start_run(first).operation_id == "submit-aaa"
            times["complete"] = monotonic() - started
            with sqlite3.connect(service.daemon.control_database) as conn:
                gate = json.loads(conn.execute(
                    "SELECT value FROM daemon_metadata WHERE key='maintenance-gate'").fetchone()[0])
            assert gate["state"] == "open" and gate["revision"] == 0
            assert all(path.read_bytes() == contents for path, contents in protected.items())
            (shared / "acceptance.json").write_text(json.dumps({
                "times": times, "prepare_host": socket.gethostname(), "execute_host": host_info["host"],
                "gpu_uuid": gpu_uuid if gpu else None, "remote_agent_root": str(remote_agent_root),
                "config_sha256": {str(p): hashlib.sha256(v).hexdigest() for p, v in protected.items()},
            }, indent=2))
    finally:
        (barrier / "release-a").touch()
        remote_stop.touch()
        stop.set()
        try:
            task.result(timeout=30)
            assert process.wait(timeout=45) == 0, (shared / "remote.log").read_text()
        finally:
            pool.shutdown(wait=True)
            log.close()
            cleanup = LocalDaemonAgentHttpClient(agent.client)
            if cleanup._supervisor is not None:
                with sqlite3.connect(tmp_path / "agent/supervisor/supervisor.sqlite") as conn:
                    for (raw,) in conn.execute("SELECT launch_json FROM launches").fetchall():
                        cleanup._supervisor.contain(_launch_from_value(json.loads(raw)))
                cleanup._supervisor.shutdown_for_test()
            cleanup.close()
            tls.stop()
            unix.stop()
            daemon.stop()
