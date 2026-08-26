"""Persistent managed-execution coordinator with a protected local agent.

The daemon owns admission, process identity, and the production composition that
connects persisted run plans to the Stage 29 orchestrator and local assignment
saga. Clients provide only a queue identity and run URI.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
from threading import Event, RLock, Thread
import time
from typing import TYPE_CHECKING, Iterator
from uuid import uuid4

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp, utc_timestamp
from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
from loom.scheduling import (
    HardConstraintEvaluator,
    PreferenceScorer,
    ResourcePlanner,
    SchedulingComponentDescriptor,
    SchedulingPolicy,
)

from .agent_sessions import (
    AgentControl,
    AgentControlEffect,
    AgentPolicyConfig,
    AgentSessionView,
    initialize_agent_session_schema,
    validate_agent_session_schema,
)
from ._agent_process_supervisor import ResidentWorkerLaunchProfile
from ._remote_stage_execution import GpuDeviceDescriptor, ResidentProfileDescriptor
from .errors import QueueConflictError, QueueServiceError, QueueStorageError

if TYPE_CHECKING:
    from .local_daemon_execution import (
        LocalDaemonExecution,
        LocalDaemonExecutionOutcome,
    )


_LOCAL_DAEMON_SCHEMA_VERSION = 5


class LocalDaemonAdmissionState(StrEnum):
    """Coordinator-owned state, kept separate from authority lifecycle truth."""

    PENDING_AUTHORITY = "PENDING_AUTHORITY"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CoordinatorSchedulingReload:
    """Inert request to read and install protected coordinator-local config."""

    operation_id: str
    expected_scheduling_epoch: str
    reason: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "operation_id"),
            (self.expected_scheduling_epoch, "expected_scheduling_epoch"),
        ):
            if not isinstance(value, str) or not value or len(value) > 160:
                raise QueueServiceError(f"{name} must be a bounded non-empty string")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 512
        ):
            raise QueueServiceError(
                "scheduling reload reason must be 1..512 characters"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "expected_scheduling_epoch": self.expected_scheduling_epoch,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "CoordinatorSchedulingReload":
        _exact_fields(
            data,
            {"operation_id", "expected_scheduling_epoch", "reason"},
            "coordinator scheduling reload",
        )
        return cls(
            operation_id=_required_string(data, "operation_id"),
            expected_scheduling_epoch=_required_string(
                data, "expected_scheduling_epoch"
            ),
            reason=_required_string(data, "reason"),
        )


class LocalDaemonRole(StrEnum):
    CLIENT = "client"
    OPERATOR = "operator"
    AGENT = "agent"
    SLURM_BOOTSTRAP = "slurm_bootstrap"


@dataclass(frozen=True, slots=True)
class ConfiguredGpuDevice:
    """One configured manageable GPU; ``binding_value`` never leaves the agent."""

    descriptor: GpuDeviceDescriptor
    binding_value: str

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, GpuDeviceDescriptor):
            raise QueueServiceError("configured GPU descriptor is invalid")
        if self.descriptor.allocation_mode != "exclusive":
            raise QueueServiceError(
                "configured GPU sharing requires an enforceable provider adapter"
            )
        if (
            not isinstance(self.binding_value, str)
            or not self.binding_value
            or "\0" in self.binding_value
        ):
            raise QueueServiceError(
                "configured GPU binding_value must be a safe non-empty string"
            )
        if "," in self.binding_value:
            raise QueueServiceError(
                "configured GPU binding_value must not contain a list separator"
            )


@dataclass(frozen=True, slots=True)
class LocalDaemonPrincipal:
    """Trusted adapter-derived principal; request bodies never select it."""

    subject: str
    role: LocalDaemonRole
    credential_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject:
            raise QueueServiceError("daemon principal subject must be non-empty")
        object.__setattr__(self, "role", LocalDaemonRole(self.role))
        if self.credential_id is not None and (
            not isinstance(self.credential_id, str) or not self.credential_id
        ):
            raise QueueServiceError("daemon principal credential ID must be non-empty")


@dataclass(frozen=True, slots=True)
class LocalDaemonSchedulingComponents:
    """Trusted, complete scheduling composition for one coordinator epoch.

    The objects are trusted project code. Durable state records only their inert
    descriptors; executable objects never cross a process or persistence boundary.
    """

    planners: tuple[ResourcePlanner, ...]
    hard_evaluators: tuple[HardConstraintEvaluator, ...]
    preference_scorers: tuple[PreferenceScorer, ...]
    policy: SchedulingPolicy

    def __post_init__(self) -> None:
        planners = tuple(self.planners)
        hard = tuple(self.hard_evaluators)
        preferences = tuple(self.preference_scorers)
        if not planners or any(
            not isinstance(item, ResourcePlanner) for item in planners
        ):
            raise QueueServiceError("scheduling composition requires resource planners")
        if not hard or any(
            not isinstance(item, HardConstraintEvaluator) for item in hard
        ):
            raise QueueServiceError("scheduling composition requires hard evaluators")
        if not preferences or any(
            not isinstance(item, PreferenceScorer) for item in preferences
        ):
            raise QueueServiceError(
                "scheduling composition requires preference scorers"
            )
        if not isinstance(self.policy, SchedulingPolicy):
            raise QueueServiceError("scheduling composition requires one policy")
        components = (*planners, *hard, *preferences, self.policy)
        descriptors = tuple(getattr(item, "descriptor", None) for item in components)
        if any(
            not isinstance(item, SchedulingComponentDescriptor) for item in descriptors
        ):
            raise QueueServiceError("scheduling component descriptors are invalid")
        typed_descriptors = tuple(
            item
            for item in descriptors
            if isinstance(item, SchedulingComponentDescriptor)
        )
        if len({item.kind for item in typed_descriptors}) != len(typed_descriptors):
            raise QueueServiceError("scheduling component kinds must be unique")
        if any(
            planner.resource_kind != planner.descriptor.kind for planner in planners
        ):
            raise QueueServiceError("resource planner identities are inconsistent")
        if any(
            not planner.claim_contracts
            or any(
                contract.kind != planner.resource_kind
                for contract in planner.claim_contracts
            )
            for planner in planners
        ):
            raise QueueServiceError("resource planner claim contracts are inconsistent")
        object.__setattr__(self, "planners", planners)
        object.__setattr__(self, "hard_evaluators", hard)
        object.__setattr__(self, "preference_scorers", preferences)

    @property
    def descriptors(self) -> tuple[SchedulingComponentDescriptor, ...]:
        return tuple(
            sorted(
                (
                    item.descriptor
                    for item in (
                        *self.planners,
                        *self.hard_evaluators,
                        *self.preference_scorers,
                        self.policy,
                    )
                ),
                key=lambda item: item.key,
            )
        )


def _default_scheduling_components() -> LocalDaemonSchedulingComponents:
    """Return the explicit built-in production composition."""

    from loom.pipeline.runtime import CpuResourcePlanner, MemoryResourcePlanner
    from loom.pipeline.runtime.scheduling_preferences import (
        GpuModelPreferenceScorer,
        OrderedAgentPreferenceScorer,
        PackingPreferenceScorer,
        ResourceAttributePreferenceScorer,
    )
    from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
    from loom.scheduling import (
        AttributeConstraintEvaluator,
        FifoSchedulingPolicy,
        TargetConstraintEvaluator,
    )

    return LocalDaemonSchedulingComponents(
        planners=(
            CpuResourcePlanner(),
            MemoryResourcePlanner(),
            GpuResourcePlanner(),
        ),
        hard_evaluators=(
            TargetConstraintEvaluator(),
            AttributeConstraintEvaluator(),
        ),
        preference_scorers=(
            OrderedAgentPreferenceScorer(),
            GpuModelPreferenceScorer(),
            ResourceAttributePreferenceScorer(),
            PackingPreferenceScorer(),
        ),
        policy=FifoSchedulingPolicy(),
    )


@dataclass(frozen=True, slots=True)
class LocalDaemonConfig:
    """Protected configuration for one local coordinator and agent."""

    coordinator_root: Path
    agent_root: Path
    run_store_root: Path
    resident_worker_launch_profile: ResidentWorkerLaunchProfile
    machine_id: str = "machine-A"
    cpu_capacity: int = 1
    memory_capacity_bytes: int = 0
    gpu_devices: tuple[ConfiguredGpuDevice, ...] = ()
    poll_interval_seconds: float = 0.05
    agent_policy: AgentPolicyConfig = AgentPolicyConfig()
    remote_profiles: tuple[ResidentProfileDescriptor, ...] = ()
    slurm_profiles: tuple[SlurmReadyStageProfile, ...] = ()
    scheduling_components: LocalDaemonSchedulingComponents = field(
        default_factory=_default_scheduling_components
    )

    def __post_init__(self) -> None:
        coordinator = Path(self.coordinator_root)
        agent = Path(self.agent_root)
        run_store = Path(self.run_store_root)
        profile = self.resident_worker_launch_profile
        if not isinstance(profile, ResidentWorkerLaunchProfile):
            raise QueueServiceError("resident worker launch profile is required")
        try:
            descriptor = ResidentProfileDescriptor.from_dict(profile.descriptor)
        except (QueueServiceError, ValueError, TypeError) as exc:
            raise QueueServiceError("resident worker launch profile is invalid") from exc
        if descriptor.to_dict() != profile.descriptor:
            raise QueueServiceError(
                "resident worker launch descriptor must be exact"
            )
        if coordinator == agent:
            raise QueueServiceError(
                "coordinator and local-agent roots must be distinct"
            )
        if not isinstance(self.machine_id, str) or not self.machine_id:
            raise QueueServiceError("machine_id must be non-empty")
        if (
            isinstance(self.cpu_capacity, bool)
            or not isinstance(self.cpu_capacity, int)
            or self.cpu_capacity < 1
        ):
            raise QueueServiceError("cpu_capacity must be a positive integer")
        if (
            isinstance(self.memory_capacity_bytes, bool)
            or not isinstance(self.memory_capacity_bytes, int)
            or self.memory_capacity_bytes < 0
        ):
            raise QueueServiceError(
                "memory_capacity_bytes must be a non-negative integer"
            )
        gpu_devices = tuple(self.gpu_devices)
        if any(not isinstance(item, ConfiguredGpuDevice) for item in gpu_devices):
            raise QueueServiceError("gpu_devices must be configured GPU devices")
        if len({item.descriptor.device_id for item in gpu_devices}) != len(gpu_devices):
            raise QueueServiceError("configured GPU device IDs must be unique")
        if len({item.binding_value for item in gpu_devices}) != len(gpu_devices):
            raise QueueServiceError("configured GPU bindings must be unique")
        if (
            isinstance(self.poll_interval_seconds, bool)
            or not isinstance(self.poll_interval_seconds, (int, float))
            or self.poll_interval_seconds <= 0
        ):
            raise QueueServiceError("poll_interval_seconds must be positive")
        if not isinstance(self.agent_policy, AgentPolicyConfig):
            raise QueueServiceError("agent_policy must be protected agent policy")
        if not isinstance(self.scheduling_components, LocalDaemonSchedulingComponents):
            raise QueueServiceError(
                "scheduling_components must be a complete trusted composition"
            )
        if any(rule.agent_id == self.machine_id for rule in self.agent_policy.agents):
            raise QueueServiceError(
                "remote agent identities must be distinct from the local machine"
            )
        profiles = tuple(self.remote_profiles)
        if any(not isinstance(item, ResidentProfileDescriptor) for item in profiles):
            raise QueueServiceError("remote resident profiles are invalid")
        if len({item.profile_id for item in profiles}) != len(profiles):
            raise QueueServiceError("remote resident profile IDs must be unique")
        slurm_profiles = tuple(self.slurm_profiles)
        if any(not isinstance(item, SlurmReadyStageProfile) for item in slurm_profiles):
            raise QueueServiceError("protected SLURM profiles are invalid")
        if len({item.profile_id for item in slurm_profiles}) != len(slurm_profiles):
            raise QueueServiceError("protected SLURM profile IDs must be unique")
        if len({item.bootstrap_principal_id for item in slurm_profiles}) != len(
            slurm_profiles
        ):
            raise QueueServiceError("SLURM bootstrap principals must be unique")
        if len({item.credential_reference for item in slurm_profiles}) != len(
            slurm_profiles
        ):
            raise QueueServiceError("SLURM bootstrap credentials must be unique")
        existing_credentials = {
            item.credential_id
            for item in (*self.agent_policy.agents, *self.agent_policy.principals)
        }
        if any(
            item.credential_reference in existing_credentials for item in slurm_profiles
        ):
            raise QueueServiceError(
                "SLURM bootstrap credentials must be role-exclusive"
            )
        object.__setattr__(self, "coordinator_root", coordinator)
        object.__setattr__(self, "agent_root", agent)
        object.__setattr__(self, "run_store_root", run_store)
        object.__setattr__(self, "resident_worker_launch_profile", profile)
        object.__setattr__(self, "remote_profiles", profiles)
        object.__setattr__(self, "slurm_profiles", slurm_profiles)
        object.__setattr__(
            self,
            "gpu_devices",
            tuple(sorted(gpu_devices, key=lambda item: item.descriptor.device_id)),
        )
        object.__setattr__(
            self, "poll_interval_seconds", float(self.poll_interval_seconds)
        )

    @property
    def endpoint(self) -> Path:
        return self.coordinator_root / "daemon.sock"

    @property
    def control_database(self) -> Path:
        return self.coordinator_root / "control.sqlite"

    @property
    def execution_database(self) -> Path:
        return self.coordinator_root / "execution.sqlite"

    @property
    def agent_journal(self) -> Path:
        return self.agent_root / "journal.sqlite"

    @property
    def slurm_transfer_root(self) -> Path:
        return self.coordinator_root / "slurm-transfers"

    @property
    def slurm_script_root(self) -> Path:
        return self.coordinator_root / "slurm-scripts"


@dataclass(frozen=True, slots=True)
class LocalDaemonAdmissionRequest:
    """The complete public submission shape."""

    queue_item_id: str
    run_uri: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.queue_item_id, "queue_item_id"),
            (self.run_uri, "run_uri"),
        ):
            if not isinstance(value, str) or not value:
                raise QueueServiceError(f"{name} must be a non-empty string")

    def to_dict(self) -> dict[str, PlainData]:
        return {"queue_item_id": self.queue_item_id, "run_uri": self.run_uri}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonAdmissionRequest":
        _exact_fields(data, {"queue_item_id", "run_uri"}, "admission request")
        return cls(
            queue_item_id=_required_string(data, "queue_item_id"),
            run_uri=_required_string(data, "run_uri"),
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonAdmission:
    admission_id: str
    queue_item_id: str
    coordinator_id: str
    run_uri: str
    intent_digest: str
    execution_owner: str
    state: LocalDaemonAdmissionState
    accepted_at: str
    authority_operation_id: str
    cancellation_operation_id: str | None = None
    cancellation_principal_id: str | None = None
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "admission_id": self.admission_id,
            "queue_item_id": self.queue_item_id,
            "coordinator_id": self.coordinator_id,
            "run_uri": self.run_uri,
            "intent_digest": self.intent_digest,
            "execution_owner": self.execution_owner,
            "state": self.state.value,
            "accepted_at": self.accepted_at,
            "authority_operation_id": self.authority_operation_id,
            "cancellation_operation_id": self.cancellation_operation_id,
            "cancellation_principal_id": self.cancellation_principal_id,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonAdmission":
        _exact_fields(
            data,
            {
                "admission_id",
                "queue_item_id",
                "coordinator_id",
                "run_uri",
                "intent_digest",
                "execution_owner",
                "state",
                "accepted_at",
                "authority_operation_id",
                "cancellation_operation_id",
                "cancellation_principal_id",
                "blocked_reason",
            },
            "local daemon admission",
        )
        return cls(
            admission_id=_required_string(data, "admission_id"),
            queue_item_id=_required_string(data, "queue_item_id"),
            coordinator_id=_required_string(data, "coordinator_id"),
            run_uri=_required_string(data, "run_uri"),
            intent_digest=_required_string(data, "intent_digest"),
            execution_owner=_required_string(data, "execution_owner"),
            state=LocalDaemonAdmissionState(_required_string(data, "state")),
            accepted_at=_required_string(data, "accepted_at"),
            authority_operation_id=_required_string(data, "authority_operation_id"),
            cancellation_operation_id=_optional_string(
                data, "cancellation_operation_id"
            ),
            cancellation_principal_id=_optional_string(
                data, "cancellation_principal_id"
            ),
            blocked_reason=_optional_string(data, "blocked_reason"),
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonStatus:
    coordinator_id: str
    coordinator_epoch: str
    as_of: str
    accepted_time: str
    service_health: str
    service_diagnostic: str | None
    admissions: tuple[LocalDaemonAdmission, ...]
    scheduling_epoch: str
    controls: tuple[Mapping[str, PlainData], ...] = ()
    runs: tuple[Mapping[str, PlainData], ...] = ()

    @property
    def scheduling_ready(self) -> bool:
        return self.service_health == "healthy" and any(
            admission.state
            in {
                LocalDaemonAdmissionState.ACTIVE,
                LocalDaemonAdmissionState.WAITING,
            }
            for admission in self.admissions
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "as_of": self.as_of,
            "accepted_time": self.accepted_time,
            "service_health": self.service_health,
            "service_diagnostic": self.service_diagnostic,
            "scheduling_epoch": self.scheduling_epoch,
            "scheduling_ready": self.scheduling_ready,
            "admissions": [item.to_dict() for item in self.admissions],
            "controls": [
                thaw_plain_data(item, path="local_daemon_status.controls")
                for item in self.controls
            ],
            "runs": [
                thaw_plain_data(item, path="local_daemon_status.runs")
                for item in self.runs
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonStatus":
        _exact_fields(
            data,
            {
                "coordinator_id",
                "coordinator_epoch",
                "as_of",
                "accepted_time",
                "service_health",
                "service_diagnostic",
                "scheduling_epoch",
                "scheduling_ready",
                "admissions",
                "controls",
                "runs",
            },
            "local daemon status",
        )
        admissions = data.get("admissions")
        if not isinstance(admissions, list) or any(
            not isinstance(item, Mapping) for item in admissions
        ):
            raise QueueServiceError("admissions must be a list of records")
        runs = data.get("runs", [])
        if not isinstance(runs, list) or any(
            not isinstance(item, Mapping) for item in runs
        ):
            raise QueueServiceError("runs must be a list of owner views")
        controls = data.get("controls")
        if not isinstance(controls, list) or any(
            not isinstance(item, Mapping) for item in controls
        ):
            raise QueueServiceError("controls must be a list of owner views")
        return cls(
            coordinator_id=_required_string(data, "coordinator_id"),
            coordinator_epoch=_required_string(data, "coordinator_epoch"),
            as_of=_required_string(data, "as_of"),
            accepted_time=_required_string(data, "accepted_time"),
            service_health=_required_string(data, "service_health"),
            service_diagnostic=_optional_string(data, "service_diagnostic"),
            scheduling_epoch=_required_string(data, "scheduling_epoch"),
            admissions=tuple(
                LocalDaemonAdmission.from_dict(item) for item in admissions
            ),
            controls=tuple(
                freeze_plain_data(item, path="local_daemon_status.controls")
                for item in controls
            ),
            runs=tuple(
                freeze_plain_data(item, path="local_daemon_status.runs")
                for item in runs
            ),
        )


class LocalDaemon:
    """One locked persistent production composition."""

    def __init__(
        self,
        config: LocalDaemonConfig,
        *,
        clock: Callable[[], str] = utc_timestamp,
        trusted_scheduling_loader: Callable[[], LocalDaemonConfig] | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._trusted_scheduling_loader = trusted_scheduling_loader
        self._coordinator_lock: object | None = None
        self._agent_lock: object | None = None
        self._coordinator_id: str | None = None
        self._agent_id: str | None = None
        self._epoch: str | None = None
        self._scheduling_epoch: str | None = None
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None
        self._assignment_workers: ThreadPoolExecutor | None = None
        self._execution: LocalDaemonExecution | None = None
        self._assignment_futures: dict[str, Future[LocalDaemonExecutionOutcome]] = {}
        self._cycle_lock = RLock()
        self._service_error: str | None = None
        self._agent_policy = config.agent_policy

    @classmethod
    def initialize(cls, config: LocalDaemonConfig) -> None:
        """Create fresh owner-private roots; existing/legacy roots are rejected."""

        if config.coordinator_root.exists() or config.agent_root.exists():
            raise QueueServiceError(
                "local daemon requires fresh roots; migration and compatibility "
                "with existing managed-local state are unsupported"
            )
        _initialize_root(config.coordinator_root, role="coordinator")
        try:
            with sqlite3.connect(config.control_database) as conn:
                conn.execute(
                    "INSERT INTO daemon_metadata(key, value) "
                    "VALUES ('scheduling_epoch', ?)",
                    (f"scheduling-epoch-{uuid4()}",),
                )
                conn.execute(
                    "INSERT INTO daemon_metadata(key, value) "
                    "VALUES ('scheduling_fingerprint', ?)",
                    (_scheduling_fingerprint(config),),
                )
                conn.commit()
            cls.initialize_agent_root(config.agent_root)
            from ._agent_process_supervisor import (
                AgentProcessSupervisorService,
                SupervisorLaunchConfiguration,
            )

            agent_id = _open_root(config.agent_root, role="local-agent")
            AgentProcessSupervisorService.initialize(
                config.agent_root,
                configuration=SupervisorLaunchConfiguration(
                    agent_id, (config.resident_worker_launch_profile,)
                ),
            )
            from .local_daemon_execution import initialize_local_daemon_owner_stores

            initialize_local_daemon_owner_stores(
                config,
                coordinator_id=_open_root(config.coordinator_root, role="coordinator"),
                agent_id=agent_id,
            )
        except Exception:
            raise

    @classmethod
    def initialize_agent_root(cls, root: Path) -> None:
        """Create one fresh protected agent root for an outbound agent owner."""
        path = Path(root)
        if path.exists():
            raise QueueServiceError("remote agent requires a fresh root")
        _initialize_root(path, role="local-agent")
        from loom.queue._managed_local import SQLiteAgentJournal
        SQLiteAgentJournal(path / "journal.sqlite")._initialize()
        (path / "journal.sqlite").chmod(0o600)

    def start(self) -> LocalDaemonStatus:
        if self._coordinator_lock is not None:
            raise QueueServiceError("local daemon is already started")
        _validate_distinct_roots(self.config)
        coordinator_lock = _acquire_lock(self.config.coordinator_root)
        try:
            agent_lock = _acquire_lock(self.config.agent_root)
        except Exception:
            coordinator_lock.close()
            raise
        try:
            coordinator_id = _open_root(
                self.config.coordinator_root, role="coordinator"
            )
            agent_id = _open_root(self.config.agent_root, role="local-agent")
            from ._agent_process_supervisor import (
                AgentProcessSupervisorClient,
                SupervisorLaunchConfiguration,
            )

            AgentProcessSupervisorClient(
                self.config.agent_root,
                SupervisorLaunchConfiguration(
                    agent_id, (self.config.resident_worker_launch_profile,)
                ),
            )
            self._coordinator_id = coordinator_id
            self._agent_id = agent_id
            epoch = f"coordinator-epoch-{uuid4()}"
            with self._connection() as conn:
                scheduling = {
                    str(row["key"]): str(row["value"])
                    for row in conn.execute(
                        "SELECT key, value FROM daemon_metadata WHERE key IN "
                        "('scheduling_epoch', 'scheduling_fingerprint')"
                    )
                }
                if scheduling.get("scheduling_fingerprint") != _scheduling_fingerprint(
                    self.config
                ):
                    raise QueueConflictError(
                        "protected scheduling configuration changed without reload"
                    )
                scheduling_epoch = scheduling.get("scheduling_epoch")
                if scheduling_epoch is None:
                    raise QueueStorageError("scheduling epoch is unavailable")
                conn.execute(
                    "INSERT INTO coordinator_epochs (epoch, started_at) VALUES (?, ?)",
                    (epoch, self._accepted_time(conn)),
                )
                conn.commit()
        except Exception:
            agent_lock.close()
            coordinator_lock.close()
            self._coordinator_id = None
            self._agent_id = None
            self._scheduling_epoch = None
            raise
        assignment_workers = ThreadPoolExecutor(
            max_workers=self.config.cpu_capacity,
            thread_name_prefix="loom-local-assignment",
        )
        from .local_daemon_execution import LocalDaemonExecution

        try:
            execution = LocalDaemonExecution(
                config=self.config,
                coordinator_id=coordinator_id,
                agent_id=agent_id,
                coordinator_epoch=epoch,
                scheduling_epoch=scheduling_epoch,
                cancellation_operation=self._cancellation_operation_id,
                admission_activated=self._activate_admission,
                daemon=self,
            )
        except Exception:
            assignment_workers.shutdown(wait=True)
            agent_lock.close()
            coordinator_lock.close()
            self._coordinator_id = None
            self._agent_id = None
            raise QueueServiceError(
                "retained daemon owner state is unavailable"
            ) from None
        thread = Thread(
            target=self._serve,
            name="loom-local-daemon-runtime",
            daemon=True,
        )
        self._coordinator_lock = coordinator_lock
        self._agent_lock = agent_lock
        self._coordinator_id = coordinator_id
        self._agent_id = agent_id
        self._epoch = epoch
        self._scheduling_epoch = scheduling_epoch
        self._service_error = None
        self._stop.clear()
        self._wake.set()
        self._assignment_workers = assignment_workers
        self._execution = execution
        self._thread = thread
        try:
            thread.start()
        except Exception:
            self.stop()
            raise
        return self.status()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join()
        assignment_workers = self._assignment_workers
        self._assignment_workers = None
        if assignment_workers is not None:
            assignment_workers.shutdown(wait=True)
        self._assignment_futures.clear()
        self._execution = None
        for lock in (self._agent_lock, self._coordinator_lock):
            if lock is not None:
                lock.close()  # type: ignore[union-attr]
        self._coordinator_lock = None
        self._agent_lock = None
        self._coordinator_id = None
        self._agent_id = None
        self._epoch = None
        self._scheduling_epoch = None

    def client_view(self, principal: LocalDaemonPrincipal) -> "LocalDaemonClientView":
        return LocalDaemonClientView(self, principal)

    def operator_view(
        self, principal: LocalDaemonPrincipal
    ) -> "LocalDaemonOperatorView":
        return LocalDaemonOperatorView(self, principal)

    def agent_view(self, principal: LocalDaemonPrincipal) -> AgentSessionView:
        """Return the restricted authenticated agent view for a trusted principal."""
        return AgentSessionView(self, principal)

    def slurm_bootstrap_view(
        self, principal: LocalDaemonPrincipal
    ) -> "LocalDaemonSlurmBootstrapView":
        """Return the assignment-scoped fixed-bootstrap application view."""

        return LocalDaemonSlurmBootstrapView(self, principal)

    def replace_agent_policy(self, policy: AgentPolicyConfig) -> None:
        """Install a new protected policy; later operations re-authorize it."""
        if not isinstance(policy, AgentPolicyConfig):
            raise QueueServiceError("agent policy is invalid")
        slurm_credentials = {
            profile.credential_reference for profile in self.config.slurm_profiles
        }
        policy_credentials = {
            item.credential_id for item in (*policy.agents, *policy.principals)
        }
        if slurm_credentials & policy_credentials:
            raise QueueServiceError(
                "SLURM bootstrap credentials must remain role-exclusive"
            )
        self._agent_policy = policy

    def _require_view_role(
        self, principal: LocalDaemonPrincipal, role: LocalDaemonRole
    ) -> None:
        from .agent_sessions import ScopedAuthorizer

        ScopedAuthorizer(self._agent_policy).require_role(principal, role.value)

    def status(self) -> LocalDaemonStatus:
        coordinator_id = self._require_started()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            accepted_time = self._accepted_time(conn)
            admissions = tuple(
                _admission_from_row(row)
                for row in conn.execute(
                    "SELECT * FROM managed_admissions "
                    "ORDER BY accepted_at, admission_id"
                )
            )
            revision_row = conn.execute(
                "SELECT revision FROM owner_status_revisions WHERE owner = 'admission'"
            ).fetchone()
            if revision_row is None:
                raise QueueStorageError("coordinator admission status is unavailable")
            admission_revision = int(revision_row["revision"])
            controls: list[Mapping[str, PlainData]] = []
            for row in conn.execute(
                "SELECT principal_id, request_json, state, result_code, "
                "effect_json, acknowledged FROM agent_controls ORDER BY operation_id"
            ):
                request = AgentControl.from_value(json.loads(str(row["request_json"])))
                effect = (
                    None
                    if row["effect_json"] is None
                    else AgentControlEffect.from_value(
                        json.loads(str(row["effect_json"]))
                    )
                )
                controls.append(
                    freeze_plain_data(
                        {
                            "owner": "agent-control",
                            "operation_id": request.operation_id,
                            "principal": str(row["principal_id"]),
                            "kind": request.kind.value,
                            "agent_id": request.agent_id,
                            "session_id": request.expected_session_id,
                            "pool": request.pool,
                            "cancel_active": request.cancel_active,
                            "state": str(row["state"]),
                            "code": row["result_code"],
                            "config_revision": (
                                None if effect is None else effect.config_revision
                            ),
                            "inventory_revision": (
                                None if effect is None else effect.inventory_revision
                            ),
                            "availability_revision": (
                                None if effect is None else effect.availability_revision
                            ),
                            "acknowledged": bool(row["acknowledged"]),
                        },
                        path="agent control status",
                    )
                )
            for row in conn.execute(
                "SELECT principal_id, request_json, state, result_code, "
                "scheduling_epoch FROM scheduling_reloads ORDER BY operation_id"
            ):
                request = CoordinatorSchedulingReload.from_dict(
                    json.loads(str(row["request_json"]))
                )
                controls.append(
                    freeze_plain_data(
                        {
                            "owner": "coordinator-scheduling",
                            "operation_id": request.operation_id,
                            "principal": str(row["principal_id"]),
                            "state": str(row["state"]),
                            "code": row["result_code"],
                            "scheduling_epoch": row["scheduling_epoch"],
                        },
                        path="scheduling reload status",
                    )
                )
            for row in conn.execute(
                "SELECT request_json, state, result_code, acknowledged "
                "FROM remote_assignment_controls ORDER BY operation_id"
            ):
                from .agent_sessions import AgentAssignmentControl

                request = AgentAssignmentControl.from_value(
                    json.loads(str(row["request_json"]))
                )
                controls.append(
                    freeze_plain_data(
                        {
                            "owner": "remote-assignment-control",
                            "operation_id": request.operation_id,
                            "session_id": request.session_id,
                            "assignment_id": request.assignment_id,
                            "state": str(row["state"]),
                            "code": row["result_code"],
                            "acknowledged": bool(row["acknowledged"]),
                        },
                        path="remote assignment control status",
                    )
                )
            conn.commit()
        from .local_daemon_execution import (
            build_local_daemon_owner_views,
            local_daemon_owner_stores_available,
        )

        views = build_local_daemon_owner_views(
            self.config,
            admissions,
            coordinator_id=coordinator_id,
            agent_id=self._require_agent_id(),
            clock=self._clock,
            admission_revision=admission_revision,
        )
        unavailable = not local_daemon_owner_stores_available(
            self.config,
            coordinator_id=coordinator_id,
            agent_id=self._require_agent_id(),
        ) or any(
            any(
                isinstance(axis, Mapping) and axis.get("availability") == "unavailable"
                for axis in view.values()
            )
            for view in views
        )
        as_of = self._clock()
        parse_timestamp(as_of)
        return LocalDaemonStatus(
            coordinator_id=coordinator_id,
            coordinator_epoch=self._epoch or "",
            as_of=as_of,
            accepted_time=accepted_time,
            service_health=(
                "healthy"
                if self._service_error is None and not unavailable
                else "degraded"
            ),
            service_diagnostic=(
                "owner_status_unavailable" if unavailable else self._service_error
            ),
            scheduling_epoch=self._scheduling_epoch or "",
            admissions=admissions,
            controls=tuple(controls),
            runs=views,
        )

    def reconcile_once(self) -> tuple[LocalDaemonAdmission, ...]:
        """Drive each admission through authority, orchestration, and execution."""

        self._require_started()
        with self._cycle_lock:
            execution = self._execution
            assignment_workers = self._assignment_workers
            if execution is None or assignment_workers is None:
                raise QueueServiceError("local daemon assignment supervisor is absent")
            execution.open_owner_stores()
            self._harvest_assignment_futures()
            with self._connection() as conn:
                admissions = tuple(
                    _admission_from_row(row)
                    for row in conn.execute(
                        "SELECT * FROM managed_admissions "
                        "WHERE state NOT IN (?, ?, ?, ?) "
                        "ORDER BY accepted_at, admission_id",
                        (
                            LocalDaemonAdmissionState.SUCCEEDED.value,
                            LocalDaemonAdmissionState.FAILED.value,
                            LocalDaemonAdmissionState.CANCELLED.value,
                            LocalDaemonAdmissionState.BLOCKED.value,
                        ),
                    )
                )
            for admission in admissions:
                if admission.admission_id in self._assignment_futures:
                    continue
                future = assignment_workers.submit(execution.advance, admission)
                future.add_done_callback(lambda _future: self._wake.set())
                self._assignment_futures[admission.admission_id] = future
            self._harvest_assignment_futures()
            return self.status().admissions

    def _harvest_assignment_futures(self) -> None:
        for admission_id, future in tuple(self._assignment_futures.items()):
            if not future.done():
                continue
            del self._assignment_futures[admission_id]
            try:
                outcome = future.result()
            except QueueConflictError:
                self._set_state(
                    admission_id,
                    LocalDaemonAdmissionState.BLOCKED,
                    reason="authority_or_intent_conflict",
                )
            except Exception:  # outages stay replayable and visible
                self._service_error = "reconciliation_unavailable"
            else:
                self._service_error = None
                self._set_state(
                    admission_id,
                    outcome.state,
                    reason=outcome.reason,
                )

    def _serve(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.reconcile_once()
            except Exception:  # keep the durable owner alive and diagnosable
                self._service_error = "reconciliation_unavailable"
            self._wake.wait(self.config.poll_interval_seconds)

    def _submit(self, request: LocalDaemonAdmissionRequest) -> LocalDaemonAdmission:
        coordinator_id = self._require_started()
        from .local_daemon_execution import load_managed_local_intent

        with self._cycle_lock:
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
                    return existing
                raise QueueConflictError("managed run admission intent conflicts")
            if other is not None:
                raise QueueConflictError(
                    "queue item identity already admits another run"
                )

            intent = load_managed_local_intent(self.config, request.run_uri)
            execution.validate_fresh_intent(intent)
            admission_id = f"admission-{uuid4()}"
            operation_id = f"authority-bind-{uuid4()}"
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                accepted_at = self._accepted_time(conn)
                conn.execute(
                    """
                    INSERT INTO managed_admissions (
                        admission_id, queue_item_id, coordinator_id, run_uri,
                        intent_digest, execution_owner, state, accepted_at,
                        authority_operation_id, cancellation_operation_id,
                        blocked_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
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
                    ),
                )
                conn.commit()
        self._wake.set()
        return self._admission(admission_id)

    def _cancel(self, queue_item_id: str, *, principal_id: str) -> LocalDaemonAdmission:
        self._require_started()
        if not isinstance(principal_id, str) or not principal_id:
            raise QueueServiceError("cancellation principal is required")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE queue_item_id = ?",
                (queue_item_id,),
            ).fetchone()
            if row is None:
                raise QueueServiceError("managed admission was not found")
            admission = _admission_from_row(row)
            if admission.state in {
                LocalDaemonAdmissionState.SUCCEEDED,
                LocalDaemonAdmissionState.FAILED,
                LocalDaemonAdmissionState.CANCELLED,
            }:
                conn.commit()
                return admission
            operation_id = admission.cancellation_operation_id or (
                f"authority-cancel-{uuid4()}"
            )
            conn.execute(
                "UPDATE managed_admissions SET state = ?, "
                "cancellation_operation_id = ?, "
                "cancellation_principal_id = COALESCE("
                "cancellation_principal_id, ?), blocked_reason = NULL "
                "WHERE admission_id = ?",
                (
                    LocalDaemonAdmissionState.CANCELLATION_REQUESTED.value,
                    operation_id,
                    principal_id,
                    admission.admission_id,
                ),
            )
            conn.commit()
        self._wake.set()
        return self._admission(admission.admission_id)

    def _control_agent(
        self, principal: LocalDaemonPrincipal, control: AgentControl
    ) -> Mapping[str, PlainData]:
        """Commit one scoped control before the outbound agent may observe it."""

        from .agent_sessions import ScopedAuthorizer

        authorizer = ScopedAuthorizer(self._agent_policy)
        authorizer.require_operator(
            principal,
            control.kind.value,
            agent_id=control.agent_id,
            pool=control.pool,
        )
        if control.cancel_active:
            authorizer.require_operator(
                principal,
                "cancel_active",
                agent_id=control.agent_id,
                pool=control.pool,
            )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session = conn.execute(
                "SELECT session_id, agent_id, config_revision, pools_json, state "
                "FROM agent_sessions WHERE session_id = ?",
                (control.expected_session_id,),
            ).fetchone()
            if session is None or str(session["state"]) != "ACTIVE":
                raise QueueConflictError("agent control session is stale")
            if (
                str(session["agent_id"]) != control.agent_id
                or str(session["config_revision"]) != control.expected_config_revision
            ):
                raise QueueConflictError("agent control revision is stale")
            pools = json.loads(str(session["pools_json"]))
            if control.pool is not None and control.pool not in pools:
                raise QueueServiceError("agent control pool is not authorized")
            if control.pool is not None and set(pools) != {control.pool}:
                raise QueueServiceError(
                    "pool-scoped control requires an independently controllable agent"
                )
            encoded = json.dumps(control.value(), sort_keys=True, separators=(",", ":"))
            prior = conn.execute(
                "SELECT principal_id, request_json, state, result_code FROM agent_controls "
                "WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            if prior is not None:
                if (
                    str(prior["principal_id"]) != principal.subject
                    or str(prior["request_json"]) != encoded
                ):
                    raise QueueConflictError("agent control operation conflicts")
                conn.commit()
                return freeze_plain_data(
                    {
                        "operation_id": control.operation_id,
                        "state": str(prior["state"]),
                        "code": prior["result_code"],
                    },
                    path="agent control receipt",
                )
            active = conn.execute(
                "SELECT operation_id FROM agent_controls WHERE session_id = ? "
                "AND state IN ('pending_delivery', 'applying') LIMIT 1",
                (control.expected_session_id,),
            ).fetchone()
            if active is not None:
                raise QueueConflictError("another agent control is still in progress")
            conn.execute(
                "INSERT INTO agent_controls(operation_id, principal_id, session_id, agent_id, request_json, state, result_code, acknowledged) VALUES (?, ?, ?, ?, ?, 'pending_delivery', NULL, 0)",
                (
                    control.operation_id,
                    principal.subject,
                    control.expected_session_id,
                    control.agent_id,
                    encoded,
                ),
            )
            # Withdrawal is coordinator-owned and happens before delivery.  It
            # changes only future offers; it never releases a durable claim.
            if control.kind.value in {"drain", "reload"}:
                conn.execute(
                    "UPDATE agent_offers SET current = 0 WHERE session_id = ?",
                    (control.expected_session_id,),
                )
                conn.execute(
                    "UPDATE agent_polls SET active = 0 WHERE session_id = ?",
                    (control.expected_session_id,),
                )
            if control.cancel_active:
                run_rows = tuple(
                    conn.execute(
                        "SELECT DISTINCT run_uri FROM remote_assignments "
                        "WHERE session_id = ? AND state != 'RELEASED'",
                        (control.expected_session_id,),
                    )
                )
                for run_row in run_rows:
                    run_uri = str(run_row["run_uri"])
                    cancellation_operation_id = (
                        "agent-control-cancel-"
                        + hashlib.sha256(
                            f"{control.operation_id}\0{run_uri}".encode()
                        ).hexdigest()
                    )
                    conn.execute(
                        "UPDATE managed_admissions SET state = ?, "
                        "cancellation_operation_id = COALESCE("
                        "cancellation_operation_id, ?), "
                        "cancellation_principal_id = COALESCE("
                        "cancellation_principal_id, ?), blocked_reason = NULL "
                        "WHERE run_uri = ? AND state NOT IN (?, ?, ?)",
                        (
                            LocalDaemonAdmissionState.CANCELLATION_REQUESTED.value,
                            cancellation_operation_id,
                            principal.subject,
                            run_uri,
                            LocalDaemonAdmissionState.SUCCEEDED.value,
                            LocalDaemonAdmissionState.FAILED.value,
                            LocalDaemonAdmissionState.CANCELLED.value,
                        ),
                    )
            conn.commit()
        self._wake.set()
        return freeze_plain_data(
            {
                "operation_id": control.operation_id,
                "state": "pending_delivery",
                "code": None,
            },
            path="agent control receipt",
        )

    def _reload_scheduling(
        self,
        principal: LocalDaemonPrincipal,
        request: CoordinatorSchedulingReload,
    ) -> Mapping[str, PlainData]:
        """Install one complete protected coordinator scheduling epoch."""

        from .agent_sessions import ScopedAuthorizer

        ScopedAuthorizer(self._agent_policy).require_operator(
            principal, "scheduling_reload"
        )
        encoded = json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._cycle_lock:
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                prior = conn.execute(
                    "SELECT principal_id, request_json, state, result_code, "
                    "scheduling_epoch FROM scheduling_reloads WHERE operation_id = ?",
                    (request.operation_id,),
                ).fetchone()
                if prior is not None:
                    if (
                        str(prior["principal_id"]) != principal.subject
                        or str(prior["request_json"]) != encoded
                    ):
                        raise QueueConflictError(
                            "scheduling reload operation conflicts"
                        )
                    conn.commit()
                    return freeze_plain_data(
                        {
                            "operation_id": request.operation_id,
                            "state": str(prior["state"]),
                            "code": prior["result_code"],
                            "scheduling_epoch": prior["scheduling_epoch"],
                        },
                        path="scheduling reload receipt",
                    )
                if request.expected_scheduling_epoch != self._scheduling_epoch:
                    raise QueueConflictError("scheduling reload epoch is stale")
                conn.execute(
                    "INSERT INTO scheduling_reloads(operation_id, principal_id, "
                    "request_json, state, result_code, scheduling_epoch) "
                    "VALUES (?, ?, ?, 'applying', NULL, NULL)",
                    (request.operation_id, principal.subject, encoded),
                )
                conn.commit()

            try:
                loader = self._trusted_scheduling_loader
                if loader is None:
                    raise QueueServiceError(
                        "trusted scheduling configuration loader is unavailable"
                    )
                replacement = loader()
                self._validate_scheduling_replacement(replacement)
                execution = self._execution
                if execution is None:
                    raise QueueServiceError("coordinator execution is unavailable")
                next_epoch = (
                    "scheduling-epoch-"
                    + hashlib.sha256(
                        (
                            request.operation_id
                            + "\0"
                            + _scheduling_fingerprint(replacement)
                        ).encode()
                    ).hexdigest()
                )
            except Exception:
                return self._reject_scheduling_reload(operation_id=request.operation_id)
            with execution.scheduling_reload_guard():
                try:
                    reload_plan = execution.prepare_scheduling_reload(
                        replacement, next_epoch
                    )
                except Exception:
                    return self._reject_scheduling_reload(
                        operation_id=request.operation_id
                    )
                with self._connection() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                        "VALUES ('scheduling_epoch', ?)",
                        (next_epoch,),
                    )
                    conn.execute(
                        "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                        "VALUES ('scheduling_fingerprint', ?)",
                        (_scheduling_fingerprint(replacement),),
                    )
                    conn.execute(
                        "UPDATE scheduling_reloads SET state = 'applied', "
                        "result_code = 'applied', scheduling_epoch = ? "
                        "WHERE operation_id = ?",
                        (next_epoch, request.operation_id),
                    )
                    conn.commit()
                execution.apply_scheduling_reload(replacement, reload_plan)
                self.config = replacement
                self._agent_policy = replacement.agent_policy
                self._scheduling_epoch = next_epoch
        self._wake.set()
        return freeze_plain_data(
            {
                "operation_id": request.operation_id,
                "state": "applied",
                "code": "applied",
                "scheduling_epoch": next_epoch,
            },
            path="scheduling reload receipt",
        )

    def _reject_scheduling_reload(
        self, *, operation_id: str
    ) -> Mapping[str, PlainData]:
        with self._connection() as conn:
            conn.execute(
                "UPDATE scheduling_reloads SET state = 'failed', "
                "result_code = 'reload_rejected', scheduling_epoch = ? "
                "WHERE operation_id = ?",
                (self._scheduling_epoch, operation_id),
            )
            conn.commit()
        return freeze_plain_data(
            {
                "operation_id": operation_id,
                "state": "failed",
                "code": "reload_rejected",
                "scheduling_epoch": self._scheduling_epoch,
            },
            path="scheduling reload receipt",
        )

    def _validate_scheduling_replacement(self, replacement: LocalDaemonConfig) -> None:
        if not isinstance(replacement, LocalDaemonConfig):
            raise QueueServiceError("trusted scheduling configuration is invalid")
        immutable = (
            "coordinator_root",
            "agent_root",
            "run_store_root",
            "machine_id",
            "cpu_capacity",
            "memory_capacity_bytes",
            "gpu_devices",
            "poll_interval_seconds",
        )
        if any(
            getattr(replacement, name) != getattr(self.config, name)
            for name in immutable
        ):
            raise QueueConflictError(
                "scheduling reload cannot replace process or agent-owned configuration"
            )
        if replacement.agent_policy != self._agent_policy:
            with self._connection() as conn:
                active = conn.execute(
                    "SELECT 1 FROM agent_sessions WHERE state = 'ACTIVE' LIMIT 1"
                ).fetchone()
            if active is not None:
                raise QueueConflictError(
                    "scheduling reload cannot replace credentials for a live agent session"
                )

    def _wait(
        self, queue_item_id: str, *, timeout_seconds: float | None
    ) -> LocalDaemonAdmission:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise QueueServiceError("timeout_seconds must be non-negative")
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        terminal = {
            LocalDaemonAdmissionState.SUCCEEDED,
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
            LocalDaemonAdmissionState.BLOCKED,
        }
        while True:
            admission = self._admission_for_queue_item(queue_item_id)
            if admission.state in terminal:
                return admission
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    "managed local admission did not reach terminal state"
                )
            self._wake.set()
            time.sleep(min(self.config.poll_interval_seconds, 0.05))

    def _cancellation_operation_id(self, admission_id: str) -> str | None:
        return self._admission(admission_id).cancellation_operation_id

    def _activate_admission(self, admission_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE managed_admissions SET state = ?, blocked_reason = NULL "
                "WHERE admission_id = ? AND cancellation_operation_id IS NULL "
                "AND state IN (?, ?, ?)",
                (
                    LocalDaemonAdmissionState.ACTIVE.value,
                    admission_id,
                    LocalDaemonAdmissionState.PENDING_AUTHORITY.value,
                    LocalDaemonAdmissionState.WAITING.value,
                    LocalDaemonAdmissionState.ACTIVE.value,
                ),
            )
            conn.commit()

    def _admission_for_queue_item(self, queue_item_id: str) -> LocalDaemonAdmission:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE queue_item_id = ?",
                (queue_item_id,),
            ).fetchone()
        if row is None:
            raise QueueServiceError("managed admission was not found")
        return _admission_from_row(row)

    def _admission(self, admission_id: str) -> LocalDaemonAdmission:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE admission_id = ?",
                (admission_id,),
            ).fetchone()
        if row is None:
            raise QueueServiceError("managed admission was not found")
        return _admission_from_row(row)

    def _set_state(
        self,
        admission_id: str,
        state: LocalDaemonAdmissionState,
        *,
        reason: str | None,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE managed_admissions SET state = ?, blocked_reason = ? "
                "WHERE admission_id = ?",
                (state.value, reason, admission_id),
            )
            conn.commit()

    def _require_started(self) -> str:
        if self._coordinator_lock is None or self._coordinator_id is None:
            raise QueueServiceError("local daemon is not started")
        return self._coordinator_id

    def _require_agent_id(self) -> str:
        if self._agent_lock is None or self._agent_id is None:
            raise QueueServiceError("local daemon is not started")
        return self._agent_id

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            conn = sqlite3.connect(
                f"{self.config.control_database.resolve().as_uri()}?mode=rw",
                uri=True,
                timeout=30,
            )
            conn.row_factory = sqlite3.Row
            expected = self._coordinator_id
            if expected is not None:
                row = conn.execute(
                    "SELECT value FROM root_metadata WHERE key = 'stable_id'"
                ).fetchone()
                if row is None or str(row["value"]) != expected:
                    raise QueueStorageError("coordinator control identity is invalid")
        except (OSError, sqlite3.Error):
            # A missing retained control store is unavailable.  Once a file is
            # present under a live locked root, however, an open/query failure
            # cannot prove that it is the stable coordinator store; report the
            # same fail-closed identity diagnostic as an explicit mismatch.
            diagnostic = (
                "coordinator control identity is invalid"
                if self._coordinator_id is not None
                and self.config.control_database.is_file()
                else "coordinator control state is unavailable"
            )
            raise QueueStorageError(diagnostic) from None
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _agent_connection(self) -> Iterator[sqlite3.Connection]:
        try:
            conn = sqlite3.connect(
                f"{self.config.agent_root.joinpath('control.sqlite').resolve().as_uri()}?mode=rw",
                uri=True,
                timeout=30,
            )
            conn.row_factory = sqlite3.Row
            expected = self._agent_id
            if expected is not None:
                row = conn.execute(
                    "SELECT value FROM root_metadata WHERE key = 'stable_id'"
                ).fetchone()
                if row is None or str(row["value"]) != expected:
                    raise QueueStorageError("agent control identity is invalid")
        except (OSError, sqlite3.Error):
            raise QueueStorageError("agent control state is unavailable") from None
        try:
            yield conn
        finally:
            conn.close()

    def _accepted_time(self, conn: sqlite3.Connection) -> str:
        now = self._clock()
        parse_timestamp(now)
        row = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = 'accepted_time'"
        ).fetchone()
        previous = None if row is None else str(row["value"])
        if previous is not None and parse_timestamp(now) < parse_timestamp(previous):
            raise QueueServiceError(
                "coordinator accepted-time regressed; scheduling is degraded"
            )
        accepted = previous if previous is not None and previous > now else now
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) "
            "VALUES ('accepted_time', ?)",
            (accepted,),
        )
        return accepted

    def _accepted_snapshot(self) -> tuple[str, int]:
        """Return one monotonic accepted timestamp and whole-second snapshot time."""

        with self._connection() as conn:
            accepted = self._accepted_time(conn)
            conn.commit()
        return accepted, int(parse_timestamp(accepted).timestamp())


@dataclass(frozen=True, slots=True)
class LocalDaemonClientView:
    _daemon: LocalDaemon
    _principal: LocalDaemonPrincipal

    def submit(self, request: LocalDaemonAdmissionRequest) -> LocalDaemonAdmission:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._submit(request)

    def status(self) -> LocalDaemonStatus:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.status()

    def wait(
        self, queue_item_id: str, *, timeout_seconds: float | None = None
    ) -> LocalDaemonAdmission:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._wait(queue_item_id, timeout_seconds=timeout_seconds)

    def cancel(self, queue_item_id: str) -> LocalDaemonAdmission:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._cancel(queue_item_id, principal_id=self._principal.subject)


@dataclass(frozen=True, slots=True)
class LocalDaemonOperatorView:
    _daemon: LocalDaemon
    _principal: LocalDaemonPrincipal

    def status(self) -> LocalDaemonStatus:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon.status()

    def reconcile_once(self) -> tuple[LocalDaemonAdmission, ...]:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon.reconcile_once()

    def control_agent(self, control: AgentControl) -> Mapping[str, PlainData]:
        return self._daemon._control_agent(self._principal, control)

    def reload_scheduling(
        self, request: CoordinatorSchedulingReload
    ) -> Mapping[str, PlainData]:
        return self._daemon._reload_scheduling(self._principal, request)


@dataclass(frozen=True, slots=True)
class LocalDaemonSlurmBootstrapView:
    """Least-privilege view for one protected SLURM profile credential."""

    _daemon: LocalDaemon
    _principal: LocalDaemonPrincipal

    def _execution(self):  # type: ignore[no-untyped-def]
        _require_role(self._principal, LocalDaemonRole.SLURM_BOOTSTRAP)
        execution = self._daemon._execution
        if execution is None:
            raise QueueServiceError("SLURM coordinator execution is unavailable")
        return execution

    def handshake(self) -> Mapping[str, PlainData]:
        execution = self._execution()
        profile = execution._slurm_profile_for_principal(
            self._principal.subject, self._principal.credential_id
        )
        return freeze_plain_data(
            {
                "protocol_version": "1",
                "capabilities": ["slurm-ready-stage-bootstrap-v1"],
                "coordinator_id": self._daemon._require_started(),
                "coordinator_epoch": self._daemon._epoch or "",
                "role": LocalDaemonRole.SLURM_BOOTSTRAP.value,
                "profile_id": profile.profile_id,
                "profile_descriptor": profile.descriptor.to_dict(),
                "credential_policy_revision": profile.credential_policy_revision,
            },
            path="SLURM bootstrap handshake",
        )

    def register(
        self,
        *,
        operation_id: str,
        request_digest: str,
        job_id: str,
        cluster: str | None,
        incarnation: str,
        capability: str,
    ) -> Mapping[str, PlainData]:
        record = self._execution().slurm_register(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            operation_id=operation_id,
            request_digest=request_digest,
            job_id=job_id,
            cluster=cluster,
            incarnation=incarnation,
            capability=capability,
        )
        return freeze_plain_data(
            {
                "assignment_id": record.assignment.assignment_id,
                "operation_id": record.assignment.operation_id,
                "issuer_epoch": record.issuer_epoch,
                "job_id": record.job_id,
                "cluster": record.cluster,
                "incarnation": record.bootstrap_incarnation,
                "delivery": record.delivery.to_dict(),
            },
            path="SLURM bootstrap registration",
        )

    def input_chunk(
        self,
        assignment_id: str,
        incarnation: str,
        transfer_id: str,
        *,
        offset: int,
    ) -> tuple[bytes, bool]:
        return self._execution().slurm_input_chunk(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            transfer_id=transfer_id,
            offset=offset,
        )

    def inputs_ready(self, assignment_id: str, incarnation: str) -> None:
        self._execution().slurm_inputs_ready(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
        )

    def grant(self, assignment_id: str, incarnation: str) -> str:
        return self._execution().slurm_grant(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
        )

    def start_permit(self, assignment_id: str, incarnation: str, fence: str) -> bool:
        return self._execution().slurm_start_permit(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            fence=fence,
        )

    def started(
        self,
        assignment_id: str,
        incarnation: str,
        fence: str,
        process_execution_id: str,
    ) -> None:
        self._execution().slurm_started(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            fence=fence,
            process_execution_id=process_execution_id,
        )

    def declare_report(
        self,
        assignment_id: str,
        incarnation: str,
        fence: str,
        report: object,
    ) -> None:
        from ._remote_stage_execution import _RemoteExecutionReport

        parsed = (
            report
            if isinstance(report, _RemoteExecutionReport)
            else _RemoteExecutionReport.from_dict(report)
        )
        self._execution().slurm_declare_report(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            fence=fence,
            report=parsed,
        )

    def output_chunk(
        self,
        assignment_id: str,
        incarnation: str,
        transfer_id: str,
        *,
        offset: int,
        data: bytes,
        final: bool,
    ) -> int:
        return self._execution().slurm_output_chunk(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            transfer_id=transfer_id,
            offset=offset,
            data=data,
            final=final,
        )

    def commit_result(self, assignment_id: str, incarnation: str, fence: str) -> None:
        self._execution().slurm_commit_result(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            fence=fence,
        )

    def release(self, assignment_id: str, incarnation: str) -> None:
        self._execution().slurm_release(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
        )


def _require_role(principal: LocalDaemonPrincipal, role: LocalDaemonRole) -> None:
    if principal.role is not role:
        raise QueueServiceError("daemon principal is not authorized for this operation")


def _initialize_root(path: Path, *, role: str) -> None:
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    database = path / "control.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE root_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO root_metadata (key, value) VALUES ('role', ?)", (role,)
        )
        conn.execute(
            "INSERT INTO root_metadata (key, value) VALUES ('stable_id', ?)",
            (f"{role}-{uuid4()}",),
        )
        conn.execute(f"PRAGMA user_version = {_LOCAL_DAEMON_SCHEMA_VERSION}")
        if role == "coordinator":
            conn.execute(
                "CREATE TABLE daemon_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE coordinator_epochs "
                "(epoch TEXT PRIMARY KEY, started_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE owner_status_revisions "
                "(owner TEXT PRIMARY KEY, revision INTEGER NOT NULL)"
            )
            conn.execute(
                "INSERT INTO owner_status_revisions(owner, revision) "
                "VALUES ('admission', 0)"
            )
            conn.execute(
                """
                CREATE TABLE managed_admissions (
                    admission_id TEXT PRIMARY KEY,
                    queue_item_id TEXT NOT NULL UNIQUE,
                    coordinator_id TEXT NOT NULL,
                    run_uri TEXT NOT NULL,
                    intent_digest TEXT NOT NULL,
                    execution_owner TEXT NOT NULL,
                    state TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    authority_operation_id TEXT NOT NULL,
                    cancellation_operation_id TEXT,
                    cancellation_principal_id TEXT,
                    blocked_reason TEXT,
                    UNIQUE(coordinator_id, run_uri)
                )
                """
            )
            conn.execute(
                "CREATE TABLE scheduling_reloads ("
                "operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
                "request_json TEXT NOT NULL, state TEXT NOT NULL, "
                "result_code TEXT, scheduling_epoch TEXT)"
            )
            conn.executescript(
                """
                CREATE TRIGGER admission_status_revision_insert
                    AFTER INSERT ON managed_admissions
                    BEGIN UPDATE owner_status_revisions
                        SET revision = revision + 1 WHERE owner = 'admission'; END;
                CREATE TRIGGER admission_status_revision_update
                    AFTER UPDATE ON managed_admissions
                    BEGIN UPDATE owner_status_revisions
                        SET revision = revision + 1 WHERE owner = 'admission'; END;
                """
            )
        initialize_agent_session_schema(conn, coordinator=role == "coordinator")
        conn.commit()
    database.chmod(0o600)


def _open_root(path: Path, *, role: str) -> str:
    _validate_private_directory(path)
    database = path / "control.sqlite"
    if not database.is_file():
        raise QueueServiceError(f"{role} root is missing control state")
    mode = stat.S_IMODE(database.stat().st_mode)
    if mode & 0o077:
        raise QueueStorageError(f"{role} root must be owner-permissioned")
    with sqlite3.connect(database) as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != _LOCAL_DAEMON_SCHEMA_VERSION:
            raise QueueStorageError(
                f"{role} daemon schema is unsupported; fresh roots are required"
            )
        validate_agent_session_schema(conn, coordinator=role == "coordinator")
        values = {
            str(row[0]): str(row[1])
            for row in conn.execute("SELECT key, value FROM root_metadata")
        }
    if values.get("role") != role or not values.get("stable_id"):
        raise QueueStorageError(f"{role} root identity is invalid")
    return values["stable_id"]


def _validate_private_directory(path: Path) -> None:
    if not path.is_dir():
        raise QueueServiceError(f"local daemon root is missing: {path}")
    details = path.stat()
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
        raise QueueStorageError("local daemon root must be owner-permissioned")


def _validate_distinct_roots(config: LocalDaemonConfig) -> None:
    if not config.coordinator_root.exists() or not config.agent_root.exists():
        raise QueueServiceError("local daemon initialized roots are missing")
    if (
        config.coordinator_root.resolve() == config.agent_root.resolve()
        or config.coordinator_root.stat().st_ino == config.agent_root.stat().st_ino
    ):
        raise QueueServiceError("coordinator and local-agent roots must not alias")


def _acquire_lock(root: Path):  # type: ignore[no-untyped-def]
    lock_path = root / "owner.lock"
    lock = lock_path.open("a+", encoding="utf-8")
    lock_path.chmod(0o600)
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock.close()
        raise QueueServiceError(f"local daemon role is already locked: {root}") from exc
    return lock


def _admission_from_row(row: sqlite3.Row) -> LocalDaemonAdmission:
    return LocalDaemonAdmission(
        admission_id=str(row["admission_id"]),
        queue_item_id=str(row["queue_item_id"]),
        coordinator_id=str(row["coordinator_id"]),
        run_uri=str(row["run_uri"]),
        intent_digest=str(row["intent_digest"]),
        execution_owner=str(row["execution_owner"]),
        state=LocalDaemonAdmissionState(str(row["state"])),
        accepted_at=str(row["accepted_at"]),
        authority_operation_id=str(row["authority_operation_id"]),
        cancellation_operation_id=(
            None
            if row["cancellation_operation_id"] is None
            else str(row["cancellation_operation_id"])
        ),
        cancellation_principal_id=(
            None
            if row["cancellation_principal_id"] is None
            else str(row["cancellation_principal_id"])
        ),
        blocked_reason=(
            None if row["blocked_reason"] is None else str(row["blocked_reason"])
        ),
    )


def _required_string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise QueueServiceError(f"{field} must be a non-empty string")
    return value


def _optional_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is not None and (not isinstance(value, str) or not value):
        raise QueueServiceError(f"{field} must be null or a non-empty string")
    return value


def _exact_fields(data: Mapping[str, object], fields: set[str], label: str) -> None:
    if set(data) != fields:
        raise QueueServiceError(
            f"{label} must contain exactly: {', '.join(sorted(fields))}"
        )


def _scheduling_fingerprint(config: LocalDaemonConfig) -> str:
    payload = {
        "machine_id": config.machine_id,
        "cpu_capacity": config.cpu_capacity,
        "memory_capacity_bytes": config.memory_capacity_bytes,
        "gpu_devices": [
            {
                "descriptor": item.descriptor.to_dict(),
                "binding_digest": hashlib.sha256(
                    item.binding_value.encode()
                ).hexdigest(),
            }
            for item in config.gpu_devices
        ],
        "agent_policy": repr(config.agent_policy),
        "resident_worker_launch_profile": {
            "project_root": str(config.resident_worker_launch_profile.project_root),
            "python_executable": str(
                config.resident_worker_launch_profile.python_executable
            ),
            "descriptor": config.resident_worker_launch_profile.descriptor,
        },
        "remote_profiles": [item.to_dict() for item in config.remote_profiles],
        "slurm_profiles": [
            {
                "profile_id": item.profile_id,
                "configuration_fingerprint": item.configuration_fingerprint,
                "available": item.available,
            }
            for item in config.slurm_profiles
        ],
        "scheduling_components": [
            item.to_dict() for item in config.scheduling_components.descriptors
        ],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return "scheduling-" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CoordinatorSchedulingReload",
    "LocalDaemon",
    "LocalDaemonAdmission",
    "LocalDaemonAdmissionRequest",
    "LocalDaemonAdmissionState",
    "AgentSessionView",
    "LocalDaemonClientView",
    "LocalDaemonConfig",
    "LocalDaemonSchedulingComponents",
    "LocalDaemonOperatorView",
    "LocalDaemonPrincipal",
    "LocalDaemonRole",
    "LocalDaemonStatus",
]
