"""Capability admission records for authority-backed runtime requests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .capabilities import BackendCapability, BackendCapabilitySet, CapabilityScope
from .config import AuthorityConfig, AuthorityDeploymentProfile


class AuthorityAdmissionError(ValueError):
    """Raised when authority capability admission records are invalid."""


class RequiredAuthorityCapability(StrEnum):
    SERIAL_RUN = "serial_run"
    BOUNDED_PARALLEL_STAGES = "bounded_parallel_stages"
    SUBPROCESS_WORKER = "subprocess_worker"
    SLURM_LIVE_WORKER = "slurm_live_worker"
    DEFERRED_FINALIZATION_WORKER = "deferred_finalization_worker"
    MULTI_RUN_SUBMISSION = "multi_run_submission"
    SWEEP_COORDINATION = "sweep_coordination"
    SHARED_RESOURCE_COUNTER = "shared_resource_counter"
    READ_ONLY_INSPECTION = "read_only_inspection"


@dataclass(frozen=True, slots=True)
class CapabilityAdmissionError:
    code: str
    required: RequiredAuthorityCapability
    backend_name: str
    backend_kind: str
    deployment_profile: str
    message: str
    capability: BackendCapability | None = None
    scope: CapabilityScope | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _non_empty_string(self.code, "code"))
        object.__setattr__(
            self,
            "required",
            _enum(self.required, RequiredAuthorityCapability, "required"),
        )
        object.__setattr__(
            self, "backend_name", _non_empty_string(self.backend_name, "backend_name")
        )
        object.__setattr__(
            self, "backend_kind", _non_empty_string(self.backend_kind, "backend_kind")
        )
        object.__setattr__(
            self,
            "deployment_profile",
            _non_empty_string(self.deployment_profile, "deployment_profile"),
        )
        object.__setattr__(self, "message", _non_empty_string(self.message, "message"))
        if self.capability is not None:
            object.__setattr__(
                self,
                "capability",
                _enum(self.capability, BackendCapability, "capability"),
            )
        if self.scope is not None:
            object.__setattr__(
                self, "scope", _enum(self.scope, CapabilityScope, "scope")
            )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "required": self.required.value,
            "backend_name": self.backend_name,
            "backend_kind": self.backend_kind,
            "deployment_profile": self.deployment_profile,
            "message": self.message,
            "capability": None if self.capability is None else self.capability.value,
            "scope": None if self.scope is None else self.scope.value,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class CapabilityAdmissionResult:
    config: AuthorityConfig
    backend_name: str
    required: tuple[RequiredAuthorityCapability, ...]
    errors: tuple[CapabilityAdmissionError, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.config, AuthorityConfig):
            raise AuthorityAdmissionError("config must be an AuthorityConfig")
        object.__setattr__(
            self, "backend_name", _non_empty_string(self.backend_name, "backend_name")
        )
        object.__setattr__(
            self,
            "required",
            tuple(
                _enum(value, RequiredAuthorityCapability, "required")
                for value in self.required
            ),
        )
        errors = tuple(self.errors)
        if any(not isinstance(error, CapabilityAdmissionError) for error in errors):
            raise AuthorityAdmissionError(
                "errors must contain CapabilityAdmissionError values"
            )
        object.__setattr__(self, "errors", errors)

    @property
    def supported(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "supported": self.supported,
            "backend_name": self.backend_name,
            "config": self.config.redacted_dict(),
            "required": [required.value for required in self.required],
            "errors": [error.to_dict() for error in self.errors],
        }

    def raise_for_errors(self) -> None:
        if self.errors:
            raise AuthorityAdmissionError(self.errors[0].message)


def admit_authority_capabilities(
    *,
    config: AuthorityConfig,
    capabilities: BackendCapabilitySet,
    required: Iterable[RequiredAuthorityCapability],
) -> CapabilityAdmissionResult:
    """Check whether a backend can satisfy a requested authority mode."""

    required_values = tuple(
        _enum(value, RequiredAuthorityCapability, "required") for value in required
    )
    errors: list[CapabilityAdmissionError] = []
    for required_value in required_values:
        errors.extend(
            _profile_errors(
                config=config,
                capabilities=capabilities,
                required=required_value,
            )
        )
        for capability, scope in _required_backend_capabilities(required_value):
            unsupported = capabilities.require(capability, scope=scope)
            if unsupported is None:
                continue
            errors.append(
                CapabilityAdmissionError(
                    code="authority.unsupported_capability",
                    required=required_value,
                    backend_name=capabilities.backend_name,
                    backend_kind=config.backend_kind.value,
                    deployment_profile=config.deployment_profile.value,
                    capability=capability,
                    scope=scope,
                    message=unsupported.message,
                    detail={
                        "missing_capability": capability.value,
                        "scope": scope.value,
                    },
                )
            )
    return CapabilityAdmissionResult(
        config=config,
        backend_name=capabilities.backend_name,
        required=required_values,
        errors=tuple(errors),
    )


def _required_backend_capabilities(
    required: RequiredAuthorityCapability,
) -> tuple[tuple[BackendCapability, CapabilityScope], ...]:
    per_run = CapabilityScope.PER_RUN
    cross_run = CapabilityScope.CROSS_RUN
    match required:
        case RequiredAuthorityCapability.SERIAL_RUN:
            return (
                (BackendCapability.RUN_ADMISSION, per_run),
                (BackendCapability.ATOMIC_TRANSITIONS, per_run),
                (BackendCapability.REVISIONED_SNAPSHOTS, per_run),
                (BackendCapability.MONOTONIC_REVISIONS, per_run),
            )
        case RequiredAuthorityCapability.BOUNDED_PARALLEL_STAGES:
            return (
                (BackendCapability.ATTEMPT_ALLOCATION, per_run),
                (BackendCapability.STAGE_LEASES, per_run),
                (BackendCapability.LEASE_TTL, per_run),
                (BackendCapability.FENCING_TOKENS, per_run),
                (BackendCapability.ATOMIC_OUTPUT_COMMIT, per_run),
                (BackendCapability.RECOVERY_SCANS, per_run),
            )
        case RequiredAuthorityCapability.SUBPROCESS_WORKER:
            return (
                (BackendCapability.STAGE_LEASES, per_run),
                (BackendCapability.FENCING_TOKENS, per_run),
                (BackendCapability.ATOMIC_OUTPUT_COMMIT, per_run),
            )
        case RequiredAuthorityCapability.SLURM_LIVE_WORKER:
            return (
                (BackendCapability.MULTI_HOST_AUTHORITY, cross_run),
                (BackendCapability.SERVICE_ENDPOINT, cross_run),
                (BackendCapability.BACKEND_LEASE_TIME, per_run),
                (BackendCapability.STAGE_LEASES, per_run),
                (BackendCapability.FENCING_TOKENS, per_run),
                (BackendCapability.ATOMIC_OUTPUT_COMMIT, per_run),
            )
        case RequiredAuthorityCapability.DEFERRED_FINALIZATION_WORKER:
            return ((BackendCapability.DEFERRED_FINALIZATION, per_run),)
        case RequiredAuthorityCapability.MULTI_RUN_SUBMISSION:
            return (
                (BackendCapability.RUN_ADMISSION, cross_run),
                (BackendCapability.CROSS_RUN_COORDINATION, cross_run),
                (BackendCapability.CONSISTENT_READS, cross_run),
            )
        case RequiredAuthorityCapability.SWEEP_COORDINATION:
            return (
                (BackendCapability.CROSS_RUN_COORDINATION, cross_run),
                (BackendCapability.GLOBAL_COUNTERS, cross_run),
                (BackendCapability.RECOVERY_SCANS, cross_run),
            )
        case RequiredAuthorityCapability.SHARED_RESOURCE_COUNTER:
            return ((BackendCapability.GLOBAL_COUNTERS, cross_run),)
        case RequiredAuthorityCapability.READ_ONLY_INSPECTION:
            return ((BackendCapability.CONSISTENT_READS, per_run),)


def _profile_errors(
    *,
    config: AuthorityConfig,
    capabilities: BackendCapabilitySet,
    required: RequiredAuthorityCapability,
) -> tuple[CapabilityAdmissionError, ...]:
    if (
        required is RequiredAuthorityCapability.SLURM_LIVE_WORKER
        and config.deployment_profile
        not in {
            AuthorityDeploymentProfile.MANAGED_SERVICE,
            AuthorityDeploymentProfile.ALLOCATION_SCOPED,
        }
    ):
        return (
            CapabilityAdmissionError(
                code="authority.unsupported_profile",
                required=required,
                backend_name=capabilities.backend_name,
                backend_kind=config.backend_kind.value,
                deployment_profile=config.deployment_profile.value,
                message=(
                    "live submitted workers require managed-service, "
                    "or allocation-scoped service authority"
                ),
                detail={"requested_feature": required.value},
            ),
        )
    if (
        required is RequiredAuthorityCapability.DEFERRED_FINALIZATION_WORKER
        and config.deployment_profile
        is not AuthorityDeploymentProfile.DEFERRED_FINALIZATION
    ):
        return (
            CapabilityAdmissionError(
                code="authority.unsupported_profile",
                required=required,
                backend_name=capabilities.backend_name,
                backend_kind=config.backend_kind.value,
                deployment_profile=config.deployment_profile.value,
                message=(
                    "deferred finalization requires the deferred-finalization "
                    "deployment profile"
                ),
                detail={"requested_feature": required.value},
            ),
        )
    return ()


def _enum[T: StrEnum](value: object, enum_type: type[T], field: str) -> T:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise AuthorityAdmissionError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityAdmissionError(f"invalid {field} {value!r}") from exc


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityAdmissionError(f"{field} must be a non-empty string")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise AuthorityAdmissionError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise AuthorityAdmissionError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


__all__ = [
    "AuthorityAdmissionError",
    "CapabilityAdmissionError",
    "CapabilityAdmissionResult",
    "RequiredAuthorityCapability",
    "admit_authority_capabilities",
]
