"""Fresh coordinator acceptance and exact replay/retry transactions.

The protected daemon remains the sole mutable and durable owner. These concrete
operations retain its cycle lock, lifetime checks and SQLite transaction order;
accepted-run progression does not pass through fresh admission policy.
"""
from __future__ import annotations

from collections.abc import Callable
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ._service_signals import write_status
from ._coordinator_transactions import short_write
from .errors import QueueConflictError, QueueServiceError
from .local_daemon import LocalDaemonAdmissionState, _admission_from_row

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon, LocalDaemonAdmission, LocalDaemonAdmissionRequest
    from .local_daemon_execution import LocalDaemonExecution


def _commit_reference(
    daemon: LocalDaemon, execution: LocalDaemonExecution, apply: Callable[[sqlite3.Connection], None],
) -> None:
    def committed(_: None) -> None:
        daemon._scheduling_reference_revision += 1

    short_write(daemon, apply, scheduling_guard=execution.scheduling_reload_guard, committed=committed)


def _submit(
    self: LocalDaemon,
    request: LocalDaemonAdmissionRequest,
    *,
    preparation_operation_id: str | None = None,
    run_operation_id: str | None = None,
) -> LocalDaemonAdmission:
    coordinator_id = self._require_started()
    from .local_daemon_execution import load_managed_local_intent

    execution = self._execution
    if execution is None:
        raise QueueServiceError("coordinator execution is unavailable")
    # Exact concurrent submission retries share one run-local operation guard.
    with self._publication_guards.hold("admission:" + request.run_uri):
        with self._state_guard():
            epochs = (self._epoch, self._scheduling_epoch)
            config = self.config
        self._lifetime.require_accepting()
        from ._preparation_operations import (
            PREPARATION_RUN_PREFIX,
            PreparationChildReserved,
        )
        from loom.pipeline.stores import run_uri_to_path

        if preparation_operation_id is None:
            try:
                run_name = run_uri_to_path(request.run_uri).name
            except ValueError:
                run_name = ""
            if run_name.startswith(PREPARATION_RUN_PREFIX):
                raise PreparationChildReserved(
                    "preparation child run identity is reserved"
                )

        with self._connection() as conn:
            reserved = conn.execute(
                "SELECT operation_id, child_name, selected_json FROM preparation_operations WHERE child_name = ?",
                (request.queue_item_id,),
            ).fetchone()
            if preparation_operation_id is not None:
                if (
                    reserved is None
                    or reserved["operation_id"] != preparation_operation_id
                ):
                    raise QueueConflictError(
                        "preparation child admission ownership conflicts"
                    )
                selected = json.loads(str(reserved["selected_json"]))
                from loom.pipeline.stores import path_to_run_uri

                if request.run_uri != path_to_run_uri(
                    Path(selected["run_store_root"]) / str(reserved["child_name"])
                ):
                    raise QueueConflictError(
                        "preparation child run identity conflicts"
                    )
            elif (
                request.queue_item_id.startswith(PREPARATION_RUN_PREFIX)
                or reserved is not None
            ):
                raise PreparationChildReserved(
                    "preparation child queue identity is reserved"
                )
        self._preparations.check_target_submission(request, run_operation_id)
        execution = self._execution
        if execution is None:
            raise QueueServiceError("coordinator execution is unavailable")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions "
                "WHERE coordinator_id = ? AND run_uri = ?",
                (coordinator_id, request.run_uri),
            ).fetchone()
            other = conn.execute(
                "SELECT run_uri FROM managed_admissions WHERE queue_item_id = ?",
                (request.queue_item_id,),
            ).fetchone()
        if row is not None:
            existing = _admission_from_row(row)
            intent = load_managed_local_intent(
                config,
                request.run_uri,
                slurm_profiles=execution.slurm_profiles,
            )
            if (
                existing.intent_digest == intent.digest
                and existing.queue_item_id == request.queue_item_id
            ):
                if request.continuation_revision is not None:
                    return _retry_failed_admission(self,
                        existing, request, execution, parent_id=run_operation_id
                    )
                return existing
            raise QueueConflictError("managed run admission intent conflicts")
        if other is not None:
            raise QueueConflictError(
                "queue item identity already admits another run"
            )
        if request.continuation_revision is not None:
            raise QueueConflictError("retry requires an existing failed admission")

        intent = load_managed_local_intent(config, request.run_uri)
        execution.validate_fresh_intent(intent)
        run_priority = self._resolve_admission_priority(request.run_uri)
        admission_id = f"admission-{uuid4()}"
        operation_id = f"authority-bind-{uuid4()}"

        def insert(conn: sqlite3.Connection) -> None:
            if self._execution is not execution or epochs != (self._epoch, self._scheduling_epoch):
                raise QueueConflictError("admission scheduling changed during preparation")
            self._lifetime.require_accepting()
            if run_operation_id is not None:
                current = conn.execute("SELECT cancellation_requested, state FROM preparation_operations WHERE operation_id = ?", (run_operation_id,)).fetchone()
                if current is None or current["cancellation_requested"] or current["state"] in {"applied", "cancelled", "failed", "conflict"}:
                    raise QueueConflictError("run continuation is suppressed or complete")
            from ._maintenance import classify
            classify(conn, request.queue_item_id, parent_id=preparation_operation_id or run_operation_id,
                     intent=intent, preparation_child=preparation_operation_id is not None)
            accepted_at = self._accepted_time(conn)
            write_status(
                conn, "admission",
                """
                    INSERT INTO managed_admissions (
                        admission_id, queue_item_id, coordinator_id, run_uri,
                        intent_digest, execution_owner, state, accepted_at,
                        authority_operation_id, run_priority, enqueue_sequence,
                        revision, cancellation_operation_id,
                        blocked_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, NULL)
                    """,
                (
                    admission_id,
                    request.queue_item_id,
                    coordinator_id,
                    request.run_uri,
                    intent.digest,
                    "managed-stage",
                    LocalDaemonAdmissionState.PENDING_AUTHORITY.value,
                    accepted_at,
                    operation_id,
                    run_priority,
                    self._next_enqueue_sequence(conn),
                ),
            )
            if run_operation_id is not None:
                admitted = conn.execute(
                    "SELECT * FROM managed_admissions WHERE admission_id = ?",
                    (admission_id,),
                ).fetchone()
                assert admitted is not None
                self._preparations.retain_admission(
                    conn, run_operation_id, _admission_from_row(admitted)
                )

        _commit_reference(self, execution, insert)
    self._wake.set()
    return self._admission(admission_id)


def _retry_failed_admission(
    self: LocalDaemon,
    admission: LocalDaemonAdmission,
    request: LocalDaemonAdmissionRequest,
    execution: LocalDaemonExecution,
    *, parent_id: str | None = None,
) -> LocalDaemonAdmission:
    # The coordinator journal bridges its local admission update and the
    # authority's atomic, replayable lifecycle continuation across restart.
    revision = request.continuation_revision
    resume_cancelled = request.resume_cancelled_revision is not None
    key = f"admission-retry:{admission.admission_id}:{revision}"
    expected_state = LocalDaemonAdmissionState.CANCELLED if resume_cancelled else LocalDaemonAdmissionState.FAILED
    with self._connection() as conn:
        row = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        if (
            admission.state is not expected_state
            or admission.revision != revision
            or (not resume_cancelled and admission.cancellation_operation_id is not None)
        ):
            raise QueueConflictError("retry failed admission revision is stale")
        snapshot = execution.validate_admission_retry(admission, resume_cancelled=resume_cancelled)
        record = {
            "admission_id": admission.admission_id,
            "failed_revision": admission.revision,
            "authority_revision": snapshot.revision.to_dict(),
            "state": "pending",
        }
        if resume_cancelled:
            record.update(
                terminal_state=expected_state.value,
                cancellation_operation_id=admission.cancellation_operation_id,
                run_uri=admission.run_uri,
                parent_id=parent_id,
                cancelled_admission=admission.to_dict(),
                cancelled_attempts=[
                    [stage.stage_name, stage.attempts[-1].attempt_id]
                    for stage in snapshot.stages
                    if stage.status.value == "CANCELLED" and stage.attempts and stage.attempts[-1].status.value == "CANCELLED"
                ],
            )
        if resume_cancelled:
            from ._shared_recovery import assignment_rows
            cancelled = {tuple(pair) for pair in record.pop("cancelled_attempts")}
            with self._connection() as conn:
                record["cancelled_assignments"] = {
                    row["assignment_id"]: [admission.run_uri, row["stage_name"], row["attempt_id"], row["fence"]]
                    for row in assignment_rows(
                        conn, admission.run_uri, slurm_assignments=execution.slurm_assignments,
                        embedded=execution._embedded_recovery,
                    )
                    if (row["stage_name"], row["attempt_id"]) in cancelled and row["fence"] is not None
                }

        def retain(conn: sqlite3.Connection) -> None:
            current = conn.execute("SELECT state, revision FROM managed_admissions WHERE admission_id=?",
                                   (admission.admission_id,)).fetchone()
            if current is None or current["state"] != expected_state.value or current["revision"] != revision:
                raise QueueConflictError("retry failed admission revision is stale")
            from ._maintenance import classify
            classify(conn, request.queue_item_id, parent_id=parent_id)
            if parent_id is not None:
                parent = conn.execute(
                    "SELECT state, cancellation_requested FROM preparation_operations WHERE operation_id = ?",
                    (parent_id,),
                ).fetchone()
                if parent is None or parent["state"] != "applying" or parent["cancellation_requested"]:
                    raise QueueConflictError("run continuation is suppressed or complete")
            conn.execute(
                "INSERT INTO daemon_metadata(key, value) VALUES (?, ?)",
                (key, json.dumps(record)),
            )

        _commit_reference(self, execution, retain)
    else:
        record = json.loads(str(row["value"]))
    if record.get("terminal_state", "FAILED") != expected_state.value:
        raise QueueConflictError("retry terminal status conflicts")
    if record["state"] == "pending":
        _apply_admission_retry(self, key, record, execution)
    self._wake.set()
    # Run operations retain their immutable acceptance projection; direct submit
    # replay observes the admission's current state after the one continuation.
    if parent_id is not None and "accepted_admission" in record:
        from .local_daemon import LocalDaemonAdmission
        return LocalDaemonAdmission.from_dict(record["accepted_admission"])
    return self._admission(admission.admission_id)


def _apply_admission_retry(
    self: LocalDaemon, key: str, record: dict[str, Any], execution: LocalDaemonExecution
) -> None:
    from loom.pipeline.stores.read_models import BackendRevision

    admission = self._admission(record["admission_id"])
    if (
        admission.state.value != record.get("terminal_state", "FAILED")
        or admission.revision != record["failed_revision"]
        or admission.cancellation_operation_id != record.get("cancellation_operation_id")
    ):
        raise QueueConflictError("pending admission retry conflicts")
    execution.resume_failed_admission(
        admission,
        operation_id=key,
        expected_revision=BackendRevision.from_dict(record["authority_revision"]),
        resume_cancelled=record.get("terminal_state") == "CANCELLED",
    )
    record["state"] = "applied"

    def settle(conn: sqlite3.Connection) -> None:
        updated = write_status(
            conn, "admission",
            "UPDATE managed_admissions SET state = ?, blocked_reason = NULL, "
            "cancellation_operation_id = NULL, cancellation_principal_id = NULL, "
            "revision = revision + 1 WHERE admission_id = ? AND revision = ? "
            "AND cancellation_operation_id IS ?",
            (
                LocalDaemonAdmissionState.PENDING_AUTHORITY.value,
                admission.admission_id, record["failed_revision"], record.get("cancellation_operation_id"),
            ),
        )
        if updated.rowcount != 1:
            raise QueueConflictError("continuation revision changed during settlement")
        if record.get("terminal_state") == "CANCELLED":
            for assignment_id, identity in record["cancelled_assignments"].items():
                conn.execute(
                    "INSERT INTO daemon_metadata(key, value) VALUES (?, ?)",
                    (f"resume-cancelled-recovery:{assignment_id}", json.dumps(identity)),
                )
            conn.execute(
                "DELETE FROM action_graph_cancellations WHERE run_uri = ? AND operation_id = ?",
                (admission.run_uri, admission.cancellation_operation_id),
            )
            # Bound operations from the cancelled run still own their original cancellation scope.
            write_status(
                conn, "operation",
                "UPDATE preparation_operations SET selected_json=json_set(selected_json, "
                "'$.reconciliation.superseded_by', ?) "
                "WHERE kind='run' AND queue_item_id=? AND operation_id IS NOT ? "
                "AND json_type(selected_json, '$.reconciliation')='object' "
                "AND json_type(selected_json, '$.reconciliation.superseded_by') IS NULL",
                (key, admission.queue_item_id, record.get("parent_id")),
            )
        accepted = conn.execute(
            "SELECT * FROM managed_admissions WHERE admission_id = ?", (admission.admission_id,),
        ).fetchone()
        record["accepted_admission"] = _admission_from_row(accepted).to_dict()
        conn.execute(
            "UPDATE daemon_metadata SET value = ? WHERE key = ?",
            (json.dumps(record), key),
        )

    _commit_reference(self, execution, settle)


def _resume_pending_admission_retries(
    self: LocalDaemon, execution: LocalDaemonExecution
) -> None:
    with self._connection() as conn:
        pending = tuple(
            conn.execute(
                "SELECT key, value FROM daemon_metadata "
                "WHERE key LIKE 'admission-retry:%' AND json_extract(value, '$.state') = 'pending'"
            )
        )
    for row in pending:
        try:
            record = json.loads(str(row["value"]))
            admission = self._admission(record["admission_id"])
            with self._publication_guards.hold("admission:" + admission.run_uri):
                _apply_admission_retry(self, str(row["key"]), record, execution)
        except Exception:
            self._record_admission_health(
                json.loads(str(row["value"]))["admission_id"], "unavailable"
            )
