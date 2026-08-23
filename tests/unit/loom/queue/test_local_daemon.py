"""Unit coverage for local-daemon control ownership."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from loom.queue import (
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    QueueServiceError,
    QueueStorageError,
)


def _config(tmp_path: Path) -> LocalDaemonConfig:
    return LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=tmp_path / "agent",
        run_store_root=tmp_path / "runs",
    )


def test_initialize_start_restart_preserves_owner_and_rotates_epoch(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first_status = first.start()
    first.stop()

    second = LocalDaemon(config)
    second_status = second.start()
    second.stop()

    assert second_status.coordinator_id == first_status.coordinator_id
    assert second_status.coordinator_epoch != first_status.coordinator_epoch


def test_start_is_open_only_and_second_owner_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(QueueServiceError, match="missing"):
        LocalDaemon(config).start()

    LocalDaemon.initialize(config)
    first = LocalDaemon(config)
    first.start()
    try:
        with pytest.raises(QueueServiceError, match="already locked"):
            LocalDaemon(config).start()
    finally:
        first.stop()


def test_schema_mismatch_requires_fresh_root_without_migration(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    with sqlite3.connect(config.control_database) as conn:
        conn.execute("PRAGMA user_version = 0")

    with pytest.raises(QueueStorageError, match="fresh roots"):
        LocalDaemon(config).start()


def test_scoped_view_rejects_client_principal_for_operator_action(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        operator = daemon.operator_view(
            LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT)
        )
        with pytest.raises(QueueServiceError, match="not authorized"):
            operator.status()
    finally:
        daemon.stop()
