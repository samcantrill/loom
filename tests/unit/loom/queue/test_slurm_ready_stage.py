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
