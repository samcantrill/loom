"""Unit tests for ``loom status`` and ``loom logs`` command orchestration."""

from __future__ import annotations

import io
import json

import pytest

from loom.cli.main import main
import loom.cli.logs as logs_command
import loom.cli.status as status_command
from loom.diagnostics.inspection import (
    LogStreamSummary,
    RunStatusSummary,
    StageLogsSummary,
    StageStatusSummary,
    SubmittedOperationSummary,
)


pytestmark = pytest.mark.unit


def test_status_json_uses_diagnostics_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        status_command,
        "build_status_result",
        lambda run_uri: RunStatusSummary(
            run_uri=run_uri,
            status="SUBMITTED",
            artifact_count=1,
            submitted_operations=(
                SubmittedOperationSummary(
                    submission_id="sub-1",
                    backend="test-backend",
                    mode="batch",
                    state="SUBMITTED",
                    created_at="2020-01-01T00:00:00Z",
                    updated_at="2020-01-01T00:00:01Z",
                    manifest_relative_path="submitted/sub-1/manifest.json",
                    summary_counts={"submitted": 1},
                    active=True,
                ),
            ),
            stages=(
                StageStatusSummary(
                    stage_name="build",
                    status="SUBMITTED",
                    output_count=1,
                ),
            ),
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["status", "file:///tmp/run1", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == status_command.STATUS_RESULT_SCHEMA_VERSION
    assert payload["result"]["status"] == "SUBMITTED"
    assert payload["result"]["submitted_operations"][0]["submission_id"] == "sub-1"
    assert payload["result"]["stages"][0]["stage_name"] == "build"
    assert stderr.getvalue() == ""


def test_logs_text_passes_options(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def build_logs_result(
        run_uri: str,
        stage_name: str,
        *,
        stream: str,
        tail: int,
        paths_only: bool,
    ) -> StageLogsSummary:
        calls.update(
            {
                "run_uri": run_uri,
                "stage_name": stage_name,
                "stream": stream,
                "tail": tail,
                "paths_only": paths_only,
            }
        )
        return StageLogsSummary(
            run_uri=run_uri,
            stage_name=stage_name,
            streams=(
                LogStreamSummary(
                    stream="stdout",
                    path="/tmp/run1/stages/build/logs/stdout.log",
                    available=True,
                    content="last\n",
                    line_count=3,
                    displayed_line_count=1,
                    truncated=True,
                ),
            ),
        )

    monkeypatch.setattr(logs_command, "build_logs_result", build_logs_result)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["logs", "file:///tmp/run1", "build", "--stream", "stdout", "--tail", "1"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert calls == {
        "run_uri": "file:///tmp/run1",
        "stage_name": "build",
        "stream": "stdout",
        "tail": 1,
        "paths_only": False,
    }
    assert "stdout: /tmp/run1/stages/build/logs/stdout.log" in stdout.getvalue()
    assert "last" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_logs_invalid_tail_is_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["logs", "file:///tmp/run1", "build", "--tail", "0"],
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )

    assert stdout.getvalue() == ""
    assert "--tail must be a positive integer" in stderr.getvalue()
