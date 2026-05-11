"""Contract tests for authority FastAPI skeleton response shapes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from loom.authority.app import create_authority_app
from loom.authority.services import AuthorityAppServices, AuthorityRouteGroup
from loom.pipeline.stores import (
    AuthorityProtocolReadiness,
    AuthorityProtocolVersion,
    AuthorityReadinessState,
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
