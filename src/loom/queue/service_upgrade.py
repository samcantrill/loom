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


def inspect_agent_result_recovery(
    root: str | Path, *, expected_root_id: str
) -> OperatorObservation:
    """Observe whether a resident agent can replay only completed results.

    This is eligibility evidence, not settlement or permission to stop a service.
    Fleet must own an acknowledged drain; the replacement owner must repeat the
    observation while holding the stopped agent's lock. Claims, deliveries and
    results remain untouched. Missing evidence refuses recovery.
    """
    root = Path(root)
    owner = inspect_native_service(root, expected_root_id=expected_root_id)
    if owner.availability != "available":
        return owner
    try:
        if owner.value["role"] != "local-agent":
            raise ValueError("result recovery requires a resident agent")
        with _readonly_root(root) as conn:
            results = _agent_recoverable_results(root, conn, expected_root_id)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        return OperatorObservation(
            owner.owner, owner.observed_at, owner.revision, "unknown",
            "unavailable", {}, "result_recovery_evidence_unavailable: " + str(exc),
        )
    return OperatorObservation(
        owner.owner, owner.observed_at, owner.revision, "current", "available",
        {"recoverable": True, "results": cast(list[PlainData], results)},
    )


def _agent_recoverable_results(
    root: Path, control: sqlite3.Connection, root_id: str
) -> list[dict[str, PlainData]]:
    import hashlib

    from loom._sqlite_inspection import inspect_sqlite_database
    from loom.pipeline.execution.models import StageWorkerResult
    from loom.pipeline.status import StageStatus
    from ._agent_process_supervisor import AgentProcessSupervisor, _launch_from_value
    from ._managed_local import _assignment_from_dict, _require_agent_journal_schema

    # Slurm has a separate physical owner and is deliberately outside this path.
    if (root / "slurm.sqlite").exists():
        raise ValueError("Slurm recovery is not supported")
    if control.execute(
        "SELECT 1 FROM agent_poll_state_local p WHERE state = 'PENDING' OR "
        "(state = 'FENCED' AND result_json IS NULL AND EXISTS "
        "(SELECT 1 FROM agent_sessions_local s WHERE s.session_id = p.session_id "
        "AND s.state = 'ACTIVE')) LIMIT 1"
    ).fetchone():
        raise ValueError("unresolved poll")
    if control.execute(
        "SELECT 1 FROM agent_controls_local WHERE effect_json IS NULL LIMIT 1"
    ).fetchone():
        raise ValueError("unresolved control")
    references = {
        row[1]: row[0] for row in control.execute(
            "SELECT session_id, reference_id FROM agent_session_references "
            "WHERE reference_kind = 'delivery' AND resolved = 0"
        )
    }
    with inspect_sqlite_database(root / "journal.sqlite") as execution:
        execution.row_factory = sqlite3.Row
        _require_agent_journal_schema(execution)
        if execution.execute(
            "SELECT 1 FROM diagnostic_probes WHERE state != 'released' LIMIT 1"
        ).fetchone():
            raise ValueError("unsettled diagnostic probe")
        rows = list(execution.execute(
            "SELECT * FROM assignments WHERE state NOT IN ('released', 'declined')"
        ))
        # A released claim can still have a delivery awaiting its acknowledgement.
        retained_ids = {row["assignment_id"] for row in rows}
        for identity in references:
            if identity not in retained_ids:
                row = execution.execute(
                    "SELECT * FROM assignments WHERE assignment_id = ?", (identity,)
                ).fetchone()
                if row is None:
                    raise ValueError("delivery has no execution evidence")
                rows.append(row)
    with inspect_sqlite_database(root / "supervisor" / "supervisor.sqlite") as supervisor:
        supervisor.row_factory = sqlite3.Row
        metadata = dict(supervisor.execute("SELECT key, value FROM metadata"))
        if (metadata.get("schema_version") != str(AgentProcessSupervisor._SCHEMA_VERSION)
                or metadata.get("agent_id") != root_id):
            raise ValueError("supervisor identity or schema changed")
        launches = {}
        for row in supervisor.execute("SELECT * FROM launches"):
            if row["state"] != "contained" or row["temporary_storage_pending"] or row["temporary_storage_error"]:
                raise ValueError("supervisor containment or cleanup is incomplete")
            launch = _launch_from_value(json.loads(row["launch_json"]))
            if launch.assignment_id in launches:
                raise ValueError("ambiguous supervisor launch")
            launches[launch.assignment_id] = (launch, row)
    results = []
    for row in rows:
        if row["state"] not in {"result_durable", "terminal_acknowledged", "providers_released", "released"}:
            raise ValueError("assignment has no durable result")
        identity = _assignment_from_dict(json.loads(row["identity_json"]))
        result = StageWorkerResult.from_dict(json.loads(row["result_json"]))
        if (references.get(identity.assignment_id) != identity.session_id
                or result.status is not StageStatus.SUCCEEDED
                or (result.run_uri, result.stage_name, result.attempt)
                != (identity.run_uri, identity.stage_name, identity.attempt)):
            raise ValueError("retained result or delivery identity conflicts")
        launch, receipt = launches[identity.assignment_id]
        if ((launch.agent_id, launch.session_id, launch.execution_fence, launch.process_execution_id)
                != (root_id, identity.session_id, row["grant_fence"], row["process_execution_id"])
                or receipt["exit_code"] != 0 or not receipt["successful_exit"]):
            raise ValueError("successful launch identity is unproven")
        result_path = launch.workspace_root / "worker-result.json"
        with result_path.open("rb") as stream:
            result_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if result_digest != receipt["result_digest"]:
            raise ValueError("worker result digest changed")
        results.append({
            "assignment_id": identity.assignment_id,
            "session_id": identity.session_id,
            "fence": row["grant_fence"],
            "stage_name": identity.stage_name,
            "attempt": identity.attempt,
            "worker_result_sha256": result_digest,
            "launch_operation_id": launch.launch_operation_id,
        })
    return results


def inspect_coordinator_result_recovery(
    root: str | Path, *, expected_root_id: str,
    agent_results: list[dict[str, PlainData]],
) -> OperatorObservation:
    """Match retained remote assignments against host-proved successful results.

    Admitted DAGs may remain pending, but each in-flight remote assignment must
    have a corresponding agent proof. Preparation, cancellation, unknown controls
    and startup attachments still refuse. The Fleet owner supplies observations
    from its selected hosts; this function neither drains nor closes admission.
    """
    from ._service_lifetime import _retained_coordinator_mutations

    root = Path(root)
    owner = inspect_native_service(root, expected_root_id=expected_root_id)
    if owner.availability != "available":
        return owner
    try:
        if owner.value["role"] != "coordinator":
            raise ValueError("result recovery requires a pure coordinator")
        results = {item["assignment_id"]: item for item in agent_results}
        if len(results) != len(agent_results):
            raise ValueError("duplicate assignment proof")
        from loom._sqlite_inspection import inspect_sqlite_database
        with inspect_sqlite_database(root / "execution.sqlite") as execution:
            identities = list(execution.execute(
                "SELECT role, stable_id FROM local_daemon_owner_identity"
            ))
            if [tuple(row) for row in identities] != [("coordinator", expected_root_id)]:
                raise ValueError("coordinator execution identity changed")
            if execution.execute(
                "SELECT 1 FROM slurm_stage_assignments WHERE state != 'released' LIMIT 1"
            ).fetchone():
                raise ValueError("Slurm recovery is not supported")
            for row in execution.execute(
                "SELECT assignment_id FROM coordinator_assignments WHERE state != 'released'"
            ):
                if row[0] not in results:
                    raise ValueError("physical assignment lacks matching agent proof")
        with _readonly_root(root) as conn:
            if _retained_coordinator_mutations(conn):
                raise ValueError("coordinator mutation remains active")
            for table in ("agent_controls", "remote_assignment_controls"):
                if conn.execute(
                    f"SELECT 1 FROM {table} WHERE state IN ('pending_delivery','applying') "
                    "OR acknowledged = 0 LIMIT 1"
                ).fetchone():
                    raise ValueError("unresolved control")
            if conn.execute(
                "SELECT 1 FROM managed_admissions WHERE cancellation_operation_id IS NOT NULL "
                "AND state NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED') LIMIT 1"
            ).fetchone():
                raise ValueError("cancellation remains active")
            # Resident workers use an assignment-local run URI. The shared
            # authority identity is assignment/session/fence, not that URI.
            names = ("assignment_id", "session_id", "fence", "stage_name", "attempt")
            for row in conn.execute(
                "SELECT " + ", ".join(names) + " FROM remote_assignments "
                "WHERE state NOT IN ('RELEASED', 'FAILED', 'CANCELLED')"
            ):
                proof = results.get(row[0])
                if proof is None:
                    raise ValueError("remote assignment lacks matching agent proof")
                mismatches = [name for name, value in zip(names, row, strict=True) if proof[name] != value]
                if mismatches:
                    raise ValueError("remote assignment lacks matching agent proof: " + ", ".join(mismatches))
            for session, kind, assignment in conn.execute(
                "SELECT session_id, reference_kind, reference_id FROM agent_coordinator_references WHERE resolved = 0"
            ):
                if kind != "delivery" or results.get(assignment, {}).get("session_id") != session:
                    raise ValueError("remote reference lacks matching agent proof")
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        return OperatorObservation(
            owner.owner, owner.observed_at, owner.revision, "unknown", "unavailable",
            {}, "result_recovery_evidence_unavailable: " + str(exc),
        )
    return OperatorObservation(
        owner.owner, owner.observed_at, owner.revision, "current", "available",
        {"recoverable": True},
    )


def require_result_recovery(
    root: Path, *, expected_root_id: str, role: str,
    agent_results: list[dict[str, PlainData]],
) -> OperatorObservation:
    """Recheck a Fleet operation's previously captured result cohort.

    Called at stop and again under the stopped native owner's replacement lock.
    Completed references may disappear; new or changed results cannot join the
    operation. This never labels outstanding publication as settled.
    """
    from .errors import QueueConflictError

    if role == "agent":
        fact = inspect_agent_result_recovery(root, expected_root_id=expected_root_id)
        if fact.availability == "available":
            expected = {item["assignment_id"]: item for item in agent_results}
            for result in fact.to_dict()["value"]["results"]:
                if expected.get(result["assignment_id"]) != result:
                    raise QueueConflictError("retained result cohort changed")
    elif role == "coordinator":
        fact = inspect_coordinator_result_recovery(
            root, expected_root_id=expected_root_id, agent_results=agent_results,
        )
    else:
        raise QueueConflictError("unsupported result recovery role")
    if fact.availability != "available" or not fact.value.get("recoverable"):
        raise QueueConflictError("native result recovery refused: " + str(fact.reason))
    return fact
