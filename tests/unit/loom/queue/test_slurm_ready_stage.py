from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.slurm_ready_stage import SQLiteSlurmStageAssignments


def test_assignment_store_requires_final_schema_identity(tmp_path: Path) -> None:
    path = tmp_path / "assignments.sqlite"
    store = SQLiteSlurmStageAssignments(path, tmp_path / "transfers")
    store._initialize()

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        conn.execute("PRAGMA user_version = 2")

    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        store._open_existing()


_RETIRED_ASSIGNMENT_COLUMNS = (
    "start_consumed",
    "agent_sequence",
    "agent_evidence_json",
    "agent_evidence_accepted_at",
)


def _storage_snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_fresh_assignment_store_contains_current_agent_evidence(tmp_path: Path) -> None:
    path = tmp_path / "assignments.sqlite"
    store = SQLiteSlurmStageAssignments(path, tmp_path / "transfers")
    store._initialize()
    with sqlite3.connect(path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(slurm_stage_assignments)")
        }
        assert set(_RETIRED_ASSIGNMENT_COLUMNS) <= columns
        assert conn.execute("PRAGMA user_version").fetchone() == (3,)
    conn.close()
    before = _storage_snapshot(tmp_path)
    SQLiteSlurmStageAssignments(
        path, tmp_path / "transfers", _allow_initialize=False
    )._open_existing()
    store._initialize()
    assert _storage_snapshot(tmp_path) == before


@pytest.mark.parametrize("shape", ["native_only", "old_version", "missing_outputs"])
@pytest.mark.parametrize("entry", ["_open_existing", "_initialize"])
def test_retired_assignment_storage_refuses_before_mutation(
    tmp_path: Path, shape: str, entry: str
) -> None:
    path = tmp_path / "assignments.sqlite"
    store = SQLiteSlurmStageAssignments(path, tmp_path / "transfers")
    store._initialize()
    with sqlite3.connect(path) as conn:
        if shape == "native_only":
            # The empty schema-3 layout emitted before agent-owned Slurm (#312).
            for column in _RETIRED_ASSIGNMENT_COLUMNS:
                conn.execute(
                    f"ALTER TABLE slurm_stage_assignments DROP COLUMN {column}"
                )
        elif shape == "old_version":
            conn.execute("PRAGMA user_version = 2")
        else:
            conn.execute("DROP TABLE slurm_stage_outputs")
    conn.close()
    before = _storage_snapshot(tmp_path)
    with pytest.raises(QueueServiceError, match="schema is unsupported"):
        getattr(store, entry)()
    assert _storage_snapshot(tmp_path) == before


@pytest.mark.parametrize("retired", [False, True])
def test_interrupted_assignment_write_recovers_only_current_storage(
    tmp_path: Path, retired: bool
) -> None:
    path = tmp_path / "assignments.sqlite"
    store = SQLiteSlurmStageAssignments(path, tmp_path / "transfers")
    store._initialize()
    if retired:
        with sqlite3.connect(path) as conn:
            for column in _RETIRED_ASSIGNMENT_COLUMNS:
                conn.execute(
                    f"ALTER TABLE slurm_stage_assignments DROP COLUMN {column}"
                )
        conn.close()
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("PRAGMA cache_size = 1")
conn.execute("BEGIN IMMEDIATE")
conn.executemany(
    "INSERT INTO slurm_stage_outputs VALUES (?, ?, ?, ?, ?)",
    (("assignment", str(i), "x" * 1000, 0, 0) for i in range(1000)),
)
os._exit(0)
""",
            str(path),
        ],
        check=True,
    )
    assert Path(str(path) + "-journal").is_file()
    before = _storage_snapshot(tmp_path)
    if retired:
        with pytest.raises(QueueServiceError, match="schema is unsupported"):
            store._initialize()
        assert _storage_snapshot(tmp_path) == before
    else:
        store._open_existing()
        assert _storage_snapshot(tmp_path) == before
        store._initialize()
        with sqlite3.connect(path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM slurm_stage_outputs"
            ).fetchone() == (0,)
        conn.close()


def test_native_preparation_framing_uses_existing_slurm_chunk_identity(tmp_path):
    import hashlib
    from tests.unit.loom.queue.test_remote_stage_execution import _preparation_output
    from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace
    from loom.queue._remote_stage_execution import (
        TRANSFER_CHUNK_BYTES,
        _atomic_regular_file,
    )

    _logical, original, _companion, data, item = _preparation_output(tmp_path)
    workspace = SlurmBootstrapWorkspace(tmp_path / "compute", "native-pair")
    wrapper = workspace.root / "retained-outputs/report"
    _atomic_regular_file(wrapper, data)
    transfer_id = (
        "output-"
        + hashlib.sha256(
            (workspace.root.name + "\0report\0" + item.digest).encode()
        ).hexdigest()
    )
    assert "sha256:" + item.digest != original.checksum
    chunks, offset = [], 0
    while True:
        chunk, final = workspace.output_chunk(transfer_id, offset)
        assert len(chunk) <= TRANSFER_CHUNK_BYTES
        assert workspace.output_chunk(transfer_id, offset) == (chunk, final)
        chunks.append(chunk)
        offset += len(chunk)
        if final:
            break
    assert b"".join(chunks) == data
    assert offset == item.size_bytes
    from loom.queue.errors import QueueConflictError

    with pytest.raises(QueueConflictError):
        item.local_ref(wrapper)
    wrapper.write_bytes(data[:-1])
    with pytest.raises(QueueConflictError, match="unavailable"):
        workspace.output_chunk(transfer_id, 0)
