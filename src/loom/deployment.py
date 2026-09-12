"""Protected deployment selection and explicit local service availability.

Paths in a selection are relative to that protected file. Experiment paths are
relative to its selected preparation project, identically for Unix and HTTPS.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Any, cast

from loom.coordinator import CoordinatorClient, CoordinatorClientError
from loom.queue.deployment import (
    _load_protected_config,
    _protected_input_path,
    load_coordinator_connection_file,
    load_coordinator_service_config,
    load_outbound_agent_service_config,
)
from loom.queue.errors import QueueConfigError, QueueConflictError, QueueServiceError
from loom.queue.local_daemon import (
    LocalDaemon,
    _acquire_lock,
    _open_root,
    _validate_deployment_binding,
)
from loom.queue.preparation import PreparationSource


@dataclass(frozen=True)
class LocalRole:
    config: Path
    lifetime: str
    env_file: Path | None


@dataclass(frozen=True)
class DeploymentSelection:
    """Version-one explicit connection, creation, preparation and timing policy."""

    path: Path
    connection: Path | None
    coordinator: LocalRole | None
    agent: LocalRole | None
    binding: Path | None
    source: PreparationSource
    preparation_profile: str
    startup_seconds: float
    wait_seconds: float | None


def load_deployment(path: str | Path) -> DeploymentSelection:
    source, _, value, _ = _load_protected_config(path)
    if value.get("schema_version") != 1 or value.get("kind") != "loom.deployment":
        raise QueueConfigError("deployment selection version/kind is invalid")
    if set(value) - {
        "schema_version",
        "kind",
        "connection",
        "coordinator",
        "agent",
        "binding_path",
        "preparation",
        "startup_seconds",
        "wait_seconds",
    }:
        raise QueueConfigError("deployment selection fields are invalid")

    def reference(v: object) -> Path:
        if not isinstance(v, str) or not v:
            raise QueueConfigError("deployment reference is invalid")
        return (source.parent / v).resolve()

    def role(name: str) -> LocalRole | None:
        v = value.get(name)
        if v is None:
            return None
        if (
            not isinstance(v, Mapping)
            or set(v) - {"service_config", "lifetime", "env_file"}
            or v.get("lifetime") not in {"persistent", "run"}
        ):
            raise QueueConfigError("deployment local role is invalid")
        return LocalRole(
            reference(v.get("service_config")),
            cast(str, v["lifetime"]),
            None if v.get("env_file") is None else reference(v["env_file"]),
        )

    def duration(name: str, default: float | None) -> float | None:
        v = value.get(name, default)
        if v is None and name == "wait_seconds":
            return None
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v <= 0
            or (name == "startup_seconds" and v > 300)
        ):
            raise QueueConfigError("deployment timing policy is invalid")
        return float(v)

    coordinator, agent = role("coordinator"), role("agent")
    connection = (
        None if value.get("connection") is None else reference(value["connection"])
    )
    binding = (
        None if value.get("binding_path") is None else reference(value["binding_path"])
    )
    if coordinator is None and connection is None:
        raise QueueConfigError("deployment requires a coordinator selection")
    if (coordinator is not None or agent is not None) and binding is None:
        raise QueueConfigError("automatic creation requires an external binding_path")
    if (
        connection is not None
        and load_coordinator_connection_file(connection).expected_coordinator_id is None
    ):
        raise QueueConfigError(
            "deployment connection requires an expected coordinator identity"
        )
    preparation = value.get("preparation")
    if (
        not isinstance(preparation, Mapping)
        or set(preparation) != {"source", "profile"}
        or not isinstance(preparation["source"], Mapping)
        or not isinstance(preparation["profile"], str)
    ):
        raise QueueConfigError("deployment preparation selection is invalid")
    return DeploymentSelection(
        source,
        connection,
        coordinator,
        agent,
        binding,
        PreparationSource.from_dict(preparation["source"]),
        preparation["profile"],
        cast(float, duration("startup_seconds", 30.0)),
        duration("wait_seconds", None),
    )


def _write_binding(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise CoordinatorClientError(
            "deadline_exceeded",
            boundary="availability",
            operation="ensure",
            mutation_outcome=None,
        )


def _bind(
    selection: DeploymentSelection, attachment_id: str, deadline: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    configs: dict[str, Any] = {}
    if selection.coordinator is not None:
        role = selection.coordinator
        configs["coordinator"] = load_coordinator_service_config(
            role.config, env_file=role.env_file
        )
    if selection.agent is not None:
        role = selection.agent
        configs["agent"] = load_outbound_agent_service_config(
            role.config, env_file=role.env_file
        )
    if not configs:
        return {}, {}
    if (
        "coordinator" in configs
        and configs["coordinator"].local_agent is not None
        and "agent" in configs
    ):
        raise QueueConfigError(
            "embedded and independent local agents cannot share a deployment selection"
        )
    path = selection.binding
    assert path is not None
    roots = {
        name: (
            config.daemon.deployment_root
            if name == "coordinator"
            else config.client.agent_root
        ).resolve()
        for name, config in configs.items()
    }
    if any(path.is_relative_to(root) for root in roots.values()):
        raise QueueConfigError("creation binding must be outside role roots")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        while True:
            _check_deadline(deadline)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        if path.exists():
            _protected_input_path(path, label="creation binding")
            binding = json.loads(path.read_text())
            if binding.get("schema_version") != 1 or set(
                binding.get("roles", {})
            ) != set(configs):
                raise QueueConflictError("deployment binding conflicts")
        else:
            binding = {
                "schema_version": 1,
                "roles": {
                    name: {
                        "identity": {
                            "config": str(getattr(selection, name).config),
                            "fingerprint": config.immutable_fingerprint,
                            "root": str(roots[name]),
                            "lifetime": getattr(selection, name).lifetime,
                        },
                        "creation": not roots[name].exists(),
                        "ids": None,
                    }
                    for name, config in configs.items()
                },
            }
            # All role intents precede the first root publication, so an
            # interrupted multi-role creation replays the exact same topology.
            _write_binding(path, binding)
        for name, config in configs.items():
            role = getattr(selection, name)
            root = roots[name]
            identity = {
                "config": str(role.config),
                "fingerprint": config.immutable_fingerprint,
                "root": str(root),
                "lifetime": role.lifetime,
            }
            retained = binding["roles"].get(name)
            if retained is not None and retained["identity"] != identity:
                raise QueueConflictError("bound role configuration conflicts")
            if retained is None:
                retained = {
                    "identity": identity,
                    "creation": not root.exists(),
                    "ids": None,
                }
                binding["roles"][name] = retained
                _write_binding(path, binding)
            if not root.exists():
                if retained["ids"] is not None or not retained["creation"]:
                    raise QueueConflictError("previously bound role root is missing")
                _check_deadline(deadline)
                if name == "coordinator":
                    LocalDaemon.initialize_deployment(config.daemon)
                else:
                    from loom.queue.agent_session_transport import (
                        LocalDaemonAgentHttpClient,
                    )

                    LocalDaemonAgentHttpClient.initialize_agent_root(config.client)
            if name == "coordinator":
                _validate_deployment_binding(config.daemon)
                role_root = config.daemon.coordinator_root
                ids = {"coordinator": _open_root(role_root, role="coordinator")}
                if config.daemon.agent_root is not None:
                    ids["agent"] = _open_root(
                        config.daemon.agent_root, role="local-agent"
                    )
            else:
                role_root = root
                ids = {"agent": _open_root(root, role="local-agent")}
            if retained["ids"] is not None and retained["ids"] != ids:
                raise QueueConflictError("bound service identity conflicts")
            with sqlite3.connect(
                f"{(role_root / 'control.sqlite').as_uri()}?mode=ro", uri=True
            ) as conn:
                existing = conn.execute(
                    "SELECT value FROM root_metadata WHERE key = 'service_lifetime'"
                ).fetchone()
            if existing is not None and existing[0] != role.lifetime:
                raise QueueConflictError("retained service lifetime conflicts")
            retained["ids"] = ids
            _write_binding(path, binding)
            # Acquire the same role lock as its runtime. Online attachments go
            # through the application protocol, never around its quiescence lock.
            try:
                role_lock = _acquire_lock(role_root)
            except QueueServiceError as exc:
                if "already locked" not in str(exc):
                    raise
                role_lock = None
            if role_lock is not None:
                try:
                    with sqlite3.connect(role_root / "control.sqlite") as conn:
                        existing = conn.execute(
                            "SELECT value FROM root_metadata WHERE key = 'service_lifetime'"
                        ).fetchone()
                        if existing is not None and existing[0] != role.lifetime:
                            raise QueueConflictError(
                                "retained service lifetime conflicts"
                            )
                        conn.execute(
                            "INSERT OR IGNORE INTO root_metadata(key,value) VALUES ('service_lifetime',?)",
                            (role.lifetime,),
                        )
                        if name == "coordinator":
                            conn.execute(
                                "INSERT INTO daemon_metadata(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                (
                                    "startup-attachment:" + attachment_id,
                                    json.dumps(
                                        time.time()
                                        + max(0, deadline - time.monotonic())
                                    ),
                                ),
                            )
                        conn.commit()
                finally:
                    role_lock.close()
        return binding["roles"], configs
    finally:
        os.close(descriptor)


@dataclass
class AvailableDeployment:
    selection: DeploymentSelection
    client: CoordinatorClient
    roles: dict[str, Any]
    connection_id: str
    description: Any
    attachment_id: str

    def release(self, deadline: float | None = None) -> None:
        self.client._native_call(
            "startup_release",
            {"attachment_id": self.attachment_id},
            self.connection_id,
            deadline=deadline,
        )


def ensure_available(
    selection: DeploymentSelection, *, attachment_id: str, deadline: float | None = None
) -> AvailableDeployment:
    """Initialize/reopen only selected local roles and bound startup dispatch time."""
    deadline = min(
        time.monotonic() + selection.startup_seconds,
        deadline if deadline is not None else math.inf,
    )
    _check_deadline(deadline)
    roles, configs = _bind(selection, attachment_id, deadline)
    if selection.connection is not None:
        client = CoordinatorClient.from_connection_file(selection.connection)
    else:
        config = configs["coordinator"]
        client = CoordinatorClient.from_unix_socket(
            config.daemon.endpoint,
            expected_coordinator_id=roles["coordinator"]["ids"]["coordinator"],
        )
    if selection.connection is not None and "coordinator" in roles:
        expected = load_coordinator_connection_file(
            selection.connection
        ).expected_coordinator_id
        if expected != roles["coordinator"]["ids"]["coordinator"]:
            raise QueueConflictError(
                "connection and local coordinator identities conflict"
            )
    launched: dict[str, subprocess.Popen] = {}
    while True:
        _check_deadline(deadline)
        try:
            connection = client._native_call("handshake", {}, deadline=deadline)
            client._native_call(
                "startup_attach",
                {
                    "attachment_id": attachment_id,
                    "expires_at": time.time() + max(0, deadline - time.monotonic()),
                },
                connection.coordinator_id,
                deadline=deadline,
            )
            break
        except CoordinatorClientError as exc:
            if exc.code not in {"unavailable", "deadline_exceeded"}:
                raise
            if "coordinator" not in configs:
                raise
            if (
                "coordinator" not in launched
                or launched["coordinator"].poll() is not None
            ):
                launched["coordinator"] = _launch(selection, "coordinator")
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    if "agent" in configs:
        _check_deadline(deadline)
        launched["agent"] = _launch(selection, "agent")
        root = Path(roles["agent"]["identity"]["root"])
        while True:
            _check_deadline(deadline)
            if launched["agent"].poll() is not None:
                launched["agent"] = _launch(selection, "agent")
            with sqlite3.connect(
                f"{(root / 'control.sqlite').as_uri()}?mode=ro", uri=True
            ) as conn:
                row = conn.execute(
                    "SELECT value FROM root_metadata WHERE key='service_process'"
                ).fetchone()
            state = {} if row is None else json.loads(row[0])
            if (
                not state.get("stopped")
                and state.get("coordinator_id") == connection.coordinator_id
                and state.get("session_id")
            ):
                try:
                    process = Path(f"/proc/{state['pid']}/stat").read_text().split()
                    live = process[21] == state["started"] and process[2] != "Z"
                except FileNotFoundError:
                    live = False
                if live:
                    break
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    return AvailableDeployment(
        selection, client, roles, connection.coordinator_id, connection, attachment_id
    )


def _launch(selection: DeploymentSelection, role: str) -> subprocess.Popen:
    assert selection.binding is not None
    log = selection.binding.with_name(selection.binding.name + f".{role}.log")
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        return subprocess.Popen(
            [sys.executable, "-m", "loom.service_runtime", str(selection.path), role],
            stdin=subprocess.DEVNULL,
            stdout=descriptor,
            stderr=descriptor,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        os.close(descriptor)
