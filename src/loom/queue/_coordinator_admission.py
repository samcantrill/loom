"""Fresh coordinator acceptance and exact replay/retry transactions.

The protected daemon remains the sole mutable and durable owner. These concrete
operations retain its cycle lock, lifetime checks and SQLite transaction order;
accepted-run progression does not pass through fresh admission policy.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .errors import QueueConflictError, QueueServiceError
from .local_daemon import LocalDaemonAdmissionState, _admission_from_row

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon, LocalDaemonAdmission, LocalDaemonAdmissionRequest
    from .local_daemon_execution import LocalDaemonExecution


def _submit(
    self: LocalDaemon,
    request: LocalDaemonAdmissionRequest,
    *,
    preparation_operation_id: str | None = None,
    run_operation_id: str | None = None,
) -> LocalDaemonAdmission:
    coordinator_id = self._require_started()
    from .local_daemon_execution import load_managed_local_intent

    with self._cycle_lock:
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
                self.config,
                request.run_uri,
                slurm_profiles=execution.slurm_profiles,
            )
            if (
                existing.intent_digest == intent.digest
                and existing.queue_item_id == request.queue_item_id
            ):
                if request.retry_failed_revision is not None:
                    return _retry_failed_admission(self,
                        existing, request, execution, parent_id=run_operation_id
                    )
                return existing
            raise QueueConflictError("managed run admission intent conflicts")
        if other is not None:
            raise QueueConflictError(
                "queue item identity already admits another run"
            )
        if request.retry_failed_revision is not None:
            raise QueueConflictError("retry requires an existing failed admission")

        intent = load_managed_local_intent(self.config, request.run_uri)
        execution.validate_fresh_intent(intent)
        run_priority = self._resolve_admission_priority(request.run_uri)
        admission_id = f"admission-{uuid4()}"
        operation_id = f"authority-bind-{uuid4()}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            from ._maintenance import classify
            classify(conn, request.queue_item_id, parent_id=preparation_operation_id or run_operation_id,
                     intent=intent, preparation_child=preparation_operation_id is not None)
            accepted_at = self._accepted_time(conn)
            conn.execute(
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
            conn.commit()
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
    key = (
        f"admission-retry:{admission.admission_id}:{request.retry_failed_revision}"
    )
    with self._connection() as conn:
        row = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        if (
            admission.state is not LocalDaemonAdmissionState.FAILED
            or admission.revision != request.retry_failed_revision
            or admission.cancellation_operation_id is not None
        ):
            raise QueueConflictError("retry failed admission revision is stale")
        snapshot = execution.validate_admission_retry(admission)
        record = {
            "admission_id": admission.admission_id,
            "failed_revision": admission.revision,
            "authority_revision": snapshot.revision.to_dict(),
            "state": "pending",
        }
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            from ._maintenance import classify
            classify(conn, request.queue_item_id, parent_id=parent_id)
            conn.execute(
                "INSERT INTO daemon_metadata(key, value) VALUES (?, ?)",
                (key, json.dumps(record)),
            )
            conn.commit()
    else:
        record = json.loads(str(row["value"]))
    if record["state"] == "pending":
        _apply_admission_retry(self, key, record, execution)
    self._wake.set()
    return self._admission(admission.admission_id)


def _apply_admission_retry(
    self: LocalDaemon, key: str, record: dict[str, Any], execution: LocalDaemonExecution
) -> None:
    from loom.pipeline.stores.read_models import BackendRevision

    admission = self._admission(record["admission_id"])
    if (
        admission.state is not LocalDaemonAdmissionState.FAILED
        or admission.revision != record["failed_revision"]
        or admission.cancellation_operation_id is not None
    ):
        raise QueueConflictError("pending admission retry conflicts")
    execution.resume_failed_admission(
        admission,
        operation_id=key,
        expected_revision=BackendRevision.from_dict(record["authority_revision"]),
    )
    record["state"] = "applied"
    with self._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE managed_admissions SET state = ?, blocked_reason = NULL, "
            "revision = revision + 1 WHERE admission_id = ?",
            (
                LocalDaemonAdmissionState.PENDING_AUTHORITY.value,
                admission.admission_id,
            ),
        )
        conn.execute(
            "UPDATE daemon_metadata SET value = ? WHERE key = ?",
            (json.dumps(record), key),
        )
        conn.commit()


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
            _apply_admission_retry(self,
                str(row["key"]), json.loads(str(row["value"])), execution
            )
        except Exception:
            self._record_admission_health(
                json.loads(str(row["value"]))["admission_id"], "unavailable"
            )
