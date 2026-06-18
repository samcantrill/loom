"""Contract tests for authority FastAPI skeleton response shapes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from loom.authority.app import create_authority_app
from loom.authority._repository import initialize_authority_repository
from loom.authority.services import AuthorityAppServices, AuthorityRouteGroup
from loom.pipeline.stores import (
    AUTHORITY_MUTATION_RUN_ADMIT_PATH,
    AuthorityBackendKind,
    AuthorityDeploymentProfile,
    AuthorityProtocolReadiness,
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRequest,
    AuthorityProtocolResponse,
    AuthorityProtocolVersion,
    AuthorityReference,
    AuthorityRegistryRecord,
    AuthorityReadinessState,
    AuthorityServiceHealthState,
    BackendCapabilitySet,
)


pytestmark = pytest.mark.contract


def test_ready_endpoint_returns_protocol_readiness_shape() -> None:
    services = AuthorityAppServices(
        service_generation="generation-1",
        workspace_id="workspace-a",
        readiness=AuthorityReadinessState.READY,
    )
    client = TestClient(create_authority_app(services=services))

    payload = client.get("/ready").json()

    assert payload == services.readiness_report.to_dict()
    readiness = AuthorityProtocolReadiness.from_dict(payload)
    assert readiness.service_generation == "generation-1"
    assert readiness.workspace_id == "workspace-a"
    assert readiness.ready is True


def test_version_endpoint_returns_protocol_version_shape() -> None:
    client = TestClient(create_authority_app())

    payload = client.get("/version").json()

    version = AuthorityProtocolVersion.from_dict(payload)
    assert payload == version.to_dict()
    assert version.supported is True


def test_capabilities_endpoint_returns_capability_set_shape() -> None:
    capabilities = BackendCapabilitySet(backend_name="custom", records=())
    client = TestClient(
        create_authority_app(
            services=AuthorityAppServices(capabilities=capabilities),
        )
    )

    payload = client.get("/capabilities").json()

    assert payload == capabilities.to_dict()
    assert BackendCapabilitySet.from_dict(payload) == capabilities


def test_mutation_route_group_manifest_is_non_mutating_boundary() -> None:
    client = TestClient(create_authority_app())

    payload = client.get("/v1/authority").json()

    assert payload["route_group"] == AuthorityRouteGroup.MUTATION.value
    assert payload["mutation_routes_implemented"] is False
    assert payload["operations"] == []


def test_unconfigured_mutation_route_returns_protocol_rejection() -> None:
    client = TestClient(create_authority_app())
    request = AuthorityProtocolRequest(
        metadata=AuthorityProtocolMetadata(
            request_id="request-1",
            operation_kind=AuthorityProtocolOperationKind.RUN_LIFECYCLE,
        ),
        run_uri="file:///runs/r1",
    )

    payload = client.post(AUTHORITY_MUTATION_RUN_ADMIT_PATH, json=request.to_dict()).json()

    response = AuthorityProtocolResponse.from_dict(payload)
    assert response.accepted is False
    assert response.rejection is not None
    assert (
        response.rejection.category
        is AuthorityProtocolErrorCategory.UNSUPPORTED_CAPABILITY
    )
    assert response.rejection.code == "authority_mutations_not_configured"


def test_repository_backed_mutation_route_returns_protocol_ack(tmp_path) -> None:
    from loom.authority.services import repository_authority_services

    repository = initialize_authority_repository(
        tmp_path,
        service_generation="generation-1",
    )
    client = TestClient(
        create_authority_app(
            services=repository_authority_services(repository),
        )
    )
    request = AuthorityProtocolRequest(
        metadata=AuthorityProtocolMetadata(
            request_id="request-1",
            operation_kind=AuthorityProtocolOperationKind.RUN_LIFECYCLE,
        ),
        run_uri="file:///runs/r1",
    )

    payload = client.post(AUTHORITY_MUTATION_RUN_ADMIT_PATH, json=request.to_dict()).json()

    response = AuthorityProtocolResponse.from_dict(payload)
    assert response.accepted is True
    assert response.result is not None
    assert response.result.revision is not None
    assert response.result.service_generation == "generation-1"


def test_repository_backed_readiness_can_seed_registry_record(tmp_path) -> None:
    from loom.authority.services import repository_authority_services

    repository = initialize_authority_repository(
        tmp_path,
        service_generation="generation-1",
    )
    services = repository_authority_services(repository, workspace_id="workspace-a")
    readiness = services.readiness_report

    record = AuthorityRegistryRecord(
        reference=AuthorityReference(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            reference_id="local-authority-supervisor",
            endpoint="http://127.0.0.1:8765",
            workspace_id="workspace-a",
            state_path=str(tmp_path),
        ),
        service_generation=services.service_generation,
        workspace_id="workspace-a",
        state_dir=str(tmp_path),
        protocol_version=readiness.version,
        capabilities=readiness.capabilities,
        service_health_state=AuthorityServiceHealthState.READY,
    )

    assert record.protocol_compatible is True
    assert record.service_generation == "generation-1"
    assert record.capabilities == readiness.capabilities
