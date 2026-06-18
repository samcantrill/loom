"""Contract coverage for authority resolution result categories."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    AuthorityReference,
    AuthorityRegistryRecord,
    AuthorityRegistryHint,
    AuthorityResolutionFailureKind,
    AuthorityResolutionMode,
    AuthorityResolutionOutcomeKind,
    AuthorityResolverInput,
    AuthorityServiceHealth,
    AuthorityServiceHealthState,
    AuthorityRegistryValidationStatus,
    validate_authority_registry_record,
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
                        backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
                        deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
                        reference_id="missing-endpoint",
                    )
                )
            ),
            AuthorityResolutionFailureKind.MISSING_AUTHORITY,
        ),
        (
            AuthorityResolverInput(
                registry_hint=AuthorityRegistryHint(
                    reference=AuthorityReference(
                        backend_kind=AuthorityBackendKind.DIRECT_DATABASE,
                        deployment_profile=AuthorityDeploymentProfile.DIRECT_DATABASE,
                        reference_id="direct-db",
                        state_path="/tmp/authority.sqlite",
                    )
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


@pytest.mark.parametrize(
    ("validation_status", "expected_failure"),
    [
        (
            AuthorityRegistryValidationStatus.STALE,
            AuthorityResolutionFailureKind.STALE_REGISTRY,
        ),
        (
            AuthorityRegistryValidationStatus.WRONG_WORKSPACE,
            AuthorityResolutionFailureKind.WRONG_WORKSPACE,
        ),
        (
            AuthorityRegistryValidationStatus.INCOMPATIBLE_GENERATION,
            AuthorityResolutionFailureKind.INCOMPATIBLE_GENERATION,
        ),
        (
            AuthorityRegistryValidationStatus.UNAVAILABLE_SERVICE,
            AuthorityResolutionFailureKind.UNAVAILABLE_SERVICE,
        ),
    ],
)
def test_authority_registry_validation_contract_maps_to_resolver_failures(
    validation_status: AuthorityRegistryValidationStatus,
    expected_failure: AuthorityResolutionFailureKind,
) -> None:
    record = AuthorityRegistryRecord(
        reference=AuthorityReference(
            backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
            reference_id="registry-authority",
            endpoint="tcp://127.0.0.1:1",
            workspace_id="workspace-a",
            state_path="/tmp/authority-state",
        ),
        service_generation="generation-1",
        workspace_id="workspace-a",
        state_dir="/tmp/authority-state",
        expires_at="2026-05-11T09:59:59Z"
        if validation_status is AuthorityRegistryValidationStatus.STALE
        else None,
        service_health_state=AuthorityServiceHealthState.UNAVAILABLE
        if validation_status is AuthorityRegistryValidationStatus.UNAVAILABLE_SERVICE
        else AuthorityServiceHealthState.READY,
    )
    validation = validate_authority_registry_record(
        record,
        expected_workspace_id="workspace-b"
        if validation_status is AuthorityRegistryValidationStatus.WRONG_WORKSPACE
        else "workspace-a",
        expected_generation="generation-old"
        if validation_status is AuthorityRegistryValidationStatus.INCOMPATIBLE_GENERATION
        else "generation-1",
        now="2026-05-11T10:00:00Z",
    )

    assert validation.status is validation_status
    result = resolve_authority(
        AuthorityResolverInput(
            registry_hint=validation.registry_hint,
            service_health=validation.service_health,
        )
    )

    assert result.failure_kind is expected_failure
