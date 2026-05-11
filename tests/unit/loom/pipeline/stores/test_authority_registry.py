"""Unit tests for workspace-local authority registry records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypedDict, Unpack, cast

import pytest

from loom.serialization import PlainData
from loom.pipeline.stores import (
    AUTHORITY_REGISTRY_SCHEMA_VERSION,
    AuthorityBackendKind,
    AuthorityDeploymentProfile,
    AuthorityProtocolVersion,
    AuthorityReference,
    AuthorityRegistryAllocationScope,
    AuthorityRegistryError,
    AuthorityRegistryRecord,
    AuthorityRegistryValidationStatus,
    AuthoritySchemaCheck,
    AuthoritySchemaFailure,
    AuthoritySchemaFailureKind,
    AuthorityServiceHealthState,
    BackendCapabilitySet,
    authority_registry_record_path,
    validate_authority_registry_record,
)


pytestmark = pytest.mark.unit


class _RecordKwargs(TypedDict, total=False):
    protocol_version: AuthorityProtocolVersion
    capabilities: BackendCapabilitySet
    allocation_scope: AuthorityRegistryAllocationScope
    allocation_id: str
    created_at: str
    updated_at: str
    expires_at: str
    service_health_state: AuthorityServiceHealthState
    diagnostics_metadata: Mapping[str, PlainData]
    schema_version: int


class _ValidationKwargs(TypedDict, total=False):
    expected_workspace_id: str
    expected_generation: str
    now: str


def _reference(
    metadata: Mapping[str, PlainData] | None = None,
) -> AuthorityReference:
    return AuthorityReference(
        backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
        deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
        reference_id="authority-1",
        endpoint="http://127.0.0.1:8000",
        workspace_id="workspace-a",
        state_path="/tmp/authority-state",
        metadata={} if metadata is None else metadata,
    )


def _record(**kwargs: Unpack[_RecordKwargs]) -> AuthorityRegistryRecord:
    reference_metadata = cast(
        Mapping[str, PlainData],
        {"token": "secret", "nested": {"authkey": "hidden"}},
    )
    return AuthorityRegistryRecord(
        reference=_reference(metadata=reference_metadata),
        service_generation="generation-1",
        workspace_id="workspace-a",
        state_dir="/tmp/authority-state",
        protocol_version=kwargs.get("protocol_version", AuthorityProtocolVersion()),
        capabilities=kwargs.get("capabilities"),
        allocation_scope=kwargs.get(
            "allocation_scope",
            AuthorityRegistryAllocationScope.WORKSPACE,
        ),
        allocation_id=kwargs.get("allocation_id"),
        created_at=kwargs.get("created_at", "2026-05-11T10:00:00Z"),
        updated_at=kwargs.get("updated_at", "2026-05-11T10:00:00Z"),
        expires_at=kwargs.get("expires_at"),
        service_health_state=kwargs.get(
            "service_health_state",
            AuthorityServiceHealthState.UNKNOWN,
        ),
        diagnostics_metadata=kwargs.get("diagnostics_metadata", {}),
        schema_version=kwargs.get(
            "schema_version",
            AUTHORITY_REGISTRY_SCHEMA_VERSION,
        ),
    )


def test_registry_record_round_trips_and_redacts_sensitive_metadata() -> None:
    record = _record(diagnostics_metadata={"credential": "abc", "safe": "ok"})

    payload = cast(dict[str, Any], record.to_dict())
    restored = AuthorityRegistryRecord.from_dict(payload)

    assert payload["reference"]["metadata"]["token"] == "[REDACTED]"
    assert payload["reference"]["metadata"]["nested"]["authkey"] == "[REDACTED]"
    assert payload["diagnostics_metadata"]["credential"] == "[REDACTED]"
    assert restored == record


def test_registry_record_rejects_sensitive_endpoint_payloads() -> None:
    with pytest.raises(AuthorityRegistryError, match="userinfo"):
        AuthorityRegistryRecord(
            reference=AuthorityReference(
                backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
                deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
                reference_id="authority-1",
                endpoint="http://user:password@127.0.0.1:8000",
                workspace_id="workspace-a",
            ),
            service_generation="generation-1",
            workspace_id="workspace-a",
            state_dir="/tmp/authority-state",
        )

    with pytest.raises(AuthorityRegistryError, match="sensitive query"):
        AuthorityRegistryRecord(
            reference=AuthorityReference(
                backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
                deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
                reference_id="authority-1",
                endpoint="http://127.0.0.1:8000?token=abc",
                workspace_id="workspace-a",
            ),
            service_generation="generation-1",
            workspace_id="workspace-a",
            state_dir="/tmp/authority-state",
        )


def test_registry_record_paths_validate_allocation_ids(tmp_path) -> None:
    assert (
        authority_registry_record_path(tmp_path)
        == tmp_path / ".loom" / "authority" / "current.json"
    )
    assert (
        authority_registry_record_path(tmp_path, allocation_id="alloc-1")
        == tmp_path / ".loom" / "authority" / "allocations" / "alloc-1.json"
    )
    with pytest.raises(AuthorityRegistryError):
        authority_registry_record_path(tmp_path, allocation_id="../bad")


@pytest.mark.parametrize(
    ("record_kwargs", "expected", "validation_kwargs"),
    [
        ({}, AuthorityRegistryValidationStatus.VALID, {}),
        (
            {"expires_at": "2026-05-11T09:59:59Z"},
            AuthorityRegistryValidationStatus.STALE,
            {"now": "2026-05-11T10:00:00Z"},
        ),
        ({}, AuthorityRegistryValidationStatus.WRONG_WORKSPACE, {"expected_workspace_id": "workspace-b"}),
        ({}, AuthorityRegistryValidationStatus.INCOMPATIBLE_GENERATION, {"expected_generation": "generation-old"}),
        (
            {
                "service_health_state": AuthorityServiceHealthState.UNAVAILABLE,
            },
            AuthorityRegistryValidationStatus.UNAVAILABLE_SERVICE,
            {},
        ),
        (
            {
                "service_health_state": AuthorityServiceHealthState.UNHEALTHY,
            },
            AuthorityRegistryValidationStatus.UNHEALTHY_SERVICE,
            {},
        ),
    ],
)
def test_registry_record_validation_statuses(
    record_kwargs: _RecordKwargs,
    expected: AuthorityRegistryValidationStatus,
    validation_kwargs: _ValidationKwargs,
) -> None:
    result = validate_authority_registry_record(
        _record(**record_kwargs),
        **validation_kwargs,
    )

    assert result.status is expected
    assert result.valid is (expected is AuthorityRegistryValidationStatus.VALID)
    if expected is not AuthorityRegistryValidationStatus.VALID:
        assert result.failure_kind is not None
    assert result.registry_hint is not None
    assert result.service_health is not None


def test_registry_validation_detects_incompatible_version() -> None:
    failure = AuthoritySchemaFailure(
        kind=AuthoritySchemaFailureKind.UNSUPPORTED_NEWER,
        message="newer schema",
        found_version=999,
    )
    record = _record(
        protocol_version=AuthorityProtocolVersion(
            schema_check=AuthoritySchemaCheck(found_version=999, failure=failure)
        )
    )

    result = validate_authority_registry_record(record)

    assert result.status is AuthorityRegistryValidationStatus.INCOMPATIBLE_VERSION
    assert result.registry_hint is not None
    assert result.registry_hint.protocol_compatible is False


def test_allocation_scope_requires_allocation_id() -> None:
    with pytest.raises(AuthorityRegistryError, match="allocation_id"):
        _record(allocation_scope=AuthorityRegistryAllocationScope.ALLOCATION)
