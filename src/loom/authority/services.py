"""Dependency values for the authority service skeleton."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.pipeline.stores import (
    AuthorityProtocolReadiness,
    AuthorityProtocolVersion,
    AuthorityReadinessState,
    BackendCapabilitySet,
    StoreDiagnostic,
)


DEFAULT_AUTHORITY_SERVICE_GENERATION = "authority-fastapi-skeleton"
DEFAULT_AUTHORITY_BACKEND_NAME = "fastapi-authority-skeleton"


class AuthorityRouteGroup(StrEnum):
    """Route ownership groups exposed by the skeleton."""

    SUPERVISOR = "supervisor"
    MUTATION = "authority_mutation"


@dataclass(frozen=True, slots=True)
class AuthorityAppServices:
    """Injected dependencies and service facts for authority routes."""

    service_generation: str = DEFAULT_AUTHORITY_SERVICE_GENERATION
    workspace_id: str | None = None
    readiness: AuthorityReadinessState = AuthorityReadinessState.READY
    capabilities: BackendCapabilitySet = field(
        default_factory=lambda: default_authority_capabilities()
    )
    diagnostics: tuple[StoreDiagnostic, ...] = ()
    repository: object | None = None
    mutation_service: object | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "service_generation",
            _non_empty_string(self.service_generation, "service_generation"),
        )
        if self.workspace_id is not None:
            object.__setattr__(
                self,
                "workspace_id",
                _non_empty_string(self.workspace_id, "workspace_id"),
            )
        object.__setattr__(
            self,
            "readiness",
            _coerce_readiness(self.readiness),
        )
        if not isinstance(self.capabilities, BackendCapabilitySet):
            raise TypeError("capabilities must be a BackendCapabilitySet")
        object.__setattr__(
            self,
            "diagnostics",
            _tuple_of_diagnostics(self.diagnostics),
        )

    @property
    def version_report(self) -> AuthorityProtocolVersion:
        return AuthorityProtocolVersion()

    @property
    def readiness_report(self) -> AuthorityProtocolReadiness:
        return AuthorityProtocolReadiness(
            version=self.version_report,
            readiness=self.readiness,
            capabilities=self.capabilities,
            service_generation=self.service_generation,
            workspace_id=self.workspace_id,
            diagnostics=self.diagnostics,
        )


def default_authority_capabilities() -> BackendCapabilitySet:
    """Return conservative skeleton capability facts."""

    return BackendCapabilitySet(
        backend_name=DEFAULT_AUTHORITY_BACKEND_NAME,
        records=(),
    )


def default_authority_services() -> AuthorityAppServices:
    """Return default injected services for a skeleton app."""

    return AuthorityAppServices()


def _coerce_readiness(value: object) -> AuthorityReadinessState:
    if isinstance(value, AuthorityReadinessState):
        return value
    if not isinstance(value, str):
        raise TypeError("readiness must be an AuthorityReadinessState or string")
    try:
        return AuthorityReadinessState(value)
    except ValueError as exc:
        raise ValueError(f"invalid readiness {value!r}") from exc


def _tuple_of_diagnostics(
    values: Sequence[object],
) -> tuple[StoreDiagnostic, ...]:
    items = tuple(values)
    if any(not isinstance(item, StoreDiagnostic) for item in items):
        raise TypeError("diagnostics must contain StoreDiagnostic values")
    return cast(tuple[StoreDiagnostic, ...], items)


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "DEFAULT_AUTHORITY_BACKEND_NAME",
    "DEFAULT_AUTHORITY_SERVICE_GENERATION",
    "AuthorityAppServices",
    "AuthorityRouteGroup",
    "default_authority_capabilities",
    "default_authority_services",
]
