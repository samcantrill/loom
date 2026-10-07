"""One-operator fixed SSH setup with retained intent and explicit continuation.

SSH selects hosts; native roots, requests, sessions and policies retain their
own identities. A lost transport reply is waiting, never proof of refusal.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
import dataclasses
import ssl
from urllib.parse import urlsplit
from uuid import uuid4
from typing import Any, cast
from loom.serialization import thaw_plain_data

from loom.fleet.configuration import Inventory, protected_directory
from loom.fleet.releases import verify_release
from loom.queue.deployment import (
    _load_protected_config,
    read_agent_spec,
    inspect_role_declaration,
)
from loom.queue.errors import QueueConfigError, QueueConflictError
from loom.coordinator import CoordinatorClientError
from loom.fleet._host import atomic, read, digest


class SshUnavailable(Exception):
    """No authoritative host result was received; dispatch may have happened."""


def ssh(host, request):
    """Send a bounded structured request using the user's existing SSH policy."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host) is None:
        raise QueueConfigError("select a plain configured SSH alias, never SSH options")
    program = Path(__file__).with_name("_ssh_bootstrap.py").read_text()
    encoded = json.dumps(request, sort_keys=True).encode()
    if len(encoded) > 128 * 1024 * 1024:
        raise QueueConfigError("selected bundle exceeds the fixed host request limit")
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "--",
                host,
                shlex.join(["python3.12", "-c", program]),
            ],
            input=encoded,
            capture_output=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SshUnavailable("SSH unavailable; retain this operation") from exc
    if result.returncode == 255 or not result.stdout:
        raise SshUnavailable("SSH returned no native receipt; retain this operation")
    try:
        if len(result.stdout) > 16 * 1024 * 1024:
            raise ValueError
        reply = json.loads(result.stdout)
        if reply["ok"] is not True:
            raise QueueConflictError(reply.get("reason", "host operation refused"))
        return reply["result"]
    except (KeyError, ValueError, TypeError) as exc:
        raise SshUnavailable(
            "SSH returned an invalid receipt; retain this operation"
        ) from exc


def _file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _selection(inventory, hosts, env_file):
    selected = inventory.select(hosts)
    names = [entry.name for entry in selected]
    if any(entry.name != "coordinator" for entry in selected):
        selected = (
            inventory.hosts[0],
            *(entry for entry in selected if entry.name != "coordinator"),
        )
    declarations = {}
    rows = {}
    for entry in selected:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", entry.name) is None:
            raise QueueConfigError(
                "inventory entry must have a simple native agent identifier"
            )
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", entry.host) is None:
            raise QueueConfigError("inventory host must be a configured SSH alias")
        _, _, declaration, _ = _load_protected_config(entry.config, env_file=env_file)
        declaration = cast(dict[str, Any], declaration)
        pending_binding = (
            entry.name == "coordinator"
            and declaration.get("agent_server") is not None
            and not declaration["agent_server"]["credential_fingerprints"]
        )
        inspection = (
            None
            if pending_binding
            else inspect_role_declaration(
                entry.config,
                role="coordinator" if entry.name == "coordinator" else "agent",
                env_file=env_file,
            )
        )
        if entry.name == "coordinator":
            if declaration["local_agent"] is not None or declaration.get(
                "slurm_profiles"
            ):
                raise QueueConfigError(
                    "setup supports a pure coordinator and separate resident agents"
                )
            root = (entry.config.parent / declaration["deployment_root"]).resolve()
            if declaration["agent_server"] is None:
                raise QueueConfigError("setup requires the native agent TLS listener")
        else:
            spec = read_agent_spec(entry.config, env_file=env_file)
            declared = cast(dict[str, Any], thaw_plain_data(spec.declarations))
            if len(declared["resident_profiles"]) != 1 or declared["slurm_profiles"]:
                raise QueueConfigError(
                    "setup requires one native resident profile per agent"
                )
            root = spec.agent_root
        declarations[entry.name] = declaration
        rows[entry.name] = {
            "host": entry.host,
            "config": str(entry.config),
            "root": str(root),
            "name": entry.name,
            "declaration_fingerprint": None
            if inspection is None
            else inspection.revision,
            "credential_binding": "pending" if pending_binding else "declared",
            "dependency": entry.name not in names,
            "env_file": None if env_file is None else str(env_file.resolve()),
            "env_sha256": None if env_file is None else _file_hash(env_file),
        }
    aliases = [entry["host"] for entry in rows.values()]
    if len(aliases) != len(set(aliases)):
        raise QueueConfigError("colocated coordinator/worker automation is unsupported")
    return rows, declarations


def plan(inventory: Inventory, *, hosts=None, issuer=None, env_file=None):
    """Observe selected hosts and coordinator dependency without writes/reservations.

    Only the release descriptor is hashed here. Apply verifies every immutable
    artifact before dispatch. Target-local filesystem evidence is authoritative.
    """
    if inventory.service_manager != "tmux":
        raise QueueConfigError(
            "SSH setup currently requires explicit tmux; no boot startup"
        )
    rows, declarations = _selection(inventory, hosts, env_file)
    requested = {"descriptor_sha256": _file_hash(inventory.runtime_release)}
    for name, row in rows.items():
        try:
            declaration = declarations[name]
            credential_role = (
                declaration["agent_server"] if name == "coordinator" else declaration
            )
            fields = (
                "certificate_path",
                "private_key_path",
                "client_ca_path" if name == "coordinator" else "server_ca_path",
            )
            credential_paths = [
                str((Path(row["config"]).parent / credential_role[field]).resolve())
                for field in fields
            ]
            observed = ssh(
                row["host"],
                {
                    **row,
                    "action": "inspect",
                    "release": requested,
                    "credential_paths": credential_paths,
                },
            )
            row["observation"] = observed
            if observed["bound_root"] and not observed["root_exists"]:
                row["conflict"] = (
                    "bound native root missing; explicit recovery required"
                )
            if observed["root_exists"] and observed["installed"] is None:
                row["conflict"] = (
                    "existing root lacks retained installation; explicit import required"
                )
            row["actions"] = [
                "verify immutable candidate",
                "preserve or prepare credentials",
                "initialize only absent unbound native root",
                "start retained tmux service",
                "observe fresh native resources",
                "run retained native self-tests",
            ]
            if name == "coordinator":
                row["actions"].insert(
                    3, "enroll selected agents with guarded native reload"
                )
            if (
                observed["installed"] is not None
                and observed["installed"]["descriptor_sha256"]
                != requested["descriptor_sha256"]
            ):
                row["conflict"] = "service release change requires explicit upgrade"
        except (SshUnavailable, QueueConflictError) as exc:
            row["unavailable"] = str(exc)
    return {
        "schema_version": 1,
        "fleet": inventory.name,
        "command": "plan",
        "outcome": "preview",
        "ready": False,
        "reservation": False,
        "service_manager": "tmux",
        "boot_start": False,
        "issuer": None if issuer is None else str(issuer),
        "release": requested,
        "hosts": rows,
    }


def _inputs(inventory, rows, env_file):
    paths = [
        inventory.path,
        inventory.runtime_release,
        *(Path(row["config"]) for row in rows.values()),
    ]
    if env_file is not None:
        paths.append(env_file)
    return {str(path): _file_hash(path) for path in paths}


def _bundle(inventory):
    import yaml

    value = yaml.safe_load(inventory.runtime_release.read_text())
    root = inventory.runtime_release.parent
    paths = [
        inventory.runtime_release,
        root / value["requirements"]["path"],
        root / value["wheelhouse"]["manifest"],
    ]
    paths.extend(
        path
        for path in (root / value["wheelhouse"]["path"]).rglob("*")
        if path.is_file()
    )
    return {
        "requirements": value["requirements"]["path"],
        "wheelhouse": value["wheelhouse"]["path"],
        "files": [
            {
                "path": str(path.relative_to(root)),
                "sha256": _file_hash(path),
                "data": base64.b64encode(path.read_bytes()).decode(),
            }
            for path in paths
        ],
    }


def _directory(inventory, operation_id):
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", operation_id) is None:
        raise QueueConfigError(
            "operation ID must be a simple identifier of at most 100 characters"
        )
    return inventory.path.parent / "operations" / operation_id


def operation_status(inventory, operation_id):
    """Read retained administration only; status never resumes a host operation."""
    directory = _directory(inventory, operation_id)
    if not (directory / "intent.json").exists():
        raise QueueConfigError("unknown administrative operation")
    intent = read(directory / "intent.json")
    result = (
        read(directory / "result.json")
        if (directory / "result.json").exists()
        else {"state": "pending"}
    )
    steps = {}
    for step in sorted((directory / "steps").glob("*")):
        receipt = step / "receipt.json"
        dispatch = step / "dispatch.json"
        if receipt.exists():
            value = read(receipt)
            steps[step.name] = {
                "native_outcome": value.get(
                    "native_outcome",
                    "not_applied" if value.get("outcome") == "unchanged" else "applied",
                ),
                "reason": None,
            }
        elif dispatch.exists():
            value = read(dispatch)
            steps[step.name] = {
                "native_outcome": "unknown",
                "reason": value.get("reason"),
            }
        else:
            steps[step.name] = {
                "native_outcome": "not_applied",
                "reason": "not_dispatched",
            }
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        "fleet": inventory.name,
        "steps": steps,
        "outcome": result["state"],
        "ready": result["state"] == "complete",
        "intent_digest": digest(intent),
        **result,
    }


class _Operation:
    def __init__(self, inventory, directory, intent):
        self.inventory, self.directory, self.intent = inventory, directory, intent
        self.receipts = directory / "steps"
        protected_directory(self.receipts)

    def recheck_composed(self, pending_inputs=None):
        updates_path = self.directory / "accepted-inputs.json"
        updates = read(updates_path) if updates_path.exists() else {}
        accepted = {**updates, **(pending_inputs or {})}
        for name, row in self.intent["hosts"].items():
            path = Path(row["config"])
            expected_hash = accepted.get(str(path), self.intent["inputs"][str(path)])
            # A changed top file may be a retained native publication awaiting
            # its receipt. call() reconciles that exact publication before the
            # ordinary byte check; unchanged top files cannot hide include edits.
            if _file_hash(path) != expected_hash:
                continue
            expected = (
                read(path)
                if str(path) in accepted
                else self.intent["declarations"][name]
            )
            current = _load_protected_config(
                path,
                env_file=None if row["env_file"] is None else Path(row["env_file"]),
            )[2]
            if current != expected:
                raise QueueConflictError("composed role changed since operation intent")

    def recheck(self, pending_inputs=None):
        self.recheck_composed(pending_inputs)
        updates = (
            read(self.directory / "accepted-inputs.json")
            if (self.directory / "accepted-inputs.json").exists()
            else {}
        )
        for path, expected in {
            **self.intent["inputs"],
            **updates,
            **(pending_inputs or {}),
        }.items():
            if _file_hash(Path(path)) != expected:
                raise QueueConflictError(
                    "input changed since operation intent; new plan required"
                )
        if verify_release(self.inventory.runtime_release) != self.intent["release"]:
            raise QueueConflictError("immutable service bundle changed")

    def call(self, name, action, **values):
        self.recheck_composed()
        key = (
            name
            + "-"
            + action
            + ("-" + values["agent_id"] if "agent_id" in values else "")
        )
        directory = self.receipts / key
        protected_directory(directory)
        row = self.intent["hosts"][name]
        request = {
            key: row[key]
            for key in ("name", "host", "config", "root", "env_file", "env_sha256")
        }
        request.update(
            action=action,
            release=self.intent["release"],
            request_id=self.intent["operation_id"]
            + "-"
            + hashlib.sha256(key.encode()).hexdigest()[:16],
            **values,
        )
        path = directory / "intent.json"
        if path.exists():
            retained = read(path)
            if {
                key: value
                for key, value in retained.items()
                if key != "expected_declaration"
            } != request:
                raise QueueConflictError("retained host intent differs")
            request = retained
        else:
            if action != "install":
                request["expected_declaration"] = digest(
                    _load_protected_config(
                        Path(row["config"]),
                        env_file=None
                        if row["env_file"] is None
                        else Path(row["env_file"]),
                    )[2]
                )
            atomic(path, request)
        receipt = directory / "receipt.json"
        if receipt.exists():
            response = read(receipt)
            self.accept_update(name, response, directory)
            return response
        pending_inputs = {}
        if (directory / "dispatch.json").exists() and action != "install":
            response = ssh(row["host"], {**request, "action": "receipt"})
            if response is not None and "pending_publication" in response:
                candidate = json.dumps(
                    response["pending_publication"]["after"], sort_keys=True
                ).encode()
                if Path(row["config"]).read_bytes() == candidate:
                    pending_inputs[row["config"]] = hashlib.sha256(
                        candidate
                    ).hexdigest()
            elif response is not None:
                atomic(receipt, response)
                self.accept_update(name, response, directory)
                return response
        self.recheck(pending_inputs)
        atomic(
            directory / "dispatch.json",
            {"request_id": request["request_id"], "outcome": "unknown"},
        )
        try:
            response = ssh(row["host"], request)
        except (SshUnavailable, QueueConflictError) as exc:
            atomic(
                directory / "dispatch.json",
                {
                    "request_id": request["request_id"],
                    "outcome": "unknown",
                    "reason": str(exc),
                },
            )
            raise
        atomic(receipt, response)
        self.accept_update(name, response, directory)
        return response

    def accept_update(self, name, response, directory):
        self.recheck_composed()
        marker = directory / "local-input.json"
        if marker.exists() or "declaration" not in response:
            return
        path = Path(self.intent["hosts"][name]["config"])
        updates_path = self.directory / "accepted-inputs.json"
        updates = read(updates_path) if updates_path.exists() else {}
        current = _load_protected_config(path)[2]
        if current != response["declaration"]:
            expected = updates.get(str(path), self.intent["inputs"][str(path)])
            if _file_hash(path) != expected:
                raise QueueConflictError(
                    "operator role changed during native enrollment"
                )
            atomic(path, response["declaration"])
        updates[str(path)] = _file_hash(path)
        atomic(updates_path, updates)
        atomic(marker, {"sha256": updates[str(path)]})

    def observe(self, name, **values):
        row = self.intent["hosts"][name]
        return ssh(
            row["host"],
            {
                **{
                    key: row[key]
                    for key in (
                        "name",
                        "host",
                        "config",
                        "root",
                        "env_file",
                        "env_sha256",
                    )
                },
                "action": "observe",
                "expected_declaration": digest(
                    _load_protected_config(
                        Path(row["config"]),
                        env_file=None
                        if row["env_file"] is None
                        else Path(row["env_file"]),
                    )[2]
                ),
                "release": self.intent["release"],
                **values,
            },
        )


def apply(
    inventory,
    *,
    operation_id,
    hosts=None,
    issuer=None,
    env_file=None,
    resume=False,
    check_selection=None,
):
    """Apply or continue the immutable selected setup; unknown replies retain IDs."""
    directory = _directory(inventory, operation_id)
    if resume and not (directory / "intent.json").exists():
        raise QueueConfigError("unknown administrative operation; cannot resume")
    protected_directory(directory)
    with (directory / "writer.lock").open("a") as writer:
        try:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QueueConflictError("operation already has an active writer") from exc
        return _apply_locked(
            inventory,
            directory,
            operation_id=operation_id,
            hosts=hosts,
            issuer=issuer,
            env_file=env_file,
            resume=resume,
            check_selection=check_selection,
        )


def _normalized_checks(selection):
    if selection is None:
        return None
    result = {key: value for key, value in selection.items() if value is not None}
    for key in ("deployment", "operator_connection"):
        if key in result:
            result[key] = str(Path(result[key]).resolve())
    return result


def _apply_locked(
    inventory,
    directory,
    *,
    operation_id,
    hosts,
    issuer,
    env_file,
    resume,
    check_selection,
):
    check_selection = _normalized_checks(check_selection)
    if not (directory / "intent.json").exists():
        if resume:
            raise QueueConfigError("unknown administrative operation; cannot resume")
        preview = plan(inventory, hosts=hosts, issuer=issuer, env_file=env_file)
        if any(
            "unavailable" in row or "conflict" in row
            for row in preview["hosts"].values()
        ):
            raise QueueConfigError(
                "selected host prerequisites unavailable; inspect plan"
            )
        if issuer is None and any(
            not row["observation"]["credentials_complete"]
            or row["credential_binding"] == "pending"
            for row in preview["hosts"].values()
        ):
            raise QueueConfigError(
                "unbound credentials require explicit coordinator-local --issuer before setup"
            )
        rows, declarations = _selection(inventory, hosts, env_file)
        release = verify_release(inventory.runtime_release)
        _validate_checks(inventory, check_selection, declarations)
        check_selection = cast(dict[str, Any], check_selection)
        intent = {
            "schema_version": 1,
            "operation_id": operation_id,
            "hosts": rows,
            "declarations": declarations,
            "release": release,
            "inputs": _inputs(inventory, rows, env_file),
            "issuer": None if issuer is None else str(issuer),
            "check_selection": check_selection,
            "nonce": uuid4().hex,
            "fresh_coordinator": not preview["hosts"]["coordinator"]["observation"][
                "root_exists"
            ],
        }
        intent["inputs"][check_selection["deployment"]] = _file_hash(
            Path(check_selection["deployment"])
        )
        if check_selection.get("operator_connection"):
            intent["inputs"][check_selection["operator_connection"]] = _file_hash(
                Path(check_selection["operator_connection"])
            )
        protected_directory(directory)
        atomic(directory / "intent.json", intent)
    else:
        intent = read(directory / "intent.json")
        if not resume:
            rows, declarations = _selection(inventory, hosts, env_file)
            same_hosts = {
                n: (r["host"], r["config"], r["root"]) for n, r in rows.items()
            } == {
                n: (r["host"], r["config"], r["root"])
                for n, r in intent["hosts"].items()
            }
            same_checks = (
                check_selection is None
                or check_selection == _normalized_checks(intent["check_selection"])
            )
            same_environment = same_hosts and all(
                row["env_file"] == intent["hosts"][name]["env_file"]
                for name, row in rows.items()
            )
            if (
                not same_hosts
                or not same_checks
                or not same_environment
                or (issuer is not None and str(issuer) != intent["issuer"])
            ):
                raise QueueConflictError(
                    "operation ID already names different selected inputs"
                )
    operation = _Operation(inventory, directory, intent)
    atomic(directory / "result.json", {"state": "running"})
    try:
        result = _continue(operation)
    except SshUnavailable:
        result = {
            "state": "waiting",
            "reason": "SSH outcome unknown; resume the same operation",
        }
    except CoordinatorClientError as exc:
        result = {
            "state": "waiting"
            if exc.code in {"unavailable", "deadline_exceeded"}
            else "blocked",
            "reason": exc.code,
        }
    except (QueueConfigError, QueueConflictError, OSError) as exc:
        result = {"state": "blocked", "reason": str(exc)}
    atomic(directory / "result.json", result)

    return operation_status(inventory, operation_id)


def _validate_checks(inventory, selected, declarations):
    from loom.deployment import load_deployment

    if selected is None or not selected.get("deployment"):
        raise QueueConfigError(
            "setup requires explicit --deployment and its shared preparation source/profile"
        )
    selection = load_deployment(selected["deployment"])
    if selection.source.mode != "shared" or selection.agent is not None:
        raise QueueConfigError(
            "setup probes require a shared source without a local agent selection"
        )
    if (
        selection.coordinator is not None
        and selection.coordinator.config != inventory.hosts[0].config
    ):
        raise QueueConfigError(
            "fresh check creation must select the inventory coordinator role"
        )
    coordinator = declarations["coordinator"]
    preparation = coordinator.get("preparation") or {}
    from loom.fleet.configuration import exclude_captures

    captures = [
        (inventory.hosts[0].config.parent / source["path"]).resolve()
        for source in preparation.get("source_roots", {}).values()
    ]
    for private in [
        inventory.path,
        *(entry.config for entry in inventory.hosts),
        inventory.path.parent / "operations",
        inventory.path.parent / "credentials",
    ]:
        exclude_captures(private, captures)
    policy = preparation.get("profiles", {}).get(selection.preparation_profile)
    if policy is None or selection.source.root not in preparation.get(
        "source_roots", {}
    ):
        raise QueueConfigError(
            "selected probe source/profile is not declared by the coordinator"
        )
    if selection.connection is None:
        for kind in ("client", "operator"):
            chosen = selected.get(kind + "_credential_id")
            principals = [
                p
                for p in coordinator["agent_policy"].get("principals", [])
                if p["role"] == kind
                and (chosen is None or p["credential_id"] == chosen)
            ]
            if len(principals) != 1:
                raise QueueConfigError(
                    "select one already-authored " + kind + " credential ID"
                )
    elif not selected.get("operator_connection"):
        raise QueueConfigError(
            "existing deployment checks require --connection with operator credentials"
        )


def _fingerprint(certificate):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest()


def _connections(operation, coordinator_id, ca):
    from loom.deployment import load_deployment, export_connection_deployment
    from loom.queue.deployment import load_coordinator_connection_file
    from loom.fleet._host import csr, keep

    selected = operation.intent["check_selection"]
    selection = load_deployment(selected["deployment"])
    if selection.connection is not None:
        connection = load_coordinator_connection_file(selection.connection)
        operator = Path(selected["operator_connection"])
        if (
            connection.expected_coordinator_id != coordinator_id
            or load_coordinator_connection_file(operator).expected_coordinator_id
            != coordinator_id
        ):
            raise QueueConflictError("selected connections pin a different coordinator")
        return Path(selected["deployment"]), operator
    connections = {}
    coordinator = operation.intent["declarations"]["coordinator"]
    for kind in ("client", "operator"):
        chosen = selected.get(kind + "_credential_id")
        principal = [
            p
            for p in coordinator["agent_policy"]["principals"]
            if p["role"] == kind and (chosen is None or p["credential_id"] == chosen)
        ][0]
        credential = principal["credential_id"]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", credential) is None:
            raise QueueConfigError(
                "credential ID must be a simple identifier for protected leaf storage"
            )
        directory = (
            operation.inventory.path.parent / "credentials" / "principals" / credential
        )
        protected_directory(directory)
        key = directory / "leaf.key"
        certificate = directory / "leaf.crt"
        previous_issuance = (
            operation.receipts / ("coordinator-issue-" + credential) / "intent.json"
        )
        bound = (
            credential
            in coordinator["agent_server"]["credential_fingerprints"].values()
        )
        if (
            certificate.exists() or previous_issuance.exists() or bound
        ) and not key.exists():
            raise QueueConflictError("bound operator leaf key missing; no replacement")
        if not certificate.exists():
            if bound and not previous_issuance.exists():
                raise QueueConflictError(
                    "bound operator leaf certificate missing; preserve its original issuance"
                )
            if previous_issuance.exists() and not key.with_suffix(".csr").exists():
                raise QueueConflictError(
                    "retained certificate request missing; no regeneration"
                )
            operation.recheck()
            pending = csr(key, credential)
            issued = operation.call(
                "coordinator",
                "issue",
                agent_id=credential,
                csr=pending.read_text(),
                issuer=operation.intent["issuer"],
                issuer_fingerprint=_fingerprint(ca),
            )
            keep(certificate, issued["certificate"].encode())
        keep(directory / "ca.crt", ca.encode())
        from loom.fleet._credentials import validate_certificate

        validate_certificate(certificate, directory / "ca.crt", key=key)
        operation.call(
            "coordinator",
            "bind",
            agent_id=credential,
            credential_id=credential,
            principal_role=kind,
            coordinator_id=None
            if operation.intent["fresh_coordinator"]
            else coordinator_id,
            certificate_fingerprint=_fingerprint(certificate.read_text()),
        )
        if coordinator_id is None:
            continue
        connection = directory / (coordinator_id + ".json")
        url = next(
            value["url"]
            for name, value in operation.intent["declarations"].items()
            if name != "coordinator"
        )
        keep(
            connection,
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "loom.coordinator-client",
                    "expected_coordinator_id": coordinator_id,
                    "transport": {
                        "kind": "https",
                        "url": url,
                        "server_ca_path": str(directory / "ca.crt"),
                        "certificate_path": str(certificate),
                        "private_key_path": str(key),
                    },
                },
                sort_keys=True,
            ).encode(),
        )
        connections[kind] = connection
    if coordinator_id is None:
        return None, None
    destination = operation.directory / "deployment.json"
    if destination.exists():
        exported = load_deployment(destination)
        if (
            exported.connection != connections["client"]
            or exported.source != selection.source
            or exported.preparation_profile != selection.preparation_profile
        ):
            raise QueueConflictError("retained client export differs")
    else:
        export_connection_deployment(
            dataclasses.replace(selection, connection=connections["client"]),
            destination,
        )
    return destination, connections["operator"]


def _continue(operation):
    intent = operation.intent
    declarations = intent["declarations"]
    workers = [name for name in intent["hosts"] if name != "coordinator"]
    if not workers:
        raise QueueConfigError(
            "setup requires at least one selected separate agent for checks"
        )
    hostname = urlsplit(declarations[workers[0]]["url"]).hostname
    bundle = _bundle(operation.inventory)
    for name in intent["hosts"]:
        operation.call(name, "install", **bundle)
    trust = operation.call(
        "coordinator",
        "prepare",
        declaration=declarations["coordinator"],
        issuer=intent["issuer"],
        hostname=hostname,
    )
    if intent["fresh_coordinator"]:
        _connections(operation, None, trust["ca"])
    initialized = operation.call("coordinator", "initialize")
    coordinator_id = initialized["owner"]
    operation.call("coordinator", "start", expected_root_id=coordinator_id)
    deployment, operator = cast(
        tuple[Path, Path], _connections(operation, coordinator_id, trust["ca"])
    )
    identities = {"coordinator": coordinator_id}
    for name in workers:
        prepared = operation.call(name, "prepare", declaration=declarations[name])
        if prepared["csr"] is not None:
            signed = operation.call(
                "coordinator",
                "issue",
                agent_id=name,
                csr=prepared["csr"],
                issuer=intent["issuer"],
                issuer_fingerprint=trust["issuer_fingerprint"],
            )
            certificate = signed["certificate"]
            operation.call(name, "receive", certificate=certificate, ca=signed["ca"])
        else:
            certificate = prepared["certificate"]
        initialized = operation.call(name, "initialize")
        identities[name] = initialized["owner"]
        devices = initialized["gpu_devices"]
        operation.call(
            "coordinator",
            "enroll",
            agent_id=name,
            coordinator_id=coordinator_id,
            registration=declarations[name]["registration"],
            gpu_devices=devices,
            profile=initialized["profile"],
            certificate=certificate,
            certificate_fingerprint=_fingerprint(certificate),
        )
        operation.call(
            name,
            "start",
            expected_root_id=identities[name],
            coordinator_id=coordinator_id,
        )
    operation.recheck()
    for name, identity in identities.items():
        fact = operation.observe(name)
        if fact["owner"] != identity:
            raise QueueConflictError("retained native identity changed")
    from loom.coordinator import CoordinatorOperatorClient

    deadline = time.monotonic() + 30
    with cast(
        CoordinatorOperatorClient,
        CoordinatorOperatorClient.from_connection_file(operator),
    ) as client:
        while True:
            if all(client.observe_agent(name).value.get("offer") for name in workers):
                break
            if time.monotonic() >= deadline:
                return {
                    "state": "waiting",
                    "reason": "fresh native resource offers unavailable",
                    "identities": identities,
                }
            time.sleep(0.1)
    from loom.fleet.self_tests import self_test

    results = {}
    for name in workers:
        child = operation.directory / "checks" / name
        protected_directory(child)
        native_intents = list((child / "checks").glob("*/intent.json"))
        if len(native_intents) > 1:
            raise QueueConflictError("multiple native check identities; no replacement")
        child_inventory = dataclasses.replace(
            operation.inventory, path=child / "fleet.json"
        )
        has_gpu = bool(
            read(operation.receipts / (name + "-initialize") / "receipt.json")[
                "gpu_devices"
            ]
        )
        results[name] = self_test(
            child_inventory,
            deployment=deployment,
            operator_connection=operator,
            config=intent["check_selection"]["config"],
            agent_id=name,
            checks=("cpu", "storage", "gpu") if has_gpu else ("cpu", "storage"),
            operation_id=native_intents[0].parent.name if native_intents else None,
        )
    state = (
        "complete"
        if all(result["outcome"] == "passed" for result in results.values())
        else "waiting"
    )
    if any(
        result["outcome"] in {"failed", "unsupported"} for result in results.values()
    ):
        state = "blocked"
    return {
        "state": state,
        "identities": identities,
        "checks": results,
        "deployment": str(deployment),
        "operator_connection": str(operator),
        "boot_start": False,
    }
