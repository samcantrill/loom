"""Settle the exact predecessor allocation of a requested same-run continuation."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING

from loom.pipeline.status import StageStatus

from ._continuation import ContinuationConflict, ContinuationPending
from ._shared_recovery import WIRE, retention_receipts
from ._slurm_start import intended_execution_id
from .errors import QueueConflictError
from .local_daemon import LocalDaemonAdmissionState, RecoverUnknownAssignment, SlurmRecoveryTarget

if TYPE_CHECKING:
    from loom.serialization import PlainData
    from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot
    from .local_daemon_execution import LocalDaemonExecution
    from .slurm_ready_stage import SlurmStageRecord


type ObserveRetrySnapshot = Callable[
    [tuple[str, ...], Callable[[], AuthoritativeRunSnapshot]], AuthoritativeRunSnapshot
]


type AdmitRetryRecovery = Callable[[RecoverUnknownAssignment], Mapping[str, PlainData]]


PROVIDER_RECOVERY_PREFIX = "slurm-provider-close-"
_FAILED_STATES = frozenset({"TIMEOUT", "FAILED", "PREEMPTED", "NODE_FAIL", "OUT_OF_MEMORY"})
GUARDED_TERMINAL_STATES = _FAILED_STATES | {"CANCELLED", "COMPLETED"}


def reason(state: str) -> str:
    return f"Slurm reported {state} for the exact allocation without a worker result"


def terminal_state(execution: LocalDaemonExecution, record: SlurmStageRecord) -> str | None:
    """A job ID or scheduler label alone cannot identify the dead incarnation."""
    return _terminal_state(execution.slurm_submissions.find(record.assignment.operation_id), record)


def _terminal_state(observed, record: SlurmStageRecord) -> str | None:
    if (observed is None or observed.scheduler_source != "sacct"
        or observed.accounting_identity is None
        or (observed.job_id, observed.cluster) != (record.job_id, record.cluster)
        or observed.scheduler_state not in GUARDED_TERMINAL_STATES):
        return None
    return observed.scheduler_state


def reconcile(
    execution: LocalDaemonExecution, run_uri: str, *, accepted_at: str | None = None,
    observe_snapshot: ObserveRetrySnapshot | None = None,
    admit_recovery: AdmitRetryRecovery | None = None,
) -> ContinuationPending | ContinuationConflict | None:
    from .local_daemon import _RecoveryNotAccepted

    daemon = execution._daemon_owner()
    history = execution.slurm_assignments.recovery_records(run_uri)
    if not history:
        return None
    admission = daemon.admission_for_run_uri(run_uri)
    def read_snapshot() -> AuthoritativeRunSnapshot:
        return execution._authority_store(run_uri).open_run(run_uri)

    if observe_snapshot is None:
        snapshot = read_snapshot()
    else:
        # A new allocation can add a stage or attempt absent from a pending
        # snapshot. Revisit its current history before making recovery decisions.
        assignments = tuple(record.assignment.assignment_id for record, _ in history)
        snapshot = observe_snapshot(assignments, read_snapshot)
    stages = {stage.stage_name: stage for stage in snapshot.stages}
    waiting = None
    for record, evidence in history:
        assignment = record.assignment
        stage = stages.get(assignment.stage_name)
        if stage is None or stage.status in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}:
            continue
        owns_recovery = record.start_consumed and WIRE in record.delivery.worker_metadata
        provider_released = evidence is not None and evidence.get("provider_released") is True
        if owns_recovery and (provider_released or record.state == "released"):
            with daemon._connection() as conn:
                receipts = retention_receipts(conn, assignment.assignment_id)
            if "seal_unavailable" in receipts:
                return ContinuationConflict("slurm_recovery_retention_budget_exceeded")
            if not provider_released:
                waiting = "waiting_for_slurm_provider_release"
                continue
            if "seal" not in receipts:
                waiting = "waiting_for_slurm_recovery_retention"
                continue
        if record.state == "released":
            if (stage.status in {StageStatus.FAILED, StageStatus.CANCELLED}
                and admission.state not in {LocalDaemonAdmissionState.FAILED, LocalDaemonAdmissionState.CANCELLED}):
                waiting = "waiting_for_slurm_admission_settlement"
            continue
        if (record.report is not None or record.state in {"terminal", "logical_released", "rejected"}
            or stage.status in {StageStatus.FAILED, StageStatus.CANCELLED}):
            waiting = ("waiting_for_slurm_recovery_retention" if record.compute_released_at is not None
                       else "waiting_for_slurm_provider_release")
            continue
        if admission.cancellation_operation_id is not None:
            waiting = "waiting_for_slurm_provider_release"
            continue
        observed = execution.slurm_submissions.find(assignment.operation_id)
        if (accepted_at and observed is not None and observed.scheduler_source == "squeue"
            and (observed.job_id, observed.cluster) == (record.job_id, record.cluster)
            and observed.scheduler_state in {"RUNNING", "PENDING", "CONFIGURING"}
            and not observed.conflicting_handles and observed.scheduler_observed_at
            and datetime.fromisoformat(observed.scheduler_observed_at) >= datetime.fromisoformat(accepted_at)):
            # A fresh scheduler observation lets an ordinary resubmission attach
            # to the live job. Older observations cannot settle a missing worker.
            continue
        state = _terminal_state(observed, record)
        if state is None or state == "COMPLETED":
            # A late result can still arrive. The coordinator never infers a
            # successful publication or failed training from a missing result.
            waiting = "waiting_for_slurm_termination_evidence"
            continue
        process_id = record.process_execution_id
        if process_id is None and record.start_consumed and record.bootstrap_incarnation is not None:
            process_id = intended_execution_id(assignment.assignment_id, record.bootstrap_incarnation)
        if (record.state not in {"unknown", "running", "granted"}
            or record.fence is None or process_id is None or record.job_id is None or record.cluster is None):
            waiting = "waiting_for_slurm_termination_evidence"
            continue
        profile = execution._slurm_profile(assignment.profile_id, assignment.profile_configuration_fingerprint)
        if profile.accounting_history is None or profile.containment_helper is None:
            waiting = "waiting_for_slurm_containment_evidence"
            continue
        attempt = next((item for item in stage.attempts if item.attempt_id == assignment.attempt_id), None)
        if attempt is None:
            raise QueueConflictError("SLURM retry has no matching authority attempt")
        if attempt.status not in {StageStatus.SUBMITTED, StageStatus.RUNNING}:
            waiting = "waiting_for_slurm_provider_release"
            continue
        # Recovery owns each pending probe across restarts. A later exact
        # observation may requalify an incarnation after an inconclusive probe.
        with daemon._connection() as conn:
            operations = conn.execute(
                "SELECT recovery_id, state FROM recovery_operations "
                "WHERE json_extract(request_json, '$.assignment_id') = ?", (assignment.assignment_id,),
            ).fetchall()
        if any(row["state"] in {"pending", "evidence_confirmed"} for row in operations):
            waiting = "waiting_for_slurm_containment_evidence"
            continue
        generation = sum(row["recovery_id"].startswith(PROVIDER_RECOVERY_PREFIX) for row in operations)
        digest = hashlib.sha256(
            f"{assignment.assignment_id}\0{record.fence}\0{state}\0{generation}".encode()
        ).hexdigest()
        request = RecoverUnknownAssignment(
            recovery_id=PROVIDER_RECOVERY_PREFIX + digest,
            run_uri=run_uri, stage_name=assignment.stage_name, attempt=assignment.attempt,
            stage_work_id=assignment.stage_work_id, assignment_id=assignment.assignment_id,
            process_execution_id=process_id, execution_fence=record.fence,
            target=SlurmRecoveryTarget(assignment.profile_id, assignment.operation_id,
                                       record.cluster, record.job_id, record.bootstrap_incarnation),
            expected_state_version=attempt.revision.sequence,
            requested_outcome="cancelled" if state == "CANCELLED" else "failed",
            consider_retry=False, reason=reason(state),
        )
        try:
            if admit_recovery is None:
                result = daemon._admit_guarded_recovery(request, f"coordinator:{execution.coordinator_id}")
            else:
                result = admit_recovery(request)
        except _RecoveryNotAccepted:
            # A worker report, independent recovery, or a changed revision can
            # win after the snapshot. Re-read all owners on the next cycle.
            waiting = "waiting_for_slurm_admission_settlement"
            continue
        waiting = ("waiting_for_slurm_provider_release" if result["state"] == "closed"
                   else "waiting_for_slurm_containment_evidence")
    return None if waiting is None else ContinuationPending(waiting)
