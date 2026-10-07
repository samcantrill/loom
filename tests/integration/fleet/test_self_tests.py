"""Finite infrastructure checks through disposable native preparation/execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest

from loom.fleet.configuration import Host, Inventory
from loom.fleet.probes import ProbeStage, gpu_probe, verify_storage, STORAGE_BYTES
from loom.fleet.self_tests import self_test, verify_check

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.fixture
def fleet(tmp_path):
    from loom.preparation import CoordinatorPreparation
    from loom.queue import LocalDaemon, LocalDaemonSocketServer
    from loom.queue.agent_sessions import AgentRegistration
    from loom.queue.agent_session_transport import (
        AgentTlsClientConfig,
        AgentTlsServerConfig,
        LocalDaemonAgentHttpClient,
        LocalDaemonAgentHttpServer,
    )
    from loom.queue.deployment import load_coordinator_service_config
    from loom.queue._remote_stage_execution import (
        ResidentExecutionProfile,
        ResidentProfileDescriptor,
    )
    from loom.queue.resident_readiness import (
        qualified_resident_profile,
        ResidentReadinessRequirements,
    )
    from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint
    from tests.integration.queue.test_preparation_operations import _service

    _service(tmp_path)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "challenge").write_bytes(b"test-output")
    roots = {
        "outputs": {
            "host_path": str(outputs),
            "container_path": "/loom/outputs",
            "access": "rw",
            "challenge": {
                "path": "challenge",
                "sha256": hashlib.sha256(b"test-output").hexdigest(),
            },
            "publication": {
                "max_members": 1024,
                "max_payload_bytes": 128 * 1024 * 1024,
                "max_manifest_bytes": 1024 * 1024,
            },
        }
    }
    profile = qualified_resident_profile(
        ResidentExecutionProfile(
            ResidentProfileDescriptor(
                "probe-profile", "v1", "project", "environment", "executor"
            ),
            Path(__file__).resolve().parents[3],
            Path(sys.executable),
            readiness_requirements=ResidentReadinessRequirements(
                imports=("loom", "loom.preparation", "weave")
            ),
            shared_roots=roots,
            preparation_shared_roots={"projects": tmp_path / "snapshots"},
        )
    )
    capabilities = (
        "python",
        "resident-execution-v1",
        "regular-file-relay-v1",
        "shared-execution-v1",
        "shared-assignment-reference-v1",
        "preparation-input-v2",
    )
    from loom.queue._remote_stage_execution import (
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    from loom.queue.shared_execution import SHARED_EXECUTION_CAPABILITY

    capabilities = (
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
        SHARED_EXECUTION_CAPABILITY,
        "shared-assignment-reference-v1",
        "preparation-input-v2",
    )
    config_path = tmp_path / "coordinator.json"
    authored = json.loads(config_path.read_text())
    authored.update(
        local_agent=None,
        shared_roots=roots,
        assignment_payload_root_id="outputs",
        remote_profiles=[profile.descriptor.to_dict()],
    )
    authored["preparation"]["profiles"]["existing-project"].update(
        configuration_policy="shared",
        shared_locations=[],
        resident_profile_id="probe-profile",
    )
    authored["agent_policy"]["agents"] = [
        {
            "credential_id": "agent",
            "principal_id": "worker",
            "agent_id": "worker",
            "pools": ["default"],
            "capabilities": list(capabilities),
            "gpu_devices": [],
        }
    ]
    authored["agent_policy"]["principals"] = [
        {
            "credential_id": "query",
            "principal_id": "caller",
            "role": "client",
            "actions": [],
            "agent_ids": [],
            "pools": [],
        },
        {
            "credential_id": "other",
            "principal_id": "operator",
            "role": "operator",
            "actions": ["drain", "maintenance"],
            "agent_ids": ["worker"],
            "pools": ["default"],
        },
    ]
    authored["agent_policy"]["local_owner"] = {
        "actions": ["drain", "maintenance"],
        "agent_ids": ["worker"],
        "pools": ["default"],
    }
    config_path.write_text(json.dumps(authored))
    service = load_coordinator_service_config(config_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    unix = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    unix.start()
    credentials = mutual_tls_credentials(tmp_path / "tls")
    from loom.diagnostics.run_inspection import RunInspectionProjection
    from loom.pipeline.stores import LocalRunStore

    inspection = RunInspectionProjection(
        run_store=LocalRunStore(service.daemon.run_store_root), daemon=daemon
    )
    server = LocalDaemonAgentHttpServer(
        daemon,
        AgentTlsServerConfig(
            "localhost",
            0,
            credentials["server"].with_suffix(".crt"),
            credentials["server"].with_suffix(".key"),
            credentials["ca"].with_suffix(".crt"),
            {
                certificate_fingerprint(credentials[name].with_suffix(".crt")): name
                for name in ("agent", "query", "other")
            },
        ),
        inspect_run=lambda uri: inspection.inspect(uri).to_dict(),
    )
    server.start()
    agent_config = AgentTlsClientConfig(
        f"https://localhost:{server.port}",
        credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".key"),
        tmp_path / "remote",
        (profile,),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(agent_config)
    remote = LocalDaemonAgentHttpClient(agent_config)
    hello = remote.handshake()
    remote.register(
        AgentRegistration(
            "register",
            str(hello["coordinator_id"]),
            str(hello["coordinator_epoch"]),
            remote.agent_root_id,
            "config-1",
            "inventory-1",
            "availability-1",
            ("default",),
            capabilities,
        )
    )
    remote.refresh_resource_offer()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    connection = private / "connection.json"
    connection.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.coordinator-client",
                "expected_coordinator_id": hello["coordinator_id"],
                "transport": {
                    "kind": "https",
                    "url": f"https://localhost:{server.port}",
                    "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                    "certificate_path": str(credentials["query"].with_suffix(".crt")),
                    "private_key_path": str(credentials["query"].with_suffix(".key")),
                },
            }
        )
    )
    connection.chmod(0o600)
    operator_connection = private / "operator.json"
    operator_value = json.loads(connection.read_text())
    operator_value["transport"].update(
        certificate_path=str(credentials["other"].with_suffix(".crt")),
        private_key_path=str(credentials["other"].with_suffix(".key")),
    )
    operator_connection.write_text(json.dumps(operator_value))
    operator_connection.chmod(0o600)
    deployment = private / "deployment.json"
    deployment.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.deployment",
                "connection": str(connection),
                "preparation": {
                    "source": {
                        "mode": "shared",
                        "root": "projects",
                        "path": ".",
                        "include": ["pipeline.yaml"],
                    },
                    "profile": "existing-project",
                },
            }
        )
    )
    deployment.chmod(0o600)
    inventory = Inventory(
        private / "fleet.yaml",
        "test",
        private / "unused-release",
        "tmux",
        (
            Host("coordinator", "fixture", config_path),
            Host("worker", "fixture", tmp_path / "agent.json"),
        ),
    )
    stop = Event()

    def work():
        while not stop.is_set():
            session = remote.active_session()
            assert session is not None
            remote.execute_one(
                session.session_id,
                session.availability_revision,
                sequence=remote.next_poll_sequence(session.session_id),
                wait_timeout_ms=200,
            )
            remote.refresh_resource_offer()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(work)
        try:
            yield inventory, deployment, daemon, remote
        finally:
            stop.set()
            try:
                future.result(timeout=30)
            finally:
                if remote._supervisor is not None:
                    remote._supervisor.shutdown_for_test()
                remote.close()
                server.stop()
                unix.stop()
                daemon.stop()


def finish(inventory, operation):
    result = {}
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        result = self_test(inventory, operation_id=operation, timeout_seconds=180)
        if result["outcome"] != "waiting":
            return result
        time.sleep(0.05)
    pytest.fail(json.dumps(result, default=str))


def retained_checks(tmp_path, operation):
    import loom.fleet.self_tests as checks_module
    from loom.coordinator import RunRequest
    from loom.queue.preparation import PreparationSource, PrepareRunRequest

    inventory = Inventory(tmp_path / "fleet.yaml", "test", tmp_path, "tmux", ())
    directory = tmp_path / "checks" / operation
    directory.mkdir(parents=True, mode=0o700)
    requests = {}
    for check in ("cpu", "storage", "gpu"):
        identity = operation + "-" + check
        requests[check] = RunRequest(
            PrepareRunRequest(
                identity,
                identity,
                PreparationSource("shared", "projects", ".", ("pipeline.yaml",)),
                "pipeline.yaml",
                "existing-project",
            ),
            identity,
        ).to_dict()
    intent = {
        "schema_version": 1,
        "operation_id": operation,
        "retry_of": None,
        "coordinator_id": "coordinator-test",
        "connection": str(tmp_path / "connection.json"),
        "operator_connection": str(tmp_path / "operator.json"),
        "agent_id": "worker",
        "session_id": "session-test",
        "agent_root_id": "root-test",
        "profile": {},
        "requests": requests,
    }
    checks_module._publish(directory / "intent.json", intent)
    return inventory, directory, intent, requests


def test_busy_gpu_deadline_preserves_cpu_storage_progress(tmp_path, monkeypatch):
    from contextlib import nullcontext

    import loom.fleet.self_tests as checks_module

    operation = "check-busy-gpu"
    inventory, directory, intent, requests = retained_checks(tmp_path, operation)
    for check, request in requests.items():
        checks_module._publish(
            directory / (check + ".dispatch.json"),
            {"operation_id": request["preparation"]["operation_id"]},
        )
    retained = (directory / "intent.json").read_bytes()
    assert list(json.loads(retained)["requests"]) == ["cpu", "gpu", "storage"]
    for client in (
        checks_module.CoordinatorClient,
        checks_module.CoordinatorOperatorClient,
    ):
        monkeypatch.setattr(client, "from_connection_file", lambda *a, **kw: nullcontext())

    clock = [100.0]
    observed = []
    monkeypatch.setattr(checks_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def observe(client, operator, path, retained_intent, check, deadline):
        assert deadline == 110.0
        assert retained_intent["requests"] == requests
        observed.append(check)
        if check == "gpu":
            # Native capacity waiting consumes the remaining shared deadline.
            clock[0] = deadline
            return {"outcome": "waiting", "code": "waiting_for_capacity"}
        return {"outcome": "passed"}

    monkeypatch.setattr(checks_module, "_observe_check", observe)
    result = self_test(inventory, operation_id=operation, timeout_seconds=10)
    assert result["checks"]["storage"]["outcome"] == "passed"
    assert result["checks"]["cpu"]["outcome"] == "passed"
    assert observed == ["cpu", "storage", "gpu"]
    assert result["outcome"] == "waiting"
    assert result["checks"]["gpu"]["code"] == "waiting_for_capacity"
    assert {check: row["operation_id"] for check, row in result["checks"].items()} == {
        check: operation + "-" + check for check in requests
    }
    assert (directory / "intent.json").read_bytes() == retained


def test_storage_deadline_does_not_prevent_gpu_dispatch(tmp_path, monkeypatch):
    from contextlib import nullcontext

    import loom.fleet.self_tests as checks_module

    operation = "check-storage-deadline"
    inventory, directory, intent, requests = retained_checks(tmp_path, operation)
    retained = (directory / "intent.json").read_bytes()
    accepted = []
    for factory in (
        checks_module.CoordinatorClient,
        checks_module.CoordinatorOperatorClient,
    ):
        monkeypatch.setattr(
            factory, "from_connection_file", lambda *args, **kw: nullcontext(client)
        )
    clock = [100.0]
    slow_storage = [True]
    monkeypatch.setattr(checks_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    current = ["cpu"]

    def observe_run(identity, **kwargs):
        current[0] = identity.rsplit("-", 1)[-1]
        return SimpleNamespace(
            operation=None,
            admission=SimpleNamespace(
                state=SimpleNamespace(value="SUCCEEDED"),
                admission_id="admission-" + current[0],
                run_uri="file:///run/" + current[0],
            ),
            to_dict=lambda: {},
        )

    def fetch_artifacts(items, destination, *, deadline):
        if current[0] == "storage" and slow_storage[0]:
            clock[0] = deadline
            return {"items": [{"outcome": "failed"}]}
        path = Path(destination) / "report.json"
        path.write_text(json.dumps({"check": current[0]}))
        return {"items": [{"outcome": "available", "primary_path": str(path)}]}

    assignment = {"stage_name": "probe", "terminal_acknowledged": True}
    client = SimpleNamespace(
        start_run=lambda request: accepted.append(request.preparation.operation_id),
        observe_run=observe_run,
        admission=lambda identity: SimpleNamespace(
            owners={"assignment": {"assignments": [{"assignment_id": identity}]}}
        ),
        observe_assignment=lambda identity: SimpleNamespace(
            availability="available", value=assignment, to_dict=lambda: {"value": assignment}
        ),
        observe_agent=lambda identity: SimpleNamespace(value={}, to_dict=lambda: {}),
        select_outputs=lambda selection: SimpleNamespace(
            items=[{"artifact": {"metadata": {"loom.shared_publication": {}}}}],
            next_cursor=None,
        ),
        fetch_artifacts=fetch_artifacts,
    )
    monkeypatch.setattr(checks_module, "verify_check", lambda *a, **kw: {"outcome": "passed"})
    monkeypatch.setattr(checks_module, "verify_storage", lambda path: {})
    first = self_test(inventory, operation_id=operation, timeout_seconds=10)
    assert first["outcome"] == "waiting"
    assert first["checks"]["gpu"]["code"] == "deadline_exceeded"
    assert accepted == [operation + "-" + name for name in ("cpu", "storage", "gpu")]
    for check, request in requests.items():
        assert json.loads((directory / (check + ".dispatch.json")).read_text()) == {
            "operation_id": request["preparation"]["operation_id"]
        }
    slow_storage[0] = False
    continued = self_test(inventory, operation_id=operation, timeout_seconds=10)
    assert continued["outcome"] == "passed"
    assert accepted == [operation + "-" + name for name in ("cpu", "storage", "gpu")]
    assert {k: v["operation_id"] for k, v in continued["checks"].items()} == {
        k: v["operation_id"] for k, v in first["checks"].items()
    }
    assert (directory / "intent.json").read_bytes() == retained


def test_native_cpu_storage_and_dropped_response_exact_continuation(fleet, monkeypatch):
    inventory, deployment, daemon, _ = fleet
    import loom.queue.agent_session_transport as transport

    original = transport._Handler._reply
    dropped = []

    def reply(handler, status, value):
        if (
            isinstance(value.get("result"), dict)
            and value["result"].get("kind") == "run"
            and not dropped
        ):
            dropped.append(True)
            handler.close_connection = True
            handler.connection.shutdown(socket.SHUT_RDWR)
            return
        original(handler, status, value)

    monkeypatch.setattr(transport._Handler, "_reply", reply)
    result = self_test(
        inventory,
        deployment=deployment,
        operator_connection=inventory.path.parent / "operator.json",
        config="pipeline.yaml",
        checks=("cpu", "storage"),
        timeout_seconds=45,
    )
    assert dropped
    result = finish(inventory, result["operation_id"])
    assert result["outcome"] == "passed", result
    assert result["checks"]["cpu"]["report"]["result"] == 49995000
    assert result["checks"]["storage"]["storage"]["bytes"] == STORAGE_BYTES
    for kind in ("cpu", "storage"):
        assignment = result["checks"][kind]["assignment"]["value"]
        assert assignment["released"] is True
        assert assignment["release_proof"]["claim_id"] == assignment["claim_id"]
        assert assignment["actual_claims"]["actual_gpu_uuids"] == []
    before = [
        result["checks"][k]["assignment"]["value"]["assignment_id"]
        for k in ("cpu", "storage")
    ]
    resumed = finish(inventory, result["operation_id"])
    assert [
        resumed["checks"][k]["assignment"]["value"]["assignment_id"]
        for k in ("cpu", "storage")
    ] == before
    assert (
        len(
            {
                v["operation_id"]
                for v in resumed["checks"].values()
                if "operation_id" in v
            }
        )
        == 2
    )

    with sqlite3.connect(daemon.config.control_database) as connection:
        for check in ("cpu", "storage"):
            uri = resumed["checks"][check]["native"]["admission"]["run_uri"]
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM remote_assignments WHERE run_uri = ? AND stage_name = 'probe'",
                    (uri,),
                ).fetchone()[0]
                == 1
            )


def test_interrupted_dispatch_retains_replay_refusal_after_admission_reopens(
    fleet, monkeypatch
):
    from loom.coordinator import CoordinatorClient
    from tests.integration.queue.test_maintenance_admission import change

    inventory, deployment, daemon, _ = fleet
    original = CoordinatorClient.start_run

    def interrupt_before_acceptance(client, request):
        raise KeyboardInterrupt

    monkeypatch.setattr(CoordinatorClient, "start_run", interrupt_before_acceptance)
    with pytest.raises(KeyboardInterrupt):
        self_test(
            inventory,
            deployment=deployment,
            operator_connection=inventory.path.parent / "operator.json",
            config="pipeline.yaml",
            checks=("cpu",),
        )
    monkeypatch.setattr(CoordinatorClient, "start_run", original)
    directory = next((inventory.path.parent / "checks").iterdir())
    intent = (directory / "intent.json").read_bytes()
    identity = json.loads(intent)["requests"]["cpu"]["preparation"]["operation_id"]
    assert json.loads((directory / "cpu.dispatch.json").read_text()) == {
        "operation_id": identity
    }

    change(daemon, "close")
    refused = self_test(inventory, operation_id=directory.name)
    assert refused["outcome"] == "failed", refused
    assert refused["checks"]["cpu"]["code"] == "maintenance_in_progress"
    assert refused["checks"]["cpu"]["native_error"]["mutation_outcome"] == "not_applied"
    assert json.loads((directory / "cpu.rejected.json").read_text()) == refused[
        "checks"
    ]["cpu"]["native_error"]

    change(daemon, "open")
    continued = self_test(inventory, operation_id=directory.name)
    assert continued["checks"]["cpu"] == refused["checks"]["cpu"]
    assert (directory / "intent.json").read_bytes() == intent
    with sqlite3.connect(daemon.config.control_database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM preparation_operations WHERE operation_id = ?",
            (identity,),
        ).fetchone()[0] == 0


def test_failed_native_check_is_observed_without_retry(fleet):
    inventory, deployment, _, _ = fleet
    first = self_test(
        inventory,
        deployment=deployment,
        operator_connection=inventory.path.parent / "operator.json",
        config="missing.yaml",
        checks=("cpu",),
    )
    failed = finish(inventory, first["operation_id"])
    assert failed["outcome"] == "failed"
    again = finish(inventory, first["operation_id"])
    assert (
        again["checks"]["cpu"]["operation_id"]
        == failed["checks"]["cpu"]["operation_id"]
    )
    assert (
        again["checks"]["cpu"]["native"]["operation"]
        == failed["checks"]["cpu"]["native"]["operation"]
    )


@pytest.mark.parametrize("fault", ["correct", "wrong", "truncated"])
def test_storage_reads_complete_independent_bytes(tmp_path, fault):
    class Context:
        stage_config = {"check": "storage"}
        run_uri = "test"
        stage_name = "probe"

        def local_output_path(self, *args, **kwargs):
            return tmp_path / "report.json"

        def save_artifact(self, *args, **kwargs):
            return args[1]

    ProbeStage().run(cast(Any, Context()), {})
    path = tmp_path / "values.bin"
    if fault == "wrong":
        with path.open("r+b") as stream:
            stream.seek(STORAGE_BYTES - 1)
            stream.write(b"\xff")
    elif fault == "truncated":
        with path.open("r+b") as stream:
            stream.truncate(STORAGE_BYTES - 1)
    if fault == "correct":
        assert verify_storage(path)["bytes"] == STORAGE_BYTES
    else:
        with pytest.raises(ValueError, match="size/hash"):
            verify_storage(path)


def evidence():
    profile = {"profile_id": "selected"}
    uuid = "GPU-12345678-1234-1234-1234-123456789abc"
    report = {
        "check": "gpu",
        "synthetic": True,
        "outcome": "passed",
        "run_uri": "loom-agent:a",
        "stage_name": "probe",
        "result": [[19.0, 22.0], [43.0, 50.0]],
        "device_uuid": uuid,
        "device_count": 1,
    }
    assignment = {
        "assignment_id": "a",
        "agent_id": "worker",
        "session_id": "s",
        "run_uri": "r",
        "stage_name": "probe",
        "profile": profile,
        "claim_id": "c",
        "released": True,
        "terminal_acknowledged": True,
        "actual_claims": {
            "availability": "available",
            "source": "native_supervisor_launch",
            "assignment_id": "a",
            "actual_gpu_uuids": [uuid],
            "gpu_capacity_keys": ["worker:gpu0"],
        },
        "release_proof": {"assignment_id": "a", "claim_id": "c", "session_id": "s"},
    }
    agent = {
        "session_id": "s",
        "connected": True,
        "offer": {
            "freshness": "current",
            "reflected_claim_ids": [],
            "gpu_atoms": [{"local_capacity_key": "gpu0"}],
        },
        "resource_status": [{"resource_kind": "gpu", "available": True}],
    }
    return report, assignment, agent, profile


@pytest.mark.parametrize(
    "fault,outcome",
    [
        ("none", "passed"),
        ("uuid", "failed"),
        ("numerics", "failed"),
        ("occupancy", "waiting"),
        ("retained", "waiting"),
        ("stale", "waiting"),
        ("torch", "unsupported"),
    ],
)
def test_finite_gpu_result_release_matrix(fault, outcome):
    report, assignment, agent, profile = evidence()
    if fault == "uuid":
        assignment["actual_claims"]["actual_gpu_uuids"] = ["GPU-other"]
    if fault == "numerics":
        report["result"][1][1] = 49
    if fault == "occupancy":
        agent["offer"]["gpu_atoms"] = []
    if fault == "retained":
        assignment["released"] = False
    if fault == "stale":
        agent["offer"]["freshness"] = "retained"
    if fault == "torch":
        report.update(outcome="unsupported", reason="torch_unavailable")
    assert (
        verify_check(
            "gpu",
            report,
            assignment,
            agent,
            agent_id="worker",
            session_id="s",
            profile=profile,
            run_uri="r",
        )["outcome"]
        == outcome
    )


def test_gpu_probe_optional_import_and_actual_uuid_compute(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    assert gpu_probe()["code"] == "unsupported_check"
    uuid = "12345678-1234-1234-1234-123456789abc"
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-" + uuid)
    synchronized = []

    class Matrix:
        def __matmul__(self, other):
            return self

        def cpu(self):
            assert synchronized
            return self

        def tolist(self):
            return [[19.0, 22.0], [43.0, 50.0]]

    torch = SimpleNamespace(
        __version__="fixture",
        float32="float32",
        tensor=lambda *a, **kw: Matrix(),
        cuda=SimpleNamespace(
            device_count=lambda: 1,
            get_device_properties=lambda _: SimpleNamespace(uuid=uuid),
            synchronize=lambda _: synchronized.append(True),
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    assert gpu_probe()["device_uuid"] == "GPU-" + uuid
    torch.cuda.get_device_properties = lambda _: SimpleNamespace(
        uuid="22345678-1234-1234-1234-123456789abc"
    )
    with pytest.raises(ValueError, match="UUID/numerical"):
        gpu_probe()


def test_installed_acceptance_requires_both_explicit_opt_ins(monkeypatch):
    from tests.fleet_acceptance.test_self_tests import acceptance_selection

    monkeypatch.setenv("LOOM_RUN_FLEET_ACCEPTANCE", "1")
    monkeypatch.delenv("LOOM_FLEET_ACCEPTANCE_CONFIG", raising=False)
    with pytest.raises(pytest.fail.Exception, match="no fleet discovery"):
        acceptance_selection()
