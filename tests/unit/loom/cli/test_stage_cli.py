"""Unit tests for ``loom stage`` worker commands."""

from __future__ import annotations

import io
import json

import pytest

import loom.cli.stage as stage_command
from loom.cli.main import main
from loom.pipeline.execution import (
    ExecutionFailure,
    StageWorkerResult,
    StageWorkerStateError,
)
from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    STAGE_WORKER_RESULT_SCHEMA_VERSION,
)
from loom.pipeline.status import StageStatus


pytestmark = pytest.mark.unit


def _worker_result(status: StageStatus = StageStatus.SUCCEEDED) -> StageWorkerResult:
    failure = None
    outputs = {}
    if status == StageStatus.FAILED:
        failure = ExecutionFailure(
            schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
            run_uri="file:///tmp/run",
            stage_name="build",
            attempt=1,
            failed_at="2020-01-01T00:00:02Z",
            executor="local",
            failure_type="stage_exception",
            message="boom",
        )
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri="file:///tmp/run",
        stage_name="build",
        attempt=1,
        status=status,
        started_at="2020-01-01T00:00:01Z",
        finished_at="2020-01-01T00:00:02Z",
        executor_name="local",
        outputs=outputs,
        failure=failure,
        exit_code=0 if status == StageStatus.SUCCEEDED else 1,
    )


def test_stage_run_success_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def run_worker(*, run_uri: str, stage_name: str, attempt: int | None) -> StageWorkerResult:
        calls["run_uri"] = run_uri
        calls["stage_name"] = stage_name
        calls["attempt"] = attempt
        return _worker_result()

    monkeypatch.setattr(stage_command, "_run_stage_worker", run_worker)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "stage",
                "run",
                "--run-uri",
                "file:///tmp/run",
                "--stage",
                "build",
                "--attempt",
                "1",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.stage.run.v1"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "SUCCEEDED"
    assert calls == {"run_uri": "file:///tmp/run", "stage_name": "build", "attempt": 1}
    assert stderr.getvalue() == ""


def test_stage_run_failure_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        stage_command,
        "_run_stage_worker",
        lambda **_kwargs: _worker_result(StageStatus.FAILED),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["stage", "run", "--run-uri", "file:///tmp/run", "--stage", "build"],
            stdout=stdout,
            stderr=stderr,
        )
        == 1
    )

    assert "FAILED stage run file:///tmp/run build attempt 1: FAILED" in stdout.getvalue()
    assert "failure stage_exception: boom" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_stage_run_state_error_returns_three_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_worker(**_kwargs: object) -> StageWorkerResult:
        raise StageWorkerStateError("worker request is missing")

    monkeypatch.setattr(stage_command, "_run_stage_worker", fail_worker)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "stage",
                "run",
                "--run-uri",
                "file:///tmp/run",
                "--stage",
                "build",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 3
    )

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "cli.stage.worker_state"
    assert payload["error"]["message"] == "worker request is missing"
    assert stderr.getvalue() == ""


def test_stage_run_invalid_attempt_is_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "stage",
                "run",
                "--run-uri",
                "file:///tmp/run",
                "--stage",
                "build",
                "--attempt",
                "0",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )

    assert stdout.getvalue() == ""
    assert "attempt must be a positive integer" in stderr.getvalue()
