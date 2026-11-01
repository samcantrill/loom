"""Add qualified container policy identities without rebinding retained work.

The existing promotion and scheduling journals own activation and recovery.
These constraints permit additions only; retirement remains a separate action.
"""

from dataclasses import fields, replace

from .errors import QueueConflictError

CAPABILITY = "quiescent-container-policy-addition-v1"


def preserve(before, after, label):
    """Require every retained mapping entry to keep its exact meaning."""
    if any(after.get(key) != value for key, value in before.items()):
        raise QueueConflictError("container policy addition cannot remove or change " + label)


def _preserve_capabilities(before, after):
    from .submitted_execution import SELECTED_INPUT_WORKER_CONTRACT

    for key, previous in before.items():
        current = after.get(key)
        if current == previous:
            continue
        if (current is None or previous.worker_contracts != (SELECTED_INPUT_WORKER_CONTRACT,)
            or not current.permits(previous)):
            raise QueueConflictError("container policy addition cannot change retained container capabilities")


def _preserve_profiles(before, after):
    from ._preparation_policy import SubmittedPreparationProfile

    for key, previous in before.items():
        current = after.get(key)
        if current == previous:
            continue
        if not isinstance(previous, SubmittedPreparationProfile) or not isinstance(current, SubmittedPreparationProfile):
            raise QueueConflictError("container policy addition cannot change preparation profiles")
        _preserve_capabilities({key: previous.capability}, {key: current.capability})
        # Expanding the authorized catalog must not add static preparation reads.
        if (replace(current, capability=previous.capability, shared_scope=previous.shared_scope,
                    image_roots=previous.image_roots) != previous
            or {k: v for k, v in current.shared_scope.items() if k != "roots"}
            != {k: v for k, v in previous.shared_scope.items() if k != "roots"}):
            raise QueueConflictError("container policy addition cannot change preparation selection")
        preserve(previous.shared_scope["roots"], current.shared_scope["roots"], "preparation roots")
        preserve(previous.image_roots, current.image_roots, "preparation image roots")


def validate_agent(previous, replacement):
    if previous.resource_inventory is None or not previous.container_policies:
        raise QueueConflictError("container policy addition requires existing policies and explicit resources")
    if previous.resident_profiles != replacement.resident_profiles:
        raise QueueConflictError("container policy addition cannot change resident profiles")
    from .submitted_execution import SELECTED_INPUT_WORKER_CONTRACT

    policies = {policy.policy_id: policy for policy in replacement.container_policies}
    for policy in previous.container_policies:
        current = policies.get(policy.policy_id)
        if current == policy:
            continue
        if (current is None or policy.worker_contracts != (SELECTED_INPUT_WORKER_CONTRACT,)
            or replace(current, shared_roots=policy.shared_roots) != policy):
            raise QueueConflictError("container policy addition cannot change retained container policies")
        preserve(policy.shared_roots, current.shared_roots, "retained container roots")


def validate_coordinator(previous, replacement):
    from ._preparation_policy import SubmittedPreparationProfile

    mutable = {"shared_roots", "preparation_policy", "container_capabilities",
               "active_configuration_fingerprint"}
    if previous.agent_root is not None or any(
        getattr(previous, item.name) != getattr(replacement, item.name)
        for item in fields(previous) if item.name not in mutable
    ):
        raise QueueConflictError("container policy addition cannot change unrelated coordinator configuration")
    preserve(previous.coordinator_shared_roots, replacement.coordinator_shared_roots, "shared roots")
    _preserve_capabilities({item.policy_id: item for item in previous.container_capabilities},
                          {item.policy_id: item for item in replacement.container_capabilities})
    old, new = previous.preparation_policy, replacement.preparation_policy
    if old is None or new is None or old.source_roots != new.source_roots:
        raise QueueConflictError("container policy addition must preserve preparation sources")
    _preserve_profiles(old.profiles, new.profiles)
    if any(not isinstance(value, SubmittedPreparationProfile)
           for key, value in new.profiles.items() if key not in old.profiles):
        raise QueueConflictError("container policy addition requires submitted preparation profiles")


def validate_coordinator_declarations(before, after):
    """Check authored candidate boundaries before host qualification/publication."""
    mutable = {"shared_roots", "preparation", "container_capabilities"}
    if {key: value for key, value in before.items() if key not in mutable} != {
        key: value for key, value in after.items() if key not in mutable
    }:
        raise QueueConflictError("container policy addition changed unrelated coordinator declaration")
    preserve(before.get("shared_roots", {}), after.get("shared_roots", {}), "shared roots")
    from .submitted_execution import SubmittedContainerCapability

    _preserve_capabilities(
        {item["policy_id"]: SubmittedContainerCapability.from_dict(item) for item in before.get("container_capabilities", [])},
        {item["policy_id"]: SubmittedContainerCapability.from_dict(item) for item in after.get("container_capabilities", [])},
    )
    old, new = before.get("preparation") or {}, after.get("preparation") or {}
    if old.get("source_roots") != new.get("source_roots"):
        raise QueueConflictError("container policy addition must preserve preparation sources")
    preserve(old.get("profiles", {}), new.get("profiles", {}), "preparation profiles")
    if any("container_policy_id" not in value for key, value in new.get("profiles", {}).items()
           if key not in old.get("profiles", {})):
        raise QueueConflictError("container policy addition requires submitted preparation profiles")
