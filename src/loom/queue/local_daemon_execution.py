"""Protected production composition for the managed-local daemon."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.execution import StageWorkerRequest, prepare_stage_attempt
from loom.pipeline.executors.slurm.ready_stage import (
    ReadyStageState,
    SQLiteReadyStageSubmissions,
    SlurmReadyStageProfile,
    SlurmReadyStageRequest,
    SlurmReadyStageSubmission,
    map_ready_stage,
)
from loom.pipeline.executors.slurm.errors import (
    SlurmPlanningError,
    SlurmResourceMappingError,
)
from loom.pipeline.execution.lifecycle import bind_stage_inputs
from loom.pipeline.execution.managed_local import (
    AtomResourceProvider,
    ClaimCommand,
    GpuResourceProvider,
    ManagedAssignment,
    ManagedOfferSnapshot,
    ObserveRequest,
    SQLiteAgentJournal,
    SQLiteCoordinatorAssignments,
    _configured_provider_descriptor,
    run_managed_local_assignment,
)
from loom.pipeline.orchestration import (
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
    CpuResourcePlanner,
    ExecutionRouteKind,
    MemoryResourcePlanner,
    RunOptions,
    ResolvedStagePlacement,
    ResolvedStageRuntimeOptions,
    parallel_execution_options,
    resolve_run_runtime,
)
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.pipeline.runtime.scheduling_preferences import (
    GpuModelPreferenceScorer,
    OrderedAgentPreferenceScorer,
    PackingPreferenceScorer,
    ResourceAttributePreferenceScorer,
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
from loom.pipeline.stores.atomic import atomic_write_bytes
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
from ._remote_stage_execution import (
    MAX_TRANSFER_BYTES,
    ResidentProfileDescriptor,
    _DeliveredExecutionRequest,
    _RemoteArtifact,
    _RemoteExecutionReport,
    _validate_remote_semantic_data,
)
from .agent_sessions import AgentOffer, _target_remote_delivery
from .local_daemon import (
    LocalDaemon,
    LocalDaemonAdmission,
    LocalDaemonAdmissionState,
    LocalDaemonConfig,
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
    pipeline: PipelineSpec
    digest: str
    max_parallel_stages: int


@dataclass(frozen=True, slots=True)
class LocalDaemonExecutionOutcome:
    state: LocalDaemonAdmissionState
    reason: str | None = None


def _production_preference_scorers():
    """The sole production registration of the resolved placement scorers."""
    return {
        "preferred_agent": OrderedAgentPreferenceScorer(),
        "gpu_model": GpuModelPreferenceScorer(),
        "resource_attribute": ResourceAttributePreferenceScorer(),
        "packing": PackingPreferenceScorer(),
    }


@dataclass(frozen=True, slots=True)
class _RemoteCandidateTarget:
    agent_id: str
    session_id: str
    offer_id: str
    availability_revision: str
    inventory_revision: str
    offer: AgentOffer
    profile: ResidentProfileDescriptor


def _connect_existing_sqlite(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)


def _coordinator_capacity(config: LocalDaemonConfig) -> tuple[CapacityAtom, ...]:
    """Protected upper bounds for local and policy-authorized agent namespaces."""

    maximum = 2**63 - 1
    amounts: dict[tuple[str, str], tuple[int, str]] = {
        ("cpu", f"{config.machine_id}:cpu"): (config.cpu_capacity, "count")
    }
    if config.memory_capacity_bytes:
        amounts[("memory", f"{config.machine_id}:memory")] = (
            config.memory_capacity_bytes,
            "B",
        )
    gpu_atoms: list[CapacityAtom] = []
    for device in config.gpu_devices:
        descriptor = device.descriptor
        gpu_atoms.append(
            descriptor.capacity_atom(f"{config.machine_id}:{descriptor.device_id}")
        )
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
    allowed_targets = {config.machine_id} | {
        rule.agent_id for rule in config.agent_policy.agents
    }
    slurm_profiles = {profile.profile_id: profile for profile in config.slurm_profiles}
    for placement in placements.values():
        if placement.route.kind is ExecutionRouteKind.MANAGED_AGENT and (
            placement.target is not None and placement.target not in allowed_targets
        ):
            raise QueueServiceError(
                "exact runtime record targets an unauthorized managed agent"
            )
        if placement.route.kind is ExecutionRouteKind.SLURM:
            profile = slurm_profiles.get(cast(str, placement.route.profile_id))
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
        agent_id: str,
        coordinator_epoch: str,
        cancellation_operation: Callable[[str], str | None],
        admission_activated: Callable[[str], None],
        daemon: LocalDaemon | None = None,
    ) -> None:
        self.config = config
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
        self.cpu_planner = CpuResourcePlanner()
        self.memory_planner = MemoryResourcePlanner()
        self.gpu_planner = GpuResourcePlanner()
        self.planners = {
            "cpu": self.cpu_planner,
            "memory": self.memory_planner,
            "gpu": self.gpu_planner,
        }
        local_capacity: list[CapacityAtom] = [
            CapacityAtom(
                "cpu",
                f"{config.machine_id}:cpu",
                ExactQuantity(config.cpu_capacity),
                "count",
                ExactQuantity(1),
            )
        ]
        if config.memory_capacity_bytes:
            local_capacity.append(
                CapacityAtom(
                    "memory",
                    f"{config.machine_id}:memory",
                    ExactQuantity(config.memory_capacity_bytes),
                    "B",
                    ExactQuantity(1),
                )
            )
        for device in config.gpu_devices:
            descriptor = device.descriptor
            local_capacity.append(
                descriptor.capacity_atom(f"{config.machine_id}:{descriptor.device_id}")
            )
        self.local_capacity = tuple(local_capacity)
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
        if not local_daemon_owner_stores_available(
            self.config,
            coordinator_id=self.coordinator_id,
            agent_id=self.agent_id,
        ):
            raise QueueServiceError("retained daemon owner state is unavailable")
        self.providers = {}
        for kind in {atom.owner_resource_kind for atom in self.local_capacity}:
            if kind == "gpu":
                continue
            provider_atoms = tuple(
                atom for atom in self.local_capacity if atom.owner_resource_kind == kind
            )
            self.providers[kind] = AtomResourceProvider(
                _configured_provider_descriptor(kind, provider_atoms),
                self.planners[kind].claim_contracts,
                provider_atoms,
            )
        if config.gpu_devices:
            healthy_gpu_keys = {
                f"{config.machine_id}:{device.descriptor.device_id}"
                for device in config.gpu_devices
                if device.descriptor.healthy
            }
            gpu_atoms = tuple(
                atom
                for atom in self.local_capacity
                if atom.owner_resource_kind == "gpu"
                and atom.local_capacity_key in healthy_gpu_keys
            )
            self.providers["gpu"] = GpuResourceProvider(
                self.gpu_planner.claim_contracts,
                gpu_atoms,
                bindings={
                    f"{config.machine_id}:{device.descriptor.device_id}": (
                        device.binding_value
                    )
                    for device in config.gpu_devices
                    if device.descriptor.healthy
                },
            )
        self.provider = self.providers["cpu"]
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
            provider = self.providers.get(command.claim.resource_kind)
            if provider is None:
                raise QueueServiceError(
                    "retained local claim has no configured provider"
                )
            provider.restore_capacity_holding(command)
        self._launch_lock = Lock()
        self._slurm_observed_operations: set[str] = set()

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

    def advance(self, admission: LocalDaemonAdmission) -> LocalDaemonExecutionOutcome:
        self.open_owner_stores()
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
                decision_as_of, snapshot_time = (
                    self._daemon_owner()._accepted_snapshot()
                )
                snapshot = scoped_authority.open_run(admission.run_uri)
                slurm_in_flight, slurm_diagnostic = self._reconcile_slurm_run(
                    admission.run_uri, scoped_authority
                )
                snapshot = scoped_authority.open_run(admission.run_uri)
                terminal = self._terminal_outcome(
                    intent.plan, snapshot, scoped_authority
                )
                if terminal is not None:
                    if slurm_in_flight:
                        return LocalDaemonExecutionOutcome(
                            LocalDaemonAdmissionState.ACTIVE,
                            slurm_diagnostic
                            or "SLURM release remains durably in flight",
                        )
                    return terminal
                if self._remote_run_in_flight(admission.run_uri):
                    return LocalDaemonExecutionOutcome(
                        LocalDaemonAdmissionState.ACTIVE,
                        "remote assignment remains durably in flight",
                    )
                orchestrator.reconcile(
                    admission_id=admission.admission_id,
                    plan=intent.plan,
                    authority_snapshot=snapshot,
                    placements=placements,
                    ready_at=snapshot_time,
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
                slurm_dispatch = self._dispatch_slurm_ready(
                    admission=admission,
                    intent=intent,
                    authority=scoped_authority,
                    snapshot=snapshot,
                )
                if slurm_dispatch is not None:
                    # A pinned route may be unavailable without becoming a
                    # global scheduling barrier.  Keep its diagnostic, but
                    # allow the ordinary managed decision below to advance
                    # independent ready work in this same cycle.
                    if slurm_dispatch.state is LocalDaemonAdmissionState.WAITING:
                        slurm_diagnostic = slurm_dispatch.reason
                    else:
                        return slurm_dispatch
                remote_targets = self._remote_candidates()
                local_candidate = self._candidate()
                remote_rejected = False
                while True:
                    candidates = tuple(
                        [
                            local_candidate
                            for _ in (0,)
                            if local_candidate.candidate_id not in remote_targets
                        ]
                        + [target[0] for _, target in sorted(remote_targets.items())]
                    )
                    decision = orchestrator.decide(
                        kernel=SchedulingKernel(
                            planners=self.planners,
                            policy=FifoSchedulingPolicy(),
                            component_epoch=self.coordinator_epoch,
                            preference_scorers=_production_preference_scorers(),
                        ),
                        candidates=candidates,
                        as_of=snapshot_time,
                        admission_id=admission.admission_id,
                    )
                    if decision.state is not PolicyDecisionState.SELECT:
                        if slurm_in_flight:
                            return LocalDaemonExecutionOutcome(
                                LocalDaemonAdmissionState.ACTIVE,
                                slurm_diagnostic
                                or "explicit SLURM assignment remains durably in flight",
                            )
                        if slurm_diagnostic is not None:
                            return LocalDaemonExecutionOutcome(
                                LocalDaemonAdmissionState.WAITING,
                                slurm_diagnostic,
                            )
                        reason = (
                            "selected remote capacity does not support path-free "
                            "regular-file execution"
                            if remote_rejected
                            else "no dependency-ready stage currently has managed "
                            "capacity"
                        )
                        return LocalDaemonExecutionOutcome(
                            LocalDaemonAdmissionState.WAITING,
                            reason,
                        )
                    assert decision.stage_work_id is not None
                    assert decision.selected is not None
                    record = _stage_work(self.stage_work_store, decision.stage_work_id)
                    candidate_id = cast(str, decision.candidate_id)
                    if candidate_id in remote_targets and not self._remote_eligible(
                        intent=intent,
                        snapshot=snapshot,
                        record=record,
                    ):
                        del remote_targets[candidate_id]
                        remote_rejected = True
                        continue
                    break
                remote_started = self._execute(
                    admission=admission,
                    intent=intent,
                    authority=scoped_authority,
                    snapshot=snapshot,
                    record=record,
                    decision=decision,
                    remote_targets={
                        key: value[1] for key, value in remote_targets.items()
                    },
                    decision_as_of=decision_as_of,
                    execution_started=release_launch,
                )
                if remote_started:
                    return LocalDaemonExecutionOutcome(
                        LocalDaemonAdmissionState.ACTIVE,
                        "remote assignment was durably targeted",
                    )
            finally:
                release_launch()
        return LocalDaemonExecutionOutcome(
            LocalDaemonAdmissionState.WAITING,
            "bounded reconciliation window exhausted",
        )

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
            before_runner=lambda submitting: self._mirror_slurm_submission_eligibility(
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
            record.assignment.profile_id
        ).job_private_file_provider.revoke(capability)
        self.slurm_assignments.release(assignment_id)

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
                profile = self._slurm_profile(record.assignment.profile_id)
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
                    self._release_slurm_assignment(assignment_id)
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
                profile = self._slurm_profile(record.assignment.profile_id)
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

    def _dispatch_slurm_ready(
        self,
        *,
        admission: LocalDaemonAdmission,
        intent: ManagedLocalIntent,
        authority: _ScopedCoordinatorAuthority,
        snapshot: AuthoritativeRunSnapshot,
    ) -> LocalDaemonExecutionOutcome | None:
        records = tuple(
            sorted(
                (
                    record
                    for record in self.stage_work_store.list_stage_work()
                    if record.admission_id == admission.admission_id
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
        profile = self._slurm_profile(cast(str, record.placement.route.profile_id))
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

    def _slurm_profile(self, profile_id: str):
        profile = next(
            (
                item
                for item in self.config.slurm_profiles
                if item.profile_id == profile_id
            ),
            None,
        )
        if profile is None:
            raise QueueConflictError("SLURM profile is not configured")
        return profile

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
                    "s.agent_id, s.session_id FROM agent_offers o "
                    "JOIN agent_sessions s ON s.session_id = o.session_id "
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
            profile = sorted(matching, key=lambda item: item.profile_id)[0]
            agent_id = str(row["agent_id"])
            availability_atoms: list[CapacityAtom] = []
            inventory_atoms: list[CapacityAtom] = []
            if offer.cpu:
                cpu_atom = CapacityAtom(
                    "cpu",
                    f"{agent_id}:cpu",
                    ExactQuantity(offer.cpu),
                    "count",
                    ExactQuantity(1),
                )
                inventory_atoms.append(cpu_atom)
                availability_atoms.append(cpu_atom)
            if offer.memory_bytes:
                memory_atom = CapacityAtom(
                    "memory",
                    f"{agent_id}:memory",
                    ExactQuantity(offer.memory_bytes),
                    "B",
                    ExactQuantity(1),
                )
                inventory_atoms.append(memory_atom)
                availability_atoms.append(memory_atom)
            inventory_atoms.extend(
                device.capacity_atom(f"{agent_id}:{device.device_id}")
                for device in offer.gpu_devices
            )
            availability_atoms.extend(
                CapacityAtom(
                    "gpu",
                    f"{agent_id}:{atom.local_capacity_key}",
                    atom.amount,
                    atom.unit,
                    atom.granularity,
                )
                for atom in offer.gpu_atoms
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
                    offer.availability_revision,
                    data=data,
                    atoms=kind_availability_atoms,
                )
            candidate = Candidate(
                agent_id,
                inventory,
                availability,
                attributes={
                    "resident_profile_id": profile.profile_id,
                    "resident_profile_revision": profile.revision,
                    "resident_project_fingerprint": profile.project_fingerprint,
                    "resident_environment_fingerprint": (
                        profile.environment_fingerprint
                    ),
                    "resident_executor_fingerprint": profile.executor_fingerprint,
                    "artifact_capability": "regular-file-relay-v1",
                },
                pool_names=offer.pools,
            )
            target = _RemoteCandidateTarget(
                agent_id=agent_id,
                session_id=str(row["session_id"]),
                offer_id=str(row["offer_id"]),
                availability_revision=offer.availability_revision,
                inventory_revision=offer.inventory_revision,
                offer=offer,
                profile=profile,
            )
            self.coordinator.publish_offer(
                ManagedOfferSnapshot(
                    agent_id=agent_id,
                    session_id=target.session_id,
                    offer_revision=target.offer_id,
                    snapshot_revision=offer.availability_revision,
                    inventory_revision=offer.inventory_revision,
                    availability_revision=offer.availability_revision,
                    component_descriptors=tuple(
                        self.planners[kind].descriptor for kind in sorted(inventory)
                    ),
                    provider_descriptors=offer.provider_descriptors,
                    atoms=tuple(availability_atoms),
                    reflected_claim_ids=offer.reflected_claim_ids,
                )
            )
            targets[agent_id] = (candidate, target)
        return targets

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
            self.coordinator.publish_offer(
                ManagedOfferSnapshot(
                    agent_id=self.config.machine_id,
                    session_id=self.coordinator_epoch,
                    offer_revision=offer_id,
                    snapshot_revision=self.coordinator_epoch,
                    inventory_revision=f"inventory-{self.coordinator_epoch}",
                    availability_revision=availability_revision,
                    component_descriptors=tuple(
                        self.planners[kind].descriptor for kind in sorted(observations)
                    ),
                    provider_descriptors=tuple(
                        self.providers[kind].descriptor for kind in sorted(observations)
                    ),
                    atoms=tuple(
                        atom
                        for kind in sorted(observations)
                        for atom in observations[kind].atoms
                    ),
                    reflected_claim_ids=tuple(
                        sorted(
                            {
                                claim_id
                                for result in observations.values()
                                for claim_id in result.live_claim_ids
                            }
                        )
                    ),
                )
            )
        provider_descriptors = {
            descriptor.kind: descriptor
            for descriptor in (
                remote_target.offer.provider_descriptors
                if remote_target is not None
                else tuple(provider.descriptor for provider in self.providers.values())
            )
        }
        commands = tuple(
            ClaimCommand(
                assignment,
                f"{assignment_id}:prepare:{index}",
                claim,
                provider_descriptors[claim.resource_kind],
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
            remote_target.availability_revision
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
                self.planners[kind].descriptor.to_dict()
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
            delivered = _DeliveredExecutionRequest.from_worker_request(
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
        run_managed_local_assignment(
            coordinator=self.coordinator,
            authority=authority,
            journal=self.journal,
            assignment=assignment,
            worker_request=worker_request,
            claims=claims,
            commands=commands,
            providers=self.providers,
            run_store=self.run_store,
            max_parallel_stages=intent.max_parallel_stages,
            decision_receipt=decision_receipt,
            cancellation_requested=lambda: self._install_cancellation_if_requested(
                admission, authority
            ),
            execution_started=execution_started,
        )
        return False

    def _remote_run_in_flight(self, run_uri: str) -> bool:
        with sqlite3.connect(self.config.control_database) as conn:
            row = conn.execute(
                "SELECT 1 FROM remote_assignments WHERE run_uri = ? "
                "AND state != 'RELEASED' LIMIT 1",
                (run_uri,),
            ).fetchone()
        return row is not None

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
        profile = self._slurm_profile_for_principal(principal_id, credential_id)
        retained = self.slurm_assignments.read_operation(operation_id)
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
        authority = self._remote_authority(record.assignment.run_uri)
        fence = authority.grant_prepared_attempt(
            record.assignment.run_uri,
            assignment_id=assignment_id,
            attempt_id=record.assignment.attempt_id,
        )
        self.slurm_assignments.mark_granted(
            assignment_id, incarnation, fence.fencing_token
        )
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
        return self.slurm_submissions.consume_start(record.assignment.operation_id)

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
        profile = self._slurm_profile_for_principal(principal_id, credential_id)
        record = self.slurm_assignments.read(assignment_id)
        if (
            record.assignment.profile_id != profile.profile_id
            or record.assignment.profile_descriptor != profile.descriptor
            or record.bootstrap_incarnation != incarnation
        ):
            raise QueueConflictError("SLURM bootstrap authorization conflicts")
        return record

    def _slurm_profile_for_principal(
        self, principal_id: str, credential_id: str | None
    ):
        profile = next(
            (
                item
                for item in self.config.slurm_profiles
                if item.bootstrap_principal_id == principal_id
                and item.credential_reference == credential_id
            ),
            None,
        )
        if profile is None:
            raise QueueServiceError("SLURM bootstrap principal is not authorized")
        return profile

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
        )

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
                "SELECT operation_id, value_json FROM ready_stage_submissions"
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
                "ORDER BY assignment_id"
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
