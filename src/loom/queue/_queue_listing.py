"""A bounded read of the coordinator admission journal for interactive queue lists."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from typing import cast

from loom.serialization import PlainData
from loom.timestamps import parse_timestamp

from ._admission_scan import ACTIVE_PREDICATE, PRIORITY_ORDER

CAPABILITY = "queue-list-v1"
_COLUMNS = (
    "admission_id", "queue_item_id", "admitted_by", "state", "accepted_at",
    "blocked_reason", "run_priority", "enqueue_sequence",
)


@dataclass(frozen=True, slots=True)
class QueueSelection:
    """Normalized queue filters. The server paginates only matching journal rows."""

    states: tuple[str, ...]
    include_terminal: bool
    principal: str | None

    @classmethod
    def from_request(cls, value: Mapping[str, object]) -> QueueSelection:
        from .local_daemon import LocalDaemonAdmissionState

        states = value["states"]
        terminal = value["include_terminal"]
        principal = value["principal"]
        if not isinstance(states, list) or not all(isinstance(s, str) for s in states):
            raise ValueError("queue states must be an array of admission states")
        normalized = tuple(sorted({LocalDaemonAdmissionState(s).value for s in states}))
        if not isinstance(terminal, bool) or (normalized and terminal):
            raise ValueError("select explicit admission states or all history")
        if principal is not None and (not isinstance(principal, str) or not principal):
            raise ValueError("queue principal must be a nonempty string")
        return cls(normalized, terminal, principal)

    def cursor_scope(self, coordinator_id: str) -> str:
        value = json.dumps([CAPABILITY, coordinator_id, self.states, self.include_terminal,
                            self.principal, PRIORITY_ORDER], separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()


def _after(cursor: str, scope: str) -> tuple[int, int, str]:
    try:
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(value, list) or len(value) != 4 or value[0] != scope:
            raise ValueError
        _, priority, sequence, identity = value
        if (type(priority) is not int or not -(2**63) <= priority < 2**63
                or type(sequence) is not int or not 0 <= sequence < 2**63
                or not isinstance(identity, str) or not identity):
            raise ValueError
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("queue cursor does not match this coordinator and selection") from exc
    return priority, sequence, identity


def queue_page(conn: sqlite3.Connection, coordinator_id: str, as_of: str,
               selection: QueueSelection, limit: int, cursor: str | None) -> dict[str, PlainData]:
    """Fetch one priority-ordered live page without opening any per-run owners."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("queue list limit must be in 1..100")
    conditions = []
    parameters: list[str | int] = []
    if selection.states:
        placeholders = ", ".join("?" for _ in selection.states)
        conditions.append(f"state IN ({placeholders})")
        parameters.extend(selection.states)
    elif not selection.include_terminal:
        conditions.append(ACTIVE_PREDICATE)
    if selection.principal is not None:
        conditions.append("admitted_by = ?")
        parameters.append(selection.principal)

    scope = selection.cursor_scope(coordinator_id)
    if cursor is not None:
        priority, sequence, identity = _after(cursor, scope)
        conditions.append("(run_priority < ? OR (run_priority = ? AND (enqueue_sequence, admission_id) > (?, ?)))")
        parameters.extend((priority, priority, sequence, identity))
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM managed_admissions{where} ORDER BY {PRIORITY_ORDER} LIMIT ?",
        (*parameters, limit + 1),
    ).fetchall()
    next_cursor = None
    if len(rows) > limit:
        rows.pop()
        last = rows[-1]
        offset = [scope, last["run_priority"], last["enqueue_sequence"], last["admission_id"]]
        next_cursor = base64.urlsafe_b64encode(json.dumps(offset, separators=(",", ":")).encode()).decode()
    return {"as_of": as_of, "admissions": [dict(row) for row in rows], "next_cursor": next_cursor}


def decode_queue_page(value: Mapping[str, object]) -> dict[str, PlainData]:
    from .local_daemon import LocalDaemonAdmissionState

    rows = value.get("admissions")
    if (set(value) != {"as_of", "admissions", "next_cursor"}
            or not isinstance(value["as_of"], str) or not isinstance(rows, list) or len(rows) > 100
            or (value["next_cursor"] is not None and not isinstance(value["next_cursor"], str))):
        raise ValueError("invalid queue page")
    parse_timestamp(value["as_of"])
    for row in rows:
        if (not isinstance(row, dict) or set(row) != set(_COLUMNS)
                or not all(isinstance(row[k], str) for k in ("admission_id", "queue_item_id", "accepted_at", "state"))
                or not all(type(row[k]) is int for k in ("run_priority", "enqueue_sequence"))
                or not all(row[k] is None or isinstance(row[k], str) for k in ("admitted_by", "blocked_reason"))):
            raise ValueError("invalid queue row")
        LocalDaemonAdmissionState(row["state"])
        parse_timestamp(row["accepted_at"])
    return cast(dict[str, PlainData], dict(value))
