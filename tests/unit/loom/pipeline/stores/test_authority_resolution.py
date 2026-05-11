"""Unit coverage for authority mode resolution contracts."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    AuthorityReference,
    AuthorityReferenceSource,
    AuthorityRegistryHint,
    AuthorityResolutionDiagnosticSeverity,
    AuthorityResolutionFailureKind,
    AuthorityResolutionMode,
    AuthorityResolutionOutcomeKind,
    AuthorityResolverInput,
    AuthorityServiceHealth,
    AuthorityServiceHealthState,
    authority_resolution_mode_from_env,
    authority_resolution_mode_from_mapping,
    authority_resolution_mode_to_env,
    resolve_authority,
)

pytestmark = pytest.mark.unit


def test_offline_first_resolution_is_explicit_and_non_authoritative() -> None:
    result = resolve_authority(
        AuthorityResolverInput(mode=AuthorityResolutionMode.OFFLINE_FIRST)
    )

    assert result.succeeded
    assert result.outcome_kind is AuthorityResolutionOutcomeKind.OFFLINE_FIRST
    assert result.reference is None
    assert result.reference_source is AuthorityReferenceSource.NONE
    assert not result.authoritative
    assert result.diagnostics[0].severity is AuthorityResolutionDiagnosticSeverity.INFO
    assert "offline evidence" in " ".join(result.diagnostics[0].next_steps)


def test_default_config_fails_closed_without_starting_authority() -> None:
    result = resolve_authority(AuthorityResolverInput(config=AuthorityConfig()))

    assert not result.succeeded
    assert result.failure_kind is AuthorityResolutionFailureKind.MISSING_AUTHORITY
    assert result.diagnostics[0].code == "authority_resolution.missing_authority"
    assert "loom authority start" in result.diagnostics[0].next_steps[0]


def test_direct_database_is_reserved_for_online_mutation() -> None:
    result = resolve_authority(
        AuthorityResolverInput(
            config=AuthorityConfig(
                backend_kind=AuthorityBackendKind.DIRECT_DATABASE,
                deployment_profile=AuthorityDeploymentProfile.DIRECT_DATABASE,
                state_path="/tmp/authority.sqlite",
            )
        )
    )

    assert not result.succeeded
    assert (
        result.failure_kind
        is AuthorityResolutionFailureKind.RESERVED_DIRECT_DATABASE
    )
    assert result.diagnostics[0].detail == {"backend_kind": "direct_database"}


def test_explicit_endpoint_resolves_as_online_authority() -> None:
    result = resolve_authority(
        AuthorityResolverInput(
            config=AuthorityConfig(
                backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
                deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
                endpoint="tcp://127.0.0.1:12345",
                reference_id="managed",
            ),
            service_health=AuthorityServiceHealth(
                state=AuthorityServiceHealthState.READY,
                service_generation="gen-1",
                protocol_compatible=True,
            ),
            expected_generation="gen-1",
        )
    )

    assert result.succeeded
    assert result.outcome_kind is AuthorityResolutionOutcomeKind.ONLINE_AUTHORITY
    assert result.reference_source is AuthorityReferenceSource.EXPLICIT_CONFIG
    assert result.reference is not None
    assert result.reference.endpoint == "tcp://127.0.0.1:12345"
    assert result.authoritative


def test_registry_hint_can_resolve_without_file_io() -> None:
    reference = AuthorityReference(
        backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
        deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
        reference_id="allocation",
        endpoint="tcp://127.0.0.1:22345",
        workspace_id="workspace-1",
    )

    result = resolve_authority(
        AuthorityResolverInput(
            registry_hint=AuthorityRegistryHint(
                reference=reference,
                workspace_matches=True,
                expected_generation="gen-1",
                observed_generation="gen-1",
                protocol_compatible=True,
            )
        )
    )

    assert result.succeeded
    assert result.reference_source is AuthorityReferenceSource.REGISTRY_HINT
    assert result.reference == reference


@pytest.mark.parametrize(
    ("registry_hint", "failure_kind"),
    [
        (
            AuthorityRegistryHint(
                reference=AuthorityReference(
                    backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE,
                    deployment_profile=AuthorityDeploymentProfile.CO_LOCATED,
                    reference_id="stale",
                    endpoint="tcp://127.0.0.1:1",
                ),
                stale=True,
            ),
            AuthorityResolutionFailureKind.STALE_REGISTRY,
        ),
        (
            AuthorityRegistryHint(
                reference=AuthorityReference(
                    backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE,
                    deployment_profile=AuthorityDeploymentProfile.CO_LOCATED,
                    reference_id="wrong-workspace",
                    endpoint="tcp://127.0.0.1:1",
                ),
                workspace_matches=False,
            ),
            AuthorityResolutionFailureKind.WRONG_WORKSPACE,
        ),
        (
            AuthorityRegistryHint(
                reference=AuthorityReference(
                    backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE,
                    deployment_profile=AuthorityDeploymentProfile.CO_LOCATED,
                    reference_id="incompatible",
                    endpoint="tcp://127.0.0.1:1",
                ),
                protocol_compatible=False,
            ),
            AuthorityResolutionFailureKind.INCOMPATIBLE_VERSION,
        ),
    ],
)
def test_registry_hint_failures_are_typed(
    registry_hint: AuthorityRegistryHint,
    failure_kind: AuthorityResolutionFailureKind,
) -> None:
    result = resolve_authority(AuthorityResolverInput(registry_hint=registry_hint))

    assert not result.succeeded
    assert result.failure_kind is failure_kind


def test_generation_mismatch_is_typed() -> None:
    result = resolve_authority(
        AuthorityResolverInput(
            config=AuthorityConfig(endpoint="tcp://127.0.0.1:12345"),
            expected_generation="expected",
            service_health=AuthorityServiceHealth(
                state=AuthorityServiceHealthState.READY,
                service_generation="observed",
            ),
        )
    )

    assert not result.succeeded
    assert result.failure_kind is AuthorityResolutionFailureKind.INCOMPATIBLE_GENERATION
    assert result.diagnostics[0].detail == {
        "expected_generation": "expected",
        "observed_generation": "observed",
    }


@pytest.mark.parametrize(
    ("health", "failure_kind"),
    [
        (
            AuthorityServiceHealth(state=AuthorityServiceHealthState.UNAVAILABLE),
            AuthorityResolutionFailureKind.UNAVAILABLE_SERVICE,
        ),
        (
            AuthorityServiceHealth(state=AuthorityServiceHealthState.UNHEALTHY),
            AuthorityResolutionFailureKind.UNHEALTHY_SERVICE,
        ),
        (
            AuthorityServiceHealth(protocol_compatible=False),
            AuthorityResolutionFailureKind.INCOMPATIBLE_VERSION,
        ),
    ],
)
def test_service_health_failures_are_typed(
    health: AuthorityServiceHealth,
    failure_kind: AuthorityResolutionFailureKind,
) -> None:
    result = resolve_authority(
        AuthorityResolverInput(
            config=AuthorityConfig(endpoint="tcp://127.0.0.1:12345"),
            service_health=health,
        )
    )

    assert not result.succeeded
    assert result.failure_kind is failure_kind


def test_authority_resolution_mode_environment_round_trip() -> None:
    env = authority_resolution_mode_to_env(AuthorityResolutionMode.OFFLINE_FIRST)

    assert env == {"LOOM_AUTHORITY_MODE": "offline_first"}
    assert (
        authority_resolution_mode_from_env(env)
        is AuthorityResolutionMode.OFFLINE_FIRST
    )
    assert (
        authority_resolution_mode_from_env({})
        is AuthorityResolutionMode.ONLINE_MUTATION
    )


def test_authority_resolution_mode_mapping_prefers_explicit_mode() -> None:
    assert (
        authority_resolution_mode_from_mapping(
            authority_mode="online_mutation",
            offline_first=True,
        )
        is AuthorityResolutionMode.ONLINE_MUTATION
    )
    assert (
        authority_resolution_mode_from_mapping(offline_first=True)
        is AuthorityResolutionMode.OFFLINE_FIRST
    )
