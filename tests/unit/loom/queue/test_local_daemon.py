"""Unit coverage for local-daemon control ownership."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

import loom.queue.local_daemon_execution as local_daemon_execution
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


@pytest.mark.parametrize("owner_store", ("execution_database", "agent_journal"))
def test_start_rejects_missing_expected_owner_store_without_retaining_locks(
    tmp_path: Path, owner_store: str
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    store_path = getattr(config, owner_store)
    store_path.unlink()

    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()
    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()
    assert not store_path.exists()


def test_failed_execution_construction_releases_daemon_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)

    class _Failure:
        def __init__(self, **_kwargs: object) -> None:
            raise RuntimeError("construction failed")

    monkeypatch.setattr(local_daemon_execution, "LocalDaemonExecution", _Failure)
    with pytest.raises(QueueServiceError, match="owner state is unavailable"):
        LocalDaemon(config).start()

    monkeypatch.undo()
    restarted = LocalDaemon(config)
    restarted.start()
    restarted.stop()


@pytest.mark.parametrize("owner_store", ("execution_database", "agent_journal"))
def test_live_owner_loss_degrades_service_and_blocks_scheduling(
    tmp_path: Path, owner_store: str
) -> None:
    config = _config(tmp_path)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        store_path = getattr(config, owner_store)
        store_path.unlink()

        status = daemon.status()
        assert status.service_health == "degraded"
        assert status.service_diagnostic == "owner_status_unavailable"
        assert not status.scheduling_ready
        with pytest.raises(QueueServiceError, match="owner state is unavailable"):
            daemon.reconcile_once()
        assert not store_path.exists()
    finally:
        daemon.stop()


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
