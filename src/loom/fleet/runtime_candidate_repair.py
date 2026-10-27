"""Replace an unactivated recovery candidate while retaining its maintenance gate."""

from __future__ import annotations

import hashlib
from pathlib import Path

from loom.fleet import upgrades
from loom.fleet import ssh_operations as sshops
from loom.fleet._host import atomic, read
from loom.fleet.configuration import protected_directory
from loom.queue.errors import QueueConfigError, QueueConflictError


def repair_candidate(operation, *, runtime_release):
    """Bind one explicit successor before any service stop or replacement.

    The original intent and failed eligibility evidence remain immutable. The
    parent writer lock and native maintenance identity also own the successor.
    """
    if runtime_release is None:
        raise QueueConfigError("repair-runtime-candidate requires --runtime-release")
    target = Path(runtime_release).resolve()
    directory = operation.directory / "runtime-candidate-repair"
    path = directory / "intent.json"
    if path.exists():
        if read(path)["target_path"] != str(target):
            raise QueueConflictError("retained runtime candidate repair target changed")
        return continue_repair(operation)
    if (operation.intent["kind"] not in {"runtime-upgrade", "runtime-upgrade-publication"}
            or not operation.intent.get("recover_retained_results")
            or operation.intent.get("runtime_retirement")
            or any((operation.directory / name).exists() for name in (
                "irreversible.json", "complete.json", "aborted.json", "retained-results.json",
            ))):
        raise QueueConflictError("candidate repair requires an unactivated retained-result recovery")
    operation.recheck()
    operation.gate()
    selection = operation.intent["check_selection"]
    environment = operation.intent["env_file"]
    from loom.queue.submitted_execution import SubmittedContainerExecution

    execution = selection.get("execution")
    plan = upgrades.preview(
        operation.inventory, runtime_release=target, recover_retained_results=True,
        hold_admission=operation.intent["kind"].endswith("-publication"),
        deployment=Path(selection["deployment"]),
        connection=Path(selection["operator_connection"]), config=selection["config"],
        check_execution=None if execution is None else SubmittedContainerExecution.from_dict(execution),
        env_file=None if environment is None else Path(environment),
    )
    if plan["release"] == operation.intent["release"]:
        raise QueueConflictError("candidate repair requires a different immutable runtime")
    if plan["declarations"] != operation.intent["declarations"] or set(plan["hosts"]) != set(operation.intent["hosts"]):
        raise QueueConflictError("candidate repair cannot change fleet declarations or hosts")
    for name, row in plan["hosts"].items():
        previous = operation.intent["hosts"][name]
        if any(row[key] != previous[key] for key in ("expected_root_id", "source_release")):
            raise QueueConflictError("candidate repair requires unchanged native roots and source runtimes")
    operation.recheck()
    operation.gate()
    inputs = dict(operation.intent["inputs"])
    inputs[str(target)] = sshops._file_hash(target)
    identity = "runtime-candidate-" + hashlib.sha256(operation.intent["operation_id"].encode()).hexdigest()[:24]
    from ._inventory_publication import bind

    intent = {
        **operation.intent,
        "operation_id": identity, "target_path": str(target), "release": plan["release"],
        "hosts": plan["hosts"], "agents": plan["agents"],
        "restore_agents": operation.intent["agents"], "inputs": inputs,
        "check_selection": plan["checks"],
        "inventory_publication": bind(operation.inventory, target, inputs[str(operation.inventory.path)]),
        "maintenance_binding": upgrades._maintenance_binding(operation.intent),
    }
    protected_directory(directory)
    atomic(path, intent)
    return continue_repair(operation)


def continue_repair(operation, *, action="resume", failed_check=None, new_check=None,
                    failed_control=None, new_control=None):
    """Resume the exact successor under its parent's existing writer lock."""
    directory = operation.directory / "runtime-candidate-repair"
    intent = read(directory / "intent.json")
    if intent["maintenance_binding"] != upgrades._maintenance_binding(operation.intent):
        raise QueueConflictError("runtime candidate repair parent intent conflicts")
    child = upgrades._Upgrade(operation.inventory, directory, intent, operation.observation)
    try:
        if action == "release-admission":
            upgrades._release_publication_hold(child)
        elif action == "retry-check":
            return upgrades._retry_check(child, failed_check, new_check)
        elif action == "retry-control":
            return upgrades._retry_control(child, failed_control, new_control)
        elif action != "resume":
            raise QueueConflictError("runtime candidate repair requires resume of its retained successor")
        result = upgrades._continue(child)
    finally:
        operation.check_observations = getattr(child, "check_observations", {})
        operation.continuation_checks = upgrades._attempts(child)
        child.close()
    if result["state"] == "complete":
        result = {**result, "runtime_candidate_repair": intent["operation_id"]}
        atomic(operation.directory / "complete.json", result)
    return result
