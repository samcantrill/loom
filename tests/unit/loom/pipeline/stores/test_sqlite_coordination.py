"""Unit coverage for the private SQLite workspace coordination backend."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from loom.pipeline.stores import (
    AuthoritySchemaFailureKind,
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    CapabilitySupport,
    WorkspaceIdentity,
    coordination_requirement_diagnostics,
)
from loom.pipeline.stores.sqlite_coordination import SQLiteWorkspaceCoordinationStore


pytestmark = pytest.mark.unit


@dataclass(slots=True)
class FrozenClock:
    value: str = "2020-01-01T00:00:00Z"

    def __call__(self) -> str:
        return self.value


def test_schema_policy_reports_missing_supported_and_newer(tmp_path: Path) -> None:
    database_path = tmp_path / "coordination.sqlite3"
    store = SQLiteWorkspaceCoordinationStore(database_path, clock=FrozenClock())

    missing = store.check_schema()
    assert missing.failure is not None
    assert missing.failure.kind is AuthoritySchemaFailureKind.MISSING

    store.create_workspace(WorkspaceIdentity(workspace_id="workspace-1"))
    assert store.check_schema().supported

    with sqlite3.connect(database_path) as conn:
        conn.execute("UPDATE metadata SET value = '999' WHERE key = 'schema_version'")
    newer = store.check_schema()
    assert newer.failure is not None
    assert newer.failure.kind is AuthoritySchemaFailureKind.UNSUPPORTED_NEWER


def test_capabilities_are_explicit_about_local_coordination_limits(
    tmp_path: Path,
) -> None:
    capabilities = SQLiteWorkspaceCoordinationStore(
        tmp_path / "coordination.sqlite3"
    ).capabilities()

    assert capabilities.supports(
        BackendCapability.CROSS_RUN_COORDINATION,
        scope=CapabilityScope.CROSS_RUN,
    )
    assert capabilities.supports(
        BackendCapability.GLOBAL_COUNTERS,
        scope=CapabilityScope.CROSS_RUN,
    )
    assert not capabilities.supports(
        BackendCapability.PER_RUN_COORDINATION,
        scope=CapabilityScope.PER_RUN,
    )
    unsupported = capabilities.require(
        BackendCapability.PER_RUN_COORDINATION,
        scope=CapabilityScope.PER_RUN,
    )
    assert unsupported is not None
    record = next(
        record
        for record in capabilities.records
        if record.capability is BackendCapability.PER_RUN_COORDINATION
    )
    assert record.support is CapabilitySupport.UNSUPPORTED

    diagnostics = coordination_requirement_diagnostics(
        capabilities,
        require_shared_filesystem=True,
        require_remote=True,
        require_resource_leases=True,
    )
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "unsafe_shared_filesystem",
        "unsafe_remote_coordination",
    ]


def test_resource_lease_requirement_reports_existing_capability_gap() -> None:
    diagnostics = coordination_requirement_diagnostics(
        BackendCapabilitySet(
            backend_name="minimal",
            records=(
                BackendCapabilityRecord(
                    capability=BackendCapability.CROSS_RUN_COORDINATION,
                    scope=CapabilityScope.CROSS_RUN,
                ),
            ),
        ),
        require_resource_leases=True,
    )

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "unsupported_resource_leases"
    ]
    assert diagnostics[0].detail["missing_capabilities"] == [
        "global_counters",
        "backend_lease_time",
    ]
