"""Promote a compatible workload inside an already replaced runtime's gate.

The parent writer lock serializes this continuation. Its original intent, failed
checks and native gate identity remain unchanged. Ordinary workload promotion
owns candidate qualification, source publication, recovery and new checks.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from loom.fleet import upgrades, workload_upgrades
from loom.fleet import ssh_operations as sshops
from loom.fleet._host import atomic, digest, read
from loom.fleet.configuration import protected_directory
from loom.queue.errors import QueueConfigError, QueueConflictError


def repair_workload(operation, *, workload_profile, image, workload_inventory=None):
    """Bind one immutable repair after a settled, failed runtime qualification."""
    if not workload_profile or image is None:
        raise QueueConfigError("repair-workload requires --workload-profile and --image")
    requested = {
        "workload_profile": workload_profile,
        "image": str(Path(image).resolve()),
        "workload_inventory": None if workload_inventory is None else str(Path(workload_inventory).resolve()),
    }
    directory = operation.directory / "workload-repair"
    path = directory / "intent.json"
    if path.exists():
        retained = read(path)
        if any(retained[key] != value for key, value in requested.items()):
            raise QueueConflictError("retained workload repair target changed")
        return continue_repair(operation)
    if (
        operation.intent["kind"] != "runtime-upgrade"
        or not (operation.directory / "irreversible.json").exists()
        or (operation.directory / "restoring.json").exists()
        or (operation.directory / "complete.json").exists()
    ):
        raise QueueConflictError("workload repair requires an incomplete replaced runtime upgrade")
    operation.recheck()
    operation.settled()
    failed = False
    for rows in upgrades._attempts(operation).values():
        result = upgrades.self_test(
            operation.inventory, operation_id=rows[-1]["operation_id"],
            timeout_seconds=operation.intent["timeout_seconds"],
        )
        failed |= result["outcome"] == "failed" and any(
            item.get("code") == "native_check_failed"
            for item in result["checks"].values()
        )
    if not failed:
        raise QueueConflictError("workload repair requires a confirmed native check failure")
    selection = operation.intent["check_selection"]
    env_file = operation.intent["env_file"]
    environment = None if env_file is None else Path(env_file)
    plan = workload_upgrades.preview(
        operation.inventory, **requested,
        deployment=Path(selection["deployment"]),
        connection=Path(selection["operator_connection"]),
        config=selection["config"], env_file=environment,
    )
    # Runtime qualification covers the whole fleet. A narrower workload target
    # cannot replace checks for untouched consumers in this recovery path.
    if set(plan["agents"]) != set(operation.intent["agents"]):
        raise QueueConflictError("runtime workload repair must cover every upgraded agent")
    for name, row in plan["hosts"].items():
        if row["expected_root_id"] != operation.intent["hosts"][name]["expected_root_id"]:
            raise QueueConflictError("runtime workload repair native root changed")
    operation.recheck()
    operation.settled()
    protected_directory(directory)
    inputs = sshops._inputs(operation.inventory, plan["hosts"], environment)
    for key in ("deployment", "operator_connection"):
        path_input = Path(selection[key])
        inputs[str(path_input)] = sshops._file_hash(path_input)
    identity = "workload-repair-" + hashlib.sha256(
        operation.intent["operation_id"].encode()
    ).hexdigest()[:24]
    intent = {
        "schema_version": 1,
        "operation_id": identity,
        "target_path": operation.intent["target_path"],
        "release": operation.intent["release"],
        "hosts": plan["hosts"],
        "agents": plan["agents"],
        "restore_agents": operation.intent["agents"],
        "declarations": plan["declarations"],
        "inputs": inputs,
        "check_selection": plan["checks"],
        "env_file": env_file,
        "timeout_seconds": operation.intent["timeout_seconds"],
        "maintenance_binding": upgrades._maintenance_binding(operation.intent),
    }
    atomic(path, workload_upgrades.bind_intent(intent, plan, directory))
    return continue_repair(operation)


def continue_repair(operation, *, action="resume", failed_check=None,
                    new_check=None, failed_control=None, new_control=None):
    """Resume under the parent lock; publish parent success only after all checks."""
    directory = operation.directory / "workload-repair"
    intent = read(directory / "intent.json")
    if intent["maintenance_binding"] != {
        "operation_id": operation.intent["operation_id"],
        "target_intent_digest": digest(operation.intent),
    } or intent["release"] != operation.intent["release"]:
        raise QueueConflictError("workload repair parent/runtime intent conflicts")
    child = workload_upgrades.WorkloadUpgrade(
        operation.inventory, directory, intent, operation.observation
    )
    try:
        if action == "retry-check":
            result = upgrades._retry_check(child, failed_check, new_check)
        elif action == "retry-control":
            result = upgrades._retry_control(child, failed_control, new_control)
        else:
            result = workload_upgrades.continue_upgrade(child)
    finally:
        child.close()
    if result["state"] == "complete":
        result = {
            **result,
            "workload_repair": intent["operation_id"],
            "runtime_checks_before_repair": upgrades._attempts(operation),
        }
        atomic(operation.directory / "complete.json", result)
    return result
