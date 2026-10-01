"""Declaration evidence is bound to accepted native state, not readiness cache."""

from dataclasses import replace
import json
import sqlite3

import pytest

from loom.queue.agent_session_transport import (
    LocalDaemonAgentHttpClient,
    _RemoteAgentJournal,
)
from loom.queue.agent_sessions import AgentRegistration, AgentSession, AgentSessionState
from loom.queue.deployment import load_outbound_agent_service_config, read_agent_spec
from loom.queue.errors import QueueError
from loom.queue.retirement import (
    agent_declaration_guard,
    read_agent_declaration_binding,
    retire_outbound_agent,
    verify_agent_candidate,
)
from tests.unit.loom.queue.test_deployment import _agent_config, _write_protected


def test_initialized_binding_matches_qualified_declaration_and_native_revision(
    tmp_path,
):
    source = _agent_config(tmp_path)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    spec = read_agent_spec(source)
    binding = read_agent_declaration_binding(spec.agent_root, spec.declaration_digest)
    assert binding is not None
    assert binding.declaration_digest == service.client.declaration_digest
    assert binding.immutable_fingerprint == service.immutable_fingerprint
    assert binding.active_fingerprint == service.active_fingerprint
    assert binding.active_configuration_revision == 1


def test_candidate_and_start_guard_use_binding_without_qualification(
    tmp_path, monkeypatch
):
    source = _agent_config(tmp_path)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    spec = read_agent_spec(source)

    def forbidden(*_args, **_kwargs):
        pytest.fail("native ownership inspection probed or started a workload")

    monkeypatch.setattr("loom.queue.deployment.qualify_agent_spec", forbidden)
    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor._profile_from_value", forbidden
    )
    binding = verify_agent_candidate(spec)
    assert verify_agent_candidate(spec) == binding
    with agent_declaration_guard(spec.agent_root, spec.declaration_digest) as owned:
        assert owned == binding
        with pytest.raises(QueueError, match="already locked"):
            verify_agent_candidate(spec)


@pytest.mark.parametrize("damage", ["partial", "registered", "legacy"])
def test_existing_candidate_is_not_success_merely_because_it_exists(tmp_path, damage):
    source = _agent_config(tmp_path)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    spec = read_agent_spec(source)
    if damage == "partial":
        (spec.agent_root / "supervisor/supervisor.sqlite").unlink()
    elif damage == "legacy":
        with sqlite3.connect(spec.agent_root / "control.sqlite") as conn:
            conn.execute("DELETE FROM root_metadata WHERE key='declaration_binding'")
    else:
        journal = _RemoteAgentJournal(
            spec.agent_root,
            expected_configuration_fingerprint=service.immutable_fingerprint,
            expected_active_configuration_fingerprint=service.active_fingerprint,
        )
        try:
            journal.persist_registration_intent(
                AgentRegistration(
                    "register",
                    "coordinator",
                    "epoch",
                    journal.root_id,
                    "config",
                    "inventory",
                    "availability",
                    ("default",),
                )
            )
        finally:
            journal.close()
    with pytest.raises(QueueError):
        verify_agent_candidate(spec)
    assert spec.agent_root.is_dir()


def test_programmatic_config_does_not_fabricate_declaration_evidence(tmp_path):
    source = _agent_config(tmp_path)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(
        replace(service.client, declaration_digest=None)
    )
    spec = read_agent_spec(source)
    assert (
        read_agent_declaration_binding(spec.agent_root, spec.declaration_digest) is None
    )


@pytest.mark.parametrize(
    "damage", ["declaration", "revision", "encoding", "immutable", "protection"]
)
def test_conflicting_present_evidence_never_falls_back_to_qualification(
    tmp_path, monkeypatch, damage
):
    source = _agent_config(tmp_path)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    spec = read_agent_spec(source)
    if damage == "declaration":
        payload = json.loads(source.read_text())
        payload["reconnect_seconds"] = 0.25
        spec = read_agent_spec(_write_protected(source, payload))
    elif damage == "protection":
        (spec.agent_root / "role-binding.json").chmod(0o644)
    else:
        with sqlite3.connect(spec.agent_root / "control.sqlite") as conn:
            if damage == "revision":
                conn.execute(
                    "UPDATE root_metadata SET value='2' WHERE key='active_configuration_revision'"
                )
            else:
                record = json.loads(
                    conn.execute(
                        "SELECT value FROM root_metadata WHERE key='declaration_binding'"
                    ).fetchone()[0]
                )
                record["immutable_fingerprint"] = "0" * 64
                conn.execute(
                    "UPDATE root_metadata SET value=? WHERE key='declaration_binding'",
                    ("not JSON" if damage == "encoding" else json.dumps(record),),
                )

    def forbidden(*_args, **_kwargs):
        pytest.fail("conflicting native evidence fell back to qualification")

    monkeypatch.setattr("loom.queue.deployment.qualify_agent_spec", forbidden)
    with pytest.raises(QueueError):
        retire_outbound_agent(
            spec,
            operation_id="remove",
            expected_coordinator_id="coordinator",
            expected_session_id="session",
        )


def test_failed_readiness_cannot_publish_a_native_declaration_binding(tmp_path):
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["resident_profiles"][0]["readiness"] = {
        "imports": ["missing_package_for_init_test"]
    }
    _write_protected(source, payload)
    service = load_outbound_agent_service_config(source, _allow_unready=True)
    assert service.client.declaration_digest is not None
    assert service.client.agent_root is not None
    with pytest.raises(QueueError, match="accepted readiness"):
        LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    assert not service.client.agent_root.exists()


def test_binding_inspection_does_not_initialize_missing_root(tmp_path):
    root = tmp_path / "missing"
    with pytest.raises(QueueError):
        read_agent_declaration_binding(root, "a" * 64)
    assert not root.exists()


def test_bound_control_owner_refuses_unresolved_delivery_before_shutdown(
    tmp_path, monkeypatch
):
    source = _agent_config(tmp_path)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    spec = read_agent_spec(source)
    journal = _RemoteAgentJournal(
        spec.agent_root,
        expected_configuration_fingerprint=service.immutable_fingerprint,
        expected_active_configuration_fingerprint=service.active_fingerprint,
    )
    try:
        registration = journal.persist_registration_intent(
            AgentRegistration(
                "register",
                "coordinator",
                "epoch",
                journal.root_id,
                "config",
                "inventory",
                "availability",
                ("default",),
            )
        )
        session = AgentSession(
            "session",
            "coordinator",
            "epoch",
            "worker",
            journal.root_id,
            "policy",
            "config",
            "inventory",
            "availability",
            ("python",),
            ("default",),
            AgentSessionState.ACTIVE,
        )
        journal.persist_session(
            registration.idempotency_key, registration.value(), session
        )
        # A delivered reference becomes durable before its workspace or launch.
        journal.retain_assignment_reference(session.session_id, "accepted-delivery")
    finally:
        journal.close()

    def forbidden(*_args, **_kwargs):
        pytest.fail(
            "unresolved delivery reached qualification, shutdown or HTTPS retirement"
        )

    monkeypatch.setattr("loom.queue.deployment.qualify_agent_spec", forbidden)
    monkeypatch.setattr(
        "loom.queue._agent_process_supervisor.retained_supervisor_guard", forbidden
    )
    monkeypatch.setattr(
        "loom.queue.agent_session_transport._exchange_agent_request", forbidden
    )
    with pytest.raises(QueueError, match="retained work"):
        retire_outbound_agent(
            spec,
            operation_id="remove",
            expected_coordinator_id="coordinator",
            expected_session_id="session",
        )
    with sqlite3.connect(spec.agent_root / "control.sqlite") as conn:
        assert (
            conn.execute("SELECT state FROM agent_sessions_local").fetchone()[0]
            == "ACTIVE"
        )
        assert (
            conn.execute("SELECT resolved FROM agent_session_references").fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT value FROM root_metadata WHERE key='role_retirement'"
            ).fetchone()
            is None
        )
