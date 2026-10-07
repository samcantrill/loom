"""Native profile promotion, immutable replay and interrupted binding recovery."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import sys

import pytest

from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    LocalDaemonAgentHttpClient,
)
from loom.queue.agent_sessions import (
    AgentControl,
    AgentControlKind,
    AgentRegistration,
    AgentSession,
    AgentSessionState,
)
from loom.queue._remote_stage_execution import (
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
)
from loom.queue.errors import QueueConflictError
from loom.queue import _profile_promotion as promotion
from tests.integration.queue.test_operator_observations import owner  # noqa: F401

pytestmark = pytest.mark.integration


def config(tmp_path, generation=1):
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "work", str(generation), "project", f"env-{generation}", "executor"
        ),
        tmp_path,
        Path(sys.executable),
    )
    return AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca",
        tmp_path / "cert",
        tmp_path / "key",
        agent_root=tmp_path / "agent",
        resident_profiles=(profile,),
        deployment_configuration_fingerprint=str(generation) * 64,
        active_configuration_fingerprint=str(generation + 3) * 64,
    )


def request(
    old, new, root_id, *, identity="promote-1", session="session", revision="config"
):
    return AgentControl(
        identity,
        AgentControlKind.PROMOTE,
        "agent-a",
        session,
        revision,
        None,
        False,
        "selected workload upgrade",
        {
            "maintenance_id": "upgrade",
            "maintenance_intent_digest": "target",
            "expected_gate_revision": 1,
            "agent_root_id": root_id,
            "predecessor_immutable": old.deployment_configuration_fingerprint,
            "predecessor_active": old.active_configuration_fingerprint,
            "target_immutable": new.deployment_configuration_fingerprint,
            "target_active": new.active_configuration_fingerprint,
            "profile_id": "work",
            "target_profile": new.resident_profiles[0].descriptor.to_dict(),
        },
    )


def client(tmp_path):
    old, new = config(tmp_path), config(tmp_path, 2)
    LocalDaemonAgentHttpClient.initialize_agent_root(old)
    c = LocalDaemonAgentHttpClient(old, trusted_config_loader=lambda: new)
    j = c._require_journal()
    registration = AgentRegistration(
        "reg",
        "coordinator",
        "epoch",
        j.root_id,
        "config",
        "inventory",
        "availability",
        ("default",),
    )
    retained = j.persist_registration_intent(registration)
    session = AgentSession(
        "session",
        "coordinator",
        "epoch",
        "agent-a",
        j.root_id,
        "policy",
        "config",
        "inventory",
        "availability",
        (),
        ("default",),
        AgentSessionState.ACTIVE,
    )
    j.persist_session(retained.idempotency_key, retained.value(), session)
    return c, old, new


def close(c):
    if c._supervisor is not None:
        c._supervisor.shutdown_for_test()
    c.close()


def apply(c, control):
    assert c._require_journal().prepare_control(control) is None
    return c._apply_agent_control(control)


def test_promotion_replay_and_later_promotion_preserve_native_history(tmp_path):
    c, old, new = client(tmp_path)
    assert old.agent_root is not None and new.agent_root is not None
    root = c.agent_root_id
    first = request(old, new, root)
    assert first.promotion is not None
    try:
        secret = (old.agent_root / "supervisor" / "service.secret").read_bytes()
        from loom.queue._agent_process_supervisor import ResidentWorkerLaunch

        supervisor = c._supervisor
        assert supervisor is not None
        workspace = tmp_path / "historical"
        workspace.mkdir()
        launch = ResidentWorkerLaunch(
            supervisor.supervisor_id,
            supervisor.continuity_epoch,
            root,
            "session",
            "old-assignment",
            "old-process",
            "old-fence",
            "old-launch",
            "a" * 64,
            workspace,
            old.resident_profiles[0].launch_profile,
            {},
        )
        supervisor.launch(launch)
        supervisor.contain(launch)
        database = old.agent_root / "supervisor" / "supervisor.sqlite"
        with sqlite3.connect(database) as conn:
            historical = conn.execute("SELECT * FROM launches").fetchall()
        assert historical
        effect = apply(c, AgentControl.from_value(first.value()))
        assert effect.code == "applied"
        assert c.agent_root_id == root
        assert c._config == new and c._drained
        c._require_journal().acknowledge_control(first.operation_id)
        third = config(tmp_path, 3)
        c._trusted_config_loader = lambda: third
        second = request(
            new, third, root, identity="promote-2", revision=effect.config_revision
        )
        assert apply(c, second).code == "applied"
        assert c._require_journal().replayed_control_effect(first) == effect
        assert promotion.apply(c, first) == effect
        assert c._config == third
        with sqlite3.connect(database) as conn:
            assert conn.execute("SELECT * FROM launches").fetchall() == historical
        assert (old.agent_root / "supervisor" / "service.secret").read_bytes() == secret
        with sqlite3.connect(old.agent_root / "control.sqlite") as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM agent_controls_local").fetchone()[0]
                == 2
            )
        changed = replace(
            first, promotion={**first.promotion, "target_active": "a" * 64}
        )
        with pytest.raises(QueueConflictError, match="conflicts"):
            c._require_journal().prepare_control(changed)
    finally:
        close(c)


@pytest.mark.parametrize("boundary", ["accepted", "supervisor", "effect"])
def test_interrupted_promotion_recovers_before_startup_and_exact_replay(
    tmp_path, monkeypatch, boundary
):
    c, old, new = client(tmp_path)
    assert old.agent_root is not None and new.agent_root is not None
    control = request(old, new, c.agent_root_id)
    assert control.promotion is not None
    original = promotion._finish
    original_write = promotion.atomic_write_bytes
    if boundary == "accepted":
        monkeypatch.setattr(
            promotion,
            "_finish",
            lambda *a: (_ for _ in ()).throw(RuntimeError("crash")),
        )
    elif boundary == "supervisor":

        def write(path, value):
            if path.name == "service.json":
                raise RuntimeError("crash")
            return original_write(path, value)

        # Interrupt after the supervisor database changes, before its file does.
        monkeypatch.setattr(
            promotion,
            "atomic_write_bytes",
            lambda *a: (_ for _ in ()).throw(RuntimeError("crash")),
        )
    else:

        def finish(*args):
            original(*args)
            raise RuntimeError("crash")

        monkeypatch.setattr(promotion, "_finish", finish)
    with pytest.raises(RuntimeError, match="crash"):
        apply(c, control)
    c.close()
    monkeypatch.setattr(promotion, "_finish", original)
    monkeypatch.setattr(promotion, "atomic_write_bytes", original_write)
    recovered = LocalDaemonAgentHttpClient(new)
    try:
        assert recovered._drained
        effect = recovered._require_journal().replayed_control_effect(control)
        assert effect is not None and effect.code == "applied"
        assert recovered._config == new
        with sqlite3.connect(new.agent_root / "control.sqlite") as conn:
            assert (
                conn.execute(
                    "SELECT 1 FROM root_metadata WHERE key='profile_promotion_pending'"
                ).fetchone()
                is None
            )
    finally:
        close(recovered)


def test_stale_local_predecessor_and_retained_work_have_no_binding_effect(
    tmp_path, monkeypatch
):
    c, old, new = client(tmp_path)
    assert old.agent_root is not None and new.agent_root is not None
    # The native configuration name is owned by its existing supervisor.
    from loom.queue._agent_process_supervisor import AgentProcessSupervisorService

    initial = old.agent_root / "supervisor" / AgentProcessSupervisorService._CONFIG_NAME
    before = initial.read_bytes()
    try:
        control = request(old, new, c.agent_root_id)
        assert control.promotion is not None
        monkeypatch.setattr(c, "_has_retained_agent_work", lambda: True)
        with pytest.raises(QueueConflictError, match="settlement"):
            apply(c, control)
        assert initial.read_bytes() == before
        monkeypatch.setattr(c, "_has_retained_agent_work", lambda: False)
        stale = replace(
            control, promotion={**control.promotion, "predecessor_active": "0" * 64}
        )
        with pytest.raises(QueueConflictError):
            promotion.apply(c, stale)
        assert initial.read_bytes() == before
    finally:
        close(c)


@pytest.mark.parametrize("owner", [("maintenance", "drain")], indirect=True)
def test_native_operator_authorization_gate_guards_and_wire_replay(owner, tmp_path):  # noqa: F811
    from loom.coordinator import CoordinatorOperatorClient, CoordinatorClientError
    from loom.queue import LocalDaemonSocketServer

    daemon, agent, session, operator = owner
    old, new = config(tmp_path), config(tmp_path, 2)
    control = request(
        old,
        new,
        "remote-root",
        session=session.session_id,
        revision=session.config_revision,
    )
    assert control.promotion is not None
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    try:
        with CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint, expected_coordinator_id=daemon.status().coordinator_id) as wire:
            with pytest.raises(CoordinatorClientError):
                wire.control_agent(control)
    finally:
        server.stop()
    # Gate closure and a settled drain are both required before authorization.
    operator.maintenance(
        {
            "operation_id": "close",
            "maintenance_id": "upgrade",
            "maintenance_intent_digest": "target",
            "action": "close",
            "expected_revision": 0,
            "check": None,
        },
        expected_coordinator_id=daemon.status().coordinator_id,
    )
    drain = replace(
        control, operation_id="drain", kind=AgentControlKind.DRAIN, promotion=None
    )
    operator.control_agent(drain)
    from loom.queue.agent_sessions import AgentControlEffect

    agent.next_control(session.session_id)
    agent.acknowledge_control(
        session.session_id,
        AgentControlEffect(
            "drain",
            "applied",
            session.config_revision,
            session.inventory_revision,
            "drained",
        ),
    )
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    try:
        with CoordinatorOperatorClient.from_unix_socket(daemon.config.endpoint, expected_coordinator_id=daemon.status().coordinator_id) as wire:
            accepted = wire.control_agent(control)
            assert wire.control_agent(control) == accepted
            assert (
                wire.observe_control(control.operation_id)["state"]
                == "pending_delivery"
            )
    finally:
        server.stop()
    with pytest.raises(QueueConflictError):
        operator.control_agent(
            replace(control, promotion={**control.promotion, "target_active": "b" * 64})
        )


def test_external_supervisor_rejoins_only_after_native_promotion(tmp_path):
    from loom.queue._agent_process_supervisor import (
        AgentProcessSupervisorService,
        SupervisorLaunchConfiguration,
    )

    c, old, new = client(tmp_path)
    new = replace(new, external_supervisor=True)
    assert new.agent_root is not None
    c._config = replace(old, external_supervisor=True)
    c._trusted_config_loader = lambda: new
    control = request(old, new, c.agent_root_id)
    external = None
    try:
        effect = apply(c, control)
        assert c._supervisor is None and c._drained
        external = AgentProcessSupervisorService.start_empty_initialized(
            new.agent_root,
            configuration=SupervisorLaunchConfiguration(
                c.agent_root_id, (new.resident_profiles[0].launch_profile,)
            ),
        )
        resume = AgentControl(
            "resume",
            AgentControlKind.RESUME,
            "agent-a",
            "session",
            effect.config_revision,
            None,
            False,
            "qualified checks",
        )
        assert apply(c, resume).code == "applied"
        assert c._supervisor is not None and not c._drained
    finally:
        if external is not None:
            external.shutdown_for_test()
        c.close()
