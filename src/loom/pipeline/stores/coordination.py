"""Workspace and sweep coordination contracts for cross-run facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .capabilities import BackendCapabilitySet
from .read_models import (
    BackendRevision,
    LeaseKind,
    LeaseRecord,
    LifecycleReason,
    RecoveryRecord,
)
from .schema_policy import AuthoritySchemaCheck


class CoordinationStoreError(ValueError):
    """Raised when workspace coordination records are invalid."""


class TrialState(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    workspace_id: str
    root_uri: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workspace_id",
            _non_empty_string(self.workspace_id, "workspace_id"),
        )
        if self.root_uri is not None:
            object.__setattr__(
                self, "root_uri", _non_empty_string(self.root_uri, "root_uri")
            )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "workspace_id": self.workspace_id,
            "root_uri": self.root_uri,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "WorkspaceIdentity":
        mapping = _mapping(data, "WorkspaceIdentity")
        _reject_unknown(
            mapping,
            {"workspace_id", "root_uri", "metadata"},
            "WorkspaceIdentity",
        )
        return cls(
            workspace_id=_non_empty_string(
                _required(mapping, "workspace_id"), "workspace_id"
            ),
            root_uri=_optional_string(mapping.get("root_uri"), "root_uri"),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class SweepIdentity:
    sweep_id: str
    workspace_id: str
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sweep_id", _non_empty_string(self.sweep_id, "sweep_id")
        )
        object.__setattr__(
            self, "workspace_id", _non_empty_string(self.workspace_id, "workspace_id")
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "sweep_id": self.sweep_id,
            "workspace_id": self.workspace_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepIdentity":
        mapping = _mapping(data, "SweepIdentity")
        _reject_unknown(
            mapping,
            {"sweep_id", "workspace_id", "metadata"},
            "SweepIdentity",
        )
        return cls(
            sweep_id=_non_empty_string(_required(mapping, "sweep_id"), "sweep_id"),
            workspace_id=_non_empty_string(
                _required(mapping, "workspace_id"), "workspace_id"
            ),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class TrialReference:
    trial_id: str
    sweep_id: str
    run_uri: str | None
    state: TrialState
    revision: BackendRevision
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "trial_id", _non_empty_string(self.trial_id, "trial_id")
        )
        object.__setattr__(
            self, "sweep_id", _non_empty_string(self.sweep_id, "sweep_id")
        )
        if self.run_uri is not None:
            object.__setattr__(
                self, "run_uri", _non_empty_string(self.run_uri, "run_uri")
            )
        object.__setattr__(self, "state", _coerce_trial_state(self.state))
        if not isinstance(self.revision, BackendRevision):
            raise CoordinationStoreError("revision must be a BackendRevision")
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "trial_id": self.trial_id,
            "sweep_id": self.sweep_id,
            "run_uri": self.run_uri,
            "state": self.state.value,
            "revision": self.revision.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "TrialReference":
        mapping = _mapping(data, "TrialReference")
        _reject_unknown(
            mapping,
            {"trial_id", "sweep_id", "run_uri", "state", "revision", "metadata"},
            "TrialReference",
        )
        return cls(
            trial_id=_non_empty_string(_required(mapping, "trial_id"), "trial_id"),
            sweep_id=_non_empty_string(_required(mapping, "sweep_id"), "sweep_id"),
            run_uri=_optional_string(mapping.get("run_uri"), "run_uri"),
            state=_coerce_trial_state(_required(mapping, "state")),
            revision=BackendRevision.from_dict(_required(mapping, "revision")),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class TrialLeaseRecord:
    workspace_id: str
    sweep_id: str
    trial_id: str
    lease: LeaseRecord

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "workspace_id", _non_empty_string(self.workspace_id, "workspace_id")
        )
        object.__setattr__(
            self, "sweep_id", _non_empty_string(self.sweep_id, "sweep_id")
        )
        object.__setattr__(
            self, "trial_id", _non_empty_string(self.trial_id, "trial_id")
        )
        if not isinstance(self.lease, LeaseRecord):
            raise CoordinationStoreError("lease must be a LeaseRecord")
        if self.lease.kind is not LeaseKind.TRIAL:
            raise CoordinationStoreError("trial lease records require trial leases")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "workspace_id": self.workspace_id,
            "sweep_id": self.sweep_id,
            "trial_id": self.trial_id,
            "lease": self.lease.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "TrialLeaseRecord":
        mapping = _mapping(data, "TrialLeaseRecord")
        _reject_unknown(
            mapping,
            {"workspace_id", "sweep_id", "trial_id", "lease"},
            "TrialLeaseRecord",
        )
        return cls(
            workspace_id=_non_empty_string(
                _required(mapping, "workspace_id"), "workspace_id"
            ),
            sweep_id=_non_empty_string(_required(mapping, "sweep_id"), "sweep_id"),
            trial_id=_non_empty_string(_required(mapping, "trial_id"), "trial_id"),
            lease=LeaseRecord.from_dict(_required(mapping, "lease")),
        )


@dataclass(frozen=True, slots=True)
class ResourceLeaseRecord:
    workspace_id: str
    resource_key: str
    lease: LeaseRecord
    amount: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "workspace_id", _non_empty_string(self.workspace_id, "workspace_id")
        )
        object.__setattr__(
            self, "resource_key", _non_empty_string(self.resource_key, "resource_key")
        )
        if not isinstance(self.lease, LeaseRecord):
            raise CoordinationStoreError("lease must be a LeaseRecord")
        if self.lease.kind is not LeaseKind.RESOURCE:
            raise CoordinationStoreError(
                "resource lease records require resource leases"
            )
        if (
            isinstance(self.amount, bool)
            or not isinstance(self.amount, int)
            or self.amount <= 0
        ):
            raise CoordinationStoreError("amount must be a positive integer")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "workspace_id": self.workspace_id,
            "resource_key": self.resource_key,
            "lease": self.lease.to_dict(),
            "amount": self.amount,
        }

    @classmethod
    def from_dict(cls, data: object) -> "ResourceLeaseRecord":
        mapping = _mapping(data, "ResourceLeaseRecord")
        _reject_unknown(
            mapping,
            {"workspace_id", "resource_key", "lease", "amount"},
            "ResourceLeaseRecord",
        )
        return cls(
            workspace_id=_non_empty_string(
                _required(mapping, "workspace_id"), "workspace_id"
            ),
            resource_key=_non_empty_string(
                _required(mapping, "resource_key"), "resource_key"
            ),
            lease=LeaseRecord.from_dict(_required(mapping, "lease")),
            amount=_positive_int(mapping.get("amount", 1), "amount"),
        )


@dataclass(frozen=True, slots=True)
class CoordinationRecoveryRecord:
    workspace_id: str
    recovery: RecoveryRecord
    sweep_id: str | None = None
    trial_id: str | None = None
    resource_key: str | None = None
    amount: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "workspace_id", _non_empty_string(self.workspace_id, "workspace_id")
        )
        if not isinstance(self.recovery, RecoveryRecord):
            raise CoordinationStoreError("recovery must be a RecoveryRecord")
        if self.sweep_id is not None:
            object.__setattr__(
                self, "sweep_id", _non_empty_string(self.sweep_id, "sweep_id")
            )
        if self.trial_id is not None:
            if self.sweep_id is None:
                raise CoordinationStoreError("trial recovery records require sweep_id")
            object.__setattr__(
                self, "trial_id", _non_empty_string(self.trial_id, "trial_id")
            )
        if self.resource_key is not None:
            object.__setattr__(
                self,
                "resource_key",
                _non_empty_string(self.resource_key, "resource_key"),
            )
        if self.amount is not None:
            object.__setattr__(self, "amount", _positive_int(self.amount, "amount"))
        if (self.resource_key is None) != (self.amount is None):
            raise CoordinationStoreError(
                "resource recovery records require resource_key and amount together"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "workspace_id": self.workspace_id,
            "recovery": self.recovery.to_dict(),
            "sweep_id": self.sweep_id,
            "trial_id": self.trial_id,
            "resource_key": self.resource_key,
            "amount": self.amount,
        }

    @classmethod
    def from_dict(cls, data: object) -> "CoordinationRecoveryRecord":
        mapping = _mapping(data, "CoordinationRecoveryRecord")
        _reject_unknown(
            mapping,
            {
                "workspace_id",
                "recovery",
                "sweep_id",
                "trial_id",
                "resource_key",
                "amount",
            },
            "CoordinationRecoveryRecord",
        )
        return cls(
            workspace_id=_non_empty_string(
                _required(mapping, "workspace_id"), "workspace_id"
            ),
            recovery=RecoveryRecord.from_dict(_required(mapping, "recovery")),
            sweep_id=_optional_string(mapping.get("sweep_id"), "sweep_id"),
            trial_id=_optional_string(mapping.get("trial_id"), "trial_id"),
            resource_key=_optional_string(mapping.get("resource_key"), "resource_key"),
            amount=_optional_positive_int(mapping.get("amount"), "amount"),
        )


@dataclass(frozen=True, slots=True)
class ConcurrencyCounter:
    counter_name: str
    value: int
    limit: int | None
    revision: BackendRevision

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "counter_name",
            _non_empty_string(self.counter_name, "counter_name"),
        )
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, int)
            or self.value < 0
        ):
            raise CoordinationStoreError("value must be a non-negative integer")
        if self.limit is not None and (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or self.limit <= 0
        ):
            raise CoordinationStoreError("limit must be a positive integer or None")
        if not isinstance(self.revision, BackendRevision):
            raise CoordinationStoreError("revision must be a BackendRevision")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "counter_name": self.counter_name,
            "value": self.value,
            "limit": self.limit,
            "revision": self.revision.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "ConcurrencyCounter":
        mapping = _mapping(data, "ConcurrencyCounter")
        _reject_unknown(
            mapping,
            {"counter_name", "value", "limit", "revision"},
            "ConcurrencyCounter",
        )
        return cls(
            counter_name=_non_empty_string(
                _required(mapping, "counter_name"), "counter_name"
            ),
            value=_non_negative_int(_required(mapping, "value"), "value"),
            limit=_optional_positive_int(mapping.get("limit"), "limit"),
            revision=BackendRevision.from_dict(_required(mapping, "revision")),
        )


@runtime_checkable
class WorkspaceCoordinationStore(Protocol):
    """Cross-run coordination contract for workspaces and sweeps."""

    def capabilities(self) -> BackendCapabilitySet: ...

    def check_schema(self) -> AuthoritySchemaCheck: ...

    def create_workspace(self, identity: WorkspaceIdentity) -> BackendRevision: ...

    def create_sweep(self, identity: SweepIdentity) -> BackendRevision: ...

    def record_trial(
        self,
        trial: TrialReference,
    ) -> BackendRevision: ...

    def list_trials(self, sweep_id: str) -> tuple[TrialReference, ...]: ...

    def acquire_trial_lease(
        self,
        sweep_id: str,
        trial_id: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> TrialLeaseRecord: ...

    def acquire_resource_lease(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        owner_id: str,
        amount: int,
        lease_ttl_seconds: int,
    ) -> ResourceLeaseRecord: ...

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord: ...

    def increment_counter(
        self, workspace_id: str, counter_name: str, *, amount: int = 1
    ) -> ConcurrencyCounter: ...

    def read_counter(
        self, workspace_id: str, counter_name: str
    ) -> ConcurrencyCounter | None: ...

    def scan_recovery(
        self, workspace_id: str
    ) -> tuple[CoordinationRecoveryRecord, ...]: ...


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CoordinationStoreError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CoordinationStoreError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise CoordinationStoreError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise CoordinationStoreError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise CoordinationStoreError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise CoordinationStoreError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise CoordinationStoreError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CoordinationStoreError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CoordinationStoreError(f"{field} must be a non-negative integer")
    return value


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field)


def _sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Sequence):
        raise CoordinationStoreError(f"{field} must be a sequence")
    return cast(Sequence[object], value)


def _coerce_trial_state(value: object) -> TrialState:
    if isinstance(value, TrialState):
        return value
    if not isinstance(value, str):
        raise CoordinationStoreError("state must be a string")
    try:
        return TrialState(value)
    except ValueError as exc:
        raise CoordinationStoreError(f"invalid trial state {value!r}") from exc


__all__ = [
    "CoordinationStoreError",
    "TrialState",
    "WorkspaceIdentity",
    "SweepIdentity",
    "TrialReference",
    "TrialLeaseRecord",
    "ResourceLeaseRecord",
    "CoordinationRecoveryRecord",
    "ConcurrencyCounter",
    "WorkspaceCoordinationStore",
]
