"""Authority guard helpers for live SLURM mutation paths."""

from __future__ import annotations

from dataclasses import dataclass

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    AuthorityServiceHealthState,
    probe_http_authority_readiness,
)
from loom.serialization import PlainData


@dataclass(frozen=True, slots=True)
class SlurmLiveAuthorityFacts:
    """Safe authority facts for SLURM submitted-operation metadata."""

    config: AuthorityConfig
    backend_name: str | None = None

    def to_metadata(self) -> dict[str, PlainData]:
        reference = self.config.to_reference()
        return {
            "backend_kind": self.config.backend_kind.value,
            "deployment_profile": self.config.deployment_profile.value,
            "backend_name": self.backend_name,
            "mutation_source": "authority_service",
            "reference": reference.redacted_dict(self.config.redaction_keys),
        }


def slurm_live_authority_facts(run_store: object) -> SlurmLiveAuthorityFacts | None:
    """Return live SLURM authority facts, or ``None`` when mutation is unsafe."""

    authority_store = getattr(run_store, "authority_store", None)
    if authority_store is None:
        return None
    config_provider = getattr(run_store, "authority_config", None)
    config = config_provider() if callable(config_provider) else None
    if not isinstance(config, AuthorityConfig):
        return None
    if not _service_profile(config):
        return None
    if _requires_live_endpoint_readiness(authority_store) and not _endpoint_ready(
        config
    ):
        return None
    backend_name = None
    capabilities = getattr(authority_store, "capabilities", None)
    if callable(capabilities):
        raw_backend_name = getattr(capabilities(), "backend_name", None)
        if isinstance(raw_backend_name, str):
            backend_name = raw_backend_name
    return SlurmLiveAuthorityFacts(config=config, backend_name=backend_name)


def _requires_live_endpoint_readiness(authority_store: object) -> bool:
    return bool(getattr(authority_store, "requires_live_endpoint_readiness", False))


def _endpoint_ready(config: AuthorityConfig) -> bool:
    endpoint = config.endpoint
    if endpoint is None:
        return False
    health = probe_http_authority_readiness(endpoint)
    return health.state is AuthorityServiceHealthState.READY


def _service_profile(config: AuthorityConfig) -> bool:
    if (
        config.backend_kind is AuthorityBackendKind.DIRECT_DATABASE
        or config.deployment_profile is AuthorityDeploymentProfile.DIRECT_DATABASE
    ):
        return False
    return config.deployment_profile in {
        AuthorityDeploymentProfile.MANAGED_SERVICE,
        AuthorityDeploymentProfile.ALLOCATION_SCOPED,
    }


__all__ = ["SlurmLiveAuthorityFacts", "slurm_live_authority_facts"]
