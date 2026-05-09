"""Workspace and sweep coordination contracts for cross-run facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .capabilities import BackendCapabilitySet
from .read_models import BackendRevision, LeaseRecord, LifecycleReason, RecoveryRecord
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


@dataclass(frozen=True, slots=True)
class SweepIdentity:
    sweep_id: str
    workspace_id: str
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sweep_id", _non_empty_string(self.sweep_id, "sweep_id"))
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


@dataclass(frozen=True, slots=True)
class TrialReference:
    trial_id: str
    sweep_id: str
    run_uri: str | None
    state: TrialState
    revision: BackendRevision
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trial_id", _non_empty_string(self.trial_id, "trial_id"))
        object.__setattr__(self, "sweep_id", _non_empty_string(self.sweep_id, "sweep_id"))
        if self.run_uri is not None:
            object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
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


@dataclass(frozen=True, slots=True)
class ResourceLeaseRecord:
    resource_key: str
    lease: LeaseRecord
    amount: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_key", _non_empty_string(self.resource_key, "resource_key")
        )
        if not isinstance(self.lease, LeaseRecord):
            raise CoordinationStoreError("lease must be a LeaseRecord")
        if isinstance(self.amount, bool) or not isinstance(self.amount, int) or self.amount <= 0:
            raise CoordinationStoreError("amount must be a positive integer")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "resource_key": self.resource_key,
            "lease": self.lease.to_dict(),
            "amount": self.amount,
        }


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
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 0:
            raise CoordinationStoreError("value must be a non-negative integer")
        if self.limit is not None and (
            isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0
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


@runtime_checkable
class WorkspaceCoordinationStore(Protocol):
    """Cross-run coordination contract for workspaces and sweeps."""

    def capabilities(self) -> BackendCapabilitySet: ...

    def check_schema(self) -> AuthoritySchemaCheck: ...

    def create_workspace(
        self, identity: WorkspaceIdentity
    ) -> BackendRevision: ...

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
    ) -> LeaseRecord: ...

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

    def scan_recovery(self, workspace_id: str) -> tuple[RecoveryRecord, ...]: ...


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CoordinationStoreError(f"{field} must be a non-empty string")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise CoordinationStoreError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise CoordinationStoreError(f"{field} must be a mapping")
    return normalized


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
    "ResourceLeaseRecord",
    "ConcurrencyCounter",
    "WorkspaceCoordinationStore",
]
