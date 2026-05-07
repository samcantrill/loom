"""Unit tests for ``loom preflight`` command orchestration."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.cli.options import ConfigCliOptions, PreflightCliOptions
import loom.cli.preflight as preflight_command
from loom.diagnostics import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightRequest,
    PreflightResult,
    PreflightSeverity,
)


pytestmark = pytest.mark.unit


def _result(
    status: PreflightCheckStatus = PreflightCheckStatus.PASS,
    *,
    message: str = "config composed successfully",
) -> PreflightResult:
    severity = PreflightSeverity.ERROR if status is PreflightCheckStatus.FAIL else PreflightSeverity.INFO
    if status is PreflightCheckStatus.WARN:
        severity = PreflightSeverity.WARNING
    return PreflightResult(
        checks=(
            PreflightCheckResult(
                check_id="config.load",
                group=PreflightGroup.CONFIG,
                status=status,
                severity=severity,
                message=message,
            ),
        ),
        groups=(PreflightGroup.CONFIG,),
    )


def test_preflight_json_passes_cli_options_to_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, PreflightRequest] = {}

    def run_preflight(request: PreflightRequest) -> PreflightResult:
        calls["request"] = request
        return _result()

    monkeypatch.setattr(preflight_command, "_run_diagnostics_preflight", run_preflight)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "preflight",
                "base.yaml",
                "--overlay",
                "team.yaml",
                "--set",
                "a=1",
                "--run-uri",
                "file:///abs/runs/demo",
                "--profile",
                "cluster",
                "--executor",
                "local",
                "--only-stage",
                "build",
                "--tag",
                "team=platform",
                "--note",
                "review",
                "--check",
                "config",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    request = calls["request"]
    assert request.config_path == Path("base.yaml")
    assert request.overlays == (Path("team.yaml"),)
    assert request.overrides == ("a=1",)
    assert request.run_uri == "file:///abs/runs/demo"
    assert request.groups == ("config",)
    assert request.runtime_options == {
        "run_uri": "file:///abs/runs/demo",
        "executor": "local",
        "profile": "cluster",
        "tags": {"team": "platform"},
        "notes": ["review"],
        "selectors": {"only_stages": ["build"]},
    }
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == preflight_command.PREFLIGHT_RESULT_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["result"]["status"] == "PASS"
    assert stderr.getvalue() == ""


def test_preflight_strict_warning_returns_failed_result_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight_command,
        "_run_diagnostics_preflight",
        lambda _request: _result(PreflightCheckStatus.WARN, message="best-effort warning"),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["preflight", "base.yaml", "--strict", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["result"]["status"] == "WARN"
    assert stderr.getvalue() == ""


def test_preflight_failure_writes_text_result_and_returns_pipeline_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight_command,
        "_run_diagnostics_preflight",
        lambda _request: _result(PreflightCheckStatus.FAIL, message="config composition failed"),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["preflight", "base.yaml"], stdout=stdout, stderr=stderr) == 4

    assert stdout.getvalue() == (
        "FAILED preflight base.yaml: FAIL\n"
        "FAIL config.load: config composition failed\n"
    )
    assert stderr.getvalue() == ""


def test_preflight_unknown_check_group_is_cli_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["preflight", "base.yaml", "--check", "unknown", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )

    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "cli.preflight.invalid_check_group"
    assert "unknown preflight group" in payload["error"]["message"]
    assert stderr.getvalue() == ""


def test_build_preflight_result_uses_none_for_default_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, PreflightRequest] = {}

    def run_preflight(request: PreflightRequest) -> PreflightResult:
        calls["request"] = request
        return _result()

    monkeypatch.setattr(preflight_command, "_run_diagnostics_preflight", run_preflight)

    preflight_command.build_preflight_result(
        config_options=ConfigCliOptions(config_path=Path("base.yaml")),
        preflight_options=PreflightCliOptions(),
    )

    assert calls["request"].groups is None
