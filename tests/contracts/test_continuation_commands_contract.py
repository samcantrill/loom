"""Contract tests for generic continuation command envelopes."""

from __future__ import annotations

import io
import json

import pytest

from loom.cli.main import main


pytestmark = pytest.mark.contract


def test_stage_job_error_envelope_schema_and_code_are_stable() -> None:
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
    assert payload["schema_version"] == "loom.cli.error.v2"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "execution.continuation.unsupported_executor"
    assert payload["error"]["context"]["executor"] == "slurm-afterok"
    assert stderr.getvalue() == ""


def test_prepared_run_error_envelope_schema_and_code_are_stable() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "prepared-run",
            "continue",
            "--run-uri",
            "file:///tmp/missing-run",
            "--executor",
            "slurm-single-job",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert code == 7
    assert payload["schema_version"] == "loom.cli.error.v2"
    assert payload["ok"] is False
    assert payload["error"]["code"] == "execution.continuation.unsupported_executor"
    assert payload["error"]["context"]["executor"] == "slurm-single-job"
    assert stderr.getvalue() == ""
