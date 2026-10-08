"""Retained installation adoption under explicit operator-enforced exclusion.

The predecessor may lack admission and conditional-control APIs. The operator
excludes new submissions and independent administration and drains retained work
using that predecessor's supported controls. Fleet prepares the candidate first,
then proves native settlement before stopping or replacing any communication
service. Adoption transfers installation ownership; qualification is separate.
"""

from __future__ import annotations

import fcntl
from pathlib import Path

from loom.fleet import ssh_operations as sshops
from loom.fleet._host import atomic, digest, read
from loom.fleet.configuration import protected_directory
from loom.fleet.releases import verify_release
from loom.fleet.upgrades import REQUIRED_CAPABILITIES
from loom.queue.errors import QueueConfigError, QueueConflictError


def _bindings(path, names):
    selected = read(Path(path).resolve())
    if (
        not isinstance(selected, dict)
        or set(selected) != {"schema_version", "kind", "hosts"}
        or type(selected["schema_version"]) is not int
        or selected["schema_version"] != 1
        or selected["kind"] != "loom.fleet-adoption"
        or not isinstance(selected["hosts"], dict)
        or set(selected["hosts"]) != set(names)
    ):
        raise QueueConfigError(
            "adoption bindings must select every declared host exactly"
        )
    for value in selected["hosts"].values():
        if (
            not isinstance(value, dict)
            or set(value) != {"expected_root_id", "python"}
            or not isinstance(value["expected_root_id"], str)
            or not value["expected_root_id"]
            or not isinstance(value["python"], str)
            or not Path(value["python"]).is_absolute()
        ):
            raise QueueConfigError(
                "adoption requires native identities and absolute retained interpreters"
            )
    return selected["hosts"]


def preview(inventory, *, bindings, env_file=None):
    """Read selected declarations and host prerequisites; never install or stop.

    An uninstalled candidate cannot prove legacy native ownership. Apply installs
    it separately and performs the authoritative inspection before any stop.
    """
    if inventory.service_manager != "tmux":
        raise QueueConfigError("installation adoption retains the tmux backend")
    rows, declarations = sshops._selection(inventory, None, env_file)
    predecessors = _bindings(bindings, rows)
    release = verify_release(inventory.runtime_release)
    for name, row in rows.items():
        row.update(
            expected_root_id=predecessors[name]["expected_root_id"],
            previous_python=predecessors[name]["python"],
        )
        try:
            observation = sshops.ssh(
                row["host"], {**row, "action": "inspect", "release": release}
            )
            row["observation"] = observation
            if not observation["root_exists"]:
                row["conflict"] = (
                    "retained native root is missing; adoption never initializes it"
                )
            if observation["installed"] is not None:
                row["conflict"] = (
                    "managed installation already exists; use Fleet upgrade"
                )
        except (sshops.SshUnavailable, QueueConflictError) as exc:
            row["unavailable"] = str(exc)
    return {
        "schema_version": 1,
        "fleet": inventory.name,
        "command": "adopt",
        "outcome": "preview",
        "ready": False,
        "reservation": False,
        "release": release,
        "hosts": rows,
        "declarations": declarations,
        "next": "Exclude submissions and independent administration; settle native work. Apply prepares candidates and proves owners before replacement. Installed qualification remains separate.",
    }


def _values(intent, name):
    row = intent["hosts"][name]
    return {
        "adoption_id": intent["operation_id"],
        "expected_root_id": row["expected_root_id"],
        "previous_python": row["previous_python"],
        "coordinator_id": intent["hosts"]["coordinator"]["expected_root_id"],
        "descriptor_name": Path(intent["release_path"]).name,
        "required_capabilities": list(REQUIRED_CAPABILITIES),
    }


def _run(operation):
    intent = operation.intent
    irreversible = operation.directory / "replacement.json"
    if not irreversible.exists():
        for name in intent["hosts"]:
            operation.call(
                name, "install-candidate", **sshops._bundle(operation.inventory)
            )
        for name in intent["hosts"]:
            values = _values(intent, name)
            path = operation.directory / (name + "-candidate.json")
            if path.exists():
                retained = read(path)
                values.update(
                    images=retained["images"],
                    expected_session_id=retained["native_owner"]["value"].get(
                        "session_id"
                    ),
                )
            fact = operation.observe(name, action="adopt-probe", **values)
            if not path.exists():
                atomic(path, fact)
        for name in intent["hosts"]:
            fact = operation.observe(
                name, action="upgrade-settlement", **_values(intent, name)
            )
            if fact["availability"] != "available" or not fact["value"].get("settled"):
                raise QueueConflictError(
                    "adoption waits for native settlement on " + name + ": " + str(fact)
                )
        atomic(irreversible, {"intent_digest": digest(intent), "step": "stop-replace"})
    # All stops precede replacement. Each exact request has local and remote
    # receipts, so lost replies never enroll another root or choose another PID.
    for name in [
        *(name for name in intent["hosts"] if name != "coordinator"),
        "coordinator",
    ]:
        fact = read(operation.directory / (name + "-candidate.json"))
        operation.call(
            name,
            "adopt-stop",
            **_values(intent, name),
            images=fact["images"],
            expected_session_id=fact["native_owner"]["value"].get("session_id"),
        )
    for name in [
        "coordinator",
        *(name for name in intent["hosts"] if name != "coordinator"),
    ]:
        fact = read(operation.directory / (name + "-candidate.json"))
        operation.call(
            name,
            "adopt-replace",
            **_values(intent, name),
            images=fact["images"],
            expected_session_id=fact["native_owner"]["value"].get("session_id"),
        )
    for name in intent["hosts"]:
        fact = read(operation.directory / (name + "-candidate.json"))
        observed = operation.observe(
            name,
            action="adopt-probe",
            **_values(intent, name),
            images=fact["images"],
            expected_session_id=fact["native_owner"]["value"].get("session_id"),
        )
        if (
            observed["native_owner"]["value"]["ownership"] != "live"
            or observed["process_python"] != observed["python"]
        ):
            raise QueueConflictError(
                "adopted candidate process remains unproven on " + name
            )
    return {
        "state": "complete",
        "ready": False,
        "installation": "adopted",
        "qualification": "required",
        "release": intent["release"],
        "identities": {
            name: row["expected_root_id"] for name, row in intent["hosts"].items()
        },
        "next": "Retain operator exclusion. Qualify the selected workload and native CPU/storage/GPU checks before reopening ordinary use.",
    }


def adopt(
    inventory,
    *,
    bindings=None,
    operation_id=None,
    env_file=None,
    apply=False,
    operator_exclusion=False,
    action="resume",
):
    """Preview or continue the exact installation handover, without rollback.

    ``operator_exclusion=True`` acknowledges an externally maintained exclusion
    of new submissions and policy edits until installed qualification completes.
    A retained operation preserves this prerequisite across continuation.
    """
    if operation_id is None:
        if apply:
            raise QueueConfigError("adoption apply requires --operation-id")
        if bindings is None:
            raise QueueConfigError("adoption preview requires --bindings")
        return preview(inventory, bindings=bindings, env_file=env_file)
    directory = sshops._directory(inventory, operation_id)
    path = directory / "intent.json"
    if not path.exists() and not apply:
        raise QueueConfigError("unknown adoption operation")
    if apply and (bindings is None or not operator_exclusion):
        raise QueueConfigError(
            "adoption apply requires --bindings and --operator-exclusion"
        )
    protected_directory(directory)
    with (directory / "writer.lock").open("a") as writer:
        try:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QueueConflictError("adoption already has an active writer") from exc
        if not path.exists():
            if bindings is None:
                raise QueueConfigError("adoption requires explicit retained bindings")
            plan = preview(inventory, bindings=bindings, env_file=env_file)
            if any(
                row.get("conflict") or row.get("unavailable")
                for row in plan["hosts"].values()
            ):
                raise QueueConflictError(
                    "adoption preview has unavailable or conflicting hosts"
                )
            binding_path = Path(bindings).resolve()
            inputs = sshops._inputs(inventory, plan["hosts"], env_file)
            inputs[str(binding_path)] = sshops._file_hash(binding_path)
            atomic(
                path,
                {
                    "schema_version": 1,
                    "kind": "installation-adoption",
                    "operation_id": operation_id,
                    "bindings": str(binding_path),
                    "release_path": str(inventory.runtime_release),
                    "release": plan["release"],
                    "inputs": inputs,
                    "hosts": plan["hosts"],
                    "declarations": plan["declarations"],
                    "operator_exclusion": True,
                },
            )
        intent = read(path)
        if intent.get("kind") != "installation-adoption":
            raise QueueConflictError("operation belongs to another kind")
        if bindings is not None and str(Path(bindings).resolve()) != intent["bindings"]:
            raise QueueConflictError("adoption bindings differ from retained intent")
        if env_file is not None and any(
            row["env_file"] != str(Path(env_file).resolve())
            for row in intent["hosts"].values()
        ):
            raise QueueConflictError(
                "adoption environment differs from retained intent"
            )
        operation = sshops._Operation(inventory, directory, intent)
        operation.recheck()
        result_path = directory / "result.json"
        if result_path.exists() and read(result_path)["state"] in {
            "complete",
            "aborted",
        }:
            return sshops.operation_status(inventory, operation_id)
        if action == "abort":
            if (directory / "replacement.json").exists():
                raise QueueConflictError(
                    "replacement intent is retained; continue adoption, no automatic rollback"
                )
            atomic(
                result_path,
                {
                    "state": "aborted",
                    "ready": False,
                    "next": "No native service was stopped or replaced. Separately installed candidates and their receipts are retained.",
                },
            )
        elif action == "resume":
            try:
                atomic(result_path, _run(operation))
            except (sshops.SshUnavailable, QueueConflictError) as exc:
                atomic(
                    result_path,
                    {
                        "state": "waiting",
                        "ready": False,
                        "reason": str(exc),
                        "next": "Preserve operator exclusion and inputs; resolve the named native condition and resume this operation.",
                    },
                )
        else:
            raise QueueConfigError(
                "adoption supports status, resume or pre-replacement abort"
            )
        return sshops.operation_status(inventory, operation_id)
