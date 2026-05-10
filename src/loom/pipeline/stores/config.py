"""Authority backend configuration records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError


class AuthorityConfigError(ValueError):
    """Raised when authority configuration records are invalid."""


class AuthorityBackendKind(StrEnum):
    CO_LOCATED_SERVICE = "co_located_service"
    MANAGED_SERVICE = "managed_service"
    ALLOCATION_SCOPED_SERVICE = "allocation_scoped_service"
    DIRECT_DATABASE = "direct_database"
    DEFERRED_FINALIZATION = "deferred_finalization"
    TRANSITIONAL_SQLITE = "transitional_sqlite"
    TEST_FAKE = "test_fake"


class AuthorityDeploymentProfile(StrEnum):
    CO_LOCATED = "co_located"
    MANAGED_SERVICE = "managed_service"
    ALLOCATION_SCOPED = "allocation_scoped"
    DIRECT_DATABASE = "direct_database"
    DEFERRED_FINALIZATION = "deferred_finalization"


_DEFAULT_REDACTION_KEYS = ("endpoint", "credential", "credentials", "token", "secret")


@dataclass(frozen=True, slots=True)
class AuthorityReference:
    """Safe-to-serialize reference to the selected authority."""

    backend_kind: AuthorityBackendKind
    deployment_profile: AuthorityDeploymentProfile
    reference_id: str
    endpoint: str | None = None
    workspace_id: str | None = None
    state_path: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "backend_kind",
            _enum(self.backend_kind, AuthorityBackendKind, "backend_kind"),
        )
        object.__setattr__(
            self,
            "deployment_profile",
            _enum(
                self.deployment_profile,
                AuthorityDeploymentProfile,
                "deployment_profile",
            ),
        )
        object.__setattr__(
            self, "reference_id", _non_empty_string(self.reference_id, "reference_id")
        )
        if self.endpoint is not None:
            object.__setattr__(
                self, "endpoint", _non_empty_string(self.endpoint, "endpoint")
            )
        if self.workspace_id is not None:
            object.__setattr__(
                self,
                "workspace_id",
                _non_empty_string(self.workspace_id, "workspace_id"),
            )
        if self.state_path is not None:
            object.__setattr__(
                self, "state_path", _non_empty_string(self.state_path, "state_path")
            )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "backend_kind": self.backend_kind.value,
            "deployment_profile": self.deployment_profile.value,
            "reference_id": self.reference_id,
            "endpoint": self.endpoint,
            "workspace_id": self.workspace_id,
            "state_path": self.state_path,
            "metadata": dict(self.metadata),
        }

    def redacted_dict(
        self, redaction_keys: Sequence[str] = _DEFAULT_REDACTION_KEYS
    ) -> dict[str, PlainData]:
        return _redact_mapping(self.to_dict(), redaction_keys)

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityReference":
        mapping = _mapping(data, "AuthorityReference")
        _reject_unknown(
            mapping,
            {
                "backend_kind",
                "deployment_profile",
                "reference_id",
                "endpoint",
                "workspace_id",
                "state_path",
                "metadata",
            },
            "AuthorityReference",
        )
        return cls(
            backend_kind=_enum(
                _required(mapping, "backend_kind"),
                AuthorityBackendKind,
                "backend_kind",
            ),
            deployment_profile=_enum(
                _required(mapping, "deployment_profile"),
                AuthorityDeploymentProfile,
                "deployment_profile",
            ),
            reference_id=_non_empty_string(
                _required(mapping, "reference_id"), "reference_id"
            ),
            endpoint=_optional_string(mapping.get("endpoint"), "endpoint"),
            workspace_id=_optional_string(mapping.get("workspace_id"), "workspace_id"),
            state_path=_optional_string(mapping.get("state_path"), "state_path"),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class AuthorityConfig:
    """Plain-data authority selection for factories and worker handoff."""

    backend_kind: AuthorityBackendKind = AuthorityBackendKind.TRANSITIONAL_SQLITE
    deployment_profile: AuthorityDeploymentProfile = (
        AuthorityDeploymentProfile.CO_LOCATED
    )
    endpoint: str | None = None
    workspace_id: str | None = None
    state_path: str | None = None
    reference_id: str = "default"
    redaction_keys: tuple[str, ...] = _DEFAULT_REDACTION_KEYS
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "backend_kind",
            _enum(self.backend_kind, AuthorityBackendKind, "backend_kind"),
        )
        object.__setattr__(
            self,
            "deployment_profile",
            _enum(
                self.deployment_profile,
                AuthorityDeploymentProfile,
                "deployment_profile",
            ),
        )
        if self.endpoint is not None:
            object.__setattr__(
                self, "endpoint", _non_empty_string(self.endpoint, "endpoint")
            )
        if self.workspace_id is not None:
            object.__setattr__(
                self,
                "workspace_id",
                _non_empty_string(self.workspace_id, "workspace_id"),
            )
        if self.state_path is not None:
            object.__setattr__(
                self, "state_path", _non_empty_string(self.state_path, "state_path")
            )
        object.__setattr__(
            self, "reference_id", _non_empty_string(self.reference_id, "reference_id")
        )
        redaction_keys = tuple(
            _non_empty_string(key, "redaction_keys") for key in self.redaction_keys
        )
        object.__setattr__(self, "redaction_keys", redaction_keys)
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_reference(self) -> AuthorityReference:
        return AuthorityReference(
            backend_kind=self.backend_kind,
            deployment_profile=self.deployment_profile,
            reference_id=self.reference_id,
            endpoint=self.endpoint,
            workspace_id=self.workspace_id,
            state_path=self.state_path,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "backend_kind": self.backend_kind.value,
            "deployment_profile": self.deployment_profile.value,
            "endpoint": self.endpoint,
            "workspace_id": self.workspace_id,
            "state_path": self.state_path,
            "reference_id": self.reference_id,
            "redaction_keys": list(self.redaction_keys),
            "metadata": dict(self.metadata),
        }

    def redacted_dict(self) -> dict[str, PlainData]:
        return _redact_mapping(self.to_dict(), self.redaction_keys)

    @classmethod
    def from_dict(cls, data: object) -> "AuthorityConfig":
        mapping = _mapping(data, "AuthorityConfig")
        _reject_unknown(
            mapping,
            {
                "backend_kind",
                "deployment_profile",
                "endpoint",
                "workspace_id",
                "state_path",
                "reference_id",
                "redaction_keys",
                "metadata",
            },
            "AuthorityConfig",
        )
        return cls(
            backend_kind=_enum(
                mapping.get(
                    "backend_kind", AuthorityBackendKind.TRANSITIONAL_SQLITE.value
                ),
                AuthorityBackendKind,
                "backend_kind",
            ),
            deployment_profile=_enum(
                mapping.get(
                    "deployment_profile",
                    AuthorityDeploymentProfile.CO_LOCATED.value,
                ),
                AuthorityDeploymentProfile,
                "deployment_profile",
            ),
            endpoint=_optional_string(mapping.get("endpoint"), "endpoint"),
            workspace_id=_optional_string(mapping.get("workspace_id"), "workspace_id"),
            state_path=_optional_string(mapping.get("state_path"), "state_path"),
            reference_id=_non_empty_string(
                mapping.get("reference_id", "default"), "reference_id"
            ),
            redaction_keys=tuple(
                _non_empty_string(key, "redaction_keys")
                for key in _sequence(
                    mapping.get("redaction_keys", _DEFAULT_REDACTION_KEYS),
                    "redaction_keys",
                )
            ),
            metadata=_plain_mapping(mapping.get("metadata", {}), "metadata"),
        )


def _enum[T: StrEnum](value: object, enum_type: type[T], field: str) -> T:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise AuthorityConfigError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise AuthorityConfigError(f"invalid {field} {value!r}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthorityConfigError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityConfigError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise AuthorityConfigError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise AuthorityConfigError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Sequence):
        raise AuthorityConfigError(f"{field} must be a sequence")
    return cast(Sequence[object], value)


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityConfigError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field)


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise AuthorityConfigError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise AuthorityConfigError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _redact_mapping(
    mapping: Mapping[str, PlainData], redaction_keys: Sequence[str]
) -> dict[str, PlainData]:
    redact_tokens = tuple(key.casefold() for key in redaction_keys)
    redacted: dict[str, PlainData] = {}
    for key, value in mapping.items():
        if any(token in key.casefold() for token in redact_tokens):
            redacted[key] = "<redacted>"
        elif isinstance(value, Mapping):
            redacted[key] = _redact_mapping(
                cast(Mapping[str, PlainData], value), redaction_keys
            )
        else:
            redacted[key] = value
    return redacted


__all__ = [
    "AuthorityBackendKind",
    "AuthorityConfig",
    "AuthorityConfigError",
    "AuthorityDeploymentProfile",
    "AuthorityReference",
]
