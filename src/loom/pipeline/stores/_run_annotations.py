"""Shared SQLite encoding for authority-owned annotation initialization."""

from __future__ import annotations

import json
import sqlite3

from loom.runs.context import RunAnnotations, SubmissionContext
from loom.serialization import stable_json_bytes


ANNOTATION_COLUMNS = frozenset({"run_uri", "annotations_json", "initialization_json"})


def create_annotations_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS run_annotations (
        run_uri TEXT PRIMARY KEY, annotations_json TEXT NOT NULL,
        initialization_json TEXT NOT NULL
    )""")


def read_annotations(conn: sqlite3.Connection, run_uri: str) -> RunAnnotations | None:
    row = conn.execute(
        "SELECT annotations_json FROM run_annotations WHERE run_uri = ?", (run_uri,)
    ).fetchone()
    return None if row is None else RunAnnotations.from_dict(json.loads(row[0]))


def initialize_annotations(
    conn: sqlite3.Connection,
    run_uri: str,
    context: SubmissionContext,
    operation_id: str | None,
    coordinator_id: str | None,
) -> RunAnnotations:
    """Called inside the owning authority transaction after checking run existence.

    A different submission observes the existing owner. Replaying the initializing
    submission returns its original receipt, even after future annotation edits.
    """
    row = conn.execute(
        "SELECT annotations_json, initialization_json FROM run_annotations WHERE run_uri = ?",
        (run_uri,),
    ).fetchone()
    if row is not None:
        original = RunAnnotations.from_dict(json.loads(row[1]))
        if (original.initializer_operation_id, original.initializer_coordinator_id) == (
            operation_id,
            coordinator_id,
        ):
            return original
        return RunAnnotations.from_dict(json.loads(row[0]))
    result = RunAnnotations(
        run_uri,
        1,
        context.description,
        context.tags,
        context.metadata,
        operation_id,
        coordinator_id,
    )
    encoded = stable_json_bytes(result.to_dict()).decode("utf-8")
    conn.execute(
        "INSERT INTO run_annotations VALUES (?, ?, ?)", (run_uri, encoded, encoded)
    )
    return result
