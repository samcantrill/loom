"""Guarded policy-only transitions for agent GPU inventories."""

from dataclasses import fields, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_sessions import AgentPolicyConfig

CAPABILITY = "quiescent-agent-gpu-policy-contraction-v1"
EXPANSION_CAPABILITY = "quiescent-agent-gpu-policy-expansion-v1"


def contracts_gpu_inventory(before: "AgentPolicyConfig", after: "AgentPolicyConfig") -> bool:
    """Keep identities, permissions and device descriptions; remove GPUs only.

    The caller owns the mutable maintenance/settlement check. Empty inventories
    are excluded: this transition repairs a retained GPU worker's allowlist.
    """
    if replace(after, agents=before.agents) != before or len(after.agents) != len(before.agents):
        return False
    changed = False
    for old in before.agents:
        candidates = [new for new in after.agents if new.agent_id == old.agent_id]
        if len(candidates) != 1:
            return False
        new = candidates[0]
        if replace(new, gpu_devices=old.gpu_devices) != old:
            return False
        if new.gpu_devices != old.gpu_devices:
            if (not new.gpu_devices or len(new.gpu_devices) >= len(old.gpu_devices)
                or not all(device in old.gpu_devices for device in new.gpu_devices)):
                return False
            changed = True
    return changed


def validate_coordinator(daemon, replacement, binding, *, expansion=False):
    """Validate the exact maintenance owner while scheduling holds its lock."""
    from ._maintenance import observe
    from .errors import QueueConflictError

    gate = observe(daemon)
    if (gate["state"] != "closed" or not gate["settled"] or gate["checks"]
        or gate["maintenance_id"] != binding["maintenance_id"]
        or gate["intent_digest"] != binding["maintenance_intent_digest"]
        or gate["revision"] != binding["expected_gate_revision"]):
        raise QueueConflictError("GPU policy transition requires exact settled maintenance")
    previous = daemon.config
    mutable = {"agent_policy", "active_configuration_fingerprint"}
    if any(getattr(previous, field.name) != getattr(replacement, field.name)
           for field in fields(previous) if field.name not in mutable):
        raise QueueConflictError("GPU policy transition cannot change unrelated configuration")
    before, after = previous.agent_policy, replacement.agent_policy
    valid = contracts_gpu_inventory(after, before) if expansion else contracts_gpu_inventory(before, after)
    if not valid:
        direction = "superset" if expansion else "subset"
        raise QueueConflictError(f"GPU policy transition requires a nonempty strict {direction} with unchanged identities and permissions")
