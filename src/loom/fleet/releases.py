"""Verify exact local service bundle inputs without invoking an installer."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from loom.queue.errors import QueueConfigError, QueueConflictError


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _contained(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise QueueConfigError("release paths must be relative to their bundle")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise QueueConfigError("release path escapes its bundle")
    return path


def _hashed_file(
    root: Path, value: object, *, fields: set[str]
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != fields:
        raise QueueConfigError("invalid release artifact fields")
    path = _contained(root, value["path"])
    digest = value["sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise QueueConfigError("release SHA-256 is invalid")
    return path, value


def verify_release(path: Path, *, previous: Path | None = None) -> dict[str, Any]:
    """Hash the selected descriptor, requirements, manifest and every wheel.

    This proves local bytes only, not installation, target compatibility or a
    complete resolved dependency graph. The operator prepares an offline,
    transitive hash lock using standard packaging tools; installation remains
    responsible for checking that graph against the selected interpreter.
    """
    import yaml
    from packaging.requirements import Requirement, InvalidRequirement
    from packaging.utils import canonicalize_name, parse_wheel_filename

    payload = path.read_bytes()
    value = yaml.safe_load(payload)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "kind",
            "release_id",
            "python",
            "requirements",
            "wheelhouse",
        }
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["kind"] != "loom.service-release"
    ):
        raise QueueConfigError("service release schema is invalid")
    if value["python"] != "3.12":
        raise QueueConfigError("unsupported Python: service releases require 3.12")
    if not isinstance(value["release_id"], str) or not value["release_id"]:
        raise QueueConfigError("release_id is required")
    root = path.resolve().parent
    requirements, req = _hashed_file(
        root, value["requirements"], fields={"path", "sha256"}
    )
    wheels, wheel = _hashed_file(
        root, value["wheelhouse"], fields={"path", "manifest", "sha256"}
    )
    manifest = _contained(root, wheel["manifest"])
    if _digest(requirements) != req["sha256"] or _digest(manifest) != wheel["sha256"]:
        raise QueueConfigError("release requirements or manifest hash changed")
    entries: dict[str, tuple[str, str]] = {}
    for line in manifest.read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line)
        if match is None:
            raise QueueConfigError("wheel manifest must use SHA-256 sum lines")
        digest, filename = match.groups()
        selected = _contained(wheels, filename)
        if (
            filename in entries
            or selected.suffix != ".whl"
            or not selected.is_file()
            or _digest(selected) != digest
        ):
            raise QueueConfigError("selected wheel is missing, duplicated or changed")
        try:
            package, version, _, _ = parse_wheel_filename(selected.name)
        except ValueError as exc:
            raise QueueConfigError("invalid wheel filename") from exc
        entries[filename] = (str(package), str(version))
    if not entries:
        raise QueueConfigError("wheel manifest is empty")
    actual = {str(p.relative_to(wheels)) for p in wheels.rglob("*") if p.is_file()}
    if actual != set(entries):
        raise QueueConfigError("wheelhouse must contain exactly its manifest's wheels")
    hashes = {
        line.split()[1].lstrip("*"): line.split()[0]
        for line in manifest.read_text().splitlines()
    }
    locked: set[str] = set()
    text = requirements.read_text().replace("\\\n", " ")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Deliberately accept only pinned, hashed requirements. Installer flags,
        # nested files and URL sources would create an unverified input channel.
        pieces = re.split(r"\s+--hash=sha256:", line)
        try:
            requirement = Requirement(pieces[0])
        except InvalidRequirement as exc:
            raise QueueConfigError(
                "service requirements must be pinned and hashed"
            ) from exc
        specs = list(requirement.specifier)
        if (
            requirement.url
            or len(specs) != 1
            or specs[0].operator != "=="
            or "*" in specs[0].version
            or len(pieces) < 2
            or any(re.fullmatch(r"[0-9a-f]{64}", h.strip()) is None for h in pieces[1:])
        ):
            raise QueueConfigError(
                "service requirements must be exact pins with SHA-256 hashes"
            )
        name = canonicalize_name(requirement.name)
        matching = [
            file
            for file, identity in entries.items()
            if identity == (name, specs[0].version)
        ]
        if not matching or any(
            hashes[file] not in {h.strip() for h in pieces[1:]} for file in matching
        ):
            raise QueueConfigError(
                "locked requirement has no matching hashed offline wheel"
            )
        if name == "loom" and "fleet" not in requirement.extras:
            raise QueueConfigError("service requirements must include loom[fleet]")
        locked.add(name)
    if "loom" not in locked or {identity[0] for identity in entries.values()} - locked:
        raise QueueConfigError(
            "service lock must include Loom and every selected wheel"
        )
    result = {
        "release_id": value["release_id"],
        "descriptor_sha256": hashlib.sha256(payload).hexdigest(),
        "requirements_sha256": req["sha256"],
        "manifest_sha256": wheel["sha256"],
        "python": "3.12",
        "wheel_count": len(entries),
        "scope": "local_bundle_bytes",
        "installed": False,
    }
    if previous is not None:
        retained = verify_release(previous)
        if retained["release_id"] == result["release_id"] and retained != result:
            raise QueueConflictError("same release label has different immutable bytes")
    return result
