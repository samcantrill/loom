"""Authenticated Slurm bootstrap lifecycle, from registration to logical release."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loom.pipeline.stores.authority import ExecutionFence

from ._action_results import action_attempt_cancelled
from .errors import QueueConflictError, QueueServiceError

if TYPE_CHECKING:
    from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
    from loom.serialization import PlainData

    from ._coordinator_run_authority import _ScopedCoordinatorAuthority
    from ._remote_stage_execution import _RemoteExecutionReport
    from ._slurm_bootstrap_settlement import SlurmBootstrapSettlement
    from .slurm_ready_stage import SlurmStageRecord


@dataclass
class SlurmBootstrapLifecycle:
    settlement: SlurmBootstrapSettlement
    profile_for: Callable[[str, str], SlurmReadyStageProfile]
    authority_for: Callable[[str], _ScopedCoordinatorAuthority]
    accepted_time: Callable[[], str]
    shared_roots: Callable[[], Mapping[str, PlainData]]
    hold_publication: Callable[[str], AbstractContextManager]
    finalize_result: Callable[[SlurmStageRecord, str], None]

    def slurm_register(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        operation_id: str,
        request_digest: str,
        job_id: str,
        cluster: str | None,
        incarnation: str,
        capability: str,
    ) -> SlurmStageRecord:
        retained = self.settlement.assignments.read_operation(operation_id)
        profile = self.profile_for(
            retained.assignment.profile_id,
            retained.assignment.profile_configuration_fingerprint,
        )
        self._require_principal(profile, principal_id, credential_id)
        if (
            retained.assignment.profile_id != profile.profile_id
            or retained.assignment.profile_descriptor != profile.descriptor
            or retained.assignment.profile_configuration_fingerprint
            != profile.configuration_fingerprint
            or retained.assignment.request_digest != request_digest
        ):
            raise QueueConflictError("SLURM bootstrap profile conflicts")
        # A rejected capability must not associate or conflict a scheduler
        # handle.  The assignment store owns proof, binding, consumption, and
        # replay in one transaction; only that proof can cross the submission
        # mutation boundary below.
        submission_before = self.settlement.submissions.read(operation_id)
        if submission_before.job_id is not None and (
            submission_before.job_id != job_id or submission_before.cluster != cluster
        ):
            raise QueueConflictError("SLURM bootstrap job handle conflicts")
        registered = self.settlement.assignments.register_bootstrap(
            operation_id,
            request_digest=request_digest,
            job_id=job_id,
            cluster=cluster,
            incarnation=incarnation,
            capability=capability,
            accepted_time=(
                self.accepted_time()
                if profile.job_private_file_provider.delivery_kind == "user_private_file_v1"
                else None
            ),
        )
        return registered

    def slurm_input_chunk(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
        transfer_id: str,
        offset: int,
    ) -> tuple[bytes, bool]:
        self._authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        return self.settlement.assignments.read_input_chunk(
            assignment_id, incarnation, transfer_id, offset
        )

    def slurm_inputs_ready(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
    ) -> bool:
        self._authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        return self.settlement.assignments.mark_input_ready(assignment_id, incarnation)

    def slurm_grant(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
    ) -> str:
        record = self._authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        fence = self.settlement.grant(record, self.authority_for)
        from ._shared_staging_continuation import WIRE as staging_wire
        from ._shared_staging_continuation import finish_grant_continuation, requested
        if requested(record.delivery) or staging_wire in record.delivery.worker_metadata:
            # A grant reply can cause a container to bind this directory before
            # start permission. Finish the handoff before exposing that reply.
            with self.hold_publication(assignment_id):
                def live_owner():
                    current = self._authorized_record(
                        principal_id, credential_id, assignment_id, incarnation,
                    )
                    if (current.delivery != record.delivery or current.fence != fence
                        or current.state != "granted" or current.start_consumed):
                        raise QueueConflictError("staging continuation grant is no longer live")
                    with self.settlement.connection() as conn:
                        if action_attempt_cancelled(conn, current.assignment.run_uri, current.assignment.attempt_id):
                            raise QueueConflictError("staging continuation grant is cancelled")
                    observed = self.authority_for(current.assignment.run_uri).read_prepared_binding(
                        current.assignment.run_uri, assignment_id=assignment_id,
                        attempt_id=current.assignment.attempt_id,
                    )
                    if observed.fence is None or observed.fence.fencing_token != fence:
                        raise QueueConflictError("staging continuation grant fence conflicts")
                    from ._shared_publication import identity
                    return identity(current.delivery, agent_id=current.assignment.agent_id, fence=fence)

                finish_grant_continuation(
                    record.delivery, self.shared_roots(),
                    agent_id=record.assignment.agent_id, fence=fence,
                    connection=self.settlement.connection,
                    require_live_owner=live_owner,
                )
        return fence

    def slurm_start_permit(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
        fence: str,
        request_id: str | None = None,
    ) -> bool:
        record = self._authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        if record.fence != fence or record.state not in {
            "granted",
            "running",
            "terminal",
            "logical_released",
            "released",
        }:
            raise QueueConflictError("SLURM start permit fence conflicts")
        with self.settlement.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if action_attempt_cancelled(conn, record.assignment.run_uri, record.assignment.attempt_id):
                conn.commit()
                return False
            if request_id is not None and record.state != "granted":
                conn.commit()
                return False
            from ._shared_staging_continuation import WIRE as staging_wire
            from ._shared_staging_continuation import (
                requested,
                require_grant_continuation,
            )
            if requested(record.delivery) or staging_wire in record.delivery.worker_metadata:
                require_grant_continuation(
                    record.delivery, conn, agent_id=record.assignment.agent_id, fence=fence,
                )
            permitted = self.settlement.assignments.consume_start(assignment_id, request_id=request_id)
            conn.commit()
            return permitted

    def slurm_started(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
        fence: str,
        process_execution_id: str,
    ) -> None:
        _safe_identifier(process_execution_id, "SLURM process execution ID")
        record = self._authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        if record.fence != fence or not record.start_consumed:
            raise QueueConflictError("SLURM execution requires the permitted fence")
        authority = self.authority_for(record.assignment.run_uri)
        authority.confirm_execution_started(
            record.assignment.run_uri,
            fence=ExecutionFence(assignment_id, record.assignment.attempt_id, fence),
        )
        self.settlement.assignments.mark_running(
            assignment_id,
            incarnation,
            fence,
            process_execution_id,
        )

    def slurm_declare_report(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
        fence: str,
        report: _RemoteExecutionReport,
    ) -> None:
        self._authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        self.settlement.assignments.declare_report(assignment_id, incarnation, fence, report)

    def slurm_output_chunk(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
        transfer_id: str,
        offset: int,
        data: bytes,
        final: bool,
    ) -> int:
        self._authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        return self.settlement.assignments.write_output_chunk(
            assignment_id,
            incarnation,
            transfer_id,
            offset,
            data,
            final=final,
        )

    def slurm_commit_result(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
        fence: str,
    ) -> None:
        with self.hold_publication(assignment_id):
            record = self._authorized_record(
                principal_id, credential_id, assignment_id, incarnation
            )
            self.finalize_result(record, fence)

    def slurm_release(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
    ) -> None:
        record = self._authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        if record.state == "terminal":
            self.settlement.assignments.advance(
                assignment_id, expected="terminal", next_state="logical_released"
            )

    def _authorized_record(
        self,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
    ) -> SlurmStageRecord:
        record = self.settlement.assignments.read(assignment_id)
        profile = self.profile_for(
            record.assignment.profile_id,
            record.assignment.profile_configuration_fingerprint,
        )
        self._require_principal(profile, principal_id, credential_id)
        if (
            record.assignment.profile_id != profile.profile_id
            or record.assignment.profile_descriptor != profile.descriptor
            or record.bootstrap_incarnation != incarnation
        ):
            raise QueueConflictError("SLURM bootstrap authorization conflicts")
        if record.terminal_observation is not None and record.terminal_observation.get("phase") == "bootstrap":
            raise QueueConflictError("SLURM bootstrap already failed before execution")
        return record

    @staticmethod
    def _require_principal(
        profile: SlurmReadyStageProfile,
        principal_id: str,
        credential_id: str | None,
    ) -> None:
        if (
            profile.bootstrap_principal_id != principal_id
            or profile.credential_reference != credential_id
        ):
            raise QueueServiceError("SLURM bootstrap principal is not authorized")


def _safe_identifier(value: object, field: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:@+"
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or any(char not in allowed for char in value)
    ):
        raise QueueServiceError(f"{field} is invalid")
    return value
