"""Publication policy changes retain native ownership and exact maintenance intent."""

from dataclasses import replace
import hashlib

import pytest

from loom.queue import LocalDaemon
from loom.queue import _profile_promotion as promotion
from loom.queue._publication_budget_increase import validate_coordinator, validate_roots
from loom.queue._remote_stage_execution import AgentResourceInventory
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.local_daemon import CoordinatorSchedulingReload
from loom.serialization import thaw_plain_data
from tests.integration.queue.test_agent_profile_promotion import config, client, request, apply, close
from tests.integration.queue.test_maintenance_admission import service, change, operator
from tests.unit.loom.queue.test_submitted_container_policy import _submitted

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]

LIMITS = {"max_members": 10_000, "max_manifest_bytes": 1_048_576, "max_payload_bytes": 4_294_967_296}
INCREASED = {"max_members": 1_000_000, "max_manifest_bytes": 536_870_912, "max_payload_bytes": 274_877_906_944}


def policies(tmp_path):
    policy, _, _, _ = _submitted(tmp_path)
    root = tmp_path / "published"
    root.mkdir()
    (root / "challenge").write_bytes(b"publication root")
    old = replace(policy, shared_roots={**policy.shared_roots, "runs": {
        "host_path": str(root), "container_path": "/loom/runs", "access": "rw",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"publication root").hexdigest()},
        "publication": LIMITS,
    }})
    roots = thaw_plain_data(old.shared_roots)
    roots["runs"]["publication"] = INCREASED
    return old, replace(old, shared_roots=roots)


def coordinators(tmp_path):
    from loom.queue._preparation_policy import SubmittedPreparationProfile
    selected = service(tmp_path, local=False).daemon
    old, new = policies(tmp_path)
    preparation = selected.preparation_policy
    installed = preparation.profiles["existing-project"]
    policy = replace(selected.agent_policy, local_owner=replace(
        selected.agent_policy.local_owner, actions=("maintenance", "scheduling_reload")))

    def configured(container, fingerprint):
        profile = SubmittedPreparationProfile(
            container.capability, installed.allowed_source_roots, ("shared",),
            installed.runtime_options,
            {"capability": "shared-execution-v1", "roots": container.capability.workload_roots, "locations": []},
            {"workloads": container.shared_roots["workloads"]},
        )
        return replace(selected, agent_policy=policy,
            agent_root=None, resident_worker_launch_profile=None,
            cpu_capacity=0, memory_capacity_bytes=0, gpu_devices=(), agent_resource_providers=(),
            shared_roots=container.shared_roots, container_capabilities=(container.capability,),
            preparation_policy=replace(preparation, profiles={"submitted": profile}),
            active_configuration_fingerprint=fingerprint)

    return configured(old, "1" * 64), configured(new, "2" * 64)


@pytest.mark.parametrize("key", list(LIMITS))
def test_budget_update_refuses_any_decrease(tmp_path, key):
    old, new = policies(tmp_path)
    validate_roots(old.shared_roots, new.shared_roots)
    roots = thaw_plain_data(new.shared_roots)
    roots["runs"]["publication"][key] = LIMITS[key] - 1
    with pytest.raises(QueueConflictError, match="only increase"):
        validate_roots(old.shared_roots, roots)


@pytest.mark.parametrize("mutation", ["alias", "host_path", "container_path", "challenge", "capacity", "environment", "policy"])
def test_agent_budget_update_preserves_roots_permissions_and_execution(tmp_path, mutation):
    old_policy, new_policy = policies(tmp_path)
    old = replace(config(tmp_path), resident_profiles=(), resource_inventory=AgentResourceInventory(2), container_policies=(old_policy,))
    new = replace(old, container_policies=(new_policy,))
    promotion.validate_candidate(old, new, None, increase_publication_budgets=True)
    if mutation == "capacity":
        new = replace(new, resource_inventory=AgentResourceInventory(3))
    elif mutation == "environment":
        new = replace(new, container_policies=(replace(new_policy, environment={"CHANGED": "yes"}),))
    elif mutation == "policy":
        new = replace(new, container_policies=(replace(new_policy, policy_id="another"),))
    else:
        roots = thaw_plain_data(new_policy.shared_roots)
        if mutation == "alias":
            roots["renamed"] = roots.pop("runs")
        elif mutation == "challenge":
            roots["runs"]["challenge"]["sha256"] = "0" * 64
        else:
            roots["runs"][mutation] += "-changed"
        new = replace(new, container_policies=(replace(new_policy, shared_roots=roots),))
    with pytest.raises(QueueConflictError):
        promotion.validate_candidate(old, new, None, increase_publication_budgets=True)


@pytest.mark.parametrize("mutation", [None, "mismatch", "source", "alias", "locations", "scheduling"])
def test_coordinator_budget_update_preserves_preparation_and_matching_limits(tmp_path, mutation):
    old, new = coordinators(tmp_path)
    if mutation == "mismatch":
        new = replace(new, container_capabilities=old.container_capabilities)
    elif mutation == "source":
        new = replace(new, preparation_policy=replace(new.preparation_policy, source_roots={}))
    elif mutation == "alias":
        new = replace(new, preparation_policy=replace(new.preparation_policy, profiles={}))
    elif mutation == "locations":
        profile = new.preparation_policy.profiles["submitted"]
        new = replace(new, preparation_policy=replace(new.preparation_policy, profiles={
            "submitted": replace(profile, shared_scope={**profile.shared_scope, "locations": [{
                "kind": "loom.shared-location", "schema_version": 1, "root_id": "data", "path": "."}]})}))
    elif mutation == "scheduling":
        new = replace(new, poll_interval_seconds=old.poll_interval_seconds + 1)
    if mutation is None:
        validate_coordinator(old, new)
    else:
        with pytest.raises(QueueConflictError):
            validate_coordinator(old, new)


def test_budget_update_is_an_explicit_exclusive_wire_intent():
    binding = {"maintenance_id": "increase", "maintenance_intent_digest": "exact", "expected_gate_revision": 1}
    value = CoordinatorSchedulingReload("increase", "epoch", "raise ceilings", publication_budget_increase=binding)
    assert CoordinatorSchedulingReload.from_dict(value.to_dict()) == value
    for name in ("retirement", "container_policy_addition"):
        with pytest.raises(QueueServiceError, match="mutually exclusive"):
            replace(value, **{name: binding})


@pytest.mark.parametrize("interrupted", [False, True])
def test_budget_promotion_recovers_same_agent_and_exact_control(tmp_path, monkeypatch, interrupted):
    old_policy, new_policy = policies(tmp_path)
    old = replace(config(tmp_path), resident_profiles=(), resource_inventory=AgentResourceInventory(2), container_policies=(old_policy,))
    new = replace(old, container_policies=(new_policy,), deployment_configuration_fingerprint="2" * 64,
                  active_configuration_fingerprint="5" * 64)
    agent, old, new = client(tmp_path, (old, new))
    root_id = agent.agent_root_id
    control = request(old, config(tmp_path), root_id)
    control = replace(control, promotion={
        **{key: value for key, value in control.promotion.items()
           if key not in {"profile_id", "target_profile", "target_immutable", "target_active"}},
        "increase_publication_budgets": True,
        "target_immutable": new.deployment_configuration_fingerprint,
        "target_active": new.active_configuration_fingerprint,
    })
    try:
        secret = (old.agent_root / "supervisor/service.secret").read_bytes()
        if interrupted:
            finish = promotion._finish
            monkeypatch.setattr(promotion, "_finish", lambda *args: (_ for _ in ()).throw(RuntimeError("interrupted")))
            with pytest.raises(RuntimeError, match="interrupted"):
                apply(agent, control)
            agent.close()
            monkeypatch.setattr(promotion, "_finish", finish)
            agent = LocalDaemonAgentHttpClient(new)
        else:
            assert apply(agent, control).code == "applied"
        assert agent._config == new and agent._drained
        assert agent.agent_root_id == root_id
        assert (old.agent_root / "supervisor/service.secret").read_bytes() == secret
        assert promotion.apply(agent, control).code == "applied"
    finally:
        close(agent)


@pytest.mark.parametrize("interrupted", [False, True])
def test_coordinator_budget_reload_requires_exact_settled_gate_and_recovers(tmp_path, monkeypatch, interrupted):
    old, new = coordinators(tmp_path)
    LocalDaemon.initialize_deployment(old)
    daemon = LocalDaemon(old, trusted_scheduling_loader=lambda: new)
    before = daemon.start()
    try:
        change(daemon, "close")
        gate = operator(daemon).observe_maintenance()
        binding = {"maintenance_id": gate["maintenance_id"], "maintenance_intent_digest": gate["intent_digest"],
                   "expected_gate_revision": gate["revision"]}
        reload = CoordinatorSchedulingReload("increase", before.scheduling_epoch, "raise ceilings", publication_budget_increase=binding)
        with pytest.raises(QueueConflictError, match="maintenance"):
            daemon._validate_scheduling_replacement(new, publication_budget_increase={**binding, "expected_gate_revision": 0})
        if interrupted:
            retain = daemon._record_scheduling_reload_intent
            def stop(**kwargs):
                retain(**kwargs)
                raise SystemExit("interrupted")
            monkeypatch.setattr(daemon, "_record_scheduling_reload_intent", stop)
            with pytest.raises(SystemExit, match="interrupted"):
                operator(daemon).reload_scheduling(reload)
        else:
            assert operator(daemon).reload_scheduling(reload)["state"] == "applied"
    finally:
        daemon.stop()
    restarted = LocalDaemon(new)
    restarted.start()
    try:
        assert restarted.status().coordinator_id == before.coordinator_id
        assert operator(restarted).reload_scheduling(reload)["state"] == "applied"
        assert operator(restarted).observe_maintenance()["state"] == "closed"
        assert restarted.config.coordinator_shared_roots["runs"]["publication"] == INCREASED
        with pytest.raises(QueueConflictError, match="conflicts"):
            operator(restarted).reload_scheduling(replace(reload, reason="different intent"))
    finally:
        restarted.stop()
