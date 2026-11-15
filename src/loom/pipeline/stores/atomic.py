"""Atomic filesystem helper utilities for store writes."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Literal

from loom.serialization.json import json_dumps_pretty

from .errors import AtomicWriteError, UnsafeStorePathError

_ENCODING = "utf-8"


def ensure_dir(path: str | Path) -> Path:
    """Create a directory tree if needed and return it."""

    path_obj = _ensure_path(path)
    try:
        path_obj.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AtomicWriteError(f"Failed to create directory {path_obj}: {exc}") from exc
    return path_obj


def unique_temp_path(path: str | Path) -> Path:
    """Return an unused temporary path in the same directory as ``path``."""

    target = _ensure_path(path)
    ensure_dir(target.parent)
    base = target.name
    temp_prefix = f".{base}.tmp"
    for _ in range(100):
        candidate = target.with_name(f"{temp_prefix}.{os.getpid()}.{uuid.uuid4().hex}")
        if not candidate.exists():
            return candidate
    raise AtomicWriteError(f"Failed to allocate unique temporary path for {target}")


def atomic_write_bytes(
    path: str | Path, data: bytes, *, durability: Literal["best_effort", "strict"] = "best_effort"
) -> None:
    """Atomically replace bytes, optionally requiring file and directory durability.

    Strict mode creates a private sibling, propagates fsync failures and syncs
    the parent after replacement. Failure after replacement has an uncertain
    durable outcome: inspect the retained operation before retrying side effects.
    Existing callers retain best-effort synchronization and permission behavior.
    """

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise AtomicWriteError(f"atomic_write_bytes expects bytes, got {type(data)!r}")
    _validate_durability(durability)
    target = _ensure_path(path)
    if durability == "strict":
        _ensure_durable_parent(target.parent)
    else:
        ensure_dir(target.parent)
    temp_path = unique_temp_path(target)
    try:
        if durability == "strict":
            descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            replace_file(temp_path, target, durability="strict")
        else:
            _write_bytes_file(temp_path, bytes(data))
            replace_file(temp_path, target)
    except Exception as exc:
        if temp_path.exists():
            _safe_unlink(temp_path)
        if isinstance(exc, AtomicWriteError):
            raise
        raise AtomicWriteError(f"Failed atomic write to {target}: {exc}") from exc


def atomic_write_text(
    path: str | Path, text: str, *, encoding: str = _ENCODING,
    durability: Literal["best_effort", "strict"] = "best_effort",
) -> None:
    """Write UTF-8 text to ``path`` using atomic replacement."""

    if not isinstance(text, str):
        raise AtomicWriteError(f"atomic_write_text expects str, got {type(text)!r}")
    if not isinstance(encoding, str) or not encoding:
        raise AtomicWriteError(f"encoding must be a non-empty string, got {encoding!r}")
    atomic_write_bytes(path, text.encode(encoding), durability=durability)


def atomic_write_json(
    path: str | Path, value: object, *, durability: Literal["best_effort", "strict"] = "best_effort"
) -> None:
    """Write deterministic JSON to ``path`` using atomic replacement."""

    serialized = json_dumps_pretty(value, sort_keys=True)
    atomic_write_text(path, serialized, encoding=_ENCODING, durability=durability)


def replace_file(
    source: str | Path, target: str | Path, *, durability: Literal["best_effort", "strict"] = "best_effort"
) -> None:
    """Atomically replace ``target`` with ``source`` using ``os.replace``."""

    source_path = _ensure_path(source)
    target_path = _ensure_path(target)
    _validate_durability(durability)
    ensure_dir(target_path.parent)

    if not source_path.exists():
        raise AtomicWriteError(f"Cannot replace {target_path}: source missing {source_path}")

    try:
        os.replace(source_path, target_path)
        if durability == "strict":
            _fsync_path_strict(target_path.parent)
        else:
            _fsync_path(target_path.parent)
    except OSError as exc:
        raise AtomicWriteError(f"Failed replacing {target_path}: {exc}") from exc


def _write_bytes_file(path: Path, data: bytes) -> None:
    """Write bytes to a temp path and sync file data/metadata."""

    try:
        with open(path, "wb") as file_obj:
            file_obj.write(data)
            file_obj.flush()
            _fsync_file(file_obj.fileno())
    except OSError as exc:
        raise AtomicWriteError(f"Failed writing temporary store file {path}: {exc}") from exc


def _ensure_path(path: str | Path) -> Path:
    try:
        return Path(path)
    except TypeError as exc:
        raise UnsafeStorePathError(f"Invalid path type: {type(path)!r}") from exc


def _fsync_file(fd: int) -> None:
    """Flush file descriptor data to storage."""

    try:
        os.fsync(fd)
    except OSError:
        # Some filesystems report fsync as unsupported; that's acceptable for this scope.
        return


def _fsync_path(path: Path) -> None:
    try:
        file_descriptor = os.open(path, os.O_RDONLY)
        try:
            _fsync_file(file_descriptor)
        finally:
            os.close(file_descriptor)
    except OSError:
        return


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _validate_durability(value: str) -> None:
    if value not in ("best_effort", "strict"):
        raise AtomicWriteError("durability must be 'best_effort' or 'strict'")


def _fsync_path_strict(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_durable_parent(path: Path) -> None:
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    try:
        for directory in reversed(missing):
            directory.mkdir(mode=0o700, exist_ok=True)
            _fsync_path_strict(directory.parent)
    except OSError as exc:
        raise AtomicWriteError(f"Failed creating durable store directory {path}: {exc}") from exc


__all__ = [
    "ensure_dir",
    "unique_temp_path",
    "atomic_write_bytes",
    "atomic_write_text",
    "atomic_write_json",
    "replace_file",
]
