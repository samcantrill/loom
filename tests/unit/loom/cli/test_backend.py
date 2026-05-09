"""Unit tests for ``loom backend`` CLI commands."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.backend import (
    BACKEND_CAPABILITIES_SCHEMA_VERSION,
    BACKEND_INSPECT_SCHEMA_VERSION,
)
from loom.cli.errors import ExitCode
from loom.cli.main import build_parser, main
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.unit.loom.pipeline.execution.test_authority_adapter import (
    _pipeline,
    _store,
)


pytestmark = pytest.mark.unit


def test_backend_command_is_registered() -> None:
    parser = build_parser()

    help_text = parser.format_help()

    assert "backend" in help_text


def test_backend_inspect_json_outputs_authoritative_summary(tmp_path: Path) -> None:
    run_uri = _authority_run(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["backend", "inspect", run_uri, "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == BACKEND_INSPECT_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["result"]["status"] == "SUCCEEDED"
    assert payload["result"]["counts"]["stages"] == 2
    assert stderr.getvalue() == ""


def test_backend_inspect_text_includes_revision_and_stage(tmp_path: Path) -> None:
    run_uri = _authority_run(tmp_path)
    stdout = io.StringIO()

    assert main(["backend", "inspect", run_uri, "--stage", "build"], stdout=stdout) == 0

    output = stdout.getvalue()
    assert output.startswith(f"backend inspect {run_uri}: SUCCEEDED")
    assert "revision:" in output
    assert "stage build: SUCCEEDED" in output
    assert "stage report" not in output


def test_backend_capabilities_json_reports_backend_records(tmp_path: Path) -> None:
    run_uri = _authority_run(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["backend", "capabilities", run_uri, "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == BACKEND_CAPABILITIES_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["result"]["backend_name"] == "sqlite-per-run-authority"
    assert payload["result"]["capabilities"]
    assert stderr.getvalue() == ""


def test_backend_capabilities_explicit_remote_requirement_fails_json(
    tmp_path: Path,
) -> None:
    run_uri = _authority_run(tmp_path)
    stdout = io.StringIO()

    assert (
        main(
            [
                "backend",
                "capabilities",
                run_uri,
                "--require-remote",
                "--format",
                "json",
            ],
            stdout=stdout,
        )
        == int(ExitCode.RUN_STATE)
    )

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.backend.unsupported_capability"
    diagnostics = payload["error"]["context"]["result"]["diagnostics"]
    assert diagnostics[0]["code"] == "unsafe_remote_coordination"


def test_backend_capabilities_explicit_requirements_fail_text_with_detail(
    tmp_path: Path,
) -> None:
    run_uri = _authority_run(tmp_path)
    stderr = io.StringIO()

    assert (
        main(
            [
                "backend",
                "capabilities",
                run_uri,
                "--require-shared-filesystem",
                "--require-remote",
            ],
            stderr=stderr,
        )
        == int(ExitCode.RUN_STATE)
    )

    error = stderr.getvalue()
    assert "unsafe_shared_filesystem" in error
    assert "unsafe_remote_coordination" in error
    assert "workspace or sweep coordination" in error


def _authority_run(tmp_path: Path) -> str:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    run_store = _store(tmp_path, authority)
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    return run_uri
