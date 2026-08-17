"""Concrete resource assignment for managed local queue dispatches.

The records in this module deliberately keep provider live state in memory.  A
queue handle receives only the provider supplied, plain-data evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable

from loom.pipeline.stores import (
    CoordinationFailureKind,
    CoordinationStoreError,
    LifecycleReason,
    ResourceLeaseRecord,
    WorkspaceCoordinationStore,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_timestamp

from .errors import QueueServiceError


class ResourceAssignmentDisposition(StrEnum):
    """Stable outcomes from a concrete resource provider."""

    ASSIGNED = "assigned"
    DEFERRED = "deferred"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LaunchEnvironmentBindings:
    """Environment values that a successful assignment asks the adapter to add."""

    environment: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[str, str] = {}
        for name, value in self.environment.items():
            if not isinstance(name, str) or not name:
                raise QueueServiceError(
                    "assignment environment names must be non-empty strings"
                )
            if not isinstance(value, str):
                raise QueueServiceError("assignment environment values must be strings")
            normalized[name] = value
        object.__setattr__(self, "environment", normalized)


@dataclass(frozen=True, slots=True)
class ResourceAssignmentRequest:
    """The narrow information a provider needs to acquire concrete slots."""

    consumer_id: str
    pool_name: str
    owner_id: str
    session_id: str
    resources: Mapping[str, int]
    admitted_lease_ids: tuple[str, ...]
    lease_ttl_seconds: int

    def __post_init__(self) -> None:
        for field_name in ("consumer_id", "pool_name", "owner_id", "session_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise QueueServiceError(
                    f"assignment {field_name} must be a non-empty string"
                )
        resources: dict[str, int] = {}
        for resource_name, amount in self.resources.items():
            if not isinstance(resource_name, str) or not resource_name:
                raise QueueServiceError(
                    "assignment resource names must be non-empty strings"
                )
            if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                raise QueueServiceError(
                    "assignment resource amounts must be positive integers"
                )
            resources[resource_name] = amount
        if len(set(self.admitted_lease_ids)) != len(self.admitted_lease_ids) or any(
            not isinstance(lease_id, str) or not lease_id
            for lease_id in self.admitted_lease_ids
        ):
            raise QueueServiceError(
                "assignment admitted_lease_ids must be unique non-empty strings"
            )
        if (
            isinstance(self.lease_ttl_seconds, bool)
            or not isinstance(self.lease_ttl_seconds, int)
            or self.lease_ttl_seconds <= 0
        ):
            raise QueueServiceError(
                "assignment lease_ttl_seconds must be a positive integer"
            )
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "admitted_lease_ids", tuple(self.admitted_lease_ids))


@dataclass(frozen=True, slots=True)
class ResourceAssignment:
    """A live assignment and its separately safe persistence projection."""

    provider_name: str
    live_token: object
    leases: tuple[ResourceLeaseRecord, ...]
    bindings: LaunchEnvironmentBindings = field(
        default_factory=LaunchEnvironmentBindings
    )
    safe_evidence: Mapping[str, PlainData] = field(default_factory=dict)
    next_maintenance_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider_name, str) or not self.provider_name:
            raise QueueServiceError(
                "assignment provider_name must be a non-empty string"
            )
        if not isinstance(self.bindings, LaunchEnvironmentBindings):
            raise QueueServiceError(
                "assignment bindings must be LaunchEnvironmentBindings"
            )
        object.__setattr__(self, "leases", tuple(self.leases))
        if not all(isinstance(lease, ResourceLeaseRecord) for lease in self.leases):
            raise QueueServiceError(
                "assignment leases must be ResourceLeaseRecord values"
            )
        object.__setattr__(
            self, "safe_evidence", _plain_mapping(self.safe_evidence, "safe_evidence")
        )
        if self.next_maintenance_at is not None:
            try:
                parse_timestamp(self.next_maintenance_at)
            except Exception as exc:  # noqa: BLE001
                raise QueueServiceError(
                    "assignment next_maintenance_at must be a UTC timestamp"
                ) from exc


@dataclass(frozen=True, slots=True)
class ResourceAssignmentDecision:
    """Discriminated provider response; only this response is serializable."""

    disposition: ResourceAssignmentDisposition | str
    assignment: ResourceAssignment | None = None
    reason_code: str | None = None
    reason_context: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        disposition = ResourceAssignmentDisposition(self.disposition)
        object.__setattr__(self, "disposition", disposition)
        if disposition is ResourceAssignmentDisposition.ASSIGNED:
            if not isinstance(self.assignment, ResourceAssignment):
                raise QueueServiceError(
                    "assigned resource decisions require an assignment"
                )
            if self.reason_code is not None:
                raise QueueServiceError(
                    "assigned resource decisions forbid reason_code"
                )
        elif self.assignment is not None:
            raise QueueServiceError(
                "deferred and failed resource decisions forbid assignments"
            )
        if disposition is not ResourceAssignmentDisposition.ASSIGNED and (
            not isinstance(self.reason_code, str) or not self.reason_code
        ):
            raise QueueServiceError(
                "non-assigned resource decisions require reason_code"
            )
        object.__setattr__(
            self,
            "reason_context",
            _plain_mapping(self.reason_context, "reason_context"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        """Return the plain-data boundary without provider private live tokens."""

        return {
            "disposition": ResourceAssignmentDisposition(self.disposition).value,
            "assignment": None
            if self.assignment is None
            else {
                "provider_name": self.assignment.provider_name,
                "safe_evidence": thaw_plain_data(
                    self.assignment.safe_evidence, path="safe_evidence"
                ),
                "next_maintenance_at": self.assignment.next_maintenance_at,
            },
            "reason_code": self.reason_code,
            "reason_context": thaw_plain_data(
                self.reason_context, path="reason_context"
            ),
        }


@runtime_checkable
class ResourceAssignmentProvider(Protocol):
    """Structural lifecycle provider for concrete local resource assignments."""

    provider_name: str

    def acquire(
        self, request: ResourceAssignmentRequest
    ) -> ResourceAssignmentDecision: ...

    def renew(self, assignment: ResourceAssignment) -> ResourceAssignment: ...

    def release(
        self, assignment: ResourceAssignment, *, reason: LifecycleReason
    ) -> None: ...


class NoOpResourceAssignmentProvider:
    """Compatibility provider for CPU-only and existing local configurations."""

    provider_name = "no-op"

    def acquire(self, request: ResourceAssignmentRequest) -> ResourceAssignmentDecision:
        return ResourceAssignmentDecision(
            disposition=ResourceAssignmentDisposition.ASSIGNED,
            assignment=ResourceAssignment(
                provider_name=self.provider_name, live_token=None, leases=()
            ),
        )

    def renew(self, assignment: ResourceAssignment) -> ResourceAssignment:
        return assignment

    def release(
        self, assignment: ResourceAssignment, *, reason: LifecycleReason
    ) -> None:
        return None


@dataclass(frozen=True, slots=True)
class StaticSlot:
    """One authored concrete slot.  Kept queue-local rather than durable."""

    resource_name: str
    slot_id: str
    coordination_key: str
    value: str
    label: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("resource_name", "slot_id", "coordination_key", "value"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise QueueServiceError(
                    f"static slot {field_name} must be a non-empty string"
                )
        if self.label is not None and (
            not isinstance(self.label, str) or not self.label
        ):
            raise QueueServiceError(
                "static slot label must be a non-empty string or None"
            )


@dataclass(frozen=True, slots=True)
class EnvironmentListBinding:
    resource_name: str
    name: str
    separator: str


class StaticSlotAssignmentProvider:
    """Acquire authored static slots in order using one authority lease per slot."""

    provider_name = "static-slots"

    def __init__(
        self,
        store: WorkspaceCoordinationStore,
        *,
        workspace_id: str,
        slots: tuple[StaticSlot, ...],
        bindings: Mapping[str, EnvironmentListBinding] | None = None,
    ) -> None:
        self._store = store
        self._workspace_id = _required_string(workspace_id, "workspace_id")
        self._slots = tuple(slots)
        self._bindings = dict(bindings or {})
        for binding in self._bindings.values():
            if not isinstance(binding, EnvironmentListBinding):
                raise QueueServiceError(
                    "static slot bindings must be EnvironmentListBinding"
                )

    def acquire(self, request: ResourceAssignmentRequest) -> ResourceAssignmentDecision:
        selected: list[tuple[StaticSlot, ResourceLeaseRecord]] = []
        for resource_name, amount in request.resources.items():
            candidates = [
                slot for slot in self._slots if slot.resource_name == resource_name
            ]
            if not candidates:
                continue
            if amount > len(candidates):
                self._release_partial(selected, "static_slot_request_invalid")
                return ResourceAssignmentDecision(
                    disposition=ResourceAssignmentDisposition.FAILED,
                    reason_code="resource_assignment.request_exceeds_inventory",
                    reason_context={
                        "resource_name": resource_name,
                        "requested": amount,
                        "available": len(candidates),
                    },
                )
            acquired_for_resource = 0
            for slot in candidates:
                if acquired_for_resource == amount:
                    break
                try:
                    lease = self._store.acquire_resource_lease(
                        self._workspace_id,
                        slot.coordination_key,
                        owner_id=_assignment_owner(request),
                        amount=1,
                        lease_ttl_seconds=request.lease_ttl_seconds,
                    )
                except CoordinationStoreError as exc:
                    if exc.kind is CoordinationFailureKind.CAPACITY:
                        continue
                    self._release_partial(selected, "static_slot_acquire_failed")
                    return ResourceAssignmentDecision(
                        disposition=ResourceAssignmentDisposition.FAILED,
                        reason_code=f"resource_assignment.{exc.kind.value}",
                        reason_context={"resource_name": resource_name},
                    )
                except Exception as exc:  # noqa: BLE001
                    self._release_partial(selected, "static_slot_acquire_failed")
                    return ResourceAssignmentDecision(
                        disposition=ResourceAssignmentDisposition.FAILED,
                        reason_code="resource_assignment.internal",
                        reason_context={"exception_type": type(exc).__name__},
                    )
                selected.append((slot, lease))
                acquired_for_resource += 1
            if acquired_for_resource != amount:
                self._release_partial(selected, "static_slot_capacity_deferred")
                return ResourceAssignmentDecision(
                    disposition=ResourceAssignmentDisposition.DEFERRED,
                    reason_code="resource_assignment.capacity_unavailable",
                    reason_context={"resource_name": resource_name},
                )
        leases = tuple(lease for _slot, lease in selected)
        values: dict[str, list[str]] = {}
        for slot, _lease in selected:
            binding = self._bindings.get(slot.resource_name)
            if binding is not None:
                values.setdefault(binding.name, []).append(slot.value)
        environment = {
            name: self._bindings_for_name(name).separator.join(value)
            for name, value in values.items()
        }
        next_maintenance_at = _lease_maintenance_at(leases, request.lease_ttl_seconds)
        return ResourceAssignmentDecision(
            disposition=ResourceAssignmentDisposition.ASSIGNED,
            assignment=ResourceAssignment(
                provider_name=self.provider_name,
                live_token=tuple(slot.slot_id for slot, _lease in selected),
                leases=leases,
                bindings=LaunchEnvironmentBindings(environment=environment),
                safe_evidence={
                    "slots": [
                        {
                            "resource_name": slot.resource_name,
                            "slot_id": slot.slot_id,
                            "lease_id": lease.lease.lease_id,
                            "expires_at": lease.lease.expires_at,
                            **({"label": slot.label} if slot.label is not None else {}),
                        }
                        for slot, lease in selected
                    ]
                },
                next_maintenance_at=next_maintenance_at,
            ),
        )

    def renew(self, assignment: ResourceAssignment) -> ResourceAssignment:
        renewed = tuple(
            self._store.renew_lease(
                lease.lease.lease_id,
                owner_id=lease.lease.owner_id,
                fencing_token=lease.lease.fencing_token,
                lease_ttl_seconds=_ttl_from_assignment(assignment),
            )
            for lease in assignment.leases
        )
        leases = tuple(
            ResourceLeaseRecord(
                workspace_id=old.workspace_id,
                resource_key=old.resource_key,
                lease=new,
                amount=old.amount,
            )
            for old, new in zip(assignment.leases, renewed, strict=True)
        )
        safe_evidence = thaw_plain_data(assignment.safe_evidence, path="safe_evidence")
        evidence_slots = (
            safe_evidence.get("slots", []) if isinstance(safe_evidence, Mapping) else []
        )
        if isinstance(evidence_slots, list):
            for evidence, lease in zip(evidence_slots, leases, strict=True):
                if isinstance(evidence, dict):
                    evidence["lease_id"] = lease.lease.lease_id
                    evidence["expires_at"] = lease.lease.expires_at
        return ResourceAssignment(
            provider_name=assignment.provider_name,
            live_token=assignment.live_token,
            leases=leases,
            bindings=assignment.bindings,
            safe_evidence={"slots": evidence_slots},
            next_maintenance_at=_lease_maintenance_at(
                leases, _ttl_from_assignment(assignment)
            ),
        )

    def release(
        self, assignment: ResourceAssignment, *, reason: LifecycleReason
    ) -> None:
        first_error: Exception | None = None
        for lease in assignment.leases:
            try:
                self._store.release_lease(
                    lease.lease.lease_id,
                    owner_id=lease.lease.owner_id,
                    fencing_token=lease.lease.fencing_token,
                    reason=reason,
                )
            except Exception as exc:  # noqa: BLE001
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def _release_partial(
        self, selected: list[tuple[StaticSlot, ResourceLeaseRecord]], code: str
    ) -> None:
        reason = LifecycleReason(
            code=code, message="released partial static slot assignment"
        )
        first_error: Exception | None = None
        for _slot, lease in reversed(selected):
            try:
                self._store.release_lease(
                    lease.lease.lease_id,
                    owner_id=lease.lease.owner_id,
                    fencing_token=lease.lease.fencing_token,
                    reason=reason,
                )
            except Exception as exc:  # noqa: BLE001
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def _bindings_for_name(self, name: str) -> EnvironmentListBinding:
        return next(
            binding for binding in self._bindings.values() if binding.name == name
        )


def _assignment_owner(request: ResourceAssignmentRequest) -> str:
    return f"{request.owner_id}:{request.session_id}"


def _ttl_from_assignment(assignment: ResourceAssignment) -> int:
    # The adapter owns scheduling and requests renewal with its configured TTL.
    # Static providers receive replacement assignments only from that adapter.
    # Lease expiry is enough to preserve the matching duration here.
    if not assignment.leases:
        return 1
    lease = assignment.leases[0].lease
    return max(
        1,
        round(
            (
                parse_timestamp(lease.expires_at) - parse_timestamp(lease.renewed_at)
            ).total_seconds()
        ),
    )


def _lease_maintenance_at(
    leases: tuple[ResourceLeaseRecord, ...], ttl: int
) -> str | None:
    if not leases:
        return None
    renewed_at = min(parse_timestamp(lease.lease.renewed_at) for lease in leases)
    return utc_timestamp(renewed_at + timedelta(seconds=ttl * 0.5))


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise QueueServiceError(f"{field} must be a non-empty string")
    return value


def _plain_mapping(
    value: Mapping[str, PlainData], path: str
) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise QueueServiceError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise QueueServiceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


__all__ = [
    "EnvironmentListBinding",
    "LaunchEnvironmentBindings",
    "NoOpResourceAssignmentProvider",
    "ResourceAssignment",
    "ResourceAssignmentDecision",
    "ResourceAssignmentDisposition",
    "ResourceAssignmentProvider",
    "ResourceAssignmentRequest",
    "StaticSlot",
    "StaticSlotAssignmentProvider",
]
