"""Integration coverage for authority deployment profiles."""

from __future__ import annotations

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityDeploymentProfile,
    DeferredReconciliationCode,
    DeferredResultEnvelope,
    preflight_authority_deployment,
    reconcile_deferred_result,
)
from loom.pipeline.stores.service_authority import (
    LocalAuthorityService,
    create_service_authority_store,
)
from tests.support.deferred_finalization import submitted_operation

pytestmark = pytest.mark.integration


def test_local_service_profile_does_not_claim_live_multi_host_authority() -> None:
    with LocalAuthorityService.start() as service:
        config = service.config(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
        )
        authority = create_service_authority_store(config)

        result = preflight_authority_deployment(
            config=config,
            capabilities=authority.capabilities(),
            require_live_worker=True,
            compute_to_authority_reachable=True,
            service_healthy=True,
        )

    assert not result.supported
    assert {diagnostic.code for diagnostic in result.diagnostics} == {
        "authority.unsupported_capability"
    }
    assert {str(diagnostic.detail["capability"]) for diagnostic in result.diagnostics} == {
        "multi_host_authority",
        "service_endpoint",
    }


def test_service_unreachable_preflight_fails_closed() -> None:
    with LocalAuthorityService.start() as service:
        config = service.config(
            backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
        )
        capabilities = create_service_authority_store(config).capabilities()

    result = preflight_authority_deployment(
        config=config,
        capabilities=capabilities,
        require_live_worker=True,
        compute_to_authority_reachable=True,
        service_healthy=False,
    )

    assert not result.supported
    assert "authority_profile.service_unavailable" in {
        diagnostic.code for diagnostic in result.diagnostics
    }


def test_deferred_envelope_reconciles_through_service_authority() -> None:
    run_uri = "file:///runs/deferred-service"
    with LocalAuthorityService.start() as service:
        authority = create_service_authority_store(service.config())
        authority.create_run(run_uri)
        allocation = authority.allocate_stage_attempt(
            run_uri,
            "build",
            owner_id="worker-1",
            lease_ttl_seconds=60,
        )
        assert allocation.lease is not None
        authority.write_submitted_operation(run_uri, submitted_operation(run_uri))
        envelope = DeferredResultEnvelope(
            run_uri=run_uri,
            stage_name="build",
            attempt_id=allocation.attempt.attempt_id,
            submission_id="sub-1",
            owner_id="worker-1",
            produced_at="2020-01-01T00:00:02Z",
            producer_id="offline-worker",
            status=StageStatus.SUCCEEDED,
            output_refs={
                "out": ArtifactRef(
                    artifact_id="build/out",
                    uri=f"{run_uri}/artifacts/build/out.json",
                    artifact_type="json",
                )
            },
        )

        result = reconcile_deferred_result(
            authority,
            envelope,
            fencing_token=allocation.lease.fencing_token,
        )

        assert result.accepted
        assert result.code is DeferredReconciliationCode.ACCEPTED
        assert authority.snapshot(run_uri).stages[0].status is StageStatus.SUCCEEDED
