"""Integration tests for workspace authority registry files."""

from __future__ import annotations

import pytest

from loom.pipeline.stores import (
    AuthorityBackendKind,
    AuthorityDeploymentProfile,
    AuthorityReference,
    AuthorityRegistryAllocationScope,
    AuthorityRegistryRecord,
    AuthorityRegistryValidationStatus,
    read_authority_registry_record,
    validate_authority_registry,
    write_authority_registry_record,
)


pytestmark = pytest.mark.integration


def _record(*, allocation_id: str | None = None) -> AuthorityRegistryRecord:
    return AuthorityRegistryRecord(
        reference=AuthorityReference(
            backend_kind=AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
            deployment_profile=AuthorityDeploymentProfile.ALLOCATION_SCOPED,
            reference_id="authority-1",
            endpoint="http://127.0.0.1:8000",
            workspace_id="workspace-a",
            state_path="/tmp/authority-state",
            metadata={"token": "secret", "safe": "kept"},
        ),
        service_generation="generation-1",
        workspace_id="workspace-a",
        state_dir="/tmp/authority-state",
        allocation_scope=AuthorityRegistryAllocationScope.ALLOCATION
        if allocation_id is not None
        else AuthorityRegistryAllocationScope.WORKSPACE,
        allocation_id=allocation_id,
        created_at="2026-05-11T10:00:00Z",
        updated_at="2026-05-11T10:00:00Z",
    )


def test_current_registry_record_writes_and_reads_atomically(tmp_path) -> None:
    path = write_authority_registry_record(tmp_path, _record())

    assert path == tmp_path / ".loom" / "authority" / "current.json"
    assert not list(path.parent.glob("*.tmp*"))
    restored = read_authority_registry_record(tmp_path)

    assert restored.service_generation == "generation-1"
    assert restored.reference.metadata["token"] == "[REDACTED]"
    assert restored.reference.metadata["safe"] == "kept"


def test_allocation_registry_record_uses_allocation_path(tmp_path) -> None:
    path = write_authority_registry_record(
        tmp_path,
        _record(allocation_id="alloc-1"),
    )

    assert path == tmp_path / ".loom" / "authority" / "allocations" / "alloc-1.json"
    restored = read_authority_registry_record(tmp_path, allocation_id="alloc-1")
    assert restored.allocation_id == "alloc-1"
    assert restored.allocation_scope is AuthorityRegistryAllocationScope.ALLOCATION


def test_validate_registry_missing_record_fails_closed(tmp_path) -> None:
    result = validate_authority_registry(tmp_path)

    assert result.status is AuthorityRegistryValidationStatus.MISSING
    assert result.registry_hint is None
    assert result.failure_kind is not None
    assert result.diagnostics[0].code == "authority_registry.missing"


def test_validate_registry_reads_record_and_checks_workspace(tmp_path) -> None:
    write_authority_registry_record(tmp_path, _record())

    valid = validate_authority_registry(
        tmp_path,
        expected_workspace_id="workspace-a",
        expected_generation="generation-1",
    )
    wrong_workspace = validate_authority_registry(
        tmp_path,
        expected_workspace_id="workspace-b",
    )

    assert valid.status is AuthorityRegistryValidationStatus.VALID
    assert valid.registry_hint is not None
    assert valid.registry_hint.reference.endpoint == "http://127.0.0.1:8000"
    assert wrong_workspace.status is AuthorityRegistryValidationStatus.WRONG_WORKSPACE
