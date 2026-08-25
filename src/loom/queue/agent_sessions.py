"""Authenticated agent session and remote stage execution protocol.

This module owns coordinator-facing sessions, offers, targeted delivery,
transfer authorization, and replay. Resident profiles, paths, physical
admission, and process launch remain protected agent-local concerns.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
from time import monotonic, sleep
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp

from .errors import QueueConflictError, QueueServiceError
from ._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    TRANSFER_CHUNK_BYTES,
    GpuDeviceDescriptor,
    ResidentProfileDescriptor,
    _DeliveredExecutionRequest,
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
    from .local_daemon import LocalDaemon, LocalDaemonPrincipal


PROTOCOL_VERSION = "5"
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
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@+\-]*\Z")


class AgentSessionState(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRING = "RETIRING"
    RETIRED_CLEAN = "RETIRED_CLEAN"


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


class AgentPollActiveError(QueueConflictError):
    """An exact poll retry reached the still-held original poll."""


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
            }
            if not set(actions).issubset(allowed):
                raise QueueServiceError("operator actions must be an explicit finite set")
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
class AgentOffer:
    session_id: str
    coordinator_epoch: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    cpu: int
    memory_bytes: int
    ttl_seconds: int
    provider_descriptors: tuple[SchedulingComponentDescriptor, ...]
    pools: tuple[str, ...] = ("default",)
    reflected_claim_ids: tuple[str, ...] = ()
    resident_profiles: tuple[ResidentProfileDescriptor, ...] = ()
    gpu_devices: tuple[GpuDeviceDescriptor, ...] = ()
    gpu_atoms: tuple[CapacityAtom, ...] = ()

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
        if not self.cpu and not self.memory_bytes and not self.gpu_devices:
            raise QueueServiceError("offer capacity must not be empty")
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, int)
            or not 1 <= self.ttl_seconds <= _MAX_OFFER_TTL_SECONDS
        ):
            raise QueueServiceError("offer TTL is outside the permitted range")
        provider_descriptors = tuple(self.provider_descriptors)
        if any(
            not isinstance(item, SchedulingComponentDescriptor)
            for item in provider_descriptors
        ) or len({item.kind for item in provider_descriptors}) != len(
            provider_descriptors
        ):
            raise QueueServiceError("offer provider descriptors are invalid")
        configured_kinds: set[str] = set()
        if self.cpu:
            configured_kinds.add("cpu")
        if self.memory_bytes:
            configured_kinds.add("memory")
        if self.gpu_devices:
            configured_kinds.add("gpu")
        if {item.kind for item in provider_descriptors} != configured_kinds:
            raise QueueServiceError(
                "offer provider descriptors must match configured resources"
            )
        object.__setattr__(
            self,
            "provider_descriptors",
            tuple(sorted(provider_descriptors, key=lambda item: item.kind)),
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

    def value(self) -> dict[str, PlainData]:
        capacity_atoms: list[PlainData] = []
        if self.cpu:
            capacity_atoms.append(
                {
                    "owner_resource_kind": "cpu",
                    "local_capacity_key": "cpu",
                    "amount": {"numerator": self.cpu, "denominator": 1},
                    "unit": "count",
                    "granularity": {"numerator": 1, "denominator": 1},
                }
            )
        if self.memory_bytes:
            capacity_atoms.append(
                {
                    "owner_resource_kind": "memory",
                    "local_capacity_key": "memory",
                    "amount": {"numerator": self.memory_bytes, "denominator": 1},
                    "unit": "byte",
                    "granularity": {"numerator": 1, "denominator": 1},
                }
            )
        capacity_atoms.extend(atom.to_dict() for atom in self.gpu_atoms)
        return {
            "session_id": self.session_id,
            "coordinator_epoch": self.coordinator_epoch,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "capacity_atoms": capacity_atoms,
            "ttl_seconds": self.ttl_seconds,
            "provider_descriptors": [
                descriptor.to_dict() for descriptor in self.provider_descriptors
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
            "provider_descriptors",
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
        capacities: dict[str, int] = {}
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
            if kind not in {"cpu", "memory", "gpu"}:
                raise QueueServiceError("agent offer capacity is invalid")
            parsed = _offer_capacity_atom(atom)
            if kind == "gpu":
                gpu_atoms.append(parsed)
                continue
            if kind in capacities or parsed.local_capacity_key != kind:
                raise QueueServiceError("agent offer capacity is invalid")
            expected_unit = "count" if kind == "cpu" else "byte"
            if (
                parsed.unit != expected_unit
                or parsed.amount.denominator != 1
                or parsed.granularity != ExactQuantity(1)
            ):
                raise QueueServiceError("agent offer capacity is invalid")
            capacities[cast(str, kind)] = parsed.amount.numerator
        pools = value["pools"]
        claims = value["reflected_claim_ids"]
        profiles = value["resident_profiles"]
        gpu_devices = value["gpu_devices"]
        provider_descriptors = value["provider_descriptors"]
        if (
            not isinstance(pools, Sequence)
            or isinstance(pools, (str, bytes))
            or not isinstance(claims, Sequence)
            or isinstance(claims, (str, bytes))
            or not isinstance(profiles, Sequence)
            or isinstance(profiles, (str, bytes))
            or not isinstance(gpu_devices, Sequence)
            or isinstance(gpu_devices, (str, bytes))
            or not isinstance(provider_descriptors, Sequence)
            or isinstance(provider_descriptors, (str, bytes))
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
            provider_descriptors=tuple(
                SchedulingComponentDescriptor.from_dict(item)
                for item in provider_descriptors
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
        )


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
            raise QueueServiceError("daemon principal is not authorized for this operation")
        rule = matches[0]
        if action not in rule.actions:
            raise QueueServiceError("daemon principal is not authorized for this operation")
        if agent_id is not None and agent_id not in rule.agent_ids:
            raise QueueServiceError("daemon principal is not authorized for this operation")
        if pool is not None and pool not in rule.pools:
            raise QueueServiceError("daemon principal is not authorized for this operation")


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
        poll_id: str,
        wait_timeout_ms: int,
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).wait_for_work(
            session_id,
            availability_revision,
            poll_id=poll_id,
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
    ) -> AgentSession:
        return AgentSessionService(self._daemon, self._principal).release_assignment(
            session_id,
            assignment_id,
            fence=fence,
            availability_revision=availability_revision,
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
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(
            self._daemon, self._principal
        ).acknowledge_assignment_control(session_id, operation_id, code=code)


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
                    "agent-sessions-v5",
                    REMOTE_EXECUTION_CAPABILITY,
                    REGULAR_FILE_RELAY_CAPABILITY,
                ],
                "coordinator_id": coordinator_id,
                "coordinator_epoch": self._daemon._epoch or "",  # type: ignore[attr-defined]
                "role": "agent",
            },
            path="agent handshake",
        )

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
                    "UPDATE agent_polls SET active = 0 WHERE session_id = ?",
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

    def acknowledge_assignment_control(
        self,
        session_id: str,
        operation_id: str,
        *,
        code: str,
    ) -> Mapping[str, PlainData]:
        rule, revision = self._authorize("assignment_control")
        _identifier(session_id, "session_id")
        _identifier(operation_id, "operation_id")
        if code not in {"never_started", "contained", "terminal", "unknown"}:
            raise QueueServiceError("assignment control result code is invalid")
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
                "SELECT request_json, result_code FROM remote_assignment_controls "
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
            state = "applied" if code != "unknown" else "settling"
            conn.execute(
                "UPDATE remote_assignment_controls SET state = ?, result_code = ?, "
                "acknowledged = 1 WHERE operation_id = ?",
                (state, code, operation_id),
            )
            conn.commit()
        return freeze_plain_data(
            {
                "operation_id": control.operation_id,
                "assignment_id": control.assignment_id,
                "state": state,
                "code": code,
            },
            path="assignment control acknowledgement",
        )

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
                "AND state != ? LIMIT 1",
                (rule.agent_id, AgentSessionState.RETIRED_CLEAN.value),
            ).fetchone()
            if previous is not None:
                raise QueueConflictError("agent already has an active session")
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

    def publish_offer(
        self, offer: AgentOffer, *, idempotency_key: str
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("offer")
        _identifier(idempotency_key, "idempotency_key")
        digest = _digest(offer.value())
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
            active_poll = conn.execute(
                "SELECT poll_id FROM agent_polls WHERE session_id = ? AND active = 1",
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
        poll_id: str,
        wait_timeout_ms: int,
    ) -> Mapping[str, PlainData]:
        rule, policy_revision = self._authorize("poll")
        for identifier, name in (
            (session_id, "session_id"),
            (availability_revision, "availability_revision"),
            (poll_id, "poll_id"),
        ):
            _identifier(identifier, name)
        if (
            isinstance(wait_timeout_ms, bool)
            or not isinstance(wait_timeout_ms, int)
            or not 1 <= wait_timeout_ms <= _MAX_POLL_WAIT_MILLISECONDS
        ):
            raise QueueServiceError("work poll wait is outside the permitted range")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        request_value: dict[str, PlainData] = {
            "session_id": session_id,
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
            existing = conn.execute(
                "SELECT digest, active, result_json FROM agent_polls "
                "WHERE principal_id = ? AND poll_id = ?",
                (rule.principal_id, poll_id),
            ).fetchone()
            if existing is not None:
                if str(existing["digest"]) != digest:
                    raise QueueConflictError(
                        "poll ID was reused with different content"
                    )
                if existing["result_json"] is not None:
                    value = _plain_result(existing["result_json"], "agent poll receipt")
                    conn.commit()
                    return value
                if bool(existing["active"]):
                    raise AgentPollActiveError("work poll is already active")
                raise QueueConflictError("work poll was fenced and is not reusable")
            self._require_current_offer(conn, session_id, availability_revision)
            active = conn.execute(
                "SELECT poll_id FROM agent_polls WHERE session_id = ? "
                "AND availability_revision = ? AND active = 1",
                (session_id, availability_revision),
            ).fetchone()
            if active is not None:
                raise QueueConflictError(
                    "agent session already has an active work poll"
                )
            conn.execute(
                "INSERT INTO agent_polls("
                "poll_id, principal_id, session_id, availability_revision, "
                "coordinator_epoch, wait_timeout_ms, digest, active, result_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL)",
                (
                    poll_id,
                    rule.principal_id,
                    session_id,
                    availability_revision,
                    epoch,
                    wait_timeout_ms,
                    digest,
                ),
            )
            conn.commit()

        delivered = self._take_targeted_delivery(
            principal_id=rule.principal_id,
            session_id=session_id,
            availability_revision=availability_revision,
            poll_id=poll_id,
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
                        "SELECT active, result_json FROM agent_polls "
                        "WHERE principal_id = ? AND poll_id = ? AND digest = ?",
                        (rule.principal_id, poll_id, digest),
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
                    poll_id=poll_id,
                    epoch=epoch,
                    digest=digest,
                )
                if delivered is not None:
                    return delivered
            value = {
                "result": "wait",
                "poll_id": poll_id,
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
                    "UPDATE agent_polls SET active = 0, result_json = ? "
                    "WHERE principal_id = ? AND poll_id = ? AND digest = ? AND active = 1",
                    (_canonical_json(value), rule.principal_id, poll_id, digest),
                ).rowcount
                if updated != 1:
                    raise QueueConflictError("work poll was fenced")
                conn.commit()
            return freeze_plain_data(value, path="agent wait")
        except Exception:
            with self._daemon._connection() as conn:  # type: ignore[attr-defined]
                conn.execute(
                    "UPDATE agent_polls SET active = 0 WHERE principal_id = ? AND poll_id = ? AND digest = ?",
                    (rule.principal_id, poll_id, digest),
                )
                conn.commit()
            raise

    def _take_targeted_delivery(
        self,
        *,
        principal_id: str,
        session_id: str,
        availability_revision: str,
        poll_id: str,
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
                "poll_id": poll_id,
                "coordinator_epoch": epoch,
                "request": cast(PlainData, json.loads(str(row["request_json"]))),
            }
            updated = conn.execute(
                "UPDATE agent_deliveries SET state = 'DELIVERED', poll_id = ? "
                "WHERE assignment_id = ? AND state = 'TARGETED'",
                (poll_id, str(row["assignment_id"])),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("targeted delivery changed before its poll")
            updated = conn.execute(
                "UPDATE agent_polls SET active = 0, result_json = ? WHERE "
                "principal_id = ? AND poll_id = ? AND digest = ? AND active = 1",
                (_canonical_json(value), principal_id, poll_id, digest),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("work poll was fenced")
            conn.commit()
        return freeze_plain_data(value, path="agent assignment delivery")

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
            request = _DeliveredExecutionRequest.from_dict(
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

    def release_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        availability_revision: str,
    ) -> AgentSession:
        rule, policy_revision = self._authorize("release")
        _identifier(fence, "fence")
        _identifier(availability_revision, "availability_revision")
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            session = self._require_remote_session(
                conn, rule, policy_revision, session_id, epoch
            )
            row = self._require_remote_assignment(conn, session_id, assignment_id)
            if row["fence"] != fence or str(row["state"]) not in {
                "TERMINAL",
                "RELEASED",
            }:
                raise QueueConflictError("remote release fence is stale")
            if str(row["state"]) == "RELEASED":
                if row["next_availability_revision"] != availability_revision:
                    raise QueueConflictError("remote release replay conflicts")
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
        self._remote_execution().remote_release(assignment_id)
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
                "session_id = ? AND reference_kind = 'delivery' AND reference_id = ?",
                (session_id, assignment_id),
            )
            conn.execute(
                "UPDATE remote_assignment_controls SET state = 'applied', "
                "result_code = COALESCE(result_code, 'terminal'), acknowledged = 1 "
                "WHERE assignment_id = ?",
                (assignment_id,),
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
                "UPDATE agent_polls SET active = 0 WHERE session_id = ?",
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


def initialize_agent_session_schema(
    conn: sqlite3.Connection, *, coordinator: bool
) -> None:
    """Create the current tables in a freshly initialized version-5 root."""
    if coordinator:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_sessions (session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, agent_root_id TEXT NOT NULL, principal_id TEXT NOT NULL, policy_revision TEXT NOT NULL, config_revision TEXT NOT NULL, inventory_revision TEXT NOT NULL, availability_revision TEXT NOT NULL, capabilities_json TEXT NOT NULL, pools_json TEXT NOT NULL, retirement_verifier TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS agent_one_open_session ON agent_sessions(agent_id) WHERE state != 'RETIRED_CLEAN';
        CREATE TABLE IF NOT EXISTS agent_receipts (principal_id TEXT NOT NULL, operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, digest TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(principal_id, operation, idempotency_key));
        CREATE TABLE IF NOT EXISTS agent_offers (offer_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, availability_revision TEXT NOT NULL, offer_json TEXT NOT NULL, accepted_at TEXT NOT NULL, expires_at TEXT NOT NULL, current INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_polls (principal_id TEXT NOT NULL, poll_id TEXT NOT NULL, session_id TEXT NOT NULL, availability_revision TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, wait_timeout_ms INTEGER NOT NULL, digest TEXT NOT NULL, active INTEGER NOT NULL, result_json TEXT, PRIMARY KEY(principal_id, poll_id));
        CREATE TABLE IF NOT EXISTS agent_coordinator_references (session_id TEXT NOT NULL, reference_kind TEXT NOT NULL, reference_id TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id, reference_kind, reference_id));
        CREATE TABLE IF NOT EXISTS agent_retirement_proofs (session_id TEXT PRIMARY KEY, proof_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_session_tombstones (session_id TEXT PRIMARY KEY, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_deliveries (assignment_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, availability_revision TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, request_json TEXT NOT NULL, state TEXT NOT NULL, poll_id TEXT);
        CREATE TABLE IF NOT EXISTS remote_assignments (assignment_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, availability_revision TEXT NOT NULL, issuer_epoch TEXT NOT NULL, run_uri TEXT NOT NULL, stage_work_id TEXT NOT NULL, stage_name TEXT NOT NULL, attempt INTEGER NOT NULL, attempt_id TEXT NOT NULL, profile_json TEXT NOT NULL, state TEXT NOT NULL, fence TEXT, start_permitted INTEGER NOT NULL DEFAULT 0, report_json TEXT, report_digest TEXT, next_availability_revision TEXT);
        CREATE TABLE IF NOT EXISTS remote_transfers (assignment_id TEXT NOT NULL, direction TEXT NOT NULL, transfer_id TEXT NOT NULL, logical_name TEXT NOT NULL, digest TEXT NOT NULL, size_bytes INTEGER NOT NULL, private_path TEXT NOT NULL, received_bytes INTEGER NOT NULL DEFAULT 0, finalized INTEGER NOT NULL DEFAULT 0, descriptor_json TEXT, PRIMARY KEY(assignment_id, direction, transfer_id));
        CREATE TABLE IF NOT EXISTS remote_transfer_authorizations (assignment_id TEXT NOT NULL, authorization_id TEXT NOT NULL, revision INTEGER NOT NULL, coordinator_epoch TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, PRIMARY KEY(assignment_id, revision));
        CREATE TABLE IF NOT EXISTS agent_controls (operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, session_id TEXT NOT NULL, agent_id TEXT NOT NULL, request_json TEXT NOT NULL, state TEXT NOT NULL, result_code TEXT, effect_json TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS remote_assignment_controls (operation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, assignment_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL, state TEXT NOT NULL, result_code TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
        """)
    else:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_registration_intents (operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL, request_json TEXT NOT NULL, retirement_secret TEXT, result_json TEXT);
        CREATE TABLE IF NOT EXISTS agent_sessions_local (session_id TEXT PRIMARY KEY, value_json TEXT NOT NULL, registration_operation_id TEXT NOT NULL, retirement_secret TEXT, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_mutation_intents (operation TEXT NOT NULL, operation_id TEXT NOT NULL, digest TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT, PRIMARY KEY(operation, operation_id));
        CREATE TABLE IF NOT EXISTS agent_offers_local (session_id TEXT PRIMARY KEY, availability_revision TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_polls_local (session_id TEXT NOT NULL, availability_revision TEXT NOT NULL, poll_id TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY(session_id, availability_revision));
        CREATE TABLE IF NOT EXISTS agent_session_references (session_id TEXT NOT NULL, reference_kind TEXT NOT NULL, reference_id TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id, reference_kind, reference_id));
        CREATE TABLE IF NOT EXISTS agent_reference_revision (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), revision INTEGER NOT NULL);
        INSERT OR IGNORE INTO agent_reference_revision(singleton, revision) VALUES (1, 0);
        CREATE TRIGGER IF NOT EXISTS agent_reference_revision_insert AFTER INSERT ON agent_session_references BEGIN UPDATE agent_reference_revision SET revision = revision + 1 WHERE singleton = 1; END;
        CREATE TRIGGER IF NOT EXISTS agent_reference_revision_update AFTER UPDATE ON agent_session_references BEGIN UPDATE agent_reference_revision SET revision = revision + 1 WHERE singleton = 1; END;
        CREATE TRIGGER IF NOT EXISTS agent_reference_revision_delete AFTER DELETE ON agent_session_references BEGIN UPDATE agent_reference_revision SET revision = revision + 1 WHERE singleton = 1; END;
        CREATE TABLE IF NOT EXISTS agent_retirement_proofs_local (session_id TEXT PRIMARY KEY, proof_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_controls_local (operation_id TEXT PRIMARY KEY, request_json TEXT NOT NULL, effect_json TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS remote_assignment_controls_local (operation_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL, result_code TEXT, acknowledged INTEGER NOT NULL DEFAULT 0);
        """)


def _target_remote_delivery(
    daemon: "LocalDaemon",
    *,
    session_id: str,
    availability_revision: str,
    request: _DeliveredExecutionRequest,
    run_uri: str,
    input_paths: Mapping[str, Path],
) -> None:
    """Coordinator-private CAS target creation; delivery remains poll-owned."""
    _identifier(session_id, "session_id")
    _identifier(availability_revision, "availability_revision")
    if not isinstance(request, _DeliveredExecutionRequest):
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
            "INSERT INTO agent_deliveries(assignment_id, session_id, availability_revision, coordinator_epoch, request_json, state, poll_id) VALUES (?, ?, ?, ?, ?, 'TARGETED', NULL)",
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
            "agent_polls": {
                "poll_id",
                "principal_id",
                "session_id",
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
            "agent_deliveries": {
                "assignment_id",
                "session_id",
                "availability_revision",
                "coordinator_epoch",
                "request_json",
                "state",
                "poll_id",
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
            "agent_polls_local": {
                "session_id",
                "availability_revision",
                "poll_id",
                "state",
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
            for row in conn.execute("PRAGMA table_info(agent_polls)")
            if int(row[5])
        }
        if poll_key != {1: "principal_id", 2: "poll_id"}:
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
    "AgentPolicyConfig",
    "AgentPrincipalPolicy",
    "AgentRegistration",
    "AgentRetirementProof",
    "AgentSession",
    "AgentSessionState",
    "AgentSessionView",
    "GpuDeviceDescriptor",
    "PROTOCOL_VERSION",
    "ScopedAuthorizer",
    "TransportPrincipalPolicy",
    "initialize_agent_session_schema",
    "validate_agent_session_schema",
]
