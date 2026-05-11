"""Contract coverage for authority resolution result categories."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    AuthorityReference,
    AuthorityRegistryHint,
    AuthorityResolutionFailureKind,
    AuthorityResolutionMode,
    AuthorityResolutionOutcomeKind,
    AuthorityResolverInput,
    AuthorityServiceHealth,
    AuthorityServiceHealthState,
    resolve_authority,
)

pytestmark = pytest.mark.contract


def test_authority_resolution_contract_distinguishes_online_and_offline() -> None:
    online = resolve_authority(
        AuthorityResolverInput(
            config=AuthorityConfig(endpoint="tcp://127.0.0.1:12345")
        )
    )
    offline = resolve_authority(
        AuthorityResolverInput(mode=AuthorityResolutionMode.OFFLINE_FIRST)
    )

    assert online.to_dict()["outcome_kind"] == "online_authority"
    assert online.to_dict()["authoritative"] is True
    assert online.to_dict()["reference"] is not None
    assert offline.to_dict()["outcome_kind"] == "offline_first"
    assert offline.to_dict()["authoritative"] is False
    assert offline.to_dict()["reference"] is None


@pytest.mark.parametrize(
    ("resolver_input", "failure_kind"),
    [
        (
            AuthorityResolverInput(),
            AuthorityResolutionFailureKind.MISSING_AUTHORITY,
        ),
        (
            AuthorityResolverInput(
                config=AuthorityConfig(
                    backend_kind=AuthorityBackendKind.DIRECT_DATABASE,
                    deployment_profile=AuthorityDeploymentProfile.DIRECT_DATABASE,
                    state_path="/tmp/authority.sqlite",
                )
            ),
            AuthorityResolutionFailureKind.RESERVED_DIRECT_DATABASE,
        ),
        (
            AuthorityResolverInput(
                registry_hint=AuthorityRegistryHint(
                    reference=AuthorityReference(
                        backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE,
                        deployment_profile=AuthorityDeploymentProfile.CO_LOCATED,
                        reference_id="stale",
                        endpoint="tcp://127.0.0.1:1",
                    ),
                    stale=True,
                )
            ),
            AuthorityResolutionFailureKind.STALE_REGISTRY,
        ),
        (
            AuthorityResolverInput(
                config=AuthorityConfig(endpoint="tcp://127.0.0.1:12345"),
                expected_generation="expected",
                service_health=AuthorityServiceHealth(
                    state=AuthorityServiceHealthState.READY,
                    service_generation="observed",
                ),
            ),
            AuthorityResolutionFailureKind.INCOMPATIBLE_GENERATION,
        ),
        (
            AuthorityResolverInput(
                config=AuthorityConfig(endpoint="tcp://127.0.0.1:12345"),
                service_health=AuthorityServiceHealth(protocol_compatible=False),
            ),
            AuthorityResolutionFailureKind.INCOMPATIBLE_VERSION,
        ),
        (
            AuthorityResolverInput(
                config=AuthorityConfig(endpoint="tcp://127.0.0.1:12345"),
                service_health=AuthorityServiceHealth(
                    state=AuthorityServiceHealthState.UNAVAILABLE
                ),
            ),
            AuthorityResolutionFailureKind.UNAVAILABLE_SERVICE,
        ),
        (
            AuthorityResolverInput(
                config=AuthorityConfig(endpoint="tcp://127.0.0.1:12345"),
                service_health=AuthorityServiceHealth(
                    state=AuthorityServiceHealthState.UNHEALTHY
                ),
            ),
            AuthorityResolutionFailureKind.UNHEALTHY_SERVICE,
        ),
    ],
)
def test_authority_resolution_contract_exposes_typed_failures(
    resolver_input: AuthorityResolverInput,
    failure_kind: AuthorityResolutionFailureKind,
) -> None:
    result = resolve_authority(resolver_input)
    data = result.to_dict()

    assert result.outcome_kind is AuthorityResolutionOutcomeKind.FAILED
    assert result.failure_kind is failure_kind
    assert data["outcome_kind"] == "failed"
    assert data["failure_kind"] == failure_kind.value
    assert result.diagnostics[0].code.startswith("authority_resolution.")
