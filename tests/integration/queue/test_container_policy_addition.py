"""Additive maintenance cannot redirect retained execution selections."""

from dataclasses import replace

import pytest

from loom.queue._container_policy_addition import validate_coordinator
from loom.queue._profile_promotion import validate_candidate
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.local_daemon import CoordinatorSchedulingReload
from tests.integration.queue.test_agent_profile_promotion import config
from tests.unit.loom.queue.test_submitted_container_policy import _submitted

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("change", ["remove", "rebind", "capacity", "resident"])
def test_agent_additions_preserve_retained_policies_and_resources(tmp_path, change):
    from loom.queue._remote_stage_execution import AgentResourceInventory

    policy, _, _, _ = _submitted(tmp_path)
    old = replace(config(tmp_path), resident_profiles=(),
                  resource_inventory=AgentResourceInventory(2), container_policies=(policy,))
    new = replace(old, container_policies=(policy, replace(policy, policy_id="new")))
    validate_candidate(old, new, None, add_container_policies=True)
    if change == "remove":
        new = replace(new, container_policies=new.container_policies[1:])
    elif change == "rebind":
        new = replace(new, container_policies=(replace(policy, environment={"DATA": "/other"}), new.container_policies[1]))
    elif change == "capacity":
        new = replace(new, resource_inventory=AgentResourceInventory(3))
    else:
        new = replace(new, resident_profiles=config(tmp_path).resident_profiles)
    with pytest.raises(QueueConflictError):
        validate_candidate(old, new, None, add_container_policies=True)


@pytest.mark.parametrize("change", [None, "capability", "preparation", "sources", "roots", "scheduling"])
def test_coordinator_additions_preserve_existing_selections(tmp_path, change):
    from loom.queue._preparation_policy import SubmittedPreparationProfile
    from tests.integration.queue.test_maintenance_admission import service

    selected = service(tmp_path, local=False)
    policy, _, _, _ = _submitted(tmp_path)
    preparation = selected.daemon.preparation_policy
    installed = preparation.profiles["existing-project"]
    profile = SubmittedPreparationProfile(
        policy.capability, installed.allowed_source_roots, ("shared",),
        installed.runtime_options,
        {"capability": "shared-execution-v1", "roots": policy.capability.workload_roots, "locations": []},
        policy.shared_roots,
    )
    before = replace(selected.daemon, agent_root=None, resident_worker_launch_profile=None,
        cpu_capacity=0, memory_capacity_bytes=0, gpu_devices=(), agent_resource_providers=(),
        shared_roots=policy.shared_roots,
        container_capabilities=(policy.capability,),
        preparation_policy=replace(preparation, profiles={"submitted": profile}))
    added = replace(policy.capability, policy_id="new")
    after = replace(before, container_capabilities=(policy.capability, added),
        preparation_policy=replace(before.preparation_policy,
            profiles={"submitted": profile, "new": replace(profile, capability=added)}))
    if change == "capability":
        after = replace(after, container_capabilities=(added,))
    elif change == "preparation":
        after = replace(after, preparation_policy=replace(after.preparation_policy,
            profiles={"submitted": replace(profile, capability=added)}))
    elif change == "sources":
        after = replace(after, preparation_policy=replace(after.preparation_policy, source_roots={}))
    elif change == "roots":
        after = replace(after, shared_roots={})
    elif change == "scheduling":
        after = replace(after, poll_interval_seconds=before.poll_interval_seconds + 1)
    if change is None:
        validate_coordinator(before, after)
    else:
        with pytest.raises(QueueConflictError):
            validate_coordinator(before, after)


def test_policy_addition_wire_binding_is_explicit_and_excludes_retirement():
    binding = {"maintenance_id": "add", "maintenance_intent_digest": "intent", "expected_gate_revision": 1}
    request = CoordinatorSchedulingReload("add", "epoch", "selected policies", container_policy_addition=binding)
    assert CoordinatorSchedulingReload.from_dict(request.to_dict()) == request
    assert "retirement" not in request.to_dict()
    with pytest.raises(QueueServiceError, match="mutually exclusive"):
        replace(request, retirement=binding)


@pytest.mark.parametrize("change", ["extend", "host_rebind", "permissions", "legacy"])
def test_selected_catalog_extension_preserves_retained_authority(tmp_path, change):
    from loom.queue._container_policy_addition import validate_coordinator_declarations
    from loom.queue._preparation_policy import SubmittedPreparationProfile
    from loom.queue._remote_stage_execution import AgentResourceInventory
    from loom.queue.submitted_execution import SELECTED_INPUT_WORKER_CONTRACT
    from tests.integration.queue.test_maintenance_admission import service

    policy, _, _, _ = _submitted(tmp_path)
    if change != "legacy":
        policy = replace(policy, worker_contracts=(SELECTED_INPUT_WORKER_CONTRACT,))
    alias, root = next((key, value) for key, value in policy.shared_roots.items()
                      if value["container_path"] is not None and value["access"] == "ro")
    roots = {**policy.shared_roots, "additional": {**root, "container_path": "/loom/additional"}}
    if change == "host_rebind":
        roots[alias] = {**root, "host_path": str(tmp_path / "different")}
    updated = replace(policy, shared_roots=roots,
                      environment={"CHANGED": "1"} if change == "permissions" else policy.environment)
    old_agent = replace(config(tmp_path), resident_profiles=(),
        resource_inventory=AgentResourceInventory(2), container_policies=(policy,))
    new_agent = replace(old_agent, container_policies=(updated,))
    if change == "extend":
        validate_candidate(old_agent, new_agent, None, add_container_policies=True)
    else:
        with pytest.raises(QueueConflictError):
            validate_candidate(old_agent, new_agent, None, add_container_policies=True)
    if change == "host_rebind":
        return

    selected = service(tmp_path, local=False)
    preparation = selected.daemon.preparation_policy
    installed = preparation.profiles["existing-project"]
    profile = SubmittedPreparationProfile(policy.capability, installed.allowed_source_roots,
        ("shared",), installed.runtime_options,
        {"capability": "shared-execution-v1", "roots": policy.capability.workload_roots, "locations": []},
        policy.shared_roots)
    before = replace(selected.daemon, agent_root=None, resident_worker_launch_profile=None,
        cpu_capacity=0, memory_capacity_bytes=0, gpu_devices=(), agent_resource_providers=(),
        shared_roots=policy.shared_roots, container_capabilities=(policy.capability,),
        preparation_policy=replace(preparation, profiles={"selected": profile}))
    expanded = replace(profile, capability=updated.capability, image_roots=updated.shared_roots,
        shared_scope={**profile.shared_scope, "roots": updated.capability.workload_roots})
    after = replace(before, shared_roots=updated.shared_roots,
        container_capabilities=(updated.capability,),
        preparation_policy=replace(preparation, profiles={"selected": expanded}))
    old = {"shared_roots": dict(policy.shared_roots), "container_capabilities": [policy.capability.to_dict()]}
    new = {"shared_roots": dict(updated.shared_roots), "container_capabilities": [updated.capability.to_dict()]}
    if change == "extend":
        validate_coordinator(before, after)
        validate_coordinator_declarations(old, new)
        # A catalog extension cannot grant an extra static preparation mount.
        widened = replace(expanded, shared_scope={**expanded.shared_scope, "locations": [
            {"kind": "loom.shared-location", "schema_version": 1, "root_id": "additional", "path": "."}]})
        with pytest.raises(QueueConflictError, match="preparation selection"):
            validate_coordinator(before, replace(after,
                preparation_policy=replace(after.preparation_policy, profiles={"selected": widened})))
    else:
        with pytest.raises(QueueConflictError):
            validate_coordinator(before, after)
        with pytest.raises(QueueConflictError):
            validate_coordinator_declarations(old, new)
