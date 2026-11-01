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


def client(tmp_path, pair=None):
    old, new = pair or (config(tmp_path), config(tmp_path, 2))
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


@pytest.mark.parametrize("change", ["relocate", "writable", "qualification"])
def test_source_relocation_preserves_logical_roots_and_native_identity(tmp_path, change):
    import hashlib

    profiles = []
    for generation in (1, 2):
        root = tmp_path / f"project-{generation}"
        root.mkdir()
        marker = b"stable source collection" if change != "qualification" or generation == 1 else b"different collection"
        (root / ".identity").write_bytes(marker)
        # Source releases live inside a retained logical root. Relocation changes
        # its host path, not the challenge, access or container location.
        project = root / "releases" / str(generation)
        project.mkdir(parents=True)
        profile = config(tmp_path, generation)
        profiles.append(replace(profile, resident_profiles=(replace(
            profile.resident_profiles[0], project_root=project,
            shared_roots={"project": {
                "host_path": str(root), "container_path": "/loom/project",
                "access": "rw" if change == "writable" else "ro",
                "challenge": {"path": ".identity", "sha256": hashlib.sha256(marker).hexdigest()},
            }},
        ),)))
    c, old, new = client(tmp_path, profiles)
    original_id = c.agent_root_id
    assert old.agent_root is not None
    try:
        binding = old.agent_root / "role-binding.json"
        before = binding.read_bytes()
        control = request(old, new, original_id)
        if change != "relocate":
            with pytest.raises(QueueConflictError, match="shared root identity or writable"):
                apply(c, control)
            assert binding.read_bytes() == before
            return
        result = apply(c, control)
        assert result.code == "applied"
        assert c.agent_root_id == original_id
        assert c._config.resident_profiles[0].project_root == new.resident_profiles[0].project_root
        assert c._config.resident_profiles[0].descriptor.shared_roots == old.resident_profiles[0].descriptor.shared_roots
        assert c._require_journal().prepare_control(control) == result
    finally:
        close(c)


@pytest.mark.parametrize("transient_unknown", [False, True])
def test_promotion_replay_and_later_promotion_preserve_native_history(
    tmp_path, transient_unknown
):
    c, old, new = client(tmp_path)
    assert old.agent_root is not None and new.agent_root is not None
    root = c.agent_root_id
    first = request(old, new, root)
    assert first.promotion is not None
    try:
        secret = (old.agent_root / "supervisor" / "service.secret").read_bytes()
        from loom.queue._agent_process_supervisor import (
            ResidentWorkerLaunch, SupervisorLaunchState,
        )

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
        if transient_unknown:
            # A transient supervision failure can precede a drain. Containment
            # then settles the launch while the drained service stops offering.
            c._service_progress = True
            c._observe_supervisor_ownership(
                replace(supervisor.query(launch), state=SupervisorLaunchState.UNKNOWN)
            )
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
        c._require_journal().acknowledge_control(second.operation_id)
        session = c._require_journal().active_session()
        assert session is not None
        resume = AgentControl(
            "resume-promoted", AgentControlKind.RESUME, "agent-a",
            session.session_id, session.config_revision, None, False, "resume",
        )
        assert apply(c, resume).code == "applied"
        assert not c._drained
        if transient_unknown:
            # Replaying an older promotion cannot clear newer ownership doubt.
            supervisor = c._supervisor
            assert supervisor is not None
            workspace = tmp_path / "current"
            workspace.mkdir()
            current = ResidentWorkerLaunch(
                supervisor.supervisor_id, supervisor.continuity_epoch, root,
                "session", "new-assignment", "new-process", "new-fence", "new-launch",
                "b" * 64, workspace, third.resident_profiles[0].launch_profile, {},
            )
            supervisor.launch(current)
            c._observe_supervisor_ownership(
                replace(supervisor.query(current), state=SupervisorLaunchState.UNKNOWN)
            )
            assert promotion.apply(c, first) == effect
            assert c._restart_with_retained_work
            supervisor.contain(current)
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
@pytest.mark.parametrize("mode", [None, "retire_configuration", "add_container_policies", "increase_publication_budgets"])
def test_native_operator_authorization_gate_guards_and_wire_replay(owner, tmp_path, mode):  # noqa: F811
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
    if mode:
        control = replace(control, promotion={
            **{key: value for key, value in control.promotion.items()
               if key not in {"profile_id", "target_profile"}},
            mode: True,
        })
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    try:
        with CoordinatorOperatorClient.from_unix_socket(
            daemon.config.endpoint,
            expected_coordinator_id=daemon.status().coordinator_id,
        ) as wire:
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
        with CoordinatorOperatorClient.from_unix_socket(
            daemon.config.endpoint,
            expected_coordinator_id=daemon.status().coordinator_id,
        ) as wire:
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


def test_another_agent_promotion_requires_global_control_settlement(tmp_path):
    import os
    from loom.queue import LocalDaemon, LocalDaemonConfig
    from loom.queue.local_daemon import LocalDaemonPrincipal, LocalDaemonRole
    from loom.queue.agent_sessions import AgentControlEffect, AgentPolicyConfig, LocalOwnerOperatorPolicy
    from tests.integration.queue.test_agent_session_transport import _policy, _request

    policies = tuple(replace(_policy().agents[0], agent_id=name,
                             principal_id=name, credential_id=name) for name in ("agent-a", "agent-b"))
    policy = AgentPolicyConfig(agents=policies, local_owner=LocalOwnerOperatorPolicy(
        ("maintenance", "drain"), ("agent-a", "agent-b"), ("default",)))
    selected = LocalDaemonConfig(tmp_path / "coordinator", None, tmp_path / "runs", None,
                                 cpu_capacity=0, agent_policy=policy)
    LocalDaemon.initialize(selected)
    daemon = LocalDaemon(selected)
    daemon.start()
    try:
        operator = daemon.operator_view(LocalDaemonPrincipal(f"uid:{os.getuid()}", LocalDaemonRole.OPERATOR))
        operator.maintenance({"operation_id": "close", "maintenance_id": "upgrade",
                              "maintenance_intent_digest": "target", "action": "close",
                              "expected_revision": 0, "check": None},
                             expected_coordinator_id=daemon.status().coordinator_id)
        controls = []
        for name in ("agent-a", "agent-b"):
            agent = daemon.agent_view(LocalDaemonPrincipal(name, LocalDaemonRole.AGENT, name))
            session = agent.register(replace(_request(agent.handshake(), name + "-root"),
                                             idempotency_key="register-" + name,
                                             retirement_verifier="a" * 64))
            control = replace(request(config(tmp_path), config(tmp_path, 2), name + "-root",
                                      identity="promote-" + name, session=session.session_id,
                                      revision=session.config_revision), agent_id=name)
            drain = replace(control, operation_id="drain-" + name,
                            kind=AgentControlKind.DRAIN, promotion=None)
            operator.control_agent(drain)
            agent.next_control(session.session_id)
            agent.acknowledge_control(session.session_id, AgentControlEffect(
                drain.operation_id, "applied", session.config_revision, session.inventory_revision, "drained"))
            controls.append(control)
        accepted = operator.control_agent(controls[0])
        with pytest.raises(QueueConflictError, match="native settlement"):
            operator.control_agent(controls[1])
        assert operator.control_agent(controls[0]) == accepted
    finally:
        daemon.stop()


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


@pytest.mark.parametrize("boundary", ["before_delivery", "source_publication"])
def test_staged_source_keeps_predecessor_startable_and_recovers_native_publication(
    tmp_path, monkeypatch, boundary
):
    from types import SimpleNamespace
    from loom.queue import deployment

    c, old, new = client(tmp_path)
    canonical = tmp_path / "service-source.json"
    canonical.write_text("old-source")
    candidate = tmp_path / "candidate.json"
    candidate.write_text("target-source")
    control = request(old, new, c.agent_root_id)
    control = replace(
        control,
        promotion={**dict(control.promotion or {}), "candidate_source": str(candidate)},
    )
    source = {
        "path": str(canonical),
        "candidate": str(candidate),
        "environment": None,
        "before": "old-source",
        "after": "target-source",
    }
    c._trusted_promotion_loader = lambda _: (new, source)
    if boundary == "before_delivery":
        c.close()
        c = LocalDaemonAgentHttpClient(
            old,
            trusted_config_loader=lambda: new,
            trusted_promotion_loader=lambda _: (new, source),
        )
        assert canonical.read_text() == "old-source"
        assert apply(c, control).code == "applied"
    else:
        original = promotion.atomic_write_bytes

        def lost_reply(path, value):
            original(path, value)
            if path == canonical:
                raise RuntimeError("source-published")

        monkeypatch.setattr(promotion, "atomic_write_bytes", lost_reply)
        with pytest.raises(RuntimeError, match="source-published"):
            apply(c, control)
        c.close()
        monkeypatch.setattr(promotion, "atomic_write_bytes", original)
        monkeypatch.setattr(
            deployment,
            "load_outbound_agent_service_config",
            lambda *a, **k: SimpleNamespace(client=new),
        )
        c = LocalDaemonAgentHttpClient(old)
    try:
        assert canonical.read_text() == "target-source"
        assert c._config == new and c._drained
        assert new.agent_root is not None
        assert promotion.completed(new.agent_root, control.operation_id)
        assert promotion.apply(c, control).code == "applied"
    finally:
        close(c)


@pytest.mark.parametrize("change", ["add", "replace", "remove", "capacity"])
def test_quiescent_promotion_can_add_container_policy_without_rebinding_capacity(tmp_path, change):
    from loom.queue._remote_stage_execution import AgentResourceInventory
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted

    policy, _, _, _ = _submitted(tmp_path)
    old = replace(config(tmp_path), resource_inventory=AgentResourceInventory(2))
    if change in {"replace", "remove"}:
        old = replace(old, container_policies=(policy,))
    new = replace(old, container_policies=(policy,),
                  deployment_configuration_fingerprint="2" * 64,
                  active_configuration_fingerprint="5" * 64)
    if change == "replace":
        new = replace(new, container_policies=(replace(policy, environment={"CHANGED": "1"}),))
    elif change == "remove":
        new = replace(new, container_policies=())
    elif change == "capacity":
        new = replace(new, resource_inventory=AgentResourceInventory(3))
    c, old, new = client(tmp_path, (old, new))
    root = c.agent_root_id
    try:
        control = request(old, new, root)
        control = replace(control, promotion={**control.promotion, "enable_submitted_containers": True})
        if change != "add":
            with pytest.raises(QueueConflictError, match="unrelated role|container policies|requires a protected policy"):
                apply(c, control)
            assert c._config == old
            return
        effect = apply(c, control)
        assert effect.code == "applied"
        assert c.agent_root_id == root
        assert c._config.resource_inventory == old.resource_inventory
        assert c._config.resident_profiles == old.resident_profiles
        assert c._config.container_policies == (policy,)
        assert "submitted-container-execution-v1" in c.active_session().capabilities
        assert c._require_journal().prepare_control(control) == effect
        close(c)
        c = LocalDaemonAgentHttpClient(new)
        assert c.agent_root_id == root
        assert c._config.container_policies == (policy,)
    finally:
        close(c)


@pytest.mark.parametrize("owner", [("drain", "maintenance")], indirect=True)
@pytest.mark.parametrize("authorized", [True, False])
@pytest.mark.parametrize("effect_code", ["applied", "reload_rejected"])
def test_container_enablement_updates_coordinator_session_only_after_authorized_effect(owner, tmp_path, authorized, effect_code):  # noqa: F811
    from loom.queue.agent_sessions import AgentControlEffect
    from loom.queue.submitted_execution import SUBMITTED_CONTAINER_CAPABILITY

    daemon, agent, session, operator = owner
    if authorized:
        policy = daemon.config.agent_policy
        rule = policy.agents[0]
        daemon.replace_agent_policy(replace(policy, agents=(replace(
            rule, capabilities=(*rule.capabilities, SUBMITTED_CONTAINER_CAPABILITY)),)))
    old, new = config(tmp_path), config(tmp_path, 2)
    control = request(old, new, "remote-root", session=session.session_id, revision=session.config_revision)
    control = replace(control, promotion={**control.promotion, "enable_submitted_containers": True})
    operator.maintenance({"operation_id":"enable-close", "maintenance_id":"upgrade",
        "maintenance_intent_digest":"target", "action":"close", "expected_revision":0, "check":None},
        expected_coordinator_id=daemon.status().coordinator_id)
    drain = replace(control, operation_id="enable-drain", kind=AgentControlKind.DRAIN, promotion=None)
    operator.control_agent(drain)
    agent.next_control(session.session_id)
    agent.acknowledge_control(session.session_id, AgentControlEffect(
        drain.operation_id,"applied",session.config_revision,session.inventory_revision,"drained"))
    if not authorized:
        with pytest.raises(QueueConflictError, match="not authorized"):
            operator.control_agent(control)
        return
    operator.control_agent(control)
    delivered=agent.next_control(session.session_id)
    assert delivered == control
    effect=AgentControlEffect(control.operation_id,effect_code,session.config_revision,session.inventory_revision,"drained")
    agent.acknowledge_control(session.session_id,effect)
    agent.acknowledge_control(session.session_id,effect)
    expected = replace(session, availability_revision="drained", capabilities=(
        tuple(sorted({*session.capabilities, SUBMITTED_CONTAINER_CAPABILITY}))
        if effect_code == "applied" else session.capabilities))
    current=agent.reconcile(expected,session.coordinator_epoch,idempotency_key="enabled-session")
    assert (SUBMITTED_CONTAINER_CAPABILITY in current.capabilities) == (effect_code == "applied")


@pytest.mark.parametrize("interrupted", [False, True])
def test_retirement_preserves_native_owner_and_recovers_container_only_target(tmp_path, monkeypatch, interrupted):
    from loom.queue._remote_stage_execution import AgentResourceInventory
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted

    policy, _, _, _ = _submitted(tmp_path)
    obsolete = {**dict(policy.shared_roots["workloads"]), "host_path": str(tmp_path / "deleted-data")}
    previous_policy = replace(policy, shared_roots={**policy.shared_roots, "obsolete": obsolete})
    old = replace(config(tmp_path), resource_inventory=AgentResourceInventory(2),
                  container_policies=(previous_policy, replace(previous_policy, policy_id="unused")))
    new = replace(old, resident_profiles=(), container_policies=(policy,),
                  deployment_configuration_fingerprint="2" * 64,
                  active_configuration_fingerprint="5" * 64)
    c, old, new = client(tmp_path, (old, new))
    root_id = c.agent_root_id
    control = request(old, old, root_id)
    control = replace(control, promotion={
        **{key: value for key, value in control.promotion.items()
           if key not in {"profile_id", "target_profile", "target_immutable", "target_active"}},
        "retire_configuration": True,
        "target_immutable": new.deployment_configuration_fingerprint,
        "target_active": new.active_configuration_fingerprint,
    })
    try:
        secret = (old.agent_root / "supervisor/service.secret").read_bytes()
        if interrupted:
            finish = promotion._finish
            monkeypatch.setattr(promotion, "_finish", lambda *args: (_ for _ in ()).throw(RuntimeError("interrupted")))
            with pytest.raises(RuntimeError, match="interrupted"):
                apply(c, control)
            c.close()
            monkeypatch.setattr(promotion, "_finish", finish)
            c = LocalDaemonAgentHttpClient(new)
        else:
            assert apply(c, control).code == "applied"
        assert c._config == new and c._drained
        assert c.agent_root_id == root_id
        assert c._config.resource_inventory == old.resource_inventory
        assert (old.agent_root / "supervisor/service.secret").read_bytes() == secret
        assert c._require_journal().replayed_control_effect(control).code == "applied"
        assert not (tmp_path / "deleted-data").exists()
        close(c)
        c = LocalDaemonAgentHttpClient(new)
        assert c.agent_root_id == root_id and c._config.container_policies == (policy,)
        assert promotion.apply(c, control).code == "applied"
    finally:
        close(c)


@pytest.mark.parametrize("change", ["capacity", "transport", "root-identity", "new-policy"])
def test_retirement_rejects_unrelated_identity_changes(tmp_path, change):
    from loom.queue._remote_stage_execution import AgentResourceInventory
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted

    policy, _, _, _ = _submitted(tmp_path)
    old = replace(config(tmp_path), resource_inventory=AgentResourceInventory(2), container_policies=(policy,))
    new = replace(old, resident_profiles=())
    if change == "capacity":
        new = replace(new, resource_inventory=AgentResourceInventory(3))
    elif change == "transport":
        new = replace(new, url="https://another-host")
    elif change == "new-policy":
        new = replace(new, container_policies=(replace(policy, policy_id="replacement-name"),))
    else:
        roots = dict(policy.shared_roots)
        roots["workloads"] = {**dict(roots["workloads"]), "container_path": "/loom/changed"}
        new = replace(new, container_policies=(replace(policy, shared_roots=roots),))
    with pytest.raises(QueueConflictError):
        promotion.validate_candidate(old, new, None, retire_configuration=True)


@pytest.mark.parametrize("failure", [None, "source_conflict", "missing_target", "candidate_root"])
def test_retirement_recovers_authored_source_before_loading_deleted_predecessor(tmp_path, monkeypatch, failure):
    import json
    from tests.unit.loom.queue.test_deployment import _agent_config, _write_protected
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted
    from loom.queue.deployment import load_outbound_agent_service_config, read_agent_spec
    from loom.queue.errors import QueueError

    policy, _, _, _ = _submitted(tmp_path)
    canonical = _agent_config(tmp_path)
    before = json.loads(canonical.read_text())
    before["resident_profiles"][0]["descriptor"]["profile_id"] = "work"
    before["resources"] = {"cpu_capacity": 1, "memory_capacity_bytes": 0,
                           "gpu": {"provider": "nvidia", "devices": "none"}}
    old_data = tmp_path / "obsolete-data"
    old_data.mkdir()
    (old_data / "challenge").write_bytes(b"images")
    old_policy = policy.to_dict()
    old_policy["shared_roots"]["obsolete"] = {
        **old_policy["shared_roots"]["workloads"], "host_path": str(old_data),
    }
    before["container_policies"] = [old_policy]
    _write_protected(canonical, before)
    after = {**before, "resident_profiles": [], "container_policies": [policy.to_dict()]}
    candidate = _write_protected(tmp_path / "candidate.json", after)
    old_service = load_outbound_agent_service_config(canonical)
    new_service = load_outbound_agent_service_config(candidate)
    c, old, new = client(tmp_path, (old_service.client, new_service.client))
    control = request(old, old, c.agent_root_id)
    control = replace(control, promotion={
        **{key: value for key, value in control.promotion.items()
           if key not in {"profile_id", "target_profile", "target_immutable", "target_active"}},
        "retire_configuration": True, "candidate_source": str(candidate),
        "target_immutable": new.deployment_configuration_fingerprint,
        "target_active": new.active_configuration_fingerprint,
    })
    original = canonical.read_text()
    source = {"path": str(canonical), "candidate": str(candidate), "environment": None,
              "before": original, "after": candidate.read_text()}
    c._trusted_promotion_loader = lambda _: (new, source)
    finish = promotion._finish
    monkeypatch.setattr(promotion, "_finish", lambda *args: (_ for _ in ()).throw(RuntimeError("interrupted")))
    try:
        with pytest.raises(RuntimeError, match="interrupted"):
            apply(c, control)
    finally:
        c.close()
    monkeypatch.setattr(promotion, "_finish", finish)
    (old_data / "challenge").unlink()
    old_data.rmdir()
    with pytest.raises(QueueError):
        load_outbound_agent_service_config(canonical)
    if failure == "source_conflict":
        _write_protected(canonical, {**before, "reconnect_seconds": 0.3})
    elif failure == "missing_target":
        (tmp_path / "workloads" / "challenge").unlink()
    elif failure == "candidate_root":
        _write_protected(candidate, {**after, "agent_root": "different-agent"})
    current = canonical.read_bytes()
    spec = read_agent_spec(canonical)
    if failure:
        with pytest.raises(QueueError):
            promotion.recover(spec)
        assert canonical.read_bytes() == current
        assert promotion.publication_state(spec.agent_root, control.operation_id) == "pending"
    else:
        from argparse import Namespace
        from loom.cli import queue as cli
        from loom.queue import deployment

        started = []
        monkeypatch.setattr(cli, "_emit_daemon_payload", lambda *args, **kwargs: None)
        monkeypatch.setattr(deployment, "run_outbound_agent_service",
                            lambda service, **kwargs: started.append(service))
        assert cli.handle_agent_serve(Namespace(config=str(canonical), env_file=None)) == 0
        assert len(started) == 1
        recovered = started[0].client
        assert recovered.deployment_configuration_fingerprint == new.deployment_configuration_fingerprint
        assert canonical.read_text() == source["after"]
        assert promotion.completed(spec.agent_root, control.operation_id)
        service = load_outbound_agent_service_config(canonical)
        restarted = LocalDaemonAgentHttpClient(service.client)
        try:
            assert restarted.agent_root_id == control.promotion["agent_root_id"]
            assert restarted._drained and not restarted._config.resident_profiles
            assert promotion.apply(restarted, control).code == "applied"
        finally:
            close(restarted)
    assert not old_data.exists()


@pytest.mark.parametrize("interrupted", [False, True])
def test_stopped_retirement_uses_received_control_with_deleted_inputs(tmp_path, monkeypatch, interrupted):
    import json
    from tests.unit.loom.queue.test_deployment import _agent_config, _write_protected
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted
    from loom.queue.deployment import load_outbound_agent_service_config, read_agent_spec
    from loom.queue.errors import QueueError

    policy, _, _, _ = _submitted(tmp_path)
    canonical = _agent_config(tmp_path)
    before = json.loads(canonical.read_text())
    before["resident_profiles"][0]["descriptor"]["profile_id"] = "work"
    before["resources"] = {"cpu_capacity": 1, "memory_capacity_bytes": 0,
                           "gpu": {"provider": "nvidia", "devices": "none"}}
    obsolete = tmp_path / "obsolete-data"
    obsolete.mkdir()
    (obsolete / "challenge").write_bytes(b"images")
    old_policy = policy.to_dict()
    old_policy["shared_roots"]["obsolete"] = {
        **old_policy["shared_roots"]["workloads"], "host_path": str(obsolete),
    }
    before["container_policies"] = [old_policy]
    _write_protected(canonical, before)
    candidate = _write_protected(tmp_path / "candidate.json",
        {**before, "resident_profiles": [], "container_policies": [policy.to_dict()]})
    old_service = load_outbound_agent_service_config(canonical)
    new_service = load_outbound_agent_service_config(candidate)
    c, old, new = client(tmp_path, (old_service.client, new_service.client))
    control = request(old, old, c.agent_root_id)
    control = replace(control, promotion={
        **{key: value for key, value in control.promotion.items()
           if key not in {"profile_id", "target_profile", "target_immutable", "target_active"}},
        "retire_configuration": True, "candidate_source": str(candidate),
        "target_immutable": new.deployment_configuration_fingerprint,
        "target_active": new.active_configuration_fingerprint,
    })
    c._require_journal().retain_control(control)
    assert c._require_journal().prepare_control(control) is None
    close(c)
    secret = (old.agent_root / "supervisor/service.secret").read_bytes()
    (obsolete / "challenge").unlink()
    obsolete.rmdir()
    with pytest.raises(QueueError):
        load_outbound_agent_service_config(canonical)
    spec = read_agent_spec(canonical)
    with pytest.raises(QueueConflictError, match="delivery or native predecessor"):
        promotion.apply_stopped(spec, replace(control, operation_id="undelivered"))
    original = canonical.read_bytes()
    if interrupted:
        finish = promotion._finish
        monkeypatch.setattr(promotion, "_finish", lambda *args: (_ for _ in ()).throw(RuntimeError("interrupted")))
        with pytest.raises(RuntimeError, match="interrupted"):
            promotion.apply_stopped(spec, control)
        assert canonical.read_bytes() == original
        monkeypatch.setattr(promotion, "_finish", finish)
    effect = promotion.apply_stopped(spec, control)
    assert effect.code == "applied"
    assert not obsolete.exists()
    assert (old.agent_root / "supervisor/service.secret").read_bytes() == secret
    accepted = load_outbound_agent_service_config(canonical)
    restarted = LocalDaemonAgentHttpClient(accepted.client)
    try:
        assert restarted.agent_root_id == control.promotion["agent_root_id"]
        assert restarted._drained and not restarted._config.resident_profiles
        assert restarted._require_journal().replayed_control_effect(control) == effect
    finally:
        close(restarted)
    assert promotion.apply_stopped(read_agent_spec(canonical), control) == effect


@pytest.mark.parametrize("interrupted", [False, True])
def test_policy_addition_preserves_native_owner_and_recovers_container_only_target(tmp_path, monkeypatch, interrupted):
    from loom.queue._remote_stage_execution import AgentResourceInventory
    from loom.queue.submitted_execution import INPUT_DIRECTORY_WORKER_CONTRACT
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted

    policy, _, _, _ = _submitted(tmp_path)
    old = replace(config(tmp_path), resident_profiles=(), resource_inventory=AgentResourceInventory(2),
                  container_policies=(policy,))
    dataset = tmp_path / "new-dataset"
    dataset.mkdir()
    added = replace(policy, policy_id="new-dataset", worker_contracts=(INPUT_DIRECTORY_WORKER_CONTRACT,),
                    shared_roots={**policy.shared_roots, "input": {
                        "host_path": str(dataset), "container_path": "/loom/inputs/new-dataset", "access": "ro",
                        "qualification": {"kind": "input_directory"}}})
    assert added.qualify() == added.capability
    new = replace(old, container_policies=(policy, added),
                  deployment_configuration_fingerprint="2" * 64,
                  active_configuration_fingerprint="5" * 64)
    c, old, new = client(tmp_path, (old, new))
    root_id = c.agent_root_id
    control = request(old, config(tmp_path), root_id)
    control = replace(control, promotion={
        **{key: value for key, value in control.promotion.items()
           if key not in {"profile_id", "target_profile", "target_immutable", "target_active"}},
        "add_container_policies": True,
        "target_immutable": new.deployment_configuration_fingerprint,
        "target_active": new.active_configuration_fingerprint,
    })
    try:
        secret = (old.agent_root / "supervisor/service.secret").read_bytes()
        if interrupted:
            finish = promotion._finish
            monkeypatch.setattr(promotion, "_finish", lambda *args: (_ for _ in ()).throw(RuntimeError("interrupted")))
            with pytest.raises(RuntimeError, match="interrupted"):
                apply(c, control)
            c.close()
            monkeypatch.setattr(promotion, "_finish", finish)
            c = LocalDaemonAgentHttpClient(new)
        else:
            assert apply(c, control).code == "applied"
        assert c._config == new and c._drained
        assert c.agent_root_id == root_id
        assert c._config.resource_inventory == old.resource_inventory
        assert (old.agent_root / "supervisor/service.secret").read_bytes() == secret
        assert c._require_journal().replayed_control_effect(control).code == "applied"
        close(c)
        c = LocalDaemonAgentHttpClient(new)
        assert c.agent_root_id == root_id and c._config.container_policies == new.container_policies
        assert promotion.apply(c, control).code == "applied"
    finally:
        close(c)
