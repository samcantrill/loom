"""Strict authority factory resolution helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import socket
from urllib import error, request
from urllib.parse import urlsplit

from loom.serialization import PlainData

from .authority import AuthorityStoreError
from .authority_client import AuthorityClient, AuthorityHttpTransport
from .authority_protocol import (
    AuthorityProtocolError,
    AuthorityProtocolReadiness,
    AuthorityReadinessState,
)
from .authority_registry import (
    AuthorityRegistryValidationResult,
    validate_authority_registry,
)
from .authority_resolution import (
    AuthorityResolutionMode,
    AuthorityResolutionOutcomeKind,
    AuthorityResolutionResult,
    AuthorityResolverInput,
    AuthorityServiceHealth,
    AuthorityServiceHealthState,
    resolve_authority,
)
from .config import AuthorityConfig, AuthorityReference


DEFAULT_AUTHORITY_READINESS_TIMEOUT_SECONDS = 5.0


class AuthorityFactoryError(AuthorityStoreError):
    """Raised when strict authority factory resolution cannot return a client."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        resolution: AuthorityResolutionResult | None = None,
        context: Mapping[str, PlainData] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.resolution = resolution
        self.context = {} if context is None else dict(context)

    @property
    def diagnostics(self) -> tuple[dict[str, PlainData], ...]:
        if self.resolution is None:
            return ()
        return tuple(diagnostic.to_dict() for diagnostic in self.resolution.diagnostics)

    def to_dict(self) -> dict[str, PlainData]:
        resolution = None if self.resolution is None else self.resolution.to_dict()
        return {
            "code": self.code,
            "message": str(self),
            "context": dict(self.context),
            "resolution": resolution,
            "diagnostics": [dict(diagnostic) for diagnostic in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class AuthorityFactoryResolution:
    """Resolved authority config plus resolver and registry evidence."""

    config: AuthorityConfig
    result: AuthorityResolutionResult
    registry: AuthorityRegistryValidationResult | None = None
    readiness: AuthorityProtocolReadiness | None = None

    @property
    def reference(self) -> AuthorityReference | None:
        return self.result.reference


def resolve_authority_for_factory(
    config: AuthorityConfig | Mapping[str, object] | None = None,
    *,
    authority_mode: AuthorityResolutionMode = AuthorityResolutionMode.ONLINE_MUTATION,
    workspace_root: str | Path | None = None,
    allocation_id: str | None = None,
    expected_workspace_id: str | None = None,
    expected_generation: str | None = None,
    readiness_timeout_seconds: float | None = (
        DEFAULT_AUTHORITY_READINESS_TIMEOUT_SECONDS
    ),
    probe_http_readiness: bool = True,
) -> AuthorityFactoryResolution:
    """Resolve authority selection for mutation-capable factories."""

    resolved_config = _resolve_config(config)
    registry: AuthorityRegistryValidationResult | None = None
    service_health: AuthorityServiceHealth | None = None
    registry_hint = None

    if resolved_config.endpoint is None and workspace_root is not None:
        registry = validate_authority_registry(
            workspace_root,
            allocation_id=allocation_id,
            expected_workspace_id=expected_workspace_id,
            expected_generation=expected_generation,
        )
        registry_hint = registry.registry_hint
        service_health = registry.service_health

    endpoint = resolved_config.endpoint
    if endpoint is None and registry is not None and registry.record is not None:
        endpoint = registry.record.reference.endpoint

    readiness: AuthorityProtocolReadiness | None = None
    if probe_http_readiness and endpoint is not None and _is_http_endpoint(endpoint):
        try:
            readiness = read_http_authority_readiness(
                endpoint,
                timeout_seconds=readiness_timeout_seconds,
            )
        except (
            TimeoutError,
            socket.timeout,
            error.URLError,
            OSError,
        ) as exc:
            service_health = AuthorityServiceHealth(
                state=AuthorityServiceHealthState.UNAVAILABLE,
                message=str(exc),
            )
        except (
            AuthorityProtocolError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            service_health = AuthorityServiceHealth(
                state=AuthorityServiceHealthState.UNHEALTHY,
                protocol_compatible=False,
                message=str(exc),
            )
        else:
            service_health = _health_from_readiness(readiness)

    result = resolve_authority(
        AuthorityResolverInput(
            config=resolved_config,
            mode=authority_mode,
            registry_hint=registry_hint,
            service_health=service_health,
            expected_generation=expected_generation,
        )
    )
    return AuthorityFactoryResolution(
        config=resolved_config,
        result=result,
        registry=registry,
        readiness=readiness,
    )


def require_online_authority(
    resolution: AuthorityFactoryResolution,
    *,
    purpose: str,
) -> AuthorityReference:
    """Return an online authority reference or raise a structured factory error."""

    result = resolution.result
    if result.outcome_kind is AuthorityResolutionOutcomeKind.ONLINE_AUTHORITY:
        if result.reference is None:
            raise AuthorityFactoryError(
                "online authority resolution did not include a reference",
                code="authority_factory.missing_reference",
                resolution=result,
                context={"purpose": purpose},
            )
        return result.reference
    if result.outcome_kind is AuthorityResolutionOutcomeKind.OFFLINE_FIRST:
        raise AuthorityFactoryError(
            f"{purpose} requires online authority; offline-first evidence is not "
            "implemented for this factory yet",
            code="authority_factory.offline_unsupported",
            resolution=result,
            context={"purpose": purpose},
        )
    diagnostic = result.diagnostics[0] if result.diagnostics else None
    message = (
        diagnostic.message
        if diagnostic is not None
        else f"{purpose} could not resolve an online authority"
    )
    raise AuthorityFactoryError(
        message,
        code="authority_factory.resolution_failed",
        resolution=result,
        context={"purpose": purpose},
    )


def create_authority_client(
    config: AuthorityConfig | Mapping[str, object] | None = None,
    *,
    authority_mode: AuthorityResolutionMode = AuthorityResolutionMode.ONLINE_MUTATION,
    workspace_root: str | Path | None = None,
    allocation_id: str | None = None,
    expected_workspace_id: str | None = None,
    expected_generation: str | None = None,
    timeout_seconds: float | None = 30.0,
    transport: AuthorityHttpTransport | None = None,
) -> AuthorityClient:
    """Create a strict resolver-backed HTTP authority client."""

    resolution = resolve_authority_for_factory(
        config,
        authority_mode=authority_mode,
        workspace_root=workspace_root,
        allocation_id=allocation_id,
        expected_workspace_id=expected_workspace_id,
        expected_generation=expected_generation,
        readiness_timeout_seconds=timeout_seconds,
        probe_http_readiness=transport is None,
    )
    reference = require_online_authority(
        resolution,
        purpose="authority HTTP client construction",
    )
    if reference.endpoint is None or not _is_http_endpoint(reference.endpoint):
        raise AuthorityFactoryError(
            "authority HTTP client requires an http or https endpoint",
            code="authority_factory.unsupported_endpoint",
            resolution=resolution.result,
            context={
                "endpoint": reference.endpoint,
                "reference_id": reference.reference_id,
            },
        )
    return AuthorityClient(
        reference.endpoint,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


def probe_http_authority_readiness(
    endpoint: str,
    *,
    timeout_seconds: float | None = DEFAULT_AUTHORITY_READINESS_TIMEOUT_SECONDS,
) -> AuthorityServiceHealth:
    """Fetch `/ready` from an HTTP authority endpoint and return resolver facts."""

    if not _is_http_endpoint(endpoint):
        return AuthorityServiceHealth()
    try:
        readiness = read_http_authority_readiness(
            endpoint,
            timeout_seconds=timeout_seconds,
        )
    except (TimeoutError, socket.timeout, error.URLError, OSError) as exc:
        return AuthorityServiceHealth(
            state=AuthorityServiceHealthState.UNAVAILABLE,
            message=str(exc),
        )
    except (AuthorityProtocolError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return AuthorityServiceHealth(
            state=AuthorityServiceHealthState.UNHEALTHY,
            protocol_compatible=False,
            message=str(exc),
        )

    return _health_from_readiness(readiness)


def read_http_authority_readiness(
    endpoint: str,
    *,
    timeout_seconds: float | None = DEFAULT_AUTHORITY_READINESS_TIMEOUT_SECONDS,
) -> AuthorityProtocolReadiness:
    """Fetch and parse `/ready` from an HTTP authority endpoint."""

    if not _is_http_endpoint(endpoint):
        raise AuthorityFactoryError(
            "authority readiness requires an http or https endpoint",
            code="authority_factory.unsupported_endpoint",
            context={"endpoint": endpoint},
        )
    with request.urlopen(
        request.Request(_join_url(endpoint, "/ready")),
        timeout=timeout_seconds,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return AuthorityProtocolReadiness.from_dict(payload)


def _health_from_readiness(readiness: AuthorityProtocolReadiness) -> AuthorityServiceHealth:
    state = (
        AuthorityServiceHealthState.READY
        if readiness.ready
        else AuthorityServiceHealthState.UNHEALTHY
    )
    if readiness.readiness is AuthorityReadinessState.UNAVAILABLE:
        state = AuthorityServiceHealthState.UNAVAILABLE
    return AuthorityServiceHealth(
        state=state,
        service_generation=readiness.service_generation,
        protocol_version=str(readiness.version.protocol_version),
        protocol_compatible=readiness.version.supported,
        message=None if readiness.ready else readiness.readiness.value,
    )


def config_from_authority_reference(reference: AuthorityReference) -> AuthorityConfig:
    """Convert a resolved authority reference back to public config."""

    return AuthorityConfig(
        backend_kind=reference.backend_kind,
        deployment_profile=reference.deployment_profile,
        endpoint=reference.endpoint,
        workspace_id=reference.workspace_id,
        state_path=reference.state_path,
        reference_id=reference.reference_id,
        metadata=reference.metadata,
    )


def _resolve_config(
    config: AuthorityConfig | Mapping[str, object] | None,
) -> AuthorityConfig:
    if config is None:
        return AuthorityConfig()
    if isinstance(config, AuthorityConfig):
        return config
    return AuthorityConfig.from_dict(config)


def _is_http_endpoint(endpoint: str) -> bool:
    return urlsplit(endpoint).scheme in {"http", "https"}


def _join_url(endpoint: str, path: str) -> str:
    return f"{endpoint.rstrip('/')}/{path.lstrip('/')}"


__all__ = [
    "DEFAULT_AUTHORITY_READINESS_TIMEOUT_SECONDS",
    "AuthorityFactoryError",
    "AuthorityFactoryResolution",
    "config_from_authority_reference",
    "create_authority_client",
    "probe_http_authority_readiness",
    "read_http_authority_readiness",
    "require_online_authority",
    "resolve_authority_for_factory",
]
