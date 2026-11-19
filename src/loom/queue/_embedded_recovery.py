"""Use the native recovery and publication protocol in the embedded agent."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from . import _shared_recovery as recovery
from ._shared_publication import identity, selected
from ._shared_staging_continuation import finish_grant_continuation, may_own_unstarted_progress
from .errors import QueueConflictError

if TYPE_CHECKING:
    from .local_daemon_execution import LocalDaemonExecution


class EmbeddedRecovery:
    def __init__(self, execution: LocalDaemonExecution):
        self.execution = execution

    def _connection(self):
        return self.execution._daemon_owner()._connection()

    def owns_root(self, alias: str, root: object) -> bool:
        counterpart = self.execution.config.coordinator_shared_roots.get(alias)
        return (
            isinstance(root, Mapping) and "publication" in root
            and isinstance(counterpart, Mapping) and "publication" in counterpart
            and Path(str(root["host_path"])).resolve() == Path(str(counterpart["host_path"])).resolve()
        )

    def rows(self, conn, run_uri, *, stage_name, limit):
        execution = self.execution
        if execution.journal is None or execution.agent_id is None:
            return []
        assignments = execution.coordinator.local_recovery_assignments(
            run_uri, agent_id=execution.config.machine_id, stage_name=stage_name, limit=limit,
        )
        if limit is not None and len(assignments) > limit:
            raise QueueConflictError("recovery history exceeds assignment limit")
        rows = []
        for assignment in assignments:
            row = execution.journal.recovery_record(assignment)
            if row is not None:
                receipts = recovery.retention_receipts(conn, assignment.assignment_id)
                rows.append({
                    **row, "agent_id": execution.agent_id, "recovery_json": receipts.get("seal"),
                    "recovery_failure_json": receipts.get("seal_unavailable"),
                })
        return rows

    def bind(self, request, assignment):
        execution = self.execution
        agent_id = execution.agent_id
        profile = execution.config.resident_worker_launch_profile
        selection = selected(request)
        assert agent_id is not None and profile is not None and selection is not None
        if not self.owns_root(selection[0], profile.shared_roots.get(selection[0])):
            raise QueueConflictError("embedded continuation requires a common publication root")
        with self._connection() as conn:
            return recovery.bind_provider_delivery(
                request, conn, assignment.run_uri, execution.config.coordinator_shared_roots,
                agent_id=agent_id, slurm_assignments=execution.slurm_assignments,
                embedded=self,
            )

    def grant(self, request, assignment, fence, roots, authority):
        execution = self.execution
        journal = execution.journal
        agent_id = execution.agent_id
        assert journal is not None and agent_id is not None

        def live_owner():
            if (
                execution.coordinator.state(assignment.assignment_id) != "granted"
                or journal.read_grant_fence(assignment.assignment_id) != fence
                or execution._attempt_cancel_requested(assignment.run_uri, assignment.attempt_id)
            ):
                raise QueueConflictError("embedded staging grant is no longer live")
            granted = authority.grant_prepared_attempt(
                assignment.run_uri, assignment_id=assignment.assignment_id,
                attempt_id=assignment.attempt_id,
            )
            if granted.fencing_token != fence:
                raise QueueConflictError("embedded staging grant fence conflicts")
            return identity(request, agent_id=agent_id, fence=fence)

        with execution._daemon_owner()._publication_guards.hold(assignment.assignment_id):
            finish_grant_continuation(
                request, roots, agent_id=agent_id, fence=fence,
                connection=self._connection, require_live_owner=live_owner,
            )

    def retain(self, request, assignment, roots):
        journal = self.execution.journal
        agent_id = self.execution.agent_id
        assert journal is not None and agent_id is not None
        row = journal.recovery_record(assignment)
        if row is None or not (
            row["start_permitted"] or may_own_unstarted_progress(row, request.worker_metadata)
        ):
            return
        proof = journal.provider_release_evidence(assignment.assignment_id)
        if proof.assignment != assignment or proof.execution_fence != row["fence"]:
            raise QueueConflictError("embedded recovery release identity conflicts")
        with self._connection() as conn:
            retained = recovery.prepare_retention(conn, row, request, roots, agent_id=agent_id)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            recovery.commit_retention(conn, retained)
            conn.commit()
