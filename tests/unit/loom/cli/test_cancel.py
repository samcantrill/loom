"""Unit tests for ``loom cancel`` command orchestration."""

from __future__ import annotations

import io
import json

import pytest

from loom.cli.main import main
import loom.cli.cancel as cancel_command
from loom.pipeline.executors.slurm.cancellation import (
    SlurmCancellationResult,
    SlurmJobCancellationResult,
)

pytestmark = pytest.mark.unit


def test_cancel_jobs_json_uses_result_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cancel_command,
        "build_cancel_jobs_result",
        lambda run_uri, authority_config=None: SlurmCancellationResult(
            run_uri=run_uri,
            submission_id="planning-1",
            status="CANCELLED",
            manifest_path="/tmp/run/slurm/submissions/planning-1/manifest.json",
            manifest_relative_path="slurm/submissions/planning-1/manifest.json",
            job_results=(
                SlurmJobCancellationResult(
                    logical_key="stage:build",
                    stage_name="build",
                    scheduler_job_id="123",
                    outcome="cancelled",
                    stage_status_before="SUBMITTED",
                    stage_status_after="CANCELLED",
                    message="cancelled",
                ),
            ),
            run_status_before="SUBMITTED",
            run_status_after="CANCELLED",
            cancelled_count=1,
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["cancel", "file:///tmp/run1", "--jobs", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == cancel_command.CANCEL_JOBS_RESULT_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["result"]["status"] == "CANCELLED"
    assert payload["result"]["job_results"][0]["outcome"] == "cancelled"
    assert stderr.getvalue() == ""


def test_cancel_requires_jobs_flag() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["cancel", "file:///tmp/run1"], stdout=stdout, stderr=stderr) == 2

    assert stdout.getvalue() == ""
    assert "requires --jobs" in stderr.getvalue()
