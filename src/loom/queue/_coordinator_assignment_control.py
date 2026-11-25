"""Authorize and settle a coordinator assignment-control receipt in one transaction."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import sqlite3

from loom.serialization import PlainData, freeze_plain_data

from .agent_sessions import AgentAssignmentControl, _identifier, _managed_containment_evidence
from .errors import QueueConflictError, QueueServiceError


def acknowledge(
    session_id: str,
    operation_id: str,
    *,
    code: str,
    evidence: Mapping[str, object] | None,
    write: Callable[[Callable[[sqlite3.Connection], Mapping[str, PlainData]]], Mapping[str, PlainData]],
    authorize_session: Callable[[sqlite3.Connection], None],
) -> Mapping[str, PlainData]:
    _identifier(session_id, "session_id")
    _identifier(operation_id, "operation_id")
    if code not in {"never_started", "contained", "terminal", "unknown"}:
        raise QueueServiceError("assignment control result code is invalid")
    parsed_evidence = (
        _managed_containment_evidence(evidence)
        if code == "contained" and evidence is not None
        else None
    )
    if code == "contained" and parsed_evidence is None:
        raise QueueServiceError(
            "contained assignment control requires supervisor evidence"
        )
    if code != "contained" and evidence is not None:
        raise QueueServiceError(
            "non-contained assignment control cannot carry containment evidence"
        )
    encoded_evidence = (
        None
        if parsed_evidence is None
        else json.dumps(
            dict(parsed_evidence), sort_keys=True, separators=(",", ":")
        )
    )

    def apply(conn: sqlite3.Connection) -> Mapping[str, PlainData]:
        authorize_session(conn)
        row = conn.execute(
            "SELECT request_json, result_code, evidence_json FROM remote_assignment_controls "
            "WHERE operation_id = ? AND session_id = ?",
            (operation_id, session_id),
        ).fetchone()
        if row is None:
            raise QueueConflictError("assignment control is unavailable")
        control = AgentAssignmentControl.from_value(
            json.loads(str(row["request_json"]))
        )
        if row["result_code"] is not None and str(row["result_code"]) != code:
            raise QueueConflictError("assignment control result conflicts")
        if (
            row["evidence_json"] is not None
            and str(row["evidence_json"]) != encoded_evidence
        ):
            raise QueueConflictError("assignment control evidence conflicts")
        state = "applied" if code != "unknown" else "settling"
        conn.execute(
            "UPDATE remote_assignment_controls SET state = ?, result_code = ?, "
            "evidence_json = ?, acknowledged = 1 WHERE operation_id = ?",
            (state, code, encoded_evidence, operation_id),
        )
        return freeze_plain_data(
            {
                "operation_id": control.operation_id,
                "assignment_id": control.assignment_id,
                "state": state,
                "code": code,
                "evidence": parsed_evidence,
            },
            path="assignment control acknowledgement",
        )

    return write(apply)
