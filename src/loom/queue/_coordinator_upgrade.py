"""Offline coordinator-root migration under the existing protected role lock."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import stat
from typing import TYPE_CHECKING
from uuid import uuid4

from .errors import QueueStorageError

if TYPE_CHECKING:
    from .local_daemon import LocalDaemonConfig


def upgrade_coordinator_root(config: LocalDaemonConfig) -> tuple[str, int]:
    from .local_daemon import (
        _COORDINATOR_SCHEMA_VERSION,
        _acquire_lock,
        _open_root,
        _validate_deployment_binding,
        _validate_private_directory,
    )

    root = config.coordinator_root
    _validate_private_directory(root)
    database = root / "control.sqlite"
    if not database.is_file() or database.is_symlink():
        raise QueueStorageError("coordinator root is unavailable")
    details = database.stat()
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
        raise QueueStorageError("coordinator root must be owner-permissioned")
    with _acquire_lock(root):
        try:
            with sqlite3.connect(database) as conn:
                version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                if version not in {12, _COORDINATOR_SCHEMA_VERSION}:
                    raise QueueStorageError("coordinator root schema cannot be upgraded")
                coordinator_id = _open_root(root, role="coordinator", schema_version=version)
                _validate_deployment_binding(config, coordinator_id=coordinator_id)
                if conn.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                    raise QueueStorageError("coordinator root is corrupt")
                if version == _COORDINATOR_SCHEMA_VERSION:
                    return coordinator_id, version
                # Stable identity is validated against the protected binding;
                # the random suffix makes a retry preserve every prior backup.
                identity = hashlib.sha256(coordinator_id.encode()).hexdigest()[:16]
                backup = root / f"control.{identity}.schema-12.{uuid4().hex}.backup"
                _backup(conn, backup)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    _apply_upgrade(conn)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        except (sqlite3.Error, OSError) as exc:
            raise QueueStorageError("coordinator root upgrade failed") from exc
        _open_root(root, role="coordinator")
        return coordinator_id, _COORDINATOR_SCHEMA_VERSION


def _apply_upgrade(conn: sqlite3.Connection) -> None:
    """Install the preparation schema and marker in the caller's transaction."""
    from .local_daemon import _COORDINATOR_SCHEMA_VERSION, _initialize_preparation_schema

    _initialize_preparation_schema(conn)
    conn.execute(f"PRAGMA user_version = {_COORDINATOR_SCHEMA_VERSION}")


def _backup(source: sqlite3.Connection, path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        with sqlite3.connect(path) as destination:
            source.backup(destination)
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        path.unlink()
        raise
