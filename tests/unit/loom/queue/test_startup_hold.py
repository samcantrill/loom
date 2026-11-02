"""Startup holds precede effects and survive owner loss without cancelling work."""

from contextlib import closing
from dataclasses import replace
import io
import json
import multiprocessing
import sqlite3
from threading import Event

import pytest

from loom.cli.main import main
from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from loom.queue._maintenance import MaintenanceInProgress
from loom.queue._agent_session_journal import _RemoteAgentJournal
from loom.queue.agent_sessions import AgentControl, AgentControlKind, AgentRegistration, AgentSession, AgentSessionState
from loom.queue.agent_session_transport import AgentTlsClientConfig, LocalDaemonAgentHttpClient
from loom.queue.errors import QueueError
from loom.queue.operations import control_intent_digest, inspect_native_service
from tests.integration.queue.test_maintenance_admission import service, operator
from tests.integration.queue.test_preparation_operations import _request
from tests.integration.queue.test_slurm_ready_stage import _profile


@pytest.fixture
def root(tmp_path_factory):
    return tmp_path_factory.mktemp("held")


def _agent(root):
    config = AgentTlsClientConfig(
        url="https://localhost:8443", server_ca_path=root / "ca.crt",
        certificate_path=root / "agent.crt", private_key_path=root / "agent.key",
        agent_root=root / "agent",
        slurm_profiles=(_profile(FakeSlurmCommandRunner(), capability_path=root / "capability"),),
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    with closing(LocalDaemonAgentHttpClient(config)) as client:
        journal = client._require_journal()
        registration = AgentRegistration("register", "coordinator", "epoch", client.agent_root_id,
                                         "config", "inventory", "availability", ("default",), ("python",))
        registration = journal.persist_registration_intent(registration)
        session = AgentSession("session", "coordinator", "epoch", "agent", client.agent_root_id,
                               "policy", "config", "inventory", "availability", ("python",),
                               ("default",), AgentSessionState.ACTIVE)
        journal.persist_session(registration.idempotency_key, registration.value(), session)
    return config


def _resume(operation="resume", *, hold=None):
    return AgentControl(operation, AgentControlKind.RESUME, "agent", "session", "config", None, False,
                        "operator resume", startup_hold_id=hold)


def _kill_owner(config, role):
    """Kill a real lock-owning process while its durable availability is active."""
    context = multiprocessing.get_context("fork")
    receiver, sender = context.Pipe(duplex=False)

    def child():
        owner = LocalDaemon(config) if role == "coordinator" else LocalDaemonAgentHttpClient(config)
        if role == "coordinator":
            owner.start()
        sender.send("ready")
        Event().wait()

    process = context.Process(target=child)
    process.start()
    sender.close()
    try:
        assert receiver.poll(10), "owner never reached active state"
        assert receiver.recv() == "ready"
    finally:
        process.kill()
        process.join(10)
        receiver.close()
    assert not process.is_alive() and process.exitcode != 0


@pytest.mark.parametrize("killed", [False, True])
def test_coordinator_hold_precedes_effects_and_uses_existing_open(root, monkeypatch, killed):
    selected = service(root, local=False)
    LocalDaemon.initialize_deployment(selected.daemon)
    if killed:
        _kill_owner(selected.daemon, "coordinator")
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    seen = []
    observe_start = daemon._event_observers.start

    def start_observers():
        with selected.daemon.connect_database(selected.daemon.control_database) as conn:
            gate = json.loads(conn.execute("SELECT value FROM daemon_metadata WHERE key='maintenance-gate'").fetchone()[0])
        assert gate["state"] == "closed"
        seen.append(gate)
        observe_start()

    monkeypatch.setattr(daemon._event_observers, "start", start_observers)
    daemon.start(start_held=True)
    try:
        assert seen
        gate = operator(daemon).observe_maintenance()
        with pytest.raises(MaintenanceInProgress):
            daemon.prepare_run(_request(), principal_id="caller")
    finally:
        daemon.stop()
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    daemon.start()  # Omission must not erase the durable hold.
    try:
        current = operator(daemon).observe_maintenance()
        assert current["maintenance_id"] == gate["maintenance_id"]
        request = {
            "operation_id": "open", "maintenance_id": gate["maintenance_id"],
            "maintenance_intent_digest": control_intent_digest({"maintenance_id": gate["maintenance_id"]}),
            "action": "open", "expected_revision": current["revision"], "check": None,
        }
        result = operator(daemon).maintenance(request, expected_coordinator_id=daemon.status().coordinator_id)
        assert result["gate"]["state"] == "open"
        assert operator(daemon).maintenance(request, expected_coordinator_id=daemon.status().coordinator_id) == result
        assert daemon.prepare_run(_request(), principal_id="caller").operation_id == _request().operation_id
    finally:
        daemon.stop()


def test_held_coordinator_replays_retained_acceptance(root):
    selected = service(root, local=False)
    LocalDaemon.initialize_deployment(selected.daemon)
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    daemon.start()
    try:
        accepted = daemon.prepare_run(_request(), principal_id="caller")
    finally:
        daemon.stop()
    daemon = LocalDaemon(selected.daemon, preparation=CoordinatorPreparation(selected))
    daemon.start(start_held=True)
    try:
        assert daemon.prepare_run(_request(), principal_id="caller").operation_id == accepted.operation_id
        with pytest.raises(MaintenanceInProgress):
            daemon.prepare_run(replace(_request(), operation_id="new-request", run_name="new-target"), principal_id="caller")
    finally:
        daemon.stop()


@pytest.mark.parametrize("prior", ["received", "prepared", "applied"])
def test_held_agent_fences_old_resume_and_replays_exact_results(root, prior):
    config = _agent(root)
    old = _resume("old-resume")
    with closing(LocalDaemonAgentHttpClient(config)) as client:
        journal = client._require_journal()
        journal.retain_control(old)
        if prior != "received":
            assert journal.prepare_control(old) is None
        if prior == "applied":
            effect = client._apply_agent_control(old)
            journal.record_control_effect(old, effect)
    _kill_owner(config, "agent")
    with closing(LocalDaemonAgentHttpClient(config, start_held=True)) as client:
        journal = client._require_journal()
        hold = journal.startup_hold_id()
        assert hold and client._drained
        assert inspect_native_service(config.agent_root).value["startup_hold_id"] == hold
        effect = journal.prepare_control(old)
        assert effect.code == ("applied" if prior == "applied" else "startup_hold")
        journal.record_control_effect(old, effect)
        journal.acknowledge_control(old.operation_id)
        assert client._drained and journal.availability_drained()
    with closing(LocalDaemonAgentHttpClient(config)) as client:
        assert client._drained and client._require_journal().startup_hold_id() == hold
    with closing(LocalDaemonAgentHttpClient(config, start_held=True)) as client:
        journal = client._require_journal()
        current = journal.startup_hold_id()
        assert current != hold
        obsolete = _resume("obsolete", hold=hold)
        assert journal.prepare_control(obsolete).code == "startup_hold"
        journal.acknowledge_control(obsolete.operation_id)
        resume = _resume("current", hold=current)
        assert journal.prepare_control(resume) is None
        effect = client._apply_agent_control(resume)
        assert effect.code == "applied"
        journal.record_control_effect(resume, effect)
        journal.record_control_effect(resume, effect)
        assert journal.prepare_control(resume) == effect
        assert not client._drained and not journal.availability_drained()
        assert journal.startup_hold_id() is None
        assert "startup_hold_id" not in inspect_native_service(config.agent_root).value


def test_failed_agent_hold_releases_owner_lock(root, monkeypatch):
    config = _agent(root)

    def fail(_self):
        raise sqlite3.OperationalError("storage unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(_RemoteAgentJournal, "_hold_for_startup", fail)
        with pytest.raises(QueueError, match="state is unavailable"):
            LocalDaemonAgentHttpClient(config, start_held=True)
    with closing(LocalDaemonAgentHttpClient(config)) as client:
        assert not client._drained


def test_held_agent_preserves_uncertain_poll_for_reconciliation(root):
    config = _agent(root)
    request = {"session_id": "session", "availability_revision": "availability", "sequence": 1, "wait_timeout_ms": 100}
    with closing(LocalDaemonAgentHttpClient(config)) as client:
        client._require_journal().prepare_poll("session", "availability", 1, request)
    with closing(LocalDaemonAgentHttpClient(config, start_held=True)) as client:
        journal = client._require_journal()
        assert journal.recovery_poll(100) == ("FENCED", request)
        assert journal.pending_poll() == ("session", "availability", 1)
        journal.complete_poll("session", 1, {"result": "wait"}, recovered=True)
        assert journal.pending_poll() is None
        assert client._drained and journal.startup_hold_id()


def test_resume_wire_compatibility_and_scope():
    legacy = _resume()
    assert "startup_hold_id" not in legacy.value()
    assert AgentControl.from_value(legacy.value()) == legacy
    held = _resume(hold="current")
    assert AgentControl.from_value(held.value()) == held
    with pytest.raises(QueueError, match="requires resume"):
        replace(held, kind=AgentControlKind.DRAIN)


def test_daemon_serve_cli_reaches_native_startup_hold(root, monkeypatch):
    import loom.service_runtime as runtime
    from loom.queue import deployment
    selected = service(root, local=False)
    LocalDaemon.initialize_deployment(selected.daemon)
    monkeypatch.setattr(deployment, "load_coordinator_service_config", lambda *a, **k: selected)
    serve = runtime.serve_coordinator

    def bounded(*args, **kwargs):
        kwargs["stop"].set()
        serve(*args, **kwargs)

    monkeypatch.setattr(runtime, "serve_coordinator", bounded)
    out, err = io.StringIO(), io.StringIO()
    assert main(["queue", "daemon-serve", str(root / "config.yaml"), "--start-held", "--format", "json"],
                stdout=out, stderr=err) == 0, err.getvalue()
    with selected.daemon.connect_database(selected.daemon.control_database) as conn:
        gate = json.loads(conn.execute("SELECT value FROM daemon_metadata WHERE key='maintenance-gate'").fetchone()[0])
    assert gate["state"] == "closed"


def test_resume_cli_carries_observed_hold(root, monkeypatch):
    import loom.cli.queue as cli
    selected = []

    class Operator:
        def control_agent(self, control):
            selected.append(control)
            return {"state": "pending_delivery"}

    monkeypatch.setattr(cli, "_operator_client", lambda _: Operator())
    err = io.StringIO()
    assert main(["queue", "daemon-agent-resume", "--endpoint", str(root / "control.sock"), "--operation-id", "resume",
                 "--agent-id", "agent", "--session-id", "session", "--config-revision", "config",
                 "--startup-hold-id", "observed", "--format", "json"], stdout=io.StringIO(), stderr=err) == 0, err.getvalue()
    assert selected[0].startup_hold_id == "observed"


def test_agent_serve_cli_reaches_native_startup_hold(root, monkeypatch):
    from loom.queue import deployment
    from tests.unit.loom.queue.test_deployment import _agent_config, _write_protected
    from tests.unit.loom.queue.test_storage_upgrade import _profile as profile_declaration

    path = _agent_config(root)
    value = json.loads(path.read_text())
    value.update(resident_profiles=[], slurm_profiles=[profile_declaration()])
    _write_protected(path, value)
    selected = deployment.load_outbound_agent_service_config(path)
    LocalDaemonAgentHttpClient.initialize_agent_root(selected.client)
    run = deployment.run_outbound_agent_service

    def bounded(*args, **kwargs):
        kwargs["stop"].set()
        run(*args, **kwargs)

    monkeypatch.setattr(deployment, "run_outbound_agent_service", bounded)
    err = io.StringIO()
    assert main(["queue", "agent-serve", str(path), "--start-held", "--format", "json"],
                stdout=io.StringIO(), stderr=err) == 0, err.getvalue()
    out = io.StringIO()
    assert main(["queue", "daemon-owner", "--root", str(selected.client.agent_root), "--format", "json"],
                stdout=out, stderr=err) == 0, err.getvalue()
    assert json.loads(out.getvalue())["result"]["value"]["startup_hold_id"]
