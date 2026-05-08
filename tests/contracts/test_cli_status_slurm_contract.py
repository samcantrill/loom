"""Contracts for scheduler-aware status CLI output."""

from __future__ import annotations

import json

import pytest

from loom.cli.formatting import format_json_envelope, format_status_jobs_text
from loom.cli.status import STATUS_JOBS_RESULT_SCHEMA_VERSION
from loom.pipeline.executors.slurm.status import (
    SlurmJobsStatusReport,
    SlurmJobStatusSummary,
    SlurmStatusWarning,
)

pytestmark = pytest.mark.contract


def test_status_jobs_json_schema_is_stable() -> None:
    warning = SlurmStatusWarning(
        code="executor.slurm.status.stale_snapshot",
        message="using persisted scheduler snapshot",
        details={"scheduler_job_id": "123"},
    )
    result = _result(warning)

    payload = json.loads(
        format_json_envelope(
            schema_version=STATUS_JOBS_RESULT_SCHEMA_VERSION,
            ok=True,
            warnings=(warning.to_dict(),),
            payload_name="result",
            payload=result.to_dict(),
        )
    )

    assert payload == {
        "schema_version": "loom.cli.status.jobs.v1",
        "ok": True,
        "warnings": [
            {
                "code": "executor.slurm.status.stale_snapshot",
                "message": "using persisted scheduler snapshot",
                "details": {"scheduler_job_id": "123"},
            }
        ],
        "result": {
            "run_uri": "file:///runs/demo",
            "run_status": "SUBMITTED",
            "submission": {
                "submission_id": "planning-1",
                "backend": "slurm",
                "mode": "slurm-afterok",
                "state": "SUBMITTED",
                "created_at": "2026-05-08T00:00:00Z",
                "updated_at": "2026-05-08T00:00:03Z",
                "manifest_relative_path": "slurm/submissions/planning-1/manifest.json",
                "summary_counts": {"submitted": 1},
                "active": True,
            },
            "manifest_path": "/runs/demo/slurm/submissions/planning-1/manifest.json",
            "manifest_relative_path": "slurm/submissions/planning-1/manifest.json",
            "job_count": 1,
            "jobs": [
                {
                    "logical_key": "stage:build",
                    "stage_name": "build",
                    "scheduler_job_id": "123",
                    "status": "RUNNING",
                    "source": "squeue",
                    "scheduler_state": "RUNNING",
                    "exit_code": None,
                    "dependency_state": None,
                    "dependency_job_ids": [],
                    "loom_run_status": "SUBMITTED",
                    "loom_stage_status": "SUBMITTED",
                    "log_paths": {
                        "stdout_relative_path": "slurm/submissions/planning-1/logs/stage-build.stdout.log",
                        "stderr_relative_path": "slurm/submissions/planning-1/logs/stage-build.stderr.log",
                    },
                    "backend_metadata": {"selected_source": "squeue"},
                    "warnings": [
                        {
                            "code": "executor.slurm.status.stale_snapshot",
                            "message": "using persisted scheduler snapshot",
                            "details": {"scheduler_job_id": "123"},
                        }
                    ],
                }
            ],
            "failed_submissions": [],
            "warnings": [
                {
                    "code": "executor.slurm.status.stale_snapshot",
                    "message": "using persisted scheduler snapshot",
                    "details": {"scheduler_job_id": "123"},
                }
            ],
        },
    }


def test_status_jobs_text_is_path_oriented() -> None:
    warning = SlurmStatusWarning(
        code="executor.slurm.status.stale_snapshot",
        message="using persisted scheduler snapshot",
        details={"scheduler_job_id": "123"},
    )

    text = format_status_jobs_text(_result(warning))

    assert "status file:///runs/demo jobs: SUBMITTED" in text
    assert "submission: planning-1 slurm/slurm-afterok SUBMITTED" in text
    assert "stage:build: 123 RUNNING scheduler=RUNNING source=squeue" in text
    assert "logs: stdout=slurm/submissions/planning-1/logs/stage-build.stdout.log" in text
    assert "warning executor.slurm.status.stale_snapshot" in text


def _result(warning: SlurmStatusWarning) -> SlurmJobsStatusReport:
    return SlurmJobsStatusReport(
        run_uri="file:///runs/demo",
        run_status="SUBMITTED",
        submission={
            "submission_id": "planning-1",
            "backend": "slurm",
            "mode": "slurm-afterok",
            "state": "SUBMITTED",
            "created_at": "2026-05-08T00:00:00Z",
            "updated_at": "2026-05-08T00:00:03Z",
            "manifest_relative_path": "slurm/submissions/planning-1/manifest.json",
            "summary_counts": {"submitted": 1},
            "active": True,
        },
        manifest_path="/runs/demo/slurm/submissions/planning-1/manifest.json",
        manifest_relative_path="slurm/submissions/planning-1/manifest.json",
        jobs=(
            SlurmJobStatusSummary(
                logical_key="stage:build",
                stage_name="build",
                scheduler_job_id="123",
                status="RUNNING",
                source="squeue",
                scheduler_state="RUNNING",
                loom_run_status="SUBMITTED",
                loom_stage_status="SUBMITTED",
                log_paths={
                    "stdout_relative_path": "slurm/submissions/planning-1/logs/stage-build.stdout.log",
                    "stderr_relative_path": "slurm/submissions/planning-1/logs/stage-build.stderr.log",
                },
                backend_metadata={"selected_source": "squeue"},
                warnings=(warning,),
            ),
        ),
        warnings=(warning,),
    )
