"""Arbitrate a registered Slurm bootstrap using its exact authority binding."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING

from loom.pipeline.executors.slurm.history import operation_job_name
from loom.pipeline.stores.authority import PreparedBindingState
from loom.pipeline.stores.read_models import LifecycleReason
from loom.serialization import PlainData

from ._action_results import action_attempt_cancelled, attach_action_fence
from .errors import QueueConflictError

if TYPE_CHECKING:
    from loom.pipeline.stores.authority import PreparedBindingReader

    from ._agent_slurm import SlurmSubmissionProjection
    from ._coordinator_run_authority import _ScopedCoordinatorAuthority
    from .slurm_ready_stage import SlurmAgentTaskRecord, SlurmStageRecord, SQLiteSlurmStageAssignments


class SlurmBootstrapSettlement:
    def __init__(
        self, assignments: SQLiteSlurmStageAssignments, submissions: SlurmSubmissionProjection,
        connect: Callable[[], sqlite3.Connection], frozen: Callable[[str], bool],
    ) -> None:
        self.assignments = assignments
        self.submissions = submissions
        self.connect = connect
        self.frozen = frozen
        # On restart only input-ready, registered owners could have lost a grant.
        # A bound read is inconclusive while a prior authority request can still finish.
        self._lock = Lock()
        self._cancel_unbound: set[str] = set()
        self._ambiguous = dict.fromkeys(assignments.unresolved_bootstrap_grants(), 0.0)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with closing(self.connect()) as conn, conn:
            yield conn

    def restore_action_fences(self) -> None:
        """Older coordinators committed the assignment before the shared action claim."""
        with self.connection() as conn:
            missing = {(uri, attempt) for uri, attempt in conn.execute(
                "SELECT owner_run_uri, attempt_id FROM action_claims WHERE "
                "state IN ('owned','settling') AND attempt_id IS NOT NULL AND fencing_token IS NULL"
            )}
        fences = self.assignments.retained_action_fences(missing)
        if fences:
            with self.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                for run_uri, attempt_id, assignment_id, fence in fences:
                    attach_action_fence(conn, run_uri, attempt_id, assignment_id, fence, allow_settling=True)

    def needs_observation(self, assignment_id: str) -> bool:
        with self._lock:
            due = self._ambiguous.get(assignment_id)
            if due is None or monotonic() < due:
                return False
            self._ambiguous[assignment_id] = monotonic() + 1
            return True

    def forget(self, assignment_id: str) -> None:
        with self._lock:
            self._ambiguous.pop(assignment_id, None)
            self._cancel_unbound.discard(assignment_id)

    def current_owner(self, captured: SlurmStageRecord) -> SlurmAgentTaskRecord:
        identity = captured.assignment.assignment_id
        current = self.assignments.read_agent_task(identity)
        if (current.assignment != captured.assignment or current.job_id != captured.job_id
                or current.cluster != captured.cluster
                or current.bootstrap_incarnation != captured.bootstrap_incarnation
                or self.frozen(identity)):
            raise QueueConflictError("SLURM bootstrap owner changed or is under guarded recovery")
        return current

    def grant(
        self, record: SlurmStageRecord, authority_for: Callable[[str], _ScopedCoordinatorAuthority],
    ) -> str:
        assignment = record.assignment
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.current_owner(record)
            if not current.input_ready:
                raise QueueConflictError("SLURM grant requires durable inputs")
            if current.fence is not None:
                return current.fence
            if current.state != "accepted":
                raise QueueConflictError("SLURM grant requires a live accepted assignment")
            if action_attempt_cancelled(conn, assignment.run_uri, assignment.attempt_id):
                raise QueueConflictError("SLURM assignment run is cancelling")

        try:
            fence = authority_for(assignment.run_uri).grant_prepared_attempt(
                assignment.run_uri, assignment_id=assignment.assignment_id,
                attempt_id=assignment.attempt_id,
            )
            self.retain_grant(record, fence.fencing_token)
        except Exception:
            with self._lock:
                self._ambiguous[assignment.assignment_id] = 0.0
            raise
        return fence.fencing_token

    def retain_grant(self, captured: SlurmStageRecord, fence: str) -> None:
        assignment = captured.assignment
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.current_owner(captured)
            if (not current.input_ready or current.bootstrap_incarnation is None
                    or (current.fence != fence and (current.state != "accepted" or current.fence is not None))):
                raise QueueConflictError("SLURM retained grant conflicts with assignment")
            attach_action_fence(
                conn, assignment.run_uri, assignment.attempt_id, assignment.assignment_id,
                fence, allow_settling=True,
            )
        # Project the action claim first. An interruption leaves an accepted
        # assignment discoverable on restart until both commits have succeeded.
        if current.fence is None:
            with self.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = self.current_owner(captured)
                if current.bootstrap_incarnation is None:
                    raise QueueConflictError("SLURM grant requires a registered bootstrap")
                self.assignments.mark_granted(assignment.assignment_id, current.bootstrap_incarnation, fence)
        self.forget(assignment.assignment_id)

    def recover_grant(self, record: SlurmStageRecord, authority: PreparedBindingReader) -> None:
        assignment = record.assignment
        observed = authority.read_prepared_binding(
            assignment.run_uri, assignment_id=assignment.assignment_id, attempt_id=assignment.attempt_id,
        )
        if observed.fence is not None:
            self.retain_grant(record, observed.fence.fencing_token)

    def needs_cancel_receipt(self, record: SlurmStageRecord | SlurmAgentTaskRecord) -> bool:
        if record.state != "accepted" or record.bootstrap_incarnation is None or record.fence is not None:
            return False
        with self._lock:
            return record.assignment.assignment_id not in self._cancel_unbound

    def settle_cancel_binding(
        self, record: SlurmStageRecord, authority: _ScopedCoordinatorAuthority,
        failure: tuple[LifecycleReason, str] | None,
    ) -> None:
        """Resolve a potential grant before asking the agent to contain an exact fence.

        Revoking an unstarted binding prevents a concurrently issued grant from
        changing that identity. The assignment and capacity still require physical
        containment and the provider release acknowledgement.
        """
        assignment = record.assignment
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if (not self.needs_cancel_receipt(self.current_owner(record))
                    or not action_attempt_cancelled(conn, assignment.run_uri, assignment.attempt_id)):
                return

        def observe():
            return authority.read_prepared_binding(
                assignment.run_uri, assignment_id=assignment.assignment_id, attempt_id=assignment.attempt_id,
            )

        outcome = observe()
        if outcome.state is PreparedBindingState.BOUND:
            authority.unbind_prepared_attempt(
                assignment.run_uri, assignment_id=assignment.assignment_id, attempt_id=assignment.attempt_id,
            )
            # An exact bootstrap failure also accepts an ordinary unbind replay.
            outcome = observe()
        if outcome.fence is not None:
            self.retain_grant(record, outcome.fence.fencing_token)
        elif outcome.reason is not None and failure is not None and failure[0] == outcome.reason:
            self.claim_failure(record, authority, *failure)
        elif outcome.state is PreparedBindingState.UNBOUND:
            with self._lock:
                self._ambiguous.pop(assignment.assignment_id, None)
                self._cancel_unbound.add(assignment.assignment_id)

    def failure_reason(self, record: SlurmStageRecord | SlurmAgentTaskRecord) -> LifecycleReason | None:
        assignment = record.assignment
        if (record.state != "accepted" or record.bootstrap_incarnation is None
                or record.fence is not None or record.start_consumed
                or record.process_execution_id is not None or record.report_present):
            return None
        submission = self.submissions.find(assignment.operation_id)
        if (submission is None or submission.scheduler_source != "sacct"
                or submission.scheduler_state not in {"FAILED", "TIMEOUT", "CANCELLED"}
                or submission.accounting_identity is None
                or (submission.job_id, submission.cluster) != (record.job_id, record.cluster)):
            return None
        physical = submission.accounting_identity
        if (physical.job_id, physical.cluster, physical.job_name) != (
                record.job_id, record.cluster, operation_job_name(assignment.operation_id)):
            return None
        facts: dict[str, PlainData] = {
            "assignment_id": assignment.assignment_id, "incarnation": record.bootstrap_incarnation,
            "accounting": physical.to_dict(), "scheduler_state": submission.scheduler_state,
        }
        return LifecycleReason(code="worker.slurm_bootstrap_failed",
                               message="SLURM job ended before its worker was granted execution",
                               detail=facts)

    def claim_failure(
        self, record: SlurmStageRecord, authority: _ScopedCoordinatorAuthority,
        reason: LifecycleReason, now: str,
    ) -> bool:
        assignment = record.assignment
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self.failure_reason(self.current_owner(record)) != reason:
                return False
            cancelled = action_attempt_cancelled(conn, assignment.run_uri, assignment.attempt_id)
        if cancelled or not authority.fail_prepared_attempt(
                assignment.run_uri, assignment_id=assignment.assignment_id,
                attempt_id=assignment.attempt_id, reason=reason):
            observed = authority.read_prepared_binding(
                assignment.run_uri, assignment_id=assignment.assignment_id, attempt_id=assignment.attempt_id,
            )
            if observed.fence is not None:
                self.retain_grant(record, observed.fence.fencing_token)
            if observed.reason != reason:
                return False
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.current_owner(record)
            if self.failure_reason(current) != reason:
                return False
            self.assignments.claim_failed_bootstrap(current, reason.detail, now)
        self.forget(assignment.assignment_id)
        return True
