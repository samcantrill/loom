"""Integration coverage for backend diagnostics over SQLite authority."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.diagnostics.backend import inspect_backend, inspect_backend_capabilities
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.stores import (
    BackendRevision,
    create_run_store,
    path_to_run_uri,
    run_uri_to_path,
)
from loom.pipeline.stores.service_authority import (
    LocalAuthorityService,
    create_service_authority_store,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.unit.loom.pipeline.execution.test_authority_adapter import (
    _pipeline,
    _store,
)


pytestmark = pytest.mark.integration


def test_backend_inspection_reports_materialization_warnings_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    before = authority.snapshot(run_uri).revision.sequence
    config_snapshot = run_uri_to_path(run_uri) / "config" / "resolved.yaml"
    if config_snapshot.exists():
        config_snapshot.unlink()

    def fail_read_bytes(self: Path) -> bytes:
        raise AssertionError(f"diagnostics read artifact payload bytes from {self}")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    result = inspect_backend(
        run_uri,
        verify_materialization=True,
        projection_revision=BackendRevision(sequence=1, token="stale"),
        authority_store=authority,
    )

    assert result.status == "SUCCEEDED"
    warning_codes = {str(warning["code"]) for warning in result.warnings}
    assert warning_codes >= {"missing_materialized_ref", "stale_projection"}
    assert authority.snapshot(run_uri).revision.sequence == before


def test_backend_capability_requirements_are_diagnostic_only(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    before = authority.snapshot(run_uri).revision.sequence

    result = inspect_backend_capabilities(
        run_uri,
        require_shared_filesystem=True,
        require_remote=True,
        authority_store=authority,
    )

    assert result.has_error_diagnostics is True
    assert {str(diagnostic["code"]) for diagnostic in result.diagnostics} == {
        "unsafe_remote_coordination",
        "unsafe_shared_filesystem",
    }
    assert authority.snapshot(run_uri).revision.sequence == before


def test_backend_capabilities_report_service_topology(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "runs" / "service")
    with LocalAuthorityService.start() as service:
        config = service.config()
        create_run_store(config).admit_run(run_uri)
        authority = create_service_authority_store(config)

        result = inspect_backend_capabilities(
            run_uri,
            require_shared_filesystem=True,
            require_remote=True,
            authority_store=authority,
        )

        assert result.backend_name == "local-authority-service"
        assert result.requirements == {
            "shared_filesystem": True,
            "remote": True,
        }
        assert {str(diagnostic["code"]) for diagnostic in result.diagnostics} == {
            "unsafe_shared_filesystem",
            "unsafe_remote_coordination",
        }
