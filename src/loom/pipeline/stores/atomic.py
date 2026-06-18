"""Atomic filesystem helper utilities for store writes."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

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


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Write bytes to ``path`` using an atomic temp-file replace path."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise AtomicWriteError(f"atomic_write_bytes expects bytes, got {type(data)!r}")
    target = _ensure_path(path)
    ensure_dir(target.parent)
    temp_path = unique_temp_path(target)
    try:
        _write_bytes_file(temp_path, bytes(data))
        replace_file(temp_path, target)
    except Exception as exc:
        if temp_path.exists():
            _safe_unlink(temp_path)
        if isinstance(exc, AtomicWriteError):
            raise
        raise AtomicWriteError(f"Failed atomic write to {target}: {exc}") from exc


def atomic_write_text(path: str | Path, text: str, *, encoding: str = _ENCODING) -> None:
    """Write UTF-8 text to ``path`` using atomic replacement."""

    if not isinstance(text, str):
        raise AtomicWriteError(f"atomic_write_text expects str, got {type(text)!r}")
    if not isinstance(encoding, str) or not encoding:
        raise AtomicWriteError(f"encoding must be a non-empty string, got {encoding!r}")
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: str | Path, value: object) -> None:
    """Write deterministic JSON to ``path`` using atomic replacement."""

    serialized = json_dumps_pretty(value, sort_keys=True)
    atomic_write_text(path, serialized, encoding=_ENCODING)


def replace_file(source: str | Path, target: str | Path) -> None:
    """Atomically replace ``target`` with ``source`` using ``os.replace``."""

    source_path = _ensure_path(source)
    target_path = _ensure_path(target)
    ensure_dir(target_path.parent)

    if not source_path.exists():
        raise AtomicWriteError(f"Cannot replace {target_path}: source missing {source_path}")

    try:
        os.replace(source_path, target_path)
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


__all__ = [
    "ensure_dir",
    "unique_temp_path",
    "atomic_write_bytes",
    "atomic_write_text",
    "atomic_write_json",
    "replace_file",
]
