"""The offline migration preserves retained control data and worker journals."""

from dataclasses import replace
from pathlib import Path
import sqlite3
import stat

import pytest

from loom.queue import LocalDaemon, LocalDaemonConfig, QueueServiceError, QueueStorageError
from loom.queue import _coordinator_upgrade as upgrade
from loom.queue.local_daemon import _acquire_lock, _open_root


def _predecessor(tmp_path: Path) -> LocalDaemonConfig:
    deployment = tmp_path / "deployment"
    config = LocalDaemonConfig(
        coordinator_root=deployment / "coordinator",
        agent_root=None,
        resident_worker_launch_profile=None,
        run_store_root=tmp_path / "runs",
        cpu_capacity=0,
        deployment_root=deployment,
        deployment_configuration_fingerprint="a" * 64,
    )
    LocalDaemon.initialize_deployment(config)
    # Schema 12 has the same prior tables and no preparation table. Use the
    # native initializer for every preserved owner, then select that predecessor.
    with sqlite3.connect(config.coordinator_root / "control.sqlite") as conn:
        conn.execute("DROP TABLE preparation_operations")
        conn.execute("PRAGMA user_version = 12")
    return config


def _contents(database: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(database) as conn:
        tables = tuple(row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ))
        return {name: tuple(conn.execute(f'SELECT * FROM "{name}"')) for name in tables}


def test_upgrade_retains_existing_rows_identity_backup_and_worker_root(tmp_path: Path) -> None:
    config = _predecessor(tmp_path)
    database = config.coordinator_root / "control.sqlite"
    coordinator_id = _open_root(config.coordinator_root, role="coordinator", schema_version=12)
    with sqlite3.connect(database) as conn:
        for index, state in enumerate(("PENDING_AUTHORITY", "SUCCEEDED"), 1):
            conn.execute(
                "INSERT INTO managed_admissions (admission_id, queue_item_id, coordinator_id, "
                "run_uri, intent_digest, execution_owner, state, accepted_at, authority_operation_id, "
                "revision, run_priority, enqueue_sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"admission-{index}", f"queue-{index}", coordinator_id,
                 f"file:///retained/run-{index}", "digest", "managed", state,
                 "2026-09-11T00:00:00Z", f"authority-operation-{index}", 3, 7, index),
            )
    before = _contents(database)
    worker = tmp_path / "worker"
    LocalDaemon.initialize_agent_root(worker)
    worker_id = _open_root(worker, role="local-agent")
    worker_database = worker / "control.sqlite"
    worker_before = worker_database.read_bytes()

    assert LocalDaemon.upgrade_coordinator_root(config) == (coordinator_id, 14)
    after = _contents(database)
    assert {name: after[name] for name in before} == before
    assert after["preparation_operations"] == ()
    assert _open_root(config.coordinator_root, role="coordinator") == coordinator_id
    assert _open_root(worker, role="local-agent") == worker_id
    assert worker_database.read_bytes() == worker_before
    backups = tuple(config.coordinator_root.glob("*.schema-12.*.backup"))
    assert len(backups) == 1
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert _contents(backups[0]) == before
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
    published = database.read_bytes(), database.stat().st_mtime_ns
    assert LocalDaemon.upgrade_coordinator_root(config) == (coordinator_id, 14)
    assert (database.read_bytes(), database.stat().st_mtime_ns) == published
    assert tuple(config.coordinator_root.glob("*.schema-12.*.backup")) == backups


def test_upgrade_rejects_live_owner_and_wrong_binding_without_database_writes(tmp_path: Path) -> None:
    config = _predecessor(tmp_path)
    database = config.coordinator_root / "control.sqlite"
    before = database.read_bytes()
    with _acquire_lock(config.coordinator_root):
        with pytest.raises(QueueServiceError, match="locked"):
            LocalDaemon.upgrade_coordinator_root(config)
    with pytest.raises(QueueServiceError, match="binding"):
        LocalDaemon.upgrade_coordinator_root(replace(
            config, deployment_configuration_fingerprint="b" * 64
        ))
    assert database.read_bytes() == before
    assert not tuple(config.coordinator_root.glob("*.backup"))


def test_upgrade_rolls_back_both_schema_and_marker_and_retries_without_overwriting_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _predecessor(tmp_path)
    database = config.coordinator_root / "control.sqlite"
    original = upgrade._apply_upgrade

    def failed_write(conn: sqlite3.Connection) -> None:
        original(conn)
        raise sqlite3.OperationalError("injected failure after DDL and version write")

    monkeypatch.setattr(upgrade, "_apply_upgrade", failed_write)
    with pytest.raises(QueueStorageError, match="upgrade failed"):
        LocalDaemon.upgrade_coordinator_root(config)
    with sqlite3.connect(database) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'preparation_operations'").fetchone() is None
    backup, = config.coordinator_root.glob("*.backup")
    original_backup = backup.read_bytes(), backup.stat().st_mtime_ns
    monkeypatch.setattr(upgrade, "_apply_upgrade", original)
    assert LocalDaemon.upgrade_coordinator_root(config)[1] == 14
    assert (backup.read_bytes(), backup.stat().st_mtime_ns) == original_backup
    assert len(tuple(config.coordinator_root.glob("*.backup"))) == 2


@pytest.mark.parametrize("version", [11, 13, 15])
def test_upgrade_rejects_unsupported_versions_without_repair(
    tmp_path: Path, version: int
) -> None:
    config = _predecessor(tmp_path)
    database = config.coordinator_root / "control.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute(f"PRAGMA user_version = {version}")
    before = database.read_bytes()
    with pytest.raises(QueueStorageError, match="cannot be upgraded"):
        LocalDaemon.upgrade_coordinator_root(config)
    assert database.read_bytes() == before
    assert not tuple(config.coordinator_root.glob("*.backup"))


def test_current_marker_without_complete_schema_is_rejected(tmp_path: Path) -> None:
    config = _predecessor(tmp_path)
    database = config.coordinator_root / "control.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA user_version = 14")
    before = database.read_bytes()
    with pytest.raises(QueueStorageError, match="schema is incomplete"):
        LocalDaemon.upgrade_coordinator_root(config)
    assert database.read_bytes() == before
    assert not tuple(config.coordinator_root.glob("*.backup"))
