"""Configured cold run, binding recovery and serialized service retirement."""

import json
from pathlib import Path
import shutil
import sqlite3
import time

import pytest

import loom
from loom.coordinator import RunRequest
from loom.deployment import _bind, load_deployment
from loom.queue.errors import QueueConflictError
from tests.integration.queue.test_preparation_operations import _request, _service

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _cleanup_state(outcome, role):
    details = outcome.cleanup[role]
    assert isinstance(details, dict)
    return details["state"]


def _selection(tmp_path: Path, *, lifetime: str = "run") -> Path:
    _service(tmp_path)
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.deployment",
                "coordinator": {
                    "service_config": "coordinator.json",
                    "lifetime": lifetime,
                },
                "binding_path": "binding.json",
                "preparation": {
                    "source": _request().source.to_dict(),
                    "profile": _request().preparation_profile,
                },
                "startup_seconds": 20,
            }
        )
    )
    path.chmod(0o600)
    return path


def test_cold_run_reopen_and_actual_owned_exit(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    request = RunRequest(_request(), "target-queue")
    result = loom.run(request, deployment=selection)
    assert result.observation.admission is not None
    assert result.observation.admission.state.value == "SUCCEEDED"
    assert _cleanup_state(result, "coordinator") == "stopped"
    identity = json.loads((tmp_path / "binding.json").read_text())
    again = loom.run(request, deployment=selection)
    assert again.observation.admission is not None
    assert (
        again.observation.admission.admission_id
        == result.observation.admission.admission_id
    )
    assert _cleanup_state(again, "coordinator") == "stopped"
    assert json.loads((tmp_path / "binding.json").read_text()) == identity


def test_bound_root_loss_never_initializes_replacement(tmp_path: Path) -> None:
    selection = load_deployment(_selection(tmp_path))
    _bind(selection, "first", time.monotonic() + 20)
    shutil.rmtree(tmp_path / "deployment")
    with pytest.raises(QueueConflictError, match="missing"):
        _bind(selection, "second", time.monotonic() + 20)
    assert not (tmp_path / "deployment").exists()


def test_interrupted_binding_completes_same_published_identity(tmp_path: Path) -> None:
    selection = load_deployment(_selection(tmp_path))
    first, _ = _bind(selection, "first", time.monotonic() + 20)
    path = tmp_path / "binding.json"
    saved = json.loads(path.read_text())
    expected = saved["roles"]["coordinator"]["ids"]
    saved["roles"]["coordinator"]["ids"] = None
    path.write_text(json.dumps(saved))
    replayed, _ = _bind(selection, "second", time.monotonic() + 20)
    assert replayed["coordinator"]["ids"] == expected


def _mixed_selection(
    tmp_path: Path, coordinator_lifetime: str, agent_lifetime: str
) -> Path:
    import socket
    from tests.support.mutual_tls import mutual_tls_credentials, certificate_fingerprint
    from loom.queue.deployment import load_coordinator_service_config
    from loom.queue._remote_stage_execution import (
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
    )
    from loom.queue.preparation import PREPARATION_INPUT_CAPABILITY

    path = _selection(tmp_path, lifetime=coordinator_lifetime)
    service = load_coordinator_service_config(tmp_path / "coordinator.json")
    credentials = mutual_tls_credentials(tmp_path / "tls")
    with socket.socket() as endpoint:
        endpoint.bind(("localhost", 0))
        port = endpoint.getsockname()[1]
    capabilities = [
        "python",
        REMOTE_EXECUTION_CAPABILITY,
        REGULAR_FILE_RELAY_CAPABILITY,
        PREPARATION_INPUT_CAPABILITY,
    ]
    coordinator = json.loads((tmp_path / "coordinator.json").read_text())
    coordinator["local_agent"] = None
    assert service.local_agent is not None
    coordinator["remote_profiles"] = [service.local_agent.profile.descriptor.to_dict()]
    coordinator["agent_policy"]["agents"] = [
        {
            "credential_id": "agent-credential",
            "principal_id": "agent-principal",
            "agent_id": "worker",
            "pools": ["default"],
            "capabilities": capabilities,
            "gpu_devices": [],
        }
    ]
    coordinator["agent_server"] = {
        "host": "localhost",
        "port": port,
        "certificate_path": str(credentials["server"].with_suffix(".crt")),
        "private_key_path": str(credentials["server"].with_suffix(".key")),
        "client_ca_path": str(credentials["ca"].with_suffix(".crt")),
        "credential_fingerprints": {
            certificate_fingerprint(
                credentials["agent"].with_suffix(".crt")
            ): "agent-credential"
        },
    }
    (tmp_path / "coordinator.json").write_text(json.dumps(coordinator))
    agent = json.loads((tmp_path / "agent.json").read_text())
    agent.update(
        {
            "kind": "loom.outbound-agent-service",
            "agent_root": "outbound",
            "url": f"https://localhost:{port}",
            "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
            "certificate_path": str(credentials["agent"].with_suffix(".crt")),
            "private_key_path": str(credentials["agent"].with_suffix(".key")),
            "registration": {
                "config_revision": "v1",
                "inventory_revision": "v1",
                "availability_revision": "v1",
                "pools": ["default"],
                "capabilities": capabilities,
            },
            "reconnect_seconds": 0.1,
        }
    )
    (tmp_path / "agent.json").write_text(json.dumps(agent))
    selection = json.loads(path.read_text())
    selection["agent"] = {"service_config": "agent.json", "lifetime": agent_lifetime}
    path.write_text(json.dumps(selection))
    return path


def _stop_fixture_process(root: Path) -> None:
    import os
    import signal

    if not (root / "control.sqlite").exists():
        return
    with sqlite3.connect(root / "control.sqlite") as conn:
        row = conn.execute(
            "SELECT value FROM root_metadata WHERE key='service_process'"
        ).fetchone()
    if row is None:
        return
    state = json.loads(row[0])
    try:
        process = Path(f"/proc/{state['pid']}/stat").read_text().split()
        if process[21] == state["started"] and process[2] != "Z":
            os.kill(state["pid"], signal.SIGINT)
    except FileNotFoundError:
        return
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            process = Path(f"/proc/{state['pid']}/stat").read_text().split()
            if process[21] != state["started"] or process[2] == "Z":
                return
        except FileNotFoundError:
            return
        time.sleep(0.05)
    raise AssertionError("fixture-owned role did not stop")


@pytest.mark.parametrize(
    "coordinator_lifetime,agent_lifetime",
    [("persistent", "run"), ("run", "persistent"), ("run", "run")],
)
def test_independent_mixed_lifetimes(
    tmp_path: Path, coordinator_lifetime: str, agent_lifetime: str
) -> None:
    path = _mixed_selection(tmp_path, coordinator_lifetime, agent_lifetime)
    try:
        outcome = loom.run(
            RunRequest(_request(), "mixed"), deployment=path, timeout_seconds=40
        )
        assert outcome.observation.admission is not None
        assert outcome.observation.admission.state.value == "SUCCEEDED"
        assert _cleanup_state(outcome, "coordinator") == (
            "stopped" if coordinator_lifetime == "run" else "persistent/borrowed"
        )
        assert _cleanup_state(outcome, "agent") == (
            "stopped" if agent_lifetime == "run" else "persistent/borrowed"
        )
    finally:
        _stop_fixture_process(tmp_path / "outbound")
        _stop_fixture_process(tmp_path / "deployment/coordinator")
        from loom.queue._agent_process_supervisor import (
            AgentProcessSupervisorClient,
            _endpoint_for_root,
            _service_configuration,
        )

        root = tmp_path / "outbound"
        if _endpoint_for_root(root / "supervisor").exists():
            supervisor = AgentProcessSupervisorClient(
                root, _service_configuration(root / "supervisor")
            )
            supervisor.shutdown_for_test()
            assert not Path(f"/proc/{supervisor.service_process_id}").exists()


def test_waiting_preparation_survives_detach_without_local_worker(
    tmp_path: Path,
) -> None:
    from loom.coordinator import CoordinatorClient
    from loom.queue.deployment import load_coordinator_service_config

    path = _selection(tmp_path)
    service = load_coordinator_service_config(tmp_path / "coordinator.json")
    config = json.loads((tmp_path / "coordinator.json").read_text())
    config["local_agent"] = None
    assert service.local_agent is not None
    config["remote_profiles"] = [service.local_agent.profile.descriptor.to_dict()]
    (tmp_path / "coordinator.json").write_text(json.dumps(config))
    try:
        outcome = loom.run(
            RunRequest(_request(), "waiting"), deployment=path, wait=False
        )
        assert outcome.observation.operation is not None
        assert outcome.observation.operation.operation_id == _request().operation_id
        assert outcome.observation.operation is not None
        assert outcome.observation.operation.kind == "run"
        client = CoordinatorClient.from_unix_socket(
            tmp_path / "deployment/coordinator/daemon.sock",
            expected_coordinator_id=outcome.observation.connection.coordinator_id,
        )
        # The selected owner stays available with accepted preparation but no
        # eligible worker; detach does not create or install one.
        assert client.operation(_request().operation_id).state == "pending"
        state = client._native_call("service_lifetime", {})
        assert state["retained"] is True
        with sqlite3.connect(tmp_path / "deployment/coordinator/control.sqlite") as conn:
            assert conn.execute("SELECT COUNT(*) FROM daemon_metadata WHERE key LIKE 'startup-attachment:%'").fetchone()[0] == 0
        assert not (tmp_path / "deployment/agent").exists()
        cancel = client.cancel_run_operation(_request().operation_id)
        assert (
            client.wait_operation(
                cancel.operation_id, timeout_seconds=20
            ).operation.state
            == "applied"
        )
    finally:
        _stop_fixture_process(tmp_path / "deployment/coordinator")


def test_unaccepted_startup_expiry_and_acceptance_retirement_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loom.queue import LocalDaemon, LocalDaemonPrincipal, LocalDaemonRole
    from loom.preparation import CoordinatorPreparation
    from loom.queue._service_lifetime import ServiceRetiring

    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        from types import SimpleNamespace
        from loom.queue import _service_lifetime

        now = [time.time()]
        monkeypatch.setattr(
            _service_lifetime, "time", SimpleNamespace(time=lambda: now[0])
        )
        daemon._lifetime.attach("abandoned", now[0] + 1)
        assert not daemon._lifetime.retire_if_idle()
        now[0] += 2
        assert daemon._lifetime.retire_if_idle()
        with pytest.raises(ServiceRetiring):
            daemon.client_view(
                LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
            ).start_run(RunRequest(_request(), "race"))
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM preparation_operations").fetchone()[
                    0
                ]
                == 0
            )
    finally:
        daemon.stop()


def test_completed_preparation_history_does_not_retain_idle_service(
    tmp_path: Path,
) -> None:
    from loom.queue import LocalDaemon, LocalDaemonPrincipal, LocalDaemonRole
    from loom.preparation import CoordinatorPreparation

    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        client.prepare_run(_request())
        with daemon._cycle_lock:
            assert daemon._lifetime.retained()
        result = client.wait_operation(_request().operation_id, timeout=25)
        assert result.operation.state == "applied"
        assert daemon._lifetime.retire_if_idle()
    finally:
        daemon.stop()


def test_concurrent_starters_share_identity_and_attachment_handoff(
    tmp_path: Path,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from loom.deployment import ensure_available

    path = _selection(tmp_path)
    selection = load_deployment(path)

    def start(attachment):
        return ensure_available(
            selection, attachment_id=attachment, deadline=time.monotonic() + 20
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(start, ["first", "second"]))
        assert first.description.coordinator_id == second.description.coordinator_id
        first.release(None)
        first.client.close()
        assert second.client._native_call("service_lifetime", {})["retained"]
        second.release(None)
        second.client.close()
        deadline = time.monotonic() + 20
        from loom._run import _process_receipt

        while _process_receipt(tmp_path / "deployment/coordinator")[0] != "stopped":
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        _stop_fixture_process(tmp_path / "deployment/coordinator")


def test_multi_role_creation_replays_interrupted_first_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import loom.deployment as deployment_module

    selection = load_deployment(_mixed_selection(tmp_path, "run", "run"))
    original = deployment_module._write_binding
    interrupted = False

    def write(path, value):
        nonlocal interrupted
        original(path, value)
        if value["roles"]["coordinator"]["ids"] is not None and not interrupted:
            interrupted = True
            raise OSError("starter interrupted after first role publication")

    monkeypatch.setattr(deployment_module, "_write_binding", write)
    with pytest.raises(OSError, match="starter interrupted"):
        _bind(selection, "first", time.monotonic() + 20)
    assert selection.binding is not None
    saved = json.loads(selection.binding.read_text())
    assert set(saved["roles"]) == {"coordinator", "agent"}
    monkeypatch.setattr(deployment_module, "_write_binding", original)
    replay, _ = _bind(selection, "second", time.monotonic() + 20)
    assert replay["coordinator"]["ids"] == saved["roles"]["coordinator"]["ids"]
    assert replay["agent"]["ids"] is not None


def test_foreground_restart_honors_retained_run_lifetime(tmp_path: Path) -> None:
    from threading import Event
    from loom.queue.deployment import load_coordinator_service_config
    from loom.service_runtime import serve_coordinator
    from loom.queue._service_lifetime import retained_lifetime

    selection = load_deployment(_selection(tmp_path))
    _bind(selection, "expired", time.monotonic() + 20)
    with sqlite3.connect(tmp_path / "deployment/coordinator/control.sqlite") as conn:
        conn.execute(
            "DELETE FROM daemon_metadata WHERE key = 'startup-attachment:expired'"
        )
        conn.commit()
    service = load_coordinator_service_config(tmp_path / "coordinator.json")
    # Omitted runtime lifetime is the existing foreground-command restart path.
    serve_coordinator(service, stop=Event())
    with sqlite3.connect(service.daemon.control_database) as conn:
        values = dict(conn.execute("SELECT key,value FROM root_metadata"))
    assert values["service_lifetime"] == "run"
    assert json.loads(values["service_process"])["stopped"]
    with pytest.raises(QueueConflictError, match="lifetime"):
        retained_lifetime(service.daemon.coordinator_root, "persistent")


def test_completed_run_cannot_retire_owner_with_another_accepted_run(
    tmp_path: Path,
) -> None:
    from dataclasses import replace
    from loom.queue import LocalDaemon
    from loom.preparation import CoordinatorPreparation

    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(RunRequest(_request(), "first"), principal_id="caller")
        assert (
            daemon.wait_operation("prepare-1", timeout=25).operation.state == "applied"
        )
        assert daemon._wait("first", timeout_seconds=25).state.value == "SUCCEEDED"
        assert daemon._preparations._reconcile_lock.acquire(timeout=5)
        try:
            second = replace(_request(), operation_id="prepare-2", run_name="target-2")
            daemon.start_run(RunRequest(second, "second"), principal_id="caller")
            assert not daemon._lifetime.retire_if_idle()
            assert daemon.operation("prepare-2").state == "pending"
            cancelled = daemon.cancel_run_operation("prepare-2", principal_id="caller")
            assert cancelled.state == "pending"
            # The cancellation control remains pending until reconciliation.
            assert not daemon._lifetime.retire_if_idle()
        finally:
            daemon._preparations._reconcile_lock.release()
        assert (
            daemon.wait_operation(cancelled.operation_id, timeout=25).operation.state
            == "applied"
        )
        assert daemon._preparations._reconcile_lock.acquire(timeout=5)
        try:
            control = daemon.cancel_run_operation("prepare-1", principal_id="caller")
            assert control.state == "pending"
            assert daemon._wait("first", timeout_seconds=1).state.value == "SUCCEEDED"
            assert not daemon._lifetime.retire_if_idle()
        finally:
            daemon._preparations._reconcile_lock.release()
        assert (
            daemon.wait_operation(control.operation_id, timeout=25).operation.state
            == "applied"
        )
        assert daemon._lifetime.retire_if_idle()
    finally:
        daemon.stop()


@pytest.mark.parametrize("transport", ["unix", "https"])
def test_same_project_relative_source_through_borrowed_connections(
    tmp_path: Path, transport: str
) -> None:
    from loom.preparation import CoordinatorPreparation
    from loom.queue import LocalDaemon, LocalDaemonSocketServer
    from loom.queue.agent_session_transport import (
        AgentTlsServerConfig,
        LocalDaemonAgentHttpServer,
    )
    from loom.queue.deployment import load_coordinator_service_config
    from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials
    from loom.diagnostics.run_inspection import projection_callable
    from loom.pipeline.stores import LocalRunStore

    service = _service(tmp_path, mode="shared")
    credentials = None
    if transport == "https":
        credentials = mutual_tls_credentials(tmp_path / "tls")
        config_path = tmp_path / "coordinator.json"
        authored = json.loads(config_path.read_text())
        authored["agent_policy"]["principals"] = [
            {
                "credential_id": "client-credential",
                "principal_id": "client",
                "role": "client",
                "actions": [],
                "agent_ids": [],
                "pools": [],
            }
        ]
        config_path.write_text(json.dumps(authored))
        service = load_coordinator_service_config(config_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    inspect = projection_callable(
        run_store=LocalRunStore(service.daemon.run_store_root), daemon=daemon
    )
    if credentials is None:
        server = LocalDaemonSocketServer(
            daemon, service.daemon.endpoint, inspect_run=inspect
        )
        server.start()
        path = tmp_path / "client.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "loom.coordinator-client",
                    "expected_coordinator_id": daemon._require_started(),
                    "transport": {
                        "kind": "unix",
                        "endpoint": str(service.daemon.endpoint),
                    },
                }
            )
        )
        path.chmod(0o600)
    else:
        server = LocalDaemonAgentHttpServer(
            daemon,
            AgentTlsServerConfig(
                "localhost",
                0,
                credentials["server"].with_suffix(".crt"),
                credentials["server"].with_suffix(".key"),
                credentials["ca"].with_suffix(".crt"),
                {
                    certificate_fingerprint(
                        credentials["other"].with_suffix(".crt")
                    ): "client-credential"
                },
            ),
            inspect_run=inspect,
        )
        server.start()
        path = tmp_path / "client.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "loom.coordinator-client",
                    "expected_coordinator_id": daemon._require_started(),
                    "transport": {
                        "kind": "https",
                        "url": f"https://localhost:{server.port}",
                        "server_ca_path": str(credentials["ca"].with_suffix(".crt")),
                        "certificate_path": str(
                            credentials["other"].with_suffix(".crt")
                        ),
                        "private_key_path": str(
                            credentials["other"].with_suffix(".key")
                        ),
                    },
                }
            )
        )
        path.chmod(0o600)

    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.deployment",
                "connection": "client.json",
                "preparation": {
                    "source": _request().source.to_dict(),
                    "profile": _request().preparation_profile,
                },
            }
        )
    )
    selection.chmod(0o600)
    if transport == "unix":
        value = json.loads(selection.read_text())
        value.pop("connection")
        value["coordinator"] = {
            "service_config": "coordinator.json",
            "lifetime": "persistent",
        }
        value["binding_path"] = "binding.json"
        selection.write_text(json.dumps(value))
    try:
        result = loom.run(
            RunRequest(_request(), "same-source"),
            deployment=selection,
            timeout_seconds=30,
        )
        assert result.observation.admission is not None
        assert result.observation.admission.state.value == "SUCCEEDED"
        assert _cleanup_state(result, "coordinator") == "persistent/borrowed"
        assert (tmp_path / "binding.json").exists() is (transport == "unix")
    finally:
        server.stop()
        daemon.stop()


def test_cleanup_refusal_preserves_committed_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event, Thread
    from loom.queue.deployment import load_coordinator_service_config
    from loom.queue.errors import QueueServiceError
    from loom.queue.local_daemon_execution import LocalDaemonExecution
    from loom.service_runtime import serve_coordinator

    path = _selection(tmp_path)
    selection = load_deployment(path)
    _bind(selection, "prepare-1", time.monotonic() + 20)
    service = load_coordinator_service_config(tmp_path / "coordinator.json")
    original = LocalDaemonExecution.shutdown_clean

    def refuse(self):
        raise QueueServiceError("fixture containment proof unavailable")

    monkeypatch.setattr(LocalDaemonExecution, "shutdown_clean", refuse)
    ready, stop = Event(), Event()
    failures = []

    def serve():
        try:
            serve_coordinator(service, stop=stop, ready=lambda *_: ready.set())
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=serve)
    thread.start()
    try:
        assert ready.wait(10)
        result = loom.run(
            RunRequest(_request(), "cleanup-refused"),
            deployment=path,
            timeout_seconds=30,
        )
        assert result.observation.admission is not None
        assert result.observation.admission.state.value == "SUCCEEDED"
        assert _cleanup_state(result, "coordinator") == "cleanup-blocked"
        assert thread.is_alive()
    finally:
        monkeypatch.setattr(LocalDaemonExecution, "shutdown_clean", original)
        stop.set()
        thread.join(10)
        assert not thread.is_alive()
        assert not failures


def test_observation_handshake_shares_configured_budget_and_keeps_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event
    from loom.preparation import CoordinatorPreparation
    from loom.queue import LocalDaemon, LocalDaemonSocketServer
    from loom.queue import local_daemon_transport as transport

    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    accepted, release = Event(), Event()
    calls = []
    accepted_at = []
    original = transport.dispatch_control

    def dispatch(daemon, principal, operation, payload, **kwargs):
        if operation == "handshake" and accepted.is_set():
            release.wait(2)
        result = original(daemon, principal, operation, payload, **kwargs)
        if operation == "start_run":
            calls.append(operation)
            accepted_at.append(time.monotonic())
            accepted.set()
        return result

    monkeypatch.setattr(transport, "dispatch_control", dispatch)
    server = LocalDaemonSocketServer(daemon, service.daemon.endpoint)
    server.start()
    connection = tmp_path / "client.json"
    connection.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.coordinator-client",
                "expected_coordinator_id": daemon._require_started(),
                "transport": {"kind": "unix", "endpoint": str(service.daemon.endpoint)},
            }
        )
    )
    connection.chmod(0o600)
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.deployment",
                "coordinator": {
                    "service_config": "coordinator.json",
                    "lifetime": "persistent",
                },
                "binding_path": "binding.json",
                "wait_seconds": 0.1,
                "preparation": {
                    "source": _request().source.to_dict(),
                    "profile": _request().preparation_profile,
                },
            }
        )
    )
    selection.chmod(0o600)
    try:
        outcome = loom.run(RunRequest(_request(), "bounded"), deployment=selection)
        assert time.monotonic() - accepted_at[0] < 1
        assert outcome.observation.operation is not None
        assert outcome.observation.operation.operation_id == "prepare-1"
        assert calls == ["start_run"]
        assert daemon.operation("prepare-1").state == "pending"
    finally:
        release.set()
        from loom.coordinator import CoordinatorClient

        client = CoordinatorClient.from_unix_socket(service.daemon.endpoint)
        control = client.cancel_run_operation("prepare-1")
        client.close()
        daemon._preparations._reconcile_lock.release()
        assert (
            daemon.wait_operation(control.operation_id, timeout=25).operation.state
            == "applied"
        )
        server.stop()
        daemon.stop()


def test_retirement_rejects_new_cancellation_of_completed_run(tmp_path: Path) -> None:
    from loom.queue import LocalDaemon
    from loom.preparation import CoordinatorPreparation
    from loom.queue._service_lifetime import ServiceRetiring

    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(RunRequest(_request(), "completed"), principal_id="caller")
        assert (
            daemon.wait_operation("prepare-1", timeout=25).operation.state == "applied"
        )
        assert daemon._wait("completed", timeout_seconds=25).state.value == "SUCCEEDED"
        assert daemon._lifetime.retire_if_idle()
        with pytest.raises(ServiceRetiring):
            daemon.cancel_run_operation("prepare-1", principal_id="caller")
        with sqlite3.connect(service.daemon.control_database) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM preparation_cancellations"
                ).fetchone()[0]
                == 0
            )
    finally:
        daemon.stop()
