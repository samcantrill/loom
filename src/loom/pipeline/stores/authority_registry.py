"""Workspace-local authority registry records."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import cast
from urllib.parse import parse_qsl, urlsplit

from loom.serialization import DeserializationError, PlainData, ensure_plain_data, json_loads
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_now, utc_timestamp

from .atomic import atomic_write_json
from .authority_protocol import (
    AuthorityProtocolVersion,
    protocol_versions_compatible,
)
from .authority_resolution import (
    AuthorityReferenceSource,
    AuthorityRegistryHint,
    AuthorityResolutionDiagnosticSeverity,
    AuthorityResolutionFailureKind,
    AuthorityResolverDiagnostic,
    AuthorityServiceHealth,
    AuthorityServiceHealthState,
)
from .capabilities import BackendCapabilitySet
from .config import AuthorityReference


AUTHORITY_REGISTRY_SCHEMA_VERSION = 1
AUTHORITY_REGISTRY_DIR = ".loom/authority"
AUTHORITY_REGISTRY_CURRENT_FILE = "current.json"
AUTHORITY_REGISTRY_ALLOCATIONS_DIR = "allocations"

_SAFE_ALLOCATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "authkey",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
)
_REDACTED = "[REDACTED]"


class AuthorityRegistryError(ValueError):
    """Raised when authority registry records or paths are invalid."""


class AuthorityRegistryAllocationScope(StrEnum):
    """Workspace registry record scope."""

    WORKSPACE = "workspace"
    ALLOCATION = "allocation"


class AuthorityRegistryValidationStatus(StrEnum):
    """Registry validation outcomes before resolver adoption."""

    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"
    STALE = "stale"
    WRONG_WORKSPACE = "wrong_workspace"
    INCOMPATIBLE_GENERATION = "incompatible_generation"
    INCOMPATIBLE_VERSION = "incompatible_version"
    UNAVAILABLE_SERVICE = "unavailable_service"
    UNHEALTHY_SERVICE = "unhealthy_service"


@dataclass(frozen=True, slots=True)
class AuthorityRegistryRecord:
    """Versioned workspace-local authority allocation record."""

    reference: AuthorityReference
    service_generation: str
    workspace_id: str
    state_dir: str
    protocol_version: AuthorityProtocolVersion = field(
        default_factory=AuthorityProtocolVersion
    )
    capabilities: BackendCapabilitySet | None = None
    allocation_scope: AuthorityRegistryAllocationScope = (
        AuthorityRegistryAllocationScope.WORKSPACE
    )
    allocation_id: str | None = None
    created_at: str = field(default_factory=utc_timestamp)
    updated_at: str = field(default_factory=utc_timestamp)
    expires_at: str | None = None
    service_health_state: AuthorityServiceHealthState = (
        AuthorityServiceHealthState.UNKNOWN
    )
    diagnostics_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = AUTHORITY_REGISTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AUTHORITY_REGISTRY_SCHEMA_VERSION:
            raise AuthorityRegistryError(
                "unsupported authority registry schema_version "
                f"{self.schema_version!r}"
            )
        if not isinstance(self.reference, AuthorityReference):
            raise AuthorityRegistryError("reference must be an AuthorityReference")
        object.__setattr__(self, "reference", _safe_reference(self.reference))
        object.__setattr__(
            self,
            "service_generation",
            _non_empty_string(self.service_generation, "service_generation"),
        )
        object.__setattr__(
            self,
            "workspace_id",
            _non_empty_string(self.workspace_id, "workspace_id"),
        )
        if self.reference.workspace_id not in {None, self.workspace_id}:
            raise AuthorityRegistryError(
                "reference.workspace_id must match registry workspace_id"
            )
        object.__setattr__(
            self,
            "state_dir",
            _non_empty_string(self.state_dir, "state_dir"),
        )
        if not isinstance(self.protocol_version, AuthorityProtocolVersion):
            raise AuthorityRegistryError(
                "protocol_version must be an AuthorityProtocolVersion"
            )
        if self.capabilities is not None and not isinstance(
            self.capabilities, BackendCapabilitySet
        ):
            raise AuthorityRegistryError(
                "capabilities must be a BackendCapabilitySet or None"
            )
        object.__setattr__(
            self,
            "allocation_scope",
            _enum(
                self.allocation_scope,
                AuthorityRegistryAllocationScope,
                "allocation_scope",
            ),
        )
        if self.allocation_id is not None:
            object.__setattr__(
                self,
                "allocation_id",
                _allocation_id(self.allocation_id),
            )
        if (
            self.allocation_scope is AuthorityRegistryAllocationScope.ALLOCATION
            and self.allocation_id is None
        ):
            raise AuthorityRegistryError("allocation records require allocation_id")
        _parse_timestamp_field(self.created_at, "created_at")
        _parse_timestamp_field(self.updated_at, "updated_at")
        if self.expires_at is not None:
            _parse_timestamp_field(self.expires_at, "expires_at")
        object.__setattr__(
            self,
            "service_health_state",
            _enum(
                self.service_health_state,
                AuthorityServiceHealthState,
                "service_health_state",
            ),
        )
        object.__setattr__(
            self,
            "diagnostics_metadata",
            _redact_plain_mapping(self.diagnostics_metadata, "diagnostics_metadata"),
        )

    @property
    def protocol_compatible(self) -> bool:
        return protocol_versions_compatible(self.protocol_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "reference": self.reference.to_dict(),
            "service_generation": self.service_generation,
            "workspace_id": self.workspace_id,
            "state_dir": self.state_dir,
            "protocol_version": self.protocol_version.to_dict(),
            "capabilities": None
            if self.capabilities is None
            else self.capabilities.to_dict(),
            "allocation_scope": self.allocation_scope.value,
            "allocation_id": self.allocation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "service_health_state": self.service_health_state.value,
            "diagnostics_metadata": dict(self.diagnostics_metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityRegistryRecord":
        mapping = _mapping(data, "AuthorityRegistryRecord")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "reference",
                "service_generation",
                "workspace_id",
                "state_dir",
                "protocol_version",
                "capabilities",
                "allocation_scope",
                "allocation_id",
                "created_at",
                "updated_at",
                "expires_at",
                "service_health_state",
                "diagnostics_metadata",
            },
            "AuthorityRegistryRecord",
        )
        capabilities = mapping.get("capabilities")
        return cls(
            schema_version=_positive_int(
                mapping.get("schema_version", AUTHORITY_REGISTRY_SCHEMA_VERSION),
                "schema_version",
            ),
            reference=AuthorityReference.from_dict(_required(mapping, "reference")),
            service_generation=_non_empty_string(
                _required(mapping, "service_generation"), "service_generation"
            ),
            workspace_id=_non_empty_string(
                _required(mapping, "workspace_id"), "workspace_id"
            ),
            state_dir=_non_empty_string(_required(mapping, "state_dir"), "state_dir"),
            protocol_version=AuthorityProtocolVersion.from_dict(
                mapping.get("protocol_version", AuthorityProtocolVersion().to_dict())
            ),
            capabilities=None
            if capabilities is None
            else BackendCapabilitySet.from_dict(capabilities),
            allocation_scope=_enum(
                mapping.get(
                    "allocation_scope",
                    AuthorityRegistryAllocationScope.WORKSPACE.value,
                ),
                AuthorityRegistryAllocationScope,
                "allocation_scope",
            ),
            allocation_id=_optional_allocation_id(mapping.get("allocation_id")),
            created_at=_timestamp_string(_required(mapping, "created_at"), "created_at"),
            updated_at=_timestamp_string(_required(mapping, "updated_at"), "updated_at"),
            expires_at=_optional_timestamp_string(mapping.get("expires_at")),
            service_health_state=_enum(
                mapping.get(
                    "service_health_state",
                    AuthorityServiceHealthState.UNKNOWN.value,
                ),
                AuthorityServiceHealthState,
                "service_health_state",
            ),
            diagnostics_metadata=_plain_mapping(
                mapping.get("diagnostics_metadata", {}),
                "diagnostics_metadata",
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorityRegistryValidationResult:
    """Fail-closed validation result for one registry lookup."""

    status: AuthorityRegistryValidationStatus
    record: AuthorityRegistryRecord | None = None
    registry_hint: AuthorityRegistryHint | None = None
    service_health: AuthorityServiceHealth | None = None
    diagnostics: tuple[AuthorityResolverDiagnostic, ...] = ()
    path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _enum(self.status, AuthorityRegistryValidationStatus, "status"),
        )
        if self.record is not None and not isinstance(
            self.record, AuthorityRegistryRecord
        ):
            raise AuthorityRegistryError(
                "record must be an AuthorityRegistryRecord or None"
            )
        if self.registry_hint is not None and not isinstance(
            self.registry_hint, AuthorityRegistryHint
        ):
            raise AuthorityRegistryError(
                "registry_hint must be an AuthorityRegistryHint or None"
            )
        if self.service_health is not None and not isinstance(
            self.service_health, AuthorityServiceHealth
        ):
            raise AuthorityRegistryError(
                "service_health must be an AuthorityServiceHealth or None"
            )
        object.__setattr__(
            self,
            "diagnostics",
            _tuple_of_diagnostics(self.diagnostics),
        )
        if self.path is not None:
            object.__setattr__(self, "path", Path(self.path))

    @property
    def valid(self) -> bool:
        return self.status is AuthorityRegistryValidationStatus.VALID

    @property
    def failure_kind(self) -> AuthorityResolutionFailureKind | None:
        return _FAILURE_KIND_BY_STATUS.get(self.status)


_FAILURE_KIND_BY_STATUS: Mapping[
    AuthorityRegistryValidationStatus,
    AuthorityResolutionFailureKind,
] = {
    AuthorityRegistryValidationStatus.MISSING: (
        AuthorityResolutionFailureKind.MISSING_AUTHORITY
    ),
    AuthorityRegistryValidationStatus.INVALID: (
        AuthorityResolutionFailureKind.MISSING_AUTHORITY
    ),
    AuthorityRegistryValidationStatus.STALE: (
        AuthorityResolutionFailureKind.STALE_REGISTRY
    ),
    AuthorityRegistryValidationStatus.WRONG_WORKSPACE: (
        AuthorityResolutionFailureKind.WRONG_WORKSPACE
    ),
    AuthorityRegistryValidationStatus.INCOMPATIBLE_GENERATION: (
        AuthorityResolutionFailureKind.INCOMPATIBLE_GENERATION
    ),
    AuthorityRegistryValidationStatus.INCOMPATIBLE_VERSION: (
        AuthorityResolutionFailureKind.INCOMPATIBLE_VERSION
    ),
    AuthorityRegistryValidationStatus.UNAVAILABLE_SERVICE: (
        AuthorityResolutionFailureKind.UNAVAILABLE_SERVICE
    ),
    AuthorityRegistryValidationStatus.UNHEALTHY_SERVICE: (
        AuthorityResolutionFailureKind.UNHEALTHY_SERVICE
    ),
}


def authority_registry_dir(workspace_root: str | Path) -> Path:
    """Return the workspace-local authority registry directory."""

    return Path(workspace_root) / ".loom" / "authority"


def authority_registry_record_path(
    workspace_root: str | Path,
    *,
    allocation_id: str | None = None,
) -> Path:
    """Return the current or allocation-scoped registry record path."""

    root = authority_registry_dir(workspace_root)
    if allocation_id is None:
        return root / AUTHORITY_REGISTRY_CURRENT_FILE
    return root / AUTHORITY_REGISTRY_ALLOCATIONS_DIR / f"{_allocation_id(allocation_id)}.json"


def write_authority_registry_record(
    workspace_root: str | Path,
    record: AuthorityRegistryRecord,
    *,
    allocation_id: str | None = None,
) -> Path:
    """Atomically write an authority registry record and return its path."""

    if not isinstance(record, AuthorityRegistryRecord):
        raise AuthorityRegistryError("record must be an AuthorityRegistryRecord")
    path = authority_registry_record_path(
        workspace_root,
        allocation_id=allocation_id or record.allocation_id,
    )
    atomic_write_json(path, record.to_dict())
    return path


def read_authority_registry_record(
    workspace_root: str | Path,
    *,
    allocation_id: str | None = None,
) -> AuthorityRegistryRecord:
    """Read and parse one authority registry record."""

    path = authority_registry_record_path(workspace_root, allocation_id=allocation_id)
    try:
        payload = json_loads(path.read_text(encoding="utf-8"), path=str(path))
    except FileNotFoundError as exc:
        raise AuthorityRegistryError(f"authority registry record is missing: {path}") from exc
    except OSError as exc:
        raise AuthorityRegistryError(f"failed reading authority registry record: {path}") from exc
    except (DeserializationError, PlainDataError) as exc:
        raise AuthorityRegistryError(
            f"failed parsing authority registry record: {path}"
        ) from exc
    return AuthorityRegistryRecord.from_dict(payload)


def validate_authority_registry(
    workspace_root: str | Path,
    *,
    allocation_id: str | None = None,
    expected_workspace_id: str | None = None,
    expected_generation: str | None = None,
    now: datetime | str | None = None,
) -> AuthorityRegistryValidationResult:
    """Read and validate one workspace registry record."""

    path = authority_registry_record_path(workspace_root, allocation_id=allocation_id)
    if not path.exists():
        return _validation_result(
            AuthorityRegistryValidationStatus.MISSING,
            path=path,
            code="authority_registry.missing",
            message="authority registry record is missing",
            detail={"path": str(path)},
        )
    try:
        record = read_authority_registry_record(
            workspace_root,
            allocation_id=allocation_id,
        )
    except AuthorityRegistryError as exc:
        return _validation_result(
            AuthorityRegistryValidationStatus.INVALID,
            path=path,
            code="authority_registry.invalid",
            message=str(exc),
            detail={"path": str(path)},
        )
    return validate_authority_registry_record(
        record,
        expected_workspace_id=expected_workspace_id,
        expected_generation=expected_generation,
        now=now,
        path=path,
    )


def validate_authority_registry_record(
    record: AuthorityRegistryRecord,
    *,
    expected_workspace_id: str | None = None,
    expected_generation: str | None = None,
    now: datetime | str | None = None,
    path: str | Path | None = None,
) -> AuthorityRegistryValidationResult:
    """Validate one already parsed registry record."""

    if not isinstance(record, AuthorityRegistryRecord):
        raise AuthorityRegistryError("record must be an AuthorityRegistryRecord")
    resolved_now = _coerce_now(now)
    if record.expires_at is not None and parse_timestamp(record.expires_at) <= resolved_now:
        return _record_result(
            AuthorityRegistryValidationStatus.STALE,
            record,
            path=path,
            stale=True,
            code="authority_registry.stale",
            message="authority registry record is stale",
        )
    if expected_workspace_id is not None and record.workspace_id != expected_workspace_id:
        return _record_result(
            AuthorityRegistryValidationStatus.WRONG_WORKSPACE,
            record,
            path=path,
            workspace_matches=False,
            code="authority_registry.wrong_workspace",
            message="authority registry record belongs to a different workspace",
            detail={"expected_workspace_id": expected_workspace_id},
        )
    if (
        expected_generation is not None
        and record.service_generation != expected_generation
    ):
        return _record_result(
            AuthorityRegistryValidationStatus.INCOMPATIBLE_GENERATION,
            record,
            path=path,
            expected_generation=expected_generation,
            observed_generation=record.service_generation,
            code="authority_registry.incompatible_generation",
            message="authority registry generation does not match expected generation",
        )
    if not record.protocol_compatible:
        return _record_result(
            AuthorityRegistryValidationStatus.INCOMPATIBLE_VERSION,
            record,
            path=path,
            protocol_compatible=False,
            code="authority_registry.incompatible_version",
            message="authority registry record is not protocol compatible",
        )
    if record.service_health_state is AuthorityServiceHealthState.UNAVAILABLE:
        return _record_result(
            AuthorityRegistryValidationStatus.UNAVAILABLE_SERVICE,
            record,
            path=path,
            code="authority_registry.unavailable_service",
            message="authority registry record reports an unavailable service",
        )
    if record.service_health_state is AuthorityServiceHealthState.UNHEALTHY:
        return _record_result(
            AuthorityRegistryValidationStatus.UNHEALTHY_SERVICE,
            record,
            path=path,
            code="authority_registry.unhealthy_service",
            message="authority registry record reports an unhealthy service",
        )
    return _record_result(
        AuthorityRegistryValidationStatus.VALID,
        record,
        path=path,
        workspace_matches=True,
        protocol_compatible=True,
        code="authority_registry.valid",
        message="authority registry record is valid",
        severity=AuthorityResolutionDiagnosticSeverity.INFO,
    )


def authority_registry_hint_from_record(
    record: AuthorityRegistryRecord,
    *,
    stale: bool = False,
    workspace_matches: bool | None = None,
    expected_generation: str | None = None,
    observed_generation: str | None = None,
    protocol_compatible: bool | None = None,
    message: str | None = None,
) -> AuthorityRegistryHint:
    """Build a resolver hint from a registry record."""

    return AuthorityRegistryHint(
        reference=record.reference,
        stale=stale,
        workspace_matches=workspace_matches,
        expected_generation=expected_generation,
        observed_generation=observed_generation or record.service_generation,
        protocol_compatible=protocol_compatible
        if protocol_compatible is not None
        else record.protocol_compatible,
        message=message,
    )


def authority_service_health_from_record(
    record: AuthorityRegistryRecord,
) -> AuthorityServiceHealth:
    """Build resolver service-health facts from a registry record."""

    return AuthorityServiceHealth(
        state=record.service_health_state,
        service_generation=record.service_generation,
        protocol_version=str(record.protocol_version.protocol_version),
        protocol_compatible=record.protocol_compatible,
        message=None if record.service_health_state is AuthorityServiceHealthState.READY else record.service_health_state.value,
    )


def _record_result(
    status: AuthorityRegistryValidationStatus,
    record: AuthorityRegistryRecord,
    *,
    path: str | Path | None,
    code: str,
    message: str,
    stale: bool = False,
    workspace_matches: bool | None = None,
    expected_generation: str | None = None,
    observed_generation: str | None = None,
    protocol_compatible: bool | None = None,
    severity: AuthorityResolutionDiagnosticSeverity = (
        AuthorityResolutionDiagnosticSeverity.ERROR
    ),
    detail: Mapping[str, PlainData] | None = None,
) -> AuthorityRegistryValidationResult:
    hint = authority_registry_hint_from_record(
        record,
        stale=stale,
        workspace_matches=workspace_matches,
        expected_generation=expected_generation,
        observed_generation=observed_generation,
        protocol_compatible=protocol_compatible,
        message=message,
    )
    return AuthorityRegistryValidationResult(
        status=status,
        record=record,
        registry_hint=hint,
        service_health=authority_service_health_from_record(record),
        diagnostics=(
            _diagnostic(
                code,
                message,
                severity=severity,
                detail=_record_detail(record, path=path, extra=detail),
            ),
        ),
        path=None if path is None else Path(path),
    )


def _validation_result(
    status: AuthorityRegistryValidationStatus,
    *,
    path: str | Path,
    code: str,
    message: str,
    detail: Mapping[str, PlainData],
) -> AuthorityRegistryValidationResult:
    return AuthorityRegistryValidationResult(
        status=status,
        diagnostics=(_diagnostic(code, message, detail=detail),),
        path=Path(path),
    )


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: AuthorityResolutionDiagnosticSeverity = (
        AuthorityResolutionDiagnosticSeverity.ERROR
    ),
    detail: Mapping[str, PlainData] | None = None,
) -> AuthorityResolverDiagnostic:
    return AuthorityResolverDiagnostic(
        code=code,
        message=message,
        severity=severity,
        detail={} if detail is None else detail,
    )


def _record_detail(
    record: AuthorityRegistryRecord,
    *,
    path: str | Path | None,
    extra: Mapping[str, PlainData] | None,
) -> dict[str, PlainData]:
    detail: dict[str, PlainData] = {
        "reference_id": record.reference.reference_id,
        "workspace_id": record.workspace_id,
        "service_generation": record.service_generation,
        "allocation_scope": record.allocation_scope.value,
        "allocation_id": record.allocation_id,
        "reference_source": AuthorityReferenceSource.REGISTRY_HINT.value,
    }
    if path is not None:
        detail["path"] = str(path)
    if extra is not None:
        detail.update(extra)
    return detail


def _safe_reference(reference: AuthorityReference) -> AuthorityReference:
    return AuthorityReference(
        backend_kind=reference.backend_kind,
        deployment_profile=reference.deployment_profile,
        reference_id=reference.reference_id,
        endpoint=None if reference.endpoint is None else _safe_endpoint(reference.endpoint),
        workspace_id=reference.workspace_id,
        state_path=reference.state_path,
        metadata=_redact_plain_mapping(reference.metadata, "metadata"),
    )


def _safe_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.username or parsed.password:
        raise AuthorityRegistryError("authority endpoint must not contain userinfo")
    if parsed.query:
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
            if _is_sensitive_key(key):
                raise AuthorityRegistryError(
                    "authority endpoint must not contain sensitive query parameters"
                )
    return endpoint


def _redact_plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    mapping = _plain_mapping(value, field)
    return cast(
        Mapping[str, PlainData],
        ensure_plain_data(
            {
                key: _redact_plain_value(key, item)
                for key, item in mapping.items()
            }
        ),
    )


def _redact_plain_value(key: str, value: PlainData) -> PlainData:
    if _is_sensitive_key(key):
        return _REDACTED
    if isinstance(value, Mapping):
        return {
            child_key: _redact_plain_value(child_key, child_value)
            for child_key, child_value in cast(Mapping[str, PlainData], value).items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [
            _redact_plain_value(key, item)
            for item in cast(Sequence[PlainData], value)
        ]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _coerce_now(now: datetime | str | None) -> datetime:
    if now is None:
        return utc_now()
    if isinstance(now, str):
        return parse_timestamp(now)
    if isinstance(now, datetime):
        return now
    raise AuthorityRegistryError("now must be a datetime, timestamp string, or None")


def _allocation_id(value: object) -> str:
    value = _non_empty_string(value, "allocation_id")
    if _SAFE_ALLOCATION_ID_RE.fullmatch(value) is None:
        raise AuthorityRegistryError(
            "allocation_id must start with an ASCII alphanumeric and contain "
            "only ASCII alphanumerics, '_', '.', or '-'"
        )
    return value


def _optional_allocation_id(value: object) -> str | None:
    if value is None:
        return None
    return _allocation_id(value)


def _timestamp_string(value: object, field: str) -> str:
    value = _non_empty_string(value, field)
    _parse_timestamp_field(value, field)
    return value


def _optional_timestamp_string(value: object) -> str | None:
    if value is None:
        return None
    return _timestamp_string(value, "expires_at")


def _parse_timestamp_field(value: str, field: str) -> None:
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise AuthorityRegistryError(f"{field} must be a UTC timestamp") from exc


def _tuple_of_diagnostics(
    values: Sequence[object],
) -> tuple[AuthorityResolverDiagnostic, ...]:
    items = tuple(values)
    if any(not isinstance(item, AuthorityResolverDiagnostic) for item in items):
        raise AuthorityRegistryError(
            "diagnostics must contain AuthorityResolverDiagnostic values"
        )
    return cast(tuple[AuthorityResolverDiagnostic, ...], items)


def _enum[T: StrEnum](value: object, enum_type: type[T], field: str) -> T:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise AuthorityRegistryError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityRegistryError(f"invalid {field} {value!r}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthorityRegistryError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityRegistryError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise AuthorityRegistryError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityRegistryError(f"{field} must have string keys")
    try:
        return cast(Mapping[str, PlainData], ensure_plain_data(dict(value)))
    except (PlainDataError, TypeError) as exc:
        raise AuthorityRegistryError(f"{field} must contain plain data") from exc


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise AuthorityRegistryError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise AuthorityRegistryError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityRegistryError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthorityRegistryError(f"{field} must be a positive integer")
    return value


__all__ = [
    "AUTHORITY_REGISTRY_ALLOCATIONS_DIR",
    "AUTHORITY_REGISTRY_CURRENT_FILE",
    "AUTHORITY_REGISTRY_DIR",
    "AUTHORITY_REGISTRY_SCHEMA_VERSION",
    "AuthorityRegistryAllocationScope",
    "AuthorityRegistryError",
    "AuthorityRegistryRecord",
    "AuthorityRegistryValidationResult",
    "AuthorityRegistryValidationStatus",
    "authority_registry_dir",
    "authority_registry_hint_from_record",
    "authority_registry_record_path",
    "authority_service_health_from_record",
    "read_authority_registry_record",
    "validate_authority_registry",
    "validate_authority_registry_record",
    "write_authority_registry_record",
]
