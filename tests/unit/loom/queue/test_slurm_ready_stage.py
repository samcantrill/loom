from __future__ import annotations

import sqlite3
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


def test_native_preparation_framing_uses_existing_slurm_chunk_identity(tmp_path):
    import hashlib
    from tests.unit.loom.queue.test_remote_stage_execution import _preparation_output
    from loom.queue.slurm_ready_stage import SlurmBootstrapWorkspace
    from loom.queue._remote_stage_execution import TRANSFER_CHUNK_BYTES, _atomic_regular_file

    _logical, original, _companion, data, item = _preparation_output(tmp_path)
    workspace = SlurmBootstrapWorkspace(tmp_path / "compute", "native-pair")
    wrapper = workspace.root / "retained-outputs/report"
    _atomic_regular_file(wrapper, data)
    transfer_id = "output-" + hashlib.sha256((workspace.root.name + "\0report\0" + item.digest).encode()).hexdigest()
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
