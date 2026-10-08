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


def candidates(inventory, path, plan, consumers, env_file):
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
    if {key: value for key, value in before.items() if key not in allowed} != {
        key: value for key, value in after.items() if key not in allowed
    }:
        raise QueueConflictError("workload inventory changed unrelated coordinator policy")
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
    return json.loads(json.dumps(declarations)), sshops._inputs(candidate, rows, env_file)
