"""Progress already accepted runs and invoke the current placement policy.

The composition retains its cycle contexts, scheduling epoch and launch lock.
These operations drive the existing graph, cancellation and settlement owners;
per-run authority still decides lifecycle and successful output commitment.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from loom.pipeline.orchestration import RunOrchestrator
from loom.pipeline.runtime import ExecutionRouteKind
from loom.pipeline.status import StageStatus
from loom.scheduling import PolicyDecisionState
from ._managed_local import ManagedLocalError
from ._remote_stage_execution import ResidentProfileDescriptor
from .errors import QueueServiceError
from .local_daemon import LocalDaemonAdmissionState

if TYPE_CHECKING:
    from loom.pipeline.orchestration import ExecutionRequirement, SQLiteStageWorkStore, StageWorkRecord
    from loom.pipeline.planning import AttemptReadiness, StagePlan
    from loom.pipeline.stores.read_models import BackendRevision
    from ._coordinator_run_authority import _ScopedCoordinatorAuthority
    from .local_daemon import LocalDaemonAdmission
    from .local_daemon_execution import LocalDaemonExecution, ManagedLocalIntent


@dataclass(frozen=True, slots=True)
class LocalDaemonExecutionOutcome:
    state: LocalDaemonAdmissionState
    reason: str | None = None


def reconcile_admission(
    self: LocalDaemonExecution, admission: LocalDaemonAdmission
) -> LocalDaemonExecutionOutcome:
    """Reconcile one run into durable ready work without selecting capacity."""

    intent, scoped_authority = self._admission_context(admission)
    self._cycle_contexts[admission.admission_id] = (intent, scoped_authority)
    outcome = _reconcile_admission(self, admission, intent, scoped_authority)
    if outcome.state not in {
        LocalDaemonAdmissionState.SUCCEEDED,
        LocalDaemonAdmissionState.FAILED,
        LocalDaemonAdmissionState.CANCELLED,
    }:
        return outcome
    if self._action_resolution is not None:
        self._action_resolution.reconcile_producers(admission.run_uri)
    slurm_in_flight, slurm_diagnostic = self._reconcile_slurm_run(
        admission.run_uri, scoped_authority
    )
    return _settled_terminal_outcome(self,
        admission.run_uri,
        outcome,
        slurm_in_flight=slurm_in_flight,
        slurm_diagnostic=slurm_diagnostic,
    )


def _reconcile_admission(
    self: LocalDaemonExecution,
    admission: LocalDaemonAdmission,
    intent: ManagedLocalIntent,
    scoped_authority: _ScopedCoordinatorAuthority,
) -> LocalDaemonExecutionOutcome:
    action_resolver = self._action_resolution
    if action_resolver is not None:
        action_resolver.reconcile_producers(admission.run_uri)
    cancelling = admission.cancellation_operation_id is not None or self.cancellation_operation(admission.admission_id) is not None
    if cancelling:
        outcome = self._cancel(admission, scoped_authority, intent.plan.stage_order)
        if action_resolver is None or not any(action_resolver.store.producer_needed(admission.run_uri, node) for node in intent.plan.stage_order):
            return outcome
    else:
        self.admission_activated(admission.admission_id)

    placements = dict(intent.placements)
    orchestrator = RunOrchestrator(
        authority=scoped_authority,
        store=self.stage_work_store,
        owner_id=self.coordinator_id,
    )
    _decision_as_of, snapshot_time = self._daemon_owner()._accepted_snapshot()
    snapshot = scoped_authority.open_run(admission.run_uri)
    slurm_in_flight, slurm_diagnostic = self._reconcile_slurm_run(
        admission.run_uri, scoped_authority
    )
    snapshot = scoped_authority.open_run(admission.run_uri)
    terminal = None if cancelling else self._terminal_outcome(
        admission,
        intent.plan,
        snapshot,
        scoped_authority,
        continue_independent=intent.continue_independent,
    )
    if terminal is not None and not cancelling:
        return terminal
    def resolve_ready(stage_plan: StagePlan, readiness: AttemptReadiness, revision: BackendRevision) -> BackendRevision | None:
        if cancelling:
            return None if action_resolver is not None and action_resolver.store.producer_needed(admission.run_uri, stage_plan.stage_name) else revision
        return None if action_resolver is None else action_resolver.resolve(admission, intent, scoped_authority, stage_plan, readiness, revision)

    orchestrator.reconcile(
        admission_id=admission.admission_id,
        plan=intent.plan,
        authority_snapshot=snapshot,
        placements=placements,
        execution_requirements=intent.execution_requirements,
        ready_action=resolve_ready,
        ready_at=snapshot_time,
        run_priority=admission.run_priority,
        enqueue_sequence=admission.enqueue_sequence,
        controller_action=None if cancelling else lambda stage_plan, readiness: (
            self._apply_controller_action(
                scoped_authority,
                admission.run_uri,
                stage_plan,
                readiness,
                admission=admission,
            )
        ),
    )
    snapshot = scoped_authority.open_run(admission.run_uri)
    slurm_in_flight, slurm_diagnostic = self._reconcile_slurm_run(
        admission.run_uri, scoped_authority
    )
    snapshot = scoped_authority.open_run(admission.run_uri)
    terminal = None if cancelling else self._terminal_outcome(
        admission,
        intent.plan,
        snapshot,
        scoped_authority,
        continue_independent=intent.continue_independent,
    )
    if terminal is not None:
        return terminal
    if cancelling:
        return self._cancel(admission, scoped_authority, intent.plan.stage_order)
    if slurm_in_flight or any(
        stage.status in {StageStatus.SUBMITTED, StageStatus.RUNNING}
        for stage in snapshot.stages
    ):
        return LocalDaemonExecutionOutcome(
            LocalDaemonAdmissionState.ACTIVE,
            slurm_diagnostic or "assignment execution remains in flight",
        )
    return LocalDaemonExecutionOutcome(
        LocalDaemonAdmissionState.WAITING,
        slurm_diagnostic
        or "no dependency-ready stage currently has managed capacity",
    )


def _settled_terminal_outcome(
    self: LocalDaemonExecution,
    run_uri: str,
    terminal: LocalDaemonExecutionOutcome,
    *,
    slurm_in_flight: bool,
    slurm_diagnostic: str | None,
) -> LocalDaemonExecutionOutcome:
    """Publish terminal truth only after ordinary assignment release settles."""

    if slurm_in_flight:
        return LocalDaemonExecutionOutcome(
            LocalDaemonAdmissionState.ACTIVE,
            slurm_diagnostic or "SLURM release remains durably in flight",
        )
    if any(
        not self._recovery_retains_assignment(assignment_id)
        for assignment_id, _state in self.coordinator.list_run_live_states(run_uri)
    ):
        return LocalDaemonExecutionOutcome(
            LocalDaemonAdmissionState.ACTIVE,
            "managed assignment release remains durably in flight",
        )
    return terminal


def schedule_once(
    self: LocalDaemonExecution, admissions: Mapping[str, LocalDaemonAdmission]
) -> tuple[str, LocalDaemonExecutionOutcome] | None:
    """Select and durably start one assignment from the global ready window."""

    if not admissions:
        return None
    with self._launch_lock:
        decision_as_of, snapshot_time = self._daemon_owner()._accepted_snapshot()
        window = tuple(record for record in self.stage_work_store.ready_window()
                       if not self._attempt_cancel_requested(record.run_uri, record.attempt_id))
        if not window:
            return None
        contexts = self._cycle_contexts
        exhausted_admissions: set[str] = set()
        for record in window:
            admission = admissions.get(record.admission_id)
            if admission is None or record.placement.route.kind not in {
                ExecutionRouteKind.MANAGED_AGENT,
                ExecutionRouteKind.SLURM,
            }:
                continue
            context = contexts.get(record.admission_id)
            if context is None:
                continue
            if (
                self.coordinator.run_active_assignment_count(admission.run_uri)
                >= context[0].max_parallel_stages
            ):
                exhausted_admissions.add(record.admission_id)
        remote_targets = self._remote_candidates()
        local_candidate = (
            self._candidate()
            if self.agent_id is not None and self.local_profile_ready
            else None
        )
        excluded_work: set[str] = set()
        attempted_slurm: set[str] = set()
        while True:
            managed_records = tuple(
                record
                for record in window
                if record.stage_work_id not in excluded_work
                and record.admission_id in admissions
                and record.admission_id in contexts
                and record.admission_id not in exhausted_admissions
                and record.placement.route.kind is ExecutionRouteKind.MANAGED_AGENT
            )
            local_profile = (
                None
                if self.config.resident_worker_launch_profile is None
                else ResidentProfileDescriptor.from_dict(
                    self.config.resident_worker_launch_profile.descriptor
                )
            )
            candidates = tuple(
                [
                    local_candidate
                    for _ in (0,)
                    if local_candidate is not None
                    and local_candidate.candidate_id not in remote_targets
                    and local_profile is not None
                    and any(
                        _profile_satisfies_requirement(
                            local_profile, record.execution_requirement
                        )
                        for record in managed_records
                    )
                ]
                + [
                    target[0]
                    for _, target in sorted(remote_targets.items())
                    if any(
                        _profile_satisfies_requirement(
                            target[1].profile, record.execution_requirement
                        )
                        for record in managed_records
                    )
                ]
            )
            decision = self._scheduling.kernel(managed_records).decide(
                work=tuple(record.to_work_item() for record in managed_records),
                candidates=candidates,
                as_of=snapshot_time,
            )
            selected_id = (
                decision.stage_work_id
                if decision.state is PolicyDecisionState.SELECT
                else None
            )
            selected_index = next(
                (
                    index
                    for index, record in enumerate(window)
                    if record.stage_work_id == selected_id
                ),
                len(window),
            )
            for record in window[: selected_index + 1]:
                if (
                    record.stage_work_id in attempted_slurm
                    or record.admission_id not in admissions
                    or record.admission_id not in contexts
                    or record.admission_id in exhausted_admissions
                    or record.placement.route.kind is not ExecutionRouteKind.SLURM
                ):
                    continue
                attempted_slurm.add(record.stage_work_id)
                admission = admissions[record.admission_id]
                intent, authority = contexts[record.admission_id]
                snapshot = authority.open_run(admission.run_uri)
                if not self._failure_policy_allows_new_work(intent, snapshot):
                    exhausted_admissions.add(record.admission_id)
                    continue
                outcome = self._dispatch_slurm_ready(
                    admission=admission,
                    intent=intent,
                    authority=authority,
                    snapshot=snapshot,
                    stage_work_id=record.stage_work_id,
                )
                if (
                    outcome is not None
                    and outcome.state is LocalDaemonAdmissionState.ACTIVE
                ):
                    return admission.admission_id, outcome
            if selected_id is None:
                return None
            record = _stage_work(self.stage_work_store, selected_id)
            admission = admissions.get(record.admission_id)
            if admission is None:
                excluded_work.add(record.stage_work_id)
                continue
            intent, authority = contexts[record.admission_id]
            snapshot = authority.open_run(admission.run_uri)
            if not self._failure_policy_allows_new_work(intent, snapshot):
                exhausted_admissions.add(record.admission_id)
                continue
            candidate_id = cast(str, decision.candidate_id)
            remote_target = remote_targets.get(candidate_id)
            local_profile = (
                None
                if self.config.resident_worker_launch_profile is None
                else ResidentProfileDescriptor.from_dict(
                    self.config.resident_worker_launch_profile.descriptor
                )
            )
            selected_profile = (
                local_profile if remote_target is None else remote_target[1].profile
            )
            if selected_profile is None or not _profile_satisfies_requirement(
                selected_profile, record.execution_requirement
            ):
                if remote_target is not None:
                    del remote_targets[candidate_id]
                else:
                    excluded_work.add(record.stage_work_id)
                continue
            if remote_target is not None and not self._remote_eligible(
                intent=intent, snapshot=snapshot, record=record
            ):
                del remote_targets[candidate_id]
                continue
            try:
                started = self._execute(
                    admission=admission,
                    intent=intent,
                    authority=authority,
                    snapshot=snapshot,
                    record=record,
                    decision=decision,
                    remote_targets={
                        key: value[1] for key, value in remote_targets.items()
                    },
                    decision_as_of=decision_as_of,
                    execution_started=lambda: None,
                )
            except ManagedLocalError as exc:
                # The reserve operation is the final capacity and
                # max-parallel CAS.  A concurrent run-limit loser is
                # bypassed, while other offer/reservation failures end this
                # turn so an unresolved offer cannot be reinterpreted.
                if str(exc) == "run active-assignment limit reached":
                    exhausted_admissions.add(record.admission_id)
                    continue
                return None
            if not started:
                excluded_work.add(record.stage_work_id)
                continue
            return admission.admission_id, LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.ACTIVE,
                "assignment was durably accepted",
            )


def _profile_satisfies_requirement(
    profile: ResidentProfileDescriptor, requirement: ExecutionRequirement
) -> bool:
    """Compare inert identities before any reservation or delivery."""

    return (
        profile.project_fingerprint == requirement.project_fingerprint
        and profile.environment_fingerprint == requirement.environment_fingerprint
        and profile.executor_fingerprint == requirement.executor_fingerprint
    )


def _stage_work(store: SQLiteStageWorkStore, stage_work_id: str) -> StageWorkRecord:
    for record in store.list_stage_work():
        if record.stage_work_id == stage_work_id:
            return record
    raise QueueServiceError("selected stage work disappeared before reservation")
