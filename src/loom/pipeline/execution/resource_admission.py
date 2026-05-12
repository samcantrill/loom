"""Scheduler-ready resource admission helpers."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from loom.pipeline.resources import ResourceRequest
from loom.pipeline.stores import (
    LifecycleReason,
    ResourceLeaseRecord,
    WorkspaceCoordinationStore,
)
from loom.serialization import PlainData

from .errors import PipelineExecutionError


DEFAULT_RESOURCE_LEASE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_RESOURCE_ADMISSION_POLL_SECONDS = 1.0


class ResourceAdmissionStatus(StrEnum):
    """Outcome class for a stage resource admission decision."""

    ADMITTED = "admitted"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class ResourceAdmissionError(PipelineExecutionError):
    """Raised when stage resource admission cannot acquire required capacity."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        context: Mapping[str, PlainData] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "message": str(self),
            "code": self.code,
            "context": dict(self.context),
        }


@dataclass(frozen=True, slots=True)
class ResourceLeaseRequest:
    """One named integer resource amount needed by a stage."""

    resource_key: str
    amount: int

    def __post_init__(self) -> None:
        if not isinstance(self.resource_key, str) or not self.resource_key:
            raise ResourceAdmissionError(
                "resource key must be a non-empty string",
                code="resource_admission.invalid_request",
            )
        if (
            isinstance(self.amount, bool)
            or not isinstance(self.amount, int)
            or self.amount <= 0
        ):
            raise ResourceAdmissionError(
                "resource amount must be a positive integer",
                code="resource_admission.invalid_request",
                context={"resource_key": self.resource_key},
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {"resource_key": self.resource_key, "amount": self.amount}


@dataclass(frozen=True, slots=True)
class ResourceAdmissionRequest:
    """Admission request for the resources needed before a stage can launch."""

    run_uri: str
    stage_name: str
    workspace_id: str
    owner_id: str
    resources: tuple[ResourceLeaseRequest, ...]
    lease_ttl_seconds: int = DEFAULT_RESOURCE_LEASE_TTL_SECONDS
    wait_timeout_seconds: float = 0.0
    poll_interval_seconds: float = DEFAULT_RESOURCE_ADMISSION_POLL_SECONDS

    def __post_init__(self) -> None:
        for field, value in {
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "workspace_id": self.workspace_id,
            "owner_id": self.owner_id,
        }.items():
            if not isinstance(value, str) or not value:
                raise ResourceAdmissionError(
                    f"{field} must be a non-empty string",
                    code="resource_admission.invalid_request",
                )
        if (
            isinstance(self.lease_ttl_seconds, bool)
            or not isinstance(self.lease_ttl_seconds, int)
            or self.lease_ttl_seconds <= 0
        ):
            raise ResourceAdmissionError(
                "lease_ttl_seconds must be a positive integer",
                code="resource_admission.invalid_request",
            )
        if (
            isinstance(self.wait_timeout_seconds, bool)
            or not isinstance(self.wait_timeout_seconds, int | float)
            or self.wait_timeout_seconds < 0
        ):
            raise ResourceAdmissionError(
                "wait_timeout_seconds must be non-negative",
                code="resource_admission.invalid_request",
            )
        if (
            isinstance(self.poll_interval_seconds, bool)
            or not isinstance(self.poll_interval_seconds, int | float)
            or self.poll_interval_seconds <= 0
        ):
            raise ResourceAdmissionError(
                "poll_interval_seconds must be positive",
                code="resource_admission.invalid_request",
            )
        object.__setattr__(self, "resources", tuple(self.resources))

    @property
    def waits(self) -> bool:
        return self.wait_timeout_seconds > 0

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "workspace_id": self.workspace_id,
            "owner_id": self.owner_id,
            "resources": [resource.to_dict() for resource in self.resources],
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "wait_timeout_seconds": self.wait_timeout_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
        }


@dataclass(frozen=True, slots=True)
class ResourceAdmissionDecision:
    """Result of one admission attempt."""

    status: ResourceAdmissionStatus
    request: ResourceAdmissionRequest
    leases: tuple[ResourceLeaseRecord, ...] = ()
    message: str | None = None

    @property
    def admitted(self) -> bool:
        return self.status is ResourceAdmissionStatus.ADMITTED

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "status": self.status.value,
            "request": self.request.to_dict(),
            "leases": [lease.to_dict() for lease in self.leases],
            "message": self.message,
        }


def resource_requests_from_runtime(
    resources: ResourceRequest,
) -> tuple[ResourceLeaseRequest, ...]:
    """Return positive integer resource lease requests from runtime resources."""

    requests: list[ResourceLeaseRequest] = []
    for key, entry in resources.entries.items():
        if entry.amount == 0:
            continue
        if not isinstance(entry.amount, int):
            raise ResourceAdmissionError(
                "resource admission requires integer resource amounts",
                code="resource_admission.non_integer_amount",
                context={"resource_key": key, "amount": entry.amount},
            )
        requests.append(ResourceLeaseRequest(resource_key=key, amount=entry.amount))
    return tuple(requests)


def acquire_resource_admission(
    store: WorkspaceCoordinationStore,
    request: ResourceAdmissionRequest,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ResourceAdmissionDecision:
    """Acquire all resource leases for a request or return a rejected decision."""

    if not request.resources:
        return ResourceAdmissionDecision(
            status=ResourceAdmissionStatus.ADMITTED,
            request=request,
        )
    deadline = monotonic() + request.wait_timeout_seconds
    last_error: Exception | None = None
    while True:
        acquired: list[ResourceLeaseRecord] = []
        try:
            for needed in request.resources:
                acquired.append(
                    store.acquire_resource_lease(
                        request.workspace_id,
                        needed.resource_key,
                        owner_id=request.owner_id,
                        amount=needed.amount,
                        lease_ttl_seconds=request.lease_ttl_seconds,
                    )
                )
            return ResourceAdmissionDecision(
                status=ResourceAdmissionStatus.ADMITTED,
                request=request,
                leases=tuple(acquired),
            )
        except Exception as exc:
            last_error = exc if isinstance(exc, Exception) else Exception(str(exc))
            _release_partial(store, request, acquired)
            if not request.waits or monotonic() >= deadline:
                return ResourceAdmissionDecision(
                    status=ResourceAdmissionStatus.BLOCKED
                    if request.waits
                    else ResourceAdmissionStatus.REJECTED,
                    request=request,
                    message=str(last_error),
                )
            sleep(min(request.poll_interval_seconds, max(0.0, deadline - monotonic())))


def release_resource_admission(
    store: WorkspaceCoordinationStore,
    decision: ResourceAdmissionDecision,
    *,
    reason: LifecycleReason | None = None,
) -> tuple[ResourceLeaseRecord, ...]:
    """Release all resource leases from an admitted decision."""

    released: list[ResourceLeaseRecord] = []
    for lease in decision.leases:
        store.release_lease(
            lease.lease.lease_id,
            owner_id=lease.lease.owner_id,
            fencing_token=lease.lease.fencing_token,
            reason=reason,
        )
        released.append(lease)
    return tuple(released)


def _release_partial(
    store: WorkspaceCoordinationStore,
    request: ResourceAdmissionRequest,
    leases: list[ResourceLeaseRecord],
) -> None:
    reason = LifecycleReason(
        code="resource_admission_partial_release",
        message=f"released partial resource admission for stage {request.stage_name}",
    )
    for lease in leases:
        try:
            store.release_lease(
                lease.lease.lease_id,
                owner_id=lease.lease.owner_id,
                fencing_token=lease.lease.fencing_token,
                reason=reason,
            )
        except Exception:
            continue


__all__ = [
    "DEFAULT_RESOURCE_ADMISSION_POLL_SECONDS",
    "DEFAULT_RESOURCE_LEASE_TTL_SECONDS",
    "ResourceAdmissionDecision",
    "ResourceAdmissionError",
    "ResourceAdmissionRequest",
    "ResourceAdmissionStatus",
    "ResourceLeaseRequest",
    "acquire_resource_admission",
    "release_resource_admission",
    "resource_requests_from_runtime",
]
