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
    StageReliabilitySummary,
    StageLogsSummary,
    StageStatusSummary,
    SubmittedOperationSummary,
)
from loom.pipeline.executors.slurm.status import (
    SlurmJobsStatusReport,
    SlurmJobStatusSummary,
    SlurmStatusWarning,
)


pytestmark = pytest.mark.unit


def test_status_json_uses_diagnostics_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        status_command,
        "build_status_result",
        lambda run_uri, authority_config=None: RunStatusSummary(
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
                    reliability=StageReliabilitySummary(
                        stage_name="build",
                        policy_count=1,
                        latest_policy={
                            "policy": {"retry": {"enabled": True, "max_attempts": 2}}
                        },
                    ),
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
    assert payload["result"]["state_source"]["label"] == "unknown"
    assert payload["result"]["submitted_operations"][0]["submission_id"] == "sub-1"
    assert payload["result"]["stages"][0]["state_source"]["label"] == "unknown"
    assert payload["result"]["stages"][0]["stage_name"] == "build"
    reliability = payload["result"]["stages"][0]["reliability"]
    assert reliability["counts"]["policy_facts"] == 1
    assert reliability["latest_policy"]["policy"]["retry"]["max_attempts"] == 2
    assert stderr.getvalue() == ""


def test_status_text_includes_reliability_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        status_command,
        "build_status_result",
        lambda run_uri, authority_config=None: RunStatusSummary(
            run_uri=run_uri,
            status="FAILED",
            stages=(
                StageStatusSummary(
                    stage_name="build",
                    status="FAILED",
                    reliability=StageReliabilitySummary(
                        stage_name="build",
                        policy_count=1,
                        transaction_count=1,
                        retry_decision_count=1,
                        timeout_outcome_count=1,
                        unsupported_timeout_count=1,
                        latest_policy={
                            "policy": {
                                "retry": {"enabled": True, "max_attempts": 2},
                                "timeout": {
                                    "enabled": True,
                                    "duration_seconds": 3.0,
                                },
                            }
                        },
                        latest_transaction={"state": "failed", "attempt": 1},
                        latest_retry_decision={
                            "decision_reason": "retry.disabled",
                            "should_retry": False,
                        },
                        latest_timeout_outcome={
                            "outcome": "unsupported",
                            "support_level": "unsupported",
                        },
                        diagnostics=(
                            {
                                "code": "reliability.timeout.unsupported",
                                "message": "timeout policy was selected but not enforced",
                                "details": {"stage_name": "build"},
                            },
                        ),
                    ),
                ),
            ),
        ),
    )
    stdout = io.StringIO()

    assert main(["status", "file:///tmp/run1"], stdout=stdout) == 0

    output = stdout.getvalue()
    assert "reliability: policies=1" in output
    assert "policy: retry=enabled max_attempts=2" in output
    assert "transaction: failed attempt=1" in output
    assert "retry: retry.disabled retry=False" in output
    assert "timeout: unsupported support=unsupported" in output
    assert "diagnostic: reliability.timeout.unsupported" in output


def test_status_jobs_json_uses_scheduler_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = SlurmStatusWarning(
        code="executor.slurm.status.scheduler_state_uncertain",
        message="state is uncertain",
        details={"scheduler_job_id": "123"},
    )
    monkeypatch.setattr(
        status_command,
        "build_status_jobs_result",
        lambda run_uri, authority_config=None: SlurmJobsStatusReport(
            run_uri=run_uri,
            run_status="SUBMITTED",
            submission={
                "submission_id": "sub-1",
                "backend": "slurm",
                "mode": "slurm-afterok",
                "state": "SUBMITTED",
                "created_at": "2026-05-08T00:00:00Z",
                "updated_at": "2026-05-08T00:00:01Z",
                "manifest_relative_path": "slurm/submissions/sub-1/manifest.json",
                "summary_counts": {"submitted": 1},
                "active": True,
            },
            manifest_path="/tmp/run/slurm/submissions/sub-1/manifest.json",
            manifest_relative_path="slurm/submissions/sub-1/manifest.json",
            jobs=(
                SlurmJobStatusSummary(
                    logical_key="stage:build",
                    stage_name="build",
                    scheduler_job_id="123",
                    status="SUBMITTED",
                    source="manifest",
                    scheduler_state="SUBMITTED",
                    loom_run_status="SUBMITTED",
                    loom_stage_status="SUBMITTED",
                    warnings=(warning,),
                ),
            ),
            warnings=(warning,),
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["status", "file:///tmp/run1", "--jobs", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == status_command.STATUS_JOBS_RESULT_SCHEMA_VERSION
    assert payload["warnings"][0]["code"] == warning.code
    assert payload["result"]["jobs"][0]["scheduler_job_id"] == "123"
    assert payload["result"]["jobs"][0]["warnings"][0]["code"] == warning.code
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
