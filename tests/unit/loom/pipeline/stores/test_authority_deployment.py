"""Unit coverage for authority deployment profile diagnostics."""

from __future__ import annotations

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    describe_authority_deployment,
    preflight_authority_deployment,
)


def _capabilities(
    *capabilities: tuple[BackendCapability, CapabilityScope],
) -> BackendCapabilitySet:
    return BackendCapabilitySet(
        backend_name="deployment-test-authority",
        records=tuple(
            BackendCapabilityRecord(capability=capability, scope=scope)
            for capability, scope in capabilities
        ),
    )


def _live_worker_capabilities() -> BackendCapabilitySet:
    per_run = CapabilityScope.PER_RUN
    cross_run = CapabilityScope.CROSS_RUN
    return _capabilities(
        (BackendCapability.MULTI_HOST_AUTHORITY, cross_run),
        (BackendCapability.SERVICE_ENDPOINT, cross_run),
        (BackendCapability.BACKEND_LEASE_TIME, per_run),
        (BackendCapability.STAGE_LEASES, per_run),
        (BackendCapability.FENCING_TOKENS, per_run),
        (BackendCapability.ATOMIC_OUTPUT_COMMIT, per_run),
    )


def test_managed_service_preflight_reports_missing_endpoint_health_and_compute() -> (
    None
):
    result = preflight_authority_deployment(
        config=AuthorityConfig(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
        ),
        capabilities=_live_worker_capabilities(),
        require_live_worker=True,
    )

    assert not result.supported
    assert {diagnostic.code for diagnostic in result.diagnostics} == {
        "authority_profile.missing_endpoint",
        "authority_profile.compute_to_authority_unproven",
        "authority_profile.service_health_unproven",
    }


def test_managed_service_live_preflight_passes_when_requirements_are_proven() -> None:
    result = preflight_authority_deployment(
        config=AuthorityConfig(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            endpoint="tcp://authority.example.invalid:9000",
        ),
        capabilities=_live_worker_capabilities(),
        require_live_worker=True,
        compute_to_authority_reachable=True,
        service_healthy=True,
    )

    assert result.supported
    assert result.diagnostics == ()
    assert "fencing_token" in result.summary.required_handoff_fields


def test_co_located_profile_downgrades_live_worker_authority() -> None:
    result = preflight_authority_deployment(
        config=AuthorityConfig(
            backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.CO_LOCATED,
        ),
        capabilities=_capabilities(),
        require_live_worker=True,
        compute_to_authority_reachable=True,
        service_healthy=True,
    )

    assert not result.supported
    assert result.summary.live_worker_authority is False
    assert "live_submitted_workers" in result.summary.unavailable_features
    assert {
        "authority_profile.live_worker_unavailable",
        "authority.unsupported_profile",
    } <= {diagnostic.code for diagnostic in result.diagnostics}


def test_deferred_profile_separates_envelope_handoff_from_live_fencing() -> None:
    config = AuthorityConfig(
        backend_kind=AuthorityBackendKind.DEFERRED_FINALIZATION,
        deployment_profile=AuthorityDeploymentProfile.DEFERRED_FINALIZATION,
    )
    result = preflight_authority_deployment(
        config=config,
        capabilities=_capabilities(
            (BackendCapability.DEFERRED_FINALIZATION, CapabilityScope.PER_RUN)
        ),
        require_deferred_finalization=True,
    )

    assert result.supported
    assert result.summary.deferred_finalization is True
    assert result.summary.live_worker_authority is False
    assert "result_envelope" in result.summary.required_handoff_fields
    assert "fencing_token" not in result.summary.required_handoff_fields


def test_describe_allocation_scoped_service_records_scheduler_handoff() -> None:
    summary = describe_authority_deployment(
        AuthorityConfig(
            backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
            endpoint="tcp://127.0.0.1:9000",
        )
    )

    assert summary.service_lifetime == "scheduler-allocation"
    assert summary.compute_to_authority_required is True
    assert {
        "service_start",
        "health_check",
        "endpoint_distribution",
        "shutdown",
    } <= set(summary.required_handoff_fields)
