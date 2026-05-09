"""Backend-neutral capability and diagnostic records for authoritative stores."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError


class AuthorityCapabilityError(ValueError):
    """Raised when an authority capability record is invalid."""


class BackendCapability(StrEnum):
    ATOMIC_TRANSITIONS = "atomic_transitions"
    ATTEMPT_ALLOCATION = "attempt_allocation"
    RUN_LEASES = "run_leases"
    STAGE_LEASES = "stage_leases"
    BACKEND_LEASE_TIME = "backend_lease_time"
    ATOMIC_OUTPUT_COMMIT = "atomic_output_commit"
    ARTIFACT_FACTS = "artifact_facts"
    SUBMITTED_OPERATIONS = "submitted_operations"
    REVISIONED_SNAPSHOTS = "revisioned_snapshots"
    RECOVERY_SCANS = "recovery_scans"
    CONSISTENT_READS = "consistent_reads"
    MATERIALIZATION_REFS = "materialization_refs"
    AUDIT_EVENTS = "audit_events"
    PER_RUN_COORDINATION = "per_run_coordination"
    CROSS_RUN_COORDINATION = "cross_run_coordination"
    GLOBAL_COUNTERS = "global_counters"


class CapabilityScope(StrEnum):
    PER_RUN = "per_run"
    CROSS_RUN = "cross_run"


class CapabilitySupport(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class UnsupportedCapabilityCode(StrEnum):
    MISSING_CAPABILITY = "missing_capability"
    UNSAFE_SHARED_FILESYSTEM = "unsafe_shared_filesystem"
    UNSAFE_REMOTE_COORDINATION = "unsafe_remote_coordination"
    UNSUPPORTED_PARALLEL_EXECUTION = "unsupported_parallel_execution"
    UNSUPPORTED_CROSS_RUN_COORDINATION = "unsupported_cross_run_coordination"


@dataclass(frozen=True, slots=True)
class StoreDiagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _non_empty_string(self.code, "code"))
        object.__setattr__(
            self, "message", _non_empty_string(self.message, "message")
        )
        object.__setattr__(
            self,
            "severity",
            _coerce_enum(self.severity, DiagnosticSeverity, "severity"),
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: object) -> "StoreDiagnostic":
        mapping = _mapping(data, "StoreDiagnostic")
        _reject_unknown(
            mapping, {"code", "message", "severity", "detail"}, "StoreDiagnostic"
        )
        return cls(
            code=_non_empty_string(_required(mapping, "code"), "code"),
            message=_non_empty_string(_required(mapping, "message"), "message"),
            severity=_coerce_enum(
                mapping.get("severity", DiagnosticSeverity.ERROR.value),
                DiagnosticSeverity,
                "severity",
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class BackendCapabilityRecord:
    capability: BackendCapability
    scope: CapabilityScope
    support: CapabilitySupport = CapabilitySupport.SUPPORTED
    message: str | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability",
            _coerce_enum(self.capability, BackendCapability, "capability"),
        )
        object.__setattr__(
            self, "scope", _coerce_enum(self.scope, CapabilityScope, "scope")
        )
        object.__setattr__(
            self,
            "support",
            _coerce_enum(self.support, CapabilitySupport, "support"),
        )
        if self.message is not None:
            object.__setattr__(
                self, "message", _non_empty_string(self.message, "message")
            )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    @property
    def supported(self) -> bool:
        return self.support is CapabilitySupport.SUPPORTED

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "capability": self.capability.value,
            "scope": self.scope.value,
            "support": self.support.value,
            "message": self.message,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: object) -> "BackendCapabilityRecord":
        mapping = _mapping(data, "BackendCapabilityRecord")
        _reject_unknown(
            mapping,
            {"capability", "scope", "support", "message", "detail"},
            "BackendCapabilityRecord",
        )
        return cls(
            capability=_coerce_enum(_required(mapping, "capability"), BackendCapability, "capability"),
            scope=_coerce_enum(_required(mapping, "scope"), CapabilityScope, "scope"),
            support=_coerce_enum(
                mapping.get("support", CapabilitySupport.SUPPORTED.value),
                CapabilitySupport,
                "support",
            ),
            message=_optional_string(mapping.get("message"), "message"),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class UnsupportedCapability:
    code: UnsupportedCapabilityCode
    capability: BackendCapability
    scope: CapabilityScope
    message: str
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _coerce_enum(self.code, UnsupportedCapabilityCode, "code")
        )
        object.__setattr__(
            self,
            "capability",
            _coerce_enum(self.capability, BackendCapability, "capability"),
        )
        object.__setattr__(
            self, "scope", _coerce_enum(self.scope, CapabilityScope, "scope")
        )
        object.__setattr__(
            self, "message", _non_empty_string(self.message, "message")
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_diagnostic(self) -> StoreDiagnostic:
        return StoreDiagnostic(
            code=self.code.value,
            message=self.message,
            severity=DiagnosticSeverity.ERROR,
            detail={
                "capability": self.capability.value,
                "scope": self.scope.value,
                **dict(self.detail),
            },
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code.value,
            "capability": self.capability.value,
            "scope": self.scope.value,
            "message": self.message,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class BackendCapabilitySet:
    backend_name: str
    records: tuple[BackendCapabilityRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "backend_name", _non_empty_string(self.backend_name, "backend_name")
        )
        object.__setattr__(self, "records", tuple(self.records))
        for record in self.records:
            if not isinstance(record, BackendCapabilityRecord):
                raise AuthorityCapabilityError(
                    "records must contain BackendCapabilityRecord values"
                )

    def supports(
        self, capability: BackendCapability, *, scope: CapabilityScope
    ) -> bool:
        wanted_capability = _coerce_enum(capability, BackendCapability, "capability")
        wanted_scope = _coerce_enum(scope, CapabilityScope, "scope")
        return any(
            record.capability is wanted_capability
            and record.scope is wanted_scope
            and record.supported
            for record in self.records
        )

    def require(
        self, capability: BackendCapability, *, scope: CapabilityScope
    ) -> UnsupportedCapability | None:
        wanted_capability = _coerce_enum(capability, BackendCapability, "capability")
        wanted_scope = _coerce_enum(scope, CapabilityScope, "scope")
        explicit_unsupported: BackendCapabilityRecord | None = None
        for record in self.records:
            if record.capability is wanted_capability and record.scope is wanted_scope:
                if record.supported:
                    return None
                explicit_unsupported = record
                break
        message = (
            explicit_unsupported.message
            if explicit_unsupported is not None
            and explicit_unsupported.message is not None
            else (
                f"backend {self.backend_name!r} does not support "
                f"{wanted_scope.value} capability {wanted_capability.value!r}"
            )
        )
        detail = (
            explicit_unsupported.detail
            if explicit_unsupported is not None
            else {}
        )
        return UnsupportedCapability(
            code=UnsupportedCapabilityCode.MISSING_CAPABILITY,
            capability=wanted_capability,
            scope=wanted_scope,
            message=message,
            detail=detail,
        )

    def diagnostics_for(
        self, capabilities: Iterable[BackendCapability], *, scope: CapabilityScope
    ) -> tuple[StoreDiagnostic, ...]:
        diagnostics: list[StoreDiagnostic] = []
        for capability in capabilities:
            unsupported = self.require(capability, scope=scope)
            if unsupported is not None:
                diagnostics.append(unsupported.to_diagnostic())
        return tuple(diagnostics)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "backend_name": self.backend_name,
            "records": [record.to_dict() for record in self.records],
        }


def _coerce_enum[T: StrEnum](
    value: object, enum_type: type[T], field: str
) -> T:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise AuthorityCapabilityError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityCapabilityError(f"invalid {field} {value!r}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthorityCapabilityError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityCapabilityError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise AuthorityCapabilityError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise AuthorityCapabilityError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityCapabilityError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field)


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise AuthorityCapabilityError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise AuthorityCapabilityError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


__all__ = [
    "AuthorityCapabilityError",
    "BackendCapability",
    "CapabilityScope",
    "CapabilitySupport",
    "DiagnosticSeverity",
    "UnsupportedCapabilityCode",
    "StoreDiagnostic",
    "BackendCapabilityRecord",
    "UnsupportedCapability",
    "BackendCapabilitySet",
]
