"""Thin protected inventory; native declarations remain the policy owner."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from loom.queue.deployment import _load_protected_config, _protected_input_path
from loom.queue.errors import QueueConfigError, QueueConflictError


@dataclass(frozen=True)
class Host:
    """Native role and optional protected environment reference."""

    name: str
    host: str
    config: Path
    env_file: Path | None = None


@dataclass(frozen=True)
class Inventory:
    path: Path
    name: str
    runtime_release: Path
    service_manager: str
    hosts: tuple[Host, ...]

    def select(self, names: list[str] | None) -> tuple[Host, ...]:
        if names is None:
            return self.hosts
        if not names or set(names) - {host.name for host in self.hosts}:
            raise QueueConfigError("--hosts must name inventory entries")
        return tuple(host for host in self.hosts if host.name in names)


def _environment_files(
    inventory: Inventory, override: Path | None
) -> dict[str, Path | None]:
    """Select native environments and reject an explicit conflicting global file."""
    global_file = None if override is None else Path(override).resolve()
    selected = {}
    for host in inventory.hosts:
        bound = None if host.env_file is None else host.env_file.resolve()
        if bound is not None and global_file is not None and bound != global_file:
            raise QueueConfigError(
                "--env-file conflicts with inventory environment binding: " + host.name
            )
        selected[host.name] = bound if bound is not None else global_file
    return selected


def fleet_path(name: str) -> Path:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) is None:
        raise QueueConfigError("fleet name must be a simple identifier")
    root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "loom" / "fleets" / name / "fleet.yaml"


def exclude_captures(path: Path, capture_roots: list[Path]) -> None:
    """Reject overlapping resolved local paths, without guessing from the cwd."""
    selected = path.resolve()
    for capture in capture_roots:
        root = capture.resolve()
        if selected.is_relative_to(root) or root.is_relative_to(selected):
            raise QueueConfigError(
                "private configuration must be separate from capture roots"
            )


def protected_directory(path: Path) -> None:
    """Create absent parents owner-only; refuse an insecure existing destination."""
    if path.exists():
        info = path.stat()
        if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise QueueConfigError("Fleet directory must be owner-protected")
        return
    if not path.parent.exists():
        protected_directory(path.parent)
    path.mkdir(mode=0o700)


def write_new(path: Path, value: object) -> None:
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def load_inventory(path: Path) -> Inventory:
    source, _, value, _ = _load_protected_config(path)
    info = source.parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise QueueConfigError("Fleet directory must be owner-protected")
    if (
        set(value)
        != {
            "schema_version",
            "name",
            "runtime_release",
            "service_manager",
            "coordinator",
            "agents",
        }
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise QueueConfigError("Fleet inventory schema is invalid")
    name = value["name"]
    if not isinstance(name, str) or not name:
        raise QueueConfigError("Fleet name is required")
    manager = value["service_manager"]
    if manager not in ("systemd-user", "tmux"):
        raise QueueConfigError("unsupported service_manager")
    release = value["runtime_release"]
    if not isinstance(release, str) or not release:
        raise QueueConfigError("runtime_release is required")
    agents = value["agents"]
    if not isinstance(agents, dict) or "coordinator" in agents:
        raise QueueConfigError(
            "agents must be a map without the reserved coordinator key"
        )
    hosts = []
    for key, entry in {"coordinator": value["coordinator"], **agents}.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(entry, dict)
            or not {"host", "config"} <= set(entry) <= {"host", "config", "env_file"}
            or any(not isinstance(v, str) or not v for v in entry.values())
        ):
            raise QueueConfigError(
                "Fleet entries require an explicit SSH alias and native config"
            )
        hosts.append(
            Host(
                key,
                entry["host"],
                (source.parent / entry["config"]).resolve(),
                None
                if "env_file" not in entry
                else _protected_input_path(
                    source.parent / entry["env_file"], label="Fleet environment"
                ),
            )
        )
    return Inventory(
        source, name, (source.parent / release).resolve(), manager, tuple(hosts)
    )


def init_fleet(
    name: str, *, service_manager: str, capture_roots: list[Path]
) -> dict[str, Any]:
    path = fleet_path(name)
    exclude_captures(path.parent, capture_roots)
    if service_manager not in {"systemd-user", "tmux"}:
        raise QueueConfigError("unsupported service_manager")
    template = {
        "schema_version": 1,
        "name": name,
        "runtime_release": "releases/loom-service.yaml",
        "service_manager": service_manager,
        "coordinator": {
            "host": "CHOOSE_COORDINATOR_SSH_ALIAS",
            "config": "roles/coordinator.yaml",
        },
        "agents": {},
    }
    if path.exists():
        current = load_inventory(path)
        if current.name != name or current.service_manager != service_manager:
            raise QueueConflictError(
                "initialization conflicts with populated inventory"
            )
        protected_directory(path.parent)
        return {
            "schema_version": 1,
            "outcome": "unchanged",
            "path": str(path),
            "next": "Complete native role and immutable release choices; run preflight.",
        }
    if path.parent.exists() and any(path.parent.iterdir()):
        raise QueueConflictError(
            "initialization destination is populated without a Fleet inventory"
        )
    protected_directory(path.parent)
    for directory in ("roles", "releases"):
        protected_directory(path.parent / directory)
    write_new(path, template)
    for file, kind in (
        ("roles/coordinator.yaml", "loom.coordinator-service"),
        ("releases/loom-service.yaml", "loom.service-release"),
    ):
        write_new(
            path.parent / file,
            {
                "kind": kind,
                "missing_choices": "Replace with your native role declaration or immutable release descriptor; see docs/fleet.md.",
            },
        )
    _protected_input_path(path, label="Fleet inventory")
    return {
        "schema_version": 1,
        "outcome": "created",
        "path": str(path),
        "next": "Choose coordinator/agent aliases and native roles, service bundle and operator connection.",
    }
