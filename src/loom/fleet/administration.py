"""Bounded Fleet observations; no SSH, service construction or native writes."""

from __future__ import annotations

import hashlib
from pathlib import Path
import ssl
from typing import Any, cast
from collections.abc import Mapping, Sequence

from loom.coordinator import CoordinatorClientError, CoordinatorOperatorClient
from loom.queue.deployment import (
    _load_protected_config,
    _protected_input_path,
    inspect_role_declaration,
    load_coordinator_connection_file,
    read_agent_spec,
)
from loom.queue.errors import QueueError, QueueConfigError
from loom.queue.operations import OperatorObservation
from loom.timestamps import utc_timestamp

from .configuration import Inventory
from .releases import verify_release


def _unavailable(reason: str, *, owner: str | None = None) -> dict[str, Any]:
    return OperatorObservation(
        owner, utc_timestamp(), None, "unknown", "unavailable", {}, reason
    ).to_dict()


def _native_failure(error: CoordinatorClientError, owner: str | None) -> dict[str, Any]:
    return OperatorObservation(
        owner,
        utc_timestamp(),
        None,
        "unknown",
        "unavailable",
        {"error": error.to_dict()},
        error.code,
    ).to_dict()


def _binding(
    inventory: Inventory, name: str, config: Path, env_file: Path | None
) -> dict[str, Any]:
    # The native coordinator policy owns agent IDs. Certificate DER fingerprints
    # map to its credential IDs; neither SSH aliases nor root IDs are agent IDs.
    coordinator = inventory.hosts[0]
    inspect_role_declaration(coordinator.config, role="coordinator", env_file=env_file)
    _, _, role, _ = _load_protected_config(coordinator.config, env_file=env_file)
    policies = cast(
        list[dict[str, Any]], cast(Mapping[str, Any], role["agent_policy"])["agents"]
    )
    selected = [policy for policy in policies if policy["agent_id"] == name]
    if len(selected) != 1:
        raise QueueConfigError(
            "inventory agent ID is absent or ambiguous in native policy"
        )
    spec = read_agent_spec(config, env_file=env_file)
    certificate = Path(str(spec.declarations["certificate_path"]))
    if not certificate.exists():
        return _unavailable("agent_certificate_unavailable", owner=name)
    _protected_input_path(
        certificate, label="agent certificate", require_owner_only=False
    )
    try:
        fingerprint = hashlib.sha256(
            ssl.PEM_cert_to_DER_cert(certificate.read_text())
        ).hexdigest()
    except ValueError as exc:
        raise QueueConfigError("agent certificate is invalid") from exc
    server = cast(Mapping[str, Any] | None, role["agent_server"])
    credential = (
        None if server is None else server["credential_fingerprints"].get(fingerprint)
    )
    if credential != selected[0]["credential_id"]:
        raise QueueConfigError(
            "inventory agent ID conflicts with native certificate binding"
        )
    return OperatorObservation(
        name,
        utc_timestamp(),
        spec.declaration_digest,
        "current",
        "available",
        {"agent_id": name, "certificate_binding": "matched", "qualified": False},
    ).to_dict()


def observe(
    inventory: Inventory,
    *,
    command: str,
    hosts: list[str] | None = None,
    connection: Path | None = None,
    env_file: Path | None = None,
    previous_release: Path | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Return non-atomic native projections and explicitly unavailable host facts.

    Preflight hashes local selected bundle bytes, but never qualifies a workload,
    starts a process or infers remote installation/storage from operator paths.
    Status and plan do not hash release or workload images.
    """
    selected = inventory.select(hosts)
    rows: dict[str, Any] = {}
    failed = False
    for host in selected:
        row: dict[str, Any] = {
            "host": host.host,
            "service_manager": _unavailable("host_observation_unavailable"),
            "native_owner": _unavailable("host_observation_unavailable"),
            "installation": _unavailable("host_installation_unavailable"),
            "storage": _unavailable("host_storage_unavailable"),
        }
        try:
            declaration = inspect_role_declaration(
                host.config,
                role="coordinator" if host.name == "coordinator" else "agent",
                env_file=env_file,
            )
            row["declaration"] = declaration.to_dict()
            if profile is not None:
                identities = cast(
                    Sequence[Mapping[str, Any]], declaration.value["profile_identities"]
                )
                matched = any(
                    identity["profile_id"] == profile for identity in identities
                )
                row["profile"] = {
                    "profile_id": profile,
                    "supported_declaration": matched,
                    "qualified": False,
                }
                failed = failed or not matched
            if host.name != "coordinator":
                row["identity_binding"] = _binding(
                    inventory, host.name, host.config, env_file
                )
            if command == "preflight":
                _, _, payload, _ = _load_protected_config(
                    host.config, env_file=env_file
                )
                credential_paths: list[tuple[object, bool]] = []
                if host.name != "coordinator":
                    credential_paths = [
                        (payload[key], key == "private_key_path")
                        for key in (
                            "server_ca_path",
                            "certificate_path",
                            "private_key_path",
                        )
                    ]
                else:
                    server = cast(Mapping[str, Any] | None, payload["agent_server"])
                    if server is not None:
                        credential_paths.extend(
                            (server[key], key == "private_key_path")
                            for key in (
                                "client_ca_path",
                                "certificate_path",
                                "private_key_path",
                            )
                        )
                    authority = cast(Mapping[str, Any], payload["authority"])
                    if authority["kind"] == "https":
                        credential_paths.extend(
                            (authority["tls"][key], key == "private_key")
                            for key in ("ca", "certificate", "private_key")
                        )
                missing = False
                for value, private in credential_paths:
                    secret = host.config.parent / str(value)
                    if secret.exists():
                        _protected_input_path(
                            secret,
                            label="native credential",
                            require_owner_only=private,
                        )
                    else:
                        missing = True
                row["credential_files"] = (
                    _unavailable("native_credentials_unavailable")
                    if missing
                    else OperatorObservation(
                        "local-files",
                        utc_timestamp(),
                        None,
                        "current",
                        "available",
                        {"permissions": "validated", "authenticated": False},
                    ).to_dict()
                )
        except (QueueError, OSError, ValueError):
            row["declaration"] = _unavailable(
                "invalid_or_unavailable_native_declaration"
            )
            failed = True
        row["native"] = _unavailable(
            "operator_connection_not_selected",
            owner=None if host.name == "coordinator" else host.name,
        )
        rows[host.name] = row
    coordinator_fact = _unavailable("operator_connection_not_selected")
    if connection is not None:
        config = load_coordinator_connection_file(connection)
        if config.expected_coordinator_id is None:
            raise QueueConfigError(
                "Fleet operator connection requires a pinned coordinator identity"
            )
        with CoordinatorOperatorClient.from_connection_file(connection) as client:
            try:
                coordinator_fact = client.observe_status().to_dict()
                for name, row in rows.items():
                    if name == "coordinator":
                        row["native"] = coordinator_fact
                    else:
                        try:
                            row["native"] = client.observe_agent(name).to_dict()
                        except CoordinatorClientError as exc:
                            row["native"] = _native_failure(
                                exc, config.expected_coordinator_id
                            )
            except CoordinatorClientError as exc:
                coordinator_fact = _native_failure(exc, config.expected_coordinator_id)
                for row in rows.values():
                    row["native"] = coordinator_fact
    release: dict[str, Any] = {"outcome": "not_requested"}
    if command == "preflight":
        try:
            release = {
                "outcome": "passed",
                **verify_release(inventory.runtime_release, previous=previous_release),
            }
        except (QueueError, OSError, ValueError):
            release = {"outcome": "failed", "reason": "invalid_or_unavailable_release"}
            failed = True
    result: dict[str, Any] = {
        "schema_version": 1,
        "command": command,
        "fleet": inventory.name,
        "outcome": "failed" if failed else "incomplete",
        "ready": False,
        "coordinator": coordinator_fact,
        "hosts": rows,
        "release": release,
        "next": "Resolve declaration failures and obtain target-host prerequisite, installation, storage and service observations; no readiness qualification was performed.",
    }
    if command == "plan":
        result["preview"] = {
            "reservation": False,
            "steps": [
                {
                    "host": name,
                    "actions": [
                        "validate native declarations and immutable release",
                        f"observe {inventory.service_manager} prerequisites on selected host",
                        "verify immutable installation and storage before explicit setup",
                    ],
                }
                for name in rows
            ],
        }
    return result
