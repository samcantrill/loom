"""Connection policy is opt-in and cannot silently migrate or recreate state."""

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from loom._sqlite_policy import SQLitePolicy, connect_existing, initialize_database


@pytest.mark.parametrize("options", [
    {"journal_mode": "off", "synchronous": "full"},
    {"journal_mode": "delete", "synchronous": "normal"},
    {"journal_mode": "delete", "synchronous": "extra", "busy_timeout_ms": True},
    {"journal_mode": "delete", "synchronous": "extra", "busy_timeout_ms": 0},
    {"journal_mode": "delete", "synchronous": "extra", "busy_timeout_ms": 300001},
])
def test_rejects_unsupported_policy(options):
    with pytest.raises(ValueError):
        SQLitePolicy(**options)


@pytest.mark.parametrize("mode,sync", [("delete", "extra"), ("wal", "full")])
def test_policy_reapplied_on_reopen_without_schema_changes(tmp_path: Path, mode, sync):
    policy = SQLitePolicy(mode, sync, 1234)
    path = tmp_path / "state with spaces.sqlite"
    with closing(initialize_database(path, policy=policy, isolation_level=None)) as conn:
        conn.execute("CREATE TABLE facts(value INTEGER)")
        conn.execute("INSERT INTO facts VALUES (42)")
    with closing(connect_existing(path, policy=policy, isolation_level=None)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == mode
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == (3 if sync == "extra" else 2)
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
        assert conn.execute("SELECT value FROM facts").fetchone()[0] == 42
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO facts VALUES (99)")
        conn.rollback()
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_missing_state_and_mode_mismatch_do_not_create_or_convert(tmp_path: Path):
    path = tmp_path / "state.sqlite"
    policy = SQLitePolicy("delete", "extra")
    with pytest.raises(sqlite3.OperationalError):
        connect_existing(path, policy=policy, isolation_level=None)
    assert not path.exists()
    with closing(initialize_database(path, policy=SQLitePolicy("wal", "full"), isolation_level=None)) as conn:
        conn.execute("CREATE TABLE facts(value INTEGER)")
    for connect in (connect_existing, initialize_database):
        with pytest.raises(sqlite3.OperationalError, match="stopped-owner migration"):
            connect(path, policy=policy, isolation_level=None)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_existing_open_does_not_select_mode_even_for_empty_database(tmp_path: Path):
    path = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(path)):
        pass
    with pytest.raises(sqlite3.OperationalError, match="migration"):
        connect_existing(path, policy=SQLitePolicy("wal", "full"), isolation_level=None)
