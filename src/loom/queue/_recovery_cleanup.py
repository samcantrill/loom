"""Coordinator-owned preview of retained recovery, using declared inventories.

A preview is an observation, not a deletion capability. Release must repeat its
checks under the coordinator reservation transaction before any filesystem work.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from . import _shared_recovery as recovery
from .errors import QueueConflictError
from ._output_selection import _authority

from ._shared_publication import RECOVERY_COMPLETE, EXECUTION_LOGS


def preview_recovery_cleanup(daemon: Any, run_uri: str) -> dict[str, Any]:
    """Describe one managed run's retained attempts without opening payloads.

    Older producers lacking an explicit complete-publication declaration remain
    ineligible. Sizes are inventory payload bytes, not filesystem block usage.
    Native assignment logs have a separate owner and must be durably published
    before a release can be approved.
    """
    daemon.admission_for_run_uri(run_uri)
    with daemon._connection() as conn:
        return _preview(daemon, run_uri, conn)


def _preview(daemon: Any, run_uri: str, conn: Any, assignment_id: str | None = None) -> dict[str, Any]:
    snapshot = _authority(daemon, run_uri).open_run(run_uri)
    stages = {stage.stage_name: stage for stage in snapshot.stages}
    rows = conn.execute(
        "SELECT r.*, a.result_json AS recovery_json FROM remote_assignments r "
        "LEFT JOIN agent_receipts a ON a.principal_id = ? "
        "AND a.operation = 'seal' AND a.idempotency_key = r.assignment_id "
        "WHERE r.run_uri = ? AND (? IS NULL OR r.assignment_id = ?) "
        "ORDER BY r.stage_name, r.attempt LIMIT 1001",
        (recovery._PRINCIPAL, run_uri, assignment_id, assignment_id),
    ).fetchall()
    if len(rows) > 1000:
        raise QueueConflictError("recovery preview exceeds assignment limit")
    entries = []
    for row in rows:
        released = _release_record(conn, row["assignment_id"])
        if released is not None:
            entries.append({
                "assignment_id": row["assignment_id"], "stage_name": row["stage_name"],
                "attempt_id": row["attempt_id"], "eligible": False,
                "retained_payload_bytes": 0 if released["state"] == "deleted" else released["payload_bytes"],
                "reclaimable_payload_bytes": 0, "reasons": ["recovery_" + released["state"]],
                "operation_id": released["operation_id"],
            })
            continue
        reasons = []
        size = 0
        if row["state"] != "RELEASED" or row["provider_release_proof_json"] is None:
            reasons.append("provider_not_settled")
        report = json.loads(row["report_json"]) if row["report_json"] else None
        if report is None or report["status"] != "SUCCEEDED":
            reasons.append("recovery_still_required")
        if row["recovery_json"] is None:
            reasons.append("recovery_not_sealed")
        else:
            reference = json.loads(row["recovery_json"])
            _, inventory = recovery.inspect(reference, daemon.config.coordinator_shared_roots)
            size = sum(member["size_bytes"] for member in inventory["members"])
            if (
                reference["identity"]["assignment_id"] != row["assignment_id"]
                or reference["identity"]["fence"] != row["fence"]
            ):
                raise QueueConflictError("recovery preview ownership conflicts")
        stage = stages.get(row["stage_name"])
        if (
            stage is None or stage.latest_commit is None
            or stage.latest_commit.attempt_id != row["attempt_id"]
        ):
            reasons.append("outputs_not_committed")
        elif not _complete_outputs(stage.artifact_facts):
            reasons.append("complete_diagnostics_not_declared")
        dependents = conn.execute(
            "SELECT r.state, r.provider_release_proof_json, d.request_json "
            "FROM remote_assignments r JOIN agent_deliveries d USING(assignment_id) "
            "WHERE r.run_uri = ? AND r.stage_name = ? AND r.attempt > ?",
            (run_uri, row["stage_name"], row["attempt"]),
        ).fetchall()
        for dependent in dependents:
            predecessors = json.loads(dependent["request_json"])["worker_metadata"].get(
                recovery.WIRE, {}
            ).get("predecessors", [])
            if any(p["identity"]["assignment_id"] == row["assignment_id"] for p in predecessors):
                if (
                    dependent["state"] != "RELEASED"
                    or dependent["provider_release_proof_json"] is None
                ):
                    reasons.append("live_recovery_dependent")
                    break
        if stage is None or not _published_logs(stage.artifact_facts, daemon.config.coordinator_shared_roots):
            reasons.append("logs_not_published")
        entries.append({
            "assignment_id": row["assignment_id"],
            "stage_name": row["stage_name"], "attempt_id": row["attempt_id"],
            "eligible": not reasons, "retained_payload_bytes": size,
            "reclaimable_payload_bytes": size if not reasons else 0,
            "reasons": reasons,
        })
    return {"run_uri": run_uri, "entries": entries}

def _complete_outputs(facts: Any) -> bool:
    names = {fact.artifact_name for fact in facts}
    for fact in facts:
        declaration = fact.artifact.metadata.get(RECOVERY_COMPLETE)
        if not isinstance(declaration, Mapping):
            continue
        required = declaration.get("required_outputs")
        if (
            set(declaration) == {"schema_version", "required_outputs"}
            and declaration["schema_version"] == 1
            and isinstance(required, (list, tuple)) and required
            and all(isinstance(name, str) for name in required)
            and set(required) == names
        ):
            return True
    return False


def _published_logs(facts: Any, roots: Any) -> bool:
    from pathlib import Path
    from loom.pipeline.stores.shared_artifacts import binding, contained, inspect_receipt

    for fact in facts:
        logs = fact.artifact.metadata.get(EXECUTION_LOGS)
        ref = binding(fact.artifact.metadata)
        if not isinstance(logs, Mapping) or ref is None:
            continue
        if not {"stdout", "stderr"} <= logs.keys() <= {"stdout", "stderr", "traceback"}:
            raise QueueConflictError("published execution log declaration conflicts")
        tree = contained(Path(roots[ref["root_id"]]["host_path"]), ref["tree"])
        receipt = inspect_receipt(tree, ref)
        members = {row["path"] for row in receipt["members"]}
        if any(path != f"_loom/logs/{stream}.log" or path not in members for stream, path in logs.items()):
            raise QueueConflictError("published execution logs are missing from their inventory")
        return True
    return False


def _release_record(conn: Any, assignment_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT result_json FROM agent_receipts WHERE principal_id = ? "
        "AND operation = 'release_recovery' AND idempotency_key = ?",
        (recovery._PRINCIPAL, assignment_id),
    ).fetchone()
    return json.loads(row["result_json"]) if row is not None else None


def release_recovery(daemon: Any, principal: Any, *, run_uri: str, assignment_id: str,
                     operation_id: str, reason: str) -> dict[str, Any]:
    """Reserve and reclaim one fully published, positively settled recovery tree.

    The durable reservation excludes future retry acquisition. Filesystem work
    runs outside the coordinator transaction; a per-assignment advisory lock
    serializes deletion/replay without blocking scheduling. A failed cleanup is
    retained for retry and never rewrites scientific results or the seal receipt.
    """
    import hashlib
    import os
    import fcntl
    from pathlib import Path
    from loom.timestamps import utc_timestamp
    from loom.pipeline.stores.shared_artifacts import encoded

    daemon.admission_for_run_uri(run_uri)
    request = dict(run_uri=run_uri, assignment_id=assignment_id,
                   operation_id=operation_id, reason=reason, principal=principal.subject)
    request_digest = hashlib.sha256(encoded(request)).hexdigest()
    with daemon._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        assignment = conn.execute(
            "SELECT * FROM remote_assignments WHERE assignment_id = ? AND run_uri = ?",
            (assignment_id, run_uri),
        ).fetchone()
        if assignment is None:
            raise QueueConflictError("recovery assignment is not in the selected run")
        # Authorization targets the assignment's recorded machine, not a caller path.
        session = conn.execute("SELECT agent_root_id FROM agent_sessions WHERE session_id = ?",
                               (assignment["session_id"],)).fetchone()
        if session is None:
            raise QueueConflictError("recovery assignment machine is unavailable")
        daemon._authorizer().require_operator(principal, "cleanup_recovery", agent_id=session["agent_root_id"])
        record = _release_record(conn, assignment_id)
        if record is not None:
            if record["request_digest"] != request_digest:
                raise QueueConflictError("recovery release is reserved by a different request")
        else:
            entry, = _preview(daemon, run_uri, conn, assignment_id)["entries"]
            if not entry["eligible"]:
                raise QueueConflictError("recovery release blocked: " + ", ".join(entry["reasons"]))
            seal = conn.execute(
                "SELECT result_json FROM agent_receipts WHERE principal_id = ? "
                "AND operation = 'seal' AND idempotency_key = ?",
                (recovery._PRINCIPAL, assignment_id),
            ).fetchone()
            record = {**request, "request_digest": request_digest, "state": "reserved",
                      "reference": json.loads(seal["result_json"]),
                      "payload_bytes": entry["retained_payload_bytes"], "created_at": utc_timestamp()}
            conn.execute(
                "INSERT INTO agent_receipts(principal_id, operation, idempotency_key, digest, result_json) "
                "VALUES (?, 'release_recovery', ?, ?, ?)",
                (recovery._PRINCIPAL, assignment_id, request_digest, encoded(record).decode()),
            )
        conn.commit()
    lock_root = Path(daemon.config.control_database).parent / "recovery-cleanup-locks"
    lock_root.mkdir(mode=0o700, exist_ok=True)
    lock_path = lock_root / hashlib.sha256(assignment_id.encode()).hexdigest()
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        with daemon._connection() as conn:
            record = _release_record(conn, assignment_id)
        if record["state"] == "deleted":
            return _release_response(record)
        record.pop("error", None)
        try:
            result = _delete_reserved_recovery(daemon, record)
            record["cleanup_result"] = result
            outcome = result["entries"][0]
            removed = outcome["outcome"] == "deleted" or (
                outcome["outcome"] == "skipped" and outcome["reason_code"] == "target_missing"
            )
            record["state"] = "deleted" if removed else "failed"
        except OSError as exc:
            record["state"] = "failed"
            record["error"] = type(exc).__name__
        with daemon._connection() as conn:
            conn.execute(
                "UPDATE agent_receipts SET result_json = ? WHERE principal_id = ? "
                "AND operation = 'release_recovery' AND idempotency_key = ?",
                (encoded(record).decode(), recovery._PRINCIPAL, assignment_id),
            )
            conn.commit()
        return _release_response(record)
    finally:
        os.close(descriptor)


def _release_response(record: Any) -> dict[str, Any]:
    return {key: record[key] for key in ("run_uri", "assignment_id", "operation_id", "state")} | {
        "reclaimed_payload_bytes": record["payload_bytes"] if record["state"] == "deleted" else 0,
        "cleanup_result": record.get("cleanup_result"), "error": record.get("error"),
    }


def _delete_reserved_recovery(daemon: Any, record: Any) -> dict[str, Any]:
    import os
    from pathlib import Path
    from loom.pipeline.stores.shared_artifacts import contained, RECEIPT
    from loom.pipeline.cleanup.execution import execute_cleanup
    from loom.pipeline.cleanup.records import (
        CleanupTargetRef, CleanupTargetKind, CleanupManagedRoot, CleanupReport,
        CleanupReportEntry, CleanupReportEntryStatus, CleanupDeleteIntent,
    )
    from loom.timestamps import utc_timestamp

    ref = recovery._reference(record["reference"])
    roots = daemon.config.coordinator_shared_roots
    root = roots[ref["root_id"]]
    if root.get("publication") != ref["budgets"] or root.get("access") != "rw":
        raise QueueConflictError("reserved recovery root qualification conflicts")
    tree = contained(Path(root["host_path"]), ref["tree"], exists=False)
    marker = tree / RECEIPT
    if marker.exists():
        recovery.inspect(ref, roots)
        # Native authority has durably retired this exact pin; preserve its seal
        # in coordinator receipts and let ordinary cleanup enforce all other pins.
        tree.chmod(tree.stat().st_mode | 0o700)
        marker.unlink()
        from ._remote_stage_execution import _fsync_directory
        _fsync_directory(tree)
    if tree.exists():
        # Sealing removed directory write bits. No file content needs modification.
        for directory, _, _ in os.walk(tree, followlinks=False):
            path = Path(directory)
            path.chmod(path.stat().st_mode | 0o700, follow_symlinks=False)
    now = utc_timestamp()
    target = CleanupTargetRef(CleanupTargetKind.LOCAL_PATH, tree.as_uri(),
                              ownership_key=ref["publication_id"])
    entry = CleanupReportEntry(record["assignment_id"], target,
                               CleanupReportEntryStatus.SELECTED, "recovery_released")
    report = CleanupReport(record["operation_id"], record["run_uri"], now, entries=(entry,))
    intent = CleanupDeleteIntent(record["operation_id"], record["principal"],
                                 record["created_at"], record["reason"],
                                 candidate_ids=(record["assignment_id"],))
    fact = execute_cleanup(
        _authority(daemon, record["run_uri"]), record["run_uri"], report, intent,
        managed_roots=(CleanupManagedRoot(ref["root_id"], Path(root["host_path"]).as_uri(),
                                         ownership_key=ref["publication_id"]),),
        emit_event=False,
    )
    if not tree.exists():
        from ._remote_stage_execution import _fsync_directory

        _fsync_directory(tree.parent)
    return fact.result.to_dict()
