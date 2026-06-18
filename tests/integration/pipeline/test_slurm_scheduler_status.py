"""Integration coverage for scheduler-aware SLURM status inspection."""

from __future__ import annotations

import json
from pathlib import Path

from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
    read_slurm_live_manifest,
)
from loom.pipeline.executors.slurm.status import inspect_slurm_job_status
from loom.pipeline.status import StageStatus, StageStatusRecord
from tests.support.slurm_status_fixtures import write_submitted_slurm_fixture


def test_scheduler_status_combines_accounting_queue_and_manifest(
    tmp_path: Path,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": (), "train": ("extract",), "report": ("train",)},
        starting_job_id=100,
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": (
                SlurmCommandResult(
                    command="sacct",
                    argv=("sacct",),
                    returncode=0,
                    stdout="100|COMPLETED|0:0\n",
                ),
            ),
            "squeue": (
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="101|RUNNING|None\n102|PENDING|Dependency\n",
                ),
            ),
        }
    )

    report = inspect_slurm_job_status(
        run_uri,
        run_store=store,
        command_runner=runner,
        captured_at="2026-05-08T00:00:10Z",
    )

    statuses = {job.logical_key: job.status for job in report.jobs}

    assert statuses == {
        "stage:extract": "SUCCEEDED",
        "stage:train": "RUNNING",
        "stage:report": "DEPENDENCY_BLOCKED",
    }
    assert report.jobs[2].warnings[0].code == "executor.slurm.status.worker_never_started"


def test_scheduler_status_uses_run_store_final_state_before_scheduler(
    tmp_path: Path,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=200,
    )
    store.write_stage_status(
        run_uri,
        "extract",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="extract",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2026-05-08T00:00:09Z",
        ),
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": (
                SlurmCommandResult(
                    command="sacct",
                    argv=("sacct",),
                    returncode=0,
                    stdout="200|FAILED|1:0\n",
                ),
            ),
            "squeue": (
                SlurmCommandResult(command="squeue", argv=("squeue",), returncode=0),
            ),
        }
    )

    report = inspect_slurm_job_status(
        run_uri,
        run_store=store,
        command_runner=runner,
        captured_at="2026-05-08T00:00:10Z",
    )

    assert report.jobs[0].status == "SUCCEEDED"
    assert report.jobs[0].source == "run_store"
    stage_status = store.read_stage_status(run_uri, "extract")
    assert stage_status is not None
    assert stage_status.status is StageStatus.SUCCEEDED


def test_scheduler_status_falls_back_to_stale_snapshot_when_commands_later_empty(
    tmp_path: Path,
) -> None:
    store, run_uri, manifest_path = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=300,
    )
    first_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": (
                SlurmCommandResult(command="sacct", argv=("sacct",), returncode=0),
            ),
            "squeue": (
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="300|RUNNING|None\n",
                ),
            ),
        }
    )
    inspect_slurm_job_status(
        run_uri,
        run_store=store,
        command_runner=first_runner,
        captured_at="2026-05-08T00:00:10Z",
    )

    second_runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": (
                SlurmCommandResult(command="sacct", argv=("sacct",), returncode=0),
            ),
            "squeue": (
                SlurmCommandResult(command="squeue", argv=("squeue",), returncode=0),
            ),
        }
    )
    report = inspect_slurm_job_status(
        run_uri,
        run_store=store,
        command_runner=second_runner,
        captured_at="2026-05-08T00:00:20Z",
    )
    manifest = read_slurm_live_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )

    assert report.jobs[0].status == "RUNNING"
    assert report.jobs[0].source == "snapshot"
    assert report.jobs[0].warnings[0].code == "executor.slurm.status.stale_snapshot"
    assert len(manifest.status_snapshots) == 2
