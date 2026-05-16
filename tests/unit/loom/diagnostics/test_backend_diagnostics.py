"""Unit tests for authoritative backend diagnostics."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from loom.diagnostics.backend import (
    BackendDiagnosticsError,
    inspect_backend,
    inspect_backend_capabilities,
    parse_projection_revision,
)
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.stores import BackendRevision, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import (
    SQLitePerRunAuthorityStore,
    _authority_database_path,
)
from tests.unit.loom.pipeline.execution.test_authority_adapter import (
    _pipeline,
    _store,
)


pytestmark = pytest.mark.unit


class ReadOnlyTrapAuthority(SQLitePerRunAuthorityStore):
    def create_run(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not create runs")

    def transition_run(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not transition runs")

    def transition_stage(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not transition stages")

    def allocate_stage_attempt(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not allocate attempts")

    def acquire_controller_lease(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not acquire leases")

    def renew_lease(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not renew leases")

    def release_lease(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not release leases")

    def fail_lease(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not fail leases")

    def write_submitted_operation(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not write submitted operations")

    def record_output_commit(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not commit outputs")

    def append_audit_event(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostics must not append audit events")


def test_inspect_backend_reports_authoritative_facts_without_mutation(
    tmp_path: Path,
) -> None:
    authority, run_uri = _authority_run(tmp_path)
    before = authority.snapshot(run_uri).revision

    result = inspect_backend(
        run_uri,
        authority_store=ReadOnlyTrapAuthority(clock=lambda: "2020-01-01T00:00:00Z"),
    )

    assert result.status == "SUCCEEDED"
    assert result.backend_name == "sqlite-per-run-authority"
    assert result.state_source["label"] == "authoritative_service_truth"
    assert result.revision["sequence"] == before.sequence
    assert result.counts["stages"] == 2
    assert result.counts["commits"] == 2
    assert result.counts["artifact_facts"] == 2
    assert result.counts["reliability_policy_facts"] == 2
    assert result.stages[0]["reliability_policy_count"] == 1
    assert [stage["stage_name"] for stage in result.stages] == ["build", "report"]
    assert authority.snapshot(run_uri).revision.sequence == before.sequence


def test_inspect_backend_supports_stage_filter_and_stale_projection_warning(
    tmp_path: Path,
) -> None:
    authority, run_uri = _authority_run(tmp_path)

    result = inspect_backend(
        run_uri,
        stage_name="build",
        projection_revision=BackendRevision(sequence=1, token="stale"),
        authority_store=authority,
    )

    assert [stage["stage_name"] for stage in result.stages] == ["build"]
    assert [warning["code"] for warning in result.warnings] == ["stale_projection"]


def test_inspect_backend_rejects_missing_authority_backend(tmp_path: Path) -> None:
    _authority, run_uri = _authority_run(tmp_path)
    _authority_database_path(run_uri).unlink()

    with pytest.raises(BackendDiagnosticsError, match="authoritative backend"):
        inspect_backend(run_uri)


def test_inspect_backend_rejects_unsupported_authority_schema(
    tmp_path: Path,
) -> None:
    authority, run_uri = _authority_run(tmp_path)
    with sqlite3.connect(_authority_database_path(run_uri)) as conn:
        conn.execute("UPDATE metadata SET value = '999' WHERE key = 'schema_version'")

    with pytest.raises(BackendDiagnosticsError) as exc_info:
        inspect_backend(run_uri, authority_store=authority)

    error = exc_info.value
    assert error.code == "backend_diagnostics.schema_unsupported_newer"
    assert error.diagnostics[0].code == "authority_schema_unsupported_newer"
    assert error.diagnostics[0].detail["found_version"] == 999


def test_capabilities_report_explicit_remote_requirement(tmp_path: Path) -> None:
    authority, run_uri = _authority_run(tmp_path)

    result = inspect_backend_capabilities(
        run_uri,
        require_remote=True,
        authority_store=authority,
    )

    assert result.has_error_diagnostics is True
    assert result.state_source["label"] == "authoritative_service_truth"
    assert result.diagnostics[0]["code"] == "unsafe_remote_coordination"
    assert "workspace or sweep coordination" in str(result.diagnostics[0]["message"])
    detail = result.diagnostics[0]["detail"]
    assert isinstance(detail, dict)
    assert detail["required_capability"] == "cross_run_coordination"
    assert result.requirements == {"shared_filesystem": False, "remote": True}


def test_parse_projection_revision_rejects_bad_shape() -> None:
    with pytest.raises(BackendDiagnosticsError, match="SEQUENCE:TOKEN"):
        parse_projection_revision("bad")


def _authority_run(tmp_path: Path) -> tuple[SQLitePerRunAuthorityStore, str]:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    return authority, run_uri
