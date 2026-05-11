"""Unit coverage for strict authority factory adoption."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
    AuthorityFactoryError,
    AuthorityReadinessState,
    AuthorityReference,
    AuthorityRegistryRecord,
    AuthorityResolutionFailureKind,
    AuthorityResolutionMode,
    AuthorityServiceHealthState,
    create_authority_client,
    create_run_store,
    resolve_authority_for_factory,
    write_authority_registry_record,
)
from loom.pipeline.stores.authority_factory import probe_http_authority_readiness
from loom.pipeline.stores.authority_protocol import AuthorityProtocolReadiness

pytestmark = pytest.mark.unit


def test_run_store_factory_fails_closed_without_authority() -> None:
    with pytest.raises(AuthorityFactoryError) as exc_info:
        create_run_store()

    error = exc_info.value
    assert error.code == "authority_factory.resolution_failed"
    assert error.resolution is not None
    assert (
        error.resolution.failure_kind
        is AuthorityResolutionFailureKind.MISSING_AUTHORITY
    )
    assert "loom authority start" in error.resolution.diagnostics[0].next_steps[0]


def test_run_store_factory_offline_first_is_explicitly_non_authoritative() -> None:
    with pytest.raises(AuthorityFactoryError) as exc_info:
        create_run_store(authority_mode=AuthorityResolutionMode.OFFLINE_FIRST)

    error = exc_info.value
    assert error.code == "authority_factory.offline_unsupported"
    assert error.resolution is not None
    assert error.resolution.authoritative is False


def test_create_authority_client_accepts_explicit_http_endpoint_with_transport() -> None:
    client = create_authority_client(
        AuthorityConfig(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            endpoint="http://127.0.0.1:8765",
            reference_id="managed",
        ),
        transport=lambda _url, _payload, _timeout: {"accepted": False},
    )

    assert client.endpoint == "http://127.0.0.1:8765"


def test_registry_reference_is_used_when_config_has_no_endpoint(tmp_path: Path) -> None:
    record = AuthorityRegistryRecord(
        reference=AuthorityReference(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            reference_id="registry-authority",
            endpoint="http://127.0.0.1:8765",
            workspace_id="workspace-a",
        ),
        workspace_id="workspace-a",
        state_dir=str(tmp_path / "state"),
        service_generation="generation-1",
        service_health_state=AuthorityServiceHealthState.READY,
    )
    write_authority_registry_record(tmp_path, record)

    resolution = resolve_authority_for_factory(
        workspace_root=tmp_path,
        expected_workspace_id="workspace-a",
        expected_generation="generation-1",
        probe_http_readiness=False,
    )

    assert resolution.result.succeeded
    assert resolution.reference == record.reference


def test_stale_registry_record_fails_closed(tmp_path: Path) -> None:
    record = AuthorityRegistryRecord(
        reference=AuthorityReference(
            backend_kind=AuthorityBackendKind.MANAGED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.MANAGED_SERVICE,
            reference_id="registry-authority",
            endpoint="http://127.0.0.1:8765",
            workspace_id="workspace-a",
        ),
        workspace_id="workspace-a",
        state_dir=str(tmp_path / "state"),
        service_generation="generation-1",
        expires_at="2020-01-01T00:00:00Z",
    )
    write_authority_registry_record(tmp_path, record)

    resolution = resolve_authority_for_factory(
        workspace_root=tmp_path,
        expected_workspace_id="workspace-a",
        probe_http_readiness=False,
    )

    assert not resolution.result.succeeded
    assert resolution.result.failure_kind is AuthorityResolutionFailureKind.STALE_REGISTRY


def test_http_readiness_probe_maps_ready_payload(monkeypatch) -> None:
    readiness = AuthorityProtocolReadiness(
        readiness=AuthorityReadinessState.READY,
        service_generation="generation-1",
        workspace_id="workspace-a",
    )

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(readiness.to_dict()).encode()

    monkeypatch.setattr(
        "loom.pipeline.stores.authority_factory.request.urlopen",
        lambda *_args, **_kwargs: _Response(),
    )

    health = probe_http_authority_readiness("http://127.0.0.1:8765")

    assert health.state is AuthorityServiceHealthState.READY
    assert health.service_generation == "generation-1"
    assert health.protocol_compatible is True


def test_http_readiness_probe_maps_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "loom.pipeline.stores.authority_factory.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )

    health = probe_http_authority_readiness("http://127.0.0.1:8765")

    assert health.state is AuthorityServiceHealthState.UNAVAILABLE


def test_direct_database_factory_resolution_uses_resolver_failure() -> None:
    resolution = resolve_authority_for_factory(
        AuthorityConfig(
            backend_kind=AuthorityBackendKind.DIRECT_DATABASE,
            deployment_profile=AuthorityDeploymentProfile.DIRECT_DATABASE,
            state_path="/tmp/authority.sqlite",
        )
    )

    assert not resolution.result.succeeded
    assert (
        resolution.result.failure_kind
        is AuthorityResolutionFailureKind.RESERVED_DIRECT_DATABASE
    )
