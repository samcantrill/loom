"""Project-owned pattern for an indivisible placement over physical members.

This is intentionally an example, not a Loom provider.  A project that needs a
pair or another topology-specific placement keeps that meaning here while
leasing the same member keys used by its individual allocator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from loom.pipeline.stores import (
    CoordinationFailureKind,
    CoordinationStoreError,
    LifecycleReason,
    ResourceLeaseRecord,
    WorkspaceCoordinationStore,
)
from loom.queue.assignments import (
    LaunchEnvironmentBindings,
    ResourceAssignment,
    ResourceAssignmentDecision,
    ResourceAssignmentDisposition,
    ResourceAssignmentRequest,
    StaticSlot,
)
from loom.timestamps import parse_timestamp, utc_timestamp


@dataclass(frozen=True, slots=True)
class _BundleToken:
    members: tuple[StaticSlot, ...]
    lease_ttl_seconds: int


class PairedMemberAssignmentProvider:
    """Lease every physical member for one project-defined indivisible bundle."""

    provider_name = "example-paired-members"

    def __init__(
        self,
        store: WorkspaceCoordinationStore,
        *,
        workspace_id: str,
        resource_name: str,
        members: tuple[StaticSlot, ...],
        environment_name: str = "LOOM_ASSIGNED_ACCELERATORS",
        separator: str = ",",
    ) -> None:
        if (
            not workspace_id
            or not resource_name
            or not environment_name
            or not separator
        ):
            raise ValueError("bundle provider requires non-empty names and separator")
        if len(members) < 2:
            raise ValueError("an indivisible bundle requires at least two members")
        if len({member.slot_id for member in members}) != len(members) or len(
            {member.coordination_key for member in members}
        ) != len(members):
            raise ValueError("bundle members must have unique physical identities")
        if any(separator in member.value or "\0" in member.value for member in members):
            raise ValueError(
                "bundle member values must be safe for the environment binding"
            )
        self._store = store
        self._workspace_id = workspace_id
        self._resource_name = resource_name
        self._members = members
        self._environment_name = environment_name
        self._separator = separator

    def acquire(self, request: ResourceAssignmentRequest) -> ResourceAssignmentDecision:
        if dict(request.resources) != {self._resource_name: 1}:
            return ResourceAssignmentDecision(
                disposition=ResourceAssignmentDisposition.FAILED,
                reason_code="resource_assignment.unsupported_bundle_request",
            )
        acquired: list[tuple[StaticSlot, ResourceLeaseRecord]] = []
        for member in self._members:
            try:
                lease = self._store.acquire_resource_lease(
                    self._workspace_id,
                    member.coordination_key,
                    owner_id=f"{request.owner_id}:{request.session_id}",
                    amount=1,
                    lease_ttl_seconds=request.lease_ttl_seconds,
                )
            except CoordinationStoreError as exc:
                self._release_partial(acquired)
                if exc.kind is CoordinationFailureKind.CAPACITY:
                    return ResourceAssignmentDecision(
                        disposition=ResourceAssignmentDisposition.DEFERRED,
                        reason_code="resource_assignment.capacity_unavailable",
                    )
                return ResourceAssignmentDecision(
                    disposition=ResourceAssignmentDisposition.FAILED,
                    reason_code=f"resource_assignment.{exc.kind.value}",
                )
            acquired.append((member, lease))
        return ResourceAssignmentDecision(
            disposition=ResourceAssignmentDisposition.ASSIGNED,
            assignment=self._assignment(
                tuple(acquired),
                _BundleToken(self._members, request.lease_ttl_seconds),
            ),
        )

    def renew(self, assignment: ResourceAssignment) -> ResourceAssignment:
        token = assignment.live_token
        if not isinstance(token, _BundleToken):
            raise ValueError("bundle provider received an unknown live assignment")
        renewed = tuple(
            self._store.renew_lease(
                lease.lease.lease_id,
                owner_id=lease.lease.owner_id,
                fencing_token=lease.lease.fencing_token,
                lease_ttl_seconds=token.lease_ttl_seconds,
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
        return self._assignment(tuple(zip(token.members, leases, strict=True)), token)

    def release(
        self, assignment: ResourceAssignment, *, reason: LifecycleReason
    ) -> None:
        first_error: Exception | None = None
        for lease in reversed(assignment.leases):
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

    def _assignment(
        self,
        acquired: tuple[tuple[StaticSlot, ResourceLeaseRecord], ...],
        token: _BundleToken,
    ) -> ResourceAssignment:
        leases = tuple(lease for _member, lease in acquired)
        return ResourceAssignment(
            provider_name=self.provider_name,
            live_token=token,
            leases=leases,
            bindings=LaunchEnvironmentBindings(
                {
                    self._environment_name: self._separator.join(
                        member.value for member, _ in acquired
                    )
                }
            ),
            safe_evidence={
                "slots": [
                    {
                        "resource_name": member.resource_name,
                        "slot_id": member.slot_id,
                        "lease_id": lease.lease.lease_id,
                        "expires_at": lease.lease.expires_at,
                        **({"label": member.label} if member.label is not None else {}),
                    }
                    for member, lease in acquired
                ]
            },
            next_maintenance_at=_maintenance_at(leases, token.lease_ttl_seconds),
        )

    def _release_partial(
        self, acquired: list[tuple[StaticSlot, ResourceLeaseRecord]]
    ) -> None:
        reason = LifecycleReason(
            code="bundle_partial_rollback",
            message="released partially acquired bundle members",
        )
        for _member, lease in reversed(acquired):
            self._store.release_lease(
                lease.lease.lease_id,
                owner_id=lease.lease.owner_id,
                fencing_token=lease.lease.fencing_token,
                reason=reason,
            )


def _maintenance_at(leases: tuple[ResourceLeaseRecord, ...], ttl: int) -> str:
    renewed_at = min(parse_timestamp(lease.lease.renewed_at) for lease in leases)
    return utc_timestamp(renewed_at + timedelta(seconds=ttl * 0.5))
