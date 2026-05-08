"""Integration tests for ``loom status`` and ``loom logs``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState


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


def _write_two_stage_pipeline_config(path: Path) -> None:
    path.write_text(
        "pipeline:\n"
        "  name: demo\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      config:\n"
        "        value: 1\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.TextConsumerStage\n"
        "      depends_on: [build]\n"
        "      inputs:\n"
        "        data: build.data\n"
        "      outputs:\n"
        "        text:\n"
        "          artifact_type: text\n"
        "          codec_key: text.v1\n",
        encoding="utf-8",
    )


def _run_pipeline(
    tmp_path: Path,
    *,
    failing: bool = False,
    executor: str = "local",
) -> str:
    config_path = tmp_path / "pipeline.yaml"
    suffix = f"{executor}-{'failed' if failing else 'ok'}"
    run_uri = path_to_run_uri(tmp_path / "runs" / suffix)
    _write_pipeline_config(config_path, failing=failing)
    stdout = io.StringIO()
    stderr = io.StringIO()
    expected = 5 if failing else 0

    argv = ["run", str(config_path), "--run-uri", run_uri, "--format", "json"]
    if executor != "local":
        argv.extend(["--executor", executor])
    assert (
        main(
            argv,
            stdout=stdout,
            stderr=stderr,
        )
        == expected
    )
    assert stderr.getvalue() == ""
    return run_uri


def _run_two_stage_pipeline(tmp_path: Path) -> str:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "ok")
    _write_two_stage_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", str(config_path), "--run-uri", run_uri, "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )
    assert stderr.getvalue() == ""
    return run_uri


def test_status_summarizes_successful_run(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path)
    LocalRunStore().write_stage_log(run_uri, "build", "stdout", "a\nb\nc\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["status", run_uri, "--format", "json"], stdout=stdout, stderr=stderr) == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.status.v3"
    assert payload["result"]["status"] == "SUCCEEDED"
    assert payload["result"]["artifact_count"] == 1
    assert payload["result"]["stages"][0]["stage_name"] == "build"
    assert payload["result"]["stages"][0]["log_available"]["stdout"] is True
    assert stderr.getvalue() == ""


def test_status_reports_persisted_submitted_state_without_scheduler_access(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "runs" / "submitted")
    store = LocalRunStore(tmp_path / "runs")
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUBMITTED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUBMITTED,
            attempt=1,
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="sub-1",
            backend="test-backend",
            mode="batch",
            created_at="2020-01-01T00:00:01Z",
            updated_at="2020-01-01T00:00:01Z",
            state=SubmittedOperationState.SUBMITTED,
            manifest_relative_path="submitted/sub-1/manifest.json",
            summary_counts={"submitted": 1},
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["status", run_uri, "--format", "json"], stdout=stdout, stderr=stderr) == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["status"] == "SUBMITTED"
    assert payload["result"]["stages"][0]["status"] == "SUBMITTED"
    assert payload["result"]["submitted_operations"][0]["submission_id"] == "sub-1"
    assert payload["result"]["submitted_operations"][0]["active"] is True
    assert stderr.getvalue() == ""


def test_logs_returns_bounded_content(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path)
    LocalRunStore().write_stage_log(run_uri, "build", "stdout", "a\nb\nc\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "logs",
                run_uri,
                "build",
                "--stream",
                "stdout",
                "--tail",
                "2",
                "--format",
                "json",
            ],
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

    assert (
        main(
            ["status", run_uri, "--format", "json"], stdout=status_stdout, stderr=stderr
        )
        == 0
    )
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
    assert (
        json.loads(logs_stdout.getvalue())["result"]["streams"][0]["content"]
        == "failed\n"
    )


def test_status_and_logs_report_subprocess_failure_metadata(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path, failing=True, executor="subprocess")
    status_stdout = io.StringIO()
    logs_stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["status", run_uri, "--format", "json"], stdout=status_stdout, stderr=stderr
        )
        == 0
    )
    status_payload = json.loads(status_stdout.getvalue())
    stage = status_payload["result"]["stages"][0]
    failure = stage["failure"]
    assert stage["status"] == "FAILED"
    assert failure["executor"] == "subprocess"
    assert failure["exit_code"] == 1
    assert failure["signal"] is None
    assert failure["stdout_path"].endswith("/stages/build/logs/stdout.log")
    assert failure["stderr_path"].endswith("/stages/build/logs/stderr.log")
    assert failure["traceback_path"].endswith("/stages/build/logs/traceback.txt")

    assert (
        main(
            ["logs", run_uri, "build", "--stream", "stderr", "--format", "json"],
            stdout=logs_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    logs_payload = json.loads(logs_stdout.getvalue())
    assert logs_payload["result"]["streams"][0]["available"] is True
    assert logs_payload["result"]["streams"][0]["content"] is not None


def test_logs_missing_stage_fails_clearly(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["logs", run_uri, "missing", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 6
    )

    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "cli.logs.run_state_error"
    assert "unknown stage" in payload["error"]["message"]
    assert stderr.getvalue() == ""


def test_artifacts_list_and_show_multiple_artifacts(tmp_path: Path) -> None:
    run_uri = _run_two_stage_pipeline(tmp_path)
    list_stdout = io.StringIO()
    show_stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["artifacts", "list", run_uri, "--format", "json"],
            stdout=list_stdout,
            stderr=stderr,
        )
        == 0
    )
    list_payload = json.loads(list_stdout.getvalue())
    assert list_payload["schema_version"] == "loom.cli.artifacts.list.v3"
    assert list_payload["result"]["artifact_count"] == 2
    assert [artifact["key"] for artifact in list_payload["result"]["artifacts"]] == [
        "build.data",
        "report.text",
    ]
    assert [
        artifact["artifact_id"] for artifact in list_payload["result"]["artifacts"]
    ] == [
        "build/data",
        "report/text",
    ]

    assert (
        main(
            ["artifacts", "show", run_uri, "report/text", "--format", "json"],
            stdout=show_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    show_payload = json.loads(show_stdout.getvalue())
    assert show_payload["schema_version"] == "loom.cli.artifacts.show.v3"
    assert show_payload["result"]["artifact"]["artifact_type"] == "text"
    assert show_payload["result"]["artifact"]["producer_stage"] == "report"
    assert show_payload["result"]["stage_provenance"] is not None
    assert stderr.getvalue() == ""


def test_artifacts_missing_artifact_id_fails_clearly(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["artifacts", "show", run_uri, "missing/out", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 6
    )

    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "cli.artifacts.run_state_error"
    assert "unknown artifact" in payload["error"]["message"]
    assert stderr.getvalue() == ""


def test_artifacts_list_failed_run_with_no_artifacts(tmp_path: Path) -> None:
    run_uri = _run_pipeline(tmp_path, failing=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["artifacts", "list", run_uri, "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["artifact_count"] == 0
    assert payload["result"]["artifacts"] == []
    assert stderr.getvalue() == ""
