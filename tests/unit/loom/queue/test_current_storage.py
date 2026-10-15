"""Current control roots open directly; retired or incomplete roots stay intact."""

from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from loom.queue import LocalDaemon, LocalDaemonConfig
from loom.queue.errors import QueueError
from loom.queue.local_daemon import _open_root
from loom.queue._agent_session_journal import _RemoteAgentJournal

pytestmark = pytest.mark.unit


def current_config(tmp_path: Path) -> LocalDaemonConfig:
    deployment = tmp_path / "deployment"
    config = LocalDaemonConfig(
        coordinator_root=deployment / "coordinator", agent_root=None,
        resident_worker_launch_profile=None, run_store_root=tmp_path / "runs",
        cpu_capacity=0, deployment_root=deployment,
        deployment_configuration_fingerprint="a" * 64,
    )
    LocalDaemon.initialize_deployment(config)
    return config


def files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("version", [12, 15, 16, 17, 18, 20])
def test_coordinator_refuses_other_schema_before_owner_lock(tmp_path: Path, version: int) -> None:
    config = current_config(tmp_path)
    with sqlite3.connect(config.control_database) as conn:
        conn.execute(f"PRAGMA user_version = {version}")
        if version < 19:
            conn.execute("DELETE FROM daemon_metadata WHERE key = 'maintenance-gate'")
        if version < 18:
            conn.execute("ALTER TABLE preparation_operations DROP COLUMN accepted_at")
        if version < 17:
            for table in ("action_demands", "action_claims", "action_graph_cancellations"):
                conn.execute(f"DROP TABLE {table}")
        if version == 12:
            conn.execute("DROP TABLE preparation_cancellations")
            conn.execute("DROP TABLE preparation_operations")
    conn.close()
    before = files(tmp_path)
    with pytest.raises(QueueError, match="schema is unsupported"):
        LocalDaemon(config).start()
    assert files(tmp_path) == before


@pytest.mark.parametrize("role", ["coordinator", "local-agent"])
def test_missing_delivery_column_is_refused_without_repair(tmp_path: Path, role: str) -> None:
    config = None
    if role == "coordinator":
        config = current_config(tmp_path)
        root = config.coordinator_root
        table = "agent_deliveries"
    else:
        root = tmp_path / "agent"
        LocalDaemon.initialize_agent_root(root)
        table = "agent_session_references"
    with sqlite3.connect(root / "control.sqlite") as conn:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN reference_json")
    conn.close()
    before = files(tmp_path)
    with pytest.raises(QueueError, match="schema"):
        if role == "coordinator":
            assert config is not None
            LocalDaemon(config).start()
        else:
            _RemoteAgentJournal(root)
    assert files(tmp_path) == before


def test_current_roots_reopen_with_their_identity(tmp_path: Path) -> None:
    config = current_config(tmp_path)
    identity = _open_root(config.coordinator_root, role="coordinator")
    daemon = LocalDaemon(config)
    try:
        assert daemon.start().coordinator_id == identity
    finally:
        daemon.stop()
    assert _open_root(config.coordinator_root, role="coordinator") == identity
    root = tmp_path / "agent"
    LocalDaemon.initialize_agent_root(root)
    agent_id = _open_root(root, role="local-agent")
    journal = _RemoteAgentJournal(root)
    try:
        assert journal.root_id == agent_id
    finally:
        journal.close()


@pytest.mark.parametrize("version", [18, 19])
def test_interrupted_coordinator_write_recovers_only_current_schema(tmp_path: Path, version: int) -> None:
    config = current_config(tmp_path)
    identity = _open_root(config.coordinator_root, role="coordinator")
    with sqlite3.connect(config.control_database) as conn:
        conn.execute(f"PRAGMA user_version = {version}")
    conn.close()
    subprocess.run([sys.executable, "-c", '''
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("PRAGMA cache_size = 1")
conn.execute("BEGIN IMMEDIATE")
conn.executemany("INSERT INTO root_metadata VALUES (?, ?)",
                 ((f"uncommitted-{i}", "x" * 500) for i in range(2000)))
os._exit(0)
''', str(config.control_database)], check=True)
    before = files(tmp_path)
    if version == 18:
        with pytest.raises(QueueError, match="schema is unsupported"):
            LocalDaemon(config).start()
        assert files(tmp_path) == before
    else:
        daemon = LocalDaemon(config)
        try:
            assert daemon.start().coordinator_id == identity
            with sqlite3.connect(config.control_database) as conn:
                assert conn.execute("SELECT COUNT(*) FROM root_metadata WHERE key LIKE 'uncommitted-%'").fetchone() == (0,)
        finally:
            daemon.stop()


@pytest.mark.parametrize("arguments", [
    ["queue", "daemon-upgrade"], ["fleet", "adopt"], ["fleet", "migrate-services"],
])
def test_retired_commands_are_not_registered(arguments: list[str]) -> None:
    from loom.cli.main import build_parser

    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(arguments)
    assert error.value.code == 2
