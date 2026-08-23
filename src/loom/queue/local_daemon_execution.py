"""Protected production composition for the managed-local daemon."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from threading import Lock
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.execution import prepare_stage_attempt
from loom.pipeline.execution.managed_local import (
    AtomResourceProvider,
    ClaimCommand,
    ManagedAssignment,
    ManagedOfferSnapshot,
    ObserveRequest,
    SQLiteAgentJournal,
    SQLiteCoordinatorAssignments,
    run_managed_local_assignment,
)
from loom.pipeline.orchestration import (
    RunOrchestrator,
    SQLiteStageWorkStore,
    StageWorkRecord,
)
from loom.pipeline.planning import (
    AttemptReadiness,
    ExecutionPlan,
    PlanAction,
    StagePlan,
)
from loom.pipeline.runtime import (
    CpuResourcePlanner,
    RunOptions,
    ResolvedStagePlacement,
    ResolvedStageRuntimeOptions,
    parallel_execution_options,
    resolve_run_runtime,
)
from loom.pipeline.specs import PipelineSpec, parse_pipeline_config
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    CancellationEpochRequest,
    CoordinatorAdmissionRequest,
    LocalRunStore,
)
from loom.pipeline.stores.read_models import (
    AuthoritativeRunSnapshot,
    LifecycleReason,
)
from loom.pipeline.stores.authority import (
    ExecutionFence,
    PreparedAttemptRequest,
    StatusTransition,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.scheduling import (
    Candidate,
    CapacityAtom,
    ExactQuantity,
    FifoSchedulingPolicy,
    PolicyDecisionState,
    ResourceAvailabilityEnvelope,
    ResourceInventoryEnvelope,
    SchedulingKernel,
)
from loom.serialization import PlainData, ensure_plain_data, json_loads
from loom.timestamps import utc_timestamp

from .errors import QueueConflictError, QueueServiceError
from .local_daemon import (
    LocalDaemonAdmission,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
)
from .local_daemon_runtime import load_managed_local_runtime_record


@dataclass(frozen=True, slots=True)
class ManagedLocalIntent:
    plan: ExecutionPlan
    runtime: Mapping[str, ResolvedStageRuntimeOptions]
    placements: Mapping[str, ResolvedStagePlacement]
    pipeline: PipelineSpec
    digest: str
    max_parallel_stages: int


@dataclass(frozen=True, slots=True)
class LocalDaemonExecutionOutcome:
    state: LocalDaemonAdmissionState
    reason: str | None = None


class _ScopedCoordinatorAuthority:
    """Least-privilege run/coordinator view used by orchestration and the agent.

    The SQLite authority remains an implementation detail of the daemon.  This
    adapter deliberately exposes only the exact Phase 1/2 calls needed after
    the coordinator binding has been accepted.
    """

    def __init__(
        self, store: SQLitePerRunAuthorityStore, *, run_uri: str, coordinator_id: str
    ) -> None:
        self._store = store
        self._run_uri = run_uri
        self._coordinator_id = coordinator_id

    def _run(self, run_uri: str) -> None:
        if run_uri != self._run_uri:
            raise QueueConflictError("scoped authority run conflicts")

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        self._run(run_uri)
        return self._store.open_run(run_uri)

    def transition_run(self, run_uri: str, **kwargs: object) -> StatusTransition:
        self._run(run_uri)
        return self._store.transition_run(run_uri, **kwargs)  # type: ignore[arg-type]

    def transition_stage(
        self, run_uri: str, stage_name: str, **kwargs: object
    ) -> StatusTransition:
        self._run(run_uri)
        return self._store.transition_stage(run_uri, stage_name, **kwargs)  # type: ignore[arg-type]

    def ensure_prepared_attempt(self, run_uri: str, request: PreparedAttemptRequest):
        self._run(run_uri)
        return self._store.ensure_prepared_attempt(run_uri, request)

    def bind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        self._run(run_uri)
        self._store.bind_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )

    def unbind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        self._run(run_uri)
        self._store.unbind_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )

    def grant_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ):
        self._run(run_uri)
        return self._store.grant_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )

    def confirm_execution_started(self, run_uri: str, *, fence: ExecutionFence) -> None:
        self._run(run_uri)
        self._store.confirm_execution_started(run_uri, fence=fence)

    def install_cancellation_epoch(
        self, run_uri: str, request: CancellationEpochRequest
    ):
        self._run(run_uri)
        if request.coordinator_id != self._coordinator_id:
            raise QueueConflictError("scoped authority coordinator conflicts")
        return self._store.install_cancellation_epoch(run_uri, request)

    def record_managed_attempt_terminal(
        self,
        run_uri: str,
        *,
        fence: ExecutionFence,
        status: StageStatus,
        reason: LifecycleReason,
    ) -> StatusTransition:
        self._run(run_uri)
        return self._store.record_managed_attempt_terminal(
            run_uri, fence=fence, status=status, reason=reason
        )

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        supersedes_commit_id: str | None = None,
        reason: LifecycleReason | None = None,
        assignment_id: str | None = None,
    ):
        self._run(run_uri)
        return self._store.record_output_commit(
            run_uri,
            stage_name,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            outputs=outputs,
            supersedes_commit_id=supersedes_commit_id,
            reason=reason,
            assignment_id=assignment_id,
        )


def load_managed_local_intent(
    config: LocalDaemonConfig, run_uri: str
) -> ManagedLocalIntent:
    """Load and validate the one canonical local admission intent."""

    store = LocalRunStore(config.run_store_root)
    run_path = store.local_run_dir(run_uri).resolve()
    configured_root = config.run_store_root.resolve()
    try:
        run_path.relative_to(configured_root)
    except ValueError as exc:
        raise QueueServiceError(
            "run_uri is outside the configured local run store"
        ) from exc
    store.open_run(run_uri)
    record = load_managed_local_runtime_record(store, run_uri)
    plan_payload = store.read_plan(run_uri)
    if plan_payload is None:
        raise QueueServiceError("managed-local admission requires a persisted plan")
    plan = ExecutionPlan.from_dict(plan_payload)
    exact_plan = ExecutionPlan.from_dict(record["plan"])
    if plan != exact_plan or plan.run_uri != run_uri:
        raise QueueServiceError(
            "persisted execution plan conflicts with exact runtime record"
        )
    snapshot = store.read_config_snapshot(run_uri, "resolved")
    if snapshot is None:
        raise QueueServiceError(
            "managed-local admission requires a resolved config snapshot"
        )
    decoded = json_loads(snapshot, path="config/resolved.json")
    if (
        hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        != record["pipeline_digest"]
    ):
        raise QueueServiceError(
            "resolved pipeline snapshot conflicts with exact runtime record"
        )
    if not isinstance(decoded, Mapping) or "pipeline" not in decoded:
        raise QueueServiceError(
            "resolved config snapshot must contain a pipeline definition"
        )
    pipeline = parse_pipeline_config(decoded["pipeline"])
    if set(plan.stage_order) != set(pipeline.stage_names):
        raise QueueServiceError(
            "persisted plan and resolved pipeline stage identities differ"
        )
    unsupported_actions = {
        stage.action
        for stage in plan.stage_plans
        if stage.action not in {PlanAction.RUN, PlanAction.REUSE, PlanAction.SKIP}
    }
    if unsupported_actions:
        raise QueueServiceError(
            "managed-local admission does not support plan actions: "
            + ", ".join(sorted(action.value for action in unsupported_actions))
        )
    runtime_options = RunOptions.from_dict(record["runtime_options"])
    runtime = resolve_run_runtime(runtime_options, stage_ids=pipeline.stage_names)
    placements_payload = record["placements"]
    if not isinstance(placements_payload, Mapping) or set(placements_payload) != set(
        pipeline.stage_names
    ):
        raise QueueServiceError(
            "exact runtime record placements conflict with pipeline"
        )
    placements = {
        name: ResolvedStagePlacement.from_dict(payload)
        for name, payload in placements_payload.items()
    }
    for name, placement in placements.items():
        if placement.target != config.machine_id:
            raise QueueServiceError("exact runtime record targets another local daemon")
    if (
        parallel_execution_options(runtime_options).max_parallel_stages
        != record["max_parallel_stages"]
    ):
        raise QueueServiceError("exact runtime record concurrency conflicts")
    return ManagedLocalIntent(
        plan,
        runtime,
        placements,
        pipeline,
        str(record["digest"]),
        cast(int, record["max_parallel_stages"]),
    )


class LocalDaemonExecution:
    """Build and drive the existing Phase 1 and Phase 2 owners."""

    def __init__(
        self,
        *,
        config: LocalDaemonConfig,
        coordinator_id: str,
        coordinator_epoch: str,
        cancellation_operation: Callable[[str], str | None],
        admission_activated: Callable[[str], None],
    ) -> None:
        self.config = config
        self.coordinator_id = coordinator_id
        self.coordinator_epoch = coordinator_epoch
        self.cancellation_operation = cancellation_operation
        self.admission_activated = admission_activated
        self.run_store = LocalRunStore(config.run_store_root)
        self.stage_work_store = SQLiteStageWorkStore(config.execution_database)
        self.cpu_planner = CpuResourcePlanner()
        self.planners = {"cpu": self.cpu_planner}
        self.capacity = (
            CapacityAtom(
                "cpu",
                f"{config.machine_id}:cpu",
                ExactQuantity(config.cpu_capacity),
                "count",
                ExactQuantity(1),
            ),
        )
        self.coordinator = SQLiteCoordinatorAssignments(
            config.execution_database, self.capacity
        )
        self.journal = SQLiteAgentJournal(config.agent_journal)
        self.provider = AtomResourceProvider(
            self.cpu_planner.descriptor,
            self.cpu_planner.claim_contracts,
            self.capacity,
        )
        # A new in-memory provider must never begin by advertising capacity that
        # a durable accepted/granted/running/unknown assignment might retain.
        # The agent journal is the only owner that has an exact provider claim;
        # coordinator state without that claim is unsafe to reconstruct.
        retained = self.journal.retained_claim_commands()
        retained_assignment_ids = {
            command.assignment.assignment_id for command in retained
        }
        missing = (
            self._capacity_holding_coordinator_assignments() - retained_assignment_ids
        )
        if missing:
            raise QueueServiceError(
                "coordinator retained assignment lacks an exact agent claim"
            )
        for command in retained:
            self.provider.restore_capacity_holding(command)
        self._launch_lock = Lock()

    def advance(self, admission: LocalDaemonAdmission) -> LocalDaemonExecutionOutcome:
        intent = load_managed_local_intent(self.config, admission.run_uri)
        if intent.digest != admission.intent_digest:
            raise QueueConflictError(
                "persisted managed-local plan or runtime changed after admission"
            )
        authority = SQLitePerRunAuthorityStore(admission.run_uri)
        authority.open_run(admission.run_uri)
        receipt = authority.bind_coordinator_admission(
            admission.run_uri,
            CoordinatorAdmissionRequest(
                operation_id=admission.authority_operation_id,
                coordinator_id=self.coordinator_id,
                run_uri=admission.run_uri,
                intent_digest=admission.intent_digest,
            ),
        )
        if receipt.request.intent_digest != admission.intent_digest:
            raise QueueConflictError(
                "authority admission receipt does not match retained intent"
            )
        scoped_authority = _ScopedCoordinatorAuthority(
            authority,
            run_uri=admission.run_uri,
            coordinator_id=self.coordinator_id,
        )
        if (
            admission.cancellation_operation_id is not None
            or self.cancellation_operation(admission.admission_id) is not None
        ):
            return self._cancel(admission, scoped_authority)
        self.admission_activated(admission.admission_id)

        placements = dict(intent.placements)
        orchestrator = RunOrchestrator(
            authority=scoped_authority,
            store=self.stage_work_store,
            owner_id=self.coordinator_id,
        )
        max_cycles = max(2, len(intent.plan.stage_plans) * 2 + 2)
        for _ in range(max_cycles):
            self._launch_lock.acquire()
            launch_released = False

            def release_launch() -> None:
                nonlocal launch_released
                if not launch_released:
                    launch_released = True
                    self._launch_lock.release()

            try:
                if self.cancellation_operation(admission.admission_id) is not None:
                    return self._cancel(admission, scoped_authority)
                snapshot = scoped_authority.open_run(admission.run_uri)
                terminal = self._terminal_outcome(
                    intent.plan, snapshot, scoped_authority
                )
                if terminal is not None:
                    return terminal
                orchestrator.reconcile(
                    admission_id=admission.admission_id,
                    plan=intent.plan,
                    authority_snapshot=snapshot,
                    placements=placements,
                    ready_at=snapshot.revision.sequence,
                    controller_action=lambda stage_plan, readiness: (
                        self._apply_controller_action(
                            scoped_authority,
                            admission.run_uri,
                            stage_plan,
                            readiness,
                        )
                    ),
                )
                snapshot = scoped_authority.open_run(admission.run_uri)
                terminal = self._terminal_outcome(
                    intent.plan, snapshot, scoped_authority
                )
                if terminal is not None:
                    return terminal
                decision = orchestrator.decide(
                    kernel=SchedulingKernel(
                        planners=self.planners,
                        policy=FifoSchedulingPolicy(),
                        component_epoch=self.coordinator_epoch,
                    ),
                    candidates=(self._candidate(),),
                    as_of=snapshot.revision.sequence,
                    admission_id=admission.admission_id,
                )
                if decision.state is not PolicyDecisionState.SELECT:
                    return LocalDaemonExecutionOutcome(
                        LocalDaemonAdmissionState.WAITING,
                        "no dependency-ready stage currently has local capacity",
                    )
                assert decision.stage_work_id is not None
                assert decision.selected is not None
                record = _stage_work(self.stage_work_store, decision.stage_work_id)
                self._execute(
                    admission=admission,
                    intent=intent,
                    authority=scoped_authority,
                    snapshot=snapshot,
                    record=record,
                    decision=decision,
                    execution_started=release_launch,
                )
            finally:
                release_launch()
        return LocalDaemonExecutionOutcome(
            LocalDaemonAdmissionState.WAITING,
            "bounded reconciliation window exhausted",
        )

    def _apply_controller_action(
        self,
        authority: _ScopedCoordinatorAuthority,
        run_uri: str,
        stage_plan: StagePlan,
        readiness: AttemptReadiness,
    ) -> None:
        snapshot = authority.open_run(run_uri)
        current = next(
            (
                stage
                for stage in snapshot.stages
                if stage.stage_name == stage_plan.stage_name
            ),
            None,
        )
        if readiness.action is PlanAction.REUSE:
            if current is None or current.status not in {
                StageStatus.SUCCEEDED,
                StageStatus.SKIPPED,
            }:
                raise QueueConflictError(
                    "reused stage is not terminal in authority truth"
                )
            return
        if readiness.action is not PlanAction.SKIP:
            raise QueueConflictError(
                f"unsupported managed-local controller action: {readiness.action.value}"
            )
        if current is not None and current.status is StageStatus.SKIPPED:
            return
        if current is not None and current.status is not StageStatus.PENDING:
            raise QueueConflictError(
                "skipped stage conflicts with authority lifecycle truth"
            )
        authority.transition_stage(
            run_uri,
            stage_plan.stage_name,
            from_status=None if current is None else current.status,
            to_status=StageStatus.SKIPPED,
            expected_revision=snapshot.revision,
            reason=LifecycleReason(
                code="plan.not_selected",
                detail={
                    "readiness_generation": readiness.readiness_generation,
                },
            ),
        )

    def _terminal_outcome(
        self,
        plan: ExecutionPlan,
        snapshot: AuthoritativeRunSnapshot,
        authority: _ScopedCoordinatorAuthority,
    ) -> LocalDaemonExecutionOutcome | None:
        if snapshot.status is RunStatus.SUCCEEDED:
            return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.SUCCEEDED)
        if snapshot.status in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.FAILED,
                f"authority run is {snapshot.status.value}",
            )
        if snapshot.status is RunStatus.CANCELLED:
            return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.CANCELLED)
        facts = {stage.stage_name: stage.status for stage in snapshot.stages}
        run_stages = {
            stage.stage_name
            for stage in plan.stage_plans
            if stage.action is PlanAction.RUN
        }
        if any(facts.get(name) is StageStatus.FAILED for name in run_stages):
            authority.transition_run(
                plan.run_uri,
                from_status=snapshot.status,
                to_status=RunStatus.FAILED,
                expected_revision=snapshot.revision,
            )
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.FAILED,
                "authority reports a failed stage",
            )
        if any(facts.get(name) is StageStatus.CANCELLED for name in run_stages):
            return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.CANCELLED)
        expected = {
            stage.stage_name: (
                {StageStatus.SKIPPED}
                if stage.action is PlanAction.SKIP
                else {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
                if stage.action is PlanAction.REUSE
                else {StageStatus.SUCCEEDED}
            )
            for stage in plan.stage_plans
        }
        if expected and all(
            facts.get(name) in statuses for name, statuses in expected.items()
        ):
            authority.transition_run(
                plan.run_uri,
                from_status=snapshot.status,
                to_status=RunStatus.SUCCEEDED,
                expected_revision=snapshot.revision,
            )
            return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.SUCCEEDED)
        return None

    def _cancel(
        self,
        admission: LocalDaemonAdmission,
        authority: _ScopedCoordinatorAuthority,
    ) -> LocalDaemonExecutionOutcome:
        operation_id = (
            admission.cancellation_operation_id
            or self.cancellation_operation(admission.admission_id)
        )
        if operation_id is None:
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.CANCELLATION_REQUESTED
            )
        authority.install_cancellation_epoch(
            admission.run_uri,
            CancellationEpochRequest(
                operation_id=operation_id,
                coordinator_id=self.coordinator_id,
                run_uri=admission.run_uri,
            ),
        )
        snapshot = authority.open_run(admission.run_uri)
        if snapshot.status is RunStatus.CANCELLED:
            return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.CANCELLED)
        terminal = {
            RunStatus.SUCCEEDED: LocalDaemonAdmissionState.SUCCEEDED,
            RunStatus.FAILED: LocalDaemonAdmissionState.FAILED,
            RunStatus.INTERRUPTED: LocalDaemonAdmissionState.FAILED,
        }
        if snapshot.status in terminal:
            return LocalDaemonExecutionOutcome(
                terminal[snapshot.status],
                "authority_terminal_before_cancellation",
            )
        try:
            authority.transition_run(
                admission.run_uri,
                from_status=snapshot.status,
                to_status=RunStatus.CANCELLED,
                expected_revision=snapshot.revision,
            )
        except Exception:
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.CANCELLING,
                "cancellation epoch is installed; active or unknown work remains",
            )
        return LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.CANCELLED)

    def _candidate(self) -> Candidate:
        observed = self.provider.observe(
            ObserveRequest(
                self.config.machine_id,
                self.coordinator_epoch,
                f"candidate-observe-{utc_timestamp()}",
            )
        )
        inventory = ResourceInventoryEnvelope(
            self.config.machine_id,
            "cpu",
            observed.availability_revision,
            atoms=self.capacity,
        )
        availability = ResourceAvailabilityEnvelope(
            self.config.machine_id,
            "cpu",
            observed.availability_revision,
            atoms=observed.atoms,
        )
        return Candidate(
            self.config.machine_id,
            {"cpu": inventory},
            {"cpu": availability},
        )

    def _execute(
        self,
        *,
        admission: LocalDaemonAdmission,
        intent: ManagedLocalIntent,
        authority: _ScopedCoordinatorAuthority,
        snapshot: AuthoritativeRunSnapshot,
        record: StageWorkRecord,
        decision: object,
        execution_started: Callable[[], None],
    ) -> None:
        selected = getattr(decision, "selected")
        claims = tuple(selected.claims)
        if len(claims) != 1 or claims[0].resource_kind != "cpu":
            raise QueueServiceError(
                "managed-local daemon requires one exact CPU claim per stage"
            )
        offer_id = f"offer-{record.stage_work_id}-{record.projection_revision}"
        assignment_id = (
            "assignment-"
            + hashlib.sha256(
                (
                    admission.admission_id
                    + "\0"
                    + record.stage_work_id
                    + "\0"
                    + offer_id
                ).encode("utf-8")
            ).hexdigest()
        )
        claim_id = f"claim-{assignment_id}"
        assignment = ManagedAssignment(
            assignment_id=assignment_id,
            run_uri=record.run_uri,
            stage_work_id=record.stage_work_id,
            stage_name=record.stage_name,
            attempt=record.attempt,
            attempt_id=record.attempt_id,
            agent_id=self.config.machine_id,
            session_id=self.coordinator_epoch,
            offer_id=offer_id,
            claim_id=claim_id,
        )
        observed = self.provider.observe(
            ObserveRequest(
                self.config.machine_id,
                self.coordinator_epoch,
                f"offer-observe-{assignment_id}",
            )
        )
        self.coordinator.publish_offer(
            ManagedOfferSnapshot(
                agent_id=self.config.machine_id,
                session_id=self.coordinator_epoch,
                offer_revision=offer_id,
                snapshot_revision=self.coordinator_epoch,
                inventory_revision=f"inventory-{self.coordinator_epoch}",
                availability_revision=observed.availability_revision,
                component_descriptors=(self.cpu_planner.descriptor,),
                atoms=observed.atoms,
                reflected_claim_ids=self.provider.live_claim_ids_for_session(
                    self.coordinator_epoch
                ),
            )
        )
        commands = tuple(
            ClaimCommand(
                assignment,
                f"{assignment_id}:prepare:{index}",
                claim,
            )
            for index, claim in enumerate(claims)
        )
        stage = intent.pipeline.get_stage(record.stage_name)
        stage_plan = next(
            item
            for item in intent.plan.ordered_stage_plans
            if item.stage_name == record.stage_name
        )
        produced = _produced_outputs(snapshot)
        runtime = intent.runtime[record.stage_name]
        worker_request = prepare_stage_attempt(
            run_store=self.run_store,
            run_uri=record.run_uri,
            stage=stage,
            stage_plan=stage_plan,
            produced_outputs=produced,
            fingerprint_context=intent.plan.fingerprint_context,
            resolved_runtime=runtime,
        )
        if worker_request.attempt != record.attempt:
            raise QueueConflictError(
                "local worker preparation attempt differs from authority attempt"
            )
        decision_receipt: dict[str, PlainData] = {
            "policy_epoch": getattr(decision, "component_epoch"),
            "policy_descriptor": getattr(decision, "policy_descriptor").to_dict(),
            "stage_work_id": record.stage_work_id,
            "candidate_id": self.config.machine_id,
            "stage_work_revision": record.projection_revision,
            "snapshot_revision": self.coordinator_epoch,
            "offer_revision": offer_id,
            "score_summary": {"preference_vector": list(selected.preference_vector)},
            "fallback_eligible": False,
            "as_of": utc_timestamp(),
            "reason_codes": ["selected"],
            "component_descriptors": [self.cpu_planner.descriptor.to_dict()],
            "claim_contract_descriptors": [
                descriptor.to_dict()
                for descriptor in sorted(
                    {claim.contract for claim in claims},
                    key=lambda item: item.key,
                )
            ],
        }
        run_managed_local_assignment(
            coordinator=self.coordinator,
            authority=authority,
            journal=self.journal,
            assignment=assignment,
            worker_request=worker_request,
            claims=claims,
            commands=commands,
            providers={"cpu": self.provider},
            run_store=self.run_store,
            max_parallel_stages=intent.max_parallel_stages,
            decision_receipt=decision_receipt,
            cancellation_requested=lambda: self._install_cancellation_if_requested(
                admission, authority
            ),
            execution_started=execution_started,
        )

    def _install_cancellation_if_requested(
        self,
        admission: LocalDaemonAdmission,
        authority: _ScopedCoordinatorAuthority,
    ) -> bool:
        operation_id = self.cancellation_operation(admission.admission_id)
        if operation_id is None:
            return False
        authority.install_cancellation_epoch(
            admission.run_uri,
            CancellationEpochRequest(
                operation_id=operation_id,
                coordinator_id=self.coordinator_id,
                run_uri=admission.run_uri,
            ),
        )
        return True

    def _capacity_holding_coordinator_assignments(self) -> set[str]:
        """Return only coordinator states that can retain a physical claim.

        A released coordinator record is proven available.  Earlier logical
        states which have not reached agent acceptance do not yet own a physical
        claim.  Every remaining capacity-holding record must be matched by the
        agent's durable, exact claim rather than a fabricated placeholder.
        """
        if not self.config.execution_database.is_file():
            return set()
        try:
            with sqlite3.connect(self.config.execution_database) as conn:
                rows = conn.execute(
                    "SELECT assignment_id FROM coordinator_assignments "
                    "WHERE state IN ("
                    "'accepted', 'granted', 'running', 'unknown', "
                    "'terminal', 'logical_released'"
                    ")"
                )
        except sqlite3.DatabaseError as exc:
            raise QueueServiceError(
                "coordinator retained assignment state is unavailable"
            ) from exc
        return {str(row[0]) for row in rows}


def _stage_work(store: SQLiteStageWorkStore, stage_work_id: str) -> StageWorkRecord:
    for record in store.list_stage_work():
        if record.stage_work_id == stage_work_id:
            return record
    raise QueueServiceError("selected stage work disappeared before reservation")


def _produced_outputs(
    snapshot: AuthoritativeRunSnapshot,
) -> dict[str, dict[str, ArtifactRef]]:
    return {
        stage.stage_name: {
            fact.artifact_name: fact.artifact for fact in stage.artifact_facts
        }
        for stage in snapshot.stages
        if stage.artifact_facts
    }


def build_local_daemon_owner_views(
    config: LocalDaemonConfig,
    admissions: tuple[LocalDaemonAdmission, ...],
    *,
    clock: Callable[[], str] = utc_timestamp,
) -> tuple[Mapping[str, PlainData], ...]:
    """Join labelled owner snapshots without claiming cross-owner atomicity."""

    stage_work_by_run: dict[str, list[dict[str, PlainData]]] = {}
    assignments_by_run: dict[str, list[dict[str, PlainData]]] = {}
    agent_work_by_run: dict[str, list[dict[str, PlainData]]] = {}
    execution_available = True
    agent_available = True
    if config.execution_database.is_file():
        try:
            with sqlite3.connect(config.execution_database) as conn:
                for (payload,) in conn.execute(
                    "SELECT record_json FROM stage_work ORDER BY stage_work_id"
                ):
                    record = StageWorkRecord.from_dict(json.loads(str(payload)))
                    stage_work_by_run.setdefault(record.run_uri, []).append(
                        {
                            "stage_work_id": record.stage_work_id,
                            "stage_name": record.stage_name,
                            "state": record.scheduling_state.value,
                            "projection_revision": record.projection_revision,
                        }
                    )
                for row in conn.execute(
                    "SELECT assignment_id, run_uri, state, session_id, offer_id, "
                    "claim_id, receipt_json FROM coordinator_assignments "
                    "ORDER BY assignment_id"
                ):
                    assignments_by_run.setdefault(str(row[1]), []).append(
                        {
                            "assignment_id": str(row[0]),
                            "state": str(row[2]),
                            "session_id": str(row[3]),
                            "offer_id": str(row[4]),
                            "claim_id": str(row[5]),
                            "receipt_digest": hashlib.sha256(
                                str(row[6]).encode("utf-8")
                            ).hexdigest(),
                        }
                    )
        except Exception:  # corrupt owner data is unavailable, never empty healthy work
            execution_available = False
    if config.agent_journal.is_file():
        try:
            with sqlite3.connect(config.agent_journal) as conn:
                for row in conn.execute(
                    "SELECT assignment_id, identity_json, state, "
                    "process_execution_id, availability_revision "
                    "FROM assignments ORDER BY assignment_id"
                ):
                    identity = json.loads(str(row[1]))
                    if not isinstance(identity, Mapping):
                        continue
                    run_uri = identity.get("run_uri")
                    if not isinstance(run_uri, str):
                        continue
                    agent_work_by_run.setdefault(run_uri, []).append(
                        {
                            "assignment_id": str(row[0]),
                            "state": str(row[2]),
                            "process_execution_id": (
                                None if row[3] is None else str(row[3])
                            ),
                            "availability_revision": (
                                None if row[4] is None else str(row[4])
                            ),
                        }
                    )
        except (json.JSONDecodeError, sqlite3.DatabaseError):
            agent_available = False

    views: list[Mapping[str, PlainData]] = []
    for admission in admissions:
        authority_view: dict[str, PlainData]
        observed_at = clock()
        cancellation_receipt: dict[str, PlainData] | None = None
        try:
            authority = SQLitePerRunAuthorityStore(admission.run_uri)
            snapshot = authority.open_run(admission.run_uri)
            if admission.cancellation_operation_id is not None:
                receipt = authority.read_cancellation_epoch_receipt(
                    admission.run_uri, admission.cancellation_operation_id
                )
                cancellation_receipt = None if receipt is None else receipt.to_dict()
        except Exception:
            authority_view = {
                "owner": "per-run-authority",
                "availability": "unavailable",
                "state": "unavailable",
                "diagnostic": "authority_unavailable",
                "observed_at": observed_at,
            }
        else:
            authority_view = {
                "owner": "per-run-authority",
                "availability": "available",
                "state": snapshot.status.value,
                "observed_at": observed_at,
                "revision": snapshot.revision.to_dict(),
                "stages": {
                    stage.stage_name: stage.status.value for stage in snapshot.stages
                },
            }
        view = ensure_plain_data(
            {
                "queue_item_id": admission.queue_item_id,
                "run_uri": admission.run_uri,
                "admission": {
                    "owner": "coordinator",
                    "availability": "available",
                    "state": admission.state.value,
                    "accepted_at": admission.accepted_at,
                    "intent_digest": admission.intent_digest,
                    "authority_operation_id": admission.authority_operation_id,
                    "observed_at": observed_at,
                },
                "authority": authority_view,
                "scheduling": {
                    "owner": "coordinator-stage-work",
                    "availability": "available"
                    if execution_available
                    else "unavailable",
                    "observed_at": observed_at,
                    "diagnostic": None
                    if execution_available
                    else "execution_store_unavailable",
                    "work": stage_work_by_run.get(admission.run_uri, []),
                },
                "assignment": {
                    "owner": "coordinator-assignments",
                    "availability": "available"
                    if execution_available
                    else "unavailable",
                    "observed_at": observed_at,
                    "diagnostic": None
                    if execution_available
                    else "execution_store_unavailable",
                    "assignments": assignments_by_run.get(admission.run_uri, []),
                },
                "execution": {
                    "owner": "local-agent",
                    "availability": "available" if agent_available else "unavailable",
                    "observed_at": observed_at,
                    "diagnostic": None
                    if agent_available
                    else "agent_journal_unavailable",
                    "journal": agent_work_by_run.get(admission.run_uri, []),
                },
                "cancellation": {
                    "owner": "per-run-authority",
                    "availability": authority_view["availability"],
                    "state": (
                        "unavailable"
                        if authority_view["availability"] == "unavailable"
                        else "installed"
                        if cancellation_receipt is not None
                        else "requested"
                        if admission.cancellation_operation_id is not None
                        else "not_requested"
                    ),
                    "requested": admission.cancellation_operation_id is not None,
                    "operation_id": admission.cancellation_operation_id,
                    "receipt": cancellation_receipt,
                    "observed_at": observed_at,
                },
                "service": {
                    "owner": "local-daemon",
                    "availability": (
                        "available"
                        if (
                            execution_available
                            and agent_available
                            and authority_view["availability"] == "available"
                        )
                        else "unavailable"
                    ),
                    "state": (
                        "healthy"
                        if (
                            execution_available
                            and agent_available
                            and authority_view["availability"] == "available"
                        )
                        else "degraded"
                    ),
                    "diagnostic": (
                        None
                        if (
                            execution_available
                            and agent_available
                            and authority_view["availability"] == "available"
                        )
                        else "owner_status_unavailable"
                    ),
                    "observed_at": observed_at,
                },
            },
            path="local_daemon_status.runs",
        )
        if not isinstance(view, dict):
            raise AssertionError("local daemon owner view must be a mapping")
        views.append(view)
    return tuple(views)


__all__ = [
    "LocalDaemonExecution",
    "LocalDaemonExecutionOutcome",
    "ManagedLocalIntent",
    "load_managed_local_intent",
    "build_local_daemon_owner_views",
]
