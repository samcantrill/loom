"""Authenticated agent session and remote stage execution protocol.

This module owns coordinator-facing sessions, offers, targeted delivery,
transfer authorization, and replay. Resident profiles, paths, physical
admission, and process launch remain protected agent-local concerns.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
from time import monotonic, sleep
from typing import TYPE_CHECKING, Concatenate, ParamSpec, TypeVar, cast
from uuid import uuid4

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp

from .errors import QueueConflictError, QueueServiceError, QueueStorageError
from ._managed_local import _provider_group_descriptor
from ._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    TRANSFER_CHUNK_BYTES,
    GpuDeviceDescriptor,
    ResidentProfileDescriptor,
    _ResidentAssignmentBundle,
    _RemoteExecutionReport,
    _RemoteOutputArtifact,
    _append_exact_chunk,
    _atomic_regular_file,
    _encode_chunk,
    _file_digest,
    _published_file_matches,
    _publish_staged_file,
    _read_regular_file_bytes,
    _read_regular_file_range,
    _reject_path_bearing_data,
)

if TYPE_CHECKING:
    from .local_daemon import (
        LocalDaemon,
        LocalDaemonPrincipal,
        RecoverUnknownAssignment,
    )


PROTOCOL_VERSION = "9"
_MAX_IDENTIFIER = 160
_MAX_COLLECTION = 32
_MAX_OFFER_TTL_SECONDS = 3600
_MAX_RESOURCE_ATOM = 2**63 - 1
_MAX_POLL_WAIT_MILLISECONDS = 5_000
_MAX_TRANSFER_AUTHORIZATIONS = 64
_MAX_REMOTE_WIRE_VALUE_BYTES = 60 * 1024
_MAX_REMOTE_EVENT_BYTES = 8 * 1024
_SESSION_REFERENCE_KINDS = frozenset(
    {
        "assignment",
        "provider",
        "delivery",
        "control",
        "transfer",
        "result",
        "output",
        "event",
        "outbox",
    }
)
_REPLACEMENT_ASSIGNMENT_REFERENCE_CLASSES = (
    "journal",
    "provider",
    "process",
    "result",
    "event",
    "outbox",
)
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+\-]*\Z")
_P = ParamSpec("_P")
_R = TypeVar("_R")


class AgentSessionState(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRING = "RETIRING"
    RETIRED_CLEAN = "RETIRED_CLEAN"
    REPLACED = "REPLACED"


class AgentControlKind(StrEnum):
    DRAIN = "drain"
    RESUME = "resume"
    RELOAD = "reload"


@dataclass(frozen=True, slots=True)
class AgentControl:
    """Inert, authenticated control data; it never carries configuration."""

    operation_id: str
    kind: AgentControlKind
    agent_id: str
    expected_session_id: str
    expected_config_revision: str
    pool: str | None
    cancel_active: bool
    reason: str

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "agent_id",
            "expected_session_id",
            "expected_config_revision",
        ):
            _identifier(getattr(self, name), name)
        object.__setattr__(self, "kind", AgentControlKind(self.kind))
        if self.pool is not None:
            _identifier(self.pool, "pool")
        if not isinstance(self.cancel_active, bool):
            raise QueueServiceError("control cancel_active must be boolean")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 512
        ):
            raise QueueServiceError("control reason must be 1..512 characters")

    def value(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind.value,
            "agent_id": self.agent_id,
            "expected_session_id": self.expected_session_id,
            "expected_config_revision": self.expected_config_revision,
            "pool": self.pool,
            "cancel_active": self.cancel_active,
            "reason": self.reason,
        }

    @classmethod
    def from_value(cls, value: Mapping[str, object]) -> "AgentControl":
        fields = {
            "operation_id",
            "kind",
            "agent_id",
            "expected_session_id",
            "expected_config_revision",
            "pool",
            "cancel_active",
            "reason",
        }
        if set(value) != fields:
            raise QueueServiceError("agent control fields are invalid")
        pool = value["pool"]
        if pool is not None and not isinstance(pool, str):
            raise QueueServiceError("control pool is invalid")
        required = (
            "operation_id",
            "kind",
            "agent_id",
            "expected_session_id",
            "expected_config_revision",
            "reason",
        )
        if any(not isinstance(value[name], str) for name in required) or not isinstance(
            value["cancel_active"], bool
        ):
            raise QueueServiceError("agent control fields are invalid")
        return cls(
            cast(str, value["operation_id"]),
            AgentControlKind(cast(str, value["kind"])),
            cast(str, value["agent_id"]),
            cast(str, value["expected_session_id"]),
            cast(str, value["expected_config_revision"]),
            pool,
            cast(bool, value["cancel_active"]),
            cast(str, value["reason"]),
        )


@dataclass(frozen=True, slots=True)
class AgentControlEffect:
    """Safe owner-local result reported after a control effect is durable."""

    operation_id: str
    code: str
    config_revision: str
    inventory_revision: str
    availability_revision: str

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "code",
            "config_revision",
            "inventory_revision",
            "availability_revision",
        ):
            _identifier(getattr(self, name), name)

    def value(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "code": self.code,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
        }

    @classmethod
    def from_value(cls, value: Mapping[str, object]) -> "AgentControlEffect":
        fields = {
            "operation_id",
            "code",
            "config_revision",
            "inventory_revision",
            "availability_revision",
        }
        if set(value) != fields or any(
            not isinstance(value[name], str) for name in fields
        ):
            raise QueueServiceError("agent control effect fields are invalid")
        return cls(
            operation_id=cast(str, value["operation_id"]),
            code=cast(str, value["code"]),
            config_revision=cast(str, value["config_revision"]),
            inventory_revision=cast(str, value["inventory_revision"]),
            availability_revision=cast(str, value["availability_revision"]),
        )


@dataclass(frozen=True, slots=True)
class AgentAssignmentControl:
    """Exact cancellation request for one retained remote assignment."""

    operation_id: str
    session_id: str
    assignment_id: str
    fence: str | None
    process_execution_id: str | None

    def __post_init__(self) -> None:
        for name in ("operation_id", "session_id", "assignment_id"):
            _identifier(getattr(self, name), name)
        for value, name in (
            (self.fence, "fence"),
            (self.process_execution_id, "process_execution_id"),
        ):
            if value is not None:
                _identifier(value, name)

    def value(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "session_id": self.session_id,
            "assignment_id": self.assignment_id,
            "fence": self.fence,
            "process_execution_id": self.process_execution_id,
        }

    @classmethod
    def from_value(cls, value: Mapping[str, object]) -> "AgentAssignmentControl":
        fields = {
            "operation_id",
            "session_id",
            "assignment_id",
            "fence",
            "process_execution_id",
        }
        if set(value) != fields or any(
            not isinstance(value[name], str)
            for name in ("operation_id", "session_id", "assignment_id")
        ):
            raise QueueServiceError("assignment control fields are invalid")
        for name in ("fence", "process_execution_id"):
            if value[name] is not None and not isinstance(value[name], str):
                raise QueueServiceError("assignment control fields are invalid")
        return cls(
            operation_id=cast(str, value["operation_id"]),
            session_id=cast(str, value["session_id"]),
            assignment_id=cast(str, value["assignment_id"]),
            fence=cast(str | None, value["fence"]),
            process_execution_id=cast(str | None, value["process_execution_id"]),
        )


_MANAGED_CONTAINMENT_EVIDENCE_FIELDS = {
    "kind",
    "state",
    "supervisor_id",
    "continuity_epoch",
    "agent_id",
    "supervisor_agent_id",
    "session_id",
    "assignment_id",
    "process_execution_id",
    "execution_fence",
    "launch_operation_id",
    "launch_spec_digest",
    "supervisor_revision",
    "worker_result_digest",
}


def _managed_containment_evidence(
    value: Mapping[str, object],
) -> Mapping[str, PlainData]:
    """Validate the exact receipt produced by the remote process owner."""

    if set(value) != _MANAGED_CONTAINMENT_EVIDENCE_FIELDS:
        raise QueueServiceError("managed containment evidence fields are invalid")
    if value.get("kind") != "managed_supervisor" or value.get("state") != "CONTAINED":
        raise QueueServiceError("managed containment evidence state is invalid")
    for name in _MANAGED_CONTAINMENT_EVIDENCE_FIELDS - {
        "kind",
        "state",
        "supervisor_revision",
        "worker_result_digest",
    }:
        _identifier(value.get(name), name)
    revision = value.get("supervisor_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise QueueServiceError("managed containment evidence revision is invalid")
    result_digest = value.get("worker_result_digest")
    if result_digest is not None:
        if (
            not isinstance(result_digest, str)
            or len(result_digest) != 64
            or any(character not in "0123456789abcdef" for character in result_digest)
        ):
            raise QueueServiceError("managed containment result digest is invalid")
    launch_digest = cast(str, value["launch_spec_digest"])
    if len(launch_digest) != 64 or any(
        character not in "0123456789abcdef" for character in launch_digest
    ):
        raise QueueServiceError("managed containment launch digest is invalid")
    frozen = freeze_plain_data(dict(value), path="managed containment evidence")
    assert isinstance(frozen, Mapping)
    return frozen


class AgentPollActiveError(QueueConflictError):
    """An exact poll retry reached the still-held original poll."""


class AgentStalePollError(QueueConflictError):
    """A poll sequence is older than the session's replayable state."""


class AgentPollSequenceGapError(QueueConflictError):
    """A poll sequence skipped the next permitted session value."""


class AgentTransferAuthorizationStaleError(QueueConflictError):
    """A transfer must obtain a fresh assignment-scoped authorization."""


@dataclass(frozen=True, slots=True)
class AgentPrincipalPolicy:
    """Protected mapping from a transport credential to one agent identity."""

    credential_id: str
    principal_id: str
    agent_id: str
    pools: tuple[str, ...]
    capabilities: tuple[str, ...] = ()
    gpu_devices: tuple[GpuDeviceDescriptor, ...] = ()

    def __post_init__(self) -> None:
        for name in ("credential_id", "principal_id", "agent_id"):
            _identifier(getattr(self, name), name)
        _identifiers(self.pools, "pools", non_empty=True)
        _identifiers(self.capabilities, "capabilities")
        devices = tuple(self.gpu_devices)
        if any(not isinstance(item, GpuDeviceDescriptor) for item in devices):
            raise QueueServiceError("agent policy GPU devices are invalid")
        if any(item.allocation_mode != "exclusive" for item in devices):
            raise QueueServiceError(
                "agent policy GPU sharing requires an enforceable provider adapter"
            )
        if len({item.device_id for item in devices}) != len(devices):
            raise QueueServiceError("agent policy GPU device IDs must be unique")
        object.__setattr__(
            self, "gpu_devices", tuple(sorted(devices, key=lambda item: item.device_id))
        )


@dataclass(frozen=True, slots=True)
class TransportPrincipalPolicy:
    """Protected client/operator credential mapping for the HTTP adapter."""

    credential_id: str
    principal_id: str
    role: str
    actions: tuple[str, ...] = ()
    agent_ids: tuple[str, ...] = ()
    pools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.credential_id, "credential_id")
        _identifier(self.principal_id, "principal_id")
        if self.role not in {"client", "operator"}:
            raise QueueServiceError("transport principal role is unsupported")
        actions = tuple(self.actions)
        agent_ids = tuple(self.agent_ids)
        pools = tuple(self.pools)
        if self.role == "operator":
            allowed = {
                "drain",
                "resume",
                "reload",
                "cancel_active",
                "scheduling_reload",
                "recover_unknown",
                "recover_time",
                "replace_session",
            }
            if not set(actions).issubset(allowed):
                raise QueueServiceError(
                    "operator actions must be an explicit finite set"
                )
            _identifiers(actions, "operator actions")
            _identifiers(agent_ids, "operator agent targets")
            _identifiers(pools, "operator pool targets")
        elif actions or agent_ids or pools:
            raise QueueServiceError("client principals cannot define operator scopes")
        object.__setattr__(self, "actions", tuple(sorted(set(actions))))
        object.__setattr__(self, "agent_ids", tuple(sorted(set(agent_ids))))
        object.__setattr__(self, "pools", tuple(sorted(set(pools))))


@dataclass(frozen=True, slots=True)
class AgentPolicyConfig:
    """Protected, replaceable current authorization policy."""

    revision: str = "policy-1"
    agents: tuple[AgentPrincipalPolicy, ...] = ()
    principals: tuple[TransportPrincipalPolicy, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.revision, "policy revision")
        credentials = [item.credential_id for item in self.agents] + [
            item.credential_id for item in self.principals
        ]
        if len(set(credentials)) != len(credentials):
            raise QueueServiceError("agent credential IDs must be unique")
        principal_agents: dict[str, str] = {}
        agent_principals: dict[str, str] = {}
        for item in self.agents:
            if (
                principal_agents.setdefault(item.principal_id, item.agent_id)
                != item.agent_id
            ):
                raise QueueServiceError(
                    "one agent principal cannot select several agents"
                )
            if (
                agent_principals.setdefault(item.agent_id, item.principal_id)
                != item.principal_id
            ):
                raise QueueServiceError(
                    "one stable agent cannot have several principals"
                )


@dataclass(frozen=True, slots=True)
class AgentRegistration:
    idempotency_key: str
    coordinator_id: str
    coordinator_epoch: str
    agent_root_id: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    declared_pools: tuple[str, ...]
    declared_capabilities: tuple[str, ...] = ()
    session_id: str | None = None
    retirement_verifier: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "coordinator_id",
            "coordinator_epoch",
            "agent_root_id",
            "config_revision",
            "inventory_revision",
            "availability_revision",
        ):
            _identifier(getattr(self, name), name)
        _identifiers(self.declared_pools, "declared pools", non_empty=True)
        _identifiers(self.declared_capabilities, "declared capabilities")
        if self.session_id is not None:
            _identifier(self.session_id, "session_id")
        if self.retirement_verifier is not None:
            _secret_digest(self.retirement_verifier, "retirement verifier")

    def value(self) -> dict[str, PlainData]:
        return {
            "idempotency_key": self.idempotency_key,
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "agent_root_id": self.agent_root_id,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "declared_pools": list(self.declared_pools),
            "declared_capabilities": list(self.declared_capabilities),
            "session_id": self.session_id,
            "retirement_verifier": self.retirement_verifier,
        }


@dataclass(frozen=True, slots=True)
class AgentSession:
    session_id: str
    coordinator_id: str
    coordinator_epoch: str
    agent_id: str
    agent_root_id: str
    policy_revision: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    capabilities: tuple[str, ...]
    pools: tuple[str, ...]
    state: AgentSessionState

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "coordinator_id",
            "coordinator_epoch",
            "agent_id",
            "agent_root_id",
            "policy_revision",
            "config_revision",
            "inventory_revision",
            "availability_revision",
        ):
            _identifier(getattr(self, name), name)
        _identifiers(self.capabilities, "session capabilities")
        _identifiers(self.pools, "session pools", non_empty=True)
        object.__setattr__(self, "state", AgentSessionState(self.state))

    def value(self) -> dict[str, PlainData]:
        return {
            "session_id": self.session_id,
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "agent_id": self.agent_id,
            "agent_root_id": self.agent_root_id,
            "policy_revision": self.policy_revision,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "capabilities": list(self.capabilities),
            "pools": list(self.pools),
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class AgentProviderDescriptor:
    """Inert wire identity and claim contracts for one physical provider."""

    descriptor: SchedulingComponentDescriptor
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, SchedulingComponentDescriptor):
            raise QueueServiceError("agent provider descriptor is invalid")
        contracts = tuple(self.claim_contracts)
        if not contracts or any(
            not isinstance(contract, ResourceClaimContractDescriptor)
            or contract.kind != self.descriptor.kind
            for contract in contracts
        ):
            raise QueueServiceError("agent provider claim contracts are invalid")
        object.__setattr__(
            self,
            "claim_contracts",
            tuple(sorted(set(contracts), key=lambda item: item.key)),
        )

    def value(self) -> dict[str, PlainData]:
        return {
            "descriptor": self.descriptor.to_dict(),
            "claim_contracts": [
                contract.to_dict() for contract in self.claim_contracts
            ],
        }

    @classmethod
    def from_value(cls, value: object) -> AgentProviderDescriptor:
        if not isinstance(value, Mapping) or set(value) != {
            "descriptor",
            "claim_contracts",
        }:
            raise QueueServiceError("agent provider value is invalid")
        contracts = value["claim_contracts"]
        if not isinstance(contracts, Sequence) or isinstance(contracts, (str, bytes)):
            raise QueueServiceError("agent provider value is invalid")
        return cls(
            SchedulingComponentDescriptor.from_dict(value["descriptor"]),
            tuple(
                ResourceClaimContractDescriptor.from_dict(contract)
                for contract in contracts
            ),
        )


@dataclass(frozen=True, slots=True)
class AgentOffer:
    session_id: str
    coordinator_epoch: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    cpu: int
    memory_bytes: int
    ttl_seconds: int
    provider_composition: tuple[AgentProviderDescriptor, ...]
    pools: tuple[str, ...] = ("default",)
    reflected_claim_ids: tuple[str, ...] = ()
    resident_profiles: tuple[ResidentProfileDescriptor, ...] = ()
    gpu_devices: tuple[GpuDeviceDescriptor, ...] = ()
    gpu_atoms: tuple[CapacityAtom, ...] = ()
    capacity_atoms: tuple[CapacityAtom, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "coordinator_epoch",
            "config_revision",
            "inventory_revision",
            "availability_revision",
        ):
            _identifier(getattr(self, name), name)
        for value, name in ((self.cpu, "cpu"), (self.memory_bytes, "memory_bytes")):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= _MAX_RESOURCE_ATOM
            ):
                raise QueueServiceError(
                    f"{name} must be a bounded non-negative integer"
                )
        capacity_atoms = tuple(self.capacity_atoms)
        if not capacity_atoms:
            built_atoms: list[CapacityAtom] = []
            if self.cpu:
                built_atoms.append(
                    CapacityAtom(
                        "cpu",
                        "cpu",
                        ExactQuantity(self.cpu),
                        "count",
                        ExactQuantity(1),
                    )
                )
            if self.memory_bytes:
                built_atoms.append(
                    CapacityAtom(
                        "memory",
                        "memory",
                        ExactQuantity(self.memory_bytes),
                        "byte",
                        ExactQuantity(1),
                    )
                )
            built_atoms.extend(self.gpu_atoms)
            capacity_atoms = tuple(built_atoms)
        if any(not isinstance(atom, CapacityAtom) for atom in capacity_atoms) or len(
            {atom.key for atom in capacity_atoms}
        ) != len(capacity_atoms):
            raise QueueServiceError("offer capacity atoms are invalid")
        if any(
            quantity.numerator > _MAX_RESOURCE_ATOM
            or quantity.denominator > _MAX_RESOURCE_ATOM
            for atom in capacity_atoms
            for quantity in (atom.amount, atom.granularity)
        ):
            raise QueueServiceError("offer capacity is outside its bound")
        cpu_atoms = tuple(
            atom for atom in capacity_atoms if atom.owner_resource_kind == "cpu"
        )
        memory_atoms = tuple(
            atom for atom in capacity_atoms if atom.owner_resource_kind == "memory"
        )
        if (
            any(
                atom.unit != "count"
                or atom.amount.denominator != 1
                or atom.granularity != ExactQuantity(1)
                for atom in cpu_atoms
            )
            or sum(atom.amount.numerator for atom in cpu_atoms) != self.cpu
        ):
            raise QueueServiceError("offer CPU atoms conflict with the CPU total")
        if (
            any(
                atom.unit != "byte"
                or atom.amount.denominator != 1
                or atom.granularity != ExactQuantity(1)
                for atom in memory_atoms
            )
            or sum(atom.amount.numerator for atom in memory_atoms) != self.memory_bytes
        ):
            raise QueueServiceError("offer memory atoms conflict with the memory total")
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, int)
            or not 1 <= self.ttl_seconds <= _MAX_OFFER_TTL_SECONDS
        ):
            raise QueueServiceError("offer TTL is outside the permitted range")
        providers = tuple(self.provider_composition)
        if any(
            not isinstance(item, AgentProviderDescriptor) for item in providers
        ) or len({item.descriptor.key for item in providers}) != len(providers):
            raise QueueServiceError("offer provider composition is invalid")
        if not providers:
            raise QueueServiceError("offer provider composition is required")
        provider_kinds = {item.descriptor.kind for item in providers}
        if any(
            contract.kind != item.descriptor.kind
            for item in providers
            for contract in item.claim_contracts
        ):
            raise QueueServiceError("offer provider composition is invalid")
        configured_kinds = {atom.owner_resource_kind for atom in capacity_atoms}
        if self.gpu_devices:
            configured_kinds.add("gpu")
        if not configured_kinds.issubset(provider_kinds):
            raise QueueServiceError(
                "offer provider composition must match configured resources"
            )
        object.__setattr__(
            self,
            "provider_composition",
            tuple(sorted(providers, key=lambda item: item.descriptor.key)),
        )
        _identifiers(self.reflected_claim_ids, "reflected claim IDs")
        _identifiers(self.pools, "offer pools", non_empty=True)
        profiles = tuple(self.resident_profiles)
        if any(not isinstance(item, ResidentProfileDescriptor) for item in profiles):
            raise QueueServiceError("offer resident profiles are invalid")
        if len({item.profile_id for item in profiles}) != len(profiles):
            raise QueueServiceError("offer resident profile IDs must be unique")
        object.__setattr__(self, "resident_profiles", profiles)
        devices = tuple(self.gpu_devices)
        if any(not isinstance(item, GpuDeviceDescriptor) for item in devices) or len(
            {item.device_id for item in devices}
        ) != len(devices):
            raise QueueServiceError("offer GPU devices are invalid")
        devices = tuple(sorted(devices, key=lambda item: item.device_id))
        configured = {item.device_id: item for item in devices}
        gpu_atoms = tuple(self.gpu_atoms)
        if any(not isinstance(item, CapacityAtom) for item in gpu_atoms) or len(
            {item.local_capacity_key for item in gpu_atoms}
        ) != len(gpu_atoms):
            raise QueueServiceError("offer GPU availability atoms are invalid")
        for atom in gpu_atoms:
            device = configured.get(atom.local_capacity_key)
            if (
                device is None
                or not device.healthy
                or atom.owner_resource_kind != "gpu"
                or atom.unit != device.unit
                or atom.granularity != device.capacity_granularity
                or atom.amount.fraction > device.capacity.fraction
            ):
                raise QueueServiceError(
                    "offer GPU availability conflicts with configured inventory"
                )
        object.__setattr__(self, "gpu_devices", devices)
        object.__setattr__(
            self,
            "gpu_atoms",
            tuple(sorted(gpu_atoms, key=lambda item: item.local_capacity_key)),
        )
        capacity_gpu_atoms = tuple(
            sorted(
                (atom for atom in capacity_atoms if atom.owner_resource_kind == "gpu"),
                key=lambda item: item.local_capacity_key,
            )
        )
        if capacity_gpu_atoms != self.gpu_atoms:
            raise QueueServiceError(
                "offer GPU capacity atoms conflict with GPU availability"
            )
        object.__setattr__(
            self,
            "capacity_atoms",
            tuple(sorted(capacity_atoms, key=lambda item: item.key)),
        )

    def value(self) -> dict[str, PlainData]:
        return {
            "session_id": self.session_id,
            "coordinator_epoch": self.coordinator_epoch,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "capacity_atoms": [atom.to_dict() for atom in self.capacity_atoms],
            "ttl_seconds": self.ttl_seconds,
            "provider_composition": [
                provider.value() for provider in self.provider_composition
            ],
            "pools": list(self.pools),
            "reflected_claim_ids": list(self.reflected_claim_ids),
            "resident_profiles": [item.to_dict() for item in self.resident_profiles],
            "gpu_devices": [device.to_dict() for device in self.gpu_devices],
        }

    @classmethod
    def from_value(cls, value: object) -> "AgentOffer":
        expected = {
            "session_id",
            "coordinator_epoch",
            "config_revision",
            "inventory_revision",
            "availability_revision",
            "capacity_atoms",
            "ttl_seconds",
            "provider_composition",
            "pools",
            "reflected_claim_ids",
            "resident_profiles",
            "gpu_devices",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise QueueServiceError("agent offer is invalid")
        atoms = value["capacity_atoms"]
        if not isinstance(atoms, Sequence) or isinstance(atoms, (str, bytes)):
            raise QueueServiceError("agent offer capacity is invalid")
        capacities: dict[str, int] = {"cpu": 0, "memory": 0}
        capacity_atoms: list[CapacityAtom] = []
        gpu_atoms: list[CapacityAtom] = []
        for atom in atoms:
            if not isinstance(atom, Mapping) or set(atom) != {
                "owner_resource_kind",
                "local_capacity_key",
                "amount",
                "unit",
                "granularity",
            }:
                raise QueueServiceError("agent offer capacity is invalid")
            kind = atom.get("owner_resource_kind")
            parsed = _offer_capacity_atom(atom)
            capacity_atoms.append(parsed)
            if kind == "gpu":
                gpu_atoms.append(parsed)
                continue
            if kind not in {"cpu", "memory"}:
                continue
            expected_unit = "count" if kind == "cpu" else "byte"
            if (
                parsed.unit != expected_unit
                or parsed.amount.denominator != 1
                or parsed.granularity != ExactQuantity(1)
            ):
                raise QueueServiceError("agent offer capacity is invalid")
            capacities[cast(str, kind)] += parsed.amount.numerator
        if len({atom.key for atom in capacity_atoms}) != len(capacity_atoms):
            raise QueueServiceError("agent offer capacity is invalid")
        pools = value["pools"]
        claims = value["reflected_claim_ids"]
        profiles = value["resident_profiles"]
        gpu_devices = value["gpu_devices"]
        provider_composition = value["provider_composition"]
        if (
            not isinstance(pools, Sequence)
            or isinstance(pools, (str, bytes))
            or not isinstance(claims, Sequence)
            or isinstance(claims, (str, bytes))
            or not isinstance(profiles, Sequence)
            or isinstance(profiles, (str, bytes))
            or not isinstance(gpu_devices, Sequence)
            or isinstance(gpu_devices, (str, bytes))
            or not isinstance(provider_composition, Sequence)
            or isinstance(provider_composition, (str, bytes))
        ):
            raise QueueServiceError("agent offer scope is invalid")
        return cls(
            session_id=cast(str, value["session_id"]),
            coordinator_epoch=cast(str, value["coordinator_epoch"]),
            config_revision=cast(str, value["config_revision"]),
            inventory_revision=cast(str, value["inventory_revision"]),
            availability_revision=cast(str, value["availability_revision"]),
            cpu=capacities.get("cpu", 0),
            memory_bytes=capacities.get("memory", 0),
            ttl_seconds=cast(int, value["ttl_seconds"]),
            provider_composition=tuple(
                AgentProviderDescriptor.from_value(item)
                for item in provider_composition
            ),
            pools=tuple(cast(Sequence[str], pools)),
            reflected_claim_ids=tuple(cast(Sequence[str], claims)),
            resident_profiles=tuple(
                ResidentProfileDescriptor.from_dict(item) for item in profiles
            ),
            gpu_devices=tuple(
                GpuDeviceDescriptor.from_dict(item) for item in gpu_devices
            ),
            gpu_atoms=tuple(gpu_atoms),
            capacity_atoms=tuple(capacity_atoms),
        )

    @property
    def provider_descriptors(self) -> tuple[SchedulingComponentDescriptor, ...]:
        grouped: dict[
            str,
            list[
                tuple[
                    SchedulingComponentDescriptor,
                    tuple[ResourceClaimContractDescriptor, ...],
                ]
            ],
        ] = {}
        for provider in self.provider_composition:
            grouped.setdefault(provider.descriptor.kind, []).append(
                (provider.descriptor, provider.claim_contracts)
            )
        return tuple(
            _provider_group_descriptor(grouped[kind]) for kind in sorted(grouped)
        )

    @property
    def provider_claim_contracts(
        self,
    ) -> Mapping[str, tuple[ResourceClaimContractDescriptor, ...]]:
        return {
            kind: tuple(
                sorted(
                    {
                        contract
                        for provider in self.provider_composition
                        if provider.descriptor.kind == kind
                        for contract in provider.claim_contracts
                    },
                    key=lambda item: item.key,
                )
            )
            for kind in sorted(
                {provider.descriptor.kind for provider in self.provider_composition}
            )
        }


def _offer_capacity_atom(value: Mapping[str, object]) -> CapacityAtom:
    try:
        atom = CapacityAtom(
            owner_resource_kind=cast(str, value["owner_resource_kind"]),
            local_capacity_key=cast(str, value["local_capacity_key"]),
            amount=ExactQuantity.from_dict(value["amount"]),
            unit=cast(str, value["unit"]),
            granularity=ExactQuantity.from_dict(value["granularity"]),
        )
    except Exception as exc:
        raise QueueServiceError("agent offer capacity is invalid") from exc
    for quantity in (atom.amount, atom.granularity):
        if (
            quantity.numerator > _MAX_RESOURCE_ATOM
            or quantity.denominator > _MAX_RESOURCE_ATOM
        ):
            raise QueueServiceError("agent offer capacity is outside its bound")
    return atom


@dataclass(frozen=True, slots=True)
class AgentRetirementProof:
    session_id: str
    coordinator_id: str
    coordinator_epoch: str
    agent_id: str
    agent_root_id: str
    policy_revision: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    reference_revision: int
    reference_digest: str
    retirement_secret: str

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "coordinator_id",
            "coordinator_epoch",
            "agent_id",
            "agent_root_id",
            "policy_revision",
            "config_revision",
            "inventory_revision",
            "availability_revision",
            "reference_digest",
            "retirement_secret",
        ):
            _identifier(getattr(self, name), name)
        if (
            isinstance(self.reference_revision, bool)
            or not isinstance(self.reference_revision, int)
            or self.reference_revision < 0
        ):
            raise QueueServiceError("agent reference revision must be non-negative")
        if len(self.reference_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.reference_digest
        ):
            raise QueueServiceError("agent reference digest is invalid")
        _secret_digest(self.retirement_secret, "agent retirement secret")

    def value(self) -> dict[str, PlainData]:
        return {
            "session_id": self.session_id,
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "agent_id": self.agent_id,
            "agent_root_id": self.agent_root_id,
            "policy_revision": self.policy_revision,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "reference_revision": self.reference_revision,
            "reference_digest": self.reference_digest,
            "retirement_secret": self.retirement_secret,
        }

    def redacted_value(self) -> dict[str, PlainData]:
        """Coordinator-retained proof evidence, deliberately excluding the secret."""
        value = self.value()
        del value["retirement_secret"]
        return value


@dataclass(frozen=True, slots=True)
class AgentProviderReleaseProof:
    """Old-root proof that every provider for one exact claim released."""

    session_id: str
    coordinator_id: str
    coordinator_epoch: str
    agent_id: str
    agent_root_id: str
    policy_revision: str
    config_revision: str
    inventory_revision: str
    assignment_id: str
    claim_id: str
    execution_fence: str
    released_availability_revision: str
    recovery_control_operation_id: str | None
    retirement_secret: str

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "coordinator_id",
            "coordinator_epoch",
            "agent_id",
            "agent_root_id",
            "policy_revision",
            "config_revision",
            "inventory_revision",
            "assignment_id",
            "claim_id",
            "execution_fence",
            "released_availability_revision",
            "retirement_secret",
        ):
            _identifier(getattr(self, name), name)
        if self.recovery_control_operation_id is not None:
            _identifier(
                self.recovery_control_operation_id,
                "recovery_control_operation_id",
            )
        _secret_digest(self.retirement_secret, "agent retirement secret")

    def value(self) -> dict[str, PlainData]:
        return {
            "session_id": self.session_id,
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "agent_id": self.agent_id,
            "agent_root_id": self.agent_root_id,
            "policy_revision": self.policy_revision,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "assignment_id": self.assignment_id,
            "claim_id": self.claim_id,
            "execution_fence": self.execution_fence,
            "released_availability_revision": (self.released_availability_revision),
            "recovery_control_operation_id": self.recovery_control_operation_id,
            "retirement_secret": self.retirement_secret,
        }

    def redacted_value(self) -> dict[str, PlainData]:
        value = self.value()
        del value["retirement_secret"]
        return value


@dataclass(frozen=True, slots=True)
class SessionReplacementRequest:
    """Privileged request to fence one derived, unreachable old session.

    The operation deliberately contains no session identity or containment
    assertion.  The coordinator derives both from protected current state.
    """

    operation_id: str
    agent_id: str
    reason: str

    def __post_init__(self) -> None:
        _identifier(self.operation_id, "replacement operation_id")
        _identifier(self.agent_id, "replacement agent_id")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 512
        ):
            raise QueueServiceError("replacement reason must be 1..512 characters")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "agent_id": self.agent_id,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SessionReplacementRequest":
        if set(data) != {"operation_id", "agent_id", "reason"} or any(
            not isinstance(data[name], str)
            for name in ("operation_id", "agent_id", "reason")
        ):
            raise QueueServiceError("session replacement request fields are invalid")
        return cls(
            cast(str, data["operation_id"]),
            cast(str, data["agent_id"]),
            cast(str, data["reason"]),
        )


@dataclass(frozen=True, slots=True)
class _ReplacementProjection:
    value: Mapping[str, PlainData]
    required_claim_ids: tuple[str, ...]
    recovery_requests: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class _ReplacementOfferAdmission:
    operation_id: str
    request: SessionReplacementRequest
    old_session_id: str
    prior_readiness: str
    decision_projection_digest: str
    projection: _ReplacementProjection
    durable_projection: Mapping[str, PlainData]


class ScopedAuthorizer:
    """The one current-policy check used by direct and transport adapters."""

    def __init__(self, policy: AgentPolicyConfig) -> None:
        self.policy = policy

    def agent(self, principal: "LocalDaemonPrincipal") -> AgentPrincipalPolicy:
        credential_id = principal.credential_id
        if credential_id is None:
            raise QueueServiceError("agent credential is required")
        for rule in self.policy.agents:
            if (
                rule.credential_id == credential_id
                and rule.principal_id == principal.subject
            ):
                return rule
        raise QueueServiceError("daemon principal is not authorized for this operation")

    def transport_principal(self, credential_id: str) -> tuple[str, str]:
        for rule in self.policy.agents:
            if rule.credential_id == credential_id:
                return rule.principal_id, "agent"
        for rule in self.policy.principals:
            if rule.credential_id == credential_id:
                return rule.principal_id, rule.role
        raise QueueServiceError("daemon principal is not authorized for this operation")

    def require_agent(
        self, principal: "LocalDaemonPrincipal", action: str
    ) -> AgentPrincipalPolicy:
        if principal.role.value != "agent":
            raise QueueServiceError(
                "daemon principal is not authorized for this operation"
            )
        if action not in {
            "handshake",
            "register",
            "reconcile",
            "offer",
            "poll",
            "authorize",
            "input",
            "accept",
            "decline",
            "started",
            "event",
            "output_manifest",
            "output",
            "result",
            "release",
            "control",
            "assignment_control",
            "start_permit",
            "retire",
        }:
            raise QueueServiceError("agent operation is unsupported")
        return self.agent(principal)

    def require_role(self, principal: "LocalDaemonPrincipal", role: str) -> None:
        """Authorize a direct view with the same current policy as HTTP."""
        if principal.role.value != role:
            raise QueueServiceError(
                "daemon principal is not authorized for this operation"
            )
        # Existing owner-only Unix/direct views carry an already-trusted local
        # principal. Only protected operator actions require an explicit scope;
        # client and agent-less status views retain their existing local owner
        # admission.
        if principal.credential_id is None:
            if role != "operator":
                return
            if any(
                rule.principal_id == principal.subject and rule.role == role
                for rule in self.policy.principals
            ):
                return
            raise QueueServiceError(
                "daemon principal is not authorized for this operation"
            )
        principal_id, mapped_role = self.transport_principal(principal.credential_id)
        if principal.subject != principal_id or mapped_role != role:
            raise QueueServiceError(
                "daemon principal is not authorized for this operation"
            )

    def require_operator(
        self,
        principal: "LocalDaemonPrincipal",
        action: str,
        *,
        agent_id: str | None = None,
        pool: str | None = None,
    ) -> None:
        """Authorize one exact protected operator action before mutation."""

        self.require_role(principal, "operator")
        matches = [
            rule
            for rule in self.policy.principals
            if rule.role == "operator"
            and rule.principal_id == principal.subject
            and (
                principal.credential_id is None
                or rule.credential_id == principal.credential_id
            )
        ]
        if len(matches) != 1:
            raise QueueServiceError(
                "daemon principal is not authorized for this operation"
            )
        rule = matches[0]
        if action not in rule.actions:
            raise QueueServiceError(
                "daemon principal is not authorized for this operation"
            )
        if agent_id is not None and agent_id not in rule.agent_ids:
            raise QueueServiceError(
                "daemon principal is not authorized for this operation"
            )
        if pool is not None and pool not in rule.pools:
            raise QueueServiceError(
                "daemon principal is not authorized for this operation"
            )


def _serialized_session_operation(
    method: Callable[Concatenate["AgentSessionService", _P], _R],
) -> Callable[Concatenate["AgentSessionService", _P], _R]:
    """Exclude replacement while one authenticated session call is in flight."""

    @wraps(method)
    def wrapped(
        service: "AgentSessionService", *args: _P.args, **kwargs: _P.kwargs
    ) -> _R:
        with service._daemon._cycle_lock:  # type: ignore[attr-defined]
            return method(service, *args, **kwargs)

    return wrapped


def _serialized_offer_operation(
    method: Callable[Concatenate["AgentSessionService", _P], _R],
) -> Callable[Concatenate["AgentSessionService", _P], _R]:
    """Also exclude assignment creation during replacement readiness."""

    @wraps(method)
    def wrapped(
        service: "AgentSessionService", *args: _P.args, **kwargs: _P.kwargs
    ) -> _R:
        with service._daemon._cycle_lock:  # type: ignore[attr-defined]
            execution = service._daemon._execution  # type: ignore[attr-defined]
            if execution is None:
                raise QueueServiceError("remote execution owner is unavailable")
            with execution.scheduling_reload_guard():
                return method(service, *args, **kwargs)

    return wrapped


class AgentSessionView:
    """A direct adapter with a trusted principal captured at construction."""

    def __init__(
        self, daemon: "LocalDaemon", principal: "LocalDaemonPrincipal"
    ) -> None:
        self._daemon = daemon
        self._principal = principal

    def handshake(self) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).handshake()

    def register(self, request: AgentRegistration) -> AgentSession:
        return AgentSessionService(self._daemon, self._principal).register(request)

    def reconcile(
        self,
        expected: AgentSession,
        coordinator_epoch: str,
        *,
        idempotency_key: str,
    ) -> AgentSession:
        return AgentSessionService(self._daemon, self._principal).reconcile(
            expected, coordinator_epoch, idempotency_key=idempotency_key
        )

    def publish_offer(
        self, offer: AgentOffer, *, idempotency_key: str
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).publish_offer(
            offer, idempotency_key=idempotency_key
        )

    def wait_for_work(
        self,
        session_id: str,
        availability_revision: str,
        *,
        sequence: int,
        wait_timeout_ms: int,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).wait_for_work(
            session_id,
            availability_revision,
            sequence=sequence,
            wait_timeout_ms=wait_timeout_ms,
        )

    def authorize_transfers(
        self,
        session_id: str,
        assignment_id: str,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).authorize_transfers(
            session_id,
            assignment_id,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def read_input_chunk(
        self,
        session_id: str,
        assignment_id: str,
        transfer_id: str,
        *,
        offset: int,
        authorization_id: str,
        authorization_revision: int,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).read_input_chunk(
            session_id,
            assignment_id,
            transfer_id,
            offset=offset,
            authorization_id=authorization_id,
            authorization_revision=authorization_revision,
        )

    def accept_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        request_digest: str,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).accept_assignment(
            session_id,
            assignment_id,
            request_digest=request_digest,
        )

    def start_permit(self, session_id: str, assignment_id: str, *, fence: str) -> bool:
        return AgentSessionService(self._daemon, self._principal).start_permit(
            session_id, assignment_id, fence=fence
        )

    def decline_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        availability_revision: str,
    ) -> AgentSession:
        return AgentSessionService(self._daemon, self._principal).decline_assignment(
            session_id,
            assignment_id,
            availability_revision=availability_revision,
        )

    def confirm_started(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        process_execution_id: str,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).confirm_started(
            session_id,
            assignment_id,
            fence=fence,
            process_execution_id=process_execution_id,
        )

    def report_event(
        self,
        session_id: str,
        assignment_id: str,
        *,
        sequence: int,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).report_event(
            session_id,
            assignment_id,
            sequence=sequence,
            event_id=event_id,
            payload=payload,
        )

    def declare_outputs(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        authorization_id: str,
        authorization_revision: int,
        report: _RemoteExecutionReport,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).declare_outputs(
            session_id,
            assignment_id,
            fence=fence,
            authorization_id=authorization_id,
            authorization_revision=authorization_revision,
            report=report,
        )

    def upload_output_chunk(
        self,
        session_id: str,
        assignment_id: str,
        transfer_id: str,
        *,
        offset: int,
        data: bytes,
        final: bool,
        authorization_id: str,
        authorization_revision: int,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).upload_output_chunk(
            session_id,
            assignment_id,
            transfer_id,
            offset=offset,
            data=data,
            final=final,
            authorization_id=authorization_id,
            authorization_revision=authorization_revision,
        )

    def commit_result(
        self, session_id: str, assignment_id: str, *, fence: str
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).commit_result(
            session_id, assignment_id, fence=fence
        )

    def release_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        availability_revision: str,
        provider_release_proof: AgentProviderReleaseProof,
    ) -> AgentSession:
        return AgentSessionService(self._daemon, self._principal).release_assignment(
            session_id,
            assignment_id,
            fence=fence,
            availability_revision=availability_revision,
            provider_release_proof=provider_release_proof,
        )

    def retire_clean(
        self, proof: AgentRetirementProof, *, idempotency_key: str
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).retire_clean(
            proof, idempotency_key=idempotency_key
        )

    def next_control(self, session_id: str) -> AgentControl | None:
        return AgentSessionService(self._daemon, self._principal).next_control(
            session_id
        )

    def acknowledge_control(
        self, session_id: str, effect: AgentControlEffect
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).acknowledge_control(
            session_id, effect
        )

    def next_assignment_control(self, session_id: str) -> AgentAssignmentControl | None:
        return AgentSessionService(
            self._daemon, self._principal
        ).next_assignment_control(session_id)

    def acknowledge_assignment_control(
        self,
        session_id: str,
        operation_id: str,
        *,
        code: str,
        evidence: Mapping[str, object] | None = None,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(
            self._daemon, self._principal
        ).acknowledge_assignment_control(
            session_id, operation_id, code=code, evidence=evidence
        )


class AgentSessionService:
    """Coordinator-owned durable transitions for the restricted agent view."""

    def __init__(
        self, daemon: "LocalDaemon", principal: "LocalDaemonPrincipal"
    ) -> None:
        self._daemon = daemon
        self._principal = principal

    def _authorize(self, action: str) -> tuple[AgentPrincipalPolicy, str]:
        policy = self._daemon._agent_policy  # type: ignore[attr-defined]
        return (
            ScopedAuthorizer(policy).require_agent(self._principal, action),
            policy.revision,
        )

    def handshake(self) -> Mapping[str, PlainData]:
        self._authorize("handshake")
        coordinator_id = self._daemon._require_started()  # type: ignore[attr-defined]
        return freeze_plain_data(
            {
                "protocol_version": PROTOCOL_VERSION,
                "capabilities": [
                    "agent-sessions-v9",
                    REMOTE_EXECUTION_CAPABILITY,
                    REGULAR_FILE_RELAY_CAPABILITY,
                ],
                "coordinator_id": coordinator_id,
                "coordinator_epoch": self._daemon._epoch or "",  # type: ignore[attr-defined]
                "role": "agent",
            },
            path="agent handshake",
        )

    @_serialized_session_operation
    def next_control(self, session_id: str) -> AgentControl | None:
        rule, revision = self._authorize("control")
        _identifier(session_id, "session_id")
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
                ).fetchone(),
                self._daemon._require_started(),
                expected_principal=rule.principal_id,
            )  # type: ignore[attr-defined]
            self._check_current_session(
                session, rule, self._daemon._epoch or "", revision
            )  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT operation_id, request_json FROM agent_controls WHERE session_id = ? AND state IN ('pending_delivery', 'applying') ORDER BY operation_id LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            control = AgentControl.from_value(json.loads(str(row["request_json"])))
            if control.expected_config_revision != session.config_revision:
                conn.execute(
                    "UPDATE agent_controls SET state = 'failed', result_code = 'stale_revision' WHERE operation_id = ?",
                    (control.operation_id,),
                )
                conn.commit()
                return None
            if control.cancel_active:
                pending = tuple(
                    conn.execute(
                        "SELECT DISTINCT a.run_uri, a.cancellation_operation_id "
                        "FROM remote_assignments r JOIN managed_admissions a "
                        "ON a.run_uri = r.run_uri WHERE r.session_id = ? "
                        "AND r.state != 'RELEASED' AND a.state NOT IN "
                        "('SUCCEEDED', 'FAILED', 'CANCELLED')",
                        (session_id,),
                    )
                )
                for cancellation in pending:
                    operation_id = cancellation["cancellation_operation_id"]
                    if operation_id is None:
                        conn.commit()
                        return None
                    try:
                        from loom.pipeline.stores.sqlite_authority import (
                            SQLitePerRunAuthorityStore,
                        )

                        receipt = SQLitePerRunAuthorityStore(
                            str(cancellation["run_uri"])
                        ).read_cancellation_epoch_receipt(
                            str(cancellation["run_uri"]), str(operation_id)
                        )
                    except Exception:
                        receipt = None
                    if receipt is None:
                        conn.commit()
                        return None
            conn.execute(
                "UPDATE agent_controls SET state = 'applying' WHERE operation_id = ?",
                (control.operation_id,),
            )
            conn.commit()
            return control

    @_serialized_session_operation
    def acknowledge_control(
        self, session_id: str, effect: AgentControlEffect
    ) -> Mapping[str, PlainData]:
        rule, revision = self._authorize("control")
        _identifier(session_id, "session_id")
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
                ).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
                expected_principal=rule.principal_id,
            )
            self._check_current_session(
                session,
                rule,
                self._daemon._epoch or "",
                revision,  # type: ignore[attr-defined]
            )
            row = conn.execute(
                "SELECT request_json, state, effect_json FROM agent_controls "
                "WHERE operation_id = ? AND session_id = ?",
                (effect.operation_id, session_id),
            ).fetchone()
            if row is None:
                raise QueueConflictError("agent control is unavailable")
            control = AgentControl.from_value(json.loads(str(row["request_json"])))
            encoded = _canonical_json(effect.value())
            if row["effect_json"] is not None:
                if str(row["effect_json"]) != encoded:
                    raise QueueConflictError("agent control acknowledgement conflicts")
                conn.commit()
                return freeze_plain_data(
                    {
                        "operation_id": control.operation_id,
                        "state": str(row["state"]),
                        "code": effect.code,
                    },
                    path="agent control acknowledgement",
                )
            if control.expected_config_revision != session.config_revision:
                raise QueueConflictError("agent control acknowledgement is stale")
            applied = effect.code == "applied"
            if applied:
                conn.execute(
                    "UPDATE agent_sessions SET config_revision = ?, "
                    "inventory_revision = ?, availability_revision = ? "
                    "WHERE session_id = ?",
                    (
                        effect.config_revision,
                        effect.inventory_revision,
                        effect.availability_revision,
                        session_id,
                    ),
                )
                conn.execute(
                    "UPDATE agent_offers SET current = 0 WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "UPDATE agent_poll_state SET active = 0 WHERE session_id = ?",
                    (session_id,),
                )
            elif (
                effect.config_revision != session.config_revision
                or effect.inventory_revision != session.inventory_revision
                or effect.availability_revision != session.availability_revision
            ):
                raise QueueConflictError("failed agent control changed revisions")
            state = "applied" if applied else "failed"
            conn.execute(
                "UPDATE agent_controls SET state = ?, result_code = ?, "
                "effect_json = ?, acknowledged = 1 WHERE operation_id = ?",
                (state, effect.code, encoded, effect.operation_id),
            )
            conn.commit()
        return freeze_plain_data(
            {
                "operation_id": control.operation_id,
                "state": state,
                "code": effect.code,
            },
            path="agent control acknowledgement",
        )

    @_serialized_session_operation
    def next_assignment_control(self, session_id: str) -> AgentAssignmentControl | None:
        rule, revision = self._authorize("assignment_control")
        _identifier(session_id, "session_id")
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
                ).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
                expected_principal=rule.principal_id,
            )
            self._check_current_session(
                session,
                rule,
                self._daemon._epoch or "",
                revision,  # type: ignore[attr-defined]
            )
            row = conn.execute(
                "SELECT operation_id, request_json FROM remote_assignment_controls "
                "WHERE session_id = ? AND state IN ('pending_delivery', 'applying') "
                "ORDER BY operation_id LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            control = AgentAssignmentControl.from_value(
                json.loads(str(row["request_json"]))
            )
            conn.execute(
                "UPDATE remote_assignment_controls SET state = 'applying' "
                "WHERE operation_id = ?",
                (control.operation_id,),
            )
            conn.commit()
            return control

    @_serialized_session_operation
    def acknowledge_assignment_control(
        self,
        session_id: str,
        operation_id: str,
        *,
        code: str,
        evidence: Mapping[str, object] | None = None,
    ) -> Mapping[str, PlainData]:
        rule, revision = self._authorize("assignment_control")
        _identifier(session_id, "session_id")
        _identifier(operation_id, "operation_id")
        if code not in {"never_started", "contained", "terminal", "unknown"}:
            raise QueueServiceError("assignment control result code is invalid")
        parsed_evidence = (
            _managed_containment_evidence(evidence)
            if code == "contained" and evidence is not None
            else None
        )
        if code == "contained" and parsed_evidence is None:
            raise QueueServiceError(
                "contained assignment control requires supervisor evidence"
            )
        if code != "contained" and evidence is not None:
            raise QueueServiceError(
                "non-contained assignment control cannot carry containment evidence"
            )
        encoded_evidence = (
            None
            if parsed_evidence is None
            else json.dumps(
                dict(parsed_evidence), sort_keys=True, separators=(",", ":")
            )
        )
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
                ).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
                expected_principal=rule.principal_id,
            )
            self._check_current_session(
                session,
                rule,
                self._daemon._epoch or "",
                revision,  # type: ignore[attr-defined]
            )
            row = conn.execute(
                "SELECT request_json, result_code, evidence_json FROM remote_assignment_controls "
                "WHERE operation_id = ? AND session_id = ?",
                (operation_id, session_id),
            ).fetchone()
            if row is None:
                raise QueueConflictError("assignment control is unavailable")
            control = AgentAssignmentControl.from_value(
                json.loads(str(row["request_json"]))
            )
            if row["result_code"] is not None and str(row["result_code"]) != code:
                raise QueueConflictError("assignment control result conflicts")
            if (
                row["evidence_json"] is not None
                and str(row["evidence_json"]) != encoded_evidence
            ):
                raise QueueConflictError("assignment control evidence conflicts")
            state = "applied" if code != "unknown" else "settling"
            conn.execute(
                "UPDATE remote_assignment_controls SET state = ?, result_code = ?, "
                "evidence_json = ?, acknowledged = 1 WHERE operation_id = ?",
                (state, code, encoded_evidence, operation_id),
            )
            conn.commit()
        return freeze_plain_data(
            {
                "operation_id": control.operation_id,
                "assignment_id": control.assignment_id,
                "state": state,
                "code": code,
                "evidence": parsed_evidence,
            },
            path="assignment control acknowledgement",
        )

    @_serialized_session_operation
    def register(self, request: AgentRegistration) -> AgentSession:
        rule, policy_revision = self._authorize("register")
        coordinator_id = self._daemon._require_started()  # type: ignore[attr-defined]
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        if request.session_id is not None:
            raise QueueConflictError("agent callers cannot select a session ID")
        if request.retirement_verifier is None:
            raise QueueServiceError("agent retirement verifier is required")
        digest = _digest(request.value())
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            replay = _receipt(
                conn, rule.principal_id, "register", request.idempotency_key, digest
            )
            if replay is not None:
                replayed = _session_from_value(replay)
                current = _session_from_row(
                    conn.execute(
                        "SELECT * FROM agent_sessions WHERE session_id = ?",
                        (replayed.session_id,),
                    ).fetchone(),
                    coordinator_id,
                    expected_principal=rule.principal_id,
                )
                if current != replayed or current.state is not AgentSessionState.ACTIVE:
                    raise QueueConflictError(
                        "agent registration receipt is no longer actionable"
                    )
                if (
                    replayed.agent_id != rule.agent_id
                    or replayed.agent_root_id != request.agent_root_id
                    or not set(replayed.capabilities).issubset(rule.capabilities)
                    or not set(replayed.pools).issubset(rule.pools)
                ):
                    raise QueueServiceError(
                        "agent registration receipt is no longer authorized"
                    )
                conn.commit()
                return replayed
            if (
                request.coordinator_id != coordinator_id
                or request.coordinator_epoch != epoch
            ):
                raise QueueConflictError("coordinator identity or epoch is stale")
            previous = conn.execute(
                "SELECT session_id, state FROM agent_sessions WHERE agent_id = ? "
                "AND state NOT IN (?, ?) LIMIT 1",
                (
                    rule.agent_id,
                    AgentSessionState.RETIRED_CLEAN.value,
                    AgentSessionState.REPLACED.value,
                ),
            ).fetchone()
            if previous is not None:
                raise QueueConflictError("agent already has an active session")
            replacement = conn.execute(
                "SELECT r.*, s.agent_root_id, s.config_revision, "
                "s.inventory_revision, s.availability_revision, "
                "s.retirement_verifier FROM session_replacements r "
                "JOIN agent_sessions s ON s.session_id = r.old_session_id "
                "WHERE r.agent_id = ? AND r.state = 'decision' "
                "AND r.successor_session_id IS NULL AND s.state = ?",
                (rule.agent_id, AgentSessionState.REPLACED.value),
            ).fetchone()
            if replacement is not None and (
                request.agent_root_id == str(replacement["agent_root_id"])
                or request.config_revision == str(replacement["config_revision"])
                or request.inventory_revision == str(replacement["inventory_revision"])
                or request.availability_revision
                == str(replacement["availability_revision"])
                or request.retirement_verifier
                == str(replacement["retirement_verifier"])
            ):
                raise QueueConflictError(
                    "replacement registration requires fresh root and revisions"
                )
            effective_pools = tuple(
                sorted(set(request.declared_pools) & set(rule.pools))
            )
            if not effective_pools:
                raise QueueServiceError("agent has no authorized pool")
            session = AgentSession(
                session_id=f"session-{uuid4()}",
                coordinator_id=coordinator_id,
                coordinator_epoch=epoch,
                agent_id=rule.agent_id,
                agent_root_id=request.agent_root_id,
                policy_revision=policy_revision,
                config_revision=request.config_revision,
                inventory_revision=request.inventory_revision,
                availability_revision=request.availability_revision,
                capabilities=tuple(
                    sorted(set(request.declared_capabilities) & set(rule.capabilities))
                ),
                pools=effective_pools,
                state=AgentSessionState.ACTIVE,
            )
            accepted = self._daemon._accepted_time(conn)  # type: ignore[attr-defined]
            conn.execute(
                "INSERT INTO agent_sessions(session_id, agent_id, agent_root_id, principal_id, policy_revision, config_revision, inventory_revision, availability_revision, capabilities_json, pools_json, retirement_verifier, coordinator_epoch, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session.session_id,
                    rule.agent_id,
                    session.agent_root_id,
                    rule.principal_id,
                    session.policy_revision,
                    session.config_revision,
                    session.inventory_revision,
                    session.availability_revision,
                    json.dumps(session.capabilities),
                    json.dumps(session.pools),
                    request.retirement_verifier,
                    epoch,
                    session.state.value,
                    accepted,
                ),
            )
            if replacement is not None:
                request_value = json.loads(str(replacement["request_json"]))
                projection = json.loads(str(replacement["decision_projection_json"]))
                if not isinstance(request_value, Mapping) or not isinstance(
                    projection, Mapping
                ):
                    raise QueueStorageError("session replacement decision is invalid")
                replacement_request = SessionReplacementRequest.from_dict(request_value)
                result = _replacement_result(
                    request=replacement_request,
                    old_session_id=str(replacement["old_session_id"]),
                    successor_session_id=session.session_id,
                    state="bound",
                    readiness="withheld",
                    withholding_reason="successor_observation_required",
                    projection=cast(Mapping[str, PlainData], projection),
                )
                updated = conn.execute(
                    "UPDATE session_replacements SET successor_session_id = ?, "
                    "state = 'bound', readiness = 'withheld', "
                    "withholding_reason = 'successor_observation_required', "
                    "result_json = ? WHERE operation_id = ? AND state = 'decision' "
                    "AND successor_session_id IS NULL",
                    (
                        session.session_id,
                        _canonical_json(result),
                        str(replacement["operation_id"]),
                    ),
                ).rowcount
                if updated != 1:
                    raise QueueConflictError(
                        "replacement successor registration conflicts"
                    )
            _write_receipt(
                conn,
                rule.principal_id,
                "register",
                request.idempotency_key,
                digest,
                session.value(),
            )
            conn.commit()
        return session

    @_serialized_session_operation
    def reconcile(
        self,
        expected: AgentSession,
        coordinator_epoch: str,
        *,
        idempotency_key: str,
    ) -> AgentSession:
        rule, policy_revision = self._authorize("reconcile")
        _identifier(coordinator_epoch, "coordinator_epoch")
        _identifier(idempotency_key, "idempotency_key")
        request_value: dict[str, PlainData] = {
            "expected": expected.value(),
            "coordinator_epoch": coordinator_epoch,
        }
        digest = _digest(request_value)
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            replay = _receipt(
                conn,
                rule.principal_id,
                "reconcile",
                idempotency_key,
                digest,
            )
            if replay is not None:
                replayed = _session_from_value(replay)
                current = _session_from_row(
                    conn.execute(
                        "SELECT * FROM agent_sessions WHERE session_id = ?",
                        (replayed.session_id,),
                    ).fetchone(),
                    self._daemon._require_started(),  # type: ignore[attr-defined]
                    expected_principal=rule.principal_id,
                )
                if current != replayed or current.state is not AgentSessionState.ACTIVE:
                    raise QueueConflictError(
                        "agent reconciliation receipt is no longer actionable"
                    )
                if (
                    replayed.agent_id != rule.agent_id
                    or replayed.agent_root_id != expected.agent_root_id
                    or not set(replayed.capabilities).issubset(rule.capabilities)
                    or not set(replayed.pools).issubset(rule.pools)
                ):
                    raise QueueServiceError(
                        "agent reconciliation receipt is no longer authorized"
                    )
                conn.commit()
                return replayed
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?",
                    (expected.session_id,),
                ).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
                expected_principal=rule.principal_id,
            )
            if (
                session.agent_id != rule.agent_id
                or session.state is not AgentSessionState.ACTIVE
            ):
                raise QueueServiceError("agent session is not authorized")
            if (
                expected.session_id != session.session_id
                or expected.coordinator_id != session.coordinator_id
                or expected.coordinator_epoch != session.coordinator_epoch
                or expected.agent_id != session.agent_id
                or expected.agent_root_id != session.agent_root_id
                or expected.policy_revision != session.policy_revision
                or expected.config_revision != session.config_revision
                or expected.inventory_revision != session.inventory_revision
                or expected.availability_revision != session.availability_revision
                or expected.capabilities != session.capabilities
                or expected.pools != session.pools
                or expected.state is not AgentSessionState.ACTIVE
            ):
                raise QueueConflictError("agent session reconciliation facts are stale")
            if not set(session.capabilities).issubset(rule.capabilities) or not set(
                session.pools
            ).issubset(rule.pools):
                raise QueueServiceError(
                    "agent session effective scope is no longer current"
                )
            if coordinator_epoch != self._daemon._epoch:  # type: ignore[attr-defined]
                raise QueueConflictError("coordinator epoch is stale")
            resumed = AgentSession(
                session.session_id,
                session.coordinator_id,
                coordinator_epoch,
                session.agent_id,
                session.agent_root_id,
                policy_revision,
                session.config_revision,
                session.inventory_revision,
                session.availability_revision,
                session.capabilities,
                session.pools,
                session.state,
            )
            conn.execute(
                "UPDATE agent_sessions SET coordinator_epoch = ?, policy_revision = ? WHERE session_id = ?",
                (
                    coordinator_epoch,
                    policy_revision,
                    session.session_id,
                ),  # type: ignore[attr-defined]
            )
            _write_receipt(
                conn,
                rule.principal_id,
                "reconcile",
                idempotency_key,
                digest,
                resumed.value(),
            )
            conn.commit()
        return resumed

    @_serialized_offer_operation
    def publish_offer(
        self, offer: AgentOffer, *, idempotency_key: str
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("offer")
        execution = self._daemon._execution  # type: ignore[attr-defined]
        if execution is None:
            raise QueueServiceError("agent offer validation is unavailable")
        _identifier(idempotency_key, "idempotency_key")
        digest = _digest(offer.value())
        replacement_admission = _replacement_offer_admission(
            self._daemon, offer.session_id
        )
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?",
                    (offer.session_id,),
                ).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
                expected_principal=rule.principal_id,
            )
            self._check_current_session(
                session, rule, offer.coordinator_epoch, policy_revision
            )
            replay = _receipt(conn, rule.principal_id, "offer", idempotency_key, digest)
            if replay is not None:
                conn.commit()
                return replay
            execution.validate_agent_offer_provider_composition(offer)
            active_poll = conn.execute(
                "SELECT sequence FROM agent_poll_state "
                "WHERE session_id = ? AND active = 1",
                (offer.session_id,),
            ).fetchone()
            if active_poll is not None:
                raise QueueConflictError(
                    "agent offer cannot change during an active poll"
                )
            if (
                offer.config_revision,
                offer.inventory_revision,
                offer.availability_revision,
            ) != (
                session.config_revision,
                session.inventory_revision,
                session.availability_revision,
            ):
                raise QueueConflictError(
                    "agent offer revisions do not match its session"
                )
            if offer.pools != session.pools:
                raise QueueConflictError(
                    "agent offer pools do not match its effective scope"
                )
            if offer.gpu_devices != rule.gpu_devices:
                raise QueueConflictError(
                    "agent offer GPU inventory does not match protected policy"
                )
            if offer.resident_profiles and not {
                REMOTE_EXECUTION_CAPABILITY,
                REGULAR_FILE_RELAY_CAPABILITY,
            }.issubset(session.capabilities):
                raise QueueServiceError(
                    "agent session lacks remote execution capabilities"
                )
            replacement = conn.execute(
                "SELECT operation_id, old_session_id, readiness, "
                "decision_projection_digest FROM session_replacements "
                "WHERE successor_session_id = ?",
                (offer.session_id,),
            ).fetchone()
            if replacement is not None:
                if (
                    replacement_admission is None
                    or str(replacement["operation_id"])
                    != replacement_admission.operation_id
                    or str(replacement["old_session_id"])
                    != replacement_admission.old_session_id
                    or str(replacement["readiness"])
                    != replacement_admission.prior_readiness
                    or str(replacement["decision_projection_digest"])
                    != replacement_admission.decision_projection_digest
                ):
                    raise QueueConflictError(
                        "replacement readiness changed before observation"
                    )
                old_claim_ids = {
                    _projection_string(cast(Mapping[str, PlainData], item), "claim_id")
                    for item in cast(
                        Sequence[object],
                        replacement_admission.durable_projection["assignments"],
                    )
                    if isinstance(item, Mapping)
                }
                if old_claim_ids & set(offer.reflected_claim_ids):
                    raise QueueConflictError(
                        "replacement successor cannot inherit old claim identity"
                    )
                if (
                    replacement_admission.prior_readiness != "ready"
                    and offer.reflected_claim_ids
                ):
                    raise QueueConflictError(
                        "replacement successor first observation must be fresh"
                    )
            elif replacement_admission is not None:
                raise QueueConflictError(
                    "replacement readiness changed before observation"
                )
            accepted = self._daemon._accepted_time(conn)  # type: ignore[attr-defined]
            expiry = _add_seconds(accepted, offer.ttl_seconds)
            offer_id = f"offer-{uuid4()}"
            conn.execute(
                "UPDATE agent_offers SET current = 0 WHERE session_id = ?",
                (offer.session_id,),
            )
            conn.execute(
                "INSERT INTO agent_offers(offer_id, session_id, coordinator_epoch, availability_revision, offer_json, accepted_at, expires_at, current) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    offer_id,
                    offer.session_id,
                    offer.coordinator_epoch,
                    offer.availability_revision,
                    json.dumps(offer.value(), sort_keys=True, separators=(",", ":")),
                    accepted,
                    expiry,
                ),
            )
            value: dict[str, PlainData] = {
                "offer_id": offer_id,
                "accepted_at": accepted,
                "expires_at": expiry,
                "state": "retained",
            }
            if replacement_admission is not None:
                projection_json = _canonical_json(
                    replacement_admission.durable_projection
                )
                result = _replacement_result(
                    request=replacement_admission.request,
                    old_session_id=replacement_admission.old_session_id,
                    successor_session_id=offer.session_id,
                    state="ready",
                    readiness="ready",
                    withholding_reason=None,
                    projection=replacement_admission.durable_projection,
                )
                updated = conn.execute(
                    "UPDATE session_replacements SET state = 'ready', "
                    "readiness = 'ready', withholding_reason = NULL, "
                    "observed_claim_ids_json = ?, "
                    "successor_observation_digest = ?, "
                    "readiness_projection_digest = ?, result_json = ?, "
                    "ready_at = COALESCE(ready_at, ?) WHERE operation_id = ? "
                    "AND successor_session_id = ?",
                    (
                        json.dumps(
                            replacement_admission.projection.required_claim_ids,
                            separators=(",", ":"),
                        ),
                        _digest(offer.value()),
                        hashlib.sha256(projection_json.encode("utf-8")).hexdigest(),
                        _canonical_json(result),
                        accepted,
                        replacement_admission.operation_id,
                        offer.session_id,
                    ),
                ).rowcount
                if updated != 1:
                    raise QueueConflictError(
                        "replacement readiness changed before publication"
                    )
            _write_receipt(
                conn, rule.principal_id, "offer", idempotency_key, digest, value
            )
            conn.commit()
        return freeze_plain_data(value, path="agent offer receipt")

    def wait_for_work(
        self,
        session_id: str,
        availability_revision: str,
        *,
        sequence: int,
        wait_timeout_ms: int,
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("poll")
        for identifier, name in (
            (session_id, "session_id"),
            (availability_revision, "availability_revision"),
        ):
            _identifier(identifier, name)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise QueueServiceError("work poll sequence must be positive")
        if (
            isinstance(wait_timeout_ms, bool)
            or not isinstance(wait_timeout_ms, int)
            or not 1 <= wait_timeout_ms <= _MAX_POLL_WAIT_MILLISECONDS
        ):
            raise QueueServiceError("work poll wait is outside the permitted range")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        request_value: dict[str, PlainData] = {
            "session_id": session_id,
            "sequence": sequence,
            "availability_revision": availability_revision,
            "coordinator_epoch": epoch,
            "wait_timeout_ms": wait_timeout_ms,
        }
        digest = _digest(request_value)
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
                ).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
                expected_principal=rule.principal_id,
            )
            self._check_current_session(session, rule, epoch, policy_revision)
            if session.availability_revision != availability_revision:
                raise QueueConflictError("work poll availability revision is stale")
            replacement = conn.execute(
                "SELECT readiness FROM session_replacements "
                "WHERE successor_session_id = ?",
                (session_id,),
            ).fetchone()
            if replacement is not None and str(replacement["readiness"]) != "ready":
                raise QueueConflictError(
                    "replacement successor readiness is still withheld"
                )
            existing = conn.execute(
                "SELECT sequence, digest, active, result_json FROM agent_poll_state "
                "WHERE principal_id = ? AND session_id = ?",
                (rule.principal_id, session_id),
            ).fetchone()
            if existing is not None:
                stored_sequence = int(existing["sequence"])
                if sequence < stored_sequence:
                    raise AgentStalePollError("work poll sequence is stale")
                if sequence > stored_sequence + 1:
                    raise AgentPollSequenceGapError("work poll sequence has a gap")
                if sequence == stored_sequence and str(existing["digest"]) != digest:
                    raise QueueConflictError(
                        "poll sequence was reused with different content"
                    )
                if sequence == stored_sequence and existing["result_json"] is not None:
                    value = _plain_result(existing["result_json"], "agent poll receipt")
                    conn.commit()
                    return value
                if bool(existing["active"]):
                    raise AgentPollActiveError("work poll is already active")
                if sequence == stored_sequence:
                    raise QueueConflictError("work poll was fenced and is not reusable")
            elif sequence != 1:
                raise AgentPollSequenceGapError("work poll sequence has a gap")
            self._require_current_offer(conn, session_id, availability_revision)
            if existing is None:
                conn.execute(
                    "INSERT INTO agent_poll_state("
                    "principal_id, session_id, sequence, availability_revision, "
                    "coordinator_epoch, wait_timeout_ms, digest, active, result_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL)",
                    (
                        rule.principal_id,
                        session_id,
                        sequence,
                        availability_revision,
                        epoch,
                        wait_timeout_ms,
                        digest,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE agent_poll_state SET sequence = ?, "
                    "availability_revision = ?, coordinator_epoch = ?, "
                    "wait_timeout_ms = ?, digest = ?, active = 1, result_json = NULL "
                    "WHERE principal_id = ? AND session_id = ?",
                    (
                        sequence,
                        availability_revision,
                        epoch,
                        wait_timeout_ms,
                        digest,
                        rule.principal_id,
                        session_id,
                    ),
                )
            conn.commit()

        delivered = self._take_targeted_delivery(
            principal_id=rule.principal_id,
            session_id=session_id,
            availability_revision=availability_revision,
            sequence=sequence,
            epoch=epoch,
            digest=digest,
        )
        if delivered is not None:
            return delivered

        deadline = monotonic() + wait_timeout_ms / 1_000
        try:
            while monotonic() < deadline:
                sleep(
                    min(
                        self._daemon.config.poll_interval_seconds,  # type: ignore[attr-defined]
                        max(0.0, deadline - monotonic()),
                    )
                )
                rule, policy_revision = self._authorize("poll")
                with self._daemon._connection() as conn:  # type: ignore[attr-defined]
                    row = conn.execute(
                        "SELECT active, result_json FROM agent_poll_state "
                        "WHERE principal_id = ? AND session_id = ? "
                        "AND sequence = ? AND digest = ?",
                        (rule.principal_id, session_id, sequence, digest),
                    ).fetchone()
                    if row is None or not bool(row["active"]):
                        raise QueueConflictError("work poll was fenced")
                    session = _session_from_row(
                        conn.execute(
                            "SELECT * FROM agent_sessions WHERE session_id = ?",
                            (session_id,),
                        ).fetchone(),
                        self._daemon._require_started(),  # type: ignore[attr-defined]
                        expected_principal=rule.principal_id,
                    )
                    self._check_current_session(session, rule, epoch, policy_revision)
                    self._require_current_offer(conn, session_id, availability_revision)
                delivered = self._take_targeted_delivery(
                    principal_id=rule.principal_id,
                    session_id=session_id,
                    availability_revision=availability_revision,
                    sequence=sequence,
                    epoch=epoch,
                    digest=digest,
                )
                if delivered is not None:
                    return delivered
            value = {
                "result": "wait",
                "sequence": sequence,
                "coordinator_epoch": epoch,
            }
            rule, policy_revision = self._authorize("poll")
            with self._daemon._connection() as conn:  # type: ignore[attr-defined]
                conn.execute("BEGIN IMMEDIATE")
                session = _session_from_row(
                    conn.execute(
                        "SELECT * FROM agent_sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone(),
                    self._daemon._require_started(),  # type: ignore[attr-defined]
                    expected_principal=rule.principal_id,
                )
                self._check_current_session(session, rule, epoch, policy_revision)
                self._require_current_offer(conn, session_id, availability_revision)
                updated = conn.execute(
                    "UPDATE agent_poll_state SET active = 0, result_json = ? "
                    "WHERE principal_id = ? AND session_id = ? AND sequence = ? "
                    "AND digest = ? AND active = 1",
                    (
                        _canonical_json(value),
                        rule.principal_id,
                        session_id,
                        sequence,
                        digest,
                    ),
                ).rowcount
                if updated != 1:
                    raise QueueConflictError("work poll was fenced")
                conn.commit()
            return freeze_plain_data(value, path="agent wait")
        except Exception:
            with self._daemon._connection() as conn:  # type: ignore[attr-defined]
                conn.execute(
                    "UPDATE agent_poll_state SET active = 0 WHERE principal_id = ? "
                    "AND session_id = ? AND sequence = ? AND digest = ?",
                    (rule.principal_id, session_id, sequence, digest),
                )
                conn.commit()
            raise

    def _take_targeted_delivery(
        self,
        *,
        principal_id: str,
        session_id: str,
        availability_revision: str,
        sequence: int,
        epoch: str,
        digest: str,
    ) -> Mapping[str, PlainData] | None:
        """Consume only an already-CAS-targeted delivery for this exact poll."""
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT assignment_id, request_json FROM agent_deliveries "
                "WHERE session_id = ? AND availability_revision = ? AND "
                "coordinator_epoch = ? AND state = 'TARGETED' ORDER BY assignment_id LIMIT 1",
                (session_id, availability_revision, epoch),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            value: dict[str, PlainData] = {
                "result": "assignment",
                "sequence": sequence,
                "coordinator_epoch": epoch,
                "request": cast(PlainData, json.loads(str(row["request_json"]))),
            }
            updated = conn.execute(
                "UPDATE agent_deliveries SET state = 'DELIVERED', poll_sequence = ? "
                "WHERE assignment_id = ? AND state = 'TARGETED'",
                (sequence, str(row["assignment_id"])),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("targeted delivery changed before its poll")
            updated = conn.execute(
                "UPDATE agent_poll_state SET active = 0, result_json = ? WHERE "
                "principal_id = ? AND session_id = ? AND sequence = ? "
                "AND digest = ? AND active = 1",
                (
                    _canonical_json(value),
                    principal_id,
                    session_id,
                    sequence,
                    digest,
                ),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("work poll was fenced")
            conn.commit()
        return freeze_plain_data(value, path="agent assignment delivery")

    @_serialized_session_operation
    def authorize_transfers(
        self,
        session_id: str,
        assignment_id: str,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("authorize")
        _identifier(operation_id, "operation_id")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise QueueServiceError("transfer authorization revision is invalid")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            self._require_remote_assignment(conn, session_id, assignment_id)
            replay = conn.execute(
                "SELECT assignment_id, authorization_id, revision, "
                "coordinator_epoch, expires_at "
                "FROM remote_transfer_authorizations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if replay is not None:
                if (
                    str(replay["assignment_id"]) != assignment_id
                    or int(replay["revision"]) != expected_revision + 1
                ):
                    raise QueueConflictError("transfer authorization replay conflicts")
                value = {
                    "authorization_id": str(replay["authorization_id"]),
                    "revision": int(replay["revision"]),
                    "coordinator_epoch": str(replay["coordinator_epoch"]),
                    "expires_at": str(replay["expires_at"]),
                }
                conn.commit()
                return freeze_plain_data(value, path="transfer authorization")
            current = int(
                conn.execute(
                    "SELECT COALESCE(MAX(revision), 0) FROM "
                    "remote_transfer_authorizations WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0]
            )
            if current != expected_revision:
                raise QueueConflictError("transfer authorization revision is stale")
            if current >= _MAX_TRANSFER_AUTHORIZATIONS:
                raise QueueConflictError(
                    "transfer authorization renewal exceeded its bound"
                )
            revision = current + 1
            authorization_id = f"authorization-{uuid4()}"
            expires_at = _add_seconds(
                self._daemon._accepted_time(conn),
                60,  # type: ignore[attr-defined]
            )
            conn.execute(
                "INSERT INTO remote_transfer_authorizations(assignment_id, "
                "authorization_id, revision, coordinator_epoch, operation_id, "
                "expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    assignment_id,
                    authorization_id,
                    revision,
                    epoch,
                    operation_id,
                    expires_at,
                ),
            )
            conn.commit()
        return freeze_plain_data(
            {
                "authorization_id": authorization_id,
                "revision": revision,
                "coordinator_epoch": epoch,
                "expires_at": expires_at,
            },
            path="transfer authorization",
        )

    @_serialized_session_operation
    def read_input_chunk(
        self,
        session_id: str,
        assignment_id: str,
        transfer_id: str,
        *,
        offset: int,
        authorization_id: str,
        authorization_revision: int,
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("input")
        _identifier(transfer_id, "transfer_id")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise QueueServiceError("input transfer offset is invalid")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            self._require_remote_assignment(conn, session_id, assignment_id)
            self._require_transfer_authorization(
                conn,
                assignment_id,
                authorization_id,
                authorization_revision,
                epoch,
            )
            row = conn.execute(
                "SELECT size_bytes, private_path FROM remote_transfers WHERE "
                "assignment_id = ? AND direction = 'input' AND transfer_id = ? "
                "AND finalized = 1",
                (assignment_id, transfer_id),
            ).fetchone()
            if row is None:
                raise QueueConflictError("remote input transfer is unavailable")
            size = int(row["size_bytes"])
            if offset > size:
                raise QueueConflictError("input transfer offset exceeds its size")
            path = Path(str(row["private_path"]))
            with path.open("rb") as stream:
                stream.seek(offset)
                data = stream.read(TRANSFER_CHUNK_BYTES)
        return freeze_plain_data(
            {
                "transfer_id": transfer_id,
                "offset": offset,
                "data": _encode_chunk(data),
                "next_offset": offset + len(data),
                "final": offset + len(data) == size,
            },
            path="remote input chunk",
        )

    @_serialized_session_operation
    def accept_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        request_digest: str,
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("accept")
        _secret_digest(request_digest, "request digest")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            delivery = conn.execute(
                "SELECT request_json, state FROM agent_deliveries "
                "WHERE assignment_id = ? AND session_id = ?",
                (assignment_id, session_id),
            ).fetchone()
            if delivery is None or str(delivery["state"]) != "DELIVERED":
                raise QueueConflictError("remote assignment was not delivered")
            if (
                hashlib.sha256(str(delivery["request_json"]).encode()).hexdigest()
                != request_digest
            ):
                raise QueueConflictError("remote durable request digest conflicts")
            if row["fence"] is not None:
                conn.commit()
                return freeze_plain_data(
                    {
                        "assignment_id": assignment_id,
                        "fence": str(row["fence"]),
                        "state": str(row["state"]),
                    },
                    path="remote assignment grant",
                )
            cancellation = conn.execute(
                "SELECT cancellation_operation_id FROM managed_admissions "
                "WHERE run_uri = ?",
                (str(row["run_uri"]),),
            ).fetchone()
            if cancellation is not None and cancellation[0] is not None:
                raise QueueConflictError("remote assignment run is cancelling")
            fence = self._remote_execution().remote_accept(assignment_id)
            conn.execute(
                "UPDATE remote_assignments SET state = 'GRANTED', fence = ? "
                "WHERE assignment_id = ?",
                (fence, assignment_id),
            )
            conn.commit()
        return freeze_plain_data(
            {"assignment_id": assignment_id, "fence": fence, "state": "GRANTED"},
            path="remote assignment grant",
        )

    @_serialized_session_operation
    def start_permit(self, session_id: str, assignment_id: str, *, fence: str) -> bool:
        """Check the effective run barrier immediately before local launch."""

        rule, policy_revision = self._authorize("start_permit")
        _identifier(fence, "fence")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            if row["fence"] != fence or str(row["state"]) not in {
                "GRANTED",
                "RUNNING",
            }:
                raise QueueConflictError("remote start permit fence is stale")
            cancellation = conn.execute(
                "SELECT cancellation_operation_id FROM managed_admissions "
                "WHERE run_uri = ?",
                (str(row["run_uri"]),),
            ).fetchone()
            if cancellation is not None and cancellation[0] is not None:
                conn.commit()
                return False
            permitted = self._remote_execution().remote_start_permit(
                assignment_id, fence=fence
            )
            if permitted:
                conn.execute(
                    "UPDATE remote_assignments SET start_permitted = 1 "
                    "WHERE assignment_id = ? AND fence = ?",
                    (assignment_id, fence),
                )
            conn.commit()
            return permitted

    @_serialized_session_operation
    def decline_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        availability_revision: str,
    ) -> AgentSession:
        rule, policy_revision = self._authorize("decline")
        _identifier(availability_revision, "availability_revision")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            session = self._require_remote_session(
                conn, rule, policy_revision, session_id, epoch
            )
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            if row["fence"] is not None or str(row["state"]) not in {
                "BOUND",
                "RELEASED",
            }:
                raise QueueConflictError(
                    "remote assignment cannot be definitively declined"
                )
            if str(row["state"]) == "RELEASED":
                if row["next_availability_revision"] != availability_revision:
                    raise QueueConflictError("remote decline replay conflicts")
                return AgentSession(
                    session.session_id,
                    session.coordinator_id,
                    session.coordinator_epoch,
                    session.agent_id,
                    session.agent_root_id,
                    session.policy_revision,
                    session.config_revision,
                    session.inventory_revision,
                    availability_revision,
                    session.capabilities,
                    session.pools,
                    session.state,
                )
        self._remote_execution().remote_decline(assignment_id)
        resumed = AgentSession(
            session.session_id,
            session.coordinator_id,
            session.coordinator_epoch,
            session.agent_id,
            session.agent_root_id,
            session.policy_revision,
            session.config_revision,
            session.inventory_revision,
            availability_revision,
            session.capabilities,
            session.pools,
            session.state,
        )
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE remote_assignments SET state = 'RELEASED', "
                "next_availability_revision = ? WHERE assignment_id = ?",
                (availability_revision, assignment_id),
            )
            conn.execute(
                "UPDATE agent_sessions SET availability_revision = ? "
                "WHERE session_id = ?",
                (availability_revision, session_id),
            )
            conn.execute(
                "UPDATE agent_offers SET current = 0 WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "UPDATE agent_coordinator_references SET resolved = 1 WHERE "
                "session_id = ? AND reference_kind = 'delivery' "
                "AND reference_id = ?",
                (session_id, assignment_id),
            )
            conn.execute(
                "UPDATE remote_assignment_controls SET state = 'applied', "
                "result_code = 'never_started', acknowledged = 1 "
                "WHERE assignment_id = ?",
                (assignment_id,),
            )
            conn.commit()
        return resumed

    @_serialized_session_operation
    def confirm_started(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        process_execution_id: str,
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("started")
        _identifier(fence, "fence")
        _identifier(process_execution_id, "process_execution_id")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            if row["fence"] != fence or str(row["state"]) not in {
                "GRANTED",
                "RUNNING",
            }:
                raise QueueConflictError("remote start grant is stale")
        self._remote_execution().remote_started(
            assignment_id, fence=fence, process_execution_id=process_execution_id
        )
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE remote_assignments SET state = 'RUNNING' "
                "WHERE assignment_id = ? AND fence = ?",
                (assignment_id, fence),
            )
            conn.commit()
        return freeze_plain_data(
            {"assignment_id": assignment_id, "state": "RUNNING"},
            path="remote start confirmation",
        )

    @_serialized_session_operation
    def report_event(
        self,
        session_id: str,
        assignment_id: str,
        *,
        sequence: int,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("event")
        _identifier(event_id, "event_id")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise QueueServiceError("remote event sequence is invalid")
        frozen_payload = freeze_plain_data(payload, path="remote event")
        if not isinstance(frozen_payload, Mapping):
            raise QueueServiceError("remote event payload is invalid")
        _reject_path_bearing_data(frozen_payload, "remote event")
        if (
            len(_canonical_json(frozen_payload).encode("utf-8"))
            > _MAX_REMOTE_EVENT_BYTES
        ):
            raise QueueServiceError("remote event payload exceeds its bound")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            if str(row["state"]) not in {
                "RUNNING",
                "RESULT_RETAINED",
                "TERMINAL",
            }:
                raise QueueConflictError(
                    "remote event requires a started retained assignment"
                )
        acknowledged = self._remote_execution().remote_event(
            assignment_id,
            sequence=sequence,
            event_id=event_id,
            payload=frozen_payload,
        )
        return freeze_plain_data(
            {"assignment_id": assignment_id, "acknowledged_sequence": acknowledged},
            path="remote event acknowledgement",
        )

    @_serialized_session_operation
    def declare_outputs(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        authorization_id: str,
        authorization_revision: int,
        report: _RemoteExecutionReport,
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("output_manifest")
        _identifier(fence, "fence")
        if report.assignment_id != assignment_id:
            raise QueueConflictError("remote report targets another assignment")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        encoded = _canonical_json(report.to_dict())
        if len(encoded.encode("utf-8")) > _MAX_REMOTE_WIRE_VALUE_BYTES:
            raise QueueServiceError("remote result manifest exceeds its bound")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            self._require_transfer_authorization(
                conn,
                assignment_id,
                authorization_id,
                authorization_revision,
                epoch,
            )
            if row["fence"] != fence or str(row["state"]) not in {
                "GRANTED",
                "RUNNING",
                "RESULT_RETAINED",
                "TERMINAL",
            }:
                raise QueueConflictError("remote result fence is stale")
            delivery = conn.execute(
                "SELECT request_json FROM agent_deliveries WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if delivery is None:
                raise QueueConflictError("remote delivered request is unavailable")
            request = _ResidentAssignmentBundle.from_dict(
                json.loads(str(delivery["request_json"]))
            )
            output_mismatch = (
                set(item.logical_name for item in report.outputs)
                != set(request.declared_outputs)
                if report.status is StageStatus.SUCCEEDED
                else bool(report.outputs)
            )
            if (
                report.stage_name != request.stage_name
                or report.attempt != request.attempt
                or output_mismatch
            ):
                raise QueueConflictError("remote result does not match its request")
            if row["report_json"] is not None:
                if str(row["report_json"]) != encoded:
                    raise QueueConflictError("remote result replay conflicts")
                conn.commit()
                return freeze_plain_data(
                    {"assignment_id": assignment_id, "state": str(row["state"])},
                    path="remote output manifest",
                )
            for item in report.outputs:
                target = (
                    self._daemon.config.coordinator_root  # type: ignore[attr-defined]
                    / "remote-relay"
                    / assignment_id
                    / "outputs"
                    / item.logical_name
                )
                conn.execute(
                    "INSERT INTO remote_transfers(assignment_id, direction, "
                    "transfer_id, logical_name, digest, size_bytes, private_path, "
                    "received_bytes, finalized, descriptor_json) "
                    "VALUES (?, 'output', ?, ?, ?, ?, ?, 0, 0, ?)",
                    (
                        assignment_id,
                        item.transfer_id,
                        item.logical_name,
                        item.digest,
                        item.size_bytes,
                        str(target),
                        _canonical_json(item.to_dict()),
                    ),
                )
            conn.execute(
                "UPDATE remote_assignments SET state = 'RESULT_RETAINED', "
                "report_json = ?, report_digest = ? WHERE assignment_id = ?",
                (encoded, digest, assignment_id),
            )
            if report.status is StageStatus.CANCELLED:
                code = (
                    "contained" if str(row["state"]) == "RUNNING" else "never_started"
                )
                conn.execute(
                    "UPDATE remote_assignment_controls SET state = 'applied', "
                    "result_code = ?, acknowledged = 1 WHERE assignment_id = ?",
                    (code, assignment_id),
                )
            conn.commit()
        return freeze_plain_data(
            {"assignment_id": assignment_id, "state": "RESULT_RETAINED"},
            path="remote output manifest",
        )

    @_serialized_session_operation
    def upload_output_chunk(
        self,
        session_id: str,
        assignment_id: str,
        transfer_id: str,
        *,
        offset: int,
        data: bytes,
        final: bool,
        authorization_id: str,
        authorization_revision: int,
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("output")
        _identifier(transfer_id, "transfer_id")
        if (
            isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or not isinstance(data, bytes)
            or len(data) > TRANSFER_CHUNK_BYTES
            or not isinstance(final, bool)
        ):
            raise QueueServiceError("remote output chunk is invalid")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            self._require_remote_assignment(conn, session_id, assignment_id)
            self._require_transfer_authorization(
                conn,
                assignment_id,
                authorization_id,
                authorization_revision,
                epoch,
            )
            row = conn.execute(
                "SELECT digest, size_bytes, private_path, received_bytes, "
                "finalized FROM remote_transfers WHERE assignment_id = ? AND "
                "direction = 'output' AND transfer_id = ?",
                (assignment_id, transfer_id),
            ).fetchone()
            if row is None:
                raise QueueConflictError("remote output transfer is not declared")
            target = Path(str(row["private_path"]))
            received = int(row["received_bytes"])
            size = int(row["size_bytes"])
            if bool(row["finalized"]):
                if offset + len(data) > size:
                    raise QueueConflictError("output replay exceeds durable content")
                with target.open("rb") as stream:
                    stream.seek(offset)
                    if stream.read(len(data)) != data:
                        raise QueueConflictError(
                            "output replay conflicts with durable bytes"
                        )
                return freeze_plain_data(
                    {"transfer_id": transfer_id, "received_bytes": size, "final": True},
                    path="remote output chunk",
                )
            if _published_file_matches(
                target, size_bytes=size, digest=str(row["digest"])
            ):
                received = size
                conn.execute(
                    "UPDATE remote_transfers SET received_bytes = ?, finalized = 1 "
                    "WHERE assignment_id = ? AND direction = 'output' "
                    "AND transfer_id = ?",
                    (received, assignment_id, transfer_id),
                )
                if offset + len(data) > size:
                    raise QueueConflictError("output replay exceeds durable content")
                if _read_regular_file_range(target, offset, len(data)) != data:
                    raise QueueConflictError(
                        "output replay conflicts with durable bytes"
                    )
                conn.commit()
                return freeze_plain_data(
                    {"transfer_id": transfer_id, "received_bytes": size, "final": True},
                    path="remote output chunk",
                )
            staging = target.with_name(f".{transfer_id}.part")
            received = _append_exact_chunk(staging, offset, received, data)
            if received > size:
                raise QueueConflictError("remote output exceeds declared size")
            should_finalize = final or received == size
            if should_finalize:
                if received != size or _file_digest(staging) != str(row["digest"]):
                    raise QueueConflictError(
                        "remote output bytes do not match their manifest"
                    )
                _publish_staged_file(staging, target)
                conn.execute(
                    "UPDATE remote_transfers SET received_bytes = ?, finalized = 1 "
                    "WHERE assignment_id = ? AND direction = 'output' "
                    "AND transfer_id = ?",
                    (received, assignment_id, transfer_id),
                )
            else:
                conn.execute(
                    "UPDATE remote_transfers SET received_bytes = ? WHERE "
                    "assignment_id = ? AND direction = 'output' AND transfer_id = ?",
                    (received, assignment_id, transfer_id),
                )
            conn.commit()
        return freeze_plain_data(
            {
                "transfer_id": transfer_id,
                "received_bytes": received,
                "final": should_finalize,
            },
            path="remote output chunk",
        )

    @_serialized_session_operation
    def commit_result(
        self, session_id: str, assignment_id: str, *, fence: str
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("result")
        _identifier(fence, "fence")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            self._require_remote_session(conn, rule, policy_revision, session_id, epoch)
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            if row["fence"] != fence or str(row["state"]) not in {
                "RESULT_RETAINED",
                "TERMINAL",
                "RELEASED",
            }:
                raise QueueConflictError("remote terminal result fence is stale")
            if row["report_json"] is None:
                raise QueueConflictError("remote terminal report is unavailable")
            report = _RemoteExecutionReport.from_dict(
                json.loads(str(row["report_json"]))
            )
            pending = int(
                conn.execute(
                    "SELECT COUNT(*) FROM remote_transfers WHERE assignment_id = ? "
                    "AND direction = 'output' AND finalized = 0",
                    (assignment_id,),
                ).fetchone()[0]
            )
            if pending:
                raise QueueConflictError("remote output manifest is incomplete")
            outputs = self._coordinator_output_refs(conn, assignment_id)
            if str(row["state"]) in {"TERMINAL", "RELEASED"}:
                return freeze_plain_data(
                    {"assignment_id": assignment_id, "state": str(row["state"])},
                    path="remote result commit",
                )
        self._remote_execution().remote_commit(
            assignment_id, fence=fence, report=report, outputs=outputs
        )
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE remote_assignments SET state = 'TERMINAL' "
                "WHERE assignment_id = ?",
                (assignment_id,),
            )
            conn.commit()
        return freeze_plain_data(
            {"assignment_id": assignment_id, "state": "TERMINAL"},
            path="remote result commit",
        )

    @_serialized_session_operation
    def release_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        availability_revision: str,
        provider_release_proof: AgentProviderReleaseProof,
    ) -> AgentSession:
        rule, policy_revision = self._authorize("release")
        _identifier(fence, "fence")
        _identifier(availability_revision, "availability_revision")
        if not isinstance(provider_release_proof, AgentProviderReleaseProof):
            raise QueueServiceError("agent provider release proof is invalid")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        recovery: RecoverUnknownAssignment | None = None
        released_claim_id: str | None = None
        proof_json = _canonical_json(provider_release_proof.redacted_value())
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            session = self._require_remote_cleanup_session(
                conn, rule, policy_revision, session_id, epoch
            )
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            replaced = session.state is AgentSessionState.REPLACED
            if row["fence"] != fence:
                raise QueueConflictError("remote release fence is stale")
            _require_matching_provider_release_proof(
                session,
                provider_release_proof,
                assignment_id=assignment_id,
                fence=fence,
                availability_revision=availability_revision,
            )
            _verify_retirement_secret(
                conn, session.session_id, provider_release_proof.retirement_secret
            )
            retained_proof = row["provider_release_proof_json"]
            if retained_proof is not None and str(retained_proof) != proof_json:
                raise QueueConflictError("remote provider release proof conflicts")
            if str(row["state"]) == "RELEASED":
                if (
                    row["next_availability_revision"] != availability_revision
                    or retained_proof is None
                ):
                    raise QueueConflictError("remote release replay conflicts")
                conn.commit()
                return AgentSession(
                    session.session_id,
                    session.coordinator_id,
                    session.coordinator_epoch,
                    session.agent_id,
                    session.agent_root_id,
                    session.policy_revision,
                    session.config_revision,
                    session.inventory_revision,
                    availability_revision,
                    session.capabilities,
                    session.pools,
                    session.state,
                )
            if replaced:
                recovery, released_claim_id = _replacement_cleanup_recovery(
                    conn,
                    session_id=session_id,
                    assignment_id=assignment_id,
                    fence=fence,
                )
                control = conn.execute(
                    "SELECT operation_id FROM remote_assignment_controls "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()
                if (
                    control is None
                    or provider_release_proof.recovery_control_operation_id
                    != str(control["operation_id"])
                    or provider_release_proof.claim_id != released_claim_id
                ):
                    raise QueueConflictError(
                        "replacement provider release proof is stale"
                    )
            elif str(row["state"]) != "TERMINAL":
                raise QueueConflictError("remote release fence is stale")
            if retained_proof is None:
                conn.execute(
                    "UPDATE remote_assignments SET provider_release_proof_json = ? "
                    "WHERE assignment_id = ?",
                    (proof_json, assignment_id),
                )
            conn.commit()
        if recovery is None:
            self._remote_execution().remote_release(assignment_id)
        else:
            self._remote_execution().remote_release_recovered(recovery)
        resumed = AgentSession(
            session.session_id,
            session.coordinator_id,
            session.coordinator_epoch,
            session.agent_id,
            session.agent_root_id,
            session.policy_revision,
            session.config_revision,
            session.inventory_revision,
            availability_revision,
            session.capabilities,
            session.pools,
            session.state,
        )
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                "UPDATE remote_assignments SET state = 'RELEASED', "
                "next_availability_revision = ? WHERE assignment_id = ? "
                "AND provider_release_proof_json = ?",
                (availability_revision, assignment_id, proof_json),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("remote provider release proof is unavailable")
            conn.execute(
                "UPDATE agent_sessions SET availability_revision = ? "
                "WHERE session_id = ?",
                (availability_revision, session_id),
            )
            conn.execute(
                "UPDATE agent_offers SET current = 0 WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "UPDATE agent_coordinator_references SET resolved = 1 WHERE "
                "session_id = ? AND reference_kind = 'delivery' AND reference_id = ?",
                (session_id, assignment_id),
            )
            conn.execute(
                "UPDATE remote_assignment_controls SET state = 'applied', "
                "result_code = COALESCE(result_code, 'terminal'), acknowledged = 1 "
                "WHERE assignment_id = ?",
                (assignment_id,),
            )
            if released_claim_id is not None:
                replacement = conn.execute(
                    "SELECT readiness, observed_claim_ids_json, result_json "
                    "FROM session_replacements WHERE old_session_id = ?",
                    (session_id,),
                ).fetchone()
                if replacement is None:
                    raise QueueConflictError(
                        "replacement cleanup decision is unavailable"
                    )
                try:
                    observed = json.loads(str(replacement["observed_claim_ids_json"]))
                except json.JSONDecodeError as exc:
                    raise QueueStorageError(
                        "replacement cleanup claim inventory is invalid"
                    ) from exc
                if (
                    not isinstance(observed, list)
                    or any(not isinstance(item, str) for item in observed)
                    or len(set(observed)) != len(observed)
                ):
                    raise QueueStorageError(
                        "replacement cleanup claim inventory is invalid"
                    )
                if (
                    str(replacement["readiness"]) == "ready"
                    and released_claim_id not in observed
                ):
                    raise QueueConflictError(
                        "replacement cleanup claim is not currently withheld"
                    )
                result = _replacement_cleanup_result(replacement["result_json"])
                conn.execute(
                    "UPDATE session_replacements SET observed_claim_ids_json = ?, "
                    "result_json = ? "
                    "WHERE old_session_id = ?",
                    (
                        json.dumps(
                            [item for item in observed if item != released_claim_id],
                            separators=(",", ":"),
                        ),
                        _canonical_json(result),
                        session_id,
                    ),
                )
            conn.commit()
        return resumed

    def _require_remote_session(
        self,
        conn: sqlite3.Connection,
        rule: AgentPrincipalPolicy,
        policy_revision: str,
        session_id: str,
        epoch: str,
    ) -> AgentSession:
        session = _session_from_row(
            conn.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone(),
            self._daemon._require_started(),  # type: ignore[attr-defined]
            expected_principal=rule.principal_id,
        )
        self._check_current_session(session, rule, epoch, policy_revision)
        if not {
            REMOTE_EXECUTION_CAPABILITY,
            REGULAR_FILE_RELAY_CAPABILITY,
        }.issubset(session.capabilities):
            raise QueueServiceError("agent session lacks remote execution capabilities")
        return session

    def _require_remote_cleanup_session(
        self,
        conn: sqlite3.Connection,
        rule: AgentPrincipalPolicy,
        policy_revision: str,
        session_id: str,
        epoch: str,
    ) -> AgentSession:
        session = _session_from_row(
            conn.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone(),
            self._daemon._require_started(),  # type: ignore[attr-defined]
            expected_principal=rule.principal_id,
        )
        if session.state is AgentSessionState.ACTIVE:
            self._check_current_session(session, rule, epoch, policy_revision)
        elif (
            session.state is not AgentSessionState.REPLACED
            or session.agent_id != rule.agent_id
        ):
            raise QueueServiceError("agent session is not authorized")
        if not {
            REMOTE_EXECUTION_CAPABILITY,
            REGULAR_FILE_RELAY_CAPABILITY,
        }.issubset(session.capabilities):
            raise QueueServiceError("agent session lacks remote execution capabilities")
        return session

    @staticmethod
    def _require_remote_assignment(
        conn: sqlite3.Connection, session_id: str, assignment_id: str
    ) -> sqlite3.Row:
        _identifier(assignment_id, "assignment_id")
        row = conn.execute(
            "SELECT * FROM remote_assignments WHERE assignment_id = ? "
            "AND session_id = ?",
            (assignment_id, session_id),
        ).fetchone()
        if row is None:
            raise QueueConflictError("remote assignment is not retained")
        return row

    def _require_transfer_authorization(
        self,
        conn: sqlite3.Connection,
        assignment_id: str,
        authorization_id: str,
        revision: int,
        epoch: str,
    ) -> None:
        _identifier(authorization_id, "authorization_id")
        row = conn.execute(
            "SELECT coordinator_epoch, expires_at FROM "
            "remote_transfer_authorizations WHERE assignment_id = ? AND "
            "authorization_id = ? AND revision = ?",
            (assignment_id, authorization_id, revision),
        ).fetchone()
        if (
            row is None
            or str(row["coordinator_epoch"]) != epoch
            or str(row["expires_at"]) < self._daemon._accepted_time(conn)  # type: ignore[attr-defined]
        ):
            raise AgentTransferAuthorizationStaleError(
                "remote transfer authorization is stale"
            )

    @staticmethod
    def _coordinator_output_refs(
        conn: sqlite3.Connection, assignment_id: str
    ) -> dict[str, ArtifactRef]:
        outputs: dict[str, ArtifactRef] = {}
        for row in conn.execute(
            "SELECT logical_name, private_path, descriptor_json FROM "
            "remote_transfers WHERE assignment_id = ? AND direction = 'output' "
            "AND finalized = 1 ORDER BY logical_name",
            (assignment_id,),
        ):
            descriptor = _RemoteOutputArtifact.from_dict(
                json.loads(str(row["descriptor_json"]))
            )
            path = Path(str(row["private_path"]))
            outputs[str(row["logical_name"])] = ArtifactRef(
                artifact_id=descriptor.artifact_id,
                uri=path.resolve().as_uri(),
                artifact_type=descriptor.artifact_type,
                codec_key=descriptor.codec_key,
                schema_version=descriptor.artifact_schema_version,
                checksum=f"sha256:{descriptor.digest}",
                fingerprint=descriptor.fingerprint,
                producer_stage=descriptor.producer_stage,
                created_at=descriptor.created_at,
                metadata=descriptor.metadata,
            )
        return outputs

    def _remote_execution(self):  # type: ignore[no-untyped-def]
        execution = self._daemon._execution  # type: ignore[attr-defined]
        if execution is None:
            raise QueueServiceError("remote execution owner is unavailable")
        return execution

    @_serialized_session_operation
    def retire_clean(
        self, proof: AgentRetirementProof, *, idempotency_key: str
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("retire")
        _identifier(idempotency_key, "idempotency_key")
        if proof.agent_id != rule.agent_id:
            raise QueueServiceError("agent session is not authorized")
        digest = _digest(proof.value())
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]

        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            replay = _receipt(
                conn, rule.principal_id, "retire", idempotency_key, digest
            )
            if replay is not None:
                conn.commit()
                return replay
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?",
                    (proof.session_id,),
                ).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
                expected_principal=rule.principal_id,
            )
            self._check_retirable_session(session, rule, epoch, policy_revision)
            _require_matching_retirement_proof(session, proof)
            _verify_retirement_secret(conn, session.session_id, proof.retirement_secret)
            conn.execute(
                "UPDATE agent_offers SET current = 0 WHERE session_id = ?",
                (session.session_id,),
            )
            conn.execute(
                "UPDATE agent_poll_state SET active = 0 WHERE session_id = ?",
                (session.session_id,),
            )
            conn.execute(
                "UPDATE agent_sessions SET state = ? WHERE session_id = ?",
                (AgentSessionState.RETIRING.value, session.session_id),
            )
            conn.commit()

        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            rule, _policy_revision = self._authorize("retire")
            if proof.agent_id != rule.agent_id:
                raise QueueServiceError("agent session is not authorized")
            replay = _receipt(
                conn, rule.principal_id, "retire", idempotency_key, digest
            )
            if replay is not None:
                conn.commit()
                return replay
            session = _session_from_row(
                conn.execute(
                    "SELECT * FROM agent_sessions WHERE session_id = ?",
                    (proof.session_id,),
                ).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
                expected_principal=rule.principal_id,
            )
            if (
                session.agent_id != rule.agent_id
                or session.state is not AgentSessionState.RETIRING
            ):
                raise QueueServiceError("agent session is not retiring")
            _require_matching_retirement_proof(session, proof)
            _verify_retirement_secret(conn, session.session_id, proof.retirement_secret)
            if not _coordinator_references_empty(conn, proof.session_id):
                conn.commit()
                raise QueueConflictError("agent session has unresolved references")
            conn.execute(
                "INSERT INTO agent_retirement_proofs(session_id, proof_json) "
                "VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE "
                "SET proof_json = excluded.proof_json",
                (proof.session_id, _canonical_json(proof.redacted_value())),
            )
            conn.execute(
                "UPDATE agent_sessions SET state = ? WHERE session_id = ?",
                (AgentSessionState.RETIRED_CLEAN.value, proof.session_id),
            )
            conn.execute(
                "INSERT INTO agent_session_tombstones(session_id, state) "
                "VALUES (?, ?) ON CONFLICT(session_id) DO NOTHING",
                (proof.session_id, AgentSessionState.RETIRED_CLEAN.value),
            )
            value: dict[str, PlainData] = {
                "session_id": proof.session_id,
                "state": AgentSessionState.RETIRED_CLEAN.value,
            }
            _write_receipt(
                conn,
                rule.principal_id,
                "retire",
                idempotency_key,
                digest,
                value,
            )
            conn.commit()
        return freeze_plain_data(value, path="agent retirement")

    def _check_current_session(
        self,
        session: AgentSession,
        rule: AgentPrincipalPolicy,
        epoch: str,
        policy_revision: str,
    ) -> None:
        if (
            session.agent_id != rule.agent_id
            or session.state is not AgentSessionState.ACTIVE
        ):
            raise QueueServiceError("agent session is not authorized")
        if session.policy_revision != policy_revision:
            raise QueueServiceError("agent credential policy is no longer current")
        if epoch != self._daemon._epoch:  # type: ignore[attr-defined]
            raise QueueConflictError("coordinator epoch is stale")

    def _check_retirable_session(
        self,
        session: AgentSession,
        rule: AgentPrincipalPolicy,
        epoch: str,
        policy_revision: str,
    ) -> None:
        if session.agent_id != rule.agent_id or session.state not in {
            AgentSessionState.ACTIVE,
            AgentSessionState.RETIRING,
        }:
            raise QueueServiceError("agent session is not authorized")
        if session.state is AgentSessionState.ACTIVE:
            if session.policy_revision != policy_revision:
                raise QueueServiceError("agent credential policy is no longer current")
            if epoch != self._daemon._epoch:  # type: ignore[attr-defined]
                raise QueueConflictError("coordinator epoch is stale")

    def _require_current_offer(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        availability_revision: str,
    ) -> None:
        offer = conn.execute(
            "SELECT expires_at FROM agent_offers WHERE session_id = ? "
            "AND coordinator_epoch = ? AND availability_revision = ? AND current = 1",
            (session_id, self._daemon._epoch, availability_revision),  # type: ignore[attr-defined]
        ).fetchone()
        if offer is None or str(offer["expires_at"]) < self._daemon._accepted_time(
            conn
        ):  # type: ignore[attr-defined]
            raise QueueConflictError("work poll requires a current offer")


def replace_agent_session(
    daemon: "LocalDaemon",
    principal: "LocalDaemonPrincipal",
    request: SessionReplacementRequest,
) -> Mapping[str, PlainData]:
    """Durably decide a guarded replacement from complete coordinator facts.

    This is intentionally a coordinator operation, rather than an agent RPC:
    possession of an agent credential or an empty new journal is not evidence
    that the previous session stopped.  The later ordinary registration is the
    only place that allocates the successor identity.
    """

    ScopedAuthorizer(daemon._agent_policy).require_operator(  # type: ignore[attr-defined]
        principal, "replace_session", agent_id=request.agent_id
    )
    encoded = _canonical_json(request.to_dict())
    digest = _digest(request.to_dict())
    execution = daemon._execution  # type: ignore[attr-defined]
    if execution is None:
        raise QueueServiceError("replacement coordinator execution is unavailable")
    with daemon._connection() as conn:  # type: ignore[attr-defined]
        prior = conn.execute(
            "SELECT principal_id, request_json, request_digest, result_json "
            "FROM session_replacements WHERE operation_id = ?",
            (request.operation_id,),
        ).fetchone()
        if prior is not None:
            return _replacement_replay(
                prior,
                principal_id=principal.subject,
                request_json=encoded,
                request_digest=digest,
            )
        old = conn.execute(
            "SELECT * FROM agent_sessions WHERE agent_id = ? AND state = ?",
            (request.agent_id, AgentSessionState.ACTIVE.value),
        ).fetchone()
        if old is None:
            raise QueueConflictError("agent has no current session to replace")
        old_session = _session_from_row(
            old,
            daemon._require_started(),  # type: ignore[attr-defined]
            expected_principal=str(old["principal_id"]),
        )
    execution_facts = execution.session_replacement_assignment_facts(
        old_session.session_id
    )
    with daemon._connection() as conn:  # type: ignore[attr-defined]
        candidate = _build_replacement_projection(
            conn,
            session=old_session,
            execution_facts=execution_facts,
            observed_at=daemon._clock(),  # type: ignore[attr-defined]
        )
    authority_facts = _replacement_authority_facts(daemon, candidate)
    current_execution_facts = execution.session_replacement_assignment_facts(
        old_session.session_id
    )
    with daemon._connection() as conn:  # type: ignore[attr-defined]
        conn.execute("BEGIN IMMEDIATE")
        raced = conn.execute(
            "SELECT principal_id, request_json, request_digest, result_json "
            "FROM session_replacements WHERE operation_id = ?",
            (request.operation_id,),
        ).fetchone()
        if raced is not None:
            result = _replacement_replay(
                raced,
                principal_id=principal.subject,
                request_json=encoded,
                request_digest=digest,
            )
            conn.commit()
            return result
        current = conn.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ?",
            (old_session.session_id,),
        ).fetchone()
        current_session = _session_from_row(
            current,
            daemon._require_started(),  # type: ignore[attr-defined]
            expected_principal=str(old["principal_id"]),
        )
        if current_session != old_session:
            raise QueueConflictError("old session changed before replacement fence")
        conn.execute(
            "UPDATE agent_controls SET state = 'superseded', "
            "result_code = 'session_replaced' WHERE session_id = ? "
            "AND state IN ('pending_delivery','applying')",
            (old_session.session_id,),
        )
        projection = _build_replacement_projection(
            conn,
            session=old_session,
            execution_facts=current_execution_facts,
            observed_at=daemon._clock(),  # type: ignore[attr-defined]
        )
        _require_monotonic_replacement_projection(candidate.value, projection.value)
        durable_projection = _bind_replacement_authority_facts(
            projection, authority_facts
        )
        conn.execute(
            "UPDATE agent_offers SET current = 0 WHERE session_id = ?",
            (old_session.session_id,),
        )
        conn.execute(
            "UPDATE agent_poll_state SET active = 0 WHERE session_id = ?",
            (old_session.session_id,),
        )
        updated = conn.execute(
            "UPDATE agent_sessions SET state = ? WHERE session_id = ? AND state = ?",
            (
                AgentSessionState.REPLACED.value,
                old_session.session_id,
                AgentSessionState.ACTIVE.value,
            ),
        ).rowcount
        if updated != 1:
            raise QueueConflictError("old session changed before replacement fence")
        conn.execute(
            "INSERT INTO agent_session_tombstones(session_id, state) VALUES (?, ?)",
            (old_session.session_id, AgentSessionState.REPLACED.value),
        )
        decided_at = daemon._accepted_time(conn)  # type: ignore[attr-defined]
        result = _replacement_result(
            request=request,
            old_session_id=old_session.session_id,
            successor_session_id=None,
            state="decision",
            readiness="withheld",
            withholding_reason="successor_registration_required",
            projection=durable_projection,
        )
        projection_json = _canonical_json(durable_projection)
        conn.execute(
            "INSERT INTO session_replacements("
            "operation_id, principal_id, request_json, request_digest, agent_id, "
            "old_session_id, successor_session_id, state, readiness, "
            "withholding_reason, decision_projection_json, "
            "decision_projection_digest, required_claim_ids_json, "
            "observed_claim_ids_json, successor_observation_digest, "
            "readiness_projection_digest, result_json, decided_at, ready_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, 'decision', 'withheld', ?, ?, ?, "
            "?, '[]', NULL, NULL, ?, ?, NULL)",
            (
                request.operation_id,
                principal.subject,
                encoded,
                digest,
                request.agent_id,
                old_session.session_id,
                "successor_registration_required",
                projection_json,
                hashlib.sha256(projection_json.encode("utf-8")).hexdigest(),
                json.dumps(projection.required_claim_ids, separators=(",", ":")),
                _canonical_json(result),
                decided_at,
            ),
        )
        conn.commit()
    return freeze_plain_data(result, path="session replacement receipt")


def _replacement_replay(
    row: sqlite3.Row,
    *,
    principal_id: str,
    request_json: str,
    request_digest: str,
) -> Mapping[str, PlainData]:
    if (
        str(row["principal_id"]) != principal_id
        or str(row["request_json"]) != request_json
        or str(row["request_digest"]) != request_digest
    ):
        raise QueueConflictError("session replacement operation conflicts")
    try:
        result = json.loads(str(row["result_json"]))
    except json.JSONDecodeError as exc:
        raise QueueStorageError("session replacement result is invalid") from exc
    if not isinstance(result, Mapping):
        raise QueueStorageError("session replacement result is invalid")
    return freeze_plain_data(result, path="session replacement receipt")


def _build_replacement_projection(
    conn: sqlite3.Connection,
    *,
    session: AgentSession,
    execution_facts: Sequence[Mapping[str, PlainData]],
    observed_at: str,
) -> _ReplacementProjection:
    """Join every supported old-session owner or fail closed."""

    from .local_daemon import ManagedRecoveryTarget, RecoverUnknownAssignment

    execution_by_id: dict[str, Mapping[str, PlainData]] = {}
    for fact in execution_facts:
        assignment_id = _projection_string(fact, "assignment_id")
        if assignment_id in execution_by_id:
            raise QueueConflictError("old session coordinator inventory conflicts")
        if (
            _projection_string(fact, "agent_id") != session.agent_id
            or _projection_string(fact, "session_id") != session.session_id
        ):
            raise QueueConflictError("old session coordinator inventory conflicts")
        execution_by_id[assignment_id] = fact
    remote_rows = tuple(
        conn.execute(
            "SELECT * FROM remote_assignments WHERE session_id = ? "
            "ORDER BY assignment_id",
            (session.session_id,),
        )
    )
    remote_by_id = {str(row["assignment_id"]): row for row in remote_rows}
    if not set(remote_by_id).issubset(execution_by_id):
        raise QueueConflictError("old session coordinator inventory is incomplete")
    deliveries = {
        str(row["assignment_id"]): row
        for row in conn.execute(
            "SELECT assignment_id, session_id, availability_revision, "
            "coordinator_epoch, state, poll_sequence FROM agent_deliveries "
            "WHERE session_id = ? ORDER BY assignment_id",
            (session.session_id,),
        )
    }
    if set(deliveries) != set(remote_by_id):
        raise QueueConflictError("old session delivery inventory is incomplete")
    reference_rows = tuple(
        conn.execute(
            "SELECT reference_kind, reference_id, resolved "
            "FROM agent_coordinator_references WHERE session_id = ? "
            "ORDER BY reference_kind, reference_id",
            (session.session_id,),
        )
    )
    references = {
        str(row["reference_id"]): row
        for row in reference_rows
        if str(row["reference_kind"]) == "delivery"
    }
    if len(references) != len(reference_rows) or set(references) != set(remote_by_id):
        raise QueueConflictError("old session reference inventory is incomplete")
    coverage_rows = tuple(
        conn.execute(
            "SELECT assignment_id, reference_class "
            "FROM agent_replacement_coverage WHERE session_id = ? "
            "ORDER BY assignment_id, reference_class",
            (session.session_id,),
        )
    )
    expected_coverage = {
        (assignment_id, reference_class)
        for assignment_id in remote_by_id
        for reference_class in _REPLACEMENT_ASSIGNMENT_REFERENCE_CLASSES
    }
    actual_coverage = {
        (str(row["assignment_id"]), str(row["reference_class"]))
        for row in coverage_rows
    }
    if actual_coverage != expected_coverage:
        raise QueueConflictError("old session agent-owner coverage is incomplete")
    assignment_controls = {
        str(row["assignment_id"]): row
        for row in conn.execute(
            "SELECT * FROM remote_assignment_controls WHERE session_id = ? "
            "ORDER BY assignment_id",
            (session.session_id,),
        )
    }
    if not set(assignment_controls).issubset(remote_by_id):
        raise QueueConflictError("old session assignment-control parent is missing")
    recovery_rows: list[tuple[sqlite3.Row, RecoverUnknownAssignment]] = []
    for row in conn.execute(
        "SELECT recovery_id, request_json, request_digest, state, evidence_json, "
        "result_json FROM recovery_operations ORDER BY recovery_id"
    ):
        try:
            decoded = json.loads(str(row["request_json"]))
            if not isinstance(decoded, Mapping):
                raise QueueServiceError("recovery request is invalid")
            recovery = RecoverUnknownAssignment.from_dict(decoded)
        except (json.JSONDecodeError, QueueServiceError) as exc:
            raise QueueConflictError(
                "old session recovery inventory is unavailable"
            ) from exc
        target = recovery.target
        if (
            isinstance(target, ManagedRecoveryTarget)
            and target.session_id == session.session_id
        ):
            if target.agent_id != session.agent_id:
                raise QueueConflictError(
                    "old session recovery target identity conflicts"
                )
            recovery_rows.append((row, recovery))
    recovery_by_assignment: dict[
        str, list[tuple[sqlite3.Row, RecoverUnknownAssignment]]
    ] = {}
    for row, recovery in recovery_rows:
        recovery_by_assignment.setdefault(recovery.assignment_id, []).append(
            (row, recovery)
        )
    if not set(recovery_by_assignment).issubset(remote_by_id):
        raise QueueConflictError("old session recovery parent is missing")

    assignments: list[PlainData] = []
    required_claim_ids: list[str] = []
    recovery_requests: list[Mapping[str, object]] = []
    transfer_count = 0
    authorization_count = 0
    released_count = 0
    contained_count = 0
    for assignment_id, execution in sorted(execution_by_id.items()):
        remote = remote_by_id.get(assignment_id)
        coordinator_state = _projection_string(execution, "state")
        immutable: dict[str, PlainData] = {
            name: cast(PlainData, execution[name])
            for name in (
                "assignment_id",
                "run_uri",
                "stage_work_id",
                "stage_name",
                "attempt",
                "attempt_id",
                "agent_id",
                "session_id",
                "offer_id",
                "claim_id",
                "receipt_digest",
                "atom_count",
                "atoms_digest",
                "event_count",
                "events_digest",
            )
        }
        if remote is None:
            if coordinator_state != "released":
                raise QueueConflictError(
                    "old session assignment target inventory is incomplete"
                )
            assignments.append(
                {
                    **immutable,
                    "coordinator_state": coordinator_state,
                    "remote_state": None,
                    "classification": "released",
                    "release_kind": "before_delivery",
                    "delivery_state": None,
                    "reference_resolved": True,
                    "transfer_count": 0,
                    "authorization_count": 0,
                    "assignment_control_state": None,
                    "assignment_control_code": None,
                    "recovery_id": None,
                    "recovery_request_digest": None,
                    "recovery_revision": None,
                }
            )
            released_count += 1
            continue
        if (
            str(remote["run_uri"]) != immutable["run_uri"]
            or str(remote["stage_work_id"]) != immutable["stage_work_id"]
            or str(remote["stage_name"]) != immutable["stage_name"]
            or int(remote["attempt"]) != immutable["attempt"]
            or str(remote["attempt_id"]) != immutable["attempt_id"]
        ):
            raise QueueConflictError("old session assignment identity conflicts")
        delivery = deliveries[assignment_id]
        reference = references[assignment_id]
        if (
            str(delivery["session_id"]) != session.session_id
            or str(delivery["availability_revision"])
            != str(remote["availability_revision"])
            or str(delivery["coordinator_epoch"]) != str(remote["issuer_epoch"])
        ):
            raise QueueConflictError("old session delivery identity conflicts")
        transfers = tuple(
            conn.execute(
                "SELECT direction, transfer_id, size_bytes, received_bytes, "
                "finalized, descriptor_json FROM remote_transfers "
                "WHERE assignment_id = ? ORDER BY direction, transfer_id",
                (assignment_id,),
            )
        )
        if any(
            int(row["size_bytes"]) < 0
            or int(row["received_bytes"]) < 0
            or int(row["received_bytes"]) > int(row["size_bytes"])
            or (bool(row["finalized"]) and row["descriptor_json"] is None)
            for row in transfers
        ):
            raise QueueConflictError("old session transfer inventory conflicts")
        authorizations = tuple(
            conn.execute(
                "SELECT authorization_id, revision, operation_id, expires_at "
                "FROM remote_transfer_authorizations WHERE assignment_id = ? "
                "ORDER BY revision",
                (assignment_id,),
            )
        )
        transfer_count += len(transfers)
        authorization_count += len(authorizations)
        control_row = assignment_controls.get(assignment_id)
        control = (
            None
            if control_row is None
            else AgentAssignmentControl.from_value(
                json.loads(str(control_row["request_json"]))
            )
        )
        if control is not None and (
            control.session_id != session.session_id
            or control.assignment_id != assignment_id
        ):
            raise QueueConflictError(
                "old session assignment-control identity conflicts"
            )
        fully_released = (
            coordinator_state == "released"
            and str(remote["state"]) == "RELEASED"
            and bool(reference["resolved"])
            and all(bool(row["finalized"]) for row in transfers)
            and (
                control_row is None
                or (
                    bool(control_row["acknowledged"])
                    and str(control_row["state"])
                    not in {"pending_delivery", "applying", "settling"}
                )
            )
        )
        recovery_id: str | None = None
        recovery_digest: str | None = None
        recovery_revision: int | None = None
        if fully_released:
            classification = "released"
            released_count += 1
        else:
            matches = recovery_by_assignment.get(assignment_id, [])
            qualifying = [
                _qualifying_replacement_recovery(
                    row,
                    recovery,
                    session=session,
                    execution=execution,
                    remote=remote,
                    control_row=control_row,
                    control=control,
                )
                for row, recovery in matches
                if str(row["state"]) == "closed"
            ]
            qualifying = [item for item in qualifying if item is not None]
            if len(qualifying) != 1 or any(
                str(row["state"]) in {"pending", "evidence_confirmed"}
                for row, _recovery in matches
            ):
                raise QueueConflictError(
                    "old session assignment is neither released nor contained"
                )
            recovery, result = qualifying[0]
            classification = "contained"
            recovery_id = recovery.recovery_id
            recovery_digest = _digest(recovery.to_dict())
            recovery_revision = cast(int, result["revision"])
            required_claim_ids.append(_projection_string(execution, "claim_id"))
            recovery_requests.append(recovery.to_dict())
            contained_count += 1
        assignments.append(
            {
                **immutable,
                "coordinator_state": coordinator_state,
                "remote_state": str(remote["state"]),
                "classification": classification,
                "release_kind": "delivered" if fully_released else None,
                "delivery_state": str(delivery["state"]),
                "reference_resolved": bool(reference["resolved"]),
                "transfer_count": len(transfers),
                "authorization_count": len(authorizations),
                "assignment_control_state": (
                    None if control_row is None else str(control_row["state"])
                ),
                "assignment_control_code": (
                    None
                    if control_row is None or control_row["result_code"] is None
                    else str(control_row["result_code"])
                ),
                "recovery_id": recovery_id,
                "recovery_request_digest": recovery_digest,
                "recovery_revision": recovery_revision,
            }
        )
    if len(set(required_claim_ids)) != len(required_claim_ids):
        raise QueueConflictError("old session retained claim identity conflicts")
    current_offer = conn.execute(
        "SELECT expires_at FROM agent_offers WHERE session_id = ? AND current = 1",
        (session.session_id,),
    ).fetchone()
    available = (
        current_offer is not None and str(current_offer["expires_at"]) >= observed_at
    )
    if not assignments and available:
        raise QueueConflictError(
            "empty active session must use ordinary clean retirement"
        )
    controls = tuple(
        conn.execute(
            "SELECT operation_id, state, result_code, acknowledged "
            "FROM agent_controls WHERE session_id = ? ORDER BY operation_id",
            (session.session_id,),
        )
    )
    control_values: list[PlainData] = [
        {
            "operation_id": str(row["operation_id"]),
            "state": str(row["state"]),
            "code": (None if row["result_code"] is None else str(row["result_code"])),
            "acknowledged": bool(row["acknowledged"]),
        }
        for row in controls
    ]
    value: dict[str, PlainData] = {
        "projection_version": 1,
        "session": {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "agent_root_id": session.agent_root_id,
            "policy_revision": session.policy_revision,
            "config_revision": session.config_revision,
            "inventory_revision": session.inventory_revision,
            "coordinator_epoch": session.coordinator_epoch,
        },
        "assignments": assignments,
        "owner_counts": {
            "assignments": len(assignments),
            "released": released_count,
            "contained": contained_count,
            "deliveries": len(deliveries),
            "references": len(reference_rows),
            "coverage_tokens": len(coverage_rows),
            "transfers": transfer_count,
            "transfer_authorizations": authorization_count,
            "controls": len(controls),
            "assignment_controls": len(assignment_controls),
            "offers": int(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_offers WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()[0]
            ),
            "polls": int(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_poll_state WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()[0]
            ),
        },
        "controls": control_values,
    }
    return _ReplacementProjection(
        value=freeze_plain_data(value, path="session replacement projection"),
        required_claim_ids=tuple(sorted(required_claim_ids)),
        recovery_requests=tuple(recovery_requests),
    )


def _qualifying_replacement_recovery(
    row: sqlite3.Row,
    recovery: "RecoverUnknownAssignment",
    *,
    session: AgentSession,
    execution: Mapping[str, PlainData],
    remote: sqlite3.Row,
    control_row: sqlite3.Row | None,
    control: AgentAssignmentControl | None,
) -> tuple["RecoverUnknownAssignment", Mapping[str, object]] | None:
    from .local_daemon import RecoverUnknownAssignment

    if not isinstance(recovery, RecoverUnknownAssignment):
        return None
    target = recovery.target
    if (
        recovery.assignment_id != remote["assignment_id"]
        or recovery.run_uri != remote["run_uri"]
        or recovery.stage_work_id != remote["stage_work_id"]
        or recovery.stage_name != remote["stage_name"]
        or recovery.attempt != remote["attempt"]
        or target.agent_id != session.agent_id  # type: ignore[union-attr]
        or target.session_id != session.session_id  # type: ignore[union-attr]
        or recovery.execution_fence != remote["fence"]
        or control_row is None
        or control is None
        or control.fence != recovery.execution_fence
        or control.process_execution_id != recovery.process_execution_id
        or not bool(control_row["acknowledged"])
        or str(control_row["result_code"]) != "contained"
    ):
        return None
    try:
        evidence = json.loads(str(row["evidence_json"]))
        result = json.loads(str(row["result_json"]))
        control_evidence = json.loads(str(control_row["evidence_json"]))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(evidence, Mapping) or not isinstance(result, Mapping):
        return None
    try:
        managed = _managed_containment_evidence(evidence)
    except QueueServiceError:
        return None
    if (
        managed.get("agent_id") != session.agent_id
        or managed.get("session_id") != session.session_id
        or managed.get("assignment_id") != remote["assignment_id"]
        or managed.get("process_execution_id") != recovery.process_execution_id
        or managed.get("execution_fence") != recovery.execution_fence
        or control_evidence != evidence
        or result.get("recovery_id") != recovery.recovery_id
        or result.get("state") != "closed"
        or result.get("evidence") != evidence
        or result.get("physical_ownership") != "retained"
        or isinstance(result.get("revision"), bool)
        or not isinstance(result.get("revision"), int)
        or _projection_string(execution, "claim_id") == ""
    ):
        return None
    return recovery, result


def _replacement_offer_admission(
    daemon: "LocalDaemon", successor_session_id: str
) -> _ReplacementOfferAdmission | None:
    execution = daemon._execution  # type: ignore[attr-defined]
    if execution is None:
        raise QueueServiceError("replacement coordinator execution is unavailable")
    with daemon._connection() as conn:  # type: ignore[attr-defined]
        row = conn.execute(
            "SELECT r.*, s.principal_id AS old_principal_id "
            "FROM session_replacements r JOIN agent_sessions s "
            "ON s.session_id = r.old_session_id "
            "WHERE r.successor_session_id = ?",
            (successor_session_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["state"]) not in {"bound", "ready"} or str(row["readiness"]) not in {
            "withheld",
            "ready",
        }:
            raise QueueConflictError("replacement readiness state is invalid")
        old_row = conn.execute(
            "SELECT * FROM agent_sessions WHERE session_id = ? AND state = ?",
            (str(row["old_session_id"]), AgentSessionState.REPLACED.value),
        ).fetchone()
        if old_row is None:
            raise QueueConflictError("replacement old-session fence is unavailable")
        tombstone = conn.execute(
            "SELECT state FROM agent_session_tombstones WHERE session_id = ?",
            (str(row["old_session_id"]),),
        ).fetchone()
        if (
            tombstone is None
            or str(tombstone["state"]) != AgentSessionState.REPLACED.value
        ):
            raise QueueConflictError("replacement old-session tombstone is unavailable")
        old_session = _session_from_row(
            old_row,
            daemon._require_started(),  # type: ignore[attr-defined]
            expected_principal=str(row["old_principal_id"]),
        )
        try:
            request_value = json.loads(str(row["request_json"]))
            decision_value = json.loads(str(row["decision_projection_json"]))
            required_value = json.loads(str(row["required_claim_ids_json"]))
        except json.JSONDecodeError as exc:
            raise QueueStorageError("session replacement decision is invalid") from exc
        if not isinstance(request_value, Mapping) or not isinstance(
            decision_value, Mapping
        ):
            raise QueueStorageError("session replacement decision is invalid")
        request = SessionReplacementRequest.from_dict(request_value)
        decision = freeze_plain_data(
            decision_value, path="session replacement decision"
        )
        if not isinstance(decision, Mapping):
            raise QueueStorageError("session replacement decision is invalid")
        encoded_decision = _canonical_json(cast(Mapping[str, PlainData], decision))
        if hashlib.sha256(encoded_decision.encode("utf-8")).hexdigest() != str(
            row["decision_projection_digest"]
        ):
            raise QueueStorageError("session replacement decision digest conflicts")
        if (
            not isinstance(required_value, list)
            or any(not isinstance(item, str) for item in required_value)
            or len(set(required_value)) != len(required_value)
        ):
            raise QueueStorageError("session replacement claim inventory is invalid")
    execution_facts = execution.session_replacement_assignment_facts(
        old_session.session_id
    )
    with daemon._connection() as conn:  # type: ignore[attr-defined]
        projection = _build_replacement_projection(
            conn,
            session=old_session,
            execution_facts=execution_facts,
            observed_at=daemon._clock(),  # type: ignore[attr-defined]
        )
    _require_monotonic_replacement_projection(
        cast(Mapping[str, PlainData], decision), projection.value
    )
    decision_required = sorted(
        _projection_string(cast(Mapping[str, PlainData], item), "claim_id")
        for item in cast(Sequence[object], decision.get("assignments", ()))
        if isinstance(item, Mapping) and item.get("classification") == "contained"
    )
    if decision_required != sorted(cast(list[str], required_value)):
        raise QueueStorageError("session replacement claim inventory conflicts")
    authority_facts = _replacement_authority_facts(daemon, projection)
    durable_projection = _bind_replacement_authority_facts(projection, authority_facts)
    return _ReplacementOfferAdmission(
        operation_id=str(row["operation_id"]),
        request=request,
        old_session_id=old_session.session_id,
        prior_readiness=str(row["readiness"]),
        decision_projection_digest=str(row["decision_projection_digest"]),
        projection=projection,
        durable_projection=durable_projection,
    )


def _replacement_cleanup_recovery(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    assignment_id: str,
    fence: str,
) -> tuple["RecoverUnknownAssignment", str]:
    """Return the one durable recovery that permits exact late release."""

    from .local_daemon import ManagedRecoveryTarget, RecoverUnknownAssignment

    replacement = conn.execute(
        "SELECT decision_projection_json FROM session_replacements "
        "WHERE old_session_id = ?",
        (session_id,),
    ).fetchone()
    if replacement is None:
        raise QueueConflictError("replacement cleanup decision is unavailable")
    try:
        projection = json.loads(str(replacement["decision_projection_json"]))
    except json.JSONDecodeError as exc:
        raise QueueStorageError("session replacement decision is invalid") from exc
    if not isinstance(projection, Mapping) or not isinstance(
        projection.get("assignments"), list
    ):
        raise QueueStorageError("session replacement decision is invalid")
    matches = [
        item
        for item in projection["assignments"]
        if isinstance(item, Mapping) and item.get("assignment_id") == assignment_id
    ]
    if (
        len(matches) != 1
        or matches[0].get("classification") != "contained"
        or not isinstance(matches[0].get("recovery_id"), str)
        or not isinstance(matches[0].get("claim_id"), str)
    ):
        raise QueueConflictError("replacement cleanup is not containment-covered")
    recovery_id = cast(str, matches[0]["recovery_id"])
    row = conn.execute(
        "SELECT request_json, state, evidence_json, result_json "
        "FROM recovery_operations WHERE recovery_id = ?",
        (recovery_id,),
    ).fetchone()
    if row is None or str(row["state"]) != "closed" or row["evidence_json"] is None:
        raise QueueConflictError("replacement cleanup recovery is unavailable")
    try:
        value = json.loads(str(row["request_json"]))
        if not isinstance(value, Mapping):
            raise QueueServiceError("recovery request is invalid")
        recovery = RecoverUnknownAssignment.from_dict(value)
    except (json.JSONDecodeError, QueueServiceError) as exc:
        raise QueueStorageError("replacement cleanup recovery is invalid") from exc
    target = recovery.target
    if (
        not isinstance(target, ManagedRecoveryTarget)
        or target.session_id != session_id
        or recovery.assignment_id != assignment_id
        or recovery.execution_fence != fence
    ):
        raise QueueConflictError("replacement cleanup recovery identity conflicts")
    return recovery, cast(str, matches[0]["claim_id"])


def _replacement_authority_facts(
    daemon: "LocalDaemon", projection: _ReplacementProjection
) -> Mapping[str, Mapping[str, PlainData]]:
    from .local_daemon import RecoverUnknownAssignment

    execution = daemon._execution  # type: ignore[attr-defined]
    if execution is None:
        raise QueueServiceError("replacement coordinator execution is unavailable")
    facts: dict[str, Mapping[str, PlainData]] = {}
    for raw in projection.recovery_requests:
        recovery = RecoverUnknownAssignment.from_dict(raw)
        fact = execution.validate_session_replacement_recovery(recovery)
        if recovery.recovery_id in facts:
            raise QueueConflictError("replacement recovery inventory conflicts")
        facts[recovery.recovery_id] = fact
    return facts


def _bind_replacement_authority_facts(
    projection: _ReplacementProjection,
    authority_facts: Mapping[str, Mapping[str, PlainData]],
) -> Mapping[str, PlainData]:
    value = thaw_plain_data(projection.value, path="session replacement projection")
    if not isinstance(value, dict):
        raise QueueStorageError("session replacement projection is invalid")
    assignments = value.get("assignments")
    if not isinstance(assignments, list):
        raise QueueStorageError("session replacement projection is invalid")
    used: set[str] = set()
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise QueueStorageError("session replacement projection is invalid")
        recovery_id = assignment.get("recovery_id")
        if recovery_id is None:
            continue
        if not isinstance(recovery_id, str):
            raise QueueStorageError("session replacement projection is invalid")
        fact = authority_facts.get(recovery_id)
        if (
            fact is None
            or fact.get("assignment_id") != assignment.get("assignment_id")
            or fact.get("authority_revision") != assignment.get("recovery_revision")
        ):
            raise QueueConflictError("replacement authority close conflicts")
        assignment["authority_revision"] = fact["authority_revision"]
        assignment["authority_status"] = fact["status"]
        used.add(recovery_id)
    if used != set(authority_facts):
        raise QueueConflictError("replacement authority inventory changed")
    return freeze_plain_data(value, path="session replacement projection")


def _require_monotonic_replacement_projection(
    previous: Mapping[str, PlainData], current: Mapping[str, PlainData]
) -> None:
    previous_session = previous.get("session")
    current_session = current.get("session")
    if previous_session != current_session:
        raise QueueConflictError("old session identity changed during replacement")
    prior_rows = previous.get("assignments")
    current_rows = current.get("assignments")
    if not isinstance(prior_rows, Sequence) or not isinstance(current_rows, Sequence):
        raise QueueStorageError("session replacement projection is invalid")
    prior = {
        _projection_string(cast(Mapping[str, PlainData], row), "assignment_id"): cast(
            Mapping[str, PlainData], row
        )
        for row in prior_rows
        if isinstance(row, Mapping)
    }
    now = {
        _projection_string(cast(Mapping[str, PlainData], row), "assignment_id"): cast(
            Mapping[str, PlainData], row
        )
        for row in current_rows
        if isinstance(row, Mapping)
    }
    if (
        len(prior) != len(prior_rows)
        or len(now) != len(current_rows)
        or set(prior) != set(now)
    ):
        raise QueueConflictError("old session assignment inventory changed")
    immutable = {
        "assignment_id",
        "run_uri",
        "stage_work_id",
        "stage_name",
        "attempt",
        "attempt_id",
        "agent_id",
        "session_id",
        "offer_id",
        "claim_id",
        "receipt_digest",
        "atom_count",
        "atoms_digest",
        "event_count",
        "events_digest",
    }
    for assignment_id, before in prior.items():
        after = now[assignment_id]
        if any(before.get(name) != after.get(name) for name in immutable):
            raise QueueConflictError("old session assignment identity changed")
        before_class = before.get("classification")
        after_class = after.get("classification")
        if before_class == "released":
            if after_class != "released":
                raise QueueConflictError("old session release state regressed")
        elif before_class == "contained":
            if after_class not in {"contained", "released"}:
                raise QueueConflictError("old session containment state regressed")
            if after_class == "contained" and any(
                before.get(name) != after.get(name)
                for name in ("recovery_id", "recovery_request_digest")
            ):
                raise QueueConflictError("old session containment identity changed")
        else:
            raise QueueStorageError("session replacement classification is invalid")


def _replacement_result(
    *,
    request: SessionReplacementRequest,
    old_session_id: str,
    successor_session_id: str | None,
    state: str,
    readiness: str,
    withholding_reason: str | None,
    projection: Mapping[str, PlainData],
) -> dict[str, PlainData]:
    counts = projection.get("owner_counts")
    if not isinstance(counts, Mapping):
        raise QueueStorageError("session replacement projection is invalid")
    frozen_counts = freeze_plain_data(counts, path="session replacement owner counts")
    if not isinstance(frozen_counts, Mapping):
        raise QueueStorageError("session replacement projection is invalid")
    return {
        "operation_id": request.operation_id,
        "agent_id": request.agent_id,
        "old_session_id": old_session_id,
        "successor_session_id": successor_session_id,
        "state": state,
        "readiness": readiness,
        "withholding_reason": withholding_reason,
        "owner_counts": dict(frozen_counts),
    }


def _replacement_cleanup_result(value: object) -> dict[str, PlainData]:
    """Advance only the current bounded counts after one exact late cleanup."""

    try:
        result = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise QueueStorageError("session replacement result is invalid") from exc
    if not isinstance(result, dict) or not isinstance(result.get("owner_counts"), dict):
        raise QueueStorageError("session replacement result is invalid")
    counts = cast(dict[str, object], result["owner_counts"])
    contained = counts.get("contained")
    released = counts.get("released")
    if (
        isinstance(contained, bool)
        or not isinstance(contained, int)
        or contained < 1
        or isinstance(released, bool)
        or not isinstance(released, int)
        or released < 0
    ):
        raise QueueStorageError("session replacement result is invalid")
    counts["contained"] = contained - 1
    counts["released"] = released + 1
    frozen = freeze_plain_data(result, path="session replacement cleanup result")
    if not isinstance(frozen, Mapping):
        raise QueueStorageError("session replacement result is invalid")
    return dict(frozen)


def _projection_string(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise QueueConflictError("replacement inventory identity is invalid")
    return item


def initialize_agent_session_schema(
    conn: sqlite3.Connection, *, coordinator: bool
) -> None:
    """Create the current hard-cut session protocol tables in a fresh root."""
    if coordinator:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_sessions (session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, agent_root_id TEXT NOT NULL, principal_id TEXT NOT NULL, policy_revision TEXT NOT NULL, config_revision TEXT NOT NULL, inventory_revision TEXT NOT NULL, availability_revision TEXT NOT NULL, capabilities_json TEXT NOT NULL, pools_json TEXT NOT NULL, retirement_verifier TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS agent_one_open_session ON agent_sessions(agent_id) WHERE state NOT IN ('RETIRED_CLEAN','REPLACED');
        CREATE TABLE IF NOT EXISTS agent_receipts (principal_id TEXT NOT NULL, operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, digest TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(principal_id, operation, idempotency_key));
        CREATE TABLE IF NOT EXISTS agent_offers (offer_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, availability_revision TEXT NOT NULL, offer_json TEXT NOT NULL, accepted_at TEXT NOT NULL, expires_at TEXT NOT NULL, current INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_poll_state (principal_id TEXT NOT NULL, session_id TEXT NOT NULL, sequence INTEGER NOT NULL, availability_revision TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, wait_timeout_ms INTEGER NOT NULL, digest TEXT NOT NULL, active INTEGER NOT NULL, result_json TEXT, PRIMARY KEY(principal_id, session_id));
        CREATE TABLE IF NOT EXISTS agent_coordinator_references (session_id TEXT NOT NULL, reference_kind TEXT NOT NULL, reference_id TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id, reference_kind, reference_id));
        CREATE TABLE IF NOT EXISTS agent_retirement_proofs (session_id TEXT PRIMARY KEY, proof_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_session_tombstones (session_id TEXT PRIMARY KEY, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS session_replacements (operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, request_json TEXT NOT NULL, request_digest TEXT NOT NULL, agent_id TEXT NOT NULL, old_session_id TEXT NOT NULL UNIQUE, successor_session_id TEXT UNIQUE, state TEXT NOT NULL, readiness TEXT NOT NULL, withholding_reason TEXT, decision_projection_json TEXT NOT NULL, decision_projection_digest TEXT NOT NULL, required_claim_ids_json TEXT NOT NULL, observed_claim_ids_json TEXT NOT NULL, successor_observation_digest TEXT, readiness_projection_digest TEXT, result_json TEXT NOT NULL, decided_at TEXT NOT NULL, ready_at TEXT);
        CREATE TABLE IF NOT EXISTS agent_replacement_coverage (session_id TEXT NOT NULL, assignment_id TEXT NOT NULL, reference_class TEXT NOT NULL, PRIMARY KEY(session_id, assignment_id, reference_class));
        CREATE TABLE IF NOT EXISTS agent_deliveries (assignment_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, availability_revision TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, request_json TEXT NOT NULL, state TEXT NOT NULL, poll_sequence INTEGER);
        CREATE TABLE IF NOT EXISTS remote_assignments (assignment_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, availability_revision TEXT NOT NULL, issuer_epoch TEXT NOT NULL, run_uri TEXT NOT NULL, stage_work_id TEXT NOT NULL, stage_name TEXT NOT NULL, attempt INTEGER NOT NULL, attempt_id TEXT NOT NULL, profile_json TEXT NOT NULL, state TEXT NOT NULL, fence TEXT, start_permitted INTEGER NOT NULL DEFAULT 0, report_json TEXT, report_digest TEXT, next_availability_revision TEXT, provider_release_proof_json TEXT);
        CREATE TABLE IF NOT EXISTS remote_transfers (assignment_id TEXT NOT NULL, direction TEXT NOT NULL, transfer_id TEXT NOT NULL, logical_name TEXT NOT NULL, digest TEXT NOT NULL, size_bytes INTEGER NOT NULL, private_path TEXT NOT NULL, received_bytes INTEGER NOT NULL DEFAULT 0, finalized INTEGER NOT NULL DEFAULT 0, descriptor_json TEXT, PRIMARY KEY(assignment_id, direction, transfer_id));
        CREATE TABLE IF NOT EXISTS remote_transfer_authorizations (assignment_id TEXT NOT NULL, authorization_id TEXT NOT NULL, revision INTEGER NOT NULL, coordinator_epoch TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, PRIMARY KEY(assignment_id, revision));
        CREATE TABLE IF NOT EXISTS agent_controls (operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, session_id TEXT NOT NULL, agent_id TEXT NOT NULL, request_json TEXT NOT NULL, state TEXT NOT NULL, result_code TEXT, effect_json TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS remote_assignment_controls (operation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, assignment_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL, state TEXT NOT NULL, result_code TEXT, evidence_json TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
        """)
    else:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_registration_intents (operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL, request_json TEXT NOT NULL, retirement_secret TEXT, result_json TEXT);
        CREATE TABLE IF NOT EXISTS agent_sessions_local (session_id TEXT PRIMARY KEY, value_json TEXT NOT NULL, registration_operation_id TEXT NOT NULL, retirement_secret TEXT, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_mutation_intents (operation TEXT NOT NULL, operation_id TEXT NOT NULL, digest TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT, PRIMARY KEY(operation, operation_id));
        CREATE TABLE IF NOT EXISTS agent_offers_local (session_id TEXT PRIMARY KEY, availability_revision TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_poll_state_local (session_id TEXT PRIMARY KEY, availability_revision TEXT NOT NULL, sequence INTEGER NOT NULL, request_digest TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT);
        CREATE TABLE IF NOT EXISTS agent_session_references (session_id TEXT NOT NULL, reference_kind TEXT NOT NULL, reference_id TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id, reference_kind, reference_id));
        CREATE TABLE IF NOT EXISTS agent_reference_revision (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), revision INTEGER NOT NULL);
        INSERT OR IGNORE INTO agent_reference_revision(singleton, revision) VALUES (1, 0);
        CREATE TRIGGER IF NOT EXISTS agent_reference_revision_insert AFTER INSERT ON agent_session_references BEGIN UPDATE agent_reference_revision SET revision = revision + 1 WHERE singleton = 1; END;
        CREATE TRIGGER IF NOT EXISTS agent_reference_revision_update AFTER UPDATE ON agent_session_references BEGIN UPDATE agent_reference_revision SET revision = revision + 1 WHERE singleton = 1; END;
        CREATE TRIGGER IF NOT EXISTS agent_reference_revision_delete AFTER DELETE ON agent_session_references BEGIN UPDATE agent_reference_revision SET revision = revision + 1 WHERE singleton = 1; END;
        CREATE TABLE IF NOT EXISTS agent_retirement_proofs_local (session_id TEXT PRIMARY KEY, proof_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_controls_local (operation_id TEXT PRIMARY KEY, request_json TEXT NOT NULL, effect_json TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS remote_assignment_controls_local (operation_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL, result_code TEXT, evidence_json TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
        """)


def _target_remote_delivery(
    daemon: "LocalDaemon",
    *,
    session_id: str,
    availability_revision: str,
    request: _ResidentAssignmentBundle,
    run_uri: str,
    input_paths: Mapping[str, Path],
) -> None:
    """Coordinator-private CAS target creation; delivery remains poll-owned."""
    _identifier(session_id, "session_id")
    _identifier(availability_revision, "availability_revision")
    if not isinstance(request, _ResidentAssignmentBundle):
        raise QueueServiceError("targeted delivery request is invalid")
    _identifier(request.assignment_id, "assignment_id")
    if not isinstance(run_uri, str) or not run_uri:
        raise QueueServiceError("targeted delivery run identity is invalid")
    expected_transfers = {item.transfer_id for item in request.inputs}
    if set(input_paths) != expected_transfers:
        raise QueueServiceError("targeted delivery input sources are incomplete")
    encoded = _canonical_json(request.to_dict())
    if len(encoded.encode("utf-8")) > _MAX_REMOTE_WIRE_VALUE_BYTES:
        raise QueueServiceError("targeted delivery request is too large")
    with daemon._connection() as conn:  # type: ignore[attr-defined]
        conn.execute("BEGIN IMMEDIATE")
        session = _session_from_row(
            conn.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)
            ).fetchone(),
            daemon._require_started(),  # type: ignore[attr-defined]
        )
        if (
            session.state is not AgentSessionState.ACTIVE
            or session.coordinator_epoch != daemon._epoch
        ):  # type: ignore[attr-defined]
            raise QueueConflictError("targeted delivery session is stale")
        prior = conn.execute(
            "SELECT request_json, session_id, availability_revision, coordinator_epoch "
            "FROM agent_deliveries WHERE assignment_id = ?",
            (request.assignment_id,),
        ).fetchone()
        if prior is not None:
            if tuple(str(prior[index]) for index in range(4)) != (
                encoded,
                session_id,
                availability_revision,
                daemon._epoch,
            ):  # type: ignore[attr-defined]
                raise QueueConflictError(
                    "targeted delivery conflicts with durable assignment"
                )
            retained = conn.execute(
                "SELECT session_id, availability_revision, issuer_epoch, run_uri, "
                "stage_work_id, stage_name, attempt, attempt_id, profile_json "
                "FROM remote_assignments WHERE assignment_id = ?",
                (request.assignment_id,),
            ).fetchone()
            if retained is None or tuple(retained) != (
                session_id,
                availability_revision,
                daemon._epoch,  # type: ignore[attr-defined]
                run_uri,
                request.stage_work_id,
                request.stage_name,
                request.attempt,
                request.attempt_id,
                _canonical_json(request.profile.to_dict()),
            ):
                raise QueueConflictError(
                    "targeted delivery owner identity conflicts with durable state"
                )
            transfer_rows = {
                str(row["transfer_id"]): row
                for row in conn.execute(
                    "SELECT * FROM remote_transfers WHERE assignment_id = ? "
                    "AND direction = 'input'",
                    (request.assignment_id,),
                )
            }
            if set(transfer_rows) != expected_transfers:
                raise QueueConflictError(
                    "targeted delivery input retention is incomplete"
                )
            for item in request.inputs:
                row = transfer_rows[item.transfer_id]
                target = (
                    daemon.config.coordinator_root
                    / "remote-relay"
                    / request.assignment_id
                    / "inputs"
                    / item.transfer_id
                )
                if (
                    str(row["logical_name"]) != item.logical_name
                    or str(row["digest"]) != item.digest
                    or int(row["size_bytes"]) != item.size_bytes
                    or str(row["private_path"]) != str(target)
                    or int(row["received_bytes"]) != item.size_bytes
                    or not bool(row["finalized"])
                    or str(row["descriptor_json"]) != _canonical_json(item.to_dict())
                ):
                    raise QueueConflictError(
                        "targeted delivery input retention conflicts"
                    )
                try:
                    retained_data = _read_regular_file_bytes(target)
                except QueueConflictError as exc:
                    raise QueueConflictError(
                        "targeted delivery input bytes are unavailable"
                    ) from exc
                if (
                    len(retained_data) != item.size_bytes
                    or hashlib.sha256(retained_data).hexdigest() != item.digest
                ):
                    raise QueueConflictError(
                        "targeted delivery input bytes conflict with durable state"
                    )
            coverage = {
                str(row["reference_class"])
                for row in conn.execute(
                    "SELECT reference_class FROM agent_replacement_coverage "
                    "WHERE session_id = ? AND assignment_id = ?",
                    (session_id, request.assignment_id),
                )
            }
            if coverage != set(_REPLACEMENT_ASSIGNMENT_REFERENCE_CLASSES):
                raise QueueConflictError(
                    "targeted delivery agent-owner coverage is incomplete"
                )
            conn.commit()
            return
        offer = conn.execute(
            "SELECT offer_json, expires_at FROM agent_offers WHERE session_id = ? "
            "AND availability_revision = ? AND coordinator_epoch = ? "
            "AND current = 1",
            (session_id, availability_revision, daemon._epoch),  # type: ignore[attr-defined]
        ).fetchone()
        if offer is None or str(offer["expires_at"]) < daemon._accepted_time(conn):  # type: ignore[attr-defined]
            raise QueueConflictError("targeted delivery requires a current offer")
        offer_value = json.loads(str(offer["offer_json"]))
        offered_profiles = offer_value.get("resident_profiles", [])
        if request.profile.to_dict() not in offered_profiles:
            raise QueueConflictError(
                "targeted delivery resident profile is not in the current offer"
            )
        retained_inputs: list[tuple[object, ...]] = []
        for item in request.inputs:
            unresolved_source = Path(input_paths[item.transfer_id])
            if unresolved_source.is_symlink():
                raise QueueServiceError("targeted remote input must be a regular file")
            try:
                source = unresolved_source.resolve(strict=True)
                data = _read_regular_file_bytes(source)
            except (OSError, QueueConflictError) as exc:
                raise QueueServiceError(
                    "targeted remote input must be a regular file"
                ) from exc
            if (
                len(data) != item.size_bytes
                or hashlib.sha256(data).hexdigest() != item.digest
            ):
                raise QueueConflictError(
                    "targeted remote input changed before durable relay"
                )
            target = (
                daemon.config.coordinator_root
                / "remote-relay"
                / request.assignment_id
                / "inputs"
                / item.transfer_id
            )
            _atomic_regular_file(target, data)
            retained_inputs.append(
                (
                    request.assignment_id,
                    "input",
                    item.transfer_id,
                    item.logical_name,
                    item.digest,
                    item.size_bytes,
                    str(target),
                    item.size_bytes,
                    1,
                    _canonical_json(item.to_dict()),
                )
            )
        conn.execute(
            "INSERT INTO remote_assignments(assignment_id, session_id, "
            "availability_revision, issuer_epoch, run_uri, stage_work_id, "
            "stage_name, attempt, attempt_id, profile_json, state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BOUND')",
            (
                request.assignment_id,
                session_id,
                availability_revision,
                daemon._epoch,
                run_uri,
                request.stage_work_id,
                request.stage_name,
                request.attempt,
                request.attempt_id,
                _canonical_json(request.profile.to_dict()),
            ),
        )
        conn.executemany(
            "INSERT INTO remote_transfers(assignment_id, direction, transfer_id, "
            "logical_name, digest, size_bytes, private_path, received_bytes, "
            "finalized, descriptor_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            retained_inputs,
        )
        conn.execute(
            "INSERT INTO agent_deliveries(assignment_id, session_id, availability_revision, coordinator_epoch, request_json, state, poll_sequence) VALUES (?, ?, ?, ?, ?, 'TARGETED', NULL)",
            (
                request.assignment_id,
                session_id,
                availability_revision,
                daemon._epoch,
                encoded,
            ),  # type: ignore[attr-defined]
        )
        conn.execute(
            "INSERT OR IGNORE INTO agent_coordinator_references(session_id, reference_kind, reference_id, resolved) VALUES (?, 'delivery', ?, 0)",
            (session_id, request.assignment_id),
        )
        conn.executemany(
            "INSERT INTO agent_replacement_coverage(session_id, assignment_id, "
            "reference_class) VALUES (?, ?, ?)",
            [
                (session_id, request.assignment_id, reference_class)
                for reference_class in _REPLACEMENT_ASSIGNMENT_REFERENCE_CLASSES
            ],
        )
        conn.commit()


def validate_agent_session_schema(
    conn: sqlite3.Connection, *, coordinator: bool
) -> None:
    """Reject a current root missing required session or execution tables."""
    required = (
        {
            "agent_sessions": {
                "session_id",
                "agent_id",
                "agent_root_id",
                "principal_id",
                "policy_revision",
                "config_revision",
                "inventory_revision",
                "availability_revision",
                "capabilities_json",
                "pools_json",
                "retirement_verifier",
                "coordinator_epoch",
                "state",
                "created_at",
            },
            "agent_receipts": {
                "principal_id",
                "operation",
                "idempotency_key",
                "digest",
                "result_json",
            },
            "agent_offers": {
                "offer_id",
                "session_id",
                "coordinator_epoch",
                "availability_revision",
                "offer_json",
                "accepted_at",
                "expires_at",
                "current",
            },
            "agent_poll_state": {
                "principal_id",
                "session_id",
                "sequence",
                "availability_revision",
                "coordinator_epoch",
                "wait_timeout_ms",
                "digest",
                "active",
                "result_json",
            },
            "agent_coordinator_references": {
                "session_id",
                "reference_kind",
                "reference_id",
                "resolved",
            },
            "agent_retirement_proofs": {"session_id", "proof_json"},
            "agent_session_tombstones": {"session_id", "state"},
            "session_replacements": {
                "operation_id",
                "principal_id",
                "request_json",
                "request_digest",
                "agent_id",
                "old_session_id",
                "successor_session_id",
                "state",
                "readiness",
                "withholding_reason",
                "decision_projection_json",
                "decision_projection_digest",
                "required_claim_ids_json",
                "observed_claim_ids_json",
                "successor_observation_digest",
                "readiness_projection_digest",
                "result_json",
                "decided_at",
                "ready_at",
            },
            "agent_replacement_coverage": {
                "session_id",
                "assignment_id",
                "reference_class",
            },
            "agent_deliveries": {
                "assignment_id",
                "session_id",
                "availability_revision",
                "coordinator_epoch",
                "request_json",
                "state",
                "poll_sequence",
            },
            "remote_assignments": {
                "assignment_id",
                "session_id",
                "availability_revision",
                "issuer_epoch",
                "run_uri",
                "stage_work_id",
                "stage_name",
                "attempt",
                "attempt_id",
                "profile_json",
                "state",
                "fence",
                "start_permitted",
                "report_json",
                "report_digest",
                "next_availability_revision",
                "provider_release_proof_json",
            },
            "remote_transfers": {
                "assignment_id",
                "direction",
                "transfer_id",
                "logical_name",
                "digest",
                "size_bytes",
                "private_path",
                "received_bytes",
                "finalized",
                "descriptor_json",
            },
            "remote_transfer_authorizations": {
                "assignment_id",
                "authorization_id",
                "revision",
                "coordinator_epoch",
                "operation_id",
                "expires_at",
            },
            "agent_controls": {
                "operation_id",
                "principal_id",
                "session_id",
                "agent_id",
                "request_json",
                "state",
                "result_code",
                "effect_json",
                "acknowledged",
            },
            "remote_assignment_controls": {
                "operation_id",
                "session_id",
                "assignment_id",
                "request_json",
                "state",
                "result_code",
                "evidence_json",
                "acknowledged",
            },
        }
        if coordinator
        else {
            "agent_registration_intents": {
                "operation_id",
                "digest",
                "request_json",
                "retirement_secret",
                "result_json",
            },
            "agent_sessions_local": {
                "session_id",
                "value_json",
                "registration_operation_id",
                "retirement_secret",
                "state",
            },
            "agent_mutation_intents": {
                "operation",
                "operation_id",
                "digest",
                "request_json",
                "result_json",
            },
            "agent_offers_local": {
                "session_id",
                "availability_revision",
                "state",
            },
            "agent_poll_state_local": {
                "session_id",
                "availability_revision",
                "sequence",
                "request_digest",
                "state",
                "result_json",
            },
            "agent_session_references": {
                "session_id",
                "reference_kind",
                "reference_id",
                "resolved",
            },
            "agent_reference_revision": {"singleton", "revision"},
            "agent_retirement_proofs_local": {"session_id", "proof_json"},
            "agent_controls_local": {
                "operation_id",
                "request_json",
                "effect_json",
                "acknowledged",
            },
            "remote_assignment_controls_local": {
                "operation_id",
                "assignment_id",
                "request_json",
                "result_code",
                "evidence_json",
                "acknowledged",
            },
        }
    )
    present = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if not set(required).issubset(present):
        raise QueueServiceError("agent session schema is incomplete")
    for table, columns in required.items():
        actual = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if not columns.issubset(actual):
            raise QueueServiceError("agent session schema is incomplete")
    required_objects = (
        {("index", "agent_one_open_session")}
        if coordinator
        else {
            ("trigger", "agent_reference_revision_insert"),
            ("trigger", "agent_reference_revision_update"),
            ("trigger", "agent_reference_revision_delete"),
        }
    )
    present_objects = {
        (str(row[0]), str(row[1]))
        for row in conn.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('index', 'trigger')"
        )
    }
    if not required_objects.issubset(present_objects):
        raise QueueServiceError("agent session schema is incomplete")
    if coordinator:
        poll_key = {
            int(row[5]): str(row[1])
            for row in conn.execute("PRAGMA table_info(agent_poll_state)")
            if int(row[5])
        }
        if poll_key != {1: "principal_id", 2: "session_id"}:
            raise QueueServiceError("agent session schema is incomplete")
    if not coordinator:
        revision = conn.execute(
            "SELECT revision FROM agent_reference_revision WHERE singleton = 1"
        ).fetchone()
        if revision is None or int(revision[0]) < 0:
            raise QueueServiceError("agent session schema is incomplete")


def _receipt(
    conn: sqlite3.Connection, principal: str, operation: str, key: str, digest: str
) -> Mapping[str, PlainData] | None:
    row = conn.execute(
        "SELECT digest, result_json FROM agent_receipts WHERE principal_id = ? AND operation = ? AND idempotency_key = ?",
        (principal, operation, key),
    ).fetchone()
    if row is None:
        return None
    if str(row["digest"]) != digest:
        raise QueueConflictError("idempotency key was reused with different content")
    value = json.loads(str(row["result_json"]))
    if not isinstance(value, Mapping):
        raise QueueServiceError("agent receipt is invalid")
    return freeze_plain_data(value, path="agent receipt")


def _coordinator_references_empty(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_coordinator_references WHERE session_id = ? AND resolved = 0",
        (session_id,),
    ).fetchone()
    return row is not None and int(row["n"]) == 0


def _verify_retirement_secret(
    conn: sqlite3.Connection, session_id: str, revealed_secret: str
) -> None:
    """Reject proof possession failures before retiring-state mutations."""
    row = conn.execute(
        "SELECT retirement_verifier FROM agent_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise QueueServiceError("agent session was not found")
    actual = hashlib.sha256(bytes.fromhex(revealed_secret)).hexdigest()
    if not hmac.compare_digest(actual, str(row["retirement_verifier"])):
        raise QueueServiceError("agent retirement proof is invalid")


def _write_receipt(
    conn: sqlite3.Connection,
    principal: str,
    operation: str,
    key: str,
    digest: str,
    result: Mapping[str, PlainData],
) -> None:
    conn.execute(
        "INSERT INTO agent_receipts(principal_id, operation, idempotency_key, digest, result_json) VALUES (?, ?, ?, ?, ?)",
        (
            principal,
            operation,
            key,
            digest,
            json.dumps(result, sort_keys=True, separators=(",", ":")),
        ),
    )


def _session_from_row(
    row: sqlite3.Row | None,
    coordinator_id: str,
    *,
    expected_principal: str | None = None,
) -> AgentSession:
    if row is None:
        raise QueueServiceError("agent session was not found")
    if (
        expected_principal is not None
        and str(row["principal_id"]) != expected_principal
    ):
        raise QueueServiceError("agent session is not authorized")
    capabilities = _stored_identifiers(row["capabilities_json"], "session capabilities")
    pools = _stored_identifiers(row["pools_json"], "session pools")
    return AgentSession(
        str(row["session_id"]),
        coordinator_id,
        str(row["coordinator_epoch"]),
        str(row["agent_id"]),
        str(row["agent_root_id"]),
        str(row["policy_revision"]),
        str(row["config_revision"]),
        str(row["inventory_revision"]),
        str(row["availability_revision"]),
        capabilities,
        pools,
        AgentSessionState(str(row["state"])),
    )


def _session_from_value(value: Mapping[str, PlainData]) -> AgentSession:
    required = {
        "session_id",
        "coordinator_id",
        "coordinator_epoch",
        "agent_id",
        "agent_root_id",
        "policy_revision",
        "config_revision",
        "inventory_revision",
        "availability_revision",
        "capabilities",
        "pools",
        "state",
    }
    if set(value) != required:
        raise QueueServiceError("agent session receipt fields are invalid")
    capabilities = value.get("capabilities")
    pools = value.get("pools")
    if (
        not isinstance(capabilities, (list, tuple))
        or any(not isinstance(item, str) for item in capabilities)
        or not isinstance(pools, (list, tuple))
        or any(not isinstance(item, str) for item in pools)
    ):
        raise QueueServiceError("agent session receipt capabilities are invalid")
    return AgentSession(
        _plain_identifier(value, "session_id"),
        _plain_identifier(value, "coordinator_id"),
        _plain_identifier(value, "coordinator_epoch"),
        _plain_identifier(value, "agent_id"),
        _plain_identifier(value, "agent_root_id"),
        _plain_identifier(value, "policy_revision"),
        _plain_identifier(value, "config_revision"),
        _plain_identifier(value, "inventory_revision"),
        _plain_identifier(value, "availability_revision"),
        tuple(cast(Sequence[str], capabilities)),
        tuple(cast(Sequence[str], pools)),
        AgentSessionState(_plain_identifier(value, "state")),
    )


def _stored_identifiers(value: object, name: str) -> tuple[str, ...]:
    try:
        stored = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise QueueServiceError(f"{name} are invalid") from exc
    if not isinstance(stored, list) or any(
        not isinstance(item, str) for item in stored
    ):
        raise QueueServiceError(f"{name} are invalid")
    _identifiers(stored, name)
    return tuple(stored)


def _require_matching_retirement_proof(
    session: AgentSession, proof: AgentRetirementProof
) -> None:
    if (
        proof.session_id != session.session_id
        or proof.coordinator_id != session.coordinator_id
        or proof.coordinator_epoch != session.coordinator_epoch
        or proof.agent_id != session.agent_id
        or proof.agent_root_id != session.agent_root_id
        or proof.policy_revision != session.policy_revision
        or proof.config_revision != session.config_revision
        or proof.inventory_revision != session.inventory_revision
        or proof.availability_revision != session.availability_revision
    ):
        raise QueueConflictError("agent retirement proof is stale")


def _require_matching_provider_release_proof(
    session: AgentSession,
    proof: AgentProviderReleaseProof,
    *,
    assignment_id: str,
    fence: str,
    availability_revision: str,
) -> None:
    if (
        proof.session_id != session.session_id
        or proof.coordinator_id != session.coordinator_id
        or proof.coordinator_epoch != session.coordinator_epoch
        or proof.agent_id != session.agent_id
        or proof.agent_root_id != session.agent_root_id
        or proof.policy_revision != session.policy_revision
        or proof.config_revision != session.config_revision
        or proof.inventory_revision != session.inventory_revision
        or proof.assignment_id != assignment_id
        or proof.execution_fence != fence
        or proof.released_availability_revision != availability_revision
    ):
        raise QueueConflictError("agent provider release proof is stale")


def _plain_identifier(value: Mapping[str, PlainData], key: str) -> str:
    item = value.get(key)
    _identifier(item, key)
    return item  # type: ignore[return-value]


def _plain_result(value: object, path: str) -> Mapping[str, PlainData]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise QueueServiceError(f"{path} is invalid") from exc
    if not isinstance(decoded, Mapping):
        raise QueueServiceError(f"{path} is invalid")
    return freeze_plain_data(decoded, path=path)


def _canonical_json(value: Mapping[str, PlainData]) -> str:
    return json.dumps(
        thaw_plain_data(value, path="agent session durable value"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Mapping[str, PlainData]) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _secret_digest(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise QueueServiceError(f"{name} is invalid")


def _identifier(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_IDENTIFIER
        or _IDENTIFIER_PATTERN.fullmatch(value) is None
    ):
        raise QueueServiceError(f"{name} must be a bounded non-empty string")


def _identifiers(values: Sequence[str], name: str, *, non_empty: bool = False) -> None:
    if non_empty and not values:
        raise QueueServiceError(f"{name} must not be empty")
    if len(values) > _MAX_COLLECTION or len(set(values)) != len(values):
        raise QueueServiceError(f"{name} must be a bounded unique collection")
    for value in values:
        _identifier(value, name)


def _add_seconds(timestamp: str, seconds: int) -> str:
    from datetime import timedelta

    return (
        (parse_timestamp(timestamp) + timedelta(seconds=seconds))
        .isoformat()
        .replace("+00:00", "Z")
    )


__all__ = [
    "AgentAssignmentControl",
    "AgentControl",
    "AgentControlEffect",
    "AgentControlKind",
    "AgentOffer",
    "AgentPollActiveError",
    "AgentPollSequenceGapError",
    "AgentProviderDescriptor",
    "AgentPolicyConfig",
    "AgentPrincipalPolicy",
    "AgentRegistration",
    "AgentRetirementProof",
    "AgentSession",
    "AgentSessionState",
    "AgentSessionView",
    "AgentStalePollError",
    "GpuDeviceDescriptor",
    "PROTOCOL_VERSION",
    "ScopedAuthorizer",
    "TransportPrincipalPolicy",
    "initialize_agent_session_schema",
    "validate_agent_session_schema",
]
