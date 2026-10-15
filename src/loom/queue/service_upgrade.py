"""Native read-only settlement proof for an explicitly selected service root."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import cast
from loom.serialization import PlainData

from .operations import OperatorObservation, inspect_native_service, _readonly_root
from ._service_lifetime import _retained_coordinator_operations


def inspect_service_settlement(
    root: str | Path, *, expected_root_id: str, include_pending_poll: bool = True
) -> OperatorObservation:
    """Observe retained native effects without stopping or initializing a role.

    This is host-local evidence, independent of the coordinator's acknowledgement
    projection. A pending agent poll is unresolved work, even with no CPU use.
    Supervisor launches must have native terminal containment evidence. Missing
    or incompatible records produce unavailable evidence, never an empty root.
    ``include_pending_poll=False`` observes assignment/containment settlement
    while a service remains accepting maintenance checks; its ordinary empty
    work poll is not a previous check's effect. Service replacement always uses
    the default, which also requires that poll to settle.
    """
    root = Path(root)
    owner = inspect_native_service(root, expected_root_id=expected_root_id)
    waits: list[str] = []
    if owner.availability != "available":
        return owner
    try:
        with _readonly_root(root) as conn:
            if owner.value["role"] == "coordinator":
                if _retained_coordinator_operations(conn):
                    waits.append("accepted_work_or_preparation")
                if conn.execute(
                    "SELECT 1 FROM agent_coordinator_references WHERE resolved = 0 LIMIT 1"
                ).fetchone():
                    waits.append("assignment_or_release")
                if conn.execute(
                    "SELECT 1 FROM agent_controls WHERE state IN ('pending_delivery','applying') OR acknowledged = 0 LIMIT 1"
                ).fetchone():
                    waits.append("control_settlement")
            elif owner.value["role"] == "local-agent":
                if conn.execute(
                    "SELECT 1 FROM agent_session_references WHERE reference_kind = 'delivery' AND resolved = 0 LIMIT 1"
                ).fetchone():
                    waits.append("local_assignment_or_release")
                if (
                    include_pending_poll
                    and conn.execute(
                        "SELECT 1 FROM agent_poll_state_local p WHERE state = 'PENDING' OR (state = 'FENCED' AND result_json IS NULL AND EXISTS (SELECT 1 FROM agent_sessions_local s WHERE s.session_id = p.session_id AND s.state = 'ACTIVE')) LIMIT 1"
                    ).fetchone()
                ):
                    waits.append("unresolved_poll")
                database = root / "supervisor" / "supervisor.sqlite"
                with sqlite3.connect(
                    database.resolve().as_uri() + "?mode=ro", uri=True
                ) as supervisor:
                    if supervisor.execute(
                        "SELECT 1 FROM launches WHERE state NOT IN ('contained','exited') LIMIT 1"
                    ).fetchone():
                        waits.append("supervisor_containment")
            else:
                raise ValueError("unsupported service role")
    except (OSError, sqlite3.Error, ValueError, KeyError, json.JSONDecodeError):
        return OperatorObservation(
            owner.owner,
            owner.observed_at,
            owner.revision,
            "unknown",
            "unavailable",
            {},
            "settlement_evidence_unavailable",
        )
    return OperatorObservation(
        owner.owner,
        owner.observed_at,
        owner.revision,
        "current",
        "available",
        {"settled": not waits, "wait_reasons": cast(list[PlainData], waits)},
    )
