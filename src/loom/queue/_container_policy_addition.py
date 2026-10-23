"""Add qualified container policy identities without rebinding retained work.

The existing promotion and scheduling journals own activation and recovery.
These constraints permit additions only; retirement remains a separate action.
"""

from dataclasses import fields

from .errors import QueueConflictError

CAPABILITY = "quiescent-container-policy-addition-v1"


def preserve(before, after, label):
    """Require every retained mapping entry to keep its exact meaning."""
    if any(after.get(key) != value for key, value in before.items()):
        raise QueueConflictError("container policy addition cannot remove or change " + label)


def validate_agent(previous, replacement):
    if previous.resource_inventory is None or not previous.container_policies:
        raise QueueConflictError("container policy addition requires existing policies and explicit resources")
    if previous.resident_profiles != replacement.resident_profiles:
        raise QueueConflictError("container policy addition cannot change resident profiles")
    preserve({policy.policy_id: policy for policy in previous.container_policies},
             {policy.policy_id: policy for policy in replacement.container_policies},
             "retained container policies")


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
    preserve({item.policy_id: item for item in previous.container_capabilities},
             {item.policy_id: item for item in replacement.container_capabilities}, "container capabilities")
    old, new = previous.preparation_policy, replacement.preparation_policy
    if old is None or new is None or old.source_roots != new.source_roots:
        raise QueueConflictError("container policy addition must preserve preparation sources")
    preserve(old.profiles, new.profiles, "preparation profiles")
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
    preserve({item["policy_id"]: item for item in before.get("container_capabilities", [])},
             {item["policy_id"]: item for item in after.get("container_capabilities", [])},
             "container capabilities")
    old, new = before.get("preparation") or {}, after.get("preparation") or {}
    if old.get("source_roots") != new.get("source_roots"):
        raise QueueConflictError("container policy addition must preserve preparation sources")
    preserve(old.get("profiles", {}), new.get("profiles", {}), "preparation profiles")
    if any("container_policy_id" not in value for key, value in new.get("profiles", {}).items()
           if key not in old.get("profiles", {})):
        raise QueueConflictError("container policy addition requires submitted preparation profiles")
