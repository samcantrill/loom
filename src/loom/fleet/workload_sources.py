"""Candidate native declarations for a selected workload source promotion.

The candidate uses the existing protected Fleet inventory and native role
formats. It is read-only input to the current fleet's operation, not another
installed fleet. Native loaders and promotion guards remain authoritative.
"""

from __future__ import annotations

import json
from pathlib import Path

from loom.fleet.configuration import load_inventory
from loom.fleet import ssh_operations as sshops
from loom.queue.errors import QueueConflictError
from loom.queue.shared_execution import _readonly_root_relocations


def candidates(inventory, path, plan, consumers, env_file, *, retire_configuration=False):
    """Read a compatible target inventory in each retained role's path frame."""
    candidate = load_inventory(Path(path))
    if (
        candidate.service_manager != inventory.service_manager
        or candidate.runtime_release != inventory.runtime_release
    ):
        raise QueueConflictError("workload inventory cannot change service backend or release")
    rows, declarations = sshops._selection(candidate, None, env_file)
    if set(rows) != set(plan["hosts"]):
        raise QueueConflictError("workload inventory must preserve the current host selection")
    for name, row in rows.items():
        previous = plan["hosts"][name]
        if (
            any(row[key] != previous[key] for key in ("host", "root", "env_file"))
            or Path(row["config"]).parent != Path(previous["config"]).parent
            or row["config"] == previous["config"]
        ):
            raise QueueConflictError(
                "workload candidate needs a separate sibling role file with the same host, root and environment"
            )
        if name != "coordinator" and name not in consumers:
            if declarations[name] != plan["declarations"][name]:
                raise QueueConflictError("workload inventory changed an unselected agent")
    before, after = plan["declarations"]["coordinator"], declarations["coordinator"]
    allowed = {"preparation", "shared_roots"}
    if retire_configuration:
        allowed |= {"remote_profiles", "container_capabilities"}
    if {key: value for key, value in before.items() if key not in allowed} != {
        key: value for key, value in after.items() if key not in allowed
    }:
        raise QueueConflictError("workload inventory changed unrelated coordinator policy")
    if retire_configuration:
        _retirement_coordinator(before, after)
    else:
        # The operation derives new descriptors and preparation generations. Target
        # authors select source paths, preserving snapshot roots and science policy.
        before_preparation, after_preparation = before["preparation"], after["preparation"]
        if before_preparation["profiles"] != after_preparation["profiles"]:
            raise QueueConflictError("workload inventory cannot change preparation policy")
        before_roots, after_roots = before_preparation["source_roots"], after_preparation["source_roots"]
        if set(before_roots) != set(after_roots) or any(
            {key: value for key, value in root.items() if key != "path"}
            != {key: value for key, value in after_roots[name].items() if key != "path"}
            for name, root in before_roots.items()
        ):
            raise QueueConflictError("workload inventory must preserve preparation snapshot mappings")
        _readonly_root_relocations(before.get("shared_roots", {}), after.get("shared_roots", {}))
        if set(before.get("shared_roots", {})) != set(after.get("shared_roots", {})):
            raise QueueConflictError("workload inventory must preserve logical storage roots")
    return (
        json.loads(json.dumps(declarations)),
        sshops._inputs(candidate, rows, env_file),
        {"hosts": rows, "declarations": declarations},
    )


def _retirement_coordinator(before, after):
    """Validate candidate input narrowing; native reload owns final acceptance."""
    for key in ("remote_profiles",):
        if any(value not in before.get(key, []) for value in after.get(key, [])):
            raise QueueConflictError("retirement inventory cannot add or change execution identities")
    from loom.queue.submitted_execution import SubmittedContainerCapability, _validate_retired_capabilities
    _validate_retired_capabilities(
        [SubmittedContainerCapability.from_dict(value) for value in before.get("container_capabilities", [])],
        [SubmittedContainerCapability.from_dict(value) for value in after.get("container_capabilities", [])],
    )
    old_roots, new_roots = before.get("shared_roots", {}), after.get("shared_roots", {})
    if not set(new_roots) <= set(old_roots):
        raise QueueConflictError("retirement inventory cannot add shared roots")
    _readonly_root_relocations({key: old_roots[key] for key in new_roots}, new_roots)
    old, new = before.get("preparation") or {}, after.get("preparation") or {}
    if any(old.get("source_roots", {}).get(key) != value for key, value in new.get("source_roots", {}).items()):
        raise QueueConflictError("retirement inventory cannot rebind preparation sources")
    for key, profile in new.get("profiles", {}).items():
        previous = old.get("profiles", {}).get(key)
        if (previous is None or not set(profile["allowed_source_roots"]) <= set(previous["allowed_source_roots"])
            or {**profile, "allowed_source_roots": previous["allowed_source_roots"]} != previous):
            raise QueueConflictError("retirement inventory cannot change preparation execution")
