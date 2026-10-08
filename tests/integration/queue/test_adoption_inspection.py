"""Legacy installation ownership requires actual native kernel lock evidence."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from loom.queue import LocalDaemon, LocalDaemonConfig
from loom.queue._service_lifetime import record_process
from loom.queue.operations import inspect_native_service
from loom.queue.service_upgrade import inspect_adoption_service

pytestmark = pytest.mark.integration


@pytest.fixture
def legacy(tmp_path):
    config = LocalDaemonConfig(
        tmp_path / "coordinator", None, tmp_path / "runs", None, cpu_capacity=0
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    record_process(config.coordinator_root, stopped=False)
    identity = daemon.status().coordinator_id
    with sqlite3.connect(config.control_database) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        original = conn.execute(
            "SELECT value FROM root_metadata WHERE key='service_process'"
        ).fetchone()[0]
        record = json.loads(original)
        record.pop("boot_id")
        # Actual schema-18 predecessors wrote this process record without boot ID.
        conn.execute("PRAGMA user_version=18")
        conn.execute(
            "UPDATE root_metadata SET value=? WHERE key='service_process'",
            (json.dumps(record),),
        )
    try:
        yield daemon, identity
    finally:
        with sqlite3.connect(config.control_database) as conn:
            conn.execute(f"PRAGMA user_version={version}")
            conn.execute(
                "UPDATE root_metadata SET value=? WHERE key='service_process'",
                (original,),
            )
        daemon.stop()


def snapshot(database):
    with sqlite3.connect(database) as conn:
        return tuple(conn.iterdump())


def test_live_legacy_native_lock_proves_owner_without_rewriting_receipt(legacy):
    daemon, identity = legacy
    root = daemon.config.coordinator_root
    before = snapshot(daemon.config.control_database)
    assert inspect_native_service(root).value["ownership"] == "unproven"
    observed = inspect_adoption_service(root, expected_root_id=identity)
    assert observed.availability == "available"
    assert observed.value["ownership"] == "live"
    assert observed.value["expected_process"] == os.getpid()
    assert observed.value["ownership_evidence"] == "kernel_owner_lock"
    assert observed.value["recorded_boot_id"] is None
    assert (
        observed.value["boot_id"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    )
    assert snapshot(daemon.config.control_database) == before
    assert (
        inspect_adoption_service(root, expected_root_id="other").reason == "wrong_owner"
    )


def test_stale_process_receipt_cannot_claim_another_live_native_owner(legacy):
    daemon, identity = legacy
    with sqlite3.connect(daemon.config.control_database) as conn:
        record = json.loads(
            conn.execute(
                "SELECT value FROM root_metadata WHERE key='service_process'"
            ).fetchone()[0]
        )
        record["pid"] = 2_000_000_000
        conn.execute(
            "UPDATE root_metadata SET value=? WHERE key='service_process'",
            (json.dumps(record),),
        )
    before = snapshot(daemon.config.control_database)
    observed = inspect_adoption_service(
        daemon.config.coordinator_root, expected_root_id=identity
    )
    assert observed.availability == "unavailable"
    assert observed.reason == "native_owner_lock_held"
    assert snapshot(daemon.config.control_database) == before


def test_missing_root_stays_missing(tmp_path):
    root = tmp_path / "missing"
    assert (
        inspect_adoption_service(root, expected_root_id="absent").availability
        == "unavailable"
    )
    assert not root.exists()


def test_exited_same_boot_process_requires_vacant_native_lock(tmp_path):
    program = """
import sys
from pathlib import Path
from loom.queue import LocalDaemon, LocalDaemonConfig
from loom.queue._service_lifetime import record_process
root = Path(sys.argv[1])
config = LocalDaemonConfig(root, None, root.parent / "runs", None, cpu_capacity=0)
LocalDaemon.initialize(config)
daemon = LocalDaemon(config)
daemon.start()
record_process(config.coordinator_root, stopped=False)
print(daemon.status().coordinator_id, flush=True)
sys.stdin.read()
"""
    root = tmp_path / "coordinator"
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        identity = process.stdout.readline().strip()
        assert identity.startswith("coordinator-")
        assert (
            inspect_adoption_service(root, expected_root_id=identity).value["ownership"]
            == "live"
        )
        process.terminate()
        process.wait(timeout=10)
        before = snapshot(root / "control.sqlite")
        observed = inspect_adoption_service(root, expected_root_id=identity)
        assert observed.availability == "available"
        assert observed.reason == "service_stopped"
        assert observed.value["ownership_evidence"] == "vacant_native_owner_lock"
        assert snapshot(root / "control.sqlite") == before
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
