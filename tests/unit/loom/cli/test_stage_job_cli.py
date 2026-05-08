"""Unit tests for ``loom stage-job`` commands."""

from __future__ import annotations

import io
import json

from loom.cli.main import main


def test_stage_job_run_rejects_recursive_executor_before_run_state() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "stage-job",
            "run",
            "--run-uri",
            "file:///tmp/missing-run",
            "--stage",
            "build",
            "--executor",
            "slurm-afterok",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert code == 7
    assert payload["ok"] is False
    assert payload["error"]["code"] == "execution.continuation.unsupported_executor"
    assert payload["error"]["context"]["executor"] == "slurm-afterok"
    assert stderr.getvalue() == ""


def test_stage_job_run_invalid_attempt_is_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "stage-job",
                "run",
                "--run-uri",
                "file:///tmp/run",
                "--stage",
                "build",
                "--executor",
                "local",
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
