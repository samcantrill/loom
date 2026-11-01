"""Monotonic publication ceilings through existing settled maintenance owners.

Only publication limits change. Logical roots, source selections, execution
permissions and resource capacity retain their previous meaning. The promotion
and scheduling journals continue to own activation, replay and interruption.
"""

from collections.abc import Mapping
from dataclasses import fields, replace
from typing import cast

from loom.pipeline.stores.shared_artifacts import admits_budgets
from loom.serialization import PlainData
from .errors import QueueConflictError

CAPABILITY = "quiescent-publication-budget-increase-v1"


def validate_roots(before, after):
    """Keep every root and non-budget fact exact; permit only higher ceilings."""
    if set(before) != set(after):
        raise QueueConflictError("publication budget increase cannot add or remove roots")
    for alias, old in before.items():
        new = after[alias]
        if ({key: value for key, value in old.items() if key != "publication"}
            != {key: value for key, value in new.items() if key != "publication"}):
            raise QueueConflictError("publication budget increase cannot change root identity or access")
        if ("publication" in old) != ("publication" in new):
            raise QueueConflictError("publication budget increase requires an existing publication root")
        if "publication" in old and not admits_budgets(new["publication"], old["publication"]):
            raise QueueConflictError("publication budgets may only increase")


def _policies(before, after):
    old = {item["policy_id"]: item for item in before}
    new = {item["policy_id"]: item for item in after}
    if len(old) != len(before) or len(new) != len(after) or set(old) != set(new):
        raise QueueConflictError("publication budget increase must preserve every policy identity")
    for key, previous in old.items():
        replacement = new[key]
        if ({name: value for name, value in previous.items() if name != "shared_roots"}
            != {name: value for name, value in replacement.items() if name != "shared_roots"}):
            raise QueueConflictError("publication budget increase cannot change execution policy")
        validate_roots(previous["shared_roots"], replacement["shared_roots"])


def require_matching_budgets(roots, policies):
    """All declarations of a published root must agree with its owning root."""
    for policy in policies:
        for alias, root in policy["shared_roots"].items():
            if "publication" in root and (
                alias not in roots or roots[alias].get("publication") != root["publication"]
            ):
                raise QueueConflictError("publication budgets disagree between root and execution policy")


def validate_agent(previous, replacement):
    if previous.resource_inventory is None or not previous.container_policies:
        raise QueueConflictError("publication budget increase requires existing container policies and resources")
    if previous.resident_profiles != replacement.resident_profiles:
        raise QueueConflictError("publication budget increase cannot change resident profiles")
    _policies([item.to_dict() for item in previous.container_policies],
              [item.to_dict() for item in replacement.container_policies])


def validate_coordinator_declarations(before, after):
    """Validate authored candidates before native qualification and publication."""
    mutable = {"shared_roots", "container_capabilities"}
    if ({key: value for key, value in before.items() if key not in mutable}
        != {key: value for key, value in after.items() if key not in mutable}):
        raise QueueConflictError("publication budget increase changed unrelated coordinator declaration")
    validate_roots(before.get("shared_roots", {}), after.get("shared_roots", {}))
    _policies(before.get("container_capabilities", []), after.get("container_capabilities", []))
    require_matching_budgets(after.get("shared_roots", {}), after.get("container_capabilities", []))


def validate_coordinator(previous, replacement):
    """Check native derived preparation facts as well as protected root policy."""
    from ._preparation_policy import SubmittedPreparationProfile

    mutable = {"shared_roots", "preparation_policy", "container_capabilities",
               "active_configuration_fingerprint"}
    if previous.agent_root is not None or any(
        getattr(previous, item.name) != getattr(replacement, item.name)
        for item in fields(previous) if item.name not in mutable
    ):
        raise QueueConflictError("publication budget increase cannot change unrelated coordinator configuration")
    validate_roots(previous.coordinator_shared_roots, replacement.coordinator_shared_roots)
    _policies([item.to_dict() for item in previous.container_capabilities],
              [item.to_dict() for item in replacement.container_capabilities])
    require_matching_budgets(replacement.coordinator_shared_roots,
                             [item.to_dict() for item in replacement.container_capabilities])
    old, new = previous.preparation_policy, replacement.preparation_policy
    if old is None or new is None:
        if old != new:
            raise QueueConflictError("publication budget increase cannot change preparation policy")
        return
    if old.source_roots != new.source_roots or set(old.profiles) != set(new.profiles):
        raise QueueConflictError("publication budget increase cannot change preparation sources or aliases")
    capabilities = {item.policy_id: item for item in replacement.container_capabilities}
    for alias, prior in old.profiles.items():
        current = new.profiles[alias]
        if not isinstance(prior, SubmittedPreparationProfile):
            if current != prior:
                raise QueueConflictError("publication budget increase cannot change installed preparation")
            continue
        if (not isinstance(current, SubmittedPreparationProfile)
            or replace(current, capability=prior.capability, shared_scope=prior.shared_scope) != prior
            or current.capability != capabilities.get(prior.capability.policy_id)):
            raise QueueConflictError("publication budget increase cannot change preparation selection")
        if ({key: value for key, value in prior.shared_scope.items() if key != "roots"}
            != {key: value for key, value in current.shared_scope.items() if key != "roots"}):
            raise QueueConflictError("publication budget increase cannot change preparation locations")
        validate_roots(prior.shared_scope["roots"], current.shared_scope["roots"])
        roots = cast(Mapping[str, PlainData], current.shared_scope["roots"])
        if any(current.capability.shared_roots.get(alias) != facts
               for alias, facts in roots.items()):
            raise QueueConflictError("preparation root budgets differ from selected capability")
