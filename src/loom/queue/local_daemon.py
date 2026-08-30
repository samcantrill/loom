"""Persistent managed-execution coordinator with a protected local agent.

The daemon owns admission, process identity, and the production composition that
connects persisted run plans to the Stage 29 orchestrator and local assignment
saga. Clients provide only a queue identity and run URI.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import StrEnum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from threading import Event, RLock, Thread
import time
from typing import TYPE_CHECKING, Iterator, cast
from uuid import uuid4

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp, utc_timestamp
from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    HardConstraintEvaluator,
    PreferenceScorer,
    ResourcePlanner,
    SchedulingComponentDescriptor,
    SchedulingPolicy,
)

from .agent_sessions import (
    AgentControl,
    AgentPolicyConfig,
    AgentSessionView,
    SessionReplacementRequest,
    initialize_agent_session_schema,
    replace_agent_session,
    validate_agent_session_schema,
)
from ._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    ResidentWorkerLaunchProfile,
)
from ._managed_local import AgentResourceProvider
from ._remote_stage_execution import GpuDeviceDescriptor, ResidentProfileDescriptor
from .errors import QueueConflictError, QueueServiceError, QueueStorageError

if TYPE_CHECKING:
    from .local_daemon_execution import (
        LocalDaemonExecution,
        LocalDaemonExecutionOutcome,
    )


_LOCAL_DAEMON_SCHEMA_VERSION = 10
_MIN_RUN_PRIORITY = -1_000_000
_MAX_RUN_PRIORITY = 1_000_000
_MAX_ADMISSION_PAGE_SIZE = 100
_DEPLOYMENT_BINDING_FILE = "deployment-binding.json"


def _default_admission_priority(_run_uri: str) -> int:
    """The protected default policy grants no client-selected preference."""

    return 0


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


@dataclass(frozen=True, slots=True)
class TimeRecoveryRequest:
    """Operator-authorized recovery of one exact degraded clock revision."""

    operation_id: str
    expected_time_revision: int
    expected_coordinator_epoch: str
    reason: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "operation_id"),
            (self.expected_coordinator_epoch, "expected_coordinator_epoch"),
        ):
            if not isinstance(value, str) or not value or len(value) > 160:
                raise QueueServiceError(f"{name} must be a bounded non-empty string")
        if (
            isinstance(self.expected_time_revision, bool)
            or not isinstance(self.expected_time_revision, int)
            or self.expected_time_revision < 1
        ):
            raise QueueServiceError("expected time revision must be positive")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 512
        ):
            raise QueueServiceError("time recovery reason must be 1..512 characters")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "expected_time_revision": self.expected_time_revision,
            "expected_coordinator_epoch": self.expected_coordinator_epoch,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TimeRecoveryRequest":
        _exact_fields(
            data,
            {
                "operation_id",
                "expected_time_revision",
                "expected_coordinator_epoch",
                "reason",
            },
            "time recovery request",
        )
        return cls(
            operation_id=_required_string(data, "operation_id"),
            expected_time_revision=_required_int(data, "expected_time_revision"),
            expected_coordinator_epoch=_required_string(
                data, "expected_coordinator_epoch"
            ),
            reason=_required_string(data, "reason"),
        )


@dataclass(frozen=True, slots=True)
class TimeRecoveryReceipt:
    operation_id: str
    request_digest: str
    recovered_at: str
    previous_coordinator_epoch: str
    coordinator_epoch: str
    time_revision: int

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "request_digest": self.request_digest,
            "recovered_at": self.recovered_at,
            "previous_coordinator_epoch": self.previous_coordinator_epoch,
            "coordinator_epoch": self.coordinator_epoch,
            "time_revision": self.time_revision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TimeRecoveryReceipt":
        _exact_fields(
            data,
            {
                "operation_id",
                "request_digest",
                "recovered_at",
                "previous_coordinator_epoch",
                "coordinator_epoch",
                "time_revision",
            },
            "time recovery receipt",
        )
        receipt = cls(
            operation_id=_required_string(data, "operation_id"),
            request_digest=_required_string(data, "request_digest"),
            recovered_at=_required_string(data, "recovered_at"),
            previous_coordinator_epoch=_required_string(
                data, "previous_coordinator_epoch"
            ),
            coordinator_epoch=_required_string(data, "coordinator_epoch"),
            time_revision=_required_int(data, "time_revision"),
        )
        parse_timestamp(receipt.recovered_at)
        return receipt


@dataclass(frozen=True, slots=True)
class ManagedRecoveryTarget:
    agent_id: str
    session_id: str

    def __post_init__(self) -> None:
        for value in (self.agent_id, self.session_id):
            _required_string({"value": value}, "value")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": "managed",
            "agent_id": self.agent_id,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ManagedRecoveryTarget":
        _exact_fields(
            data, {"kind", "agent_id", "session_id"}, "managed recovery target"
        )
        if data.get("kind") != "managed":
            raise QueueServiceError("managed recovery target kind is invalid")
        return cls(
            _required_string(data, "agent_id"), _required_string(data, "session_id")
        )


@dataclass(frozen=True, slots=True)
class SlurmRecoveryTarget:
    profile_id: str
    submission_operation_id: str
    cluster_id: str
    job_id: str
    bootstrap_incarnation_id: str | None

    def __post_init__(self) -> None:
        for value in (
            self.profile_id,
            self.submission_operation_id,
            self.cluster_id,
            self.job_id,
        ):
            _required_string({"value": value}, "value")
        if self.bootstrap_incarnation_id is not None:
            _required_string({"value": self.bootstrap_incarnation_id}, "value")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": "slurm",
            "profile_id": self.profile_id,
            "submission_operation_id": self.submission_operation_id,
            "cluster_id": self.cluster_id,
            "job_id": self.job_id,
            "bootstrap_incarnation_id": self.bootstrap_incarnation_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SlurmRecoveryTarget":
        _exact_fields(
            data,
            {
                "kind",
                "profile_id",
                "submission_operation_id",
                "cluster_id",
                "job_id",
                "bootstrap_incarnation_id",
            },
            "SLURM recovery target",
        )
        if data.get("kind") != "slurm":
            raise QueueServiceError("SLURM recovery target kind is invalid")
        raw_incarnation = data.get("bootstrap_incarnation_id")
        if raw_incarnation is not None and not isinstance(raw_incarnation, str):
            raise QueueServiceError("SLURM recovery bootstrap incarnation is invalid")
        return cls(
            _required_string(data, "profile_id"),
            _required_string(data, "submission_operation_id"),
            _required_string(data, "cluster_id"),
            _required_string(data, "job_id"),
            raw_incarnation,
        )


@dataclass(frozen=True, slots=True)
class RecoverUnknownAssignment:
    """Closed, replay-safe privileged recovery request.

    Target-owned evidence is intentionally absent: a caller can request a
    close but cannot assert that a process was contained.
    """

    recovery_id: str
    run_uri: str
    stage_name: str
    attempt: int
    stage_work_id: str
    assignment_id: str
    process_execution_id: str
    execution_fence: str
    target: ManagedRecoveryTarget | SlurmRecoveryTarget
    expected_state_version: int
    requested_outcome: str
    consider_retry: bool
    reason: str

    def __post_init__(self) -> None:
        for value in (
            self.recovery_id,
            self.run_uri,
            self.stage_name,
            self.stage_work_id,
            self.assignment_id,
            self.process_execution_id,
            self.execution_fence,
        ):
            _required_string({"value": value}, "value")
        if isinstance(self.attempt, bool) or self.attempt < 1:
            raise QueueServiceError("recovery attempt is invalid")
        if not isinstance(self.target, ManagedRecoveryTarget | SlurmRecoveryTarget):
            raise QueueServiceError("recovery target is invalid")
        if (
            isinstance(self.expected_state_version, bool)
            or self.expected_state_version < 0
        ):
            raise QueueServiceError("recovery expected state version is invalid")
        if self.requested_outcome not in {"failed", "cancelled"}:
            raise QueueServiceError("recovery requested outcome is invalid")
        if not isinstance(self.consider_retry, bool):
            raise QueueServiceError("recovery retry decision is invalid")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 512
        ):
            raise QueueServiceError("recovery reason is invalid")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "recovery_id": self.recovery_id,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "stage_work_id": self.stage_work_id,
            "assignment_id": self.assignment_id,
            "process_execution_id": self.process_execution_id,
            "execution_fence": self.execution_fence,
            "target": self.target.to_dict(),
            "expected_state_version": self.expected_state_version,
            "requested_outcome": self.requested_outcome,
            "consider_retry": self.consider_retry,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "RecoverUnknownAssignment":
        _exact_fields(
            data,
            {
                "recovery_id",
                "run_uri",
                "stage_name",
                "attempt",
                "stage_work_id",
                "assignment_id",
                "process_execution_id",
                "execution_fence",
                "target",
                "expected_state_version",
                "requested_outcome",
                "consider_retry",
                "reason",
            },
            "recovery request",
        )
        target = data.get("target")
        if not isinstance(target, Mapping):
            raise QueueServiceError("recovery target is invalid")
        kind = target.get("kind")
        if kind == "managed":
            parsed_target: ManagedRecoveryTarget | SlurmRecoveryTarget = (
                ManagedRecoveryTarget.from_dict(target)
            )
        elif kind == "slurm":
            parsed_target = SlurmRecoveryTarget.from_dict(target)
        else:
            raise QueueServiceError("recovery target kind is invalid")
        return cls(
            recovery_id=_required_string(data, "recovery_id"),
            run_uri=_required_string(data, "run_uri"),
            stage_name=_required_string(data, "stage_name"),
            attempt=_required_int(data, "attempt"),
            stage_work_id=_required_string(data, "stage_work_id"),
            assignment_id=_required_string(data, "assignment_id"),
            process_execution_id=_required_string(data, "process_execution_id"),
            execution_fence=_required_string(data, "execution_fence"),
            target=parsed_target,
            expected_state_version=_required_int(data, "expected_state_version"),
            requested_outcome=_required_string(data, "requested_outcome"),
            consider_retry=_required_bool(data, "consider_retry"),
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
    agent_resource_providers: tuple[AgentResourceProvider, ...] | None = None
    agent_resource_capacity: tuple[CapacityAtom, ...] = field(init=False, repr=False)
    poll_interval_seconds: float = 0.05
    agent_policy: AgentPolicyConfig = AgentPolicyConfig()
    remote_profiles: tuple[ResidentProfileDescriptor, ...] = ()
    slurm_profiles: tuple[SlurmReadyStageProfile, ...] = ()
    scheduling_components: LocalDaemonSchedulingComponents = field(
        default_factory=_default_scheduling_components
    )
    admission_priority_resolver: Callable[[str], int] = _default_admission_priority
    max_accepted_time_step_seconds: float = 3600.0
    deployment_root: Path | None = None
    deployment_configuration_fingerprint: str | None = None
    active_configuration_fingerprint: str | None = None
    coordinator_authority_factory: Callable[[str], object] | None = None

    def __post_init__(self) -> None:
        coordinator = Path(self.coordinator_root)
        agent = Path(self.agent_root)
        run_store = Path(self.run_store_root)
        deployment_root = (
            None if self.deployment_root is None else Path(self.deployment_root)
        )
        if self.deployment_configuration_fingerprint is not None and (
            not isinstance(self.deployment_configuration_fingerprint, str)
            or len(self.deployment_configuration_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.deployment_configuration_fingerprint
            )
        ):
            raise QueueServiceError("deployment configuration fingerprint is invalid")
        if self.active_configuration_fingerprint is not None and (
            not isinstance(self.active_configuration_fingerprint, str)
            or len(self.active_configuration_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.active_configuration_fingerprint
            )
        ):
            raise QueueServiceError("active configuration fingerprint is invalid")
        authority_factory = self.coordinator_authority_factory
        if authority_factory is None:
            from .coordinator_authority import embedded_coordinator_authority

            authority_factory = embedded_coordinator_authority
        if not callable(authority_factory):
            raise QueueServiceError("coordinator authority factory is invalid")
        profile = self.resident_worker_launch_profile
        if not isinstance(profile, ResidentWorkerLaunchProfile):
            raise QueueServiceError("resident worker launch profile is required")
        try:
            descriptor = ResidentProfileDescriptor.from_dict(profile.descriptor)
        except (QueueServiceError, ValueError, TypeError) as exc:
            raise QueueServiceError(
                "resident worker launch profile is invalid"
            ) from exc
        if descriptor.to_dict() != profile.descriptor:
            raise QueueServiceError("resident worker launch descriptor must be exact")
        if coordinator == agent:
            raise QueueServiceError(
                "coordinator and local-agent roots must be distinct"
            )
        if deployment_root is not None and (
            coordinator != deployment_root / "coordinator"
            or agent != deployment_root / "agent"
        ):
            raise QueueServiceError(
                "deployment roots must be the coordinator and agent bundle subroots"
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
        providers = self.agent_resource_providers
        if providers is None:
            # This compatibility construction belongs to trusted configuration,
            # never to the daemon runtime.  Deployments that need a different
            # physical provider pass the complete composition explicitly.
            from ._managed_local import (
                GpuResourceProvider,
                AtomResourceProvider,
                _configured_provider_descriptor,
            )

            atoms = [
                CapacityAtom(
                    "cpu",
                    f"{self.machine_id}:cpu",
                    ExactQuantity(self.cpu_capacity),
                    "count",
                    ExactQuantity(1),
                )
            ]
            if self.memory_capacity_bytes:
                atoms.append(
                    CapacityAtom(
                        "memory",
                        f"{self.machine_id}:memory",
                        ExactQuantity(self.memory_capacity_bytes),
                        "B",
                        ExactQuantity(1),
                    )
                )
            atoms.extend(
                item.descriptor.capacity_atom(
                    f"{self.machine_id}:{item.descriptor.device_id}"
                )
                for item in gpu_devices
            )
            planners = {
                item.resource_kind: item for item in self.scheduling_components.planners
            }
            providers = (
                AtomResourceProvider(
                    _configured_provider_descriptor(
                        "cpu",
                        tuple(
                            atom for atom in atoms if atom.owner_resource_kind == "cpu"
                        ),
                    ),
                    planners["cpu"].claim_contracts,
                    tuple(atom for atom in atoms if atom.owner_resource_kind == "cpu"),
                ),
                *(
                    (
                        AtomResourceProvider(
                            _configured_provider_descriptor(
                                "memory",
                                tuple(
                                    atom
                                    for atom in atoms
                                    if atom.owner_resource_kind == "memory"
                                ),
                            ),
                            planners["memory"].claim_contracts,
                            tuple(
                                atom
                                for atom in atoms
                                if atom.owner_resource_kind == "memory"
                            ),
                        ),
                    )
                    if self.memory_capacity_bytes
                    else ()
                ),
                *(
                    (
                        GpuResourceProvider(
                            planners["gpu"].claim_contracts,
                            tuple(
                                atom
                                for atom in atoms
                                if atom.owner_resource_kind == "gpu"
                                and any(
                                    atom.local_capacity_key
                                    == f"{self.machine_id}:{device.descriptor.device_id}"
                                    and device.descriptor.healthy
                                    for device in gpu_devices
                                )
                            ),
                            bindings={
                                f"{self.machine_id}:{device.descriptor.device_id}": device.binding_value
                                for device in gpu_devices
                                if device.descriptor.healthy
                            },
                        ),
                    )
                    if gpu_devices
                    else ()
                ),
            )
        providers = tuple(providers)
        if not providers:
            raise QueueServiceError("agent resource provider composition is required")
        if any(
            not hasattr(item, "descriptor")
            or not hasattr(item, "claim_contracts")
            or not callable(getattr(item, "observe", None))
            for item in providers
        ):
            raise QueueServiceError("agent resource providers are invalid")
        from ._managed_local import ObserveRequest, _compose_agent_resource_providers

        try:
            provider_owners = _compose_agent_resource_providers(providers)
            provider_capacity = tuple(
                atom
                for kind, provider in sorted(provider_owners.items())
                for atom in provider.observe(
                    ObserveRequest(
                        self.machine_id,
                        "configured-local-agent",
                        f"configured-capacity:{kind}",
                    )
                ).atoms
            )
        except Exception as exc:
            raise QueueServiceError(
                "agent resource provider capacity is invalid"
            ) from exc
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
        if not callable(self.admission_priority_resolver):
            raise QueueServiceError(
                "admission priority resolver must be protected code"
            )
        if (
            isinstance(self.max_accepted_time_step_seconds, bool)
            or not isinstance(self.max_accepted_time_step_seconds, (int, float))
            or self.max_accepted_time_step_seconds <= 0
        ):
            raise QueueServiceError("maximum accepted-time step must be positive")
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
        object.__setattr__(self, "deployment_root", deployment_root)
        object.__setattr__(self, "resident_worker_launch_profile", profile)
        object.__setattr__(self, "remote_profiles", profiles)
        object.__setattr__(self, "agent_resource_providers", providers)
        object.__setattr__(self, "agent_resource_capacity", provider_capacity)
        object.__setattr__(self, "slurm_profiles", slurm_profiles)
        object.__setattr__(self, "coordinator_authority_factory", authority_factory)
        object.__setattr__(
            self,
            "gpu_devices",
            tuple(sorted(gpu_devices, key=lambda item: item.descriptor.device_id)),
        )
        object.__setattr__(
            self, "poll_interval_seconds", float(self.poll_interval_seconds)
        )
        object.__setattr__(
            self,
            "max_accepted_time_step_seconds",
            float(self.max_accepted_time_step_seconds),
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
    run_priority: int = 0
    enqueue_sequence: int = 0
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
            "run_priority": self.run_priority,
            "enqueue_sequence": self.enqueue_sequence,
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
                "run_priority",
                "enqueue_sequence",
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
            run_priority=_run_priority(_required_int(data, "run_priority")),
            enqueue_sequence=_required_int(data, "enqueue_sequence"),
            cancellation_operation_id=_optional_string(
                data, "cancellation_operation_id"
            ),
            cancellation_principal_id=_optional_string(
                data, "cancellation_principal_id"
            ),
            blocked_reason=_optional_string(data, "blocked_reason"),
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonAdmissionDetail:
    """One admission plus its explicit targeted owner join."""

    admission: LocalDaemonAdmission
    authority: Mapping[str, PlainData]
    owners: Mapping[str, PlainData] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "admission": self.admission.to_dict(),
            "authority": thaw_plain_data(
                self.authority, path="local daemon admission detail authority"
            ),
            "owners": thaw_plain_data(
                self.owners, path="local daemon admission detail owners"
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonAdmissionDetail":
        _exact_fields(
            data,
            {"admission", "authority", "owners"},
            "local daemon admission detail",
        )
        admission = data.get("admission")
        authority = data.get("authority")
        owners = data.get("owners")
        if (
            not isinstance(admission, Mapping)
            or not isinstance(authority, Mapping)
            or not isinstance(owners, Mapping)
        ):
            raise QueueServiceError("local daemon admission detail is invalid")
        return cls(
            admission=LocalDaemonAdmission.from_dict(admission),
            authority=freeze_plain_data(
                authority, path="local daemon admission detail authority"
            ),
            owners=freeze_plain_data(
                owners, path="local daemon admission detail owners"
            ),
        )


@dataclass(frozen=True, slots=True)
class DaemonStatus:
    """Constant-size, redacted coordinator health summary.

    Detailed admissions deliberately live behind ``admissions()`` and
    ``admission()``.  Keeping the summary separate prevents a status read from
    becoming an accidental history export.
    """

    coordinator_id: str
    coordinator_epoch: str
    as_of: str
    service_health: str
    service_diagnostic: str | None
    scheduling_epoch: str
    active_admissions: int
    waiting_admissions: int
    running_assignments: int
    accepted_time_health: str
    accepted_time_diagnostic: str | None

    @property
    def scheduling_ready(self) -> bool:
        return (
            self.service_health == "healthy" and self.accepted_time_health == "healthy"
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "as_of": self.as_of,
            "service_health": self.service_health,
            "service_diagnostic": self.service_diagnostic,
            "scheduling_epoch": self.scheduling_epoch,
            "scheduling_ready": self.scheduling_ready,
            "active_admissions": self.active_admissions,
            "waiting_admissions": self.waiting_admissions,
            "running_assignments": self.running_assignments,
            "accepted_time_health": self.accepted_time_health,
            "accepted_time_diagnostic": self.accepted_time_diagnostic,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "DaemonStatus":
        _exact_fields(
            data,
            {
                "coordinator_id",
                "coordinator_epoch",
                "as_of",
                "service_health",
                "service_diagnostic",
                "scheduling_epoch",
                "scheduling_ready",
                "active_admissions",
                "waiting_admissions",
                "running_assignments",
                "accepted_time_health",
                "accepted_time_diagnostic",
            },
            "local daemon status",
        )
        return cls(
            coordinator_id=_required_string(data, "coordinator_id"),
            coordinator_epoch=_required_string(data, "coordinator_epoch"),
            as_of=_required_string(data, "as_of"),
            service_health=_required_string(data, "service_health"),
            service_diagnostic=_optional_string(data, "service_diagnostic"),
            scheduling_epoch=_required_string(data, "scheduling_epoch"),
            active_admissions=_non_negative_int(
                _required_int(data, "active_admissions"), "active_admissions"
            ),
            waiting_admissions=_non_negative_int(
                _required_int(data, "waiting_admissions"), "waiting_admissions"
            ),
            running_assignments=_non_negative_int(
                _required_int(data, "running_assignments"), "running_assignments"
            ),
            accepted_time_health=_required_string(data, "accepted_time_health"),
            accepted_time_diagnostic=_optional_string(data, "accepted_time_diagnostic"),
        )


@dataclass(frozen=True, slots=True)
class AdmissionPage:
    admissions: tuple[LocalDaemonAdmission, ...]
    next_cursor: str | None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "admissions": [item.to_dict() for item in self.admissions],
            "next_cursor": self.next_cursor,
        }


class AdmissionWaitKind(StrEnum):
    CHANGED = "CHANGED"
    TERMINAL = "TERMINAL"
    TIMEOUT = "TIMEOUT"


class AdmissionNotFoundError(QueueServiceError):
    """The requested managed admission does not exist."""


@dataclass(frozen=True, slots=True)
class AdmissionWaitResult:
    kind: AdmissionWaitKind
    admission: LocalDaemonAdmission
    revision: int

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind.value,
            "admission": self.admission.to_dict(),
            "revision": self.revision,
        }


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
        self._execution: LocalDaemonExecution | None = None
        self._cycle_lock = RLock()
        self._service_error: str | None = None
        self._agent_policy = config.agent_policy

    @classmethod
    def initialize_deployment(cls, config: LocalDaemonConfig) -> None:
        """Publish one complete coordinator/embedded-agent bundle atomically."""

        target = config.deployment_root
        if target is None:
            raise QueueServiceError("coordinator deployment root is required")
        if target.exists():
            raise QueueServiceError("coordinator deployment requires a fresh root")
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        staging = target.parent / f".{target.name}.staging-{uuid4()}"
        staged = replace(
            config,
            coordinator_root=staging / "coordinator",
            agent_root=staging / "agent",
            deployment_root=staging,
        )
        try:
            staging.mkdir(mode=0o700)
            cls.initialize(staged)
            coordinator_id = _open_root(staged.coordinator_root, role="coordinator")
            agent_id = _open_root(staged.agent_root, role="local-agent")
            binding = {
                "schema_version": 2,
                "role_kind": "coordinator-bundle",
                "coordinator_id": coordinator_id,
                "agent_id": agent_id,
                "immutable_fingerprint": (
                    staged.deployment_configuration_fingerprint
                ),
            }
            binding_path = staging / _DEPLOYMENT_BINDING_FILE
            binding_path.write_text(
                json.dumps(
                    binding,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
            binding_path.chmod(0o600)
            from .local_daemon_execution import local_daemon_owner_stores_available

            if not local_daemon_owner_stores_available(
                staged, coordinator_id=coordinator_id, agent_id=agent_id
            ):
                raise QueueServiceError(
                    "coordinator deployment owner stores are incomplete"
                )
            if target.exists():
                raise QueueServiceError("coordinator deployment requires a fresh root")
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

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
                conn.execute(
                    "INSERT INTO daemon_metadata(key, value) "
                    "VALUES ('active_configuration_revision', '1')"
                )
                conn.commit()
            cls.initialize_agent_root(config.agent_root)
            from ._agent_process_supervisor import (
                AgentProcessSupervisorService,
                SupervisorLaunchConfiguration,
            )

            agent_id = _open_root(config.agent_root, role="local-agent")
            AgentProcessSupervisorService.initialize_process_free(
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

    def start(self) -> DaemonStatus:
        if self._coordinator_lock is not None:
            raise QueueServiceError("local daemon is already started")
        if self.config.deployment_root is not None:
            _validate_deployment_binding(self.config)
        _validate_distinct_roots(self.config)
        coordinator_lock = _acquire_lock(self.config.coordinator_root)
        try:
            agent_lock = _acquire_lock(self.config.agent_root)
        except Exception:
            coordinator_lock.close()
            raise
        created_supervisor: AgentProcessSupervisorClient | None = None
        owner_ids: tuple[str, str] | None = None
        try:
            coordinator_id = _open_root(
                self.config.coordinator_root, role="coordinator"
            )
            agent_id = _open_root(self.config.agent_root, role="local-agent")
            owner_ids = coordinator_id, agent_id
            from ._agent_process_supervisor import (
                AgentProcessSupervisorService,
                SupervisorLaunchConfiguration,
            )

            supervisor_configuration = SupervisorLaunchConfiguration(
                agent_id, (self.config.resident_worker_launch_profile,)
            )
            from .local_daemon_execution import local_daemon_owner_work_is_retained

            # The protected scheduling binding is a read-only rejection point.
            # Check it before an empty detached owner exists at all.
            with self._connection() as conn:
                scheduling = {
                    str(row["key"]): str(row["value"])
                    for row in conn.execute(
                        "SELECT key, value FROM daemon_metadata WHERE key IN "
                        "('scheduling_epoch', 'scheduling_fingerprint', "
                        "'active_configuration_revision')"
                    )
                }
            if scheduling.get("scheduling_fingerprint") != _scheduling_fingerprint(
                self.config
            ):
                raise QueueConflictError(
                    "protected scheduling configuration changed without reload"
                )
            scheduling_epoch = scheduling.get("scheduling_epoch")
            configuration_revision = scheduling.get("active_configuration_revision")
            if (
                scheduling_epoch is None
                or configuration_revision is None
                or not configuration_revision.isdecimal()
                or int(configuration_revision) < 1
            ):
                raise QueueStorageError("active scheduling configuration is unavailable")
            # This is the same cross-owner proof used by normal shutdown.  It
            # rejects unavailable owner state before process creation and
            # identifies retained work that must keep a newly started service
            # available for recovery if later construction fails.
            local_daemon_owner_work_is_retained(
                self.config, coordinator_id=coordinator_id, agent_id=agent_id
            )
            try:
                AgentProcessSupervisorClient(
                    self.config.agent_root, supervisor_configuration
                )
            except AgentProcessSupervisorError as exc:
                if str(exc) != "managed supervisor endpoint is unavailable":
                    raise
                created_supervisor = (
                    AgentProcessSupervisorService.start_empty_initialized(
                        self.config.agent_root,
                        configuration=supervisor_configuration,
                    )
                )
            self._coordinator_id = coordinator_id
            self._agent_id = agent_id
            epoch = f"coordinator-epoch-{uuid4()}"
            with self._connection() as conn:
                try:
                    started_at = self._accepted_time(conn)
                except QueueServiceError:
                    high_water = conn.execute(
                        "SELECT value FROM daemon_metadata "
                        "WHERE key = 'accepted_time_high_water'"
                    ).fetchone()
                    if high_water is None:
                        raise
                    started_at = str(high_water["value"])
                conn.execute(
                    "INSERT INTO coordinator_epochs (epoch, started_at) VALUES (?, ?)",
                    (epoch, started_at),
                )
                # An active row without a result belonged to a request held by
                # the previous process epoch.  Delivery and its replay result
                # commit in one transaction, so fencing only that abandoned
                # request cannot hide accepted work.  Committed results remain
                # replayable while the reconciled agent advances from a fenced
                # request to the next sequence.
                conn.execute(
                    "UPDATE agent_poll_state SET active = 0 "
                    "WHERE active = 1 AND result_json IS NULL"
                )
                conn.commit()
        except Exception:
            if created_supervisor is not None and owner_ids is not None:
                self._shutdown_created_supervisor_if_empty(
                    created_supervisor,
                    coordinator_id=owner_ids[0],
                    agent_id=owner_ids[1],
                )
            agent_lock.close()
            coordinator_lock.close()
            self._coordinator_id = None
            self._agent_id = None
            self._scheduling_epoch = None
            raise
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
            # A persisted recovery may already have target-owned evidence from
            # before the restart.  Replay it before ordinary retained work is
            # allowed to mutate authority again.
            self._resume_pending_recoveries(execution)
            # The daemon is not observable or schedulable until every retained
            # local launch has joined the continuous supervisor and completed
            # ordinary result/output/provider replay.
            execution.resume_retained_local_work()
        except Exception:
            if created_supervisor is not None:
                self._shutdown_created_supervisor_if_empty(
                    created_supervisor,
                    coordinator_id=coordinator_id,
                    agent_id=agent_id,
                )
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
        self._execution = execution
        self._thread = thread
        try:
            thread.start()
        except Exception:
            self.stop()
            raise
        return self.status()

    def _shutdown_created_supervisor_if_empty(
        self,
        supervisor: AgentProcessSupervisorClient,
        *,
        coordinator_id: str,
        agent_id: str,
    ) -> None:
        """Retire only the empty cross-owner service this start created."""

        from .local_daemon_execution import local_daemon_owner_work_is_retained

        try:
            if not local_daemon_owner_work_is_retained(
                self.config, coordinator_id=coordinator_id, agent_id=agent_id
            ):
                supervisor.shutdown_clean()
        except (AgentProcessSupervisorError, QueueConflictError, QueueServiceError):
            # Unknown or retained owner state is deliberately recoverable; a
            # constructor failure must never turn it into forced termination.
            pass

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join()
        if self._execution is not None:
            self._execution.close()
            try:
                self._execution.shutdown_clean()
            except (QueueConflictError, QueueServiceError):
                # A busy or unavailable cross-owner proof deliberately leaves
                # the detached process running for recovery.
                pass
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

    def status(self) -> DaemonStatus:
        coordinator_id = self._require_started()
        # This is intentionally a small coordinator-only operation.  Do not add
        # owner joins here: detail belongs to admission() and the owner views
        # remain an internal reconciliation diagnostic.
        with self._connection() as conn:
            counts = {
                str(row["state"]): int(row["n"])
                for row in conn.execute(
                    "SELECT state, COUNT(*) AS n FROM managed_admissions GROUP BY state"
                )
            }
            failed = conn.execute(
                "SELECT 1 FROM admission_reconciliation_health "
                "WHERE health IN ('failed', 'unavailable') LIMIT 1"
            ).fetchone()
            time_state = {
                str(row["key"]): str(row["value"])
                for row in conn.execute(
                    "SELECT key, value FROM daemon_metadata WHERE key IN "
                    "('accepted_time_health', 'accepted_time_diagnostic')"
                )
            }
        active = counts.get(LocalDaemonAdmissionState.ACTIVE.value, 0)
        waiting = counts.get(LocalDaemonAdmissionState.WAITING.value, 0)
        # Assignment ownership is split between local and remote stores.  The
        # coordinator's remote assignment table is the bounded public count;
        # local owner activity is included when its journal is available.
        running = 0
        assignment_counts_available = True
        try:
            with self._connection() as conn:
                running += int(
                    conn.execute(
                        "SELECT COUNT(*) FROM remote_assignments "
                        "WHERE state NOT IN ('RELEASED', 'FAILED', 'CANCELLED')"
                    ).fetchone()[0]
                )
            with sqlite3.connect(
                f"{self.config.execution_database.resolve().as_uri()}?mode=rw",
                uri=True,
            ) as execution:
                running += int(
                    execution.execute(
                        "SELECT COUNT(*) FROM slurm_stage_assignments "
                        "WHERE state NOT IN ('rejected', 'released')"
                    ).fetchone()[0]
                )
            with sqlite3.connect(
                f"{self.config.agent_journal.resolve().as_uri()}?mode=rw", uri=True
            ) as journal:
                running += int(
                    journal.execute(
                        "SELECT COUNT(*) FROM assignments "
                        "WHERE state NOT IN ('RELEASED', 'FAILED', 'CANCELLED')"
                    ).fetchone()[0]
                )
        except (sqlite3.Error, OSError):
            # The coordinator remains observable even if a private owner store
            # is temporarily unavailable; health carries that condition.
            assignment_counts_available = False
        time_health = time_state.get("accepted_time_health", "healthy")
        diagnostic = time_state.get("accepted_time_diagnostic")
        from .local_daemon_execution import local_daemon_owner_stores_available

        owners_available = local_daemon_owner_stores_available(
            self.config,
            coordinator_id=coordinator_id,
            agent_id=self._require_agent_id(),
        )
        as_of = self._clock()
        parse_timestamp(as_of)
        return DaemonStatus(
            coordinator_id=coordinator_id,
            coordinator_epoch=self._epoch or "",
            as_of=as_of,
            service_health=(
                "healthy"
                if self._service_error is None
                and failed is None
                and time_health == "healthy"
                and owners_available
                and assignment_counts_available
                else "degraded"
            ),
            service_diagnostic=(
                diagnostic
                if time_health != "healthy"
                else (
                    "admission_reconciliation_degraded"
                    if failed is not None
                    else (
                        "owner_status_unavailable"
                        if not owners_available or not assignment_counts_available
                        else self._service_error
                    )
                )
            ),
            scheduling_epoch=self._scheduling_epoch or "",
            active_admissions=active,
            waiting_admissions=waiting,
            running_assignments=running,
            accepted_time_health=time_health,
            accepted_time_diagnostic=diagnostic,
        )

    def admissions(
        self, *, limit: int = _MAX_ADMISSION_PAGE_SIZE, cursor: str | None = None
    ) -> AdmissionPage:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_ADMISSION_PAGE_SIZE
        ):
            raise QueueServiceError("admission list limit must be in 1..100")
        pair = _decode_admission_cursor(cursor) if cursor is not None else None
        query = "SELECT * FROM managed_admissions"
        values: tuple[object, ...] = ()
        if pair is not None:
            query += " WHERE (enqueue_sequence, admission_id) > (?, ?)"
            values = pair
        query += " ORDER BY enqueue_sequence, admission_id LIMIT ?"
        with self._connection() as conn:
            rows = tuple(conn.execute(query, (*values, limit + 1)))
        page = tuple(_admission_from_row(row) for row in rows[:limit])
        next_cursor = (
            _encode_admission_cursor(page[-1].enqueue_sequence, page[-1].admission_id)
            if len(rows) > limit and page
            else None
        )
        return AdmissionPage(page, next_cursor)

    def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
        _required_string({"admission_id": admission_id}, "admission_id")
        admission = self._admission(admission_id)
        with self._connection() as conn:
            revision_row = conn.execute(
                "SELECT revision FROM owner_status_revisions WHERE owner = 'admission'"
            ).fetchone()
        if revision_row is None:
            raise QueueStorageError("coordinator admission status is unavailable")
        from .local_daemon_execution import build_local_daemon_owner_views

        views = build_local_daemon_owner_views(
            self.config,
            (admission,),
            coordinator_id=self._require_started(),
            agent_id=self._require_agent_id(),
            clock=self._clock,
            admission_revision=int(revision_row["revision"]),
        )
        if len(views) != 1 or not isinstance(views[0].get("authority"), Mapping):
            raise QueueStorageError("targeted admission owner detail is unavailable")
        owners = views[0]
        authority = cast(Mapping[str, PlainData], owners["authority"])
        return LocalDaemonAdmissionDetail(
            admission=admission,
            authority=authority,
            owners=owners,
        )

    def admission_for_queue_item(self, queue_item_id: str) -> LocalDaemonAdmission:
        _required_string({"queue_item_id": queue_item_id}, "queue_item_id")
        return self._admission_for_queue_item(queue_item_id)

    def wait_admission(
        self, admission_id: str, *, expected_revision: int, timeout: float | None
    ) -> AdmissionWaitResult:
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise QueueServiceError("expected admission revision is invalid")
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout < 0
        ):
            raise QueueServiceError("admission wait timeout is invalid")
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        terminal = {
            LocalDaemonAdmissionState.SUCCEEDED,
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
            LocalDaemonAdmissionState.BLOCKED,
        }
        while True:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM managed_admissions WHERE admission_id = ?",
                    (admission_id,),
                ).fetchone()
                revision = conn.execute(
                    "SELECT revision FROM owner_status_revisions WHERE owner = 'admission'"
                ).fetchone()
            if row is None:
                raise AdmissionNotFoundError("managed admission was not found")
            if revision is None:
                raise QueueStorageError("coordinator admission status is unavailable")
            current = int(revision["revision"])
            if expected_revision > current:
                raise QueueConflictError(
                    "expected admission revision is ahead of current revision"
                )
            admission = _admission_from_row(row)
            if admission.state in terminal:
                return AdmissionWaitResult(
                    AdmissionWaitKind.TERMINAL, admission, current
                )
            if current != expected_revision:
                return AdmissionWaitResult(
                    AdmissionWaitKind.CHANGED, admission, current
                )
            if deadline is not None and time.monotonic() >= deadline:
                return AdmissionWaitResult(
                    AdmissionWaitKind.TIMEOUT, admission, current
                )
            self._wake.set()
            time.sleep(min(self.config.poll_interval_seconds, 0.05))

    def reconcile_once(self) -> tuple[LocalDaemonAdmission, ...]:
        """Project every admission, then schedule one global bounded window."""

        self._require_started()
        with self._cycle_lock:
            time_healthy = self._sample_clock_health()
            execution = self._execution
            if execution is None:
                raise QueueServiceError("local daemon execution is absent")
            execution.open_owner_stores()
            self._resume_pending_recoveries(execution)
            execution.begin_cycle()
            with self._connection() as conn:
                admissions = tuple(
                    _admission_from_row(row)
                    for row in conn.execute(
                        "SELECT * FROM managed_admissions "
                        "WHERE state NOT IN (?, ?, ?, ?) "
                        "ORDER BY run_priority DESC, enqueue_sequence, admission_id",
                        (
                            LocalDaemonAdmissionState.SUCCEEDED.value,
                            LocalDaemonAdmissionState.FAILED.value,
                            LocalDaemonAdmissionState.CANCELLED.value,
                            LocalDaemonAdmissionState.BLOCKED.value,
                        ),
                    )
                )
            schedulable: dict[str, LocalDaemonAdmission] = {}
            waiting_outcomes: dict[str, LocalDaemonExecutionOutcome] = {}
            for admission in admissions:
                try:
                    outcome = execution.reconcile_admission(admission)
                except QueueConflictError:
                    self._record_admission_health(admission.admission_id, "failed")
                    self._set_state(
                        admission.admission_id,
                        LocalDaemonAdmissionState.BLOCKED,
                        reason="authority_or_intent_conflict",
                    )
                except Exception:  # one unhealthy run cannot stop other admissions
                    self._record_admission_health(admission.admission_id, "unavailable")
                else:
                    self._record_admission_health(
                        admission.admission_id,
                        (
                            "unavailable"
                            if execution.local_assignment_reconciliation_pending(
                                admission.run_uri
                            )
                            else "healthy"
                        ),
                    )
                    if outcome.state is LocalDaemonAdmissionState.WAITING:
                        waiting_outcomes[admission.admission_id] = outcome
                    else:
                        self._set_state(
                            admission.admission_id,
                            outcome.state,
                            reason=outcome.reason,
                        )
                    if outcome.state in {
                        LocalDaemonAdmissionState.ACTIVE,
                        LocalDaemonAdmissionState.WAITING,
                    }:
                        schedulable[admission.admission_id] = admission

            # The durable ready query owns the 256-item window.  A cycle may
            # launch at most that many assignments, but a larger pipeline is
            # never rejected merely for having more stages.
            started_admissions: set[str] = set()
            if time_healthy:
                for _ in range(256):
                    scheduled = execution.schedule_once(schedulable)
                    if scheduled is None:
                        break
                    admission_id, outcome = scheduled
                    started_admissions.add(admission_id)
                    admission = schedulable[admission_id]
                    self._record_admission_health(
                        admission_id,
                        (
                            "unavailable"
                            if execution.local_assignment_reconciliation_pending(
                                admission.run_uri
                            )
                            else "healthy"
                        ),
                    )
                    self._set_state(admission_id, outcome.state, reason=outcome.reason)
            for admission_id, outcome in waiting_outcomes.items():
                if admission_id in started_admissions:
                    continue
                self._set_state(
                    admission_id,
                    LocalDaemonAdmissionState.WAITING,
                    reason=outcome.reason,
                )
            # Reconciliation is an internal operation; retain its bounded
            # nonterminal work result without rebuilding public detail/status.
            return tuple(
                self._admission(admission.admission_id) for admission in admissions
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
            run_priority = self._resolve_admission_priority(request.run_uri)
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
                        authority_operation_id, run_priority, enqueue_sequence,
                        cancellation_operation_id,
                        blocked_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
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
                        run_priority,
                        self._next_enqueue_sequence(conn),
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
                raise AdmissionNotFoundError("managed admission was not found")
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
                    "UPDATE agent_poll_state SET active = 0 WHERE session_id = ?",
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
                    "scheduling_epoch, configuration_revision "
                    "FROM scheduling_reloads WHERE operation_id = ?",
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
                    receipt: dict[str, PlainData] = {
                            "operation_id": request.operation_id,
                            "state": str(prior["state"]),
                            "code": prior["result_code"],
                            "scheduling_epoch": prior["scheduling_epoch"],
                        }
                    if prior["configuration_revision"] is not None:
                        receipt["configuration_revision"] = int(
                            prior["configuration_revision"]
                        )
                    return freeze_plain_data(receipt, path="scheduling reload receipt")
                if request.expected_scheduling_epoch != self._scheduling_epoch:
                    raise QueueConflictError("scheduling reload epoch is stale")
                conn.execute(
                    "INSERT INTO scheduling_reloads(operation_id, principal_id, "
                    "request_json, state, result_code, scheduling_epoch, "
                    "configuration_revision) "
                    "VALUES (?, ?, ?, 'applying', NULL, NULL, NULL)",
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
                    revision_row = conn.execute(
                        "SELECT value FROM daemon_metadata "
                        "WHERE key = 'active_configuration_revision'"
                    ).fetchone()
                    if (
                        revision_row is None
                        or not str(revision_row["value"]).isdecimal()
                    ):
                        raise QueueStorageError(
                            "active scheduling configuration is unavailable"
                        )
                    next_revision = int(str(revision_row["value"])) + 1
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
                        "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                        "VALUES ('active_configuration_revision', ?)",
                        (str(next_revision),),
                    )
                    conn.execute(
                        "UPDATE scheduling_reloads SET state = 'applied', "
                        "result_code = 'applied', scheduling_epoch = ?, "
                        "configuration_revision = ? "
                        "WHERE operation_id = ?",
                        (next_epoch, next_revision, request.operation_id),
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
                "configuration_revision": next_revision,
            },
            path="scheduling reload receipt",
        )

    def _recover_unknown(
        self, principal: LocalDaemonPrincipal, request: RecoverUnknownAssignment
    ) -> Mapping[str, PlainData]:
        """Persist and advance one immutable guarded-recovery saga."""

        from .agent_sessions import ScopedAuthorizer

        authorizer = ScopedAuthorizer(self._agent_policy)
        authorizer.require_operator(principal, "recover_unknown")
        encoded = json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        execution = self._execution
        if execution is None:
            raise QueueServiceError("recovery coordinator execution is unavailable")
        with self._cycle_lock:
            with self._connection() as conn:
                prior = conn.execute(
                    "SELECT principal_id, request_json, request_digest, recorded_at, "
                    "state, evidence_json, result_json FROM recovery_operations "
                    "WHERE recovery_id = ?",
                    (request.recovery_id,),
                ).fetchone()
                if prior is not None:
                    if (
                        str(prior["principal_id"]) != principal.subject
                        or str(prior["request_json"]) != encoded
                        or str(prior["request_digest"]) != digest
                    ):
                        raise QueueConflictError("recovery operation conflicts")
                    if str(prior["state"]) not in {"pending", "evidence_confirmed"}:
                        return freeze_plain_data(
                            json.loads(str(prior["result_json"])),
                            path="recovery receipt",
                        )
                    recorded_at = str(prior["recorded_at"])
                else:
                    execution.validate_recovery_admission(request)
                    conn.execute("BEGIN IMMEDIATE")
                    raced = conn.execute(
                        "SELECT recovery_id FROM recovery_operations "
                        "WHERE recovery_id = ?",
                        (request.recovery_id,),
                    ).fetchone()
                    if raced is not None:
                        raise QueueConflictError("recovery operation conflicts")
                    recorded_at = self._accepted_time(conn)
                    conn.execute(
                        "INSERT INTO recovery_operations("
                        "recovery_id, principal_id, request_json, request_digest, "
                        "recorded_at, state, evidence_json, result_json) "
                        "VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?)",
                        (
                            request.recovery_id,
                            principal.subject,
                            encoded,
                            digest,
                            recorded_at,
                            json.dumps(
                                {
                                    "recovery_id": request.recovery_id,
                                    "state": "pending",
                                    "evidence": "PENDING",
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                    conn.commit()
            result = self._advance_recovery(execution, request, recorded_at)
        self._wake.set()
        return freeze_plain_data(result, path="recovery receipt")

    def _replace_agent_session(
        self, principal: LocalDaemonPrincipal, request: SessionReplacementRequest
    ) -> Mapping[str, PlainData]:
        """Fence one completely classified old session before successor bind."""

        execution = self._execution
        if execution is None:
            raise QueueServiceError("replacement coordinator execution is unavailable")
        with self._cycle_lock:
            with execution.scheduling_reload_guard():
                result = replace_agent_session(self, principal, request)
        self._wake.set()
        return result

    def _advance_recovery(
        self,
        execution: "LocalDaemonExecution",
        request: RecoverUnknownAssignment,
        recorded_at: str,
    ) -> Mapping[str, PlainData]:
        """Advance only from facts already durable at each saga boundary."""

        with self._connection() as conn:
            row = conn.execute(
                "SELECT state, evidence_json, result_json FROM recovery_operations "
                "WHERE recovery_id = ?",
                (request.recovery_id,),
            ).fetchone()
        if row is None:
            raise QueueStorageError("recovery intent is unavailable")
        state = str(row["state"])
        if state not in {"pending", "evidence_confirmed"}:
            result = json.loads(str(row["result_json"]))
            if not isinstance(result, Mapping):
                raise QueueStorageError("recovery result is invalid")
            return cast(Mapping[str, PlainData], result)

        if execution.recovery_has_ordinary_winner(request):
            return self._finish_recovery(
                request.recovery_id,
                {
                    "recovery_id": request.recovery_id,
                    "state": "superseded",
                    "evidence": "ORDINARY_TERMINAL",
                },
            )
        if not execution.recovery_target_is_still_unknown(request):
            return self._finish_recovery(
                request.recovery_id,
                {
                    "recovery_id": request.recovery_id,
                    "state": "unknown",
                    "evidence": "TARGET_STATE_CHANGED",
                },
            )

        evidence: Mapping[str, PlainData] | None = None
        if row["evidence_json"] is not None:
            decoded = freeze_plain_data(
                json.loads(str(row["evidence_json"])), path="recovery evidence"
            )
            if not isinstance(decoded, Mapping):
                raise QueueStorageError("recovery evidence is invalid")
            evidence = decoded
        else:
            evidence_state, resolved = execution.resolve_recovery_evidence(request)
            if evidence_state == "pending":
                return {
                    "recovery_id": request.recovery_id,
                    "state": "pending",
                    "evidence": "PENDING",
                }
            if evidence_state != "contained" or resolved is None:
                return self._finish_recovery(
                    request.recovery_id,
                    {
                        "recovery_id": request.recovery_id,
                        "state": "unknown",
                        "evidence": "UNKNOWN",
                    },
                )
            evidence = resolved
            encoded_evidence = json.dumps(
                thaw_plain_data(evidence, path="recovery evidence"),
                sort_keys=True,
                separators=(",", ":"),
            )
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                updated = conn.execute(
                    "UPDATE recovery_operations SET state = 'evidence_confirmed', "
                    "evidence_json = ? WHERE recovery_id = ? AND state = 'pending'",
                    (encoded_evidence, request.recovery_id),
                ).rowcount
                if updated != 1:
                    raise QueueConflictError("recovery evidence state conflicts")
                conn.commit()

        if execution.recovery_has_ordinary_winner(request):
            return self._finish_recovery(
                request.recovery_id,
                {
                    "recovery_id": request.recovery_id,
                    "state": "superseded",
                    "evidence": "ORDINARY_TERMINAL",
                },
            )
        result = execution.close_recovered_assignment(
            request, evidence, recorded_at=recorded_at
        )
        return self._finish_recovery(request.recovery_id, result)

    def _finish_recovery(
        self, recovery_id: str, result: Mapping[str, PlainData]
    ) -> Mapping[str, PlainData]:
        state = result.get("state")
        if state not in {"closed", "superseded", "unknown"}:
            raise QueueServiceError("recovery result state is invalid")
        encoded = json.dumps(
            thaw_plain_data(result, path="recovery result"),
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE recovery_operations SET state = ?, result_json = ? "
                "WHERE recovery_id = ?",
                (state, encoded, recovery_id),
            )
            conn.commit()
        return result

    def _resume_pending_recoveries(self, execution: "LocalDaemonExecution") -> None:
        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT request_json, recorded_at FROM recovery_operations "
                    "WHERE state IN ('pending', 'evidence_confirmed') "
                    "ORDER BY recorded_at, recovery_id"
                )
            )
        for row in rows:
            request = RecoverUnknownAssignment.from_dict(
                json.loads(str(row["request_json"]))
            )
            self._advance_recovery(execution, request, str(row["recorded_at"]))

    def _recovery_fences_ordinary_terminal(self, assignment_id: str) -> bool:
        """Whether recovery has permanently fenced ordinary terminal mutation."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT request_json FROM recovery_operations "
                    "WHERE state IN ('pending', 'evidence_confirmed', 'closed')"
                )
            )
        for row in rows:
            value = json.loads(str(row["request_json"]))
            if (
                isinstance(value, Mapping)
                and value.get("assignment_id") == assignment_id
            ):
                return True
        return False

    def _recovery_is_settling(self, assignment_id: str) -> bool:
        """Whether close and its existing-policy retry decision are incomplete."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT request_json FROM recovery_operations "
                    "WHERE state IN ('pending', 'evidence_confirmed')"
                )
            )
        return any(
            isinstance(value := json.loads(str(row["request_json"])), Mapping)
            and value.get("assignment_id") == assignment_id
            for row in rows
        )

    def _recovery_retains_assignment(self, assignment_id: str) -> bool:
        """Whether recovery intentionally keeps this physical owner retained."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT request_json FROM recovery_operations "
                    "WHERE state IN ('pending', 'evidence_confirmed', 'closed')"
                )
            )
        return any(
            isinstance(value := json.loads(str(row["request_json"])), Mapping)
            and value.get("assignment_id") == assignment_id
            for row in rows
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
        if (
            replacement.deployment_configuration_fingerprint
            != self.config.deployment_configuration_fingerprint
        ):
            raise QueueConflictError(
                "scheduling reload cannot replace immutable role configuration"
            )
        immutable = (
            "coordinator_root",
            "agent_root",
            "run_store_root",
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

    def _resolve_admission_priority(self, run_uri: str) -> int:
        """Resolve site policy before entering the durable admission transaction."""

        try:
            return _run_priority(self.config.admission_priority_resolver(run_uri))
        except Exception as exc:
            if isinstance(exc, QueueServiceError):
                raise
            raise QueueServiceError(
                "protected admission priority policy failed"
            ) from exc

    def _next_enqueue_sequence(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = 'admission_enqueue_sequence'"
        ).fetchone()
        try:
            previous = 0 if row is None else int(cast(str, row["value"]))
        except (TypeError, ValueError) as exc:
            raise QueueStorageError("admission enqueue sequence is invalid") from exc
        if previous < 0:
            raise QueueStorageError("admission enqueue sequence is invalid")
        sequence = previous + 1
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata(key, value) VALUES "
            "('admission_enqueue_sequence', ?)",
            (str(sequence),),
        )
        return sequence

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
            raise AdmissionNotFoundError("managed admission was not found")
        return _admission_from_row(row)

    def _admission(self, admission_id: str) -> LocalDaemonAdmission:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE admission_id = ?",
                (admission_id,),
            ).fetchone()
        if row is None:
            raise AdmissionNotFoundError("managed admission was not found")
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

    def _record_admission_health(self, admission_id: str, health: str) -> None:
        if health not in {"healthy", "failed", "unavailable"}:
            raise QueueServiceError("admission reconciliation health is invalid")
        with self._connection() as conn:
            try:
                observed_at = self._accepted_time(conn)
            except QueueServiceError:
                row = conn.execute(
                    "SELECT value FROM daemon_metadata "
                    "WHERE key = 'accepted_time_high_water'"
                ).fetchone()
                if row is None:
                    raise
                observed_at = str(row["value"])
            conn.execute(
                "INSERT INTO admission_reconciliation_health("
                "admission_id, health, observed_at) VALUES (?, ?, ?) "
                "ON CONFLICT(admission_id) DO UPDATE SET health = excluded.health, "
                "observed_at = excluded.observed_at",
                (admission_id, health, observed_at),
            )
            conn.commit()

    def _record_admission_health_for_run(self, run_uri: str, health: str) -> None:
        """Join retained exact assignment work to its one admission owner."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT admission_id FROM managed_admissions WHERE run_uri = ?",
                    (run_uri,),
                )
            )
        if len(rows) != 1:
            raise QueueConflictError("retained assignment admission is unavailable")
        self._record_admission_health(str(rows[0]["admission_id"]), health)

    def _sample_clock_health(self) -> bool:
        with self._connection() as conn:
            try:
                self._accepted_time(conn)
            except QueueServiceError:
                return False
            conn.commit()
        return True

    def _recover_time(
        self, principal: LocalDaemonPrincipal, request: TimeRecoveryRequest
    ) -> TimeRecoveryReceipt:
        from .agent_sessions import ScopedAuthorizer

        ScopedAuthorizer(self._agent_policy).require_operator(principal, "recover_time")
        encoded = json.dumps(
            request.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self._cycle_lock:
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT request_digest, result_json FROM time_recoveries "
                    "WHERE operation_id = ?",
                    (request.operation_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_digest"]) != digest:
                        raise QueueConflictError(
                            "time recovery operation was reused with different content"
                        )
                    value = json.loads(str(existing["result_json"]))
                    if not isinstance(value, Mapping):
                        raise QueueStorageError("time recovery receipt is invalid")
                    conn.commit()
                    return TimeRecoveryReceipt.from_dict(value)
                state = {
                    str(row["key"]): str(row["value"])
                    for row in conn.execute(
                        "SELECT key, value FROM daemon_metadata WHERE key IN "
                        "('accepted_time_high_water', 'accepted_time_health', "
                        "'accepted_time_revision')"
                    )
                }
                current_epoch = self._epoch or ""
                revision = int(state.get("accepted_time_revision", "0"))
                if state.get("accepted_time_health") != "degraded":
                    raise QueueConflictError(
                        "coordinator accepted-time is not degraded"
                    )
                if request.expected_time_revision != revision:
                    raise QueueConflictError("time recovery revision is stale")
                if request.expected_coordinator_epoch != current_epoch:
                    raise QueueConflictError("time recovery coordinator epoch is stale")
                high_water = state.get("accepted_time_high_water")
                if high_water is None:
                    raise QueueStorageError("accepted-time high-water is unavailable")
                now = self._clock()
                parse_timestamp(now)
                if parse_timestamp(now) < parse_timestamp(high_water):
                    raise QueueConflictError(
                        "coordinator clock is still below accepted-time high-water"
                    )
                new_epoch = f"coordinator-epoch-{uuid4()}"
                next_revision = revision + 1
                receipt = TimeRecoveryReceipt(
                    operation_id=request.operation_id,
                    request_digest=digest,
                    recovered_at=now,
                    previous_coordinator_epoch=current_epoch,
                    coordinator_epoch=new_epoch,
                    time_revision=next_revision,
                )
                conn.execute(
                    "INSERT INTO coordinator_epochs(epoch, started_at) VALUES (?, ?)",
                    (new_epoch, now),
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO daemon_metadata(key, value) VALUES (?, ?)",
                    (
                        ("accepted_time_high_water", now),
                        ("accepted_time_health", "healthy"),
                        ("accepted_time_revision", str(next_revision)),
                    ),
                )
                conn.execute(
                    "DELETE FROM daemon_metadata WHERE key = 'accepted_time_diagnostic'"
                )
                conn.execute("UPDATE agent_offers SET current = 0 WHERE current = 1")
                conn.execute(
                    "INSERT INTO time_recoveries(operation_id, principal_id, "
                    "request_json, request_digest, result_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        request.operation_id,
                        principal.subject,
                        encoded,
                        digest,
                        json.dumps(
                            receipt.to_dict(),
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ),
                    ),
                )
                conn.commit()
            self._epoch = new_epoch
            execution = self._execution
            if execution is not None:
                execution.coordinator_epoch = new_epoch
            self._wake.set()
            return receipt

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
        state = {
            str(row["key"]): str(row["value"])
            for row in conn.execute(
                "SELECT key, value FROM daemon_metadata WHERE key IN "
                "('accepted_time_high_water', 'accepted_time_health', "
                "'accepted_time_diagnostic')"
            )
        }
        if state.get("accepted_time_health") == "degraded":
            raise QueueServiceError(
                "coordinator accepted-time is degraded; operator recovery is required"
            )
        previous = state.get("accepted_time_high_water")
        if previous is not None and parse_timestamp(now) < parse_timestamp(previous):
            self._degrade_time(conn, "clock_regressed")
            conn.commit()
            raise QueueServiceError(
                "coordinator accepted-time regressed; scheduling is degraded"
            )
        if (
            previous is not None
            and (parse_timestamp(now) - parse_timestamp(previous)).total_seconds()
            > self.config.max_accepted_time_step_seconds
        ):
            self._degrade_time(conn, "clock_step_exceeds_policy")
            conn.commit()
            raise QueueServiceError(
                "coordinator accepted-time step exceeds protected policy; scheduling is degraded"
            )
        accepted = now
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) "
            "VALUES ('accepted_time_high_water', ?)",
            (accepted,),
        )
        return accepted

    @staticmethod
    def _degrade_time(conn: sqlite3.Connection, diagnostic: str) -> None:
        health = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = 'accepted_time_health'"
        ).fetchone()
        if health is not None and str(health["value"]) == "degraded":
            return
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) VALUES "
            "('accepted_time_health', 'degraded')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) VALUES "
            "('accepted_time_diagnostic', ?)",
            (diagnostic,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) VALUES "
            "('accepted_time_revision', COALESCE((SELECT CAST(value AS INTEGER) + 1 "
            "FROM daemon_metadata WHERE key = 'accepted_time_revision'), 1))"
        )

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

    def status(self) -> DaemonStatus:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.status()

    def admissions(
        self, *, limit: int = _MAX_ADMISSION_PAGE_SIZE, cursor: str | None = None
    ) -> AdmissionPage:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.admissions(limit=limit, cursor=cursor)

    def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.admission(admission_id)

    def admission_for_queue_item(self, queue_item_id: str) -> LocalDaemonAdmission:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.admission_for_queue_item(queue_item_id)

    def wait_admission(
        self, admission_id: str, *, expected_revision: int, timeout: float | None
    ) -> AdmissionWaitResult:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.wait_admission(
            admission_id, expected_revision=expected_revision, timeout=timeout
        )

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

    def status(self) -> DaemonStatus:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon.status()

    def reconcile_once(self) -> tuple[LocalDaemonAdmission, ...]:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon.reconcile_once()

    def control_agent(self, control: AgentControl) -> Mapping[str, PlainData]:
        with self._daemon._cycle_lock:
            return self._daemon._control_agent(self._principal, control)

    def reload_scheduling(
        self, request: CoordinatorSchedulingReload
    ) -> Mapping[str, PlainData]:
        return self._daemon._reload_scheduling(self._principal, request)

    def recover_unknown(
        self, request: RecoverUnknownAssignment
    ) -> Mapping[str, PlainData]:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon._recover_unknown(self._principal, request)

    def recover_time(self, request: TimeRecoveryRequest) -> TimeRecoveryReceipt:
        return self._daemon._recover_time(self._principal, request)

    def replace_agent_session(
        self, request: SessionReplacementRequest
    ) -> Mapping[str, PlainData]:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon._replace_agent_session(self._principal, request)


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
            conn.executemany(
                "INSERT INTO daemon_metadata(key, value) VALUES (?, ?)",
                (
                    ("accepted_time_health", "healthy"),
                    ("accepted_time_revision", "0"),
                ),
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
                    run_priority INTEGER NOT NULL,
                    enqueue_sequence INTEGER NOT NULL UNIQUE,
                    cancellation_operation_id TEXT,
                    cancellation_principal_id TEXT,
                    blocked_reason TEXT,
                    UNIQUE(coordinator_id, run_uri)
                )
                """
            )
            conn.execute(
                "INSERT INTO daemon_metadata(key, value) VALUES "
                "('admission_enqueue_sequence', '0')"
            )
            conn.execute(
                "CREATE TABLE admission_reconciliation_health ("
                "admission_id TEXT PRIMARY KEY REFERENCES managed_admissions(admission_id), "
                "health TEXT NOT NULL, observed_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE scheduling_reloads ("
                "operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
                "request_json TEXT NOT NULL, state TEXT NOT NULL, "
                "result_code TEXT, scheduling_epoch TEXT, "
                "configuration_revision INTEGER)"
            )
            conn.execute(
                "CREATE TABLE recovery_operations ("
                "recovery_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
                "request_json TEXT NOT NULL, request_digest TEXT NOT NULL, "
                "recorded_at TEXT NOT NULL, state TEXT NOT NULL, "
                "evidence_json TEXT, result_json TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE time_recoveries ("
                "operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
                "request_json TEXT NOT NULL, request_digest TEXT NOT NULL, "
                "result_json TEXT NOT NULL)"
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


def _validate_deployment_binding(config: LocalDaemonConfig) -> None:
    target = config.deployment_root
    if target is None:
        raise QueueServiceError("coordinator deployment root is required")
    _validate_private_directory(target)
    binding_path = target / _DEPLOYMENT_BINDING_FILE
    if (
        not binding_path.is_file()
        or binding_path.stat().st_uid != os.getuid()
        or stat.S_IMODE(binding_path.stat().st_mode) & 0o077
    ):
        raise QueueServiceError("coordinator deployment binding is unavailable")
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueServiceError("coordinator deployment binding is invalid") from exc
    expected = {
        "schema_version": 2,
        "role_kind": "coordinator-bundle",
        "coordinator_id": _open_root(config.coordinator_root, role="coordinator"),
        "agent_id": _open_root(config.agent_root, role="local-agent"),
        "immutable_fingerprint": config.deployment_configuration_fingerprint,
    }
    if binding != expected:
        raise QueueServiceError("coordinator deployment binding is invalid")


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
        run_priority=_run_priority(int(row["run_priority"])),
        enqueue_sequence=_non_negative_int(
            int(row["enqueue_sequence"]), "enqueue_sequence"
        ),
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


def _encode_admission_cursor(sequence: int, admission_id: str) -> str:
    """Opaque durable keyset cursor for the admission ordering contract."""
    value = json.dumps(
        [sequence, admission_id], separators=(",", ":"), ensure_ascii=True
    )
    return (
        hashlib.sha256(value.encode("ascii")).hexdigest()[:16]
        + "."
        + value.encode("ascii").hex()
    )


def _decode_admission_cursor(cursor: str) -> tuple[int, str]:
    if not isinstance(cursor, str) or len(cursor) > 512 or "." not in cursor:
        raise QueueServiceError("admission cursor is invalid")
    prefix, encoded = cursor.split(".", 1)
    try:
        value = bytes.fromhex(encoded).decode("ascii")
        if hashlib.sha256(value.encode("ascii")).hexdigest()[:16] != prefix:
            raise ValueError
        sequence, admission_id = json.loads(value)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise QueueServiceError("admission cursor is invalid") from None
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 0
        or not isinstance(admission_id, str)
        or not admission_id
    ):
        raise QueueServiceError("admission cursor is invalid")
    return sequence, admission_id


def _required_int(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueueServiceError(f"{field} must be an integer")
    return value


def _non_negative_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QueueServiceError(f"{field} must be a non-negative integer")
    return value


def _run_priority(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not _MIN_RUN_PRIORITY <= value <= _MAX_RUN_PRIORITY
    ):
        raise QueueServiceError("run_priority is outside the protected range")
    return value


def _required_bool(data: Mapping[str, object], field: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise QueueServiceError(f"{field} must be a boolean")
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
    if config.active_configuration_fingerprint is not None:
        return config.active_configuration_fingerprint
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
    "LocalDaemonAdmissionDetail",
    "LocalDaemonAdmissionRequest",
    "LocalDaemonAdmissionState",
    "AgentSessionView",
    "LocalDaemonClientView",
    "LocalDaemonConfig",
    "LocalDaemonSchedulingComponents",
    "LocalDaemonOperatorView",
    "LocalDaemonPrincipal",
    "LocalDaemonRole",
    "DaemonStatus",
    "AdmissionPage",
    "AdmissionNotFoundError",
    "AdmissionWaitKind",
    "AdmissionWaitResult",
    "ManagedRecoveryTarget",
    "RecoverUnknownAssignment",
    "SlurmRecoveryTarget",
    "TimeRecoveryReceipt",
    "TimeRecoveryRequest",
]
