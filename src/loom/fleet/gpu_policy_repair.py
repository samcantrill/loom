"""Reconcile an already-bound agent GPU contraction during a settled upgrade."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from loom.queue._agent_gpu_policy import CAPABILITY
from loom.queue.errors import QueueConfigError, QueueConflictError
from loom.serialization import thaw_plain_data

from ._host import atomic, config, coordinator_client, coordinator_observation, payload, read


def repair(operation, *, agent_id) -> dict[str, Any]:
    """Repair the active successor without rewriting any upgrade intent."""
    from . import upgrades

    successor = operation.directory / "runtime-candidate-repair"
    if (successor / "intent.json").exists():
        intent = read(successor / "intent.json")
        if intent["maintenance_binding"] != upgrades._maintenance_binding(operation.intent):
            raise QueueConflictError("GPU policy repair successor maintenance identity conflicts")
        child = upgrades._Upgrade(operation.inventory, successor, intent, operation.observation)
        try:
            return repair(child, agent_id=agent_id)
        finally:
            child.close()
    if not agent_id or agent_id not in operation.intent["agents"]:
        raise QueueConfigError("GPU policy repair requires one retained agent ID")
    if (operation.intent["kind"] not in {"runtime-upgrade", "runtime-upgrade-publication"}
        or any((operation.directory / name).exists() for name in (
            "checks.json", "restoring.json", "complete.json", "aborted.json"))
        or any(not (operation.receipts / (name + "-upgrade-replace") / "receipt.json").exists()
               for name in operation.intent["hosts"])):
        raise QueueConflictError("GPU policy repair requires all replacements before qualification")
    gpu = operation.intent["declarations"][agent_id].get("resources", {}).get("gpu", {})
    devices = gpu.get("devices")
    if gpu.get("provider") != "nvidia" or not isinstance(devices, str):
        raise QueueConflictError("GPU policy repair requires an explicit bound NVIDIA UUID allowlist")
    uuids = devices.split(",")
    if not uuids or len(set(uuids)) != len(uuids) or any(not value.startswith("GPU-") for value in uuids):
        raise QueueConflictError("GPU policy repair requires unique explicit GPU UUIDs")
    gate = operation.gate()
    if not gate.get("settled") or gate["checks"]:
        raise QueueConflictError("GPU policy repair requires settled maintenance before checks")
    # call() reconciles an exact pending host publication before checking hashes.
    result = operation.call(
        "coordinator", "repair-gpu-policy", agent_id=agent_id, gpu_uuids=uuids,
        coordinator_id=operation.intent["hosts"]["coordinator"]["expected_root_id"],
        maintenance_binding=upgrades._maintenance_binding(operation.intent),
    )
    operation.recheck()
    return {"state": "waiting", "reason": "GPU policy repaired; resume the retained upgrade",
            "gpu_policy_repair": {"agent_id": agent_id, "reload": result["reload"]}}


def repair_host(request, directory) -> dict[str, Any]:
    """Publish and reload one strict contraction using the native journals."""
    from loom.queue.local_daemon import CoordinatorSchedulingReload

    service, client = coordinator_client(request)
    observation = coordinator_observation(request, service)
    if observation.owner != request["coordinator_id"]:
        raise QueueConflictError("GPU policy repair coordinator identity changed")
    status = cast(dict[str, Any], thaw_plain_data(observation.value))
    if CAPABILITY not in status.get("capabilities", ()):
        raise QueueConflictError("coordinator runtime does not support GPU policy contraction")
    path = directory / "reload.json"
    if path.exists():
        intent = read(path)
    else:
        before = payload(request)
        if status["scheduling_fingerprint"] != service.active_fingerprint:
            raise QueueConflictError("authored policy differs from native accepted state")
        gate = client.observe_maintenance()
        binding = request["maintenance_binding"]
        if (gate["state"] != "closed" or not gate["settled"] or gate["checks"]
            or gate["maintenance_id"] != binding["operation_id"]
            or gate["intent_digest"] != binding["target_intent_digest"]):
            raise QueueConflictError("GPU policy repair requires its exact settled maintenance gate")
        after = json.loads(json.dumps(before))
        rules = [row for row in after["agent_policy"]["agents"] if row["agent_id"] == request["agent_id"]]
        if len(rules) != 1:
            raise QueueConflictError("GPU policy repair requires one existing agent rule")
        rule = rules[0]
        uuids = request["gpu_uuids"]
        selected = [device for device in rule["gpu_devices"] if device["id"] in uuids]
        if (not selected or len(selected) != len(uuids) or len(set(uuids)) != len(uuids)
            or len(selected) >= len(rule["gpu_devices"])):
            raise QueueConflictError("GPU policy repair requires a nonempty strict subset")
        rule["gpu_devices"] = selected
        intent = {"before": before, "after": after, "reload": CoordinatorSchedulingReload(
            request["request_id"], status["scheduling_epoch"],
            "Fleet retained agent GPU policy contraction",
            gpu_policy_contraction={
                "maintenance_id": gate["maintenance_id"],
                "maintenance_intent_digest": gate["intent_digest"],
                "expected_gate_revision": gate["revision"],
            },
        ).to_dict()}
        atomic(path, intent)
    current = payload(request)
    if current == intent["before"]:
        atomic(config(request), intent["after"])
    elif current != intent["after"]:
        raise QueueConflictError("coordinator source changed during GPU policy repair")
    result = cast(dict[str, Any], thaw_plain_data(client.reload_scheduling(CoordinatorSchedulingReload.from_dict(intent["reload"]))))
    if result.get("state") != "applied":
        raise QueueConflictError("native GPU policy reload not applied")
    return {"outcome": "applied", "coordinator_id": observation.owner, "reload": result,
            "declaration": intent["after"],
            "config_sha256": hashlib.sha256(config(request).read_bytes()).hexdigest()}
