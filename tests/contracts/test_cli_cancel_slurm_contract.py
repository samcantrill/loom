"""Contracts for submitted-job cancellation CLI output."""

from __future__ import annotations

import json

import pytest

from loom.cli.cancel import CANCEL_JOBS_RESULT_SCHEMA_VERSION
from loom.cli.formatting import format_cancel_jobs_text, format_json_envelope
from loom.pipeline.executors.slurm.cancellation import (
    SlurmCancellationResult,
    SlurmJobCancellationResult,
)

pytestmark = pytest.mark.contract


def test_cancel_jobs_json_schema_is_stable() -> None:
    result = _result()

    payload = json.loads(
        format_json_envelope(
            schema_version=CANCEL_JOBS_RESULT_SCHEMA_VERSION,
            ok=True,
            warnings=[],
            payload_name="result",
            payload=result.to_dict(),
        )
    )

    assert payload == {
        "schema_version": "loom.cli.cancel.jobs.v1",
        "ok": True,
        "warnings": [],
        "result": {
            "run_uri": "file:///runs/demo",
            "submission_id": "planning-1",
            "status": "CANCELLED",
            "dry_run": False,
            "manifest_path": "/runs/demo/slurm/submissions/planning-1/manifest.json",
            "manifest_relative_path": "slurm/submissions/planning-1/manifest.json",
            "run_status_before": "SUBMITTED",
            "run_status_after": "CANCELLED",
            "cancelled_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "unknown_count": 0,
            "job_results": [
                {
                    "logical_key": "stage:build",
                    "stage_name": "build",
                    "scheduler_job_id": "123",
                    "outcome": "cancelled",
                    "stage_status_before": "SUBMITTED",
                    "stage_status_after": "CANCELLED",
                    "message": "cancelled",
                    "command_record": None,
                }
            ],
            "warnings": [],
        },
    }


def test_cancel_jobs_text_is_conservative_and_path_oriented() -> None:
    text = format_cancel_jobs_text(_result())

    assert "OK cancel file:///runs/demo: CANCELLED" in text
    assert "submission_id: planning-1" in text
    assert "manifest: /runs/demo/slurm/submissions/planning-1/manifest.json" in text
    assert "jobs: 1 cancelled, 0 failed, 0 skipped, 0 unknown" in text
    assert "stage:build: 123 cancelled" in text


def _result() -> SlurmCancellationResult:
    return SlurmCancellationResult(
        run_uri="file:///runs/demo",
        submission_id="planning-1",
        status="CANCELLED",
        manifest_path="/runs/demo/slurm/submissions/planning-1/manifest.json",
        manifest_relative_path="slurm/submissions/planning-1/manifest.json",
        run_status_before="SUBMITTED",
        run_status_after="CANCELLED",
        cancelled_count=1,
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
    )
