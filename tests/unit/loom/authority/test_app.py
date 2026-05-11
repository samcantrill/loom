"""Unit tests for the authority FastAPI app skeleton."""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from loom.authority.app import create_authority_app
from loom.authority.routes.mutations import MUTATION_ROUTE_PREFIX
from loom.authority.services import (
    DEFAULT_AUTHORITY_BACKEND_NAME,
    AuthorityAppServices,
    AuthorityRouteGroup,
    default_authority_services,
)
from loom.pipeline.stores import (
    AuthorityReadinessState,
    BackendCapabilitySet,
)


pytestmark = pytest.mark.unit


def test_default_services_build_protocol_reports() -> None:
    services = default_authority_services()

    assert services.capabilities.backend_name == DEFAULT_AUTHORITY_BACKEND_NAME
    assert services.readiness_report.ready is True
    assert services.readiness_report.capabilities == services.capabilities
    assert services.version_report.supported is True


def test_custom_services_preserve_injected_state() -> None:
    capabilities = BackendCapabilitySet(backend_name="custom", records=())
    services = AuthorityAppServices(
        service_generation="generation-1",
        workspace_id="workspace-a",
        readiness=AuthorityReadinessState.DEGRADED,
        capabilities=capabilities,
        repository=object(),
        mutation_service=object(),
    )

    assert services.readiness_report.service_generation == "generation-1"
    assert services.readiness_report.workspace_id == "workspace-a"
    assert services.readiness_report.readiness is AuthorityReadinessState.DEGRADED
    assert services.readiness_report.ready is False
    assert services.readiness_report.capabilities == capabilities


def test_create_authority_app_registers_supervisor_and_mutation_boundaries() -> None:
    services = AuthorityAppServices(service_generation="generation-1")

    app = create_authority_app(services=services)

    assert app.state.authority_services is services
    routes = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute)
    }
    assert {"/health", "/live", "/ready", "/version", "/capabilities"}.issubset(
        routes
    )
    assert MUTATION_ROUTE_PREFIX in routes
    assert AuthorityRouteGroup.SUPERVISOR.value in routes["/ready"].tags
    assert AuthorityRouteGroup.MUTATION.value in routes[MUTATION_ROUTE_PREFIX].tags
