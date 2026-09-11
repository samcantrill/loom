"""Finite, durable-value models and shared-storage capture for preparation.

This module deliberately contains no composition or worker imports.  It is the
native boundary between an authored project tree and the coordinator's managed
preparation lifecycle.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import cast

from loom.serialization import PlainData

from .errors import QueueServiceError


_MAX_INCLUDES = 100
_MAX_FILES = 4096
_MAX_BYTES = 64 * 1024 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _relative(value: object, field: str, *, dot: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise QueueServiceError(f"preparation {field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or (path == PurePosixPath(".") and not dot):
        raise QueueServiceError(f"preparation {field} must be a contained relative path")
    if any(part in {"", "."} for part in path.parts if part != "."):
        raise QueueServiceError(f"preparation {field} is invalid")
    return str(path)


@dataclass(frozen=True, slots=True)
class PreparationSource:
    """One protected-root project selection; only ``shared`` is executable here."""

    mode: str
    root: str
    path: str
    include: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.mode not in {"shared", "staged"}:
            raise QueueServiceError("preparation source mode is invalid")
        if not isinstance(self.root, str) or not self.root:
            raise QueueServiceError("preparation source root is invalid")
        object.__setattr__(self, "path", _relative(self.path, "source path", dot=True))
        values = tuple(_relative(item, "include", dot=True) for item in self.include)
        if not values or len(values) > _MAX_INCLUDES or len(set(values)) != len(values):
            raise QueueServiceError("preparation includes must be 1..100 unique paths")
        object.__setattr__(self, "include", tuple(sorted(values)))

    def to_dict(self) -> dict[str, PlainData]:
        return {"mode": self.mode, "root": self.root, "path": self.path, "include": list(self.include)}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "PreparationSource":
        if set(data) != {"mode", "root", "path", "include"} or not isinstance(data.get("include"), list):
            raise QueueServiceError("preparation source is invalid")
        return cls(cast(str, data["mode"]), cast(str, data["root"]), cast(str, data["path"]), tuple(cast(list[str], data["include"])))


@dataclass(frozen=True, slots=True)
class PrepareRunRequest:
    """Coordinator-owned request for one idempotent preparation operation."""

    operation_id: str
    run_name: str
    source: PreparationSource
    config_path: str
    preparation_profile: str

    def __post_init__(self) -> None:
        for value, field in ((self.operation_id, "operation_id"), (self.run_name, "run_name"), (self.preparation_profile, "preparation_profile")):
            if not isinstance(value, str) or len(value) > 160 or _SAFE_ID.fullmatch(value) is None:
                raise QueueServiceError(f"preparation {field} is invalid")
        if not isinstance(self.source, PreparationSource):
            raise QueueServiceError("preparation source is invalid")
        object.__setattr__(self, "config_path", _relative(self.config_path, "config_path"))

    def to_dict(self) -> dict[str, PlainData]:
        return {"operation_id": self.operation_id, "run_name": self.run_name, "source": self.source.to_dict(), "config_path": self.config_path, "preparation_profile": self.preparation_profile}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "PrepareRunRequest":
        if set(data) != {"operation_id", "run_name", "source", "config_path", "preparation_profile"} or not isinstance(data.get("source"), Mapping):
            raise QueueServiceError("prepare request is invalid")
        return cls(cast(str, data["operation_id"]), cast(str, data["run_name"]), PreparationSource.from_dict(cast(Mapping[str, object], data["source"])), cast(str, data["config_path"]), cast(str, data["preparation_profile"]))

    def intent_digest(self, principal_id: str) -> str:
        if not isinstance(principal_id, str) or not principal_id:
            raise QueueServiceError("preparation principal is invalid")
        value = {"request": self.to_dict(), "principal_id": principal_id}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SharedInputReceipt:
    manifest_digest: str
    root: str
    path: str

    def to_dict(self) -> dict[str, PlainData]:
        return {"mode": "shared", "manifest_digest": self.manifest_digest, "reference": {"schema_version": 1, "kind": "loom.shared-preparation-input", "root": self.root, "path": self.path}}


def capture_shared_input(request: PrepareRunRequest, *, source_root: Path, snapshot_root: Path) -> SharedInputReceipt:
    """Capture selected regular files into one immutable shared snapshot.

    The walk refuses links and special files and verifies the selected bytes both
    before and while publishing.  The returned reference is relative to the
    protected snapshot root, never an arbitrary host path.
    """
    if request.source.mode != "shared":
        raise QueueServiceError("staged preparation input is unsupported")
    root = source_root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise QueueServiceError("preparation source is unavailable")
    project = _contained_path(root, request.source.path)
    if not project.is_dir():
        raise QueueServiceError("preparation source is unavailable")
    files: dict[str, Path] = {}
    for include in request.source.include:
        selected = _contained_path(project, include)
        if not selected.exists() or selected.is_symlink():
            raise QueueServiceError("preparation source is unavailable")
        candidates: Iterable[Path] = (selected.rglob("*") if selected.is_dir() else (selected,))
        for candidate in candidates:
            if candidate.is_dir():
                continue
            if candidate.is_symlink() or not candidate.is_file():
                raise QueueServiceError("preparation source contains unsupported file")
            rel = candidate.relative_to(project).as_posix()
            files[rel] = candidate
    if request.config_path not in files:
        raise QueueServiceError("preparation config_path is not included")
    if len(files) > _MAX_FILES:
        raise QueueServiceError("preparation input_limit_exceeded")
    manifest: list[dict[str, PlainData]] = []
    contents: dict[str, bytes] = {}
    total = 0
    for rel, candidate in sorted(files.items()):
        data = candidate.read_bytes()
        total += len(data)
        if total > _MAX_BYTES:
            raise QueueServiceError("preparation input_limit_exceeded")
        contents[rel] = data
        manifest.append({"path": rel, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    encoded = {"schema_version": 1, "files": manifest}
    digest = hashlib.sha256(json.dumps(encoded, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    relative = f"{request.operation_id}-{digest[:16]}"
    destination = snapshot_root / relative
    if destination.exists():
        _verify_capture(destination, encoded, digest)
        return SharedInputReceipt(digest, request.source.root, relative)
    staging = snapshot_root / f".{relative}.tmp-{os.getpid()}"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    try:
        staging.mkdir()
        for rel, candidate in files.items():
            output = staging / rel
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(contents[rel])
            if candidate.read_bytes() != contents[rel]:
                raise QueueServiceError("preparation source_changed")
        (staging / "manifest.json").write_text(json.dumps(encoded, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        _verify_capture(staging, encoded, digest)
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return SharedInputReceipt(digest, request.source.root, relative)


def _contained_path(root: Path, relative: str) -> Path:
    """Build a path only through real directory components below ``root``."""
    current = root
    for part in PurePosixPath(relative).parts:
        if part == ".":
            continue
        current = current / part
        if current.is_symlink():
            raise QueueServiceError("preparation source contains symbolic link")
    return current


def _verify_capture(directory: Path, manifest: Mapping[str, object], digest: str) -> None:
    """Verify a published capture before it becomes a reusable input receipt."""
    manifest_path = directory / "manifest.json"
    if directory.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
        raise QueueServiceError("preparation capture is incomplete")
    try:
        actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueServiceError("preparation capture is invalid") from exc
    if actual != manifest or hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != digest:
        raise QueueServiceError("preparation capture is invalid")
    entries = actual.get("files") if isinstance(actual, Mapping) else None
    if not isinstance(entries, list):
        raise QueueServiceError("preparation capture is invalid")
    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("size_bytes"), int) or not isinstance(entry.get("sha256"), str):
            raise QueueServiceError("preparation capture is invalid")
        path = _contained_path(directory, cast(str, entry["path"]))
        if not path.is_file() or path.is_symlink():
            raise QueueServiceError("preparation capture is incomplete")
        data = path.read_bytes()
        if len(data) != entry["size_bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise QueueServiceError("preparation capture is invalid")
        expected.add(cast(str, entry["path"]))
    observed = {item.relative_to(directory).as_posix() for item in directory.rglob("*") if item.is_file() and item.name != "manifest.json"}
    if observed != expected:
        raise QueueServiceError("preparation capture is invalid")


__all__ = ["PrepareRunRequest", "PreparationSource", "SharedInputReceipt", "capture_shared_input"]
