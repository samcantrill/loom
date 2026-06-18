"""Unit tests for ``loom backend`` CLI commands."""

from __future__ import annotations

from collections.abc import Iterator
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
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import AuthorityConfig, authority_config_to_cli_args
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.service_authority import LocalAuthorityService
from tests.unit.loom.pipeline.execution.test_authority_adapter import _pipeline


pytestmark = pytest.mark.unit


@pytest.fixture
def authority_context() -> Iterator[tuple[AuthorityConfig, tuple[str, ...]]]:
    with LocalAuthorityService.start() as service:
        config = service.config()
        yield config, authority_config_to_cli_args(config)


def test_backend_command_is_registered() -> None:
    parser = build_parser()

    help_text = parser.format_help()

    assert "backend" in help_text


def test_backend_inspect_json_outputs_authoritative_summary(
    tmp_path: Path,
    authority_context: tuple[AuthorityConfig, tuple[str, ...]],
) -> None:
    authority_config, authority_args = authority_context
    run_uri = _authority_run(tmp_path, authority_config=authority_config)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["backend", "inspect", run_uri, *authority_args, "--format", "json"],
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
    assert payload["result"]["counts"]["reliability_policy_facts"] == 2
    assert payload["result"]["stages"][0]["reliability_policy_count"] == 1
    assert payload["result"]["state_source"]["label"] == "authoritative_service_truth"
    assert stderr.getvalue() == ""


def test_backend_inspect_text_includes_revision_and_stage(
    tmp_path: Path,
    authority_context: tuple[AuthorityConfig, tuple[str, ...]],
) -> None:
    authority_config, authority_args = authority_context
    run_uri = _authority_run(tmp_path, authority_config=authority_config)
    stdout = io.StringIO()

    assert (
        main(
            ["backend", "inspect", run_uri, "--stage", "build", *authority_args],
            stdout=stdout,
        )
        == 0
    )

    output = stdout.getvalue()
    assert output.startswith(f"backend inspect {run_uri}: SUCCEEDED")
    assert "source: authoritative_service_truth" in output
    assert "revision:" in output
    assert "reliability: policies=2" in output
    assert "  reliability: policies=1" in output
    assert "stage build: SUCCEEDED" in output
    assert "stage report" not in output


def test_backend_capabilities_json_reports_backend_records(
    tmp_path: Path,
    authority_context: tuple[AuthorityConfig, tuple[str, ...]],
) -> None:
    authority_config, authority_args = authority_context
    run_uri = _authority_run(tmp_path, authority_config=authority_config)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["backend", "capabilities", run_uri, *authority_args, "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == BACKEND_CAPABILITIES_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["result"]["backend_name"] == "local-authority-service"
    assert payload["result"]["state_source"]["label"] == "authoritative_service_truth"
    assert payload["result"]["capabilities"]
    assert stderr.getvalue() == ""


def test_backend_capabilities_explicit_remote_requirement_fails_json(
    tmp_path: Path,
    authority_context: tuple[AuthorityConfig, tuple[str, ...]],
) -> None:
    authority_config, authority_args = authority_context
    run_uri = _authority_run(tmp_path, authority_config=authority_config)
    stdout = io.StringIO()

    assert main(
        [
            "backend",
            "capabilities",
            run_uri,
            "--require-remote",
            *authority_args,
            "--format",
            "json",
        ],
        stdout=stdout,
    ) == int(ExitCode.RUN_STATE)

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.backend.unsupported_capability"
    diagnostics = payload["error"]["context"]["result"]["diagnostics"]
    assert diagnostics[0]["code"] == "unsafe_remote_coordination"


def test_backend_capabilities_explicit_requirements_fail_text_with_detail(
    tmp_path: Path,
    authority_context: tuple[AuthorityConfig, tuple[str, ...]],
) -> None:
    authority_config, authority_args = authority_context
    run_uri = _authority_run(tmp_path, authority_config=authority_config)
    stderr = io.StringIO()

    assert main(
        [
            "backend",
            "capabilities",
            run_uri,
            "--require-shared-filesystem",
            "--require-remote",
            *authority_args,
        ],
        stderr=stderr,
    ) == int(ExitCode.RUN_STATE)

    error = stderr.getvalue()
    assert "unsafe_shared_filesystem" in error
    assert "unsafe_remote_coordination" in error
    assert "workspace-level coordination" in error


def _authority_run(tmp_path: Path, *, authority_config: AuthorityConfig) -> str:
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_config=authority_config,
    )
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    PipelineRunner(run_store=run_store).run(
        RunRequest(pipeline=_pipeline(), run_uri=run_uri)
    )
    return run_uri
