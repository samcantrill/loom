"""Read and pack one submit-agent page without retaining coordinator ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
import json
import sqlite3
from time import monotonic, sleep
from typing import TYPE_CHECKING

from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageSubmission
from loom.serialization import PlainData

from ._action_results import action_attempt_cancelled
from ._agent_session_codec import _MAX_BODY_BYTES
from ._agent_session_journal import _canonical_json
from .errors import QueueServiceError

if TYPE_CHECKING:
    from .local_daemon_execution import LocalDaemonExecution
    from .slurm_ready_stage import SlurmAgentTaskRecord


def read_recoveries(conn: sqlite3.Connection, ids: tuple[str, ...]) -> dict[str, list[tuple[str, str, bool]]]:
    grouped: dict[str, list[tuple[str, str, bool]]] = {}
    if ids:
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            "SELECT json_extract(request_json, '$.assignment_id'), request_json, state, "
            "NOT (state = 'closed' AND json_extract(request_json, '$.target.kind') = 'slurm') "
            "FROM recovery_operations WHERE state IN ('pending', 'evidence_confirmed', 'closed') "
            f"AND json_extract(request_json, '$.assignment_id') IN ({placeholders}) ORDER BY rowid",
            ids,
        )
        for identity, request, state, retains in rows:
            grouped.setdefault(identity, []).append((request, state, bool(retains)))
    return grouped


@dataclass(frozen=True)
class TaskFacts:
    recoveries: Sequence[tuple[str, str, bool]]
    cancelled: bool
    probe_due: bool


def control_facts(
    owner: LocalDaemonExecution, conn: sqlite3.Connection, records: Sequence[SlurmAgentTaskRecord],
) -> dict[str, TaskFacts]:
    recoveries = read_recoveries(conn, tuple(row.assignment.assignment_id for row in records))
    now = None
    if any(row.terminal_observation is not None for row in records):
        now = owner._read_terminal_accepted_time(conn)
    cancelled = {
        key: action_attempt_cancelled(conn, *key)
        for key in dict.fromkeys((r.assignment.run_uri, r.assignment.attempt_id) for r in records)
    }
    return {
        row.assignment.assignment_id: TaskFacts(
            recoveries.get(row.assignment.assignment_id, ()),
            cancelled[row.assignment.run_uri, row.assignment.attempt_id],
            owner._terminal_probe_due(row, now),
        )
        for row in records
    }


def pack_page(
    ids: Sequence[str], cursor: str | None,
    task_at: Callable[[int], tuple[Mapping[str, PlainData], bool]],
) -> dict[str, PlainData]:
    tasks: list[PlainData] = []
    tasks_bytes = 0
    scanned = cursor
    for index, identity in enumerate(ids[:32]):
        task, withheld = task_at(index)
        next_cursor = identity if index + 1 < len(ids) else None
        envelope = {"ok": True, "result": {"tasks": [], "next_cursor": next_cursor}}
        size = len(_canonical_json(envelope).encode()) + tasks_bytes
        additional = 0 if withheld else len(_canonical_json(task).encode()) + bool(tasks)
        if size + additional > _MAX_BODY_BYTES:
            if not tasks:
                raise QueueServiceError("SLURM task exceeds control response budget")
            return {"tasks": tasks, "next_cursor": scanned}
        if not withheld:
            tasks.append(dict(task))
            tasks_bytes += additional
        scanned = identity
    return {"tasks": tasks, "next_cursor": scanned if len(ids) > 32 else None}


def read_task_page(
    owner: LocalDaemonExecution, agent_id: str, root_id: str, cursor: str | None,
) -> dict[str, PlainData]:
    config = owner.config
    with (closing(config.connect_database(config.control_database)) as control,
          closing(config.connect_database(config.execution_database)) as execution):
        # Each data_version is comparable only on the same open connection.
        # Keep both connections in autocommit while rendering the response.
        deadline = monotonic() + control.execute("PRAGMA busy_timeout").fetchone()[0] / 1000
        for conn in (control, execution):
            conn.execute("PRAGMA busy_timeout = 0")
        while True:
            try:
                page = _read_page_attempt(owner, agent_id, root_id, cursor, control, execution)
                if page is not None:
                    return page
            except sqlite3.OperationalError as exc:
                if (getattr(exc, "sqlite_errorcode", 0) & 255) != sqlite3.SQLITE_BUSY:
                    raise
                sleep(min(0.01, max(0, deadline - monotonic())))
            if monotonic() >= deadline:
                # Retain the cursor so the next turn retries a changing or busy page.
                return {"tasks": [], "next_cursor": cursor}


def _read_page_attempt(
    owner: LocalDaemonExecution, agent_id: str, root_id: str, cursor: str | None,
    control: sqlite3.Connection, execution: sqlite3.Connection,
) -> dict[str, PlainData] | None:
    scheduling = owner.scheduling_epoch
    versions = tuple(c.execute("PRAGMA data_version").fetchone()[0] for c in (execution, control))
    source, records = owner.slurm_assignments.task_page_source(
        execution, agent_id, root_id, cursor, include_records=True,
    )
    control.execute("BEGIN")
    try:
        facts = control_facts(owner, control, records)
    finally:
        control.rollback()

    def task_at(index: int) -> tuple[Mapping[str, PlainData], bool]:
        row = records[index]
        current = facts[row.assignment.assignment_id]
        value = source[index].submission_json
        submission = None if value is None else SlurmReadyStageSubmission.from_dict(json.loads(value))
        task = owner._slurm_task(row, current, submission)
        return task, any(retains for _, _, retains in current.recoveries) and task["recovery_request"] is None

    page = pack_page([row.assignment_id for row in source], cursor, task_at)
    # Pin both final read snapshots at the coordinator's decision point.
    # The projected task facts have already been read and the wire page encoded.
    try:
        with owner._daemon_owner()._state_guard():
            execution.execute("BEGIN")
            control.execute("BEGIN")
            current_versions = tuple(c.execute("PRAGMA data_version").fetchone()[0] for c in (execution, control))
            current_epoch = owner.scheduling_epoch
        if current_epoch == scheduling and (
            current_versions[0] == versions[0] or source == owner.slurm_assignments.task_page_source(
                execution, agent_id, root_id, cursor, include_records=False,
            )[0]
        ) and (
            current_versions[1] == versions[1] or facts == control_facts(owner, control, records)
        ):
            return page
    finally:
        control.rollback()
        execution.rollback()
    return None
