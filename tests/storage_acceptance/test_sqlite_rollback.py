"""Opt-in process-crash/locking observations on an operator-selected filesystem.

These probes use private fixture databases, never production roles. They do not
simulate a storage-server outage or certify cross-host locking.
"""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import selectors
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

import pytest

from loom._sqlite_policy import SQLitePolicy, connect_existing, initialize_database
from loom.pipeline.stores.atomic import atomic_write_bytes


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("LOOM_RUN_STORAGE_ACCEPTANCE") != "1",
        reason="requires explicit filesystem qualification selection",
    ),
]
POLICY = SQLitePolicy("delete", "extra", 250)


@pytest.fixture
def storage_root():
    selected = Path(os.environ["LOOM_STORAGE_ACCEPTANCE_ROOT"])
    assert selected.is_absolute() and selected.is_dir()
    root = Path(tempfile.mkdtemp(prefix="loom-storage-probe-", dir=selected))
    children = []
    try:
        yield root, children
    finally:
        # A process blocked in filesystem I/O may resist timely termination.
        # Preserve its exact fixture instead of deleting state underneath it.
        if all(child.poll() is not None for child in children):
            shutil.rmtree(root)


@contextmanager
def child_process(storage_root, action, path):
    _, children = storage_root
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), action, str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    children.append(child)
    try:
        yield child
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)


def child_line(child):
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=10), "fixture process did not report its boundary"
        line = child.stdout.readline()
    assert line, "fixture process exited before its boundary"
    return json.loads(line)


def database(root):
    path = root / "state.sqlite"
    with initialize_database(path, policy=POLICY, isolation_level="") as conn:
        conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, generation INTEGER, payload BLOB)")
        conn.executemany(
            "INSERT INTO data VALUES (?, 0, ?)",
            ((i, b"x" * 4096) for i in range(256)),
        )
    return path


def test_writer_exclusion_reader_visibility_and_busy_timeout(storage_root):
    root, _ = storage_root
    path = database(root)
    with connect_existing(path, policy=POLICY, isolation_level=None) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE data SET generation=1 WHERE id=0")
        with child_process(storage_root, "contend", path) as child:
            observed = child_line(child)
        assert observed["visible"] == 0
        assert observed["locked"] is True
        assert 0.15 <= observed["elapsed"] < 5
        writer.commit()
    with child_process(storage_root, "contend", path) as child:
        observed = child_line(child)
    assert observed["visible"] == 1
    assert observed["locked"] is False


@pytest.mark.parametrize("boundary", ("uncommitted", "committed", "acknowledged"))
def test_killed_writer_recovers_atomic_rows(storage_root, boundary):
    root, _ = storage_root
    path = database(root)
    with child_process(storage_root, boundary, path) as child:
        observed = child_line(child)
        assert observed["boundary"] == boundary
        if boundary == "uncommitted":
            assert Path(str(path) + "-journal").stat().st_size > 0
        child.kill()
        child.wait(timeout=10)
    with connect_existing(path, policy=POLICY, isolation_level="") as conn:
        expected = 0 if boundary == "uncommitted" else 1
        assert conn.execute("SELECT DISTINCT generation FROM data").fetchall() == [(expected,)]
        assert conn.execute("SELECT count(*) FROM data").fetchone()[0] == 256
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert not Path(str(path) + "-wal").exists()


def test_role_lock_exclusion_and_strict_publication(storage_root):
    root, _ = storage_root
    path = root / "role.lock"
    with path.open("xb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        with child_process(storage_root, "flock", path) as child:
            assert child_line(child)["locked"] is True
    with child_process(storage_root, "flock", path) as child:
        assert child_line(child)["locked"] is False
    target = root / "receipt.json"
    atomic_write_bytes(target, b'{"generation":1}', durability="strict")
    with child_process(storage_root, "read", target) as child:
        assert child_line(child) == {"generation": 1}
    atomic_write_bytes(target, b'{"generation":2}', durability="strict")
    with child_process(storage_root, "read", target) as child:
        assert child_line(child) == {"generation": 2}
    assert target.stat().st_mode & 0o777 == 0o600


def worker(action, path):
    if action == "read":
        print(path.read_text(), flush=True)
        return
    if action == "flock":
        with path.open("rb") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = False
            except BlockingIOError:
                locked = True
            print(json.dumps({"locked": locked}), flush=True)
        return
    with connect_existing(path, policy=POLICY, isolation_level=None) as conn:
        if action == "contend":
            visible = conn.execute("SELECT generation FROM data WHERE id=0").fetchone()[0]
            started = time.monotonic()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
                locked = False
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc):
                    raise
                locked = True
            print(json.dumps({
                "visible": visible, "locked": locked,
                "elapsed": time.monotonic() - started,
            }), flush=True)
            return
        assert action in {"uncommitted", "committed", "acknowledged"}
        conn.execute("PRAGMA cache_size=8")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE data SET generation=1")
        if action != "uncommitted":
            conn.commit()
        # 'committed' is a probe control signal before application acknowledgement;
        # 'acknowledged' represents that acknowledgement. Neither holds a DB lock.
        print(json.dumps({"boundary": action}), flush=True)
        sys.stdin.read()


if __name__ == "__main__":
    worker(sys.argv[1], Path(sys.argv[2]))
