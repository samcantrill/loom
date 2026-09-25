"""Shared SQLite encoding for authority-owned annotation initialization."""

from __future__ import annotations

import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import uuid4

from loom.runs.context import RunAnnotations, SubmissionContext
from loom.runs.annotations import (
    AnnotationConflictError,
    AnnotationValidationError,
    AnnotationPatch,
    RunNote,
    RunNotePage,
    mutation_request,
    page_notes,
)
from loom.serialization import stable_json_bytes


ANNOTATION_COLUMNS = frozenset({"run_uri", "annotations_json", "initialization_json"})
NOTE_COLUMNS = frozenset({"run_uri", "note_id", "created_at", "note_json"})
RECEIPT_COLUMNS = frozenset(
    {"run_uri", "principal", "mutation_id", "digest", "result_json"}
)


def create_annotation_mutation_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS run_annotation_notes (
        run_uri TEXT NOT NULL, note_id TEXT NOT NULL, created_at TEXT NOT NULL,
        note_json TEXT NOT NULL, PRIMARY KEY (run_uri, note_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS run_annotation_mutations (
        run_uri TEXT NOT NULL, principal TEXT NOT NULL, mutation_id TEXT NOT NULL,
        digest TEXT NOT NULL, result_json TEXT NOT NULL,
        PRIMARY KEY (run_uri, principal, mutation_id))""")


def legacy_run_notes(run_uri: str, texts: Sequence[str]) -> tuple[RunNote, ...]:
    return tuple(
        RunNote(run_uri, f"legacy-{index:012d}", text, None, None, "legacy_runtime")
        for index, text in enumerate(texts)
    )


def mutate_annotations(
    conn: sqlite3.Connection,
    run_uri: str,
    principal: str,
    mutation_id: str,
    operation: str,
    change: Mapping[str, object],
    legacy_context: SubmissionContext,
    legacy_notes: Sequence[str],
) -> RunAnnotations | RunNote:
    """Commit a run-scoped receipt and its effect in the caller's owner transaction."""
    request = mutation_request(run_uri, mutation_id, operation, change)
    if not isinstance(principal, str) or not principal:
        raise ValueError("native principal is required")
    digest = hashlib.sha256(stable_json_bytes(request)).hexdigest()
    receipt = conn.execute(
        "SELECT digest, result_json FROM run_annotation_mutations WHERE run_uri=? AND principal=? AND mutation_id=?",
        (run_uri, principal, mutation_id),
    ).fetchone()
    if receipt is not None:
        if receipt[0] != digest:
            raise AnnotationConflictError(
                "mutation ID already used for another request"
            )
        value = json.loads(receipt[1])
        return (
            RunAnnotations.from_dict(value)
            if operation == "patch_run_annotations"
            else RunNote.from_dict(value)
        )
    current = read_annotations(conn, run_uri)
    change = cast(Mapping[str, object], request["change"])
    try:
        if current is None:
            current = RunAnnotations(
                run_uri,
                0,
                legacy_context.description,
                legacy_context.tags,
                legacy_context.metadata,
            )
        if operation == "patch_run_annotations":
            result: RunAnnotations | RunNote = AnnotationPatch.from_dict(change).apply(
                current
            )
        else:
            result = RunNote(
                run_uri,
                uuid4().hex,
                cast(str, change["text"]),
                principal,
                datetime.now(timezone.utc).isoformat(),
            )
        imported_notes = legacy_run_notes(run_uri, legacy_notes)
    except AnnotationConflictError:
        raise
    except ValueError as exc:
        raise AnnotationValidationError(str(exc)) from exc
    # First write establishes legacy annotations once; reads never do so.
    if read_annotations(conn, run_uri) is None:
        encoded = stable_json_bytes(current.to_dict()).decode()
        conn.execute(
            "INSERT INTO run_annotations VALUES (?, ?, ?)", (run_uri, encoded, encoded)
        )
    for note in imported_notes:
        conn.execute(
            "INSERT OR IGNORE INTO run_annotation_notes VALUES (?, ?, ?, ?)",
            (run_uri, note.note_id, "", stable_json_bytes(note.to_dict()).decode()),
        )
    encoded_result = stable_json_bytes(result.to_dict()).decode()
    if isinstance(result, RunAnnotations):
        conn.execute(
            "UPDATE run_annotations SET annotations_json=? WHERE run_uri=?",
            (encoded_result, run_uri),
        )
    else:
        conn.execute(
            "INSERT INTO run_annotation_notes VALUES (?, ?, ?, ?)",
            (run_uri, result.note_id, result.created_at, encoded_result),
        )
    conn.execute(
        "INSERT INTO run_annotation_mutations VALUES (?, ?, ?, ?, ?)",
        (run_uri, principal, mutation_id, digest, encoded_result),
    )
    return result


def read_notes(
    conn: sqlite3.Connection,
    run_uri: str,
    limit: int,
    cursor: str | None,
    legacy_notes: Sequence[str],
) -> RunNotePage:
    # Legacy evidence is projected without writes, including pre-annotation runs.
    notes = {note.note_id: note for note in legacy_run_notes(run_uri, legacy_notes)}
    for row in conn.execute(
        "SELECT note_json FROM run_annotation_notes WHERE run_uri=?", (run_uri,)
    ):
        note = RunNote.from_dict(json.loads(row[0]))
        notes[note.note_id] = note
    return page_notes(run_uri, tuple(notes.values()), limit, cursor)


def create_annotations_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS run_annotations (
        run_uri TEXT PRIMARY KEY, annotations_json TEXT NOT NULL,
        initialization_json TEXT NOT NULL
    )""")
    create_annotation_mutation_schema(conn)


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
