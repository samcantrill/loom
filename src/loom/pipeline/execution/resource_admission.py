"""Scheduler-ready resource admission helpers."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.pipeline.resources import ResourceRequest
from loom.pipeline.stores import (
    ConcurrencyCounter,
    LifecycleReason,
    ResourceLeaseRecord,
    CoordinationFailureKind,
    CoordinationStoreError,
    WorkspaceCoordinationStore,
)
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .errors import PipelineExecutionError


DEFAULT_RESOURCE_LEASE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_RESOURCE_ADMISSION_POLL_SECONDS = 1.0


class ResourceAdmissionStatus(StrEnum):
    """Outcome class for a stage resource admission decision."""

    ADMITTED = "admitted"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class ResourceLimitReconciliationStatus(StrEnum):
    """Machine-readable resource-limit reconciliation outcomes."""

    SUCCESS = "success"
    MISMATCH = "mismatch"
    MISSING_LIMIT = "missing_limit"
    UNAVAILABLE_AUTHORITY = "unavailable_authority"


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
        for field_name, value in {
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "workspace_id": self.workspace_id,
            "owner_id": self.owner_id,
        }.items():
            if not isinstance(value, str) or not value:
                raise ResourceAdmissionError(
                    f"{field_name} must be a non-empty string",
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
    reason_code: str | None = None
    failure_kind: CoordinationFailureKind | None = None
    reason_context: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ResourceAdmissionStatus(self.status))
        object.__setattr__(self, "leases", tuple(self.leases))
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str) or not self.reason_code
        ):
            raise ResourceAdmissionError(
                "reason_code must be a non-empty string",
                code="resource_admission.invalid_decision",
            )
        if self.failure_kind is not None:
            object.__setattr__(
                self, "failure_kind", CoordinationFailureKind(self.failure_kind)
            )
        object.__setattr__(
            self,
            "reason_context",
            _plain_mapping(self.reason_context, "reason_context"),
        )

    @property
    def admitted(self) -> bool:
        return self.status is ResourceAdmissionStatus.ADMITTED

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "status": self.status.value,
            "request": self.request.to_dict(),
            "leases": [lease.to_dict() for lease in self.leases],
            "message": self.message,
            "reason_code": self.reason_code,
            "failure_kind": None
            if self.failure_kind is None
            else self.failure_kind.value,
            "reason_context": dict(self.reason_context),
        }


@dataclass(frozen=True, slots=True)
class ResourceLimitReconciliationResult:
    """Read-only comparison of one desired resource limit against authority."""

    status: ResourceLimitReconciliationStatus
    workspace_id: str
    resource_key: str
    desired_limit: int
    actual_limit: int | None = None
    active: int | None = None
    reason_code: str | None = None
    message: str | None = None
    reason_context: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            ResourceLimitReconciliationStatus(self.status),
        )
        for field_name, value in {
            "workspace_id": self.workspace_id,
            "resource_key": self.resource_key,
        }.items():
            if not isinstance(value, str) or not value:
                raise ResourceAdmissionError(
                    f"{field_name} must be a non-empty string",
                    code="resource_limit_reconciliation.invalid_request",
                )
        object.__setattr__(
            self, "desired_limit", _positive_int(self.desired_limit, "desired_limit")
        )
        if self.actual_limit is not None:
            object.__setattr__(
                self, "actual_limit", _positive_int(self.actual_limit, "actual_limit")
            )
        if self.active is not None:
            object.__setattr__(self, "active", _non_negative_int(self.active, "active"))
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str) or not self.reason_code
        ):
            raise ResourceAdmissionError(
                "reason_code must be a non-empty string",
                code="resource_limit_reconciliation.invalid_result",
            )
        object.__setattr__(
            self,
            "reason_context",
            _plain_mapping(self.reason_context, "reason_context"),
        )

    @property
    def ok(self) -> bool:
        return self.status is ResourceLimitReconciliationStatus.SUCCESS

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "status": self.status.value,
            "workspace_id": self.workspace_id,
            "resource_key": self.resource_key,
            "desired_limit": self.desired_limit,
            "actual_limit": self.actual_limit,
            "active": self.active,
            "reason_code": self.reason_code,
            "message": self.message,
            "reason_context": dict(self.reason_context),
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


def reconcile_resource_limits(
    store: WorkspaceCoordinationStore,
    workspace_id: str,
    desired_limits: Mapping[str, int],
) -> tuple[ResourceLimitReconciliationResult, ...]:
    """Compare desired finite resource limits against authority without mutation."""

    if not isinstance(workspace_id, str) or not workspace_id:
        raise ResourceAdmissionError(
            "workspace_id must be a non-empty string",
            code="resource_limit_reconciliation.invalid_request",
        )
    if not isinstance(desired_limits, Mapping):
        raise ResourceAdmissionError(
            "desired_limits must be a mapping",
            code="resource_limit_reconciliation.invalid_request",
        )
    normalized = tuple(
        (
            _non_empty_string(resource_key, "resource_key"),
            _positive_int(limit, "desired_limit"),
        )
        for resource_key, limit in desired_limits.items()
    )
    results: list[ResourceLimitReconciliationResult] = []
    for resource_key, desired_limit in normalized:
        try:
            counter = store.read_resource_limit(workspace_id, resource_key)
        except Exception as exc:
            results.append(
                ResourceLimitReconciliationResult(
                    status=ResourceLimitReconciliationStatus.UNAVAILABLE_AUTHORITY,
                    workspace_id=workspace_id,
                    resource_key=resource_key,
                    desired_limit=desired_limit,
                    reason_code="resource_limit_reconciliation.unavailable_authority",
                    message=str(exc),
                    reason_context={"exception_type": type(exc).__name__},
                )
            )
            continue
        results.append(
            _resource_limit_reconciliation_result(
                workspace_id=workspace_id,
                resource_key=resource_key,
                desired_limit=desired_limit,
                counter=counter,
            )
        )
    return tuple(results)


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
            compensation_error = _release_partial(store, request, acquired)
            failure_kind = _admission_failure_kind(last_error)
            if compensation_error is not None:
                last_error = compensation_error
                failure_kind = _admission_failure_kind(compensation_error)
                if failure_kind is CoordinationFailureKind.CAPACITY:
                    failure_kind = CoordinationFailureKind.INTERNAL
                return ResourceAdmissionDecision(
                    status=ResourceAdmissionStatus.REJECTED,
                    request=request,
                    message=str(last_error),
                    reason_code=_admission_reason_code(last_error, failure_kind),
                    failure_kind=failure_kind,
                    reason_context=_admission_reason_context(
                        request, last_error, waited=request.waits
                    ),
                )
            if not request.waits or monotonic() >= deadline:
                return ResourceAdmissionDecision(
                    status=ResourceAdmissionStatus.BLOCKED
                    if request.waits
                    else ResourceAdmissionStatus.REJECTED,
                    request=request,
                    message=str(last_error),
                    reason_code=_admission_reason_code(last_error, failure_kind),
                    failure_kind=failure_kind,
                    reason_context=_admission_reason_context(
                        request,
                        last_error,
                        waited=request.waits,
                    ),
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
) -> Exception | None:
    reason = LifecycleReason(
        code="resource_admission_partial_release",
        message=f"released partial resource admission for stage {request.stage_name}",
    )
    first_error: Exception | None = None
    for lease in leases:
        try:
            store.release_lease(
                lease.lease.lease_id,
                owner_id=lease.lease.owner_id,
                fencing_token=lease.lease.fencing_token,
                reason=reason,
            )
        except Exception as exc:  # noqa: BLE001
            if first_error is None:
                first_error = exc
    return first_error


def _resource_limit_reconciliation_result(
    *,
    workspace_id: str,
    resource_key: str,
    desired_limit: int,
    counter: ConcurrencyCounter | None,
) -> ResourceLimitReconciliationResult:
    if counter is None or counter.limit is None:
        return ResourceLimitReconciliationResult(
            status=ResourceLimitReconciliationStatus.MISSING_LIMIT,
            workspace_id=workspace_id,
            resource_key=resource_key,
            desired_limit=desired_limit,
            active=None if counter is None else counter.value,
            reason_code="resource_limit_reconciliation.missing_limit",
            message="authority resource limit is not configured",
        )
    if counter.limit != desired_limit:
        return ResourceLimitReconciliationResult(
            status=ResourceLimitReconciliationStatus.MISMATCH,
            workspace_id=workspace_id,
            resource_key=resource_key,
            desired_limit=desired_limit,
            actual_limit=counter.limit,
            active=counter.value,
            reason_code="resource_limit_reconciliation.mismatch",
            message="authority resource limit does not match desired limit",
        )
    return ResourceLimitReconciliationResult(
        status=ResourceLimitReconciliationStatus.SUCCESS,
        workspace_id=workspace_id,
        resource_key=resource_key,
        desired_limit=desired_limit,
        actual_limit=counter.limit,
        active=counter.value,
        reason_code="resource_limit_reconciliation.success",
    )


def _admission_reason_code(
    exc: Exception, kind: CoordinationFailureKind | None = None
) -> str:
    if isinstance(exc, ResourceAdmissionError):
        return exc.code
    kind = kind or _admission_failure_kind(exc)
    if kind is CoordinationFailureKind.CAPACITY:
        return "resource_admission.capacity_unavailable"
    if kind is CoordinationFailureKind.INVALID_OR_UNSUPPORTED:
        return "resource_admission.unsupported_resource"
    if kind is CoordinationFailureKind.UNAVAILABLE:
        return "resource_admission.unavailable_authority"
    if kind is CoordinationFailureKind.OWNERSHIP_LOST:
        return "resource_admission.ownership_lost"
    return "resource_admission.acquisition_failed"


def _admission_failure_kind(exc: Exception) -> CoordinationFailureKind:
    if isinstance(exc, CoordinationStoreError):
        return exc.kind
    return CoordinationFailureKind.INTERNAL


def _admission_reason_context(
    request: ResourceAdmissionRequest,
    exc: Exception,
    *,
    waited: bool,
) -> dict[str, PlainData]:
    return {
        "exception_type": type(exc).__name__,
        "waited": waited,
        "wait_timeout_seconds": request.wait_timeout_seconds,
        "resources": [resource.to_dict() for resource in request.resources],
    }


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResourceAdmissionError(
            f"{field} must be a non-empty string",
            code="resource_limit_reconciliation.invalid_request",
        )
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResourceAdmissionError(
            f"{field} must be a positive integer",
            code="resource_limit_reconciliation.invalid_request",
        )
    return value


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResourceAdmissionError(
            f"{field} must be a non-negative integer",
            code="resource_limit_reconciliation.invalid_result",
        )
    return value


def _plain_mapping(value: Mapping[str, PlainData], field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(dict(value), path=field)
    except (PlainDataError, ValueError) as exc:
        raise ResourceAdmissionError(
            f"{field} must be plain-data-compatible: {exc}",
            code="resource_admission.invalid_decision",
        ) from exc
    if not isinstance(normalized, Mapping):
        raise ResourceAdmissionError(
            f"{field} must be a mapping",
            code="resource_admission.invalid_decision",
        )
    return cast(Mapping[str, PlainData], normalized)


__all__ = [
    "DEFAULT_RESOURCE_ADMISSION_POLL_SECONDS",
    "DEFAULT_RESOURCE_LEASE_TTL_SECONDS",
    "ResourceAdmissionDecision",
    "ResourceAdmissionError",
    "ResourceAdmissionRequest",
    "ResourceAdmissionStatus",
    "ResourceLimitReconciliationResult",
    "ResourceLimitReconciliationStatus",
    "ResourceLeaseRequest",
    "acquire_resource_admission",
    "reconcile_resource_limits",
    "release_resource_admission",
    "resource_requests_from_runtime",
]
