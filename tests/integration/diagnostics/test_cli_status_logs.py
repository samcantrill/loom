"""Integration tests for ``loom status`` and ``loom logs``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.stores import LocalRunStore, path_to_run_uri


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _write_pipeline_config(path: Path, *, failing: bool = False) -> None:
    target = (
        "tests.support.pipeline_execution_stages.FailingStage"
        if failing
        else "tests.support.pipeline_execution_stages.JsonProducerStage"
    )
    config_block = "" if failing else "      config:\n        value: 1\n"
    path.write_text(
        "pipeline:\n"
        "  name: demo\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        f"        _target_: {target}\n"
        f"{config_block}"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n",
        encoding="utf-8",
    )


def _run_pipeline(tmp_path: Path, *, failing: bool = False) -> str:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / ("failed" if failing else "ok"))
    _write_pipeline_config(config_path, failing=failing)
    stdout = io.StringIO()
    stderr = io.StringIO()
    expected = 5 if failing else 0

    assert (
        main(
            ["run", str(config_path), "--run-uri", run_uri, "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == expected
    )
    assert stderr.getvalue() == ""
    return run_uri


def test_status_summarizes_successful_run(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path)
    LocalRunStore().write_stage_log(run_uri, "build", "stdout", "a\nb\nc\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["status", run_uri, "--format", "json"], stdout=stdout, stderr=stderr) == 0

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.status.v3"
    assert payload["result"]["status"] == "SUCCEEDED"
    assert payload["result"]["artifact_count"] == 1
    assert payload["result"]["stages"][0]["stage_name"] == "build"
    assert payload["result"]["stages"][0]["log_available"]["stdout"] is True
    assert stderr.getvalue() == ""


def test_logs_returns_bounded_content(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path)
    LocalRunStore().write_stage_log(run_uri, "build", "stdout", "a\nb\nc\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["logs", run_uri, "build", "--stream", "stdout", "--tail", "2", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    stream = payload["result"]["streams"][0]
    assert payload["schema_version"] == "loom.cli.logs.v3"
    assert stream["content"] == "b\nc\n"
    assert stream["displayed_line_count"] == 2
    assert stream["truncated"] is True
    assert stderr.getvalue() == ""


def test_status_and_logs_report_failed_run(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path, failing=True)
    LocalRunStore().write_stage_log(run_uri, "build", "stderr", "failed\n")
    status_stdout = io.StringIO()
    logs_stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["status", run_uri, "--format", "json"], stdout=status_stdout, stderr=stderr) == 0
    status_payload = json.loads(status_stdout.getvalue())
    assert status_payload["result"]["status"] == "FAILED"
    assert status_payload["result"]["stages"][0]["status"] == "FAILED"
    assert status_payload["result"]["stages"][0]["failure"] is not None

    assert (
        main(
            ["logs", run_uri, "build", "--stream", "stderr", "--format", "json"],
            stdout=logs_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert json.loads(logs_stdout.getvalue())["result"]["streams"][0]["content"] == "failed\n"


def test_logs_missing_stage_fails_clearly(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["logs", run_uri, "missing", "--format", "json"], stdout=stdout, stderr=stderr)
        == 6
    )

    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "cli.logs.run_state_error"
    assert "unknown stage" in payload["error"]["message"]
    assert stderr.getvalue() == ""
