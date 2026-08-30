"""Protected production composition for the managed-local daemon."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import sqlite3
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event, Lock
from types import MappingProxyType
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.execution import StageWorkerRequest, prepare_stage_attempt
from loom.pipeline.execution.reliability import (
    record_resolved_reliability_policy_fact,
    record_retry_decision_for_stage_result,
    record_stage_reliability_transition,
)
from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    ExecutionFailure,
)
from loom.pipeline.reliability import (
    RetryDecisionRecord,
    StageAttemptTransaction,
    StageAttemptTransactionState,
    TimeoutOutcomeRecord,
)
from loom.pipeline.reliability import ReliabilityPolicy
from loom.pipeline.executors.slurm.ready_stage import (
    ReadyStageState,
    SQLiteReadyStageSubmissions,
    SlurmReadyStageProfile,
    SlurmReadyStageRequest,
    SlurmReadyStageSubmission,
    map_ready_stage,
    resolve_slurm_containment,
)
from loom.pipeline.executors.slurm.errors import (
    SlurmPlanningError,
    SlurmResourceMappingError,
)
from loom.pipeline.execution.lifecycle import bind_stage_inputs
from loom.queue._managed_local import (
    AgentResourceProvider,
    AssignmentState,
    ManagedAssignment,
    ManagedLocalError,
    ManagedOfferSnapshot,
    ObserveRequest,
    SQLiteAgentJournal,
    SQLiteCoordinatorAssignments,
    _compose_agent_resource_providers,
    run_managed_local_assignment,
)
from loom.pipeline.orchestration import (
    ExecutionRequirement,
    RunOrchestrator,
    SchedulingProjectionState,
    SQLiteStageWorkStore,
    StageWorkRecord,
)
from loom.pipeline.planning import (
    AttemptReadiness,
    ExecutionPlan,
    PlanAction,
    StagePlan,
    build_stage_fingerprint,
)
from loom.pipeline.runtime import (
    ExecutionRouteKind,
    RunOptions,
    ResolvedStagePlacement,
    ResolvedStageRuntimeOptions,
    parallel_execution_options,
    resolve_run_runtime,
)
from loom.pipeline.specs import PipelineSpec, parse_pipeline_config
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import (
    AuthorityStoreError,
    CancellationEpochRequest,
    CoordinatorAdmissionRequest,
    LocalRunStore,
    RunReliabilityStore,
)
from loom.pipeline.stores.read_models import (
    AuthoritativeRunSnapshot,
    LifecycleReason,
    ReliabilityPolicyFact,
    ReliabilityPolicyScope,
    ReliabilityStatusDetail,
)
from loom.pipeline.stores.authority import (
    ExecutionFence,
    PreparedAttemptRequest,
    StatusTransition,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.scheduling import (
    Candidate,
    CapacityAtom,
    ComponentRegistry,
    ExactQuantity,
    HardConstraintEvaluator,
    PolicyDecisionState,
    PreferenceScorer,
    ResourceAvailabilityEnvelope,
    ResourceInventoryEnvelope,
    ResourcePlanner,
    SchedulingComponentDescriptor,
    SchedulingError,
    SchedulingKernel,
    SchedulingPolicy,
)
from loom.serialization import (
    PlainData,
    ensure_plain_data,
    freeze_plain_data,
    json_loads,
)
from loom.timestamps import utc_timestamp

from .errors import QueueConflictError, QueueServiceError
from ._remote_stage_execution import (
    MAX_TRANSFER_BYTES,
    ResidentProfileDescriptor,
    _ResidentAssignmentBundle,
    _RemoteArtifact,
    _ResidentAssignmentWorkspace,
    _RemoteExecutionReport,
    _validate_remote_semantic_data,
)
from ._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    SupervisorLaunchState,
    SupervisorLaunchConfiguration,
)
from .agent_sessions import (
    AgentAssignmentControl,
    AgentOffer,
    _managed_containment_evidence,
    _target_remote_delivery,
)
from .local_daemon import (
    LocalDaemon,
    LocalDaemonAdmission,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
    LocalDaemonSchedulingComponents,
    ManagedRecoveryTarget,
    RecoverUnknownAssignment,
    SlurmRecoveryTarget,
    _default_scheduling_components,
)
from .local_daemon_runtime import load_managed_local_runtime_record
from .slurm_ready_stage import (
    SQLiteSlurmStageAssignments,
    SlurmStageAssignment,
    SlurmStageDelivery,
    SlurmStageRecord,
)


@dataclass(frozen=True, slots=True)
class ManagedLocalIntent:
    plan: ExecutionPlan
    runtime: Mapping[str, ResolvedStageRuntimeOptions]
    placements: Mapping[str, ResolvedStagePlacement]
    execution_requirements: Mapping[str, ExecutionRequirement]
    pipeline: PipelineSpec
    digest: str
    max_parallel_stages: int


@dataclass(frozen=True, slots=True)
class LocalDaemonExecutionOutcome:
    state: LocalDaemonAdmissionState
    reason: str | None = None


def _validate_agent_provider_composition(
    providers: Sequence[AgentResourceProvider],
    planners: Mapping[str, ResourcePlanner],
) -> dict[str, AgentResourceProvider]:
    """Reject provider/planner skew before an offer can expose capacity.

    Providers are checked one at a time.  In particular, a CPU provider is
    never compared with a GPU planner merely because both are configured.
    """

    for provider in providers:
        if (
            not hasattr(provider, "descriptor")
            or not hasattr(provider, "claim_contracts")
            or not callable(getattr(provider, "observe", None))
        ):
            raise QueueServiceError("agent resource provider is invalid")
        kind = provider.descriptor.kind
        planner = planners.get(kind)
        if planner is None:
            raise QueueServiceError(
                f"agent resource provider has no active planner for {kind!r}"
            )
        if not set(provider.claim_contracts) & set(planner.claim_contracts):
            raise QueueServiceError(
                f"agent resource provider has no claim-contract intersection for {kind!r}"
            )
        if any(contract.kind != kind for contract in provider.claim_contracts):
            raise QueueServiceError(
                f"agent resource provider has an invalid claim contract for {kind!r}"
            )
    try:
        return _compose_agent_resource_providers(providers)
    except ManagedLocalError as exc:
        raise QueueServiceError(str(exc)) from exc


def _production_preference_scorers() -> Mapping[str, PreferenceScorer]:
    """Compatibility-free view of the explicit built-in composition."""

    return {
        item.descriptor.kind: item
        for item in _default_scheduling_components().preference_scorers
    }


@dataclass(frozen=True, slots=True)
class _CoordinatorSchedulingEpoch:
    """One immutable active/retained coordinator scheduling composition."""

    epoch_id: str
    registry: ComponentRegistry
    planner_kinds: tuple[str, ...]
    hard_evaluator_kinds: tuple[str, ...]
    preference_scorer_kinds: tuple[str, ...]
    policy_kind: str
    active_slurm_profiles: Mapping[str, SlurmReadyStageProfile]
    retained_slurm_profiles: Mapping[tuple[str, str], SlurmReadyStageProfile]

    def available_slurm_profiles(
        self,
    ) -> dict[tuple[str, str], SlurmReadyStageProfile]:
        profiles = dict(self.retained_slurm_profiles)
        profiles.update(
            {
                (profile.profile_id, profile.configuration_fingerprint): profile
                for profile in self.active_slurm_profiles.values()
            }
        )
        return profiles

    def active_planners(self) -> dict[str, ResourcePlanner]:
        return {
            kind: cast(ResourcePlanner, self.registry.active(kind))
            for kind in self.planner_kinds
        }

    def planners_for_record(
        self, record: StageWorkRecord
    ) -> dict[str, ResourcePlanner]:
        planners = self.active_planners()
        planners.update(
            {
                kind: cast(ResourcePlanner, self.registry.retained(descriptor))
                for kind, descriptor in record.placement.planner_descriptors.items()
            }
        )
        return planners

    def kernel(self, records: Sequence[StageWorkRecord]) -> SchedulingKernel:
        active_planners = self.active_planners()
        active_hard = {
            kind: cast(HardConstraintEvaluator, self.registry.active(kind))
            for kind in self.hard_evaluator_kinds
        }
        active_preferences = {
            kind: cast(PreferenceScorer, self.registry.active(kind))
            for kind in self.preference_scorer_kinds
        }
        work_planners: dict[str, dict[str, ResourcePlanner]] = {}
        work_hard: dict[str, dict[str, HardConstraintEvaluator]] = {}
        work_preferences: dict[str, dict[str, PreferenceScorer]] = {}
        for record in records:
            planners = dict(active_planners)
            planners.update(
                {
                    kind: cast(ResourcePlanner, self.registry.retained(descriptor))
                    for kind, descriptor in record.placement.planner_descriptors.items()
                }
            )
            hard_descriptors: dict[str, SchedulingComponentDescriptor] = {}
            for spec in record.placement.hard_constraints:
                if spec.descriptor is None:
                    raise QueueConflictError(
                        "referenced hard evaluator descriptor is unavailable"
                    )
                _add_exact_descriptor(hard_descriptors, spec.evaluator, spec.descriptor)
            hard = dict(active_hard)
            hard.update(
                {
                    kind: cast(
                        HardConstraintEvaluator, self.registry.retained(descriptor)
                    )
                    for kind, descriptor in hard_descriptors.items()
                }
            )
            preference_descriptors: dict[str, SchedulingComponentDescriptor] = {}
            for spec in record.placement.preferences:
                if spec.descriptor is None:
                    raise QueueConflictError(
                        "referenced preference scorer descriptor is unavailable"
                    )
                _add_exact_descriptor(
                    preference_descriptors, spec.scorer, spec.descriptor
                )
            preferences = dict(active_preferences)
            preferences.update(
                {
                    kind: cast(PreferenceScorer, self.registry.retained(descriptor))
                    for kind, descriptor in preference_descriptors.items()
                }
            )
            work_planners[record.stage_work_id] = planners
            work_hard[record.stage_work_id] = hard
            work_preferences[record.stage_work_id] = preferences
        policy = cast(SchedulingPolicy, self.registry.active(self.policy_kind))
        return SchedulingKernel(
            planners=active_planners,
            hard_evaluators=active_hard,
            preference_scorers=active_preferences,
            work_planners=work_planners,
            work_hard_evaluators=work_hard,
            work_preference_scorers=work_preferences,
            policy=policy,
            component_epoch=self.epoch_id,
        )


def _add_exact_descriptor(
    values: dict[str, SchedulingComponentDescriptor],
    kind: str,
    descriptor: SchedulingComponentDescriptor,
) -> None:
    current = values.setdefault(kind, descriptor)
    if current != descriptor:
        raise QueueConflictError(
            "one work item cannot mix component versions for one kind"
        )


def _build_scheduling_epoch(
    *,
    epoch_id: str,
    composition: LocalDaemonSchedulingComponents,
    active_slurm_profiles: Mapping[str, SlurmReadyStageProfile],
    retained_slurm_profiles: Mapping[tuple[str, str], SlurmReadyStageProfile]
    | None = None,
    current: _CoordinatorSchedulingEpoch | None = None,
    referenced_descriptors: Sequence[SchedulingComponentDescriptor] = (),
) -> _CoordinatorSchedulingEpoch:
    registry = ComponentRegistry(epoch_id=epoch_id)
    active_components = (
        *composition.planners,
        *composition.hard_evaluators,
        *composition.preference_scorers,
        composition.policy,
    )
    for component in active_components:
        registry.register(component)
    if referenced_descriptors and current is None:
        raise QueueConflictError("retained components require an existing epoch")
    active_by_key = {
        component.descriptor.key: component for component in active_components
    }
    for descriptor in sorted(
        {item.key: item for item in referenced_descriptors}.values(),
        key=lambda item: item.key,
    ):
        assert current is not None
        try:
            retained = current.registry.retained(descriptor)
        except SchedulingError as exc:
            raise QueueConflictError(
                "referenced scheduling component is unavailable"
            ) from exc
        replacement = active_by_key.get(descriptor.key)
        if replacement is not None:
            if replacement is not retained:
                raise QueueConflictError(
                    "scheduling reload would reinterpret a retained component"
                )
            continue
        registry.register(retained, active=False)
    registry.freeze()
    return _CoordinatorSchedulingEpoch(
        epoch_id=epoch_id,
        registry=registry,
        planner_kinds=tuple(item.resource_kind for item in composition.planners),
        hard_evaluator_kinds=tuple(
            item.descriptor.kind for item in composition.hard_evaluators
        ),
        preference_scorer_kinds=tuple(
            item.descriptor.kind for item in composition.preference_scorers
        ),
        policy_kind=composition.policy.descriptor.kind,
        active_slurm_profiles=MappingProxyType(dict(active_slurm_profiles)),
        retained_slurm_profiles=MappingProxyType(dict(retained_slurm_profiles or {})),
    )


@dataclass(frozen=True, slots=True)
class _RemoteCandidateTarget:
    agent_id: str
    session_id: str
    offer_id: str
    availability_revision: str
    scheduling_availability_revision: str
    inventory_revision: str
    offer: AgentOffer
    profile: ResidentProfileDescriptor
    availability_atoms: tuple[CapacityAtom, ...]
    reflected_claim_ids: tuple[str, ...]


def _profile_satisfies_requirement(
    profile: ResidentProfileDescriptor, requirement: ExecutionRequirement
) -> bool:
    """Compare inert identities before any reservation or delivery."""

    return (
        profile.project_fingerprint == requirement.project_fingerprint
        and profile.environment_fingerprint == requirement.environment_fingerprint
        and profile.executor_fingerprint == requirement.executor_fingerprint
    )


def _replacement_scheduling_identities(
    *,
    offer_id: str,
    availability_revision: str,
    withheld_claim_ids: tuple[str, ...],
) -> tuple[str, str]:
    """Give each coordinator-owned net-capacity projection a fresh identity."""

    withheld = json.dumps(withheld_claim_ids, sort_keys=True, separators=(",", ":"))
    scheduling_offer_id = (
        "replacement-offer-"
        + hashlib.sha256(
            f"{offer_id}\0{availability_revision}\0{withheld}".encode("utf-8")
        ).hexdigest()
    )
    scheduling_availability_revision = (
        "replacement-availability-"
        + hashlib.sha256(
            f"{availability_revision}\0{withheld}".encode("utf-8")
        ).hexdigest()
    )
    return scheduling_offer_id, scheduling_availability_revision


def _connect_existing_sqlite(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)


def _coordinator_capacity(config: LocalDaemonConfig) -> tuple[CapacityAtom, ...]:
    """Protected upper bounds for local and policy-authorized agent namespaces."""

    maximum = 2**63 - 1
    local_atoms = config.agent_resource_capacity
    amounts: dict[tuple[str, str], tuple[int, str]] = {}
    gpu_atoms: list[CapacityAtom] = []
    for atom in local_atoms:
        if atom.owner_resource_kind == "gpu":
            gpu_atoms.append(atom)
            continue
        if atom.amount.denominator != 1:
            raise QueueServiceError(
                "coordinator capacity requires integral non-GPU provider atoms"
            )
        amounts[atom.key] = (atom.amount.numerator, atom.unit)
    for rule in config.agent_policy.agents:
        amounts[("cpu", f"{rule.agent_id}:cpu")] = (maximum, "count")
        amounts[("memory", f"{rule.agent_id}:memory")] = (maximum, "B")
        gpu_atoms.extend(
            device.capacity_atom(f"{rule.agent_id}:{device.device_id}")
            for device in rule.gpu_devices
        )
    return tuple(
        CapacityAtom(kind, key, ExactQuantity(amount), unit, ExactQuantity(1))
        for (kind, key), (amount, unit) in sorted(amounts.items())
    ) + tuple(gpu_atoms)


def initialize_local_daemon_owner_stores(
    config: LocalDaemonConfig,
    *,
    coordinator_id: str = "coordinator",
    agent_id: str = "agent",
) -> None:
    """Create the two current runtime-owner stores for a fresh daemon root."""

    capacity = _coordinator_capacity(config)
    SQLiteStageWorkStore(config.execution_database)._initialize()
    SQLiteCoordinatorAssignments(config.execution_database, capacity)._initialize()
    SQLiteReadyStageSubmissions(config.execution_database)._open_existing()
    SQLiteSlurmStageAssignments(
        config.execution_database, config.slurm_transfer_root
    )._initialize()
    SQLiteAgentJournal(config.agent_journal)._initialize()
    _initialize_owner_status_revisions(config)
    _bind_owner_store(
        config.execution_database, role="coordinator", stable_id=coordinator_id
    )
    _bind_owner_store(config.agent_journal, role="local-agent", stable_id=agent_id)


def local_daemon_owner_stores_available(
    config: LocalDaemonConfig,
    *,
    coordinator_id: str = "coordinator",
    agent_id: str = "agent",
) -> bool:
    """Whether both retained runtime owners can still be opened read-only."""

    try:
        capacity = _coordinator_capacity(config)
        SQLiteStageWorkStore(
            config.execution_database, _allow_initialize=False
        )._open_existing()
        SQLiteCoordinatorAssignments(
            config.execution_database, capacity, _allow_initialize=False
        )._open_existing()
        SQLiteReadyStageSubmissions(
            config.execution_database, _allow_initialize=False
        )._open_existing()
        SQLiteSlurmStageAssignments(
            config.execution_database,
            config.slurm_transfer_root,
            _allow_initialize=False,
        )._open_existing()
        SQLiteAgentJournal(
            config.agent_journal, _allow_initialize=False
        )._open_existing()
        with _connect_existing_sqlite(config.execution_database) as conn:
            _verify_owner_store_binding(
                conn, role="coordinator", stable_id=coordinator_id
            )
            axes = {
                str(row[0])
                for row in conn.execute(
                    "SELECT axis FROM local_daemon_status_revisions"
                )
            }
        with _connect_existing_sqlite(config.agent_journal) as conn:
            _verify_owner_store_binding(conn, role="local-agent", stable_id=agent_id)
            agent_revision = conn.execute(
                "SELECT revision FROM local_daemon_status_revision"
            ).fetchone()
        return {"scheduling", "assignment"}.issubset(
            axes
        ) and agent_revision is not None
    except Exception:
        return False


def local_daemon_owner_work_is_retained(
    config: LocalDaemonConfig,
    *,
    coordinator_id: str,
    agent_id: str,
) -> bool:
    """Return only a validated cross-owner retained-work result."""

    if not local_daemon_owner_stores_available(
        config, coordinator_id=coordinator_id, agent_id=agent_id
    ):
        raise QueueServiceError("retained daemon owner state is unavailable")
    try:
        journal = SQLiteAgentJournal(config.agent_journal, _allow_initialize=False)
        coordinator = SQLiteCoordinatorAssignments(
            config.execution_database,
            _coordinator_capacity(config),
            _allow_initialize=False,
        )
        journal._open_existing()
        coordinator._open_existing()
        return bool(journal.retained_claim_commands()) or bool(
            coordinator.retained_assignments(agent_id=config.machine_id)
        )
    except ManagedLocalError as exc:
        raise QueueServiceError(
            "local daemon retained-work proof is unavailable"
        ) from exc


def _bind_owner_store(path: Path, *, role: str, stable_id: str) -> None:
    with _connect_existing_sqlite(path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS local_daemon_owner_identity "
            "(role TEXT PRIMARY KEY, stable_id TEXT NOT NULL)"
        )
        rows = tuple(
            conn.execute("SELECT role, stable_id FROM local_daemon_owner_identity")
        )
        if not rows:
            conn.execute(
                "INSERT INTO local_daemon_owner_identity(role, stable_id) VALUES (?, ?)",
                (role, stable_id),
            )
        elif rows != ((role, stable_id),):
            raise sqlite3.DatabaseError("retained daemon owner identity is invalid")
        conn.commit()


def _verify_owner_store_binding(
    conn: sqlite3.Connection, *, role: str, stable_id: str
) -> None:
    rows = tuple(
        conn.execute("SELECT role, stable_id FROM local_daemon_owner_identity")
    )
    if rows != ((role, stable_id),):
        raise sqlite3.DatabaseError("retained daemon owner identity is invalid")


def _initialize_owner_status_revisions(config: LocalDaemonConfig) -> None:
    with sqlite3.connect(config.execution_database) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS local_daemon_status_revisions (
                axis TEXT PRIMARY KEY,
                revision INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO local_daemon_status_revisions(axis, revision)
                VALUES ('scheduling', 0), ('assignment', 0);
            CREATE TRIGGER IF NOT EXISTS local_daemon_scheduling_insert
                AFTER INSERT ON stage_work
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'scheduling'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_scheduling_update
                AFTER UPDATE ON stage_work
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'scheduling'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_preparation_insert
                AFTER INSERT ON preparation_intents
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'scheduling'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_assignment_insert
                AFTER INSERT ON coordinator_assignments
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_assignment_update
                AFTER UPDATE ON coordinator_assignments
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_offer_insert
                AFTER INSERT ON coordinator_offers
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_offer_update
                AFTER UPDATE ON coordinator_offers
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_assignment_event_insert
                AFTER INSERT ON coordinator_events
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_slurm_assignment_insert
                AFTER INSERT ON slurm_stage_assignments
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_slurm_assignment_update
                AFTER UPDATE ON slurm_stage_assignments
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_slurm_submission_insert
                AFTER INSERT ON ready_stage_submissions
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_slurm_submission_update
                AFTER UPDATE ON ready_stage_submissions
                BEGIN UPDATE local_daemon_status_revisions
                    SET revision = revision + 1 WHERE axis = 'assignment'; END;
            """
        )
        conn.commit()
    with sqlite3.connect(config.agent_journal) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS local_daemon_status_revision (
                revision INTEGER NOT NULL
            );
            INSERT INTO local_daemon_status_revision(revision)
                SELECT 0 WHERE NOT EXISTS (
                    SELECT 1 FROM local_daemon_status_revision
                );
            CREATE TRIGGER IF NOT EXISTS local_daemon_agent_assignment_insert
                AFTER INSERT ON assignments
                BEGIN UPDATE local_daemon_status_revision SET revision = revision + 1; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_agent_assignment_update
                AFTER UPDATE ON assignments
                BEGIN UPDATE local_daemon_status_revision SET revision = revision + 1; END;
            CREATE TRIGGER IF NOT EXISTS local_daemon_agent_event_insert
                AFTER INSERT ON events
                BEGIN UPDATE local_daemon_status_revision SET revision = revision + 1; END;
            """
        )
        conn.commit()


class _ScopedCoordinatorAuthority:
    """Least-privilege run/coordinator view used by orchestration and the agent.

    The SQLite authority remains an implementation detail of the daemon.  This
    adapter deliberately exposes only the exact Phase 1/2 calls needed after
    the coordinator binding has been accepted.
    """

    def __init__(
        self,
        store: SQLitePerRunAuthorityStore,
        *,
        run_uri: str,
        coordinator_id: str,
        ordinary_mutation_frozen: Callable[[str], bool] | None = None,
    ) -> None:
        self._store = store
        self._run_uri = run_uri
        self._coordinator_id = coordinator_id
        self._ordinary_mutation_frozen = ordinary_mutation_frozen

    def _require_ordinary_mutation(self, assignment_id: str) -> None:
        frozen = self._ordinary_mutation_frozen
        if frozen is not None and frozen(assignment_id):
            raise QueueConflictError(
                "ordinary terminal mutation is frozen by guarded recovery"
            )

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

    def read_cancellation_epoch_receipt(self, run_uri: str, operation_id: str):
        self._run(run_uri)
        return self._store.read_cancellation_epoch_receipt(run_uri, operation_id)

    def finalize_cancellation(
        self, run_uri: str, request: CancellationEpochRequest
    ) -> RunStatus:
        self._run(run_uri)
        if request.coordinator_id != self._coordinator_id:
            raise QueueConflictError("scoped authority coordinator conflicts")
        return self._store.finalize_cancellation(run_uri, request)

    def record_managed_attempt_terminal(
        self,
        run_uri: str,
        *,
        fence: ExecutionFence,
        status: StageStatus,
        reason: LifecycleReason,
    ) -> StatusTransition:
        self._run(run_uri)
        self._require_ordinary_mutation(fence.assignment_id)
        return self._store.record_managed_attempt_terminal(
            run_uri, fence=fence, status=status, reason=reason
        )

    def close_managed_attempt_fence(self, run_uri: str, **kwargs: object):
        self._run(run_uri)
        return self._store.close_managed_attempt_fence(run_uri, **kwargs)  # type: ignore[arg-type]

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
        if assignment_id is not None:
            self._require_ordinary_mutation(assignment_id)
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
    config: LocalDaemonConfig,
    run_uri: str,
    *,
    slurm_profiles: Mapping[tuple[str, str], SlurmReadyStageProfile] | None = None,
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
    requirements_payload = record["execution_requirements"]
    if not isinstance(requirements_payload, Mapping):
        raise QueueServiceError(
            "exact runtime record execution requirements are invalid"
        )
    try:
        execution_requirements = {
            name: ExecutionRequirement.from_dict(payload)
            for name, payload in requirements_payload.items()
        }
    except Exception as exc:
        raise QueueServiceError(
            "exact runtime record execution requirements are invalid"
        ) from exc
    if set(execution_requirements) != set(pipeline.stage_names):
        raise QueueServiceError(
            "exact runtime record execution requirements conflict with pipeline"
        )
    allowed_targets = {config.machine_id} | {
        rule.agent_id for rule in config.agent_policy.agents
    }
    available_slurm_profiles = (
        {
            (profile.profile_id, profile.configuration_fingerprint): profile
            for profile in config.slurm_profiles
        }
        if slurm_profiles is None
        else dict(slurm_profiles)
    )
    for placement in placements.values():
        if placement.route.kind is ExecutionRouteKind.MANAGED_AGENT and (
            placement.target is not None and placement.target not in allowed_targets
        ):
            raise QueueServiceError(
                "exact runtime record targets an unauthorized managed agent"
            )
        if placement.route.kind is ExecutionRouteKind.SLURM:
            profile = available_slurm_profiles.get(
                (
                    cast(str, placement.route.profile_id),
                    cast(
                        str,
                        placement.route.profile_configuration_fingerprint,
                    ),
                )
            )
            if (
                profile is None
                or placement.route.profile_descriptor != profile.descriptor
                or placement.route.profile_configuration_fingerprint
                != profile.configuration_fingerprint
            ):
                raise QueueServiceError(
                    "exact runtime record names a changed or unavailable SLURM profile"
                )
    if (
        parallel_execution_options(runtime_options).max_parallel_stages
        != record["max_parallel_stages"]
    ):
        raise QueueServiceError("exact runtime record concurrency conflicts")
    return ManagedLocalIntent(
        plan,
        runtime,
        placements,
        execution_requirements,
        pipeline,
        str(record["digest"]),
        cast(int, record["max_parallel_stages"]),
    )


def _validate_recovery_request_identity(
    request: RecoverUnknownAssignment, binding: tuple[object, str, str, int, str]
) -> None:
    target, run_uri, stage_name, attempt, _attempt_id = binding
    assignment = getattr(target, "assignment", target)
    if (
        request.run_uri != run_uri
        or request.stage_name != stage_name
        or request.attempt != attempt
        or request.stage_work_id != getattr(assignment, "stage_work_id", None)
    ):
        raise QueueConflictError("recovery request identity conflicts")


def _recovery_retry_policy(
    authority: SQLitePerRunAuthorityStore, run_uri: str, stage_name: str, attempt: int
):
    """Read the immutable attempt policy from the authority reliability owner."""

    facts = authority.list_reliability_policy_facts(run_uri, stage_name=stage_name)
    selected = [
        fact
        for fact in facts
        if fact.scope is ReliabilityPolicyScope.ATTEMPT and fact.attempt == attempt
    ]
    if not selected:
        return None
    policy = selected[-1].policy
    return cast(ReliabilityPolicy, policy).retry


def _current_attempt_retry_is_authorized(stage: object) -> bool:
    """Whether authority permits the orchestrator to prepare the next attempt."""

    attempts = getattr(stage, "attempts", ())
    if not attempts:
        return False
    current = attempts[-1]
    return any(
        decision.status.attempt == current.attempt
        and decision.should_retry
        and decision.next_attempt == current.attempt + 1
        for decision in getattr(stage, "retry_decisions", ())
    )


class _AuthorityReliabilityStore:
    """Narrow reliability facade that persists every fact in authority."""

    def __init__(self, authority: SQLitePerRunAuthorityStore) -> None:
        self._authority = authority

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> None:
        self._authority.write_reliability_policy_fact(run_uri, fact)

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        return self._authority.list_reliability_policy_facts(
            run_uri, stage_name=stage_name
        )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> None:
        self._authority.write_reliability_status_detail(run_uri, detail)

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        return self._authority.list_reliability_status_details(
            run_uri, stage_name=stage_name
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> None:
        self._authority.write_stage_attempt_transaction(run_uri, transaction)

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._authority.read_transaction_chain(run_uri, transaction_id)

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._authority.list_stage_attempt_transactions(
            run_uri, stage_name=stage_name
        )

    def write_retry_decision(self, run_uri: str, decision: RetryDecisionRecord) -> None:
        self._authority.write_retry_decision(run_uri, decision)

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        return self._authority.list_retry_decisions(run_uri, stage_name=stage_name)

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> None:
        self._authority.write_timeout_outcome(run_uri, outcome)

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        return self._authority.list_timeout_outcomes(run_uri, stage_name=stage_name)


class LocalDaemonExecution:
    """Build and drive the existing Phase 1 and Phase 2 owners."""

    def __init__(
        self,
        *,
        config: LocalDaemonConfig,
        coordinator_id: str,
        agent_id: str,
        coordinator_epoch: str,
        scheduling_epoch: str,
        cancellation_operation: Callable[[str], str | None],
        admission_activated: Callable[[str], None],
        daemon: LocalDaemon | None = None,
    ) -> None:
        self.config = config
        self._scheduling = _build_scheduling_epoch(
            epoch_id=scheduling_epoch,
            composition=config.scheduling_components,
            active_slurm_profiles={
                item.profile_id: item for item in config.slurm_profiles
            },
        )
        self.coordinator_id = coordinator_id
        self.agent_id = agent_id
        self.coordinator_epoch = coordinator_epoch
        self.cancellation_operation = cancellation_operation
        self.admission_activated = admission_activated
        self.daemon = daemon
        self.run_store = LocalRunStore(config.run_store_root)
        self.stage_work_store = SQLiteStageWorkStore(
            config.execution_database, _allow_initialize=False
        )
        initial_planners = self._scheduling.active_planners()
        configured_providers = tuple(config.agent_resource_providers or ())
        self.providers = _validate_agent_provider_composition(
            configured_providers, initial_planners
        )
        self.local_capacity = config.agent_resource_capacity
        self.capacity = _coordinator_capacity(config)
        self.coordinator = SQLiteCoordinatorAssignments(
            config.execution_database, self.capacity, _allow_initialize=False
        )
        self.slurm_submissions = SQLiteReadyStageSubmissions(
            config.execution_database, _allow_initialize=False
        )
        self.slurm_assignments = SQLiteSlurmStageAssignments(
            config.execution_database,
            config.slurm_transfer_root,
            _allow_initialize=False,
        )
        self.journal = SQLiteAgentJournal(config.agent_journal, _allow_initialize=False)
        self.stage_work_store._open_existing()
        self.coordinator._open_existing()
        self.slurm_submissions._open_existing()
        self.slurm_assignments._open_existing()
        self.journal._open_existing()
        self.supervisor = AgentProcessSupervisorClient(
            config.agent_root,
            SupervisorLaunchConfiguration(
                self.agent_id, (config.resident_worker_launch_profile,)
            ),
        )
        if not local_daemon_owner_stores_available(
            self.config,
            coordinator_id=self.coordinator_id,
            agent_id=self.agent_id,
        ):
            raise QueueServiceError("retained daemon owner state is unavailable")
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
        if missing and any(
            not _ResidentAssignmentWorkspace(
                self.config.agent_root, assignment_id
            ).has_request()
            for assignment_id in missing
        ):
            raise QueueServiceError(
                "coordinator retained assignment lacks an exact resident bundle"
            )
        for command in retained:
            provider = self.providers.get(command.claim.resource_kind)
            if provider is None:
                raise QueueServiceError(
                    "retained local claim has no configured provider"
                )
            provider.restore_capacity_holding(command)
        self._launch_lock = Lock()
        self._slurm_observed_operations: set[str] = set()
        # A run reconciliation cycle may only project and reserve work.  The
        # existing managed-local saga remains the durable result owner, but it
        # must not hold that run's scheduling turn while a resident worker is
        # executing.  These tasks are deliberately keyed by assignment ID:
        # assignment identity, rather than admission identity, is the durable
        # launch/result boundary.
        self._local_assignment_workers = ThreadPoolExecutor(
            max_workers=max(2, config.cpu_capacity),
            thread_name_prefix="loom-local-assignment",
        )
        self._local_assignment_futures: dict[str, Future[None]] = {}
        self._pending_local_assignment_reconciliation: dict[str, str] = {}
        self._cycle_contexts: dict[
            str, tuple[ManagedLocalIntent, _ScopedCoordinatorAuthority]
        ] = {}

    def close(self) -> None:
        """Stop only assignment observers after their durable owners settle."""

        self._local_assignment_workers.shutdown(wait=True)
        self._local_assignment_futures.clear()
        self._pending_local_assignment_reconciliation.clear()
        self._cycle_contexts.clear()

    def shutdown_clean(self) -> None:
        """Use all local authoritative owners before retiring the supervisor."""

        if local_daemon_owner_work_is_retained(
            self.config,
            coordinator_id=self.coordinator_id,
            agent_id=self.agent_id,
        ):
            raise QueueConflictError("local daemon has retained work")
        try:
            self.supervisor.shutdown_clean()
        except AgentProcessSupervisorError as exc:
            raise QueueConflictError(str(exc)) from exc

    def begin_cycle(self) -> None:
        """Observe completed exact assignment work before scheduling again."""

        for assignment_id, future in tuple(self._local_assignment_futures.items()):
            if not future.done():
                continue
            self._local_assignment_futures.pop(assignment_id, None)
            try:
                future.result()
            except Exception:
                # The retained assignment is the replay identity; a failed
                # observer must not disappear and permit replacement work.
                run_uri = self._retained_local_assignment_run_uri(assignment_id)
                if run_uri is not None:
                    self._pending_local_assignment_reconciliation[assignment_id] = (
                        run_uri
                    )
                    self._record_assignment_health(run_uri, "unavailable")
            else:
                run_uri = self._pending_local_assignment_reconciliation.get(
                    assignment_id
                )
                if run_uri is not None:
                    self._record_assignment_health(run_uri, "healthy")
                    self._pending_local_assignment_reconciliation.pop(
                        assignment_id, None
                    )
        for assignment_id in tuple(self._pending_local_assignment_reconciliation):
            if assignment_id in self._local_assignment_futures:
                continue
            future = self._local_assignment_workers.submit(
                self._reconcile_exact_local_assignment, assignment_id
            )
            daemon = self.daemon
            if daemon is not None:

                def wake_daemon(
                    _future: Future[None], target: LocalDaemon = daemon
                ) -> None:
                    target._wake.set()

                future.add_done_callback(wake_daemon)
            self._local_assignment_futures[assignment_id] = future
        self._cycle_contexts.clear()

    def _record_assignment_health(self, run_uri: str, health: str) -> None:
        daemon = self.daemon
        if daemon is not None:
            daemon._record_admission_health_for_run(run_uri, health)

    def local_assignment_reconciliation_pending(self, run_uri: str) -> bool:
        """Report the one live health override owned by exact replay."""

        return run_uri in self._pending_local_assignment_reconciliation.values()

    def _retained_local_assignment_run_uri(self, assignment_id: str) -> str | None:
        for assignment, _receipt in self.coordinator.retained_assignments(
            agent_id=self.config.machine_id
        ):
            if assignment.assignment_id == assignment_id:
                return assignment.run_uri
        return None

    def _reconcile_exact_local_assignment(self, assignment_id: str) -> None:
        matches = tuple(
            item
            for item in self.coordinator.retained_assignments(
                agent_id=self.config.machine_id
            )
            if item[0].assignment_id == assignment_id
        )
        if not matches:
            return
        if len(matches) != 1:
            raise QueueConflictError("retained local assignment identity conflicts")
        assignment, decision_receipt = matches[0]
        if not self._reconcile_retained_local_assignment(
            assignment,
            decision_receipt,
            suspend_requested=(
                None if self.daemon is None else self.daemon._stop.is_set
            ),
        ):
            raise ManagedLocalError("retained local assignment is intentionally held")

    def _reconcile_retained_local_assignment(
        self,
        assignment: ManagedAssignment,
        decision_receipt: Mapping[str, PlainData],
        *,
        suspend_requested: Callable[[], bool] | None = None,
    ) -> bool:
        """Replay one exact durable assignment without allocating replacement work."""

        if self._recovery_retains_assignment(assignment.assignment_id):
            return False
        workspace = _ResidentAssignmentWorkspace(
            self.config.agent_root, assignment.assignment_id
        )
        request = workspace.request()
        if (
            request.assignment_id != assignment.assignment_id
            or request.stage_work_id != assignment.stage_work_id
            or request.stage_name != assignment.stage_name
            or request.attempt != assignment.attempt
            or request.attempt_id != assignment.attempt_id
            or request.offer_id != assignment.offer_id
            or request.claim_id != assignment.claim_id
        ):
            raise QueueConflictError(
                "retained resident bundle conflicts with coordinator identity"
            )
        raw_worker_request = self.run_store.read_stage_worker_request(
            assignment.run_uri,
            assignment.stage_name,
            attempt=assignment.attempt,
        )
        if raw_worker_request is None:
            raise QueueConflictError(
                "retained local assignment has no prepared worker request"
            )
        authority_store = SQLitePerRunAuthorityStore(assignment.run_uri)
        authority_store.open_run(assignment.run_uri)
        intent = load_managed_local_intent(
            self.config,
            assignment.run_uri,
            slurm_profiles=self._scheduling.available_slurm_profiles(),
        )
        scoped_authority = _ScopedCoordinatorAuthority(
            authority_store,
            run_uri=assignment.run_uri,
            coordinator_id=self.coordinator_id,
            ordinary_mutation_frozen=self._ordinary_mutation_frozen,
        )
        try:
            run_managed_local_assignment(
                coordinator=self.coordinator,
                authority=scoped_authority,
                journal=self.journal,
                assignment=assignment,
                worker_request=StageWorkerRequest.from_dict(raw_worker_request),
                claims=request.claims,
                providers=self.providers,
                run_store=self.run_store,
                max_parallel_stages=intent.max_parallel_stages,
                cancellation_requested=lambda: (
                    self._install_run_cancellation_if_requested(
                        assignment.run_uri,
                        scoped_authority,
                        intent.plan.stage_order,
                    )
                ),
                decision_receipt=decision_receipt,
                agent_root=self.config.agent_root,
                supervisor=self.supervisor,
                resident_launch_profile=self.config.resident_worker_launch_profile,
                suspend_requested=suspend_requested,
            )
        except ManagedLocalError:
            if not self._is_exact_retained_unknown(assignment.assignment_id):
                raise
            return False
        return True

    def resume_retained_local_work(self) -> None:
        """Join every local supervisor operation before daemon availability."""

        intentionally_retained: set[str] = set()
        for assignment, decision_receipt in self.coordinator.retained_assignments(
            agent_id=self.config.machine_id
        ):
            if not self._reconcile_retained_local_assignment(
                assignment, decision_receipt
            ):
                intentionally_retained.add(assignment.assignment_id)
        retained_commands = self.journal.retained_claim_commands()
        if any(
            command.assignment.assignment_id not in intentionally_retained
            for command in retained_commands
        ):
            raise QueueConflictError(
                "retained local assignment reconciliation is incomplete"
            )
        allowed_claim_ids = {
            command.assignment.claim_id
            for command in retained_commands
            if command.assignment.assignment_id in intentionally_retained
        }
        for kind, provider in sorted(self.providers.items()):
            observed = provider.observe(
                ObserveRequest(
                    self.config.machine_id,
                    self.coordinator_epoch,
                    f"startup-reconciled:{kind}",
                )
            )
            if not set(observed.live_claim_ids).issubset(allowed_claim_ids):
                raise QueueConflictError(
                    "startup provider observation retains unresolved claims"
                )

    def _recovery_retains_assignment(self, assignment_id: str) -> bool:
        daemon = self.daemon
        return (
            False
            if daemon is None
            else daemon._recovery_retains_assignment(assignment_id)
        )

    def _is_exact_retained_unknown(self, assignment_id: str) -> bool:
        try:
            return self.coordinator.state(
                assignment_id
            ) == "unknown" and self.journal.read_state(assignment_id) in {
                AssignmentState.PREPARE_UNKNOWN,
                AssignmentState.ACTIVATION_UNKNOWN,
                AssignmentState.START_UNKNOWN,
            }
        except ManagedLocalError:
            return False

    @property
    def scheduling_epoch(self) -> str:
        return self._scheduling.epoch_id

    @property
    def planners(self) -> Mapping[str, ResourcePlanner]:
        return MappingProxyType(self._scheduling.active_planners())

    @property
    def slurm_profiles(
        self,
    ) -> Mapping[tuple[str, str], SlurmReadyStageProfile]:
        return MappingProxyType(self._scheduling.available_slurm_profiles())

    @property
    def gpu_planner(self) -> ResourcePlanner:
        return self._scheduling.active_planners()["gpu"]

    def validate_fresh_intent(self, intent: ManagedLocalIntent) -> None:
        """Reject a not-yet-admitted runtime record from another epoch."""

        for placement in intent.placements.values():
            for kind, descriptor in placement.planner_descriptors.items():
                self._require_active_descriptor(kind, descriptor)
            for spec in placement.hard_constraints:
                if spec.descriptor is None:
                    raise QueueConflictError(
                        "managed runtime hard evaluator is unresolved"
                    )
                self._require_active_descriptor(spec.evaluator, spec.descriptor)
            for spec in placement.preferences:
                if spec.descriptor is None:
                    raise QueueConflictError(
                        "managed runtime preference scorer is unresolved"
                    )
                self._require_active_descriptor(spec.scorer, spec.descriptor)
            if placement.route.kind is ExecutionRouteKind.SLURM:
                profile = self._scheduling.active_slurm_profiles.get(
                    cast(str, placement.route.profile_id)
                )
                if (
                    profile is None
                    or profile.descriptor != placement.route.profile_descriptor
                    or profile.configuration_fingerprint
                    != placement.route.profile_configuration_fingerprint
                ):
                    raise QueueConflictError(
                        "managed runtime SLURM profile is not active"
                    )

    def _require_active_descriptor(
        self, kind: str, descriptor: SchedulingComponentDescriptor
    ) -> None:
        try:
            component = self._scheduling.registry.active(kind)
        except SchedulingError as exc:
            raise QueueConflictError(
                "managed runtime scheduling component is not active"
            ) from exc
        if getattr(component, "descriptor", None) != descriptor:
            raise QueueConflictError(
                "managed runtime scheduling component is from another epoch"
            )

    def open_owner_stores(self) -> None:
        """Recheck retained owners before any new scheduling mutation."""

        try:
            self.stage_work_store._open_existing()
            self.coordinator._open_existing()
            self.slurm_submissions._open_existing()
            self.slurm_assignments._open_existing()
            self.journal._open_existing()
            if not local_daemon_owner_stores_available(
                self.config,
                coordinator_id=self.coordinator_id,
                agent_id=self.agent_id,
            ):
                raise QueueServiceError("retained daemon owner state is unavailable")
        except Exception:
            raise QueueServiceError(
                "retained daemon owner state is unavailable"
            ) from None

    def _admission_context(
        self, admission: LocalDaemonAdmission
    ) -> tuple[ManagedLocalIntent, _ScopedCoordinatorAuthority]:
        """Open and bind the exact retained execution context for one admission."""

        self.open_owner_stores()
        intent = load_managed_local_intent(
            self.config,
            admission.run_uri,
            slurm_profiles=self._scheduling.available_slurm_profiles(),
        )
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
            ordinary_mutation_frozen=self._ordinary_mutation_frozen,
        )
        return intent, scoped_authority

    def reconcile_admission(
        self, admission: LocalDaemonAdmission
    ) -> LocalDaemonExecutionOutcome:
        """Reconcile one run into durable ready work without selecting capacity."""

        intent, scoped_authority = self._admission_context(admission)
        self._cycle_contexts[admission.admission_id] = (intent, scoped_authority)
        if (
            admission.cancellation_operation_id is not None
            or self.cancellation_operation(admission.admission_id) is not None
        ):
            return self._cancel(admission, scoped_authority, intent.plan.stage_order)
        self.admission_activated(admission.admission_id)

        placements = dict(intent.placements)
        orchestrator = RunOrchestrator(
            authority=scoped_authority,
            store=self.stage_work_store,
            owner_id=self.coordinator_id,
        )
        if self.cancellation_operation(admission.admission_id) is not None:
            return self._cancel(admission, scoped_authority, intent.plan.stage_order)
        _decision_as_of, snapshot_time = self._daemon_owner()._accepted_snapshot()
        snapshot = scoped_authority.open_run(admission.run_uri)
        slurm_in_flight, slurm_diagnostic = self._reconcile_slurm_run(
            admission.run_uri, scoped_authority
        )
        snapshot = scoped_authority.open_run(admission.run_uri)
        terminal = self._terminal_outcome(intent.plan, snapshot, scoped_authority)
        if terminal is not None:
            if slurm_in_flight:
                return LocalDaemonExecutionOutcome(
                    LocalDaemonAdmissionState.ACTIVE,
                    slurm_diagnostic or "SLURM release remains durably in flight",
                )
            return terminal
        orchestrator.reconcile(
            admission_id=admission.admission_id,
            plan=intent.plan,
            authority_snapshot=snapshot,
            placements=placements,
            execution_requirements=intent.execution_requirements,
            ready_at=snapshot_time,
            run_priority=admission.run_priority,
            enqueue_sequence=admission.enqueue_sequence,
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
        slurm_in_flight, slurm_diagnostic = self._reconcile_slurm_run(
            admission.run_uri, scoped_authority
        )
        snapshot = scoped_authority.open_run(admission.run_uri)
        terminal = self._terminal_outcome(intent.plan, snapshot, scoped_authority)
        if terminal is not None:
            if slurm_in_flight:
                return LocalDaemonExecutionOutcome(
                    LocalDaemonAdmissionState.ACTIVE,
                    slurm_diagnostic or "SLURM release remains durably in flight",
                )
            return terminal
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

    def schedule_once(
        self, admissions: Mapping[str, LocalDaemonAdmission]
    ) -> tuple[str, LocalDaemonExecutionOutcome] | None:
        """Select and durably start one assignment from the global ready window."""

        if not admissions:
            return None
        with self._launch_lock:
            decision_as_of, snapshot_time = self._daemon_owner()._accepted_snapshot()
            window = self.stage_work_store.ready_window()
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
            local_candidate = self._candidate()
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
                local_profile = ResidentProfileDescriptor.from_dict(
                    self.config.resident_worker_launch_profile.descriptor
                )
                candidates = tuple(
                    [
                        local_candidate
                        for _ in (0,)
                        if local_candidate.candidate_id not in remote_targets
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
                candidate_id = cast(str, decision.candidate_id)
                remote_target = remote_targets.get(candidate_id)
                local_profile = ResidentProfileDescriptor.from_dict(
                    self.config.resident_worker_launch_profile.descriptor
                )
                selected_profile = (
                    local_profile if remote_target is None else remote_target[1].profile
                )
                if not _profile_satisfies_requirement(
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

    def advance(self, admission: LocalDaemonAdmission) -> LocalDaemonExecutionOutcome:
        """Compatibility wrapper for one-admission embedded callers."""

        outcome = self.reconcile_admission(admission)
        if outcome.state not in {
            LocalDaemonAdmissionState.ACTIVE,
            LocalDaemonAdmissionState.WAITING,
        }:
            return outcome
        scheduled = self.schedule_once({admission.admission_id: admission})
        return outcome if scheduled is None else scheduled[1]

    def _publish_slurm_verifier(
        self,
        assignment_id: str,
        submission: SlurmReadyStageSubmission,
    ) -> None:
        """Publish one retained verifier to bootstrap authority."""

        capability = submission.capability
        if capability is None:
            raise SlurmPlanningError("ready-stage submission requires a capability")
        request = submission.request
        self.slurm_assignments.install_capability(
            assignment_id,
            operation_id=request.operation_id,
            request_digest=request.digest,
            profile_id=request.profile_id,
            profile_descriptor=request.profile_descriptor,
            verifier=capability.verifier,
        )

    def _mirror_slurm_submission_eligibility(
        self,
        assignment_id: str,
        submission: SlurmReadyStageSubmission,
    ) -> None:
        """Mirror one committed submit barrier to bootstrap authority."""

        capability = submission.capability
        if capability is None:
            raise SlurmPlanningError("ready-stage submission requires a capability")
        request = submission.request
        self.slurm_assignments.mark_submission_eligible(
            assignment_id,
            operation_id=request.operation_id,
            request_digest=request.digest,
            profile_id=request.profile_id,
            profile_descriptor=request.profile_descriptor,
            verifier=capability.verifier,
        )

    def _before_slurm_runner(
        self,
        assignment_id: str,
        submission: SlurmReadyStageSubmission,
    ) -> bool:
        """Publish the durable handoff, then make the final no-call decision."""

        self._mirror_slurm_submission_eligibility(assignment_id, submission)
        return self._run_cancellation_operation(submission.request.run_uri) is None

    def _submit_slurm_ready(
        self,
        *,
        assignment_id: str,
        request: SlurmReadyStageRequest,
        profile: SlurmReadyStageProfile,
        script_path: Path,
    ) -> SlurmReadyStageSubmission:
        """Commit the cross-owner handoff before the one external submission."""

        prepared = self.slurm_submissions.prepare(request, profile, script_path)
        if prepared.state is ReadyStageState.INTENT:
            self._publish_slurm_verifier(assignment_id, prepared)
        return self.slurm_submissions.submit(
            request,
            profile,
            script_path,
            before_runner=lambda submitting: self._before_slurm_runner(
                assignment_id, submitting
            ),
        )

    def _release_slurm_assignment(self, assignment_id: str) -> None:
        """Revoke one exact site receipt before committing final release."""

        record = self.slurm_assignments.read(assignment_id)
        if record.state == "released":
            return
        if record.state == "terminal":
            self.slurm_assignments.advance(
                assignment_id, expected="terminal", next_state="logical_released"
            )
        elif record.state == "rejected":
            self.slurm_assignments.advance(
                assignment_id, expected="rejected", next_state="logical_released"
            )
        elif record.state != "logical_released":
            raise QueueConflictError("SLURM assignment is not releasable")
        submission = self.slurm_submissions.read(record.assignment.operation_id)
        capability = submission.capability
        request = submission.request
        if (
            capability is None
            or request.operation_id != record.assignment.operation_id
            or request.digest != record.assignment.request_digest
            or request.profile_id != record.assignment.profile_id
            or request.profile_descriptor != record.assignment.profile_descriptor
        ):
            raise QueueConflictError("SLURM provider release binding conflicts")
        self._slurm_profile(
            record.assignment.profile_id,
            record.assignment.profile_configuration_fingerprint,
        ).job_private_file_provider.revoke(capability)
        self.slurm_assignments.release(assignment_id)

    def _reject_slurm_assignment(
        self, record: SlurmStageRecord, authority: _ScopedCoordinatorAuthority
    ) -> None:
        """Perform the definite-rejection release saga in its only safe order."""

        if record.state != "rejected":
            raise QueueConflictError("SLURM assignment is not definitely rejected")
        # The authority call is idempotent.  It is intentionally separate from
        # every release owner so a crash leaves the same rejected record for
        # replay and can never free capacity while the fence is still bound.
        authority.unbind_prepared_attempt(
            record.assignment.run_uri,
            assignment_id=record.assignment.assignment_id,
            attempt_id=record.assignment.attempt_id,
        )
        self._release_slurm_assignment(record.assignment.assignment_id)

    def _reconcile_slurm_run(
        self,
        run_uri: str,
        authority: _ScopedCoordinatorAuthority,
    ) -> tuple[bool, str | None]:
        records = self.slurm_assignments.list_run_unreleased(run_uri)
        if not records:
            return False, None
        in_flight = False
        diagnostic: str | None = None
        for retained in records:
            record = retained
            assignment_id = record.assignment.assignment_id
            if self._reconcile_slurm_terminal_assignment(record, authority):
                record = self.slurm_assignments.read(assignment_id)
            if record.state in {"logical_released", "terminal", "rejected"}:
                try:
                    if record.state == "rejected":
                        self._reject_slurm_assignment(record, authority)
                    else:
                        self._release_slurm_assignment(assignment_id)
                except SlurmPlanningError:
                    in_flight = True
                    diagnostic = diagnostic or "slurm_release_awaiting_acknowledgement"
                    continue
                if record.state == "rejected":
                    diagnostic = diagnostic or "slurm_submission_rejected"
                continue
            if record.state == "conflict":
                in_flight = True
                diagnostic = diagnostic or "slurm_submission_conflict"
                continue
            if record.state == "reserved":
                authority.bind_prepared_attempt(
                    record.assignment.run_uri,
                    assignment_id=assignment_id,
                    attempt_id=record.assignment.attempt_id,
                )
                self.slurm_assignments.advance(
                    assignment_id, expected="reserved", next_state="bound"
                )
                record = self.slurm_assignments.read(assignment_id)
            if record.state in {"bound", "submitting", "unknown"}:
                profile = self._slurm_profile(
                    record.assignment.profile_id,
                    record.assignment.profile_configuration_fingerprint,
                )
                submission = self.slurm_submissions.find(record.assignment.operation_id)
                if submission is None or submission.state is ReadyStageState.INTENT:
                    if record.state != "bound":
                        in_flight = True
                        diagnostic = diagnostic or "slurm_submission_intent_unavailable"
                        continue
                    request = SlurmReadyStageRequest.from_dict(record.request)
                    script_path = self.config.slurm_script_root / f"{assignment_id}.sh"
                    submission = self._submit_slurm_ready(
                        assignment_id=assignment_id,
                        request=request,
                        profile=profile,
                        script_path=script_path,
                    )
                elif submission.state is ReadyStageState.SUBMITTING:
                    self._mirror_slurm_submission_eligibility(assignment_id, submission)
                if submission.state in {
                    ReadyStageState.SUBMITTING,
                    ReadyStageState.UNKNOWN,
                }:
                    submission = self.slurm_submissions.reconcile(
                        record.assignment.operation_id, profile
                    )
                state = self.slurm_assignments.record_submission(
                    assignment_id,
                    state=submission.state.value,
                    job_id=submission.job_id,
                    cluster=submission.cluster,
                )
                if state == "rejected":
                    self._reject_slurm_assignment(
                        self.slurm_assignments.read(assignment_id), authority
                    )
                    diagnostic = diagnostic or "slurm_submission_rejected"
                    continue
                if state == "conflict":
                    diagnostic = diagnostic or "slurm_submission_conflict"
            current_state = self.slurm_assignments.read(assignment_id).state
            operation_id = record.assignment.operation_id
            if (
                current_state in {"accepted", "granted", "running"}
                and operation_id not in self._slurm_observed_operations
            ):
                profile = self._slurm_profile(
                    record.assignment.profile_id,
                    record.assignment.profile_configuration_fingerprint,
                )
                self.slurm_submissions.observe(operation_id, profile)
                self._slurm_observed_operations.add(operation_id)
            in_flight = True
        return in_flight, diagnostic

    def _reconcile_slurm_terminal_assignment(
        self,
        record: SlurmStageRecord,
        authority: _ScopedCoordinatorAuthority,
    ) -> bool:
        """Mirror exact authority terminal evidence before provider release.

        A bootstrap may lose its response after committing the authority result,
        leaving the assignment in ``granted`` or ``running``.  The retained
        report, assignment/attempt binding, fence, and authority stage result
        must all agree before this recovery advances the assignment.  This
        keeps an authority-terminal admission retryable until the shared revoke
        owner receives a definite acknowledgement.
        """

        if record.state not in {"granted", "running"}:
            return False
        report = record.report
        fence = record.fence
        if report is None or fence is None:
            return False
        snapshot = authority.open_run(record.assignment.run_uri)
        stage = next(
            (
                item
                for item in snapshot.stages
                if item.stage_name == record.assignment.stage_name
            ),
            None,
        )
        if stage is None or stage.status is not report.status:
            return False
        granted = authority.grant_prepared_attempt(
            record.assignment.run_uri,
            assignment_id=record.assignment.assignment_id,
            attempt_id=record.assignment.attempt_id,
        )
        if granted.fencing_token != fence:
            raise QueueConflictError("SLURM terminal fence conflicts")
        self.slurm_assignments.mark_terminal(record.assignment.assignment_id)
        return True

    def recovery_has_ordinary_winner(self, request: RecoverUnknownAssignment) -> bool:
        """Recheck complete ordinary truth before containment and before close."""

        binding = self._recovery_binding(request)
        run_uri, stage_name, attempt, attempt_id = binding[1:]
        authority = SQLitePerRunAuthorityStore(run_uri)
        snapshot = authority.open_run(run_uri)
        for stage in snapshot.stages:
            if stage.stage_name != stage_name:
                continue
            for item in stage.attempts:
                if item.attempt != attempt or item.attempt_id != attempt_id:
                    continue
                if item.status in {
                    StageStatus.SUCCEEDED,
                    StageStatus.FAILED,
                    StageStatus.CANCELLED,
                }:
                    detail = {} if item.reason is None else item.reason.detail
                    return detail.get("recovery_id") != request.recovery_id
                break
        if isinstance(request.target, SlurmRecoveryTarget):
            record = cast(SlurmStageRecord, binding[0])
            if record.report is None or record.fence is None:
                return False
            try:
                self.slurm_assignments.committed_result(
                    record.assignment.assignment_id,
                    cast(str, record.bootstrap_incarnation),
                    record.fence,
                )
            except QueueConflictError:
                return False
            return True
        if self._managed_target_is_remote(request.assignment_id):
            return self._remote_result_is_complete(request.assignment_id)
        return self.journal.read_result(request.assignment_id) is not None

    def validate_recovery_admission(self, request: RecoverUnknownAssignment) -> None:
        """Require an exact current unknown target before recovery is durable."""

        binding = self._recovery_binding(request)
        run_uri, stage_name, attempt, attempt_id = binding[1:]
        snapshot = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
        matches = [
            item
            for stage in snapshot.stages
            if stage.stage_name == stage_name
            for item in stage.attempts
            if item.attempt == attempt and item.attempt_id == attempt_id
        ]
        if len(matches) != 1:
            raise QueueConflictError("recovery authority identity conflicts")
        current = matches[0]
        if (
            current.revision.sequence != request.expected_state_version
            or current.status not in {StageStatus.SUBMITTED, StageStatus.RUNNING}
        ):
            raise QueueConflictError("recovery expected state conflicts")
        if not self._recovery_binding_is_unknown(request, binding):
            raise QueueConflictError("recovery target is not in an exact unknown state")

    def recovery_target_is_still_unknown(
        self, request: RecoverUnknownAssignment
    ) -> bool:
        """Recheck the target-owned unknown fact after intent wins admission."""

        binding = self._recovery_binding(request)
        return self._recovery_binding_is_unknown(request, binding)

    def _recovery_binding_is_unknown(
        self,
        request: RecoverUnknownAssignment,
        binding: tuple[object, str, str, int, str],
    ) -> bool:
        if isinstance(request.target, SlurmRecoveryTarget):
            record = cast(SlurmStageRecord, binding[0])
            if record.report is not None:
                return False
            if record.state == "unknown":
                return True
            if record.state != "running":
                return False
            submission = self.slurm_submissions.find(record.assignment.operation_id)
            return submission is not None and (
                submission.scheduler_source == "unavailable"
                or submission.scheduler_state == "UNKNOWN"
            )
        if self._managed_target_is_remote(request.assignment_id):
            with sqlite3.connect(self.config.control_database) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT state, report_json, session_id FROM remote_assignments "
                    "WHERE assignment_id = ?",
                    (request.assignment_id,),
                ).fetchone()
                if row is None or row["report_json"] is not None:
                    return False
                coordinator_state = self.coordinator.state(request.assignment_id)
                if coordinator_state == "unknown":
                    return str(row["state"]) in {"GRANTED", "RUNNING", "UNKNOWN"}
                if coordinator_state not in {"granted", "running"} or str(
                    row["state"]
                ) not in {"GRANTED", "RUNNING"}:
                    return False
                offer = conn.execute(
                    "SELECT expires_at FROM agent_offers "
                    "WHERE session_id = ? AND current = 1",
                    (str(row["session_id"]),),
                ).fetchone()
            observed_at = (
                utc_timestamp()
                if self.daemon is None
                else self._daemon_owner()._clock()  # noqa: SLF001
            )
            return offer is not None and str(offer["expires_at"]) < observed_at
        return self._is_exact_retained_unknown(request.assignment_id)

    def resolve_recovery_evidence(
        self, request: RecoverUnknownAssignment
    ) -> tuple[str, Mapping[str, PlainData] | None]:
        """Return target-owned evidence, a pending remote request, or UNKNOWN."""

        binding = self._recovery_binding(request)
        if isinstance(request.target, SlurmRecoveryTarget):
            record = cast(SlurmStageRecord, binding[0])
            profile = self._slurm_profile(
                record.assignment.profile_id,
                record.assignment.profile_configuration_fingerprint,
            )
            if profile.containment_helper is None:
                return "unknown", None
            proof = self._slurm_recovery_proof(request, record, profile)
            receipt = resolve_slurm_containment(profile, proof)
            if not receipt.contained:
                return "unknown", None
            evidence = freeze_plain_data(
                {
                    "kind": "slurm_helper",
                    "state": "CONTAINED",
                    "helper_descriptor": profile.containment_helper.descriptor,
                    "evidence_id": receipt.evidence_id,
                    "evidence_revision": receipt.evidence_revision,
                    "echo": dict(cast(Mapping[str, PlainData], receipt.echo)),
                },
                path="SLURM recovery evidence",
            )
            assert isinstance(evidence, Mapping)
            return "contained", evidence
        if self._managed_target_is_remote(request.assignment_id):
            return self._remote_managed_recovery_evidence(request)
        assignment = cast(ManagedAssignment, binding[0])
        workspace = _ResidentAssignmentWorkspace(
            self.config.agent_root, assignment.assignment_id
        )
        raw = workspace.supervisor_launch_json()
        if raw is None:
            return "unknown", None
        try:
            from ._managed_local import _launch_from_value

            launch = _launch_from_value(json.loads(raw))
            if not self._launch_matches_recovery(request, launch):
                return "unknown", None
            receipt = self.supervisor.contain(launch)
            if receipt.state is not SupervisorLaunchState.CONTAINED:
                return "unknown", None
            evidence = _managed_containment_evidence(
                {
                    "kind": "managed_supervisor",
                    "state": "CONTAINED",
                    "supervisor_id": launch.supervisor_id,
                    "continuity_epoch": launch.continuity_epoch,
                    "agent_id": assignment.agent_id,
                    "supervisor_agent_id": launch.agent_id,
                    "session_id": launch.session_id,
                    "assignment_id": launch.assignment_id,
                    "process_execution_id": launch.process_execution_id,
                    "execution_fence": launch.execution_fence,
                    "launch_operation_id": launch.launch_operation_id,
                    "launch_spec_digest": launch.spec_digest,
                    "supervisor_revision": receipt.supervisor_revision,
                    "worker_result_digest": receipt.worker_result_digest,
                }
            )
        except (ManagedLocalError, QueueServiceError, ValueError):
            return "unknown", None
        return "contained", evidence

    def close_recovered_assignment(
        self,
        request: RecoverUnknownAssignment,
        evidence: Mapping[str, PlainData],
        *,
        recorded_at: str,
    ) -> Mapping[str, PlainData]:
        """Close from persisted evidence and write one existing-owner decision."""

        binding = self._recovery_binding(request)
        self._validate_persisted_recovery_evidence(request, binding, evidence)
        run_uri, stage_name, attempt, attempt_id = binding[1:]
        authority_store = SQLitePerRunAuthorityStore(run_uri)
        authority_store.open_run(run_uri)
        authority = _ScopedCoordinatorAuthority(
            authority_store,
            run_uri=run_uri,
            coordinator_id=self.coordinator_id,
        )
        status = (
            StageStatus.FAILED
            if request.requested_outcome == "failed"
            else StageStatus.CANCELLED
        )
        try:
            transition = authority.close_managed_attempt_fence(
                run_uri,
                recovery_id=request.recovery_id,
                fence=ExecutionFence(
                    request.assignment_id, attempt_id, request.execution_fence
                ),
                expected_state_version=request.expected_state_version,
                status=status,
                reason=LifecycleReason(
                    code="operator.recovery_close",
                    message=request.reason,
                    detail={
                        "assignment_id": request.assignment_id,
                        "evidence": dict(evidence),
                    },
                ),
            )
        except AuthorityStoreError as exc:
            if "ordinary terminal fact supersedes recovery" in str(exc):
                return {
                    "recovery_id": request.recovery_id,
                    "state": "superseded",
                    "evidence": "ORDINARY_TERMINAL",
                }
            raise
        decision: RetryDecisionRecord | None = None
        if request.consider_retry:
            decision = self._record_recovery_reliability(
                authority_store,
                request=request,
                stage_name=stage_name,
                attempt=attempt,
                status=status,
                recorded_at=recorded_at,
            )
        return {
            "recovery_id": request.recovery_id,
            "state": "closed",
            "evidence": dict(evidence),
            "revision": transition.revision.sequence,
            "retry_allowed": None if decision is None else decision.should_retry,
            "next_attempt": None if decision is None else decision.next_attempt,
            "physical_ownership": "retained",
        }

    def _record_recovery_reliability(
        self,
        authority: SQLitePerRunAuthorityStore,
        *,
        request: RecoverUnknownAssignment,
        stage_name: str,
        attempt: int,
        status: StageStatus,
        recorded_at: str,
    ) -> RetryDecisionRecord:
        store: RunReliabilityStore = _AuthorityReliabilityStore(authority)
        intent = load_managed_local_intent(
            self.config,
            request.run_uri,
            slurm_profiles=self._scheduling.available_slurm_profiles(),
        )
        record_resolved_reliability_policy_fact(
            store,
            run_uri=request.run_uri,
            stage_name=stage_name,
            attempt=attempt,
            resolved_runtime=intent.runtime[stage_name],
            recorded_at=recorded_at,
        )
        terminal_state = (
            StageAttemptTransactionState.FAILED
            if status is StageStatus.FAILED
            else StageAttemptTransactionState.CANCELLED
        )
        transactions = tuple(
            item
            for item in store.list_stage_attempt_transactions(
                request.run_uri, stage_name=stage_name
            )
            if item.attempt == attempt
            and item.state
            in {
                StageAttemptTransactionState.FAILED,
                StageAttemptTransactionState.CANCELLED,
            }
        )
        if transactions and any(
            item.state is not terminal_state for item in transactions
        ):
            raise QueueConflictError("recovery reliability transition conflicts")
        if not transactions:
            record_stage_reliability_transition(
                store,
                run_uri=request.run_uri,
                stage_name=stage_name,
                attempt=attempt,
                state=terminal_state,
                stage_status=status,
                recorded_at=recorded_at,
            )
        decisions = tuple(
            item
            for item in store.list_retry_decisions(
                request.run_uri, stage_name=stage_name
            )
            if item.status.attempt == attempt
        )
        if decisions:
            if len(decisions) != 1:
                raise QueueConflictError("recovery retry decision conflicts")
            return decisions[0]
        failure = (
            None
            if status is StageStatus.CANCELLED
            else ExecutionFailure(
                schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
                run_uri=request.run_uri,
                stage_name=stage_name,
                attempt=attempt,
                failed_at=recorded_at,
                executor="guarded-recovery",
                failure_type="executor_infrastructure",
                message=request.reason,
                executor_metadata={"recovery_id": request.recovery_id},
                details={"assignment_id": request.assignment_id},
            )
        )
        decision = record_retry_decision_for_stage_result(
            store,
            run_uri=request.run_uri,
            stage_name=stage_name,
            attempt=attempt,
            stage_status=status,
            recorded_at=recorded_at,
            policy=_recovery_retry_policy(
                authority, request.run_uri, stage_name, attempt
            ),
            failure=failure,
        )
        if decision is None:
            raise QueueServiceError("recovery retry decision was not persisted")
        return decision

    def _recovery_binding(
        self, request: RecoverUnknownAssignment
    ) -> tuple[object, str, str, int, str]:
        if isinstance(request.target, SlurmRecoveryTarget):
            record = self.slurm_assignments.read(request.assignment_id)
            target = request.target
            if (
                record.assignment.operation_id != target.submission_operation_id
                or record.assignment.profile_id != target.profile_id
                or record.job_id != target.job_id
                or record.cluster != target.cluster_id
                or record.bootstrap_incarnation != target.bootstrap_incarnation_id
                or record.fence != request.execution_fence
                or record.process_execution_id != request.process_execution_id
            ):
                raise QueueConflictError("SLURM recovery target identity conflicts")
            binding = (
                record,
                record.assignment.run_uri,
                record.assignment.stage_name,
                record.assignment.attempt,
                record.assignment.attempt_id,
            )
            _validate_recovery_request_identity(request, binding)
            return binding
        target = cast(ManagedRecoveryTarget, request.target)
        remote = self._managed_target_is_remote(request.assignment_id)
        assignment_agent_id = target.agent_id
        matches = [
            item
            for item in self.coordinator.retained_assignments(
                agent_id=assignment_agent_id
            )
            if item[0].assignment_id == request.assignment_id
            and item[0].session_id == target.session_id
        ]
        if len(matches) != 1:
            raise QueueConflictError("managed recovery target identity conflicts")
        assignment = matches[0][0]
        if remote:
            with sqlite3.connect(self.config.control_database) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT r.*, s.agent_id FROM remote_assignments r "
                    "JOIN agent_sessions s ON s.session_id = r.session_id "
                    "WHERE r.assignment_id = ?",
                    (request.assignment_id,),
                ).fetchone()
            if (
                row is None
                or str(row["agent_id"]) != target.agent_id
                or str(row["session_id"]) != target.session_id
                or row["fence"] != request.execution_fence
                or str(row["run_uri"]) != request.run_uri
                or str(row["stage_work_id"]) != request.stage_work_id
                or str(row["stage_name"]) != request.stage_name
                or int(row["attempt"]) != request.attempt
                or str(row["attempt_id"]) != assignment.attempt_id
                or self._remote_process_execution_id(request.assignment_id)
                != request.process_execution_id
            ):
                raise QueueConflictError("managed recovery target identity conflicts")
        elif (
            self.journal.read_grant_fence(request.assignment_id)
            != request.execution_fence
        ):
            raise QueueConflictError("managed recovery target identity conflicts")
        binding = (
            assignment,
            assignment.run_uri,
            assignment.stage_name,
            assignment.attempt,
            assignment.attempt_id,
        )
        _validate_recovery_request_identity(request, binding)
        return binding

    def _managed_target_is_remote(self, assignment_id: str) -> bool:
        with sqlite3.connect(self.config.control_database) as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM remote_assignments WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()
                is not None
            )

    def _remote_process_execution_id(self, assignment_id: str) -> str | None:
        with sqlite3.connect(self.config.execution_database) as conn:
            row = conn.execute(
                "SELECT payload_json FROM coordinator_events "
                "WHERE assignment_id = ? AND sequence = 1",
                (assignment_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        value = (
            payload.get("process_execution_id")
            if isinstance(payload, Mapping)
            else None
        )
        return value if isinstance(value, str) else None

    def _remote_result_is_complete(self, assignment_id: str) -> bool:
        with sqlite3.connect(self.config.control_database) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT report_json FROM remote_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None or row["report_json"] is None:
                return False
            report = _RemoteExecutionReport.from_dict(
                json.loads(str(row["report_json"]))
            )
            outputs = tuple(
                conn.execute(
                    "SELECT finalized FROM remote_transfers WHERE assignment_id = ? "
                    "AND direction = 'output'",
                    (assignment_id,),
                )
            )
        return len(outputs) == len(report.outputs) and all(
            bool(item["finalized"]) for item in outputs
        )

    def _remote_managed_recovery_evidence(
        self, request: RecoverUnknownAssignment
    ) -> tuple[str, Mapping[str, PlainData] | None]:
        operation_id = (
            "recover-remote-"
            + hashlib.sha256(
                f"{request.recovery_id}\0{request.assignment_id}".encode()
            ).hexdigest()
        )
        control = AgentAssignmentControl(
            operation_id=operation_id,
            session_id=cast(ManagedRecoveryTarget, request.target).session_id,
            assignment_id=request.assignment_id,
            fence=request.execution_fence,
            process_execution_id=request.process_execution_id,
        )
        encoded = json.dumps(control.value(), sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(self.config.control_database) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json, state, result_code, evidence_json "
                "FROM remote_assignment_controls WHERE assignment_id = ?",
                (request.assignment_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO remote_assignment_controls("
                    "operation_id, session_id, assignment_id, request_json, state, "
                    "result_code, evidence_json, acknowledged) "
                    "VALUES (?, ?, ?, ?, 'pending_delivery', NULL, NULL, 0)",
                    (
                        operation_id,
                        control.session_id,
                        control.assignment_id,
                        encoded,
                    ),
                )
                conn.commit()
                return "pending", None
            retained = AgentAssignmentControl.from_value(
                json.loads(str(row["request_json"]))
            )
            if (
                retained.session_id != control.session_id
                or retained.assignment_id != control.assignment_id
                or retained.fence != control.fence
                or retained.process_execution_id != control.process_execution_id
            ):
                conn.commit()
                return "unknown", None
            code = None if row["result_code"] is None else str(row["result_code"])
            raw_evidence = row["evidence_json"]
            conn.commit()
        if code is None:
            return "pending", None
        if code != "contained" or raw_evidence is None:
            return "unknown", None
        value = json.loads(str(raw_evidence))
        if not isinstance(value, Mapping):
            return "unknown", None
        try:
            evidence = _managed_containment_evidence(value)
        except QueueServiceError:
            return "unknown", None
        if not self._managed_evidence_matches(request, evidence):
            return "unknown", None
        return "contained", evidence

    def _launch_matches_recovery(
        self, request: RecoverUnknownAssignment, launch: object
    ) -> bool:
        target = cast(ManagedRecoveryTarget, request.target)
        return (
            getattr(launch, "assignment_id", None) == request.assignment_id
            and (
                self._managed_target_is_remote(request.assignment_id)
                or getattr(launch, "agent_id", None) == self.agent_id
            )
            and getattr(launch, "session_id", None) == target.session_id
            and getattr(launch, "process_execution_id", None)
            == request.process_execution_id
            and getattr(launch, "execution_fence", None) == request.execution_fence
        )

    @staticmethod
    def _managed_evidence_matches(
        request: RecoverUnknownAssignment, evidence: Mapping[str, PlainData]
    ) -> bool:
        target = cast(ManagedRecoveryTarget, request.target)
        return (
            evidence.get("agent_id") == target.agent_id
            and evidence.get("session_id") == target.session_id
            and evidence.get("assignment_id") == request.assignment_id
            and evidence.get("process_execution_id") == request.process_execution_id
            and evidence.get("execution_fence") == request.execution_fence
        )

    @staticmethod
    def _slurm_recovery_proof(
        request: RecoverUnknownAssignment,
        record: SlurmStageRecord,
        profile: SlurmReadyStageProfile,
    ) -> dict[str, PlainData]:
        helper = profile.containment_helper
        if helper is None:
            raise QueueServiceError("SLURM containment helper is unavailable")
        return {
            "assignment_id": record.assignment.assignment_id,
            "profile_id": record.assignment.profile_id,
            "profile_configuration_fingerprint": record.assignment.profile_configuration_fingerprint,
            "helper_descriptor": helper.descriptor,
            "submission_operation_id": record.assignment.operation_id,
            "cluster_id": cast(str, record.cluster),
            "job_id": cast(str, record.job_id),
            "bootstrap_incarnation_id": record.bootstrap_incarnation,
            "process_execution_id": request.process_execution_id,
            "execution_fence": request.execution_fence,
        }

    def _validate_persisted_recovery_evidence(
        self,
        request: RecoverUnknownAssignment,
        binding: tuple[object, str, str, int, str],
        evidence: Mapping[str, PlainData],
    ) -> None:
        if isinstance(request.target, SlurmRecoveryTarget):
            record = cast(SlurmStageRecord, binding[0])
            profile = self._slurm_profile(
                record.assignment.profile_id,
                record.assignment.profile_configuration_fingerprint,
            )
            proof = self._slurm_recovery_proof(request, record, profile)
            helper = profile.containment_helper
            if (
                set(evidence)
                != {
                    "kind",
                    "state",
                    "helper_descriptor",
                    "evidence_id",
                    "evidence_revision",
                    "echo",
                }
                or evidence.get("kind") != "slurm_helper"
                or evidence.get("state") != "CONTAINED"
                or helper is None
                or evidence.get("helper_descriptor") != helper.descriptor
                or evidence.get("echo") != proof
                or not isinstance(evidence.get("evidence_id"), str)
                or not isinstance(evidence.get("evidence_revision"), str)
            ):
                raise QueueConflictError("persisted SLURM recovery evidence conflicts")
            return
        try:
            managed = _managed_containment_evidence(evidence)
        except QueueServiceError as exc:
            raise QueueConflictError(
                "persisted managed recovery evidence conflicts"
            ) from exc
        if not self._managed_evidence_matches(request, managed):
            raise QueueConflictError("persisted managed recovery evidence conflicts")
        if not self._managed_target_is_remote(request.assignment_id):
            from ._managed_local import _launch_from_value

            raw = _ResidentAssignmentWorkspace(
                self.config.agent_root, request.assignment_id
            ).supervisor_launch_json()
            if raw is None:
                raise QueueConflictError(
                    "managed recovery launch evidence is unavailable"
                )
            launch = _launch_from_value(json.loads(raw))
            if (
                not self._launch_matches_recovery(request, launch)
                or managed.get("supervisor_id") != launch.supervisor_id
                or managed.get("supervisor_agent_id") != launch.agent_id
                or managed.get("continuity_epoch") != launch.continuity_epoch
                or managed.get("launch_operation_id") != launch.launch_operation_id
                or managed.get("launch_spec_digest") != launch.spec_digest
            ):
                raise QueueConflictError(
                    "persisted managed recovery evidence conflicts"
                )

    def _dispatch_slurm_ready(
        self,
        *,
        admission: LocalDaemonAdmission,
        intent: ManagedLocalIntent,
        authority: _ScopedCoordinatorAuthority,
        snapshot: AuthoritativeRunSnapshot,
        stage_work_id: str,
    ) -> LocalDaemonExecutionOutcome | None:
        records = tuple(
            sorted(
                (
                    record
                    for record in self.stage_work_store.list_stage_work()
                    if record.admission_id == admission.admission_id
                    and record.stage_work_id == stage_work_id
                    and record.scheduling_state is SchedulingProjectionState.READY
                    and record.placement.route.kind is ExecutionRouteKind.SLURM
                ),
                key=lambda item: (
                    item.ready_at,
                    item.ready_order,
                    item.stage_work_id,
                ),
            )
        )
        if not records:
            return None
        record = records[0]
        profile = self._slurm_profile(
            cast(str, record.placement.route.profile_id),
            cast(
                str,
                record.placement.route.profile_configuration_fingerprint,
            ),
        )
        operation_id = (
            "slurm-op-"
            + hashlib.sha256(
                (
                    admission.admission_id
                    + "\0"
                    + record.stage_work_id
                    + "\0"
                    + profile.configuration_fingerprint
                ).encode()
            ).hexdigest()
        )
        assignment_id = (
            "slurm-assignment-"
            + hashlib.sha256(
                (record.stage_work_id + "\0" + operation_id).encode()
            ).hexdigest()
        )
        try:
            request = map_ready_stage(
                placement=record.placement,
                profile=profile,
                operation_id=operation_id,
                stage_work_id=record.stage_work_id,
                run_uri=record.run_uri,
                attempt_id=record.attempt_id,
            )
            stage = intent.pipeline.get_stage(record.stage_name)
            stage_plan = next(
                item
                for item in intent.plan.ordered_stage_plans
                if item.stage_name == record.stage_name
            )
            raw_worker_request = self.run_store.read_stage_worker_request(
                record.run_uri,
                record.stage_name,
                attempt=record.attempt,
            )
            worker_request = (
                StageWorkerRequest.from_dict(raw_worker_request)
                if raw_worker_request is not None
                else prepare_stage_attempt(
                    run_store=self.run_store,
                    run_uri=record.run_uri,
                    stage=stage,
                    stage_plan=stage_plan,
                    produced_outputs=_produced_outputs(snapshot),
                    fingerprint_context=intent.plan.fingerprint_context,
                    resolved_runtime=intent.runtime[record.stage_name],
                )
            )
            if (
                worker_request.run_uri != record.run_uri
                or worker_request.stage_name != record.stage_name
                or worker_request.attempt != record.attempt
                or worker_request.executor_name != profile.executor_name
            ):
                raise QueueConflictError("SLURM worker preparation identity conflicts")
            assignment = SlurmStageAssignment(
                assignment_id=assignment_id,
                operation_id=operation_id,
                run_uri=record.run_uri,
                stage_work_id=record.stage_work_id,
                stage_name=record.stage_name,
                attempt=record.attempt,
                attempt_id=record.attempt_id,
                profile_id=profile.profile_id,
                profile_descriptor=profile.descriptor,
                profile_configuration_fingerprint=profile.configuration_fingerprint,
                request_digest=request.digest,
            )
            remote_inputs: list[_RemoteArtifact] = []
            input_paths: dict[str, Path] = {}
            total_bytes = 0
            for logical_name, ref in sorted(worker_request.inputs.items()):
                transfer_id = (
                    "input-"
                    + hashlib.sha256(
                        (
                            assignment.assignment_id
                            + "\0"
                            + logical_name
                            + "\0"
                            + ref.artifact_id
                        ).encode()
                    ).hexdigest()
                )
                descriptor, source = _RemoteArtifact.from_local_ref(
                    transfer_id=transfer_id,
                    logical_name=logical_name,
                    ref=ref,
                )
                total_bytes += descriptor.size_bytes
                if total_bytes > MAX_TRANSFER_BYTES:
                    raise QueueServiceError(
                        "SLURM assignment inputs exceed the configured bound"
                    )
                remote_inputs.append(descriptor)
                input_paths[transfer_id] = source
            delivery = SlurmStageDelivery.from_worker_request(
                assignment=assignment,
                worker_request=worker_request,
                project_fingerprint=profile.project_fingerprint,
                environment_fingerprint=profile.environment_fingerprint,
                executor_fingerprint=profile.executor_fingerprint,
                inputs=tuple(remote_inputs),
                declared_outputs=tuple(sorted(stage.outputs)),
            )
            script_path = self.config.slurm_script_root / f"{assignment_id}.sh"
            atomic_write_bytes(script_path, request.script.encode("utf-8"))
            script_path.chmod(0o600)
            self.slurm_assignments.reserve(
                assignment,
                request_json=request.to_dict(),
                delivery=delivery,
                input_paths=input_paths,
                issuer_epoch=self.coordinator_epoch,
                max_parallel_stages=intent.max_parallel_stages,
                max_profile_outstanding=profile.max_outstanding,
            )
            authority.bind_prepared_attempt(
                record.run_uri,
                assignment_id=assignment_id,
                attempt_id=record.attempt_id,
            )
            self.slurm_assignments.advance(
                assignment_id, expected="reserved", next_state="bound"
            )
            submission = self._submit_slurm_ready(
                assignment_id=assignment_id,
                request=request,
                profile=profile,
                script_path=script_path,
            )
            self.slurm_assignments.record_submission(
                assignment_id,
                state=submission.state.value,
                job_id=submission.job_id,
                cluster=submission.cluster,
            )
            if submission.state is ReadyStageState.REJECTED:
                authority.unbind_prepared_attempt(
                    record.run_uri,
                    assignment_id=assignment_id,
                    attempt_id=record.attempt_id,
                )
                self._release_slurm_assignment(assignment_id)
        except SlurmResourceMappingError:
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.WAITING,
                "slurm_route_unmappable",
            )
        except SlurmPlanningError as exc:
            diagnostic = str(exc)
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.WAITING,
                (
                    diagnostic
                    if diagnostic
                    in {
                        "slurm_profile_unavailable",
                        "slurm_profile_operation_discovery_unavailable",
                        "slurm_profile_changed",
                    }
                    else "slurm_route_unavailable_or_unmappable"
                ),
            )
        except (
            QueueConflictError,
            QueueServiceError,
            OSError,
            ValueError,
        ):
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.WAITING,
                "slurm_route_unavailable_or_unmappable",
            )
        return LocalDaemonExecutionOutcome(
            (
                LocalDaemonAdmissionState.WAITING
                if submission.state
                in {ReadyStageState.REJECTED, ReadyStageState.CONFLICT}
                else LocalDaemonAdmissionState.ACTIVE
            ),
            {
                ReadyStageState.REJECTED: "slurm_submission_rejected",
                ReadyStageState.CONFLICT: "slurm_submission_conflict",
                ReadyStageState.UNKNOWN: "slurm_submission_unknown",
            }.get(submission.state, "explicit SLURM assignment was submitted"),
        )

    def _slurm_profile(
        self, profile_id: str, configuration_fingerprint: str | None = None
    ) -> SlurmReadyStageProfile:
        profile = (
            self._scheduling.active_slurm_profiles.get(profile_id)
            if configuration_fingerprint is None
            else self._scheduling.retained_slurm_profiles.get(
                (profile_id, configuration_fingerprint)
            )
            or next(
                (
                    item
                    for item in self._scheduling.active_slurm_profiles.values()
                    if item.profile_id == profile_id
                    and item.configuration_fingerprint == configuration_fingerprint
                ),
                None,
            )
        )
        if profile is None:
            raise QueueConflictError("SLURM profile is not configured")
        return profile

    @contextmanager
    def scheduling_reload_guard(self) -> Iterator[None]:
        """Serialize replacement planning and swap with scheduling/start admission."""

        self._launch_lock.acquire()
        try:
            yield
        finally:
            self._launch_lock.release()

    def session_replacement_assignment_facts(
        self, session_id: str
    ) -> tuple[Mapping[str, PlainData], ...]:
        """Enumerate the complete coordinator assignment set for a session."""

        try:
            return self.coordinator.session_assignment_facts(session_id=session_id)
        except ManagedLocalError as exc:
            raise QueueConflictError(
                "old session coordinator inventory is unavailable"
            ) from exc

    def session_replacement_withheld_atoms(
        self,
        *,
        agent_id: str,
        atoms: Sequence[CapacityAtom],
        claim_ids: Sequence[str],
    ) -> tuple[CapacityAtom, ...]:
        """Project a fresh offer after exact old claims are withheld."""

        try:
            return self.coordinator.withhold_claims(
                agent_id=agent_id, atoms=atoms, claim_ids=claim_ids
            )
        except ManagedLocalError as exc:
            raise QueueConflictError(
                "replacement claim withholding is unavailable"
            ) from exc

    def validate_session_replacement_recovery(
        self, request: RecoverUnknownAssignment
    ) -> Mapping[str, PlainData]:
        """Recheck the exact Phase 9E containment and authority-close winner."""

        if not isinstance(request.target, ManagedRecoveryTarget):
            raise QueueConflictError(
                "session replacement requires managed recovery evidence"
            )
        binding = self._recovery_binding(request)
        _record, run_uri, stage_name, attempt, attempt_id = binding
        snapshot = SQLitePerRunAuthorityStore(run_uri).open_run(run_uri)
        matches = [
            item
            for stage in snapshot.stages
            if stage.stage_name == stage_name
            for item in stage.attempts
            if item.attempt == attempt and item.attempt_id == attempt_id
        ]
        if len(matches) != 1:
            raise QueueConflictError(
                "replacement authority assignment identity conflicts"
            )
        current = matches[0]
        expected_status = (
            StageStatus.FAILED
            if request.requested_outcome == "failed"
            else StageStatus.CANCELLED
        )
        detail = {} if current.reason is None else current.reason.detail
        if (
            current.status is not expected_status
            or current.reason is None
            or current.reason.code != "operator.recovery_close"
            or detail.get("recovery_id") != request.recovery_id
            or detail.get("assignment_id") != request.assignment_id
        ):
            raise QueueConflictError(
                "replacement recovery did not win the authority close"
            )
        return freeze_plain_data(
            {
                "recovery_id": request.recovery_id,
                "assignment_id": request.assignment_id,
                "attempt_id": attempt_id,
                "authority_revision": current.revision.sequence,
                "status": current.status.value,
            },
            path="session replacement authority fact",
        )

    def prepare_scheduling_reload(
        self,
        replacement: LocalDaemonConfig,
        scheduling_epoch: str,
    ) -> _CoordinatorSchedulingEpoch:
        """Build the complete replacement epoch before any durable mutation."""

        replacement_capacity = _coordinator_capacity(replacement)
        if replacement_capacity != self.capacity:
            raise QueueConflictError(
                "scheduling reload cannot reinterpret configured capacity"
            )
        replacement_planners = {
            item.resource_kind: item
            for item in replacement.scheduling_components.planners
        }
        for kind, provider in self.providers.items():
            planner = replacement_planners.get(kind)
            if (
                planner is None
                or not planner.claim_contracts
                or any(
                    contract not in provider.claim_contracts
                    for contract in planner.claim_contracts
                )
            ):
                raise QueueConflictError(
                    "scheduling reload planner is incompatible with the local provider"
                )
        runtime_placements = self._referenced_runtime_placements()
        retained: dict[tuple[str, str], SlurmReadyStageProfile] = {}
        for placement in runtime_placements:
            if placement.route.kind is not ExecutionRouteKind.SLURM:
                continue
            profile = self._slurm_profile(
                cast(str, placement.route.profile_id),
                cast(str, placement.route.profile_configuration_fingerprint),
            )
            retained[(profile.profile_id, profile.configuration_fingerprint)] = profile
        for record in self.slurm_assignments.list_unreleased():
            profile = self._slurm_profile(
                record.assignment.profile_id,
                record.assignment.profile_configuration_fingerprint,
            )
            retained[(profile.profile_id, profile.configuration_fingerprint)] = profile
        for submission in self.slurm_submissions.list_nonterminal():
            profile = self._slurm_profile(
                submission.request.profile_id,
                submission.request.profile_descriptor.configuration_fingerprint,
            )
            retained[(profile.profile_id, profile.configuration_fingerprint)] = profile
        active = {item.profile_id: item for item in replacement.slurm_profiles}
        if len(active) != len(replacement.slurm_profiles):
            raise QueueConflictError("replacement SLURM profile IDs conflict")
        active_credentials = {
            item.credential_reference: item for item in active.values()
        }
        active_by_key = {
            (item.profile_id, item.configuration_fingerprint): item
            for item in active.values()
        }
        for retained_profile in retained.values():
            same_identity = active_by_key.get(
                (
                    retained_profile.profile_id,
                    retained_profile.configuration_fingerprint,
                )
            )
            if same_identity is not None and same_identity is not retained_profile:
                raise QueueConflictError(
                    "scheduling reload would reinterpret a retained SLURM profile"
                )
            replacement_profile = active_credentials.get(
                retained_profile.credential_reference
            )
            if (
                replacement_profile is not None
                and replacement_profile.bootstrap_principal_id
                != retained_profile.bootstrap_principal_id
            ):
                raise QueueConflictError(
                    "scheduling reload cannot reinterpret a retained credential"
                )
        return _build_scheduling_epoch(
            epoch_id=scheduling_epoch,
            composition=replacement.scheduling_components,
            active_slurm_profiles=active,
            retained_slurm_profiles=retained,
            current=self._scheduling,
            referenced_descriptors=self._referenced_component_descriptors(
                runtime_placements
            ),
        )

    def apply_scheduling_reload(
        self,
        replacement: LocalDaemonConfig,
        plan: _CoordinatorSchedulingEpoch,
    ) -> None:
        """Install one already-validated scheduling plan without fallible work."""

        self._scheduling = plan
        self.config = replacement

    def _referenced_component_descriptors(
        self,
        runtime_placements: Sequence[ResolvedStagePlacement] = (),
    ) -> tuple[SchedulingComponentDescriptor, ...]:
        references: dict[
            tuple[str, int, str, str, str], SchedulingComponentDescriptor
        ] = {
            item.key: item
            for item in self.coordinator.retained_scheduling_descriptors()
        }
        for placement in runtime_placements:
            for descriptor in placement.planner_descriptors.values():
                references[descriptor.key] = descriptor
            for spec in placement.hard_constraints:
                if spec.descriptor is None:
                    raise QueueConflictError(
                        "referenced hard evaluator descriptor is unavailable"
                    )
                references[spec.descriptor.key] = spec.descriptor
            for spec in placement.preferences:
                if spec.descriptor is None:
                    raise QueueConflictError(
                        "referenced preference scorer descriptor is unavailable"
                    )
                references[spec.descriptor.key] = spec.descriptor
        snapshots: dict[str, AuthoritativeRunSnapshot] = {}
        terminal_runs = {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.INTERRUPTED,
        }
        active_attempts = {
            StageStatus.PENDING,
            StageStatus.SUBMITTED,
            StageStatus.RUNNING,
        }
        for record in self.stage_work_store.list_stage_work():
            snapshot = snapshots.get(record.run_uri)
            if snapshot is None:
                try:
                    snapshot = SQLitePerRunAuthorityStore(record.run_uri).open_run(
                        record.run_uri
                    )
                except Exception as exc:
                    raise QueueConflictError(
                        "referenced stage-work authority is unavailable"
                    ) from exc
                snapshots[record.run_uri] = snapshot
            if snapshot.status in terminal_runs:
                continue
            attempt = next(
                (
                    attempt
                    for stage in snapshot.stages
                    for attempt in stage.attempts
                    if attempt.attempt_id == record.attempt_id
                ),
                None,
            )
            if attempt is None:
                raise QueueConflictError(
                    "referenced stage work has no exact authority attempt"
                )
            if attempt.status not in active_attempts:
                continue
            for descriptor in record.placement.planner_descriptors.values():
                references[descriptor.key] = descriptor
            for spec in record.placement.hard_constraints:
                if spec.descriptor is None:
                    raise QueueConflictError(
                        "referenced hard evaluator descriptor is unavailable"
                    )
                references[spec.descriptor.key] = spec.descriptor
            for spec in record.placement.preferences:
                if spec.descriptor is None:
                    raise QueueConflictError(
                        "referenced preference scorer descriptor is unavailable"
                    )
                references[spec.descriptor.key] = spec.descriptor
        return tuple(sorted(references.values(), key=lambda item: item.key))

    def _referenced_runtime_placements(
        self,
    ) -> tuple[ResolvedStagePlacement, ...]:
        """Read exact placements pinned by accepted nonterminal admissions."""

        terminal = (
            LocalDaemonAdmissionState.SUCCEEDED.value,
            LocalDaemonAdmissionState.FAILED.value,
            LocalDaemonAdmissionState.CANCELLED.value,
            LocalDaemonAdmissionState.BLOCKED.value,
        )
        try:
            with sqlite3.connect(self.config.control_database) as conn:
                rows = tuple(
                    conn.execute(
                        "SELECT run_uri, intent_digest FROM managed_admissions "
                        "WHERE state NOT IN (?, ?, ?, ?) ORDER BY admission_id",
                        terminal,
                    )
                )
            placements: list[ResolvedStagePlacement] = []
            for run_uri, intent_digest in rows:
                record = load_managed_local_runtime_record(self.run_store, str(run_uri))
                if record.get("digest") != str(intent_digest):
                    raise QueueConflictError(
                        "accepted managed runtime intent changed after admission"
                    )
                raw_placements = record.get("placements")
                if not isinstance(raw_placements, Mapping):
                    raise QueueConflictError(
                        "accepted managed runtime placements are unavailable"
                    )
                placements.extend(
                    ResolvedStagePlacement.from_dict(value)
                    for _, value in sorted(raw_placements.items())
                )
            return tuple(placements)
        except QueueConflictError:
            raise
        except Exception as exc:
            raise QueueConflictError(
                "accepted managed runtime references are unavailable"
            ) from exc

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
        stage_facts = {stage.stage_name: stage for stage in snapshot.stages}
        facts = {name: stage.status for name, stage in stage_facts.items()}
        run_stages = {
            stage.stage_name
            for stage in plan.stage_plans
            if stage.action is PlanAction.RUN
        }
        terminal_failures = tuple(
            stage_facts[name]
            for name in run_stages
            if name in stage_facts
            and stage_facts[name].status is StageStatus.FAILED
            and not _current_attempt_retry_is_authorized(stage_facts[name])
            and not self._recovery_failure_is_settling(stage_facts[name])
        )
        if terminal_failures:
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

    def _recovery_failure_is_settling(self, stage: object) -> bool:
        reason = getattr(stage, "reason", None)
        if reason is None or getattr(reason, "code", None) != "operator.recovery_close":
            return False
        detail = getattr(reason, "detail", {})
        assignment_id = (
            detail.get("assignment_id") if isinstance(detail, Mapping) else None
        )
        daemon = self.daemon
        return (
            isinstance(assignment_id, str)
            and daemon is not None
            and daemon._recovery_is_settling(assignment_id)
        )

    def _cancel(
        self,
        admission: LocalDaemonAdmission,
        authority: _ScopedCoordinatorAuthority,
        stage_names: Sequence[str],
    ) -> LocalDaemonExecutionOutcome:
        operation_id = (
            admission.cancellation_operation_id
            or self.cancellation_operation(admission.admission_id)
        )
        if operation_id is None:
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.CANCELLATION_REQUESTED
            )
        # A terminal authority fact wins a late client request.  Installing a
        # cancellation epoch against it is neither needed nor generally a
        # valid authority mutation.
        before = authority.open_run(admission.run_uri)
        terminal = {
            RunStatus.SUCCEEDED: LocalDaemonAdmissionState.SUCCEEDED,
            RunStatus.FAILED: LocalDaemonAdmissionState.FAILED,
            RunStatus.INTERRUPTED: LocalDaemonAdmissionState.FAILED,
            RunStatus.CANCELLED: LocalDaemonAdmissionState.CANCELLED,
        }
        if before.status in terminal:
            return LocalDaemonExecutionOutcome(
                terminal[before.status], "authority_terminal_before_cancellation"
            )
        cancellation_request = CancellationEpochRequest(
            operation_id=operation_id,
            coordinator_id=self.coordinator_id,
            run_uri=admission.run_uri,
            stage_names=tuple(stage_names),
        )
        authority.install_cancellation_epoch(admission.run_uri, cancellation_request)
        # An effective epoch prevents a later bootstrap grant/start, but it is
        # not containment for a job which has already reached the external
        # scheduler.  Fan out only to the exact retained handles and retain
        # every other submission (including SUBMITTING-without-a-handle) for
        # reconciliation.  In particular, do not let a successful scancel
        # response turn the run terminal: it is merely a requested fact.
        settling = self._fan_out_slurm_cancellation(admission.run_uri)
        settling = (
            self._fan_out_local_cancellation(admission.run_uri, authority) or settling
        )
        settling = (
            self._fan_out_remote_cancellation(admission.run_uri, operation_id)
            or settling
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
        if settling:
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.CANCELLING,
                "cancellation epoch is installed; one or more owners are settling",
            )
        try:
            final_status = authority.finalize_cancellation(
                admission.run_uri, cancellation_request
            )
        except Exception:
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.CANCELLING,
                "cancellation epoch is installed; active or unknown work remains",
            )
        final = {
            RunStatus.SUCCEEDED: LocalDaemonAdmissionState.SUCCEEDED,
            RunStatus.FAILED: LocalDaemonAdmissionState.FAILED,
            RunStatus.INTERRUPTED: LocalDaemonAdmissionState.FAILED,
            RunStatus.CANCELLED: LocalDaemonAdmissionState.CANCELLED,
        }.get(final_status)
        if final is None:
            return LocalDaemonExecutionOutcome(
                LocalDaemonAdmissionState.CANCELLING,
                "cancellation finalization did not reach a terminal authority state",
            )
        return LocalDaemonExecutionOutcome(final)

    def _fan_out_local_cancellation(
        self, run_uri: str, authority: _ScopedCoordinatorAuthority
    ) -> bool:
        """Join coordinator and journal truth before allowing terminal cancellation.

        A reservation is releasable only when the journal has no request at all.
        Once the journal owns a request, it alone proves a pre-grant abort.  Any
        grant, launch, unknown state, or failed containment remains settling.
        """

        settling = False
        for assignment_id, coordinator_state in self.coordinator.list_run_live_states(
            run_uri
        ):
            journal_state = self.journal.find_state(assignment_id)
            if coordinator_state == "reserved" and journal_state is None:
                self.coordinator.cancellation_release_unstarted(assignment_id)
                continue
            if coordinator_state not in {"bound", "accepted"}:
                settling = True
                continue
            if journal_state is None:
                authority.unbind_prepared_attempt(
                    run_uri,
                    assignment_id=assignment_id,
                    attempt_id=self._attempt_id(assignment_id),
                )
                self.coordinator.cancellation_release_pregrant(assignment_id)
                continue
            if journal_state in {
                AssignmentState.REQUEST_DURABLE,
                AssignmentState.PREPARED,
                AssignmentState.ACCEPTED,
                AssignmentState.DECLINED,
            }:
                try:
                    self.journal.cancel_pregrant(assignment_id, self.providers)
                    authority.unbind_prepared_attempt(
                        run_uri,
                        assignment_id=assignment_id,
                        attempt_id=self._attempt_id(assignment_id),
                    )
                    self.coordinator.cancellation_release_pregrant(assignment_id)
                except Exception:
                    settling = True
                continue
            settling = True
        return settling

    def _attempt_id(self, assignment_id: str) -> str:
        """Read the immutable authority attempt identity from the coordinator owner."""

        with sqlite3.connect(self.coordinator.path) as conn:
            row = conn.execute(
                "SELECT identity_json FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        if row is None:
            raise QueueConflictError("local cancellation assignment is unavailable")
        value = json.loads(cast(str, row[0]))
        attempt_id = value.get("attempt_id") if isinstance(value, dict) else None
        if not isinstance(attempt_id, str) or not attempt_id:
            raise QueueConflictError("local cancellation attempt identity is invalid")
        return attempt_id

    def _fan_out_slurm_cancellation(self, run_uri: str) -> bool:
        """Reconcile cancellation and release for exact SLURM ownership.

        A missing handle after durable submission is unknown work, and a
        rejected or unavailable external request is still settling work. A
        terminal or logically released assignment is settled only after its
        exact protected-provider release succeeds.
        """

        settling = False
        for record in self.slurm_assignments.list_run_unreleased(run_uri):
            if record.state == "released":
                continue
            submission = self.slurm_submissions.find(record.assignment.operation_id)
            if record.state in {"terminal", "logical_released", "rejected"}:
                try:
                    if record.state == "rejected":
                        self._remote_authority(run_uri).unbind_prepared_attempt(
                            run_uri,
                            assignment_id=record.assignment.assignment_id,
                            attempt_id=record.assignment.attempt_id,
                        )
                    if submission is None:
                        if record.state == "rejected":
                            self.slurm_assignments.advance(
                                record.assignment.assignment_id,
                                expected="rejected",
                                next_state="logical_released",
                            )
                        self.slurm_assignments.release(record.assignment.assignment_id)
                    else:
                        self._release_slurm_assignment(record.assignment.assignment_id)
                except Exception:
                    # Logical release is not physical provider settlement. Keep
                    # cancellation open until exact revocation/release replays.
                    settling = True
                continue
            if record.state == "bound" and (
                submission is None or submission.state is ReadyStageState.INTENT
            ):
                authority = self._remote_authority(run_uri)
                if submission is not None:
                    self.slurm_submissions.suppress_before_submit(
                        record.assignment.operation_id
                    )
                self.slurm_assignments.record_submission(
                    record.assignment.assignment_id,
                    state=ReadyStageState.REJECTED.value,
                    job_id=None,
                    cluster=None,
                )
                authority.unbind_prepared_attempt(
                    run_uri,
                    assignment_id=record.assignment.assignment_id,
                    attempt_id=record.assignment.attempt_id,
                )
                if submission is None:
                    self.slurm_assignments.advance(
                        record.assignment.assignment_id,
                        expected="rejected",
                        next_state="logical_released",
                    )
                    self.slurm_assignments.release(record.assignment.assignment_id)
                else:
                    self._release_slurm_assignment(record.assignment.assignment_id)
                continue
            if submission is None or submission.job_id is None:
                # Before an exact handle exists, suppression/reconciliation is
                # the only truthful action.  The authority epoch blocks grant
                # and start while this durable reference remains retained.
                settling = True
                continue
            try:
                profile = self._slurm_profile(
                    record.assignment.profile_id,
                    record.assignment.profile_configuration_fingerprint,
                )
                self.slurm_submissions.request_cancel(
                    record.assignment.operation_id, profile
                )
            except (QueueConflictError, SlurmPlanningError):
                # A retained binding that cannot currently perform its exact
                # cancellation stays visible and bound; no inference is safe.
                settling = True
                continue
            # Even a positive scancel response is not containment evidence.
            settling = True
        return settling

    def _fan_out_remote_cancellation(
        self, run_uri: str, cancellation_operation_id: str
    ) -> bool:
        """Retain exact per-assignment controls until each remote owner settles."""

        from .agent_sessions import AgentAssignmentControl

        settling = False
        with sqlite3.connect(self.config.control_database) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            if (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'remote_assignments'"
                ).fetchone()
                is None
            ):
                conn.commit()
                return False
            rows = tuple(
                conn.execute(
                    "SELECT assignment_id, session_id, state, fence "
                    "FROM remote_assignments WHERE run_uri = ? "
                    "AND state != 'RELEASED' ORDER BY assignment_id",
                    (run_uri,),
                )
            )
            for row in rows:
                settling = True
                assignment_id = str(row["assignment_id"])
                operation_id = (
                    "cancel-remote-"
                    + hashlib.sha256(
                        f"{cancellation_operation_id}\0{assignment_id}".encode()
                    ).hexdigest()
                )
                control = AgentAssignmentControl(
                    operation_id=operation_id,
                    session_id=str(row["session_id"]),
                    assignment_id=assignment_id,
                    fence=None if row["fence"] is None else str(row["fence"]),
                    process_execution_id=(
                        f"{assignment_id}:root"
                        if str(row["state"])
                        in {"RUNNING", "RESULT_RETAINED", "TERMINAL"}
                        else None
                    ),
                )
                encoded = json.dumps(
                    control.value(), sort_keys=True, separators=(",", ":")
                )
                prior = conn.execute(
                    "SELECT request_json, state FROM remote_assignment_controls "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()
                if prior is None:
                    conn.execute(
                        "INSERT INTO remote_assignment_controls("
                        "operation_id, session_id, assignment_id, request_json, "
                        "state, result_code, acknowledged) "
                        "VALUES (?, ?, ?, ?, 'pending_delivery', NULL, 0)",
                        (
                            operation_id,
                            control.session_id,
                            assignment_id,
                            encoded,
                        ),
                    )
                else:
                    retained = AgentAssignmentControl.from_value(
                        json.loads(str(prior["request_json"]))
                    )
                    if (
                        retained.session_id != control.session_id
                        or retained.assignment_id != control.assignment_id
                        or retained.fence != control.fence
                        or (
                            retained.process_execution_id is not None
                            and control.process_execution_id is not None
                            and retained.process_execution_id
                            != control.process_execution_id
                        )
                    ):
                        raise QueueConflictError(
                            "remote cancellation operation conflicts"
                        )
            conn.commit()
        return settling

    def _candidate(self) -> Candidate:
        inventory: dict[str, ResourceInventoryEnvelope] = {}
        availability: dict[str, ResourceAvailabilityEnvelope] = {}
        for kind, provider in self.providers.items():
            observed = provider.observe(
                ObserveRequest(
                    self.config.machine_id,
                    self.coordinator_epoch,
                    f"candidate-observe-{kind}-{utc_timestamp()}",
                )
            )
            data: Mapping[str, PlainData] = {}
            if kind == "gpu":
                data = cast(
                    Mapping[str, PlainData],
                    {
                        "devices": [
                            device.descriptor.to_dict(
                                device_id=(
                                    f"{self.config.machine_id}:"
                                    f"{device.descriptor.device_id}"
                                )
                            )
                            for device in self.config.gpu_devices
                        ]
                    },
                )
            inventory[kind] = ResourceInventoryEnvelope(
                self.config.machine_id,
                kind,
                observed.availability_revision,
                data=data,
                atoms=tuple(
                    atom
                    for atom in self.local_capacity
                    if atom.owner_resource_kind == kind
                ),
            )
            availability[kind] = ResourceAvailabilityEnvelope(
                self.config.machine_id,
                kind,
                observed.availability_revision,
                data=data,
                atoms=observed.atoms,
            )
        return Candidate(
            self.config.machine_id,
            inventory,
            availability,
        )

    def _remote_candidates(
        self,
    ) -> dict[str, tuple[Candidate, _RemoteCandidateTarget]]:
        if not self.config.remote_profiles:
            return {}
        configured = {
            profile.profile_id: profile for profile in self.config.remote_profiles
        }
        with sqlite3.connect(self.config.control_database) as conn:
            conn.row_factory = sqlite3.Row
            rows = tuple(
                conn.execute(
                    "SELECT o.offer_id, o.offer_json, o.expires_at, "
                    "s.agent_id, s.session_id, r.observed_claim_ids_json "
                    "FROM agent_offers o "
                    "JOIN agent_sessions s ON s.session_id = o.session_id "
                    "LEFT JOIN session_replacements r "
                    "ON r.successor_session_id = s.session_id "
                    "AND r.readiness = 'ready' "
                    "WHERE o.current = 1 AND o.coordinator_epoch = ? "
                    "AND s.state = 'ACTIVE' AND s.coordinator_epoch = ?",
                    (self.coordinator_epoch, self.coordinator_epoch),
                )
            )
            accepted_row = conn.execute(
                "SELECT value FROM daemon_metadata WHERE key = 'accepted_time'"
            ).fetchone()
            accepted_time = "" if accepted_row is None else str(accepted_row[0])
        targets: dict[str, tuple[Candidate, _RemoteCandidateTarget]] = {}
        for row in rows:
            if accepted_time and str(row["expires_at"]) < accepted_time:
                continue
            offer = AgentOffer.from_value(json.loads(str(row["offer_json"])))
            matching = tuple(
                profile
                for profile in offer.resident_profiles
                if configured.get(profile.profile_id) == profile
            )
            if not matching:
                continue
            agent_id = str(row["agent_id"])
            detailed_atoms = [
                CapacityAtom(
                    atom.owner_resource_kind,
                    f"{agent_id}:{atom.local_capacity_key}",
                    atom.amount,
                    "B" if atom.owner_resource_kind == "memory" else atom.unit,
                    atom.granularity,
                )
                for atom in offer.capacity_atoms
            ]
            availability_atoms = [
                atom
                for atom in detailed_atoms
                if atom.owner_resource_kind not in {"cpu", "memory"}
            ]
            if offer.cpu:
                availability_atoms.append(
                    CapacityAtom(
                        "cpu",
                        f"{agent_id}:cpu",
                        ExactQuantity(offer.cpu),
                        "count",
                        ExactQuantity(1),
                    )
                )
            if offer.memory_bytes:
                availability_atoms.append(
                    CapacityAtom(
                        "memory",
                        f"{agent_id}:memory",
                        ExactQuantity(offer.memory_bytes),
                        "B",
                        ExactQuantity(1),
                    )
                )
            inventory_atoms = [
                atom for atom in availability_atoms if atom.owner_resource_kind != "gpu"
            ]
            inventory_atoms.extend(
                device.capacity_atom(f"{agent_id}:{device.device_id}")
                for device in offer.gpu_devices
            )
            raw_withheld_claim_ids = row["observed_claim_ids_json"]
            if raw_withheld_claim_ids is None:
                withheld_claim_ids: tuple[str, ...] = ()
                scheduling_offer_id = str(row["offer_id"])
                scheduling_availability_revision = offer.availability_revision
            else:
                try:
                    decoded_claim_ids = json.loads(str(raw_withheld_claim_ids))
                except json.JSONDecodeError as exc:
                    raise QueueConflictError(
                        "replacement claim inventory is invalid"
                    ) from exc
                if (
                    not isinstance(decoded_claim_ids, list)
                    or any(not isinstance(item, str) for item in decoded_claim_ids)
                    or len(set(decoded_claim_ids)) != len(decoded_claim_ids)
                ):
                    raise QueueConflictError("replacement claim inventory is invalid")
                withheld_claim_ids = tuple(sorted(decoded_claim_ids))
                availability_atoms = list(
                    self.session_replacement_withheld_atoms(
                        agent_id=agent_id,
                        atoms=availability_atoms,
                        claim_ids=withheld_claim_ids,
                    )
                )
                (
                    scheduling_offer_id,
                    scheduling_availability_revision,
                ) = _replacement_scheduling_identities(
                    offer_id=str(row["offer_id"]),
                    availability_revision=offer.availability_revision,
                    withheld_claim_ids=withheld_claim_ids,
                )
            inventory: dict[str, ResourceInventoryEnvelope] = {}
            availability: dict[str, ResourceAvailabilityEnvelope] = {}
            for kind in {atom.owner_resource_kind for atom in inventory_atoms}:
                kind_inventory_atoms = tuple(
                    atom for atom in inventory_atoms if atom.owner_resource_kind == kind
                )
                kind_availability_atoms = tuple(
                    atom
                    for atom in availability_atoms
                    if atom.owner_resource_kind == kind
                )
                data: Mapping[str, PlainData] = {}
                if kind == "gpu":
                    data = cast(
                        Mapping[str, PlainData],
                        {
                            "devices": [
                                device.to_dict(
                                    device_id=f"{agent_id}:{device.device_id}"
                                )
                                for device in offer.gpu_devices
                            ]
                        },
                    )
                inventory[kind] = ResourceInventoryEnvelope(
                    agent_id,
                    kind,
                    offer.availability_revision,
                    data=data,
                    atoms=kind_inventory_atoms,
                )
                availability[kind] = ResourceAvailabilityEnvelope(
                    agent_id,
                    kind,
                    scheduling_availability_revision,
                    data=data,
                    atoms=kind_availability_atoms,
                )
            for profile in sorted(matching, key=lambda item: item.profile_id):
                candidate_id = ":".join(
                    (agent_id, str(row["session_id"]), profile.profile_id)
                )
                candidate = Candidate(
                    candidate_id,
                    {
                        kind: replace(envelope, candidate_id=candidate_id)
                        for kind, envelope in inventory.items()
                    },
                    {
                        kind: replace(envelope, candidate_id=candidate_id)
                        for kind, envelope in availability.items()
                    },
                    attributes={
                        "agent_id": agent_id,
                        "target": agent_id,
                        "resident_profile_id": profile.profile_id,
                        "resident_profile_revision": profile.revision,
                        "resident_profile_fingerprint": profile.fingerprint,
                        "resident_project_fingerprint": profile.project_fingerprint,
                        "resident_environment_fingerprint": profile.environment_fingerprint,
                        "resident_executor_fingerprint": profile.executor_fingerprint,
                        "artifact_capability": "regular-file-relay-v1",
                    },
                    pool_names=offer.pools,
                )
                targets[candidate_id] = (
                    candidate,
                    _RemoteCandidateTarget(
                        agent_id=agent_id,
                        session_id=str(row["session_id"]),
                        offer_id=scheduling_offer_id,
                        availability_revision=offer.availability_revision,
                        scheduling_availability_revision=scheduling_availability_revision,
                        inventory_revision=offer.inventory_revision,
                        offer=offer,
                        profile=profile,
                        availability_atoms=tuple(availability_atoms),
                        reflected_claim_ids=tuple(
                            sorted(
                                set(offer.reflected_claim_ids) | set(withheld_claim_ids)
                            )
                        ),
                    ),
                )
        return targets

    def validate_agent_offer_provider_composition(self, offer: AgentOffer) -> None:
        """Validate each advertised physical provider against its own planner."""

        planners = self._scheduling.active_planners()
        for provider in offer.provider_composition:
            kind = provider.descriptor.kind
            planner = planners.get(kind)
            if planner is None:
                raise QueueServiceError(
                    f"agent resource provider has no active planner for {kind!r}"
                )
            if not set(provider.claim_contracts).intersection(planner.claim_contracts):
                raise QueueServiceError(
                    "agent resource provider has no claim-contract intersection "
                    f"for {kind!r}"
                )

    @staticmethod
    def _remote_eligible(
        *,
        intent: ManagedLocalIntent,
        snapshot: AuthoritativeRunSnapshot,
        record: StageWorkRecord,
    ) -> bool:
        """Preflight the selected remote pair before any durable assignment."""

        stage = intent.pipeline.get_stage(record.stage_name)
        stage_plan = next(
            item
            for item in intent.plan.ordered_stage_plans
            if item.stage_name == record.stage_name
        )
        inputs = bind_stage_inputs(
            stage=stage,
            stage_plan=stage_plan,
            produced_outputs=_produced_outputs(snapshot),
        )
        fingerprint = build_stage_fingerprint(
            stage,
            bound_inputs=inputs,
            fingerprint_context=intent.plan.fingerprint_context,
        ).to_dict()
        try:
            _validate_remote_semantic_data(
                fingerprint=fingerprint,
                resolved_runtime=intent.runtime[record.stage_name].to_safe_metadata(),
                worker_metadata={},
            )
            total_bytes = 0
            for index, (logical_name, ref) in enumerate(sorted(inputs.items())):
                descriptor, _path = _RemoteArtifact.from_local_ref(
                    transfer_id=f"preflight-{index}",
                    logical_name=logical_name,
                    ref=ref,
                )
                total_bytes += descriptor.size_bytes
                if total_bytes > MAX_TRANSFER_BYTES:
                    return False
        except (OSError, QueueConflictError, QueueServiceError):
            return False
        return True

    def _execute(
        self,
        *,
        admission: LocalDaemonAdmission,
        intent: ManagedLocalIntent,
        authority: _ScopedCoordinatorAuthority,
        snapshot: AuthoritativeRunSnapshot,
        record: StageWorkRecord,
        decision: object,
        remote_targets: Mapping[str, _RemoteCandidateTarget],
        decision_as_of: str,
        execution_started: Callable[[], None],
    ) -> bool:
        selected = getattr(decision, "selected")
        claims = tuple(selected.claims)
        if not claims or len({claim.resource_kind for claim in claims}) != len(claims):
            raise QueueServiceError(
                "managed daemon requires one exact claim per resource kind"
            )
        candidate_id = cast(str, getattr(decision, "candidate_id"))
        remote_target = remote_targets.get(candidate_id)
        offer_id = (
            remote_target.offer_id
            if remote_target is not None
            else f"offer-{record.stage_work_id}-{record.projection_revision}"
        )
        assignment_id = (
            "assignment-"
            + hashlib.sha256(
                (
                    admission.admission_id
                    + "\0"
                    + record.stage_work_id
                    + "\0"
                    + offer_id
                    + "\0"
                    + str(record.projection_revision)
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
            agent_id=(
                remote_target.agent_id
                if remote_target is not None
                else self.config.machine_id
            ),
            session_id=(
                remote_target.session_id
                if remote_target is not None
                else self.coordinator_epoch
            ),
            offer_id=offer_id,
            claim_id=claim_id,
        )
        decision_planners = self._scheduling.planners_for_record(record)
        if remote_target is None:
            observations = {
                kind: provider.observe(
                    ObserveRequest(
                        self.config.machine_id,
                        self.coordinator_epoch,
                        f"offer-observe-{assignment_id}-{kind}",
                    )
                )
                for kind, provider in self.providers.items()
            }
            availability_revision = (
                "local-"
                + hashlib.sha256(
                    "\0".join(
                        observations[kind].availability_revision
                        for kind in sorted(observations)
                    ).encode()
                ).hexdigest()
            )
            provider_descriptors = {
                kind: provider.descriptor for kind, provider in self.providers.items()
            }
            offer_snapshot = ManagedOfferSnapshot(
                agent_id=self.config.machine_id,
                session_id=self.coordinator_epoch,
                offer_revision=offer_id,
                snapshot_revision=self.coordinator_epoch,
                inventory_revision=f"inventory-{self.coordinator_epoch}",
                availability_revision=availability_revision,
                component_descriptors=tuple(
                    decision_planners[kind].descriptor
                    for kind in sorted(provider_descriptors)
                ),
                provider_descriptors=tuple(
                    provider_descriptors[kind] for kind in sorted(provider_descriptors)
                ),
                atoms=tuple(
                    atom
                    for kind in sorted(observations)
                    for atom in observations[kind].atoms
                ),
                reflected_claim_ids=tuple(
                    sorted(
                        {
                            live_claim_id
                            for result in observations.values()
                            for live_claim_id in result.live_claim_ids
                        }
                    )
                ),
            )
        else:
            provider_descriptors = {
                descriptor.kind: descriptor
                for descriptor in remote_target.offer.provider_descriptors
            }
            offer_snapshot = ManagedOfferSnapshot(
                agent_id=remote_target.agent_id,
                session_id=remote_target.session_id,
                offer_revision=remote_target.offer_id,
                snapshot_revision=(remote_target.scheduling_availability_revision),
                inventory_revision=remote_target.inventory_revision,
                availability_revision=(remote_target.scheduling_availability_revision),
                component_descriptors=tuple(
                    decision_planners[kind].descriptor
                    for kind in sorted(provider_descriptors)
                ),
                provider_descriptors=tuple(
                    provider_descriptors[kind] for kind in sorted(provider_descriptors)
                ),
                atoms=remote_target.availability_atoms,
                reflected_claim_ids=remote_target.reflected_claim_ids,
            )
        self.coordinator.publish_offer(offer_snapshot)
        stage = intent.pipeline.get_stage(record.stage_name)
        stage_plan = next(
            item
            for item in intent.plan.ordered_stage_plans
            if item.stage_name == record.stage_name
        )
        produced = _produced_outputs(snapshot)
        runtime = intent.runtime[record.stage_name]
        raw_worker_request = self.run_store.read_stage_worker_request(
            record.run_uri,
            record.stage_name,
            attempt=record.attempt,
        )
        worker_request = (
            StageWorkerRequest.from_dict(raw_worker_request)
            if raw_worker_request is not None
            else prepare_stage_attempt(
                run_store=self.run_store,
                run_uri=record.run_uri,
                stage=stage,
                stage_plan=stage_plan,
                produced_outputs=produced,
                fingerprint_context=intent.plan.fingerprint_context,
                resolved_runtime=runtime,
            )
        )
        if (
            worker_request.run_uri != record.run_uri
            or worker_request.stage_name != record.stage_name
            or worker_request.attempt != record.attempt
        ):
            raise QueueConflictError(
                "managed worker preparation identity differs from authority attempt"
            )
        snapshot_revision = (
            remote_target.scheduling_availability_revision
            if remote_target is not None
            else self.coordinator_epoch
        )
        decision_receipt: dict[str, PlainData] = {
            "policy_epoch": getattr(decision, "component_epoch"),
            "policy_descriptor": getattr(decision, "policy_descriptor").to_dict(),
            "stage_work_id": record.stage_work_id,
            "candidate_id": assignment.agent_id,
            "stage_work_revision": record.projection_revision,
            "snapshot_revision": snapshot_revision,
            "offer_revision": offer_id,
            "score_summary": {"preference_vector": list(selected.preference_vector)},
            "fallback_eligible": selected.fallback_eligible,
            "as_of": decision_as_of,
            "reason_codes": ["selected"],
            "component_descriptors": [
                decision_planners[kind].descriptor.to_dict()
                for kind in sorted(claim.resource_kind for claim in claims)
            ],
            "provider_descriptors": [
                provider_descriptors[kind].to_dict()
                for kind in sorted(claim.resource_kind for claim in claims)
            ],
            "claim_contract_descriptors": [
                descriptor.to_dict()
                for descriptor in sorted(
                    {claim.contract for claim in claims},
                    key=lambda item: item.key,
                )
            ],
        }
        if remote_target is not None:
            remote_inputs: list[_RemoteArtifact] = []
            input_paths: dict[str, Path] = {}
            total_bytes = 0
            for logical_name, ref in sorted(worker_request.inputs.items()):
                transfer_id = (
                    "input-"
                    + hashlib.sha256(
                        (
                            assignment.assignment_id
                            + "\0"
                            + logical_name
                            + "\0"
                            + ref.artifact_id
                        ).encode("utf-8")
                    ).hexdigest()
                )
                descriptor, path = _RemoteArtifact.from_local_ref(
                    transfer_id=transfer_id,
                    logical_name=logical_name,
                    ref=ref,
                )
                total_bytes += descriptor.size_bytes
                if total_bytes > MAX_TRANSFER_BYTES:
                    raise QueueServiceError(
                        "remote assignment inputs exceed the configured bound"
                    )
                remote_inputs.append(descriptor)
                input_paths[transfer_id] = path
            delivered = _ResidentAssignmentBundle.from_worker_request(
                assignment_id=assignment.assignment_id,
                stage_work_id=assignment.stage_work_id,
                attempt_id=assignment.attempt_id,
                offer_id=assignment.offer_id,
                claim_id=assignment.claim_id,
                worker_request=worker_request,
                profile=remote_target.profile,
                inputs=tuple(remote_inputs),
                declared_outputs=tuple(sorted(stage.outputs)),
                claims=claims,
                provider_descriptors=tuple(
                    provider_descriptors[claim.resource_kind] for claim in claims
                ),
            )
            self.coordinator.reserve(
                assignment,
                claims,
                max_parallel_stages=intent.max_parallel_stages,
                decision_receipt=decision_receipt,
            )
            authority.bind_prepared_attempt(
                assignment.run_uri,
                assignment_id=assignment.assignment_id,
                attempt_id=assignment.attempt_id,
            )
            self.coordinator.advance(
                assignment.assignment_id,
                expected="reserved",
                next_state="bound",
            )
            try:
                _target_remote_delivery(
                    self._daemon_owner(),
                    session_id=remote_target.session_id,
                    availability_revision=remote_target.availability_revision,
                    request=delivered,
                    run_uri=assignment.run_uri,
                    input_paths=input_paths,
                )
            except (QueueConflictError, QueueServiceError):
                if self._remote_delivery_retained(assignment.assignment_id):
                    execution_started()
                    return True
                authority.unbind_prepared_attempt(
                    assignment.run_uri,
                    assignment_id=assignment.assignment_id,
                    attempt_id=assignment.attempt_id,
                )
                self.coordinator.release_unaccepted(
                    assignment.assignment_id,
                    reopen_offer=True,
                )
                return False
            execution_started()
            return True
        accepted = Event()

        def started() -> None:
            execution_started()
            accepted.set()

        def observe_and_finalize() -> None:
            run_managed_local_assignment(
                coordinator=self.coordinator,
                authority=authority,
                journal=self.journal,
                assignment=assignment,
                worker_request=worker_request,
                claims=claims,
                providers=self.providers,
                run_store=self.run_store,
                max_parallel_stages=intent.max_parallel_stages,
                decision_receipt=decision_receipt,
                agent_root=self.config.agent_root,
                supervisor=self.supervisor,
                resident_launch_profile=self.config.resident_worker_launch_profile,
                cancellation_requested=lambda: self._install_cancellation_if_requested(
                    admission, authority, intent.plan.stage_order
                ),
                suspend_requested=(
                    None if self.daemon is None else self.daemon._stop.is_set
                ),
                execution_started=started,
            )

        prior = self._local_assignment_futures.get(assignment.assignment_id)
        if prior is None:
            prior = self._local_assignment_workers.submit(observe_and_finalize)
            daemon = self.daemon
            if daemon is not None:
                prior.add_done_callback(lambda _future: daemon._wake.set())
            self._local_assignment_futures[assignment.assignment_id] = prior
        while not accepted.wait(timeout=0.01):
            if prior.done():
                # Preserve the existing saga failure semantics; an unaccepted
                # launch is never reported as a background start.
                prior.result()
        return True

    def _remote_delivery_retained(self, assignment_id: str) -> bool:
        with sqlite3.connect(self.config.control_database) as conn:
            row = conn.execute(
                "SELECT 1 FROM remote_assignments r JOIN agent_deliveries d "
                "ON d.assignment_id = r.assignment_id "
                "WHERE r.assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        return row is not None

    def _install_cancellation_if_requested(
        self,
        admission: LocalDaemonAdmission,
        authority: _ScopedCoordinatorAuthority,
        stage_names: Sequence[str],
    ) -> bool:
        return self._install_run_cancellation_if_requested(
            admission.run_uri, authority, stage_names
        )

    def _install_run_cancellation_if_requested(
        self,
        run_uri: str,
        authority: _ScopedCoordinatorAuthority,
        stage_names: Sequence[str],
    ) -> bool:
        operation_id = self._run_cancellation_operation(run_uri)
        if operation_id is None:
            return False
        authority.install_cancellation_epoch(
            run_uri,
            CancellationEpochRequest(
                operation_id=operation_id,
                coordinator_id=self.coordinator_id,
                run_uri=run_uri,
                stage_names=tuple(stage_names),
            ),
        )
        return True

    def _daemon_owner(self) -> LocalDaemon:
        if self.daemon is None:
            raise QueueServiceError("remote coordinator owner is unavailable")
        return self.daemon

    def remote_accept(self, assignment_id: str) -> str:
        """Advance one delivered, input-durable assignment through grant."""

        record = self._remote_assignment_record(assignment_id)
        authority = self._remote_authority(str(record["run_uri"]))
        state = self.coordinator.state(assignment_id)
        if state == "bound":
            self.coordinator.advance(
                assignment_id, expected="bound", next_state="accepted"
            )
        fence = authority.grant_prepared_attempt(
            str(record["run_uri"]),
            assignment_id=assignment_id,
            attempt_id=str(record["attempt_id"]),
        )
        state = self.coordinator.state(assignment_id)
        if state == "accepted":
            self.coordinator.advance(
                assignment_id, expected="accepted", next_state="granted"
            )
        return fence.fencing_token

    def remote_start_permit(self, assignment_id: str, *, fence: str) -> bool:
        """Fail closed when the exact run cancellation barrier is effective."""

        record = self._remote_assignment_record(assignment_id)
        authority = self._remote_authority(str(record["run_uri"]))
        operation_id = self._run_cancellation_operation(str(record["run_uri"]))
        if (
            operation_id is not None
            and authority.read_cancellation_epoch_receipt(
                str(record["run_uri"]), operation_id
            )
            is not None
        ):
            return False
        granted = authority.grant_prepared_attempt(
            str(record["run_uri"]),
            assignment_id=assignment_id,
            attempt_id=str(record["attempt_id"]),
        )
        if granted.fencing_token != fence:
            raise QueueConflictError("remote start permit fence conflicts")
        return True

    def remote_decline(self, assignment_id: str) -> None:
        """Release a pre-grant assignment after definitive physical decline."""

        record = self._remote_assignment_record(assignment_id)
        authority = self._remote_authority(str(record["run_uri"]))
        state = self.coordinator.state(assignment_id)
        if state == "released":
            return
        if state != "bound":
            raise QueueConflictError("only a bound remote assignment can be declined")
        authority.unbind_prepared_attempt(
            str(record["run_uri"]),
            assignment_id=assignment_id,
            attempt_id=str(record["attempt_id"]),
        )
        self.coordinator.release_unaccepted(assignment_id)

    def remote_started(
        self, assignment_id: str, *, fence: str, process_execution_id: str
    ) -> None:
        record = self._remote_assignment_record(assignment_id)
        authority = self._remote_authority(str(record["run_uri"]))
        granted = authority.grant_prepared_attempt(
            str(record["run_uri"]),
            assignment_id=assignment_id,
            attempt_id=str(record["attempt_id"]),
        )
        if granted.fencing_token != fence:
            raise QueueConflictError("remote execution fence conflicts")
        authority.confirm_execution_started(str(record["run_uri"]), fence=granted)
        state = self.coordinator.state(assignment_id)
        if state == "granted":
            self.coordinator.advance(
                assignment_id, expected="granted", next_state="running"
            )
        self.coordinator.record_event(
            assignment_id,
            1,
            f"{assignment_id}:process-started",
            {"process_execution_id": process_execution_id},
        )

    def remote_event(
        self,
        assignment_id: str,
        *,
        sequence: int,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> int:
        # Sequence 1 is reserved for the coordinator-confirmed start fact.
        return (
            self.coordinator.record_event(
                assignment_id, sequence + 1, event_id, payload
            )
            - 1
        )

    def remote_commit(
        self,
        assignment_id: str,
        *,
        fence: str,
        report: _RemoteExecutionReport,
        outputs: Mapping[str, ArtifactRef],
    ) -> None:
        record = self._remote_assignment_record(assignment_id)
        authority = self._remote_authority(str(record["run_uri"]))
        granted = authority.grant_prepared_attempt(
            str(record["run_uri"]),
            assignment_id=assignment_id,
            attempt_id=str(record["attempt_id"]),
        )
        if granted.fencing_token != fence:
            raise QueueConflictError("remote terminal fence conflicts")
        if report.status is StageStatus.SUCCEEDED:
            authority.record_output_commit(
                str(record["run_uri"]),
                str(record["stage_name"]),
                attempt_id=str(record["attempt_id"]),
                fencing_token=fence,
                outputs=outputs,
                assignment_id=assignment_id,
            )
        else:
            authority.record_managed_attempt_terminal(
                str(record["run_uri"]),
                fence=granted,
                status=report.status,
                reason=LifecycleReason(
                    code=(
                        "worker.remote_cancelled"
                        if report.status is StageStatus.CANCELLED
                        else "worker.remote_failed"
                    ),
                    detail={
                        "failure_type": report.failure_type,
                        "message": report.message,
                    },
                ),
            )
        state = self.coordinator.state(assignment_id)
        if state == "running":
            self.coordinator.advance(
                assignment_id, expected="running", next_state="terminal"
            )
        elif state == "granted":
            self.coordinator.advance(
                assignment_id, expected="granted", next_state="terminal"
            )
        state = self.coordinator.state(assignment_id)
        if state == "terminal":
            self.coordinator.advance(
                assignment_id,
                expected="terminal",
                next_state="logical_released",
            )

    def remote_release(self, assignment_id: str) -> None:
        state = self.coordinator.state(assignment_id)
        if state == "logical_released":
            self.coordinator.advance(
                assignment_id,
                expected="logical_released",
                next_state="released",
            )
        elif state != "released":
            raise QueueConflictError("remote assignment is not logically released")

    def remote_release_recovered(self, request: RecoverUnknownAssignment) -> None:
        """Release only the exact claim covered by a guarded recovery close."""

        if self.coordinator.state(request.assignment_id) == "released":
            return
        self.validate_session_replacement_recovery(request)
        try:
            self.coordinator.release_contained(request.assignment_id)
        except ManagedLocalError as exc:
            raise QueueConflictError(
                "contained remote assignment is not releasable"
            ) from exc

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
        retained = self.slurm_assignments.read_operation(operation_id)
        profile = self._slurm_profile(
            retained.assignment.profile_id,
            retained.assignment.profile_configuration_fingerprint,
        )
        self._require_slurm_profile_principal(profile, principal_id, credential_id)
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
        submission_before = self.slurm_submissions.read(operation_id)
        if submission_before.job_id is not None and (
            submission_before.job_id != job_id or submission_before.cluster != cluster
        ):
            raise QueueConflictError("SLURM bootstrap job handle conflicts")
        registered = self.slurm_assignments.register_bootstrap(
            operation_id,
            request_digest=request_digest,
            job_id=job_id,
            cluster=cluster,
            incarnation=incarnation,
            capability=capability,
        )
        submission = self.slurm_submissions.associate_handle(
            operation_id,
            profile,
            job_id=job_id,
            cluster=cluster,
        )
        self.slurm_assignments.record_submission(
            retained.assignment.assignment_id,
            state=submission.state.value,
            job_id=submission.job_id,
            cluster=submission.cluster,
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
        self._slurm_authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        return self.slurm_assignments.read_input_chunk(
            assignment_id, incarnation, transfer_id, offset
        )

    def slurm_inputs_ready(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
    ) -> None:
        self._slurm_authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        self.slurm_assignments.mark_input_ready(assignment_id, incarnation)

    def slurm_grant(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
    ) -> str:
        record = self._slurm_authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        if not record.input_ready:
            raise QueueConflictError("SLURM grant requires durable inputs")
        if record.fence is not None:
            return record.fence
        with sqlite3.connect(self.config.control_database) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cancellation = conn.execute(
                "SELECT cancellation_operation_id FROM managed_admissions "
                "WHERE run_uri = ?",
                (record.assignment.run_uri,),
            ).fetchone()
            if cancellation is not None and cancellation[0] is not None:
                raise QueueConflictError("SLURM assignment run is cancelling")
            authority = self._remote_authority(record.assignment.run_uri)
            fence = authority.grant_prepared_attempt(
                record.assignment.run_uri,
                assignment_id=assignment_id,
                attempt_id=record.assignment.attempt_id,
            )
            self.slurm_assignments.mark_granted(
                assignment_id, incarnation, fence.fencing_token
            )
            conn.commit()
        return fence.fencing_token

    def slurm_start_permit(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
        fence: str,
    ) -> bool:
        record = self._slurm_authorized_record(
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
        with sqlite3.connect(self.config.control_database) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cancellation = conn.execute(
                "SELECT cancellation_operation_id FROM managed_admissions "
                "WHERE run_uri = ?",
                (record.assignment.run_uri,),
            ).fetchone()
            if cancellation is not None and cancellation[0] is not None:
                conn.commit()
                return False
            permitted = self.slurm_submissions.consume_start(
                record.assignment.operation_id
            )
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
        record = self._slurm_authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        authority = self._remote_authority(record.assignment.run_uri)
        granted = authority.grant_prepared_attempt(
            record.assignment.run_uri,
            assignment_id=assignment_id,
            attempt_id=record.assignment.attempt_id,
        )
        if granted.fencing_token != fence:
            raise QueueConflictError("SLURM execution fence conflicts")
        authority.confirm_execution_started(record.assignment.run_uri, fence=granted)
        self.slurm_assignments.mark_running(
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
        self._slurm_authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        self.slurm_assignments.declare_report(assignment_id, incarnation, fence, report)

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
        self._slurm_authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        return self.slurm_assignments.write_output_chunk(
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
        record = self._slurm_authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        report, outputs = self.slurm_assignments.committed_result(
            assignment_id, incarnation, fence
        )
        authority = self._remote_authority(record.assignment.run_uri)
        granted = authority.grant_prepared_attempt(
            record.assignment.run_uri,
            assignment_id=assignment_id,
            attempt_id=record.assignment.attempt_id,
        )
        if granted.fencing_token != fence:
            raise QueueConflictError("SLURM terminal fence conflicts")
        if report.status is StageStatus.SUCCEEDED:
            authority.record_output_commit(
                record.assignment.run_uri,
                record.assignment.stage_name,
                attempt_id=record.assignment.attempt_id,
                fencing_token=fence,
                outputs=outputs,
                assignment_id=assignment_id,
            )
        else:
            authority.record_managed_attempt_terminal(
                record.assignment.run_uri,
                fence=granted,
                status=report.status,
                reason=LifecycleReason(
                    code=(
                        "worker.slurm_cancelled"
                        if report.status is StageStatus.CANCELLED
                        else "worker.slurm_failed"
                    ),
                    detail={
                        "failure_type": report.failure_type,
                        "message": report.message,
                    },
                ),
            )
        self.slurm_assignments.mark_terminal(assignment_id)

    def slurm_release(
        self,
        *,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
    ) -> None:
        self._slurm_authorized_record(
            principal_id, credential_id, assignment_id, incarnation
        )
        self._release_slurm_assignment(assignment_id)

    def _slurm_authorized_record(
        self,
        principal_id: str,
        credential_id: str | None,
        assignment_id: str,
        incarnation: str,
    ) -> SlurmStageRecord:
        record = self.slurm_assignments.read(assignment_id)
        profile = self._slurm_profile(
            record.assignment.profile_id,
            record.assignment.profile_configuration_fingerprint,
        )
        self._require_slurm_profile_principal(profile, principal_id, credential_id)
        if (
            record.assignment.profile_id != profile.profile_id
            or record.assignment.profile_descriptor != profile.descriptor
            or record.bootstrap_incarnation != incarnation
        ):
            raise QueueConflictError("SLURM bootstrap authorization conflicts")
        return record

    def _slurm_profile_for_principal(
        self, principal_id: str, credential_id: str | None
    ) -> SlurmReadyStageProfile:
        profile = next(
            (
                item
                for item in (
                    *self._scheduling.active_slurm_profiles.values(),
                    *self._scheduling.retained_slurm_profiles.values(),
                )
                if item.bootstrap_principal_id == principal_id
                and item.credential_reference == credential_id
            ),
            None,
        )
        if profile is None:
            raise QueueServiceError("SLURM bootstrap principal is not authorized")
        return profile

    def _slurm_profile_for_credential(
        self, credential_id: str
    ) -> SlurmReadyStageProfile | None:
        return next(
            (
                item
                for item in (
                    *self._scheduling.active_slurm_profiles.values(),
                    *self._scheduling.retained_slurm_profiles.values(),
                )
                if item.credential_reference == credential_id
            ),
            None,
        )

    @staticmethod
    def _require_slurm_profile_principal(
        profile: SlurmReadyStageProfile,
        principal_id: str,
        credential_id: str | None,
    ) -> None:
        if (
            profile.bootstrap_principal_id != principal_id
            or profile.credential_reference != credential_id
        ):
            raise QueueServiceError("SLURM bootstrap principal is not authorized")

    def _remote_assignment_record(self, assignment_id: str) -> sqlite3.Row:
        with sqlite3.connect(self.config.control_database) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM remote_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
        if row is None:
            raise QueueConflictError("remote assignment is not retained")
        return row

    def _remote_authority(self, run_uri: str) -> _ScopedCoordinatorAuthority:
        store = SQLitePerRunAuthorityStore(run_uri)
        store.open_run(run_uri)
        return _ScopedCoordinatorAuthority(
            store,
            run_uri=run_uri,
            coordinator_id=self.coordinator_id,
            ordinary_mutation_frozen=self._ordinary_mutation_frozen,
        )

    def _ordinary_mutation_frozen(self, assignment_id: str) -> bool:
        daemon = self.daemon
        return (
            False
            if daemon is None
            else daemon._recovery_fences_ordinary_terminal(assignment_id)
        )

    def _run_cancellation_operation(self, run_uri: str) -> str | None:
        with sqlite3.connect(self.config.control_database) as conn:
            row = conn.execute(
                "SELECT cancellation_operation_id FROM managed_admissions "
                "WHERE run_uri = ?",
                (run_uri,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0])

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
                capacity_holding = {str(row[0]) for row in rows}
            remote_assignment_ids: set[str] = set()
            if self.config.control_database.is_file():
                with sqlite3.connect(self.config.control_database) as conn:
                    table = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'remote_assignments'"
                    ).fetchone()
                    if table is not None:
                        remote_rows = conn.execute(
                            "SELECT assignment_id FROM remote_assignments"
                        )
                        remote_assignment_ids = {str(row[0]) for row in remote_rows}
        except sqlite3.DatabaseError as exc:
            raise QueueServiceError(
                "coordinator retained assignment state is unavailable"
            ) from exc
        return capacity_holding - remote_assignment_ids


def _stage_work(store: SQLiteStageWorkStore, stage_work_id: str) -> StageWorkRecord:
    for record in store.list_stage_work():
        if record.stage_work_id == stage_work_id:
            return record
    raise QueueServiceError("selected stage work disappeared before reservation")


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


def _slurm_state_diagnostic(state: str) -> str | None:
    return {
        "reserved": "slurm_awaiting_authority_bind",
        "bound": "slurm_awaiting_submission",
        "submitting": "slurm_submission_unknown",
        "unknown": "slurm_submission_unknown",
        "conflict": "slurm_submission_conflict",
        "rejected": "slurm_submission_rejected",
        "accepted": "slurm_bootstrap_awaiting_registration",
        "granted": "slurm_bootstrap_awaiting_start",
        "running": "slurm_loom_result_awaiting_commit",
        "terminal": "slurm_result_committed",
        "logical_released": "slurm_release_awaiting_acknowledgement",
        "released": "slurm_released",
    }.get(state)


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
    coordinator_id: str = "coordinator",
    agent_id: str = "agent",
    clock: Callable[[], str] = utc_timestamp,
    admission_revision: int = 0,
) -> tuple[Mapping[str, PlainData], ...]:
    """Join labelled owner snapshots without claiming cross-owner atomicity."""

    if not admissions:
        return ()
    run_uris = tuple(sorted({item.run_uri for item in admissions}))
    run_placeholders = ",".join("?" for _ in run_uris)
    stage_work_by_run: dict[str, list[dict[str, PlainData]]] = {}
    assignments_by_run: dict[str, list[dict[str, PlainData]]] = {}
    slurm_by_run: dict[str, list[dict[str, PlainData]]] = {}
    slurm_submission_by_operation: dict[str, dict[str, PlainData]] = {}
    agent_work_by_run: dict[str, list[dict[str, PlainData]]] = {}
    execution_available = False
    agent_available = False
    scheduling_revision: int | None = None
    assignment_revision: int | None = None
    agent_revision: int | None = None
    admission_observed_at = clock()
    try:
        with _connect_existing_sqlite(config.execution_database) as conn:
            conn.execute("BEGIN")
            _verify_owner_store_binding(
                conn, role="coordinator", stable_id=coordinator_id
            )
            revisions = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT axis, revision FROM local_daemon_status_revisions"
                )
            }
            scheduling_revision = revisions["scheduling"]
            assignment_revision = revisions["assignment"]
            for (payload,) in conn.execute(
                "SELECT record_json FROM stage_work WHERE run_uri IN ("
                f"{run_placeholders}) ORDER BY stage_work_id",
                run_uris,
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
                f"WHERE run_uri IN ({run_placeholders}) ORDER BY assignment_id",
                run_uris,
            ):
                assignments_by_run.setdefault(str(row[1]), []).append(
                    {
                        "assignment_id": str(row[0]),
                        "target": "managed_agent",
                        "state": str(row[2]),
                        "session_id": str(row[3]),
                        "offer_id": str(row[4]),
                        "claim_id": str(row[5]),
                        "receipt_digest": hashlib.sha256(
                            str(row[6]).encode("utf-8")
                        ).hexdigest(),
                    }
                )
            for operation_id, value_json in conn.execute(
                "SELECT operation_id, value_json FROM ready_stage_submissions "
                "WHERE operation_id IN (SELECT operation_id FROM "
                "slurm_stage_assignments WHERE run_uri IN ("
                f"{run_placeholders}))",
                run_uris,
            ):
                submission = SlurmReadyStageSubmission.from_dict(
                    json.loads(str(value_json))
                )
                slurm_submission_by_operation[str(operation_id)] = {
                    "dispatch_state": submission.state.value,
                    "scheduler_state": submission.scheduler_state,
                    "scheduler_source": submission.scheduler_source,
                    "scheduler_observed_at": submission.scheduler_observed_at,
                    "conflicting_handles": [
                        {"job_id": job_id, "cluster": cluster}
                        for job_id, cluster in submission.conflicting_handles
                    ],
                    "cancel_requested": submission.cancel_requested,
                }
            for row in conn.execute(
                "SELECT assignment_id, run_uri, state, profile_id, operation_id, "
                "job_id, cluster, bootstrap_incarnation, input_ready, fence, "
                "process_execution_id, report_json FROM slurm_stage_assignments "
                f"WHERE run_uri IN ({run_placeholders}) ORDER BY assignment_id",
                run_uris,
            ):
                report_status: str | None = None
                if row[11] is not None:
                    report = json.loads(str(row[11]))
                    if isinstance(report, Mapping) and isinstance(
                        report.get("status"), str
                    ):
                        report_status = cast(str, report["status"])
                slurm_by_run.setdefault(str(row[1]), []).append(
                    {
                        "assignment_id": str(row[0]),
                        "target": "slurm",
                        "state": str(row[2]),
                        "profile_id": str(row[3]),
                        "operation_id": str(row[4]),
                        "job_id": None if row[5] is None else str(row[5]),
                        "cluster": None if row[6] is None else str(row[6]),
                        "bootstrap_registered": row[7] is not None,
                        "input_ready": bool(row[8]),
                        "fence_bound": row[9] is not None,
                        "process_execution_id": (
                            None if row[10] is None else str(row[10])
                        ),
                        "loom_result_status": report_status,
                        "diagnostic": _slurm_state_diagnostic(str(row[2])),
                        "submission": slurm_submission_by_operation.get(
                            str(row[4]),
                            {
                                "dispatch_state": "unavailable",
                                "scheduler_state": None,
                                "scheduler_source": None,
                                "scheduler_observed_at": None,
                                "conflicting_handles": [],
                                "cancel_requested": False,
                            },
                        ),
                    }
                )
            execution_available = True
    except Exception:  # corrupt owner data is unavailable, never partial healthy work
        stage_work_by_run.clear()
        assignments_by_run.clear()
        slurm_by_run.clear()
        slurm_submission_by_operation.clear()
        scheduling_revision = None
        assignment_revision = None
        execution_available = False
    execution_observed_at = clock()
    try:
        with _connect_existing_sqlite(config.agent_journal) as conn:
            conn.execute("BEGIN")
            _verify_owner_store_binding(conn, role="local-agent", stable_id=agent_id)
            revision_row = conn.execute(
                "SELECT revision FROM local_daemon_status_revision"
            ).fetchone()
            if revision_row is None:
                raise sqlite3.DatabaseError("agent status revision is missing")
            agent_revision = int(revision_row[0])
            assignment_ids = tuple(
                sorted(
                    {
                        cast(str, item["assignment_id"])
                        for values in assignments_by_run.values()
                        for item in values
                    }
                )
            )
            assignment_placeholders = ",".join("?" for _ in assignment_ids)
            rows = (
                ()
                if not assignment_ids
                else conn.execute(
                    "SELECT assignment_id, identity_json, state, "
                    "process_execution_id, availability_revision "
                    "FROM assignments WHERE assignment_id IN ("
                    f"{assignment_placeholders}) ORDER BY assignment_id",
                    assignment_ids,
                )
            )
            for row in rows:
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
            agent_available = True
    except Exception:
        agent_work_by_run.clear()
        agent_revision = None
        agent_available = False
    agent_observed_at = clock()

    views: list[Mapping[str, PlainData]] = []
    for admission in admissions:
        authority_view: dict[str, PlainData]
        authority_observed_at = clock()
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
                "observed_at": authority_observed_at,
                "freshness": "unavailable",
            }
        else:
            authority_view = {
                "owner": "per-run-authority",
                "availability": "available",
                "state": snapshot.status.value,
                "observed_at": authority_observed_at,
                "revision": snapshot.revision.to_dict(),
                "stages": {
                    stage.stage_name: stage.status.value for stage in snapshot.stages
                },
                "freshness": "current",
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
                    "revision": admission_revision,
                    "observed_at": admission_observed_at,
                    "freshness": "current",
                },
                "authority": authority_view,
                "scheduling": {
                    "owner": "coordinator-stage-work",
                    "availability": "available"
                    if execution_available
                    else "unavailable",
                    "state": (
                        "unavailable"
                        if not execution_available
                        else "populated"
                        if stage_work_by_run.get(admission.run_uri)
                        else "empty"
                    ),
                    "revision": scheduling_revision,
                    "observed_at": execution_observed_at,
                    "freshness": ("current" if execution_available else "unavailable"),
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
                    "state": (
                        "unavailable"
                        if not execution_available
                        else "populated"
                        if assignments_by_run.get(admission.run_uri)
                        else "empty"
                    ),
                    "revision": assignment_revision,
                    "observed_at": execution_observed_at,
                    "freshness": ("current" if execution_available else "unavailable"),
                    "diagnostic": None
                    if execution_available
                    else "execution_store_unavailable",
                    "assignments": assignments_by_run.get(admission.run_uri, []),
                },
                "slurm": {
                    "owner": "coordinator-slurm",
                    "availability": (
                        "available" if execution_available else "unavailable"
                    ),
                    "state": (
                        "unavailable"
                        if not execution_available
                        else "populated"
                        if slurm_by_run.get(admission.run_uri)
                        else "empty"
                    ),
                    "revision": assignment_revision,
                    "observed_at": execution_observed_at,
                    "freshness": ("current" if execution_available else "unavailable"),
                    "diagnostic": (
                        None if execution_available else "execution_store_unavailable"
                    ),
                    "assignments": slurm_by_run.get(admission.run_uri, []),
                },
                "execution": {
                    "owner": "local-agent",
                    "availability": "available" if agent_available else "unavailable",
                    "state": (
                        "unavailable"
                        if not agent_available
                        else "populated"
                        if agent_work_by_run.get(admission.run_uri)
                        else "empty"
                    ),
                    "revision": agent_revision,
                    "observed_at": agent_observed_at,
                    "freshness": "current" if agent_available else "unavailable",
                    "diagnostic": None
                    if agent_available
                    else "agent_journal_unavailable",
                    "journal": agent_work_by_run.get(admission.run_uri, []),
                },
                "cancellation": {
                    "owner": "coordinator-and-per-run-authority",
                    "availability": authority_view["availability"],
                    "state": (
                        "requested_degraded"
                        if authority_view["availability"] == "unavailable"
                        and admission.cancellation_operation_id is not None
                        else "terminal"
                        if admission.state is LocalDaemonAdmissionState.CANCELLED
                        else "terminal_prevailed"
                        if admission.cancellation_operation_id is not None
                        and admission.state
                        in {
                            LocalDaemonAdmissionState.SUCCEEDED,
                            LocalDaemonAdmissionState.FAILED,
                        }
                        else "settling"
                        if admission.state is LocalDaemonAdmissionState.CANCELLING
                        else "effective"
                        if cancellation_receipt is not None
                        else "requested"
                        if admission.cancellation_operation_id is not None
                        else "not_requested"
                    ),
                    "requested": admission.cancellation_operation_id is not None,
                    "operation_id": admission.cancellation_operation_id,
                    "principal": admission.cancellation_principal_id,
                    "effective": cancellation_receipt is not None,
                    "settling": admission.state is LocalDaemonAdmissionState.CANCELLING,
                    "terminal": admission.state
                    in {
                        LocalDaemonAdmissionState.CANCELLED,
                        LocalDaemonAdmissionState.SUCCEEDED,
                        LocalDaemonAdmissionState.FAILED,
                    },
                    "receipt": cancellation_receipt,
                    "observed_at": authority_observed_at,
                    "freshness": (
                        "current"
                        if authority_view["availability"] == "available"
                        else "unavailable"
                    ),
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
                    "revision": {
                        "admission": admission_revision,
                        "scheduling": scheduling_revision,
                        "assignment": assignment_revision,
                        "execution": agent_revision,
                    },
                    "observed_at": clock(),
                    "freshness": (
                        "current"
                        if (
                            execution_available
                            and agent_available
                            and authority_view["availability"] == "available"
                        )
                        else "unavailable"
                    ),
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
