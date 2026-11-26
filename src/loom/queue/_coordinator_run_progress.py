"""Progress already accepted runs and invoke the current placement policy.

The composition retains its cycle contexts, scheduling epoch and launch lock.
These operations drive the existing graph, cancellation and settlement owners;
per-run authority still decides lifecycle and successful output commitment.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from loom.pipeline.orchestration import READY_WINDOW_LIMIT, RunOrchestrator, SubmittedContainerRequirement
from .submitted_execution import SubmittedContainerCapability
from loom.pipeline.planning import PlanAction
from loom.pipeline.runtime import ExecutionRouteKind
from loom.pipeline.status import StageStatus
from loom.scheduling import PolicyDecisionState
from ._admission_scan import SchedulingAdmissions
from ._recovery_retry import _RecoveryRetry
from ._run_observations import ObservationSteps, RunObservationPending, RunSteps
from ._managed_local import ManagedLocalError
from ._remote_stage_execution import ResidentProfileDescriptor
from .errors import QueueServiceError
from .local_daemon import LocalDaemonAdmissionState
from ._phase_timing import phase

if TYPE_CHECKING:
    from loom.pipeline.orchestration import ManagedExecutionRequirement, SQLiteStageWorkStore, StageWorkRecord
    from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot
    from ._context_preparation import PreparedAdmissionContext
    from ._coordinator_run_authority import _ScopedCoordinatorAuthority
    from .local_daemon import LocalDaemonAdmission
    from .local_daemon_execution import LocalDaemonExecution, ManagedLocalIntent


_STAGES_PER_TURN = 32


@dataclass(frozen=True, slots=True)
class LocalDaemonExecutionOutcome:
    state: LocalDaemonAdmissionState
    reason: str | None = None


def _dispatch_offering(self, record, phase):
    from contextlib import nullcontext

    if self.daemon is None:
        return nullcontext()
    return self.daemon._result_verifications.bulk.offering(
        ("dispatch", record.run_uri, record.stage_work_id, phase),
    )


def reconcile_admission(
    self: LocalDaemonExecution, admission: LocalDaemonAdmission,
    *, prepared_intent: ManagedLocalIntent | None = None, prepared_context: PreparedAdmissionContext | None = None,
) -> LocalDaemonExecutionOutcome:
    """Reconcile one run into durable ready work without selecting capacity."""

    if self.daemon is not None:
        self._cycle_context_revisions[admission.admission_id] = admission.revision
        self._cycle_context_epochs.setdefault(admission.admission_id, (self.daemon._epoch, self.daemon._scheduling_epoch))
    intent, scoped_authority = (self._admission_context(admission, prepared_intent=prepared_intent)
                               if prepared_context is None else prepared_context)
    self._cycle_contexts[admission.admission_id] = (intent, scoped_authority)

    def steps() -> RunSteps:
        outcome = yield from _reconcile_admission_steps(self, admission, intent, scoped_authority)
        if outcome.state not in {
            LocalDaemonAdmissionState.SUCCEEDED,
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
        }:
            return outcome
        self._ready_preparations.retain_run(admission.run_uri, set())
        self._scheduling_waits.retain(admission.run_uri, set())
        self._orchestration_after.pop(admission.admission_id, None)
        if self._action_resolution is not None:
            yield from self._action_resolution.producer_steps(admission.run_uri, scoped_authority)
        slurm_in_flight, slurm_diagnostic = yield from self._reconcile_slurm_steps(admission.run_uri, scoped_authority)
        return _settled_terminal_outcome(
            self,
            admission.run_uri,
            outcome,
            slurm_in_flight=slurm_in_flight,
            slurm_diagnostic=slurm_diagnostic,
        )

    if self.daemon is not None and prepared_context is not None:
        if admission.state is LocalDaemonAdmissionState.PENDING_AUTHORITY and admission.cancellation_operation_id is None:
            # Binding succeeded. Activation changes the admission revision, so
            # a read started with the pre-activation revision could never apply.
            self.admission_activated(admission.admission_id)
            self.daemon._wake.set()
            raise RunObservationPending()
        return self.run_observations.advance(
            admission, (self.daemon._epoch, self.daemon._scheduling_epoch),
            prepared_context, steps, self.daemon._result_verifications.bulk,
        )
    elif self.daemon is None:
        return _drive_run_steps(steps(), scoped_authority, admission.run_uri)
    else:
        with self.daemon._result_verifications.bulk.offering(("run", admission.run_uri)):
            return _drive_run_steps(steps(), scoped_authority, admission.run_uri)


def _drive_run_steps[T](
    steps: ObservationSteps[T], authority: _ScopedCoordinatorAuthority, run_uri: str,
) -> T:
    try:
        request = next(steps)
        while True:
            try:
                result = authority.open_run(run_uri) if request is None else request()
            except Exception as error:
                request = steps.throw(error)
            else:
                request = steps.send(result)
    except StopIteration as settled:
        return settled.value
    finally:
        steps.close()


def _reconcile_admission_steps(
    self: LocalDaemonExecution,
    admission: LocalDaemonAdmission,
    intent: ManagedLocalIntent,
    scoped_authority: _ScopedCoordinatorAuthority,
) -> RunSteps:
    from loom.pipeline.orchestration import SchedulingProjectionState

    action_resolver = self._action_resolution
    cancelling = admission.cancellation_operation_id is not None or self.cancellation_operation(admission.admission_id) is not None
    if cancelling:
        outcome = yield from self._cancel_steps(admission, scoped_authority, intent.plan.stage_order)
        if action_resolver is None or not any(action_resolver.store.producer_needed(admission.run_uri, node) for node in intent.plan.stage_order):
            self._ready_preparations.retain_run(admission.run_uri, set())
            return outcome
    else:
        if action_resolver is not None:
            yield from action_resolver.producer_steps(admission.run_uri, scoped_authority)
        if admission.state is LocalDaemonAdmissionState.PENDING_AUTHORITY:
            self.admission_activated(admission.admission_id)

    placements = dict(intent.placements)
    orchestrator = RunOrchestrator(
        authority=scoped_authority,
        store=self.stage_work_store,
        owner_id=self.coordinator_id,
    )
    order = intent.plan.stage_order
    # One captured admission context covers one finite READY page. Each
    # 32-stage slice yields to other admissions for a fresh authority snapshot.
    for _ in range(READY_WINDOW_LIMIT // _STAGES_PER_TURN):
        _decision_as_of, snapshot_time = self._daemon_owner()._accepted_snapshot()
        slurm_in_flight, slurm_diagnostic = yield from self._reconcile_slurm_steps(admission.run_uri, scoped_authority)
        snapshot = yield
        eligible = {
            stage.stage_name for stage in snapshot.stages
            if stage.status is StageStatus.PENDING
            and (not cancelling or (action_resolver is not None
                 and action_resolver.store.producer_needed(admission.run_uri, stage.stage_name)))
        }
        if not cancelling and not self._failure_policy_allows_new_work(intent, snapshot):
            eligible.clear()
        self._ready_preparations.retain_run(admission.run_uri, eligible)
        self._scheduling_waits.retain(admission.run_uri, eligible)
        terminal = None if cancelling else (yield from self._terminal_steps(
            admission,
            intent.plan,
            snapshot,
            scoped_authority,
            continue_independent=intent.continue_independent,
        ))
        if terminal is not None and not cancelling:
            return terminal
        steps = orchestrator._ready_steps(
            admission_id=admission.admission_id,
            plan=intent.plan,
            authority_snapshot=snapshot,
            placements=placements,
            execution_requirements=intent.execution_requirements,
            resolve_ready=cancelling or action_resolver is not None,
            ready_at=snapshot_time,
            run_priority=admission.run_priority,
            enqueue_sequence=admission.enqueue_sequence,
            max_work_items=_STAGES_PER_TURN,
            after_stage=self._orchestration_after.get(admission.admission_id),
        )
        action_revision = None
        superseded = False
        try:
            while True:
                with phase("coordinator.orchestrate_ready"):
                    try:
                        stage_plan, readiness, expected = steps.send(action_revision)
                    except StopIteration as done:
                        for record in done.value:
                            if record.scheduling_state is SchedulingProjectionState.READY:
                                self._scheduling_waits.ready(record)
                        break
                action_revision = None
                if readiness.action is PlanAction.RUN:
                    if cancelling:
                        if action_resolver is None or not action_resolver.store.producer_needed(admission.run_uri, stage_plan.stage_name):
                            action_revision = expected
                    elif action_resolver is not None:
                        action_revision = yield from action_resolver.resolve_steps(
                            admission, intent, scoped_authority, stage_plan, readiness, expected, snapshot,
                        )
                    continue
                if cancelling:
                    continue
                # The planner's original stage facts remain valid only through
                # its own prior commits. Recompute on any intervening revision.
                current = yield
                if current.revision != expected:
                    superseded = True
                    break
                action_revision = self._apply_controller_action(
                    scoped_authority, admission.run_uri, stage_plan, readiness,
                    admission=admission, snapshot=current,
                )
        finally:
            steps.close()
        if superseded:
            continue
        previous = self._orchestration_after.get(admission.admission_id)
        if orchestrator.next_stage is None:
            self._orchestration_after.pop(admission.admission_id, None)
        else:
            self._orchestration_after[admission.admission_id] = orchestrator.next_stage
            self._daemon_owner()._wake.set()
        if (cancelling or orchestrator.next_stage is None or orchestrator.next_stage == order[-1]
            or (previous is not None and order.index(orchestrator.next_stage) <= order.index(previous))):
            break
    slurm_in_flight, slurm_diagnostic = yield from self._reconcile_slurm_steps(admission.run_uri, scoped_authority)
    snapshot = yield
    terminal = None if cancelling else (yield from self._terminal_steps(
        admission,
        intent.plan,
        snapshot,
        scoped_authority,
        continue_independent=intent.continue_independent,
    ))
    if terminal is not None:
        return terminal
    if not cancelling and self.daemon is not None and (
        self.config.remote_profiles or self.config.container_capabilities
    ):
        self._observed_ready[admission.admission_id] = snapshot
    if cancelling:
        return (yield from self._cancel_steps(admission, scoped_authority, intent.plan.stage_order))
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
    resolver = self._action_resolution
    if resolver is not None and any(
        claim["state"] in {"owned", "settling"}
        for claim in resolver.store.producers(run_uri)
    ):
        # Keep the admission eligible for reconciliation while an audit is
        # running or waiting for a bounded worker slot. Its final observation
        # also releases the producer's authority continuation.
        return LocalDaemonExecutionOutcome(
            LocalDaemonAdmissionState.ACTIVE,
            "action result settlement remains in flight",
        )
    return terminal


def _advance_ready_inputs(self, record, admission, context, epochs, *, anticipated):
    """Start host-independent IO only for a currently owned, bound READY attempt."""
    if record.placement.route.kind is not ExecutionRouteKind.MANAGED_AGENT:
        # A Slurm submit agent preflights its offer and GPU budget before any
        # preparation-report IO. Its route resumes through the same selector.
        return
    profiles = (*self.config.remote_profiles, *self.config.container_capabilities)
    remote = any(_profile_satisfies_requirement(profile, record.execution_requirement) for profile in profiles)
    if anticipated and not remote:
        return
    key = (record.run_uri, record.stage_name)
    if anticipated and not self._ready_preparations.can_anticipate(key):
        return
    intent, _ = context
    if not anticipated:
        owned, prepared = self._ready_preparations.request_for_descriptors(key, record.stage_work_id)
        if owned:
            if prepared is not None and remote:
                self._prepared_input_descriptors(record, prepared)
            return
    snapshot = (self._observed_ready.get(admission.admission_id)
                or self.dispatch_observations.snapshot_for_preparation(admission, epochs))
    if (snapshot is None or snapshot.revision.sequence < record.authority_revision.sequence
        or not self._failure_policy_allows_new_work(intent, snapshot)
        or not any(stage.stage_name == record.stage_name and stage.status is StageStatus.PENDING
                   and any(a.attempt_id == record.attempt_id for a in stage.attempts)
                   for stage in snapshot.stages)):
        return
    if anticipated:
        self._prepared_ready_request(record, snapshot, intent, speculative=True)
    else:
        self._prepared_ready_request(record, snapshot, intent)


def resume_ready_inputs(self, work_ids, admissions, epochs):
    """Revisit exact prerequisites ahead of discovery. The global policy still places work."""
    from loom.pipeline.orchestration import SchedulingProjectionState
    for work_id in work_ids:
        record = self.stage_work_store.find_stage_work(work_id)
        if record is None or record.scheduling_state is not SchedulingProjectionState.READY:
            continue
        admissions.include({record.admission_id})
        admission = admissions.get(record.admission_id)
        context = self._cycle_contexts.get(record.admission_id)
        if (admission is None or context is None or self._cycle_context_epochs.get(record.admission_id) != epochs
            or self._cycle_context_revisions.get(record.admission_id) != admission.revision
            or self._attempt_cancel_requested(record.run_uri, record.attempt_id)):
            continue
        try:
            _advance_ready_inputs(self, record, admission, context, epochs, anticipated=False)
        except Exception:
            # The selected route owns the durable decision about a failed preparation.
            continue


def _schedule_window(
    self: LocalDaemonExecution, admissions: Mapping[str, LocalDaemonAdmission],
    page: tuple[StageWorkRecord, ...], *,
    waiting_outcomes: dict[str, LocalDaemonExecutionOutcome] | None = None,
) -> tuple[str, LocalDaemonExecutionOutcome] | None:
    disabled_routes = set() if self.daemon is None else {
        identity for identity, profile in self._scheduling.retained_slurm_profiles.items() if not profile.available
    }
    dispatchable = {
        record.admission_id for record in page
        if record.placement.route.kind is not ExecutionRouteKind.SLURM
        or (record.placement.route.profile_id, record.placement.route.profile_configuration_fingerprint) not in disabled_routes
    }
    if not dispatchable and not any(record.admission_id in (waiting_outcomes or {}) for record in page):
        # Disabled routes cannot retain dispatch tickets. The only remaining
        # work here is publishing a newly reconciled admission's waiting reason.
        if isinstance(admissions, SchedulingAdmissions):
            admissions.visited_dispatch.update(("dispatch", record.run_uri, record.stage_work_id) for record in page)
        return None

    decision_as_of, snapshot_time = self._daemon_owner()._accepted_snapshot()
    # Read the page's cancellation preflight over one control connection. The
    # actual reservation rechecks the current cancellation and offer.
    from ._action_results import action_attempt_cancelled

    with self.config.connect_database(self.config.control_database) as conn:
        window = tuple(record for record in page
                       if not action_attempt_cancelled(conn, record.run_uri, record.attempt_id))
    if not window:
        return None
    # A release before agent acceptance reopens the existing projection. A
    # retry can reach dispatch before the next admission reconciliation sweep.
    for record in window:
        self._scheduling_waits.ready(record)
    if isinstance(admissions, SchedulingAdmissions):
        admissions.include({record.admission_id for record in window})
        admissions.visited_dispatch.update(
            ("dispatch", record.run_uri, record.stage_work_id) for record in window
            if record.admission_id in self._cycle_contexts
        )
    daemon = self.daemon
    epochs = (None, None) if daemon is None else (daemon._epoch, daemon._scheduling_epoch)
    if daemon is not None:
        # READY projections outlive an admission sweep. Revalidate their retained
        # intent through the same bounded context loader before allocating work.
        ready_admissions = dict.fromkeys(record.admission_id for record in window)
        for identity in ready_admissions:
            if identity not in dispatchable:
                continue
            admission = admissions.get(identity)
            if admission is not None and self._cycle_context_revisions.get(identity) != admission.revision:
                self.discard_dispatch_context(identity)
            if admission is not None and self._cycle_context_epochs.get(identity) != epochs:
                if self.run_observations.awaiting_read(admission, epochs, daemon._result_verifications.bulk):
                    continue
                if not daemon._contexts.try_submit(admission, epochs, self.prepare_admission_context, for_dispatch=True):
                    break
        admissions = {key: value for key, value in admissions.items()
                      if self._cycle_context_epochs.get(key) == epochs}
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
            context[0].max_parallel_stages is not None
            and self.coordinator.run_active_assignment_count(admission.run_uri)
            >= context[0].max_parallel_stages
        ):
            exhausted_admissions.add(record.admission_id)
            self._scheduling_waits.record(record.run_uri, record.stage_name, "reservation")
            self._scheduling_waits.capacity(record, "run_parallel_limit")
        elif daemon is not None:
            try:
                _advance_ready_inputs(self, record, admission, context, epochs, anticipated=True)
            except Exception:
                # Route-specific eligibility will report/retry the exact preparation.
                pass
    remote_targets = self._remote_candidates()
    configured_hosts = {rule.agent_id for rule in self.config.agent_policy.agents}
    all_slots_full = (self.agent_id is None and bool(configured_hosts)
                      and configured_hosts.issubset(self._full_offer_hosts))
    local_candidate = (
        self._candidate_for_dispatch()
        if self.agent_id is not None and self.local_profile_ready and any(
            record.admission_id in contexts and record.admission_id in admissions
            and record.placement.route.kind is ExecutionRouteKind.MANAGED_AGENT for record in window
        )
        else None
    )
    observed_offers = {target.offer_id for _, target in remote_targets.values()}
    local_timing = self._local_offer_timing() if local_candidate is not None else None
    if local_timing is not None:
        observed_offers.add(local_timing[0])
    self._scheduling_waits.current_offers(observed_offers, epochs)
    observed: dict[str, AuthoritativeRunSnapshot | None] = {}

    def dispatch_snapshot(
        admission: LocalDaemonAdmission, authority: _ScopedCoordinatorAuthority, record: StageWorkRecord,
    ) -> AuthoritativeRunSnapshot | None:
        if self.daemon is None:
            return authority.open_run(admission.run_uri)
        identity = admission.admission_id
        if identity not in observed:
            try:
                observed[identity] = self.dispatch_observations.poll(
                    admission, epochs, lambda: authority.open_run(admission.run_uri),
                    notify=lambda: self._ready_continuations.post(record.stage_work_id),
                )
            except Exception as error:
                with self.daemon._state_guard():
                    retry = self.daemon._admission_retries.setdefault(admission.run_uri, _RecoveryRetry())
                retry.failed(error, operation_id=admission.authority_operation_id, admission_id=identity,
                             state=(admission.revision, epochs[1]))
                self.daemon._record_admission_health(identity, "unavailable")
                observed[identity] = None
        snapshot = observed[identity]
        if snapshot is None:
            self._scheduling_waits.capacity(record, "preparation")
            self._scheduling_waits.record(record.run_uri, record.stage_name, "preparation")
            exhausted_admissions.add(identity)
            return None
        if snapshot.revision.sequence < record.authority_revision.sequence:
            self._scheduling_waits.capacity(record, "preparation")
            return None
        if not any(attempt.attempt_id == record.attempt_id for stage in snapshot.stages
                   if stage.stage_name == record.stage_name for attempt in stage.attempts):
            self._scheduling_waits.capacity(record, "preparation")
            return None
        return snapshot

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
        # Admission fairness belongs to this shared route selector. The native
        # resident kernel still owns resource feasibility and stage selection.
        groups = tuple(dict.fromkeys(record.admission_id for record in managed_records))
        decision = None
        for admission_id in groups or (None,):
            group = tuple(record for record in managed_records if record.admission_id == admission_id)
            decision = self._scheduling.kernel(group).decide(
                work=tuple(record.to_work_item() for record in group),
                candidates=candidates,
                as_of=snapshot_time,
            )
            if decision.state is PolicyDecisionState.SELECT:
                break
        assert decision is not None  # The empty group still receives a decision.
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
            profile = self._slurm_profile(
                cast(str, record.placement.route.profile_id),
                cast(str, record.placement.route.profile_configuration_fingerprint),
            )
            if not profile.available:
                self._scheduling_waits.record(record.run_uri, record.stage_name, "host_eligibility")
                if waiting_outcomes is not None and admission.admission_id in waiting_outcomes:
                    waiting_outcomes[admission.admission_id] = LocalDaemonExecutionOutcome(
                        LocalDaemonAdmissionState.WAITING, "slurm_route_unavailable_or_unmappable",
                    )
                continue
            snapshot = dispatch_snapshot(admission, authority, record)
            if snapshot is None:
                continue
            if not self._failure_policy_allows_new_work(intent, snapshot):
                exhausted_admissions.add(record.admission_id)
                continue
            with _dispatch_offering(self, record, "execution"):
                outcome = self._dispatch_slurm_ready(
                    admission=admission,
                    intent=intent,
                    authority=authority,
                    snapshot=snapshot,
                    stage_work_id=record.stage_work_id,
                )
            if (
                outcome is not None
                and outcome.state is LocalDaemonAdmissionState.WAITING
                and waiting_outcomes is not None
                and admission.admission_id in waiting_outcomes
            ):
                # Preserve a concrete deferral without returning early and
                # starving other ready work. In-flight runs remain ACTIVE.
                waiting_outcomes[admission.admission_id] = outcome
            if (
                outcome is not None
                and outcome.state is LocalDaemonAdmissionState.ACTIVE
            ):
                self._scheduling_waits.clear(record.run_uri, record.stage_name)
                return admission.admission_id, outcome
        if selected_id is None:
            for pending in managed_records:
                target_host = pending.placement.target
                if target_host in self._full_offer_hosts or (target_host is None and all_slots_full):
                    reason = "assignment_slots_full"
                elif not candidates or (target_host is not None and not any(
                    c.attributes.get("target") == target_host for c in candidates
                )):
                    reason = "capacity_unknown"
                else:
                    reason = "no_eligible_offer"
                self._scheduling_waits.capacity(pending, reason)
                self._scheduling_waits.record(pending.run_uri, pending.stage_name, "host_eligibility")
            return None
        record = _stage_work(self.stage_work_store, selected_id)
        admission = admissions.get(record.admission_id)
        if admission is None:
            excluded_work.add(record.stage_work_id)
            continue
        intent, authority = contexts[record.admission_id]
        snapshot = dispatch_snapshot(admission, authority, record)
        if snapshot is None:
            excluded_work.add(record.stage_work_id)
            continue
        if not self._failure_policy_allows_new_work(intent, snapshot):
            self._scheduling_waits.capacity(record, "run_policy")
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
            self._scheduling_waits.capacity(record, "no_eligible_offer")
            if remote_target is not None:
                del remote_targets[candidate_id]
            else:
                excluded_work.add(record.stage_work_id)
            continue
        if remote_target is not None:
            eligible = self._remote_eligible(intent=intent, snapshot=snapshot, record=record)
            if eligible is None:
                self._scheduling_waits.capacity(record, "request_preparation")
                self._scheduling_waits.record(record.run_uri, record.stage_name, "request_preparation")
                excluded_work.add(record.stage_work_id)
                continue
            if not eligible:
                self._scheduling_waits.capacity(record, "no_eligible_offer")
                del remote_targets[candidate_id]
                continue
        timing = ((remote_target[1].offer_id, remote_target[1].expires_ns)
                  if remote_target is not None else local_timing)
        if timing is not None:
            available = self._ready_preparations.request_available_ns(
                (record.run_uri, record.stage_name), record.stage_work_id,
            )
            self._scheduling_waits.eligible(record, *timing, available)
        try:
            with _dispatch_offering(self, record, "execution"):
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
                self._scheduling_waits.capacity(record, "run_parallel_limit")
                exhausted_admissions.add(record.admission_id)
                continue
            self._scheduling_waits.capacity(record, "capacity_unknown")
            return None
        if not started:
            excluded_work.add(record.stage_work_id)
            continue
        self._scheduling_waits.clear(record.run_uri, record.stage_name)
        return admission.admission_id, LocalDaemonExecutionOutcome(
            LocalDaemonAdmissionState.ACTIVE,
            "assignment was durably accepted",
        )


def _profile_satisfies_requirement(
    profile: ResidentProfileDescriptor | SubmittedContainerCapability,
    requirement: ManagedExecutionRequirement,
) -> bool:
    """Compare inert identities before any reservation or delivery."""

    if isinstance(requirement, SubmittedContainerRequirement):
        return isinstance(profile, SubmittedContainerCapability) and profile.satisfies(requirement)
    if isinstance(profile, SubmittedContainerCapability):
        return False
    return (
        profile.project_fingerprint == requirement.project_fingerprint
        and profile.environment_fingerprint == requirement.environment_fingerprint
        and profile.executor_fingerprint == requirement.executor_fingerprint
    )


def _stage_work(store: SQLiteStageWorkStore, stage_work_id: str) -> StageWorkRecord:
    record = store.find_stage_work(stage_work_id)
    if record is None:
        raise QueueServiceError("selected stage work disappeared before reservation")
    return record
