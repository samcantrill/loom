"""Dependency values for the authority service skeleton."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from loom.pipeline.stores import (
    AuthorityProtocolReadiness,
    AuthorityProtocolVersion,
    AuthorityReadinessState,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    CapabilitySupport,
    StoreDiagnostic,
)

from ._repository import AuthorityRepository
from .mutation_service import AuthorityMutationService


DEFAULT_AUTHORITY_SERVICE_GENERATION = "authority-fastapi-skeleton"
DEFAULT_AUTHORITY_BACKEND_NAME = "fastapi-authority-skeleton"
REPOSITORY_AUTHORITY_BACKEND_NAME = "fastapi-authority-repository"
AUTHORITY_SERVICES_STATE_KEY = "authority_services"
AUTHORITY_PEER_CERTIFICATE_FINGERPRINT_STATE_KEY = (
    "authority_peer_certificate_fingerprint"
)


class AuthorityRouteGroup(StrEnum):
    """Route ownership groups exposed by the skeleton."""

    SUPERVISOR = "supervisor"
    MUTATION = "authority_mutation"
    COORDINATOR = "coordinator_authority"


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
    repository: AuthorityRepository | None = None
    mutation_service: AuthorityMutationService | None = None
    coordinator_credentials: Mapping[str, str] | None = None

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
        if self.repository is not None and not isinstance(
            self.repository,
            AuthorityRepository,
        ):
            raise TypeError("repository must be an AuthorityRepository or None")
        if self.mutation_service is not None and not isinstance(
            self.mutation_service,
            AuthorityMutationService,
        ):
            raise TypeError(
                "mutation_service must be an AuthorityMutationService or None"
            )
        credentials = self.coordinator_credentials
        if credentials is not None:
            normalized: dict[str, str] = {}
            for service_id, fingerprint in credentials.items():
                service = _non_empty_string(service_id, "coordinator service ID")
                if (
                    not isinstance(fingerprint, str)
                    or len(fingerprint) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in fingerprint
                    )
                ):
                    raise ValueError(
                        "coordinator credential fingerprint must be lowercase SHA-256"
                    )
                normalized[service] = fingerprint
            object.__setattr__(
                self,
                "coordinator_credentials",
                MappingProxyType(normalized),
            )
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


def repository_authority_capabilities() -> BackendCapabilitySet:
    """Return capability facts for a repository-backed authority service."""

    supported = (
        BackendCapability.RUN_ADMISSION,
        BackendCapability.ATOMIC_TRANSITIONS,
        BackendCapability.ATTEMPT_ALLOCATION,
        BackendCapability.RUN_LEASES,
        BackendCapability.STAGE_LEASES,
        BackendCapability.LEASE_TTL,
        BackendCapability.FENCING_TOKENS,
        BackendCapability.BACKEND_LEASE_TIME,
        BackendCapability.ATOMIC_OUTPUT_COMMIT,
        BackendCapability.ARTIFACT_FACTS,
        BackendCapability.SUBMITTED_OPERATIONS,
        BackendCapability.REVISIONED_SNAPSHOTS,
        BackendCapability.MONOTONIC_REVISIONS,
        BackendCapability.RECOVERY_SCANS,
        BackendCapability.CONSISTENT_READS,
        BackendCapability.TRANSACTION_ISOLATION,
        BackendCapability.CLOCK_SEMANTICS,
        BackendCapability.AUDIT_EVENTS,
        BackendCapability.SINGLE_HOST_AUTHORITY,
        BackendCapability.SERVICE_ENDPOINT,
        BackendCapability.OFFLINE_IMPORT,
    )
    unsupported = {
        BackendCapability.CROSS_RUN_COORDINATION:
            "workspace coordination is implemented in a later v10 phase",
        BackendCapability.GLOBAL_COUNTERS:
            "workspace counters are implemented in a later v10 phase",
        BackendCapability.DEFERRED_FINALIZATION:
            "deferred finalization remains separate from the mutation API",
        BackendCapability.MULTI_HOST_AUTHORITY:
            "the local FastAPI authority does not provide hosted multi-host semantics",
    }
    return BackendCapabilitySet(
        backend_name=REPOSITORY_AUTHORITY_BACKEND_NAME,
        records=tuple(
            BackendCapabilityRecord(
                capability=capability,
                scope=CapabilityScope.PER_RUN,
                detail={"service_boundary": True},
            )
            for capability in supported
        )
        + tuple(
            BackendCapabilityRecord(
                capability=capability,
                scope=CapabilityScope.CROSS_RUN
                if capability
                in {
                    BackendCapability.CROSS_RUN_COORDINATION,
                    BackendCapability.GLOBAL_COUNTERS,
                }
                else CapabilityScope.PER_RUN,
                support=CapabilitySupport.UNSUPPORTED,
                message=message,
                detail={"service_boundary": True},
            )
            for capability, message in unsupported.items()
        ),
    )


def default_authority_services() -> AuthorityAppServices:
    """Return default injected services for a skeleton app."""

    return AuthorityAppServices()


def repository_authority_services(
    repository: AuthorityRepository,
    *,
    workspace_id: str | None = None,
    coordinator_credentials: Mapping[str, str] | None = None,
) -> AuthorityAppServices:
    """Return app services backed by a private authority repository."""

    identity = repository.read_identity()
    mutation_service = AuthorityMutationService(
        repository,
        service_generation=identity.service_generation,
        workspace_id=workspace_id,
    )
    return AuthorityAppServices(
        service_generation=identity.service_generation,
        workspace_id=workspace_id,
        readiness=AuthorityReadinessState.READY,
        capabilities=repository_authority_capabilities(),
        repository=repository,
        mutation_service=mutation_service,
        coordinator_credentials=coordinator_credentials,
    )


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
    "REPOSITORY_AUTHORITY_BACKEND_NAME",
    "AUTHORITY_SERVICES_STATE_KEY",
    "AuthorityAppServices",
    "AuthorityRouteGroup",
    "default_authority_capabilities",
    "default_authority_services",
    "repository_authority_capabilities",
    "repository_authority_services",
]
