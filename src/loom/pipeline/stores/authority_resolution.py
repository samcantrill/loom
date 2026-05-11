"""Side-effect-free authority mode resolution contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import os
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .config import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityReference,
)


class AuthorityResolutionError(ValueError):
    """Raised when authority resolution records are invalid."""


class AuthorityResolutionMode(StrEnum):
    """Caller-selected authority resolution mode."""

    ONLINE_MUTATION = "online_mutation"
    OFFLINE_FIRST = "offline_first"


class AuthorityReferenceSource(StrEnum):
    """Where a resolved authority reference came from."""

    NONE = "none"
    EXPLICIT_CONFIG = "explicit_config"
    REGISTRY_HINT = "registry_hint"


class AuthorityServiceHealthState(StrEnum):
    """Supplied health state for a referenced authority service."""

    UNKNOWN = "unknown"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    UNHEALTHY = "unhealthy"


class AuthorityResolutionOutcomeKind(StrEnum):
    """Top-level resolver outcome category."""

    ONLINE_AUTHORITY = "online_authority"
    OFFLINE_FIRST = "offline_first"
    FAILED = "failed"


class AuthorityResolutionFailureKind(StrEnum):
    """Typed failure categories for fail-closed online mutation resolution."""

    MISSING_AUTHORITY = "missing_authority"
    RESERVED_DIRECT_DATABASE = "reserved_direct_database"
    STALE_REGISTRY = "stale_registry"
    WRONG_WORKSPACE = "wrong_workspace"
    INCOMPATIBLE_GENERATION = "incompatible_generation"
    INCOMPATIBLE_VERSION = "incompatible_version"
    UNAVAILABLE_SERVICE = "unavailable_service"
    UNHEALTHY_SERVICE = "unhealthy_service"


class AuthorityResolutionDiagnosticSeverity(StrEnum):
    """Severity labels for authority resolver diagnostics."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


LOOM_AUTHORITY_MODE = "LOOM_AUTHORITY_MODE"


@dataclass(frozen=True, slots=True)
class AuthorityResolverDiagnostic:
    """Actionable authority resolution diagnostic."""

    code: str
    message: str
    severity: AuthorityResolutionDiagnosticSeverity = (
        AuthorityResolutionDiagnosticSeverity.ERROR
    )
    next_steps: tuple[str, ...] = ()
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _non_empty_string(self.code, "code"))
        object.__setattr__(
            self, "message", _non_empty_string(self.message, "message")
        )
        object.__setattr__(
            self,
            "severity",
            _enum(
                self.severity,
                AuthorityResolutionDiagnosticSeverity,
                "severity",
            ),
        )
        object.__setattr__(
            self,
            "next_steps",
            tuple(_non_empty_string(step, "next_steps") for step in self.next_steps),
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "next_steps": list(self.next_steps),
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityResolverDiagnostic":
        mapping = _mapping(data, "AuthorityResolverDiagnostic")
        _reject_unknown(
            mapping,
            {"code", "message", "severity", "next_steps", "detail"},
            "AuthorityResolverDiagnostic",
        )
        return cls(
            code=_non_empty_string(_required(mapping, "code"), "code"),
            message=_non_empty_string(_required(mapping, "message"), "message"),
            severity=_enum(
                mapping.get(
                    "severity", AuthorityResolutionDiagnosticSeverity.ERROR.value
                ),
                AuthorityResolutionDiagnosticSeverity,
                "severity",
            ),
            next_steps=tuple(
                _non_empty_string(step, "next_steps")
                for step in _sequence(mapping.get("next_steps", ()), "next_steps")
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class AuthorityRegistryHint:
    """Supplied registry facts for a candidate authority reference."""

    reference: AuthorityReference
    stale: bool = False
    workspace_matches: bool | None = None
    expected_generation: str | None = None
    observed_generation: str | None = None
    protocol_compatible: bool | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, AuthorityReference):
            raise AuthorityResolutionError("reference must be an AuthorityReference")
        if not isinstance(self.stale, bool):
            raise AuthorityResolutionError("stale must be a bool")
        if self.workspace_matches is not None and not isinstance(
            self.workspace_matches, bool
        ):
            raise AuthorityResolutionError("workspace_matches must be a bool or None")
        if self.expected_generation is not None:
            object.__setattr__(
                self,
                "expected_generation",
                _non_empty_string(
                    self.expected_generation, "expected_generation"
                ),
            )
        if self.observed_generation is not None:
            object.__setattr__(
                self,
                "observed_generation",
                _non_empty_string(
                    self.observed_generation, "observed_generation"
                ),
            )
        if self.protocol_compatible is not None and not isinstance(
            self.protocol_compatible, bool
        ):
            raise AuthorityResolutionError("protocol_compatible must be a bool or None")
        if self.message is not None:
            object.__setattr__(
                self, "message", _non_empty_string(self.message, "message")
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "reference": self.reference.to_dict(),
            "stale": self.stale,
            "workspace_matches": self.workspace_matches,
            "expected_generation": self.expected_generation,
            "observed_generation": self.observed_generation,
            "protocol_compatible": self.protocol_compatible,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class AuthorityServiceHealth:
    """Supplied service health facts for a candidate authority reference."""

    state: AuthorityServiceHealthState = AuthorityServiceHealthState.UNKNOWN
    service_generation: str | None = None
    protocol_version: str | None = None
    protocol_compatible: bool | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "state", _enum(self.state, AuthorityServiceHealthState, "state")
        )
        if self.service_generation is not None:
            object.__setattr__(
                self,
                "service_generation",
                _non_empty_string(self.service_generation, "service_generation"),
            )
        if self.protocol_version is not None:
            object.__setattr__(
                self,
                "protocol_version",
                _non_empty_string(self.protocol_version, "protocol_version"),
            )
        if self.protocol_compatible is not None and not isinstance(
            self.protocol_compatible, bool
        ):
            raise AuthorityResolutionError("protocol_compatible must be a bool or None")
        if self.message is not None:
            object.__setattr__(
                self, "message", _non_empty_string(self.message, "message")
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "state": self.state.value,
            "service_generation": self.service_generation,
            "protocol_version": self.protocol_version,
            "protocol_compatible": self.protocol_compatible,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class AuthorityResolverInput:
    """Inputs supplied to the authority resolver."""

    config: AuthorityConfig = field(default_factory=AuthorityConfig)
    mode: AuthorityResolutionMode = AuthorityResolutionMode.ONLINE_MUTATION
    registry_hint: AuthorityRegistryHint | None = None
    service_health: AuthorityServiceHealth | None = None
    expected_generation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.config, AuthorityConfig):
            raise AuthorityResolutionError("config must be an AuthorityConfig")
        object.__setattr__(
            self, "mode", _enum(self.mode, AuthorityResolutionMode, "mode")
        )
        if self.registry_hint is not None and not isinstance(
            self.registry_hint, AuthorityRegistryHint
        ):
            raise AuthorityResolutionError(
                "registry_hint must be an AuthorityRegistryHint or None"
            )
        if self.service_health is not None and not isinstance(
            self.service_health, AuthorityServiceHealth
        ):
            raise AuthorityResolutionError(
                "service_health must be an AuthorityServiceHealth or None"
            )
        if self.expected_generation is not None:
            object.__setattr__(
                self,
                "expected_generation",
                _non_empty_string(self.expected_generation, "expected_generation"),
            )


@dataclass(frozen=True, slots=True)
class AuthorityResolutionResult:
    """Side-effect-free authority resolution result."""

    mode: AuthorityResolutionMode
    outcome_kind: AuthorityResolutionOutcomeKind
    reference_source: AuthorityReferenceSource = AuthorityReferenceSource.NONE
    reference: AuthorityReference | None = None
    authoritative: bool = False
    failure_kind: AuthorityResolutionFailureKind | None = None
    diagnostics: tuple[AuthorityResolverDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "mode", _enum(self.mode, AuthorityResolutionMode, "mode")
        )
        object.__setattr__(
            self,
            "outcome_kind",
            _enum(
                self.outcome_kind,
                AuthorityResolutionOutcomeKind,
                "outcome_kind",
            ),
        )
        object.__setattr__(
            self,
            "reference_source",
            _enum(
                self.reference_source,
                AuthorityReferenceSource,
                "reference_source",
            ),
        )
        if self.reference is not None and not isinstance(
            self.reference, AuthorityReference
        ):
            raise AuthorityResolutionError(
                "reference must be an AuthorityReference or None"
            )
        if self.failure_kind is not None:
            object.__setattr__(
                self,
                "failure_kind",
                _enum(
                    self.failure_kind,
                    AuthorityResolutionFailureKind,
                    "failure_kind",
                ),
            )
        if not isinstance(self.authoritative, bool):
            raise AuthorityResolutionError("authoritative must be a bool")
        diagnostics = tuple(self.diagnostics)
        if any(
            not isinstance(diagnostic, AuthorityResolverDiagnostic)
            for diagnostic in diagnostics
        ):
            raise AuthorityResolutionError(
                "diagnostics must contain AuthorityResolverDiagnostic values"
            )
        object.__setattr__(self, "diagnostics", diagnostics)
        if self.outcome_kind is AuthorityResolutionOutcomeKind.FAILED:
            if self.failure_kind is None:
                raise AuthorityResolutionError("failed outcomes require failure_kind")
            if self.authoritative:
                raise AuthorityResolutionError("failed outcomes are not authoritative")
        if self.outcome_kind is AuthorityResolutionOutcomeKind.ONLINE_AUTHORITY:
            if self.reference is None:
                raise AuthorityResolutionError("online outcomes require reference")
            if not self.authoritative:
                raise AuthorityResolutionError("online outcomes must be authoritative")
        if self.outcome_kind is AuthorityResolutionOutcomeKind.OFFLINE_FIRST:
            if self.authoritative or self.reference is not None:
                raise AuthorityResolutionError(
                    "offline-first outcomes must not be authoritative"
                )

    @property
    def succeeded(self) -> bool:
        return self.outcome_kind is not AuthorityResolutionOutcomeKind.FAILED

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "mode": self.mode.value,
            "outcome_kind": self.outcome_kind.value,
            "reference_source": self.reference_source.value,
            "reference": None if self.reference is None else self.reference.to_dict(),
            "authoritative": self.authoritative,
            "failure_kind": None
            if self.failure_kind is None
            else self.failure_kind.value,
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
        }


def resolve_authority(input: AuthorityResolverInput) -> AuthorityResolutionResult:
    """Resolve authority mode without process, network, registry, or DB side effects."""

    if not isinstance(input, AuthorityResolverInput):
        raise AuthorityResolutionError("input must be an AuthorityResolverInput")

    if input.mode is AuthorityResolutionMode.OFFLINE_FIRST:
        return AuthorityResolutionResult(
            mode=input.mode,
            outcome_kind=AuthorityResolutionOutcomeKind.OFFLINE_FIRST,
            reference_source=AuthorityReferenceSource.NONE,
            authoritative=False,
            diagnostics=(
                _diagnostic(
                    "authority_resolution.offline_first_selected",
                    "offline-first mode selected; local evidence is not authority truth",
                    severity=AuthorityResolutionDiagnosticSeverity.INFO,
                    next_steps=(
                        "write v10 offline evidence before import",
                        "import accepted evidence through the authority service later",
                    ),
                ),
            ),
        )

    if input.config.backend_kind is AuthorityBackendKind.DIRECT_DATABASE:
        return _failure(
            input.mode,
            AuthorityResolutionFailureKind.RESERVED_DIRECT_DATABASE,
            "authority_resolution.direct_database_reserved",
            "direct database authority is reserved and unsupported for v10 runtime mutation",
            next_steps=(
                "select a service authority endpoint",
                "or select explicit offline-first mode when local evidence is intended",
            ),
            detail={"backend_kind": input.config.backend_kind.value},
        )

    reference: AuthorityReference | None
    source: AuthorityReferenceSource
    if input.config.endpoint is not None:
        reference = input.config.to_reference()
        source = AuthorityReferenceSource.EXPLICIT_CONFIG
    elif input.registry_hint is not None:
        registry_failure = _registry_failure(input.mode, input.registry_hint)
        if registry_failure is not None:
            return registry_failure
        reference = input.registry_hint.reference
        source = AuthorityReferenceSource.REGISTRY_HINT
    else:
        return _failure(
            input.mode,
            AuthorityResolutionFailureKind.MISSING_AUTHORITY,
            "authority_resolution.missing_authority",
            "online mutation mode requires an explicit authority endpoint or valid registry reference",
            next_steps=(
                "start an authority with `loom authority start --state-dir <path>`",
                "or select explicit offline-first mode when authority truth is not required yet",
            ),
            detail={"backend_kind": input.config.backend_kind.value},
        )

    generation_failure = _generation_failure(
        input.mode,
        expected_generation=input.expected_generation
        or (
            None
            if input.registry_hint is None
            else input.registry_hint.expected_generation
        ),
        observed_generation=(
            None
            if input.service_health is None
            else input.service_health.service_generation
        )
        or (
            None
            if input.registry_hint is None
            else input.registry_hint.observed_generation
        ),
    )
    if generation_failure is not None:
        return generation_failure

    health_failure = _health_failure(input.mode, input.service_health)
    if health_failure is not None:
        return health_failure

    return AuthorityResolutionResult(
        mode=input.mode,
        outcome_kind=AuthorityResolutionOutcomeKind.ONLINE_AUTHORITY,
        reference_source=source,
        reference=reference,
        authoritative=True,
        diagnostics=(
            _diagnostic(
                "authority_resolution.online_authority_selected",
                "online authority selected for mutation",
                severity=AuthorityResolutionDiagnosticSeverity.INFO,
                detail={"reference_source": source.value},
            ),
        ),
    )


def authority_resolution_mode_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    default: AuthorityResolutionMode = AuthorityResolutionMode.ONLINE_MUTATION,
) -> AuthorityResolutionMode:
    """Resolve authority resolution mode from Loom environment variables."""

    source = os.environ if environ is None else environ
    raw = source.get(LOOM_AUTHORITY_MODE)
    if raw in {None, ""}:
        return _enum(default, AuthorityResolutionMode, "default")
    return _enum(raw, AuthorityResolutionMode, LOOM_AUTHORITY_MODE)


def authority_resolution_mode_to_env(
    mode: AuthorityResolutionMode,
) -> dict[str, str]:
    """Serialize an authority resolution mode into Loom environment variables."""

    resolved = _enum(mode, AuthorityResolutionMode, "mode")
    return {LOOM_AUTHORITY_MODE: resolved.value}


def authority_resolution_mode_from_mapping(
    *,
    authority_mode: str | None = None,
    offline_first: bool | None = None,
    default: AuthorityResolutionMode = AuthorityResolutionMode.ONLINE_MUTATION,
) -> AuthorityResolutionMode:
    """Resolve authority mode from explicit option values."""

    if authority_mode not in {None, ""}:
        return _enum(authority_mode, AuthorityResolutionMode, "authority_mode")
    if offline_first:
        return AuthorityResolutionMode.OFFLINE_FIRST
    return _enum(default, AuthorityResolutionMode, "default")


def _registry_failure(
    mode: AuthorityResolutionMode,
    hint: AuthorityRegistryHint,
) -> AuthorityResolutionResult | None:
    if hint.stale:
        return _failure(
            mode,
            AuthorityResolutionFailureKind.STALE_REGISTRY,
            "authority_resolution.stale_registry",
            "authority registry reference is stale",
            next_steps=(
                "inspect the authority with `loom authority status`",
                "restart it explicitly with `loom authority restart --state-dir <path>`",
            ),
            detail=_hint_detail(hint),
        )
    if hint.workspace_matches is False:
        return _failure(
            mode,
            AuthorityResolutionFailureKind.WRONG_WORKSPACE,
            "authority_resolution.wrong_workspace",
            "authority registry reference belongs to a different workspace",
            next_steps=("select an authority for this workspace",),
            detail=_hint_detail(hint),
        )
    if hint.protocol_compatible is False:
        return _failure(
            mode,
            AuthorityResolutionFailureKind.INCOMPATIBLE_VERSION,
            "authority_resolution.incompatible_version",
            "authority registry reference is not protocol compatible",
            next_steps=("upgrade or restart the authority service explicitly",),
            detail=_hint_detail(hint),
        )
    return None


def _generation_failure(
    mode: AuthorityResolutionMode,
    *,
    expected_generation: str | None,
    observed_generation: str | None,
) -> AuthorityResolutionResult | None:
    if (
        expected_generation is not None
        and observed_generation is not None
        and expected_generation != observed_generation
    ):
        return _failure(
            mode,
            AuthorityResolutionFailureKind.INCOMPATIBLE_GENERATION,
            "authority_resolution.incompatible_generation",
            "authority service generation does not match the expected generation",
            next_steps=(
                "refresh the authority reference",
                "or restart the authority explicitly before mutating",
            ),
            detail={
                "expected_generation": expected_generation,
                "observed_generation": observed_generation,
            },
        )
    return None


def _health_failure(
    mode: AuthorityResolutionMode,
    health: AuthorityServiceHealth | None,
) -> AuthorityResolutionResult | None:
    if health is None:
        return None
    if health.protocol_compatible is False:
        return _failure(
            mode,
            AuthorityResolutionFailureKind.INCOMPATIBLE_VERSION,
            "authority_resolution.incompatible_version",
            "authority service protocol is not compatible",
            next_steps=("use a compatible authority service version",),
            detail=health.to_dict(),
        )
    if health.state is AuthorityServiceHealthState.UNAVAILABLE:
        return _failure(
            mode,
            AuthorityResolutionFailureKind.UNAVAILABLE_SERVICE,
            "authority_resolution.unavailable_service",
            "authority service is unavailable",
            next_steps=(
                "inspect the authority with `loom authority status`",
                "restart it explicitly with `loom authority restart --state-dir <path>`",
            ),
            detail=health.to_dict(),
        )
    if health.state is AuthorityServiceHealthState.UNHEALTHY:
        return _failure(
            mode,
            AuthorityResolutionFailureKind.UNHEALTHY_SERVICE,
            "authority_resolution.unhealthy_service",
            "authority service is unhealthy",
            next_steps=("run `loom authority doctor` for diagnostics",),
            detail=health.to_dict(),
        )
    return None


def _failure(
    mode: AuthorityResolutionMode,
    failure_kind: AuthorityResolutionFailureKind,
    code: str,
    message: str,
    *,
    next_steps: tuple[str, ...],
    detail: Mapping[str, PlainData] | None = None,
) -> AuthorityResolutionResult:
    return AuthorityResolutionResult(
        mode=mode,
        outcome_kind=AuthorityResolutionOutcomeKind.FAILED,
        reference_source=AuthorityReferenceSource.NONE,
        authoritative=False,
        failure_kind=failure_kind,
        diagnostics=(
            _diagnostic(
                code,
                message,
                next_steps=next_steps,
                detail={} if detail is None else detail,
            ),
        ),
    )


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: AuthorityResolutionDiagnosticSeverity = (
        AuthorityResolutionDiagnosticSeverity.ERROR
    ),
    next_steps: tuple[str, ...] = (),
    detail: Mapping[str, PlainData] | None = None,
) -> AuthorityResolverDiagnostic:
    return AuthorityResolverDiagnostic(
        code=code,
        message=message,
        severity=severity,
        next_steps=next_steps,
        detail={} if detail is None else detail,
    )


def _hint_detail(hint: AuthorityRegistryHint) -> dict[str, PlainData]:
    return {
        "reference_id": hint.reference.reference_id,
        "workspace_id": hint.reference.workspace_id,
        "expected_generation": hint.expected_generation,
        "observed_generation": hint.observed_generation,
        "message": hint.message,
    }


def _enum[T: StrEnum](value: object, enum_type: type[T], field: str) -> T:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise AuthorityResolutionError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityResolutionError(f"invalid {field} {value!r}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthorityResolutionError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityResolutionError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise AuthorityResolutionError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise AuthorityResolutionError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, str | bytes | bytearray):
        raise AuthorityResolutionError(f"{field} must be a sequence")
    if value is None:
        return ()
    try:
        return tuple(cast(tuple[object, ...], value))
    except TypeError as exc:
        raise AuthorityResolutionError(f"{field} must be a sequence") from exc


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityResolutionError(f"{field} must be a non-empty string")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise AuthorityResolutionError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityResolutionError(f"{field} must have string keys")
    try:
        return cast(Mapping[str, PlainData], ensure_plain_data(dict(value)))
    except (PlainDataError, TypeError) as exc:
        raise AuthorityResolutionError(f"{field} must contain plain data") from exc


__all__ = [
    "LOOM_AUTHORITY_MODE",
    "AuthorityRegistryHint",
    "AuthorityReferenceSource",
    "AuthorityResolutionDiagnosticSeverity",
    "AuthorityResolutionError",
    "AuthorityResolutionFailureKind",
    "AuthorityResolutionMode",
    "AuthorityResolutionOutcomeKind",
    "AuthorityResolutionResult",
    "AuthorityResolverDiagnostic",
    "AuthorityResolverInput",
    "AuthorityServiceHealth",
    "AuthorityServiceHealthState",
    "authority_resolution_mode_from_env",
    "authority_resolution_mode_from_mapping",
    "authority_resolution_mode_to_env",
    "resolve_authority",
]
