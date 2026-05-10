"""Authority deployment profile diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from loom.serialization import PlainData

from .admission import (
    RequiredAuthorityCapability,
    admit_authority_capabilities,
)
from .capabilities import BackendCapabilitySet, DiagnosticSeverity, StoreDiagnostic
from .config import AuthorityConfig, AuthorityDeploymentProfile


class AuthorityDeploymentError(ValueError):
    """Raised when authority deployment diagnostics are invalid."""


@dataclass(frozen=True, slots=True)
class AuthorityDeploymentProfileSummary:
    """Serializable description of a selected authority deployment profile."""

    config: AuthorityConfig
    service_lifetime: str
    live_worker_authority: bool
    deferred_finalization: bool
    multi_host_authority: bool
    endpoint_required: bool
    compute_to_authority_required: bool
    required_handoff_fields: tuple[str, ...]
    unavailable_features: tuple[str, ...] = ()
    diagnostics: tuple[StoreDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.config, AuthorityConfig):
            raise AuthorityDeploymentError("config must be an AuthorityConfig")
        object.__setattr__(
            self, "service_lifetime", _non_empty_string(self.service_lifetime)
        )
        object.__setattr__(
            self,
            "required_handoff_fields",
            tuple(_non_empty_string(field) for field in self.required_handoff_fields),
        )
        object.__setattr__(
            self,
            "unavailable_features",
            tuple(_non_empty_string(feature) for feature in self.unavailable_features),
        )
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(diagnostic, StoreDiagnostic) for diagnostic in diagnostics):
            raise AuthorityDeploymentError(
                "diagnostics must contain StoreDiagnostic values"
            )
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def profile(self) -> AuthorityDeploymentProfile:
        return self.config.deployment_profile

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "backend_kind": self.config.backend_kind.value,
            "deployment_profile": self.profile.value,
            "authority": self.config.redacted_dict(),
            "service_lifetime": self.service_lifetime,
            "live_worker_authority": self.live_worker_authority,
            "deferred_finalization": self.deferred_finalization,
            "multi_host_authority": self.multi_host_authority,
            "endpoint_required": self.endpoint_required,
            "compute_to_authority_required": self.compute_to_authority_required,
            "required_handoff_fields": list(self.required_handoff_fields),
            "unavailable_features": list(self.unavailable_features),
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
        }


@dataclass(frozen=True, slots=True)
class AuthorityDeploymentPreflightResult:
    """Deterministic preflight result for one authority deployment profile."""

    summary: AuthorityDeploymentProfileSummary
    requirements: Mapping[str, PlainData] = field(default_factory=dict)
    diagnostics: tuple[StoreDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.summary, AuthorityDeploymentProfileSummary):
            raise AuthorityDeploymentError(
                "summary must be an AuthorityDeploymentProfileSummary"
            )
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(diagnostic, StoreDiagnostic) for diagnostic in diagnostics):
            raise AuthorityDeploymentError(
                "diagnostics must contain StoreDiagnostic values"
            )
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def supported(self) -> bool:
        return not any(
            diagnostic.severity is DiagnosticSeverity.ERROR
            for diagnostic in self.diagnostics
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "supported": self.supported,
            "summary": self.summary.to_dict(),
            "requirements": dict(self.requirements),
            "diagnostics": [
                diagnostic.to_dict() for diagnostic in self.diagnostics
            ],
        }


def describe_authority_deployment(
    config: AuthorityConfig,
) -> AuthorityDeploymentProfileSummary:
    """Describe the selected authority deployment without probing the backend."""

    profile = config.deployment_profile
    match profile:
        case AuthorityDeploymentProfile.CO_LOCATED:
            summary = AuthorityDeploymentProfileSummary(
                config=config,
                service_lifetime="runner-process-or-single-host",
                live_worker_authority=False,
                deferred_finalization=False,
                multi_host_authority=False,
                endpoint_required=False,
                compute_to_authority_required=False,
                required_handoff_fields=(
                    "run_uri",
                    "stage_name",
                    "attempt_id",
                    "owner_id",
                    "authority_reference",
                ),
                unavailable_features=(
                    "live_submitted_workers",
                    "multi_host_workers",
                    "cross_run_coordination",
                    "deferred_finalization",
                ),
            )
        case AuthorityDeploymentProfile.MANAGED_SERVICE:
            summary = _live_service_summary(
                config,
                service_lifetime="external-managed-service",
                extra_handoff_fields=(),
            )
        case AuthorityDeploymentProfile.ALLOCATION_SCOPED:
            summary = _live_service_summary(
                config,
                service_lifetime="scheduler-allocation",
                extra_handoff_fields=(
                    "service_start",
                    "health_check",
                    "endpoint_distribution",
                    "shutdown",
                ),
            )
        case AuthorityDeploymentProfile.DIRECT_DATABASE:
            summary = _live_service_summary(
                config,
                service_lifetime="external-transactional-database",
                extra_handoff_fields=("database_reference",),
            )
        case AuthorityDeploymentProfile.DEFERRED_FINALIZATION:
            summary = AuthorityDeploymentProfileSummary(
                config=config,
                service_lifetime="offline-worker-result-envelope",
                live_worker_authority=False,
                deferred_finalization=True,
                multi_host_authority=False,
                endpoint_required=False,
                compute_to_authority_required=False,
                required_handoff_fields=(
                    "run_uri",
                    "stage_name",
                    "attempt_id",
                    "submission_id",
                    "owner_id",
                    "result_envelope",
                    "materialized_outputs",
                ),
                unavailable_features=(
                    "live_worker_commits",
                    "live_lease_renewal",
                    "immediate_success_visibility",
                    "live_cancellation_feedback",
                ),
            )
    return _with_static_diagnostics(summary)


def preflight_authority_deployment(
    *,
    config: AuthorityConfig,
    capabilities: BackendCapabilitySet,
    require_live_worker: bool = False,
    require_deferred_finalization: bool = False,
    compute_to_authority_reachable: bool | None = None,
    service_healthy: bool | None = None,
) -> AuthorityDeploymentPreflightResult:
    """Check deterministic deployment assumptions before worker submission."""

    summary = describe_authority_deployment(config)
    diagnostics = list(summary.diagnostics)
    required: list[RequiredAuthorityCapability] = []
    if require_live_worker:
        required.append(RequiredAuthorityCapability.SLURM_LIVE_WORKER)
        if not summary.live_worker_authority:
            diagnostics.append(
                _diagnostic(
                    "authority_profile.live_worker_unavailable",
                    "selected authority profile does not support live worker commits",
                    profile=summary.profile.value,
                )
            )
        if compute_to_authority_reachable is not True:
            diagnostics.append(
                _diagnostic(
                    "authority_profile.compute_to_authority_unproven"
                    if compute_to_authority_reachable is None
                    else "authority_profile.compute_to_authority_blocked",
                    "compute workers cannot prove reachability to authority",
                    profile=summary.profile.value,
                    reachable=compute_to_authority_reachable,
                )
            )
        if summary.endpoint_required and service_healthy is not True:
            diagnostics.append(
                _diagnostic(
                    "authority_profile.service_health_unproven"
                    if service_healthy is None
                    else "authority_profile.service_unavailable",
                    "authority service health is not proven",
                    profile=summary.profile.value,
                    service_healthy=service_healthy,
                )
            )
    if require_deferred_finalization:
        required.append(RequiredAuthorityCapability.DEFERRED_FINALIZATION_WORKER)
        if not summary.deferred_finalization:
            diagnostics.append(
                _diagnostic(
                    "authority_profile.deferred_finalization_unavailable",
                    "selected authority profile does not support deferred finalization",
                    profile=summary.profile.value,
                )
            )
    if required:
        admission = admit_authority_capabilities(
            config=config,
            capabilities=capabilities,
            required=required,
        )
        diagnostics.extend(
            StoreDiagnostic(
                code=error.code,
                message=error.message,
                severity=DiagnosticSeverity.ERROR,
                detail=error.to_dict(),
            )
            for error in admission.errors
        )
    return AuthorityDeploymentPreflightResult(
        summary=summary,
        requirements={
            "live_worker": require_live_worker,
            "deferred_finalization": require_deferred_finalization,
            "compute_to_authority_reachable": compute_to_authority_reachable,
            "service_healthy": service_healthy,
        },
        diagnostics=tuple(diagnostics),
    )


def _live_service_summary(
    config: AuthorityConfig,
    *,
    service_lifetime: str,
    extra_handoff_fields: tuple[str, ...],
) -> AuthorityDeploymentProfileSummary:
    return AuthorityDeploymentProfileSummary(
        config=config,
        service_lifetime=service_lifetime,
        live_worker_authority=True,
        deferred_finalization=False,
        multi_host_authority=True,
        endpoint_required=True,
        compute_to_authority_required=True,
        required_handoff_fields=(
            "run_uri",
            "stage_name",
            "attempt_id",
            "owner_id",
            "authority_reference",
            "endpoint",
            "lease_id",
            "fencing_token",
            *extra_handoff_fields,
        ),
        unavailable_features=("offline_worker_commits",),
    )


def _with_static_diagnostics(
    summary: AuthorityDeploymentProfileSummary,
) -> AuthorityDeploymentProfileSummary:
    diagnostics = list(summary.diagnostics)
    if summary.endpoint_required and summary.config.endpoint is None:
        diagnostics.append(
            _diagnostic(
                "authority_profile.missing_endpoint",
                "selected authority profile requires an endpoint",
                profile=summary.profile.value,
            )
        )
    return AuthorityDeploymentProfileSummary(
        config=summary.config,
        service_lifetime=summary.service_lifetime,
        live_worker_authority=summary.live_worker_authority,
        deferred_finalization=summary.deferred_finalization,
        multi_host_authority=summary.multi_host_authority,
        endpoint_required=summary.endpoint_required,
        compute_to_authority_required=summary.compute_to_authority_required,
        required_handoff_fields=summary.required_handoff_fields,
        unavailable_features=summary.unavailable_features,
        diagnostics=tuple(diagnostics),
    )


def _diagnostic(code: str, message: str, **detail: PlainData) -> StoreDiagnostic:
    return StoreDiagnostic(
        code=code,
        message=message,
        severity=DiagnosticSeverity.ERROR,
        detail=detail,
    )


def _non_empty_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityDeploymentError("value must be a non-empty string")
    return value


__all__ = [
    "AuthorityDeploymentError",
    "AuthorityDeploymentPreflightResult",
    "AuthorityDeploymentProfileSummary",
    "describe_authority_deployment",
    "preflight_authority_deployment",
]
