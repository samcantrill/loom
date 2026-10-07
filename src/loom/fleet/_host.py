"""Installed native host steps for the fixed Fleet SSH protocol."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
from typing import Any, cast

from loom.queue.deployment import _load_protected_config, _protected_input_path
from loom.queue.errors import QueueConflictError
from loom.queue.operations import inspect_native_service
from loom.fleet.configuration import protected_directory
from loom.fleet import _credentials as credentials
from loom.fleet._ssh_bootstrap import local, publish


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read(path):
    _protected_input_path(path, label="Fleet host record")
    return json.loads(path.read_text())


def atomic(path, value):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".fleet-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


def keep(path, data):
    protected_directory(path.parent)
    if path.exists():
        _protected_input_path(path, label="Fleet retained file")
        if path.read_bytes() != data:
            raise QueueConflictError("retained file differs; no overwrite")
    else:
        publish(path, data)


def role(request):
    return "coordinator" if request["name"] == "coordinator" else "agent"


def native_root(request):
    root = Path(request["root"])
    return root / "coordinator" if role(request) == "coordinator" else root


def config(request):
    return Path(request["config"])


def environment(request):
    selected = request.get("env_file")
    if selected is None or not Path(selected).exists():
        return None
    selected = Path(selected)
    _protected_input_path(selected, label="native role environment")
    if hashlib.sha256(selected.read_bytes()).hexdigest() != request["env_sha256"]:
        raise QueueConflictError("host role environment changed since intent")
    return selected


def payload(request) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _load_protected_config(config(request), env_file=environment(request))[2],
    )


def run_native(request, command):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from loom.cli.main import main; raise SystemExit(main())",
            "queue",
            command,
            str(config(request)),
            "--format",
            "json",
            *(
                []
                if environment(request) is None
                else ["--env-file", str(environment(request))]
            ),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    evidence = Path(request["admin"]) / "last-native.json"
    atomic(
        evidence,
        {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
    if result.returncode:
        raise QueueConflictError(
            "native role command failed; inspect protected host evidence"
        )
    return json.loads(result.stdout)


def owner(request) -> dict[str, Any]:
    observation = inspect_native_service(native_root(request))
    if observation.availability != "available":
        raise QueueConflictError(
            "bound native root missing or incomplete; explicit recovery required"
        )
    return cast(dict[str, Any], observation.to_dict())


def issuer(request, *, fresh=False):
    if request.get("issuer") is None:
        raise QueueConflictError(
            "certificate issuance requires explicit coordinator-local --issuer"
        )
    directory = Path(request["issuer"])
    if not directory.is_absolute():
        raise QueueConflictError("issuer must be an absolute coordinator-local path")
    local(directory)
    selected = payload(request)
    captures = [
        (config(request).parent / item["path"]).resolve()
        for item in (selected.get("preparation") or {}).get("source_roots", {}).values()
    ]
    captures.extend(
        Path(item["host_path"]).resolve()
        for item in selected.get("shared_roots", {}).values()
    )
    from loom.fleet.configuration import exclude_captures

    exclude_captures(directory, captures)
    protected_directory(directory)
    ca = credentials.ensure_ca(directory, create=fresh)
    expected = request.get("issuer_fingerprint")
    if expected is not None and credentials.fingerprint(ca) != expected:
        raise QueueConflictError("retained issuer fingerprint changed")
    return directory


def csr(key, name):
    protected_directory(key.parent)
    request = key.with_suffix(".csr")
    if not key.exists():
        if request.exists():
            raise QueueConflictError("retained key missing; no regeneration")
        publish(
            key,
            credentials.openssl(
                "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"
            ),
        )
    _protected_input_path(key, label="host private key")
    if not request.exists():
        publish(
            request,
            credentials.openssl("req", "-new", "-key", key, "-subj", f"/CN={name}"),
        )
    if credentials.openssl(
        "req", "-in", request, "-pubkey", "-noout"
    ) != credentials.openssl("pkey", "-in", key, "-pubout"):
        raise QueueConflictError("retained request does not match private key")
    return request


def credential_path(request, value):
    return (config(request).parent / value).resolve()


def prepare(request, repeated):
    selected = request["declaration"]
    path = config(request)
    # Published roles retain their authored meaning; a supported enrollment is
    # the sole exception and its exact before/after inputs live in its step.
    if path.exists():
        if payload(request) != selected:
            raise QueueConflictError("target role changed since preview")
    else:
        keep(path, json.dumps(selected, sort_keys=True).encode())
    if role(request) == "agent":
        key = credential_path(request, selected["private_key_path"])
        certificate = credential_path(request, selected["certificate_path"])
        ca = credential_path(request, selected["server_ca_path"])
        if certificate.exists():
            credentials.validate_certificate(certificate, None, key=key)
            return {"certificate": certificate.read_text(), "csr": None}
        if Path(request["root"]).exists():
            raise QueueConflictError(
                "bound agent credentials unavailable; no replacement"
            )
        if repeated and not key.exists():
            raise QueueConflictError(
                "dispatched credential generation has no retained key"
            )
        return {"csr": csr(key, request["name"]).read_text(), "certificate": None}
    server = selected["agent_server"]
    certificate = credential_path(request, server["certificate_path"])
    key = credential_path(request, server["private_key_path"])
    ca = credential_path(request, server["client_ca_path"])
    if certificate.exists():
        credentials.validate_certificate(
            certificate, None, key=key, hostname=request["hostname"]
        )
        if request.get("issuer"):
            directory = issuer(request)
            if credentials.fingerprint(ca) != credentials.fingerprint(
                directory / "ca.crt"
            ):
                raise QueueConflictError("issuer differs from accepted client CA")
        return {"ca": ca.read_text(), "issuer_fingerprint": credentials.fingerprint(ca)}
    if Path(request["root"]).exists():
        raise QueueConflictError(
            "bound coordinator credentials unavailable; no replacement"
        )
    directory = issuer(request, fresh=not repeated)
    keep(ca, (directory / "ca.crt").read_bytes())
    request_path = csr(key, "coordinator")
    credentials.issue(
        directory,
        request_path,
        certificate,
        "coordinator",
        hostname=request["hostname"],
    )
    return {"ca": ca.read_text(), "issuer_fingerprint": credentials.fingerprint(ca)}


def issue(request):
    server = payload(request)["agent_server"]
    ca = credential_path(request, server["client_ca_path"])
    directory = issuer(request)
    if credentials.fingerprint(ca) != credentials.fingerprint(directory / "ca.crt"):
        raise QueueConflictError("issuer differs from native client CA")
    destination = directory / "issued" / request["request_id"]
    protected_directory(destination)
    pending = destination / "agent.csr"
    certificate = destination / "agent.crt"
    keep(pending, request["csr"].encode())
    credentials.issue(directory, pending, certificate, request["agent_id"])
    return {"certificate": certificate.read_text(), "ca": ca.read_text()}


def receive(request):
    selected = payload(request)
    ca = credential_path(request, selected["server_ca_path"])
    certificate = credential_path(request, selected["certificate_path"])
    if not ca.exists():
        keep(ca, request["ca"].encode())
    client_ca = Path(request["admin"]) / "client-ca.crt"
    keep(client_ca, request["ca"].encode())
    keep(certificate, request["certificate"].encode())
    credentials.validate_certificate(
        certificate, ca, key=credential_path(request, selected["private_key_path"])
    )
    return {"certificate_fingerprint": credentials.fingerprint(certificate)}


def initialized_observation(request):
    fact = owner(request)
    if role(request) == "agent":
        from loom.queue.deployment import load_outbound_agent_service_config
        from loom.serialization import thaw_plain_data

        service = load_outbound_agent_service_config(
            config(request), env_file=environment(request)
        )
        profile = service.client.resident_profiles[0]
        inventory = service.client.resource_inventory
        devices = profile.gpu_devices if inventory is None else inventory.gpu_devices
        fact["profile"] = thaw_plain_data(profile.descriptor.to_dict())
        fact["gpu_devices"] = [
            thaw_plain_data(device.descriptor.to_dict()) for device in devices
        ]
        fact["max_concurrent_assignments"] = service.client.max_concurrent_assignments
    return fact


def initialize(request, repeated):
    root = Path(request["root"])
    identities = set()
    for previous in (Path(request["admin"]) / "operations").glob("*/intent.json"):
        old = read(previous)
        if old["action"] != "initialize":
            continue
        receipt = previous.parent / "receipt.json"
        if receipt.exists():
            identities.add(read(receipt)["owner"])
        elif (
            old["request_id"] != request["request_id"]
            and (previous.parent / "dispatched.json").exists()
        ):
            raise QueueConflictError(
                "earlier initialization outcome is unresolved; resume that operation"
            )
    if identities and not root.exists():
        raise QueueConflictError(
            "bound native root missing; no replacement initialization"
        )
    if root.exists():
        fact = owner(request)
        if identities and identities != {fact["owner"]}:
            raise QueueConflictError("retained native root identity changed")
        run_native(
            request, "daemon-check" if role(request) == "coordinator" else "agent-check"
        )
        return initialized_observation(request)
    if repeated:
        raise QueueConflictError(
            "dispatched initialization lacks bound root; explicit recovery required"
        )
    run_native(
        request, "daemon-init" if role(request) == "coordinator" else "agent-init"
    )
    return initialized_observation(request)


def start(request):
    fact = owner(request)
    expected = request["expected_root_id"]
    if fact["owner"] != expected:
        raise QueueConflictError("native root identity changed")
    admin = Path(request["admin"])
    socket = admin / "tmux.sock"
    if len(os.fsencode(socket)) > 90:
        raise QueueConflictError("native host-local path is too long for tmux IPC")
    argv = ["tmux", "-f", "/dev/null", "-S", str(socket)]
    session = "loom"
    pane = subprocess.run(
        [*argv, "list-panes", "-t", session, "-F", "#{@loom_root}"],
        capture_output=True,
        text=True,
    )
    if pane.returncode == 0:
        if pane.stdout.strip() != expected:
            raise QueueConflictError("existing tmux owner differs")
    else:
        if fact["value"]["ownership"] == "live":
            raise QueueConflictError("native service already has a different owner")
        native_lock = native_root(request) / "owner.lock"
        if native_lock.exists():
            with native_lock.open("r") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = [
            sys.executable,
            "-c",
            "from loom.cli.main import main; raise SystemExit(main())",
            "queue",
            "daemon-serve" if role(request) == "coordinator" else "agent-serve",
            str(config(request)),
            "--format",
            "json",
        ]
        if environment(request) is not None:
            command += ["--env-file", str(environment(request))]
        if role(request) == "agent":
            command += ["--expected-coordinator-id", request["coordinator_id"]]
        shell = (
            "exec "
            + shlex.join(command)
            + " >> "
            + shlex.quote(str(admin / "service.log"))
            + " 2>&1"
        )
        subprocess.run(
            [
                *argv,
                "new-session",
                "-d",
                "-s",
                session,
                shell,
                ";",
                "set-option",
                "-t",
                session,
                "@loom_root",
                expected,
            ],
            capture_output=True,
            check=True,
        )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        fact = owner(request)
        if fact["value"]["ownership"] == "live":
            return {
                "native_owner": fact,
                "service_manager": "tmux",
                "boot_start": False,
            }
        time.sleep(0.1)
    raise QueueConflictError("native service start remains unproven")


def coordinator_client(request):
    from loom.queue import LocalDaemonSocketClient
    from loom.queue.deployment import load_coordinator_service_config

    service = load_coordinator_service_config(
        config(request), env_file=environment(request)
    )
    return service, LocalDaemonSocketClient(service.daemon.endpoint)


def coordinator_observation(request, service):
    from loom.coordinator import CoordinatorOperatorClient

    operator = cast(
        CoordinatorOperatorClient,
        CoordinatorOperatorClient.from_unix_socket(
            service.daemon.endpoint,
            expected_coordinator_id=request.get("coordinator_id"),
        ),
    )
    with operator:
        return operator.observe_status()


def enroll(request, directory):
    from loom.queue.local_daemon import CoordinatorSchedulingReload
    from loom.serialization import thaw_plain_data

    service, client = coordinator_client(request)
    observation = coordinator_observation(request, service)
    if observation.owner != request["coordinator_id"]:
        raise QueueConflictError("coordinator identity differs")
    before = payload(request)
    certificate = directory / "approved-agent.crt"
    keep(certificate, request["certificate"].encode())
    credentials.validate_certificate(
        certificate, credential_path(request, before["agent_server"]["client_ca_path"])
    )
    if credentials.fingerprint(certificate) != request["certificate_fingerprint"]:
        raise QueueConflictError("agent certificate differs from retained fingerprint")
    intent_path = directory / "reload.json"
    if intent_path.exists():
        intent = read(intent_path)
    else:
        if observation.value["scheduling_fingerprint"] != service.active_fingerprint:
            raise QueueConflictError(
                "authored policy differs from native accepted state"
            )
        after = json.loads(json.dumps(before))
        policy = after["agent_policy"]
        credential = "fleet-" + request["agent_id"]
        rule = {
            "agent_id": request["agent_id"],
            "credential_id": credential,
            "principal_id": credential,
            "pools": request["registration"]["pools"],
            "capabilities": request["registration"]["capabilities"],
            "gpu_devices": request["gpu_devices"],
        }
        existing = [
            row for row in policy["agents"] if row["agent_id"] == request["agent_id"]
        ]
        fingerprint = request["certificate_fingerprint"]
        mappings = after["agent_server"]["credential_fingerprints"]
        if existing:
            rule["credential_id"] = existing[0]["credential_id"]
            rule["principal_id"] = existing[0]["principal_id"]
            if existing != [rule] or mappings.get(fingerprint) != rule["credential_id"]:
                raise QueueConflictError(
                    "existing enrollment differs; use explicit upgrade"
                )
            return {"outcome": "unchanged", "coordinator_id": observation.owner}
        if any(
            row["credential_id"] == credential or row["principal_id"] == credential
            for row in [*policy["agents"], *policy.get("principals", [])]
        ):
            raise QueueConflictError(
                "new agent credential conflicts with existing principal"
            )
        if fingerprint in mappings or credential in mappings.values():
            raise QueueConflictError(
                "certificate mapping already belongs to another identity"
            )
        profiles = after["remote_profiles"]
        if request["profile"] not in profiles:
            raise QueueConflictError(
                "agent profile must match an accepted coordinator profile"
            )
        policy["agents"].append(rule)
        if request["agent_id"] not in policy["local_owner"]["agent_ids"]:
            policy["local_owner"]["agent_ids"].append(request["agent_id"])
        mappings[fingerprint] = credential
        intent = {
            "before": before,
            "after": after,
            "reload": CoordinatorSchedulingReload(
                request["request_id"],
                client.status().scheduling_epoch,
                "Fleet agent enrollment",
            ).to_dict(),
        }
        atomic(intent_path, intent)
    current = payload(request)
    if current == intent["before"]:
        atomic(config(request), intent["after"])
    elif current != intent["after"]:
        raise QueueConflictError("coordinator config changed during enrollment")
    result = cast(
        dict[str, Any],
        thaw_plain_data(
            client.reload_scheduling(
                CoordinatorSchedulingReload.from_dict(intent["reload"])
            )
        ),
    )
    if result.get("state") != "applied":
        raise QueueConflictError("native reload not applied")
    return {
        "outcome": "applied",
        "coordinator_id": observation.owner,
        "reload": result,
        "declaration": intent["after"],
        "config_sha256": hashlib.sha256(config(request).read_bytes()).hexdigest(),
    }


def bind_principal(request, directory):
    from loom.queue.local_daemon import CoordinatorSchedulingReload
    from loom.serialization import thaw_plain_data

    authored = payload(request)
    if request["coordinator_id"] is None:
        if Path(request["root"]).exists():
            raise QueueConflictError(
                "fresh principal binding cannot modify a bound root"
            )
        principals = [
            p
            for p in authored["agent_policy"]["principals"]
            if p["credential_id"] == request["credential_id"]
            and p["role"] == request["principal_role"]
        ]
        if len(principals) != 1:
            raise QueueConflictError("select one already-authored principal")
        mappings = authored["agent_server"]["credential_fingerprints"]
        fingerprint, credential = (
            request["certificate_fingerprint"],
            request["credential_id"],
        )
        retained = directory / "reload.json"
        if retained.exists():
            intent = read(retained)
            if authored not in (intent["before"], intent["after"]):
                raise QueueConflictError(
                    "fresh coordinator declaration changed during binding"
                )
            authored = intent["after"]
        elif mappings.get(fingerprint) != credential:
            if fingerprint in mappings or credential in mappings.values():
                raise QueueConflictError("existing credential binding differs")
            after = json.loads(json.dumps(authored))
            after["agent_server"]["credential_fingerprints"][fingerprint] = credential
            atomic(retained, {"before": authored, "after": after})
            authored = after
        if payload(request) != authored:
            atomic(config(request), authored)
        return {
            "outcome": "applied",
            "declaration": authored,
            "config_sha256": hashlib.sha256(config(request).read_bytes()).hexdigest(),
        }
    service, client = coordinator_client(request)
    observed = coordinator_observation(request, service)
    if observed.owner != request["coordinator_id"]:
        raise QueueConflictError("coordinator identity changed")
    principals = [
        p
        for p in authored["agent_policy"]["principals"]
        if p["credential_id"] == request["credential_id"]
        and p["role"] == request["principal_role"]
    ]
    if len(principals) != 1:
        raise QueueConflictError(
            "credential must select one authored principal of the required role"
        )
    retained = directory / "reload.json"
    if retained.exists():
        intent = read(retained)
    else:
        if observed.value["scheduling_fingerprint"] != service.active_fingerprint:
            raise QueueConflictError("authored policy differs from accepted state")
        mappings = authored["agent_server"]["credential_fingerprints"]
        fingerprint = request["certificate_fingerprint"]
        credential = request["credential_id"]
        if mappings.get(fingerprint) == credential:
            return {"outcome": "unchanged", "declaration": authored}
        if fingerprint in mappings or credential in mappings.values():
            raise QueueConflictError(
                "bound principal certificate differs; no replacement"
            )
        after = json.loads(json.dumps(authored))
        after["agent_server"]["credential_fingerprints"][fingerprint] = credential
        intent = {
            "before": authored,
            "after": after,
            "reload": CoordinatorSchedulingReload(
                request["request_id"],
                client.status().scheduling_epoch,
                "Fleet authored principal credential binding",
            ).to_dict(),
        }
        atomic(retained, intent)
    current = payload(request)
    if current == intent["before"]:
        atomic(config(request), intent["after"])
    elif current != intent["after"]:
        raise QueueConflictError("coordinator role changed during retained binding")
    result = cast(
        dict[str, Any],
        thaw_plain_data(
            client.reload_scheduling(
                CoordinatorSchedulingReload.from_dict(intent["reload"])
            )
        ),
    )
    if result.get("state") != "applied":
        raise QueueConflictError("native principal binding not applied")
    return {
        "outcome": "applied",
        "declaration": intent["after"],
        "reload": result,
        "config_sha256": hashlib.sha256(config(request).read_bytes()).hexdigest(),
    }


def execute(request, repeated, directory):
    action = request["action"]
    if action == "prepare":
        return prepare(request, repeated)
    if action == "issue":
        return issue(request)
    if action == "receive":
        return receive(request)
    if action == "initialize":
        return initialize(request, repeated)
    if action == "start":
        return start(request)
    if action == "enroll":
        return enroll(request, directory)
    if action == "bind":
        return bind_principal(request, directory)
    if action == "observe":
        return owner(request)
    if action == "resources":
        service, _ = coordinator_client(request)
        from loom.coordinator import CoordinatorOperatorClient

        with cast(
            CoordinatorOperatorClient,
            CoordinatorOperatorClient.from_unix_socket(service.daemon.endpoint),
        ) as client:
            return client.observe_agent(request["agent_id"]).to_dict()
    raise QueueConflictError("unsupported fixed native host action")


def main():
    os.umask(0o077)
    request = json.loads(sys.stdin.buffer.read(128 * 1024 * 1024 + 1))
    admin = Path(request["admin"])
    with (admin / "native.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if request["action"] == "receipt":
            receipt = admin / "operations" / request["request_id"] / "receipt.json"
            if receipt.exists():
                return read(receipt)
            publication = receipt.parent / "reload.json"
            return (
                {"pending_publication": read(publication)}
                if publication.exists()
                else None
            )
        if request["action"] in {"observe", "resources"}:
            if (
                request.get("expected_declaration") is not None
                and digest(payload(request)) != request["expected_declaration"]
            ):
                raise QueueConflictError(
                    "target declaration changed since expected input"
                )
            return execute(request, False, admin)
        directory = admin / "operations" / request["request_id"]
        protected_directory(directory)
        intent_path = directory / "intent.json"
        retained = {key: value for key, value in request.items() if key != "admin"}
        if intent_path.exists():
            if read(intent_path) != retained:
                raise QueueConflictError(
                    "host request ID conflicts with immutable intent"
                )
        else:
            atomic(intent_path, retained)
        receipt = directory / "receipt.json"
        if receipt.exists():
            return read(receipt)
        dispatched = directory / "dispatched.json"
        repeated = dispatched.exists()
        if not repeated:
            atomic(dispatched, {"request_id": request["request_id"]})
        if (
            request["action"] != "prepare"
            and request.get("expected_declaration") is not None
        ):
            if digest(payload(request)) != request["expected_declaration"]:
                publication = directory / "reload.json"
                if (
                    not publication.exists()
                    or payload(request) != read(publication)["after"]
                ):
                    raise QueueConflictError(
                        "target declaration changed since expected input"
                    )
        result = execute(request, repeated, directory)
        result["native_outcome"] = (
            "not_applied" if result.get("outcome") == "unchanged" else "applied"
        )
        atomic(receipt, result)
        return result


if __name__ == "__main__":
    try:
        print(json.dumps(main(), sort_keys=True))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "host_error": {
                        "code": type(exc).__name__,
                        "reason": str(exc)
                        if isinstance(exc, QueueConflictError)
                        else "native host step failed",
                    }
                }
            )
        )
        sys.exit(1)
