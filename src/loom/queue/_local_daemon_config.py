"""Protected role declarations and normalization for the local coordinator."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loom._sqlite_policy import SQLitePolicy, connect_existing, initialize_database
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
from loom.serialization import PlainData, freeze_plain_data

from ._agent_process_supervisor import (
    ResidentWorkerLaunchProfile,
)
from ._managed_contracts import AgentResourceProvider
from ._managed_providers import GpuResourceProvider
from ._preparation_policy import PreparationPolicy
from ._remote_stage_execution import GpuDeviceDescriptor, ResidentProfileDescriptor
from ._slurm_admission import SlurmAdmissionPolicy
from ._slurm_terminal_recovery import SlurmTerminalRecoveryPolicy
from ._storage_policy import StoragePolicy
from .agent_sessions import (
    AgentPolicyConfig,
)
from .errors import QueueServiceError
from .gpu.occupancy import GpuOccupancyMonitor, GpuOccupancyPolicy
from .submitted_execution import SubmittedContainerCapability

if TYPE_CHECKING:
    from .coordinator_authority import CoordinatorAuthorityFactory


def _default_admission_priority(_run_uri: str) -> int:
    """The protected default policy grants no client-selected preference."""

    return 0


class LocalDaemonRole(StrEnum):
    CLIENT = "client"
    OPERATOR = "operator"
    AGENT = "agent"
    QUERY = "query"
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
        SpreadingPreferenceScorer,
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
            SpreadingPreferenceScorer(),
        ),
        policy=FifoSchedulingPolicy(),
    )


@dataclass(frozen=True, slots=True)
class LocalDaemonConfig:
    """Protected configuration for one local coordinator and agent."""

    coordinator_root: Path
    agent_root: Path | None
    run_store_root: Path
    resident_worker_launch_profile: ResidentWorkerLaunchProfile | None
    machine_id: str = "machine-A"
    cpu_capacity: int = 1
    memory_capacity_bytes: int = 0
    gpu_devices: tuple[ConfiguredGpuDevice, ...] = ()
    agent_resource_providers: tuple[AgentResourceProvider, ...] | None = None
    agent_resource_capacity: tuple[CapacityAtom, ...] = field(init=False, repr=False)
    poll_interval_seconds: float = 1.0
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
    coordinator_authority_factory: CoordinatorAuthorityFactory | None = None
    gpu_occupancy_policy: GpuOccupancyPolicy | None = None
    preparation_policy: PreparationPolicy | None = None
    resident_preparation_ready: bool = False
    resident_preparation_staged_ready: bool = False
    shared_roots: Mapping[str, PlainData] = field(default_factory=dict)
    assignment_payload_root_id: str | None = None
    container_capabilities: tuple[SubmittedContainerCapability, ...] = ()
    storage: StoragePolicy | None = None
    slurm_admission: SlurmAdmissionPolicy | None = None
    slurm_terminal_recovery: SlurmTerminalRecoveryPolicy | None = None

    @property
    def sqlite_policy(self) -> SQLitePolicy | None:
        return None if self.storage is None else self.storage.sqlite

    @property
    def durable_files(self) -> Literal["best_effort", "strict"]:
        return "best_effort" if self.storage is None else self.storage.durable_files

    @property
    def slurm_schema_version(self) -> int:
        """Select the shared execution schema before any co-owner initializes it."""
        if self.slurm_terminal_recovery is not None:
            return 7
        from ._slurm_start import SLURM_REPLAYABLE_START_CAPABILITY
        from .agent_sessions import SLURM_PENDING_EFFECTS_CAPABILITY
        if any(SLURM_REPLAYABLE_START_CAPABILITY in rule.capabilities for rule in self.agent_policy.agents):
            return 6
        if any(SLURM_PENDING_EFFECTS_CAPABILITY in rule.capabilities for rule in self.agent_policy.agents):
            return 5
        return 4 if self.slurm_admission is not None or any(
            profile.job_private_file_provider.delivery_kind == "user_private_file_v1"
            for profile in self.slurm_profiles
        ) else 3

    def connect_database(self, path: Path, *, initialize=False, **legacy_options):
        if self.storage is None:
            return sqlite3.connect(path, **legacy_options)
        self.storage.require_owner()
        connect = initialize_database if initialize else connect_existing
        return connect(
            path, policy=self.storage.sqlite,
            isolation_level=legacy_options.get("isolation_level", ""),
            factory=legacy_options.get("factory"),
        )

    @property
    def coordinator_shared_roots(self) -> Mapping[str, PlainData]:
        """Private coordinator mappings; older colocated roles use their profile."""
        if self.shared_roots:
            return self.shared_roots
        profile = self.resident_worker_launch_profile
        return {} if profile is None else profile.shared_roots

    @property
    def preparation_enabled(self) -> bool:
        return self.preparation_policy is not None and bool(
            self.preparation_policy.effective_modes
        )

    def __post_init__(self) -> None:
        from .shared_execution import qualifications, root_bindings
        if self.storage is not None and not isinstance(self.storage, StoragePolicy):
            raise QueueServiceError("storage policy is invalid")
        if self.slurm_admission is not None and not isinstance(self.slurm_admission, SlurmAdmissionPolicy):
            raise QueueServiceError("SLURM admission policy is invalid")

        if self.slurm_terminal_recovery is not None:
            if not isinstance(self.slurm_terminal_recovery, SlurmTerminalRecoveryPolicy):
                raise QueueServiceError("SLURM terminal recovery policy is invalid")
            if self.slurm_terminal_recovery.enabled and any(profile.containment_helper is None for profile in self.slurm_profiles):
                raise QueueServiceError("automatic Slurm recovery requires containment helpers")

        roots = root_bindings(self.shared_roots)
        qualifications(roots)
        object.__setattr__(self, "shared_roots", freeze_plain_data(roots, path="coordinator shared roots"))
        if self.assignment_payload_root_id is not None:
            if not isinstance(self.assignment_payload_root_id, str):
                raise QueueServiceError("assignment_payload_root_id must be a root identifier")
            root = self.coordinator_shared_roots.get(self.assignment_payload_root_id)
            if not isinstance(root, Mapping) or root.get("access") != "rw":
                raise QueueServiceError("assignment_payload_root_id must select a writable shared root")
        coordinator = Path(self.coordinator_root)
        if type(self.resident_preparation_ready) is not bool:
            raise QueueServiceError("resident preparation readiness must be boolean")
        if type(self.resident_preparation_staged_ready) is not bool:
            raise QueueServiceError(
                "resident staged preparation readiness must be boolean"
            )
        if self.preparation_policy is not None and not isinstance(
            self.preparation_policy, PreparationPolicy
        ):
            raise QueueServiceError("preparation policy is invalid")
        agent = None if self.agent_root is None else Path(self.agent_root)
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
            from loom.pipeline.stores.coordinator_authority import (
                embedded_coordinator_authority,
            )

            authority_factory = embedded_coordinator_authority
        if not callable(authority_factory):
            raise QueueServiceError("coordinator authority factory is invalid")
        profile = self.resident_worker_launch_profile
        if (agent is None) != (profile is None):
            raise QueueServiceError(
                "local-agent root and resident worker launch profile must agree"
            )
        if profile is not None and not isinstance(profile, ResidentWorkerLaunchProfile):
            raise QueueServiceError("resident worker launch profile is invalid")
        if profile is not None:
            try:
                descriptor = ResidentProfileDescriptor.from_dict(profile.descriptor)
            except (QueueServiceError, ValueError, TypeError) as exc:
                raise QueueServiceError(
                    "resident worker launch profile is invalid"
                ) from exc
            if descriptor.to_dict() != profile.descriptor:
                raise QueueServiceError(
                    "resident worker launch descriptor must be exact"
                )
        if agent is not None and coordinator == agent:
            raise QueueServiceError(
                "coordinator and local-agent roots must be distinct"
            )
        if deployment_root is not None and (
            coordinator != deployment_root / "coordinator"
            or (agent is not None and agent != deployment_root / "agent")
        ):
            raise QueueServiceError(
                "deployment roots must be the coordinator and agent bundle subroots"
            )
        if not isinstance(self.machine_id, str) or not self.machine_id:
            raise QueueServiceError("machine_id must be non-empty")
        gpu_devices, providers, provider_capacity = self._resident_resources(agent)
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
        capabilities = tuple(self.container_capabilities)
        if (
            any(not isinstance(item, SubmittedContainerCapability) for item in capabilities)
            or len({item.policy_id for item in capabilities}) != len(capabilities)
        ):
            raise QueueServiceError("container execution capabilities must have unique policy IDs")
        object.__setattr__(self, "container_capabilities", capabilities)
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

    def _default_providers(self, gpu_devices: tuple[ConfiguredGpuDevice, ...]) -> tuple[AgentResourceProvider, ...]:
        # This compatibility construction belongs to trusted configuration,
        # never to the daemon runtime.  Deployments that need a different
        # physical provider pass the complete composition explicitly.
        from ._managed_providers import (
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
        return (
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
                        occupancy_monitor=(
                            None
                            if self.gpu_occupancy_policy is None
                            else GpuOccupancyMonitor(
                                tuple(
                                    device.binding_value
                                    for device in gpu_devices
                                    if device.descriptor.healthy
                                ),
                                policy=self.gpu_occupancy_policy,
                            )
                        ),
                    ),
                )
                if gpu_devices
                else ()
            ),
        )

    def _resident_resources(
        self, agent: Path | None,
    ) -> tuple[tuple[ConfiguredGpuDevice, ...], tuple[AgentResourceProvider, ...], tuple[CapacityAtom, ...]]:
        if (
            isinstance(self.cpu_capacity, bool)
            or not isinstance(self.cpu_capacity, int)
            or self.cpu_capacity < (1 if agent is not None else 0)
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
        if agent is None and (
            self.cpu_capacity
            or self.memory_capacity_bytes
            or gpu_devices
            or self.agent_resource_providers not in (None, ())
        ):
            raise QueueServiceError(
                "coordinator-only configuration has local agent state"
            )
        if any(not isinstance(item, ConfiguredGpuDevice) for item in gpu_devices):
            raise QueueServiceError("gpu_devices must be configured GPU devices")
        if len({item.descriptor.device_id for item in gpu_devices}) != len(gpu_devices):
            raise QueueServiceError("configured GPU device IDs must be unique")
        if len({item.binding_value for item in gpu_devices}) != len(gpu_devices):
            raise QueueServiceError("configured GPU bindings must be unique")
        providers = self.agent_resource_providers
        if agent is None:
            providers = ()
        elif providers is None:
            providers = self._default_providers(gpu_devices)
        providers = tuple(providers)
        if agent is not None and not providers:
            raise QueueServiceError("agent resource provider composition is required")
        if any(
            not hasattr(item, "descriptor")
            or not hasattr(item, "claim_contracts")
            or not callable(getattr(item, "observe", None))
            for item in providers
        ):
            raise QueueServiceError("agent resource providers are invalid")
        provider_capacity: tuple[CapacityAtom, ...] = ()
        if agent is not None:
            from ._managed_contracts import ObserveRequest
            from ._managed_providers import _compose_agent_resource_providers

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
                # A busy/unverified device remains configured inventory. Its
                # live provider observation alone owns current availability.
                configured = {atom.key: atom for atom in provider_capacity}
                for member in providers:
                    if isinstance(member, GpuResourceProvider):
                        configured.update(
                            (atom.key, atom) for atom in member.configured_atoms
                        )
                provider_capacity = tuple(configured[key] for key in sorted(configured))
            except Exception as exc:
                raise QueueServiceError(
                    "agent resource provider capacity is invalid"
                ) from exc
        return gpu_devices, providers, provider_capacity

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
        if self.agent_root is None:
            raise QueueServiceError("coordinator has no local agent journal")
        return self.agent_root / "journal.sqlite"

    @property
    def slurm_transfer_root(self) -> Path:
        return self.coordinator_root / "slurm-transfers"
