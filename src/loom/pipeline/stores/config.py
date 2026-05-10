"""Authority backend configuration records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import json
import os
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
LOOM_AUTHORITY_BACKEND = "LOOM_AUTHORITY_BACKEND"
LOOM_AUTHORITY_PROFILE = "LOOM_AUTHORITY_PROFILE"
LOOM_AUTHORITY_ENDPOINT = "LOOM_AUTHORITY_ENDPOINT"
LOOM_AUTHORITY_WORKSPACE = "LOOM_AUTHORITY_WORKSPACE"
LOOM_AUTHORITY_STATE = "LOOM_AUTHORITY_STATE"
LOOM_AUTHORITY_REFERENCE_ID = "LOOM_AUTHORITY_REFERENCE_ID"
LOOM_AUTHORITY_METADATA_JSON = "LOOM_AUTHORITY_METADATA_JSON"


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

    backend_kind: AuthorityBackendKind = AuthorityBackendKind.CO_LOCATED_SERVICE
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
                    "backend_kind", AuthorityBackendKind.CO_LOCATED_SERVICE.value
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


def default_deployment_profile_for_backend(
    backend_kind: AuthorityBackendKind | str,
) -> AuthorityDeploymentProfile:
    """Return the default deployment profile for a backend kind."""

    kind = _enum(backend_kind, AuthorityBackendKind, "backend_kind")
    match kind:
        case AuthorityBackendKind.CO_LOCATED_SERVICE:
            return AuthorityDeploymentProfile.CO_LOCATED
        case AuthorityBackendKind.MANAGED_SERVICE:
            return AuthorityDeploymentProfile.MANAGED_SERVICE
        case AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE:
            return AuthorityDeploymentProfile.ALLOCATION_SCOPED
        case AuthorityBackendKind.DIRECT_DATABASE:
            return AuthorityDeploymentProfile.DIRECT_DATABASE
        case AuthorityBackendKind.DEFERRED_FINALIZATION:
            return AuthorityDeploymentProfile.DEFERRED_FINALIZATION
        case AuthorityBackendKind.TRANSITIONAL_SQLITE | AuthorityBackendKind.TEST_FAKE:
            return AuthorityDeploymentProfile.CO_LOCATED


def authority_config_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    default: AuthorityConfig | None = None,
) -> AuthorityConfig:
    """Resolve authority config from Loom environment variables."""

    source = os.environ if environ is None else environ
    fallback = default or AuthorityConfig()
    selected = {
        key: source.get(key)
        for key in (
            LOOM_AUTHORITY_BACKEND,
            LOOM_AUTHORITY_PROFILE,
            LOOM_AUTHORITY_ENDPOINT,
            LOOM_AUTHORITY_WORKSPACE,
            LOOM_AUTHORITY_STATE,
            LOOM_AUTHORITY_REFERENCE_ID,
            LOOM_AUTHORITY_METADATA_JSON,
        )
    }
    if all(value in {None, ""} for value in selected.values()):
        return fallback

    backend = selected[LOOM_AUTHORITY_BACKEND]
    endpoint = _blank_to_none(selected[LOOM_AUTHORITY_ENDPOINT])
    if backend is None or backend == "":
        backend = (
            AuthorityBackendKind.CO_LOCATED_SERVICE.value
            if endpoint is not None
            else fallback.backend_kind.value
        )
    backend_kind = _enum(backend, AuthorityBackendKind, "backend_kind")
    profile = selected[LOOM_AUTHORITY_PROFILE]
    deployment_profile = (
        default_deployment_profile_for_backend(backend_kind)
        if profile is None or profile == ""
        else _enum(profile, AuthorityDeploymentProfile, "deployment_profile")
    )
    metadata = fallback.metadata
    raw_metadata = selected[LOOM_AUTHORITY_METADATA_JSON]
    if raw_metadata not in {None, ""}:
        metadata = _metadata_from_json(cast(str, raw_metadata))
    return AuthorityConfig(
        backend_kind=backend_kind,
        deployment_profile=deployment_profile,
        endpoint=endpoint if endpoint is not None else fallback.endpoint,
        workspace_id=_blank_to_none(selected[LOOM_AUTHORITY_WORKSPACE])
        or fallback.workspace_id,
        state_path=_blank_to_none(selected[LOOM_AUTHORITY_STATE]) or fallback.state_path,
        reference_id=_blank_to_none(selected[LOOM_AUTHORITY_REFERENCE_ID])
        or fallback.reference_id,
        redaction_keys=fallback.redaction_keys,
        metadata=metadata,
    )


def authority_config_to_env(config: AuthorityConfig) -> dict[str, str]:
    """Serialize authority config into Loom environment variables."""

    if not isinstance(config, AuthorityConfig):
        raise AuthorityConfigError("config must be an AuthorityConfig")
    values = {
        LOOM_AUTHORITY_BACKEND: config.backend_kind.value,
        LOOM_AUTHORITY_PROFILE: config.deployment_profile.value,
        LOOM_AUTHORITY_REFERENCE_ID: config.reference_id,
    }
    if config.endpoint is not None:
        values[LOOM_AUTHORITY_ENDPOINT] = config.endpoint
    if config.workspace_id is not None:
        values[LOOM_AUTHORITY_WORKSPACE] = config.workspace_id
    if config.state_path is not None:
        values[LOOM_AUTHORITY_STATE] = config.state_path
    if config.metadata:
        values[LOOM_AUTHORITY_METADATA_JSON] = json.dumps(
            config.metadata,
            sort_keys=True,
            separators=(",", ":"),
        )
    return values


def authority_config_to_cli_args(config: AuthorityConfig) -> tuple[str, ...]:
    """Serialize authority config as CLI flags for worker handoff commands."""

    env = authority_config_to_env(config)
    args: list[str] = []
    flag_by_var = {
        LOOM_AUTHORITY_BACKEND: "--authority-backend",
        LOOM_AUTHORITY_PROFILE: "--authority-profile",
        LOOM_AUTHORITY_ENDPOINT: "--authority-endpoint",
        LOOM_AUTHORITY_WORKSPACE: "--authority-workspace",
        LOOM_AUTHORITY_STATE: "--authority-state",
        LOOM_AUTHORITY_REFERENCE_ID: "--authority-reference",
        LOOM_AUTHORITY_METADATA_JSON: "--authority-metadata-json",
    }
    for variable in (
        LOOM_AUTHORITY_BACKEND,
        LOOM_AUTHORITY_PROFILE,
        LOOM_AUTHORITY_ENDPOINT,
        LOOM_AUTHORITY_WORKSPACE,
        LOOM_AUTHORITY_STATE,
        LOOM_AUTHORITY_REFERENCE_ID,
        LOOM_AUTHORITY_METADATA_JSON,
    ):
        value = env.get(variable)
        if value is not None:
            args.extend((flag_by_var[variable], value))
    return tuple(args)


def authority_config_from_mapping(
    *,
    backend_kind: str | None = None,
    deployment_profile: str | None = None,
    endpoint: str | None = None,
    workspace_id: str | None = None,
    state_path: str | None = None,
    reference_id: str | None = None,
    metadata_json: str | None = None,
    default: AuthorityConfig | None = None,
) -> AuthorityConfig:
    """Resolve explicit authority option values over the environment/default."""

    fallback = authority_config_from_env(default=default)
    explicit_values = (
        backend_kind,
        deployment_profile,
        endpoint,
        workspace_id,
        state_path,
        reference_id,
        metadata_json,
    )
    if all(value in {None, ""} for value in explicit_values):
        return fallback
    if backend_kind in {None, ""}:
        backend = (
            AuthorityBackendKind.CO_LOCATED_SERVICE
            if endpoint not in {None, ""}
            else fallback.backend_kind
        )
    else:
        backend = _enum(backend_kind, AuthorityBackendKind, "backend_kind")
    profile = (
        default_deployment_profile_for_backend(backend)
        if deployment_profile in {None, ""}
        and (backend_kind not in {None, ""} or endpoint not in {None, ""})
        else (
            fallback.deployment_profile
            if deployment_profile in {None, ""}
            else _enum(
                deployment_profile,
                AuthorityDeploymentProfile,
                "deployment_profile",
            )
        )
    )
    metadata = (
        fallback.metadata
        if metadata_json in {None, ""}
        else _metadata_from_json(cast(str, metadata_json))
    )
    return AuthorityConfig(
        backend_kind=backend,
        deployment_profile=profile,
        endpoint=_blank_to_none(endpoint) or fallback.endpoint,
        workspace_id=_blank_to_none(workspace_id) or fallback.workspace_id,
        state_path=_blank_to_none(state_path) or fallback.state_path,
        reference_id=_blank_to_none(reference_id) or fallback.reference_id,
        redaction_keys=fallback.redaction_keys,
        metadata=metadata,
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


def _blank_to_none(value: str | None) -> str | None:
    return None if value is None or value == "" else value


def _metadata_from_json(value: str) -> Mapping[str, PlainData]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AuthorityConfigError(
            f"{LOOM_AUTHORITY_METADATA_JSON} must contain JSON object metadata"
        ) from exc
    return _plain_mapping(decoded, "metadata")


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
    "LOOM_AUTHORITY_BACKEND",
    "LOOM_AUTHORITY_ENDPOINT",
    "LOOM_AUTHORITY_METADATA_JSON",
    "LOOM_AUTHORITY_PROFILE",
    "LOOM_AUTHORITY_REFERENCE_ID",
    "LOOM_AUTHORITY_STATE",
    "LOOM_AUTHORITY_WORKSPACE",
    "authority_config_from_env",
    "authority_config_from_mapping",
    "authority_config_to_cli_args",
    "authority_config_to_env",
    "default_deployment_profile_for_backend",
]
