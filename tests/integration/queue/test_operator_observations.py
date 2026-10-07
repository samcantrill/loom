"""Supported native operator observations through real owner and wire boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
import os
import socket
import sqlite3

import pytest

from loom.coordinator import CoordinatorClientError, CoordinatorOperatorClient
from loom.queue import LocalDaemon, LocalDaemonConfig, LocalDaemonSocketServer
from loom.queue.local_daemon import LocalDaemonPrincipal, LocalDaemonRole
from loom.queue.agent_sessions import (
    AgentControl,
    AgentControlKind,
    AgentControlEffect,
    AgentOffer,
    AgentPolicyConfig,
    LocalOwnerOperatorPolicy,
    TransportPrincipalPolicy,
)
from loom.queue._managed_local import ResourceAvailabilityStatus
from loom.queue._remote_stage_execution import GpuDeviceDescriptor
from loom.queue.agent_session_transport import (
    LocalDaemonAgentHttpServer,
    AgentTlsServerConfig,
)
from loom.queue.operations import inspect_native_service, probe_upgrade_compatibility
from tests.integration.queue.test_agent_session_transport import (
    _policy,
    _request,
    _provider_descriptors,
    _credentials,
    _fingerprint,
)

pytestmark = pytest.mark.integration
DEVICE = GpuDeviceDescriptor("gpu0", "synthetic", 1024)


@pytest.fixture
def owner(tmp_path, request):
    actions = getattr(request, "param", ("drain",))
    policy = AgentPolicyConfig(
        agents=(replace(_policy().agents[0], gpu_devices=(DEVICE,)),),
        principals=(
            TransportPrincipalPolicy(
                "operator-credential",
                "operator-principal",
                "operator",
                actions=("drain",),
                agent_ids=("agent-a",),
                pools=("default",),
            ),
        ),
        local_owner=LocalOwnerOperatorPolicy(actions, ("agent-a",), ("default",)),
    )
    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        None,
        tmp_path / "runs",
        None,
        cpu_capacity=0,
        agent_policy=policy,
    )
    LocalDaemon.initialize(config)
    from loom.timestamps import utc_timestamp
    accepted_time = utc_timestamp()
    daemon = LocalDaemon(config, clock=lambda: accepted_time)
    daemon.start()
    agent = daemon.agent_view(
        LocalDaemonPrincipal(
            "agent-principal", LocalDaemonRole.AGENT, "agent-credential"
        )
    )
    session = agent.register(
        replace(
            _request(agent.handshake(), "remote-root"), retirement_verifier="a" * 64
        )
    )
    operator = daemon.operator_view(
        LocalDaemonPrincipal(f"uid:{os.getuid()}", LocalDaemonRole.OPERATOR)
    )
    try:
        yield daemon, agent, session, operator
    finally:
        daemon.stop()


def offer(agent, session, *, busy=False):
    agent.publish_offer(
        AgentOffer(
            session.session_id,
            session.coordinator_epoch,
            session.config_revision,
            session.inventory_revision,
            session.availability_revision,
            2,
            4096,
            60,
            _provider_descriptors("cpu", "memory", "gpu"),
            gpu_devices=(DEVICE,),
            gpu_atoms=() if busy else (DEVICE.capacity_atom("gpu0"),),
            resource_status=(
                ResourceAvailabilityStatus(
                    "gpu",
                    "gpu0",
                    not busy,
                    "external_occupancy" if busy else "available",
                    "2026-10-06T00:00:00Z",
                ),
            ),
        ),
        idempotency_key="offer-1",
    )


def drain(session, *, operation_id="drain-1"):
    return AgentControl(
        operation_id,
        AgentControlKind.DRAIN,
        session.agent_id,
        session.session_id,
        session.config_revision,
        "default",
        False,
        "operator test",
    )


def dump(path):
    with sqlite3.connect(path) as conn:
        return tuple(conn.iterdump())


@pytest.mark.parametrize("case", ["capacity", "occupancy", "drained", "stale"])
def test_observation_matrix_preserves_roots_and_control_state(owner, monkeypatch, case):
    daemon, agent, session, operator = owner
    offer(agent, session, busy=case == "occupancy")
    if case == "drained":
        operator.control_agent(drain(session))
    if case == "stale":
        monkeypatch.setattr(daemon, "_clock", lambda: "2099-01-01T00:00:00Z")
    before = dump(daemon.config.control_database)
    files = set(daemon.config.coordinator_root.rglob("*"))
    value = operator.observe_agent(session.agent_id)
    assert value.owner == daemon.status().coordinator_id
    assert value.value["agent_root_id"] == "remote-root"
    assert value.value["connected"] == (case != "stale")
    assert value.value["drained"] == (case == "drained")
    if case == "occupancy":
        assert value.value["available"] is True  # CPU remains available.
        assert value.value["resource_status"][0]["reason_code"] == "external_occupancy"
    if case in {"drained", "stale"}:
        assert value.value["available"] is False
    assert value.freshness == ("retained" if case == "stale" else "current")
    status = operator.observe_status()
    assert status.value["configuration_revision"] == "1"
    assert status.value["scheduling_fingerprint"].startswith("scheduling-")
    assert dump(daemon.config.control_database) == before
    assert set(daemon.config.coordinator_root.rglob("*")) == files



@pytest.mark.parametrize("owner", [("drain", "resume")], indirect=True)
@pytest.mark.parametrize("outcome", ["pending", "applying", "retained_work", "reload_rejected", "applied"])
def test_resume_preserves_drain_until_agent_confirms_application(owner, outcome):
    daemon, agent, session, operator = owner
    offer(agent, session)
    operator.control_agent(drain(session))
    assert agent.next_control(session.session_id).operation_id == "drain-1"
    agent.acknowledge_control(
        session.session_id,
        AgentControlEffect("drain-1", "applied", session.config_revision,
                           session.inventory_revision, "drained-availability"),
    )
    assert operator.observe_agent(session.agent_id).value["drained"] is True
    operator.control_agent(
        replace(drain(session, operation_id="resume-1"), kind=AgentControlKind.RESUME)
    )
    assert operator.observe_agent(session.agent_id).value["drained"] is True
    if outcome != "pending":
        assert agent.next_control(session.session_id).operation_id == "resume-1"
    if outcome not in {"pending", "applying"}:
        agent.acknowledge_control(
            session.session_id,
            AgentControlEffect(
                "resume-1", outcome, session.config_revision, session.inventory_revision,
                "resumed-availability" if outcome == "applied" else "drained-availability",
            ),
        )
    before = dump(daemon.config.control_database)
    observation = operator.observe_agent(session.agent_id)
    assert observation.value["drained"] is (outcome != "applied")
    state = {"pending": "pending_delivery", "applying": "applying", "applied": "applied"}.get(outcome, "failed")
    assert observation.value["control"]["state"] == state
    assert dump(daemon.config.control_database) == before


def test_unavailable_and_offline_probes_create_nothing(tmp_path):
    root = tmp_path / "absent"
    with CoordinatorOperatorClient.from_unix_socket(
        root / "daemon.sock", expected_coordinator_id="known-owner"
    ) as client:
        value = client.observe_status()
    assert value.owner == "known-owner"
    assert value.availability == "unavailable"
    assert value.reason == "unavailable"
    assert inspect_native_service(root).availability == "unavailable"
    assert probe_upgrade_compatibility(root).availability == "unavailable"
    assert not root.exists()


def test_offline_probe_identity_boot_and_compatibility(owner):
    from loom.queue._service_lifetime import record_process

    daemon, _, _, _ = owner
    root = daemon.config.coordinator_root
    record_process(root, stopped=False)
    before = dump(daemon.config.control_database)
    result = inspect_native_service(
        root, expected_root_id=daemon.status().coordinator_id
    )
    assert result.value["ownership"] == "live"
    assert result.value["recorded_boot_id"] == result.value["boot_id"]
    assert (
        inspect_native_service(root, expected_root_id="another").reason == "wrong_owner"
    )
    compatible = probe_upgrade_compatibility(root)
    assert compatible.value["compatible"] is True
    assert compatible.value["migration_direction"] == "none"
    assert (
        probe_upgrade_compatibility(root, required_capabilities=("future",)).reason
        == "unsupported_capability"
    )
    assert dump(daemon.config.control_database) == before


@pytest.mark.parametrize("transport", ["unix", "https"])
def test_operator_control_guard_denial_lost_reply_and_exact_replay(
    owner, tmp_path, monkeypatch, transport
):
    import loom.queue.local_daemon_transport as unix
    import loom.queue.agent_session_transport as https

    daemon, agent, session, _ = owner
    offer(agent, session)
    coordinator_id = daemon.status().coordinator_id
    dropped = []
    if transport == "unix":
        server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
        server.start()
        client = CoordinatorOperatorClient.from_unix_socket(
            daemon.config.endpoint, expected_coordinator_id=coordinator_id
        )
        original = unix._write_message

        def reply_unix(connection, value):
            if (
                isinstance(value.get("result"), Mapping)
                and value["result"].get("operation_id") == "drain-1"
                and not dropped
            ):
                dropped.append(True)
                connection.shutdown(socket.SHUT_RDWR)
                return
            original(connection, value)

        monkeypatch.setattr(unix, "_write_message", reply_unix)
    else:
        credentials = _credentials(tmp_path / "tls")
        server = LocalDaemonAgentHttpServer(
            daemon,
            AgentTlsServerConfig(
                "localhost",
                0,
                credentials["server"].with_suffix(".crt"),
                credentials["server"].with_suffix(".key"),
                credentials["ca"].with_suffix(".crt"),
                {
                    _fingerprint(
                        credentials["other"].with_suffix(".crt")
                    ): "operator-credential"
                },
            ),
        )
        server.start()
        path = tmp_path / "operator.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "loom.coordinator-client",
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
        client = CoordinatorOperatorClient.from_connection_file(
            path, expected_coordinator_id=coordinator_id
        )
        original = https._Handler._reply

        def reply_https(handler, status, value):
            if (
                isinstance(value.get("result"), Mapping)
                and value["result"].get("operation_id") == "drain-1"
                and not dropped
            ):
                dropped.append(True)
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                return
            original(handler, status, value)

        monkeypatch.setattr(https._Handler, "_reply", reply_https)
    try:
        assert client.observe_status().owner == coordinator_id
        assert client.observe_agent("agent-a").value["connected"] is True
        before = dump(daemon.config.control_database)
        for control, expected, code in (
            (drain(session), "wrong-owner", "conflict"),
            (
                replace(drain(session), kind=AgentControlKind.RESUME),
                coordinator_id,
                "unauthorized",
            ),
        ):
            with pytest.raises(CoordinatorClientError) as caught:
                client.control_agent(control, expected_coordinator_id=expected)
            assert caught.value.code == code
            assert caught.value.mutation_outcome == "not_applied"
            assert dump(daemon.config.control_database) == before
        with pytest.raises(CoordinatorClientError) as caught:
            client.control_agent(drain(session), condition={"expected_control_id": None})
        assert dropped
        assert caught.value.mutation_outcome == "unknown"
        receipt = client.observe_control("drain-1")
        assert receipt["mutation_outcome"] == "applied"
        assert isinstance(receipt["intent_digest"], str)
        assert len(receipt["intent_digest"]) == 64
        after = dump(daemon.config.control_database)
        assert client.control_agent(drain(session), condition={"expected_control_id": None})["mutation_outcome"] == "applied"
        with pytest.raises(CoordinatorClientError) as caught:
            client.control_agent(replace(drain(session), reason="changed intent"), condition={"expected_control_id": None})
        assert caught.value.code == "conflict"
        assert caught.value.mutation_outcome == "not_applied"
        assert dump(daemon.config.control_database) == after
    finally:
        client.close()
        server.stop()


@pytest.mark.parametrize("role", ["coordinator", "agent"])
def test_role_declarations_are_protected_redacted_and_inert(
    tmp_path, monkeypatch, role
):
    from loom.queue import deployment
    from tests.unit.loom.queue.test_deployment import _coordinator_config, _agent_config

    source = (_coordinator_config if role == "coordinator" else _agent_config)(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("declaration inspection qualified execution")

    monkeypatch.setattr(deployment, "_resident_profile", forbidden)
    monkeypatch.setattr(deployment, "_trusted_target", forbidden)
    before = set(tmp_path.rglob("*"))
    observation = deployment.inspect_role_declaration(source, role=role)
    assert observation.value["qualified"] is False
    assert observation.value["protected_paths"] == "validated"
    assert observation.revision is not None
    assert len(observation.revision) == 64
    assert str(tmp_path) not in json.dumps(observation.to_dict())
    assert set(tmp_path.rglob("*")) == before
    source.chmod(0o644)
    from loom.queue.errors import QueueError

    with pytest.raises(QueueError):
        deployment.inspect_role_declaration(source, role=role)



def test_coordinator_declaration_rejects_incomplete_agent_server(tmp_path, monkeypatch):
    import yaml
    from loom.cli.main import main
    from loom.queue import deployment
    from loom.queue.errors import QueueConfigError
    from tests.unit.loom.queue.test_deployment import _coordinator_config

    source = _coordinator_config(tmp_path)
    payload = yaml.safe_load(source.read_text())
    payload["agent_server"] = {"port": 443}
    source.write_text(yaml.safe_dump(payload))

    def forbidden(*args, **kwargs):
        pytest.fail("declaration inspection qualified execution")

    monkeypatch.setattr(deployment, "_resident_profile", forbidden)
    monkeypatch.setattr(deployment, "_trusted_target", forbidden)
    before = set(tmp_path.rglob("*"))
    with pytest.raises(QueueConfigError, match="agent_server"):
        deployment.inspect_role_declaration(source, role="coordinator")
    assert main(["queue", "daemon-check", "--config", str(source), "--declaration-only"]) != 0
    assert set(tmp_path.rglob("*")) == before


def test_operator_cli_and_old_peer_capability_refusal(owner, monkeypatch, capsys):
    import loom.queue.local_daemon_transport as unix
    from loom.cli.main import main

    daemon, agent, session, _ = owner
    offer(agent, session)
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    try:
        assert (
            main(
                [
                    "queue",
                    "daemon-agent",
                    "agent-a",
                    "--operator",
                    "--endpoint",
                    str(daemon.config.endpoint),
                    "--format",
                    "json",
                ]
            )
            == 0
        )
        result = json.loads(capsys.readouterr().out)["result"]
        assert result["value"]["agent_root_id"] == "remote-root"
        original = unix.dispatch_control
        calls = []

        def old_peer(daemon, principal, operation, payload, **kwargs):
            calls.append(operation)
            result = dict(original(daemon, principal, operation, payload, **kwargs))
            if operation == "operator_handshake":
                result["capabilities"] = ["daemon-control-v1"]
            return result

        monkeypatch.setattr(unix, "dispatch_control", old_peer)
        with CoordinatorOperatorClient.from_unix_socket(
            daemon.config.endpoint
        ) as client:
            with pytest.raises(CoordinatorClientError) as caught:
                client.observe_status()
        assert caught.value.code == "unsupported_capability"
        assert caught.value.ids["missing_capability"] == "operator-observations-v1"
        assert calls == ["operator_handshake"]
    finally:
        server.stop()


@pytest.mark.parametrize("remote", [False, True])
def test_actual_claim_and_release_observations(tmp_path, monkeypatch, remote):
    from tests.integration.queue.test_agent_session_transport import (
        test_external_gpu_occupancy_drives_real_local_and_remote_admission as exercise,
    )

    exercise(tmp_path, monkeypatch, remote)


def test_unreachable_status_preserves_last_observed_owner_fact(owner):
    daemon, _, _, _ = owner
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    with CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint) as client:
        try:
            first = client.observe_status()
        finally:
            server.stop()
        retained = client.observe_status()
    assert retained.owner == first.owner
    assert retained.freshness == "retained"
    assert retained.availability == "unavailable"
    assert retained.reason == "unavailable"
    assert retained.value["retained_observed_at"] == first.observed_at
    assert retained.value["configuration_revision"] == first.value["configuration_revision"]


@pytest.mark.parametrize("owner", [("drain", "resume")], indirect=True)
def test_conditional_controls_preserve_independent_policy_and_exact_replay(owner):
    daemon, agent, session, direct = owner
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    def acknowledge(identity):
        assert agent.next_control(session.session_id).operation_id == identity
        agent.acknowledge_control(session.session_id, AgentControlEffect(
            identity, "applied", session.config_revision, session.inventory_revision,
            "availability-" + identity))
    try:
        with CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint, expected_coordinator_id=daemon.status().coordinator_id) as client:
            first = drain(session, operation_id="owned-drain")
            absent = {"expected_control_id": None}
            client.control_agent(first, condition=absent)
            acknowledge(first.operation_id)
            assert client.observe_agent(session.agent_id).value["control"]["operation_id"] == first.operation_id
            independent = drain(session, operation_id="independent-drain")
            direct.control_agent(independent)
            acknowledge(independent.operation_id)
            restore = replace(drain(session, operation_id="restore"), kind=AgentControlKind.RESUME)
            stale = {"expected_control_id": first.operation_id}
            with pytest.raises(CoordinatorClientError) as refused:
                client.control_agent(restore, condition=stale)
            assert refused.value.code == "conflict"
            assert refused.value.mutation_outcome == "not_applied"
            assert client.observe_agent(session.agent_id).value["drained"] is True
            assert client.observe_agent(session.agent_id).value["control"]["operation_id"] == independent.operation_id
            matching = {"expected_control_id": independent.operation_id}
            client.control_agent(restore, condition=matching)
            acknowledge(restore.operation_id)
            later = drain(session, operation_id="later-drain")
            direct.control_agent(later)
            acknowledge(later.operation_id)
            # Lost-reply recovery resolves original acceptance, never reapplies it.
            assert client.control_agent(restore, condition=matching)["state"] == "applied"
            assert client.observe_agent(session.agent_id).value["drained"] is True
            assert client.observe_agent(session.agent_id).value["control"]["operation_id"] == later.operation_id
            with pytest.raises(CoordinatorClientError) as changed:
                client.control_agent(restore, condition={"expected_control_id": later.operation_id})
            assert changed.value.code == "conflict"
    finally:
        server.stop()
