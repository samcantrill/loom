"""Unit coverage for the local service authority backend."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityFactoryError,
    BackendCapability,
    CapabilityScope,
    create_run_store,
)
from loom.pipeline.stores.service_authority import (
    AuthorityServiceUnavailable,
    LocalAuthorityService,
    create_service_authority_store,
)


def test_service_config_carries_endpoint_without_state_path() -> None:
    with LocalAuthorityService.start() as service:
        config = service.config()

        assert config.backend_kind is AuthorityBackendKind.CO_LOCATED_SERVICE
        assert config.endpoint == service.endpoint
        assert config.state_path is None
        assert "authkey" in config.metadata


def test_service_capabilities_are_explicit_about_unsupported_topologies() -> None:
    with LocalAuthorityService.start() as service:
        store = create_service_authority_store(service.config())
        capabilities = store.capabilities()

        assert capabilities.supports(
            BackendCapability.SERVICE_ENDPOINT, scope=CapabilityScope.PER_RUN
        )
        assert capabilities.supports(
            BackendCapability.TRANSACTION_ISOLATION, scope=CapabilityScope.PER_RUN
        )
        assert not capabilities.supports(
            BackendCapability.MULTI_HOST_AUTHORITY, scope=CapabilityScope.PER_RUN
        )
        assert not capabilities.supports(
            BackendCapability.SHARED_FILESYSTEM_SAFE, scope=CapabilityScope.PER_RUN
        )
        assert not capabilities.supports(
            BackendCapability.DEFERRED_FINALIZATION, scope=CapabilityScope.PER_RUN
        )


def test_service_client_rejects_missing_co_located_endpoint() -> None:
    with pytest.raises(AuthorityFactoryError, match="online mutation mode requires"):
        create_run_store(
            AuthorityConfig(backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE)
        )


def test_service_client_rejects_missing_authkey_for_explicit_endpoint() -> None:
    with pytest.raises(ValueError, match="authkey"):
        create_run_store(
            AuthorityConfig(
                backend_kind=AuthorityBackendKind.CO_LOCATED_SERVICE,
                endpoint="tcp://127.0.0.1:1",
            )
        )


def test_service_client_maps_unavailable_service() -> None:
    service = LocalAuthorityService.start()
    config = service.config()
    service.stop()

    with pytest.raises(AuthorityServiceUnavailable, match="unavailable"):
        create_run_store(config)


def test_service_health_reports_revision_and_run_count(tmp_path) -> None:
    run_uri = f"file://{tmp_path}/runs/r1"
    with LocalAuthorityService.start() as service:
        store = create_service_authority_store(service.config())
        assert service.health()["runs"] == 0

        store.create_run(run_uri)

        health = service.health()
        assert health["ok"] is True
        assert health["runs"] == 1
        assert health["revision"] == 1
