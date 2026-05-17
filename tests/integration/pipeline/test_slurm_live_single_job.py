"""Integration tests for live single-job SLURM submission persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmCommandArgv,
    SlurmLiveSubmissionStatus,
    SlurmPlannedJob,
    plan_single_job_slurm_dry_run,
    read_slurm_live_manifest,
    submit_single_job_slurm,
)
from loom.pipeline.status import RunStatus
from loom.pipeline.submitted import SubmittedOperationState
from tests.integration.pipeline.test_slurm_dry_run_planning import _prepared_store


def test_live_single_job_submission_updates_manifest_registry_and_run_status(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"build": ()}, authority_backed=True)
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="planning-live",
        created_at="2026-05-08T00:00:00Z",
    )

    result = submit_single_job_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=FakeSlurmCommandRunner(starting_job_id=5678),
        submitted_at="2026-05-08T00:00:03Z",
    )

    manifest = read_slurm_live_manifest(
        json.loads(planning.manifest_artifact.local_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)
    status = store.read_run_status(run_uri)

    assert result.submitted_jobs[0]["scheduler_job_id"] == "5678"
    assert manifest.submission_status is SlurmLiveSubmissionStatus.SUBMITTED
    assert manifest.summary_counts["submitted"] == 1
    assert registry is not None
    assert registry.state is SubmittedOperationState.SUBMITTED
    assert registry.manifest_relative_path == planning.manifest_artifact.relative_path
    assert status is not None
    assert status.status is RunStatus.SUBMITTED


def test_live_single_job_submission_reuses_apptainer_wrapped_plan(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"build": ()}, authority_backed=True)
    planning = plan_single_job_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        container_options={"image": {"reference": "analysis.sif"}},
        planning_id="planning-live-container",
        created_at="2026-05-08T00:00:00Z",
    )
    runner = FakeSlurmCommandRunner(starting_job_id=6000)

    result = submit_single_job_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=runner,
        submitted_at="2026-05-08T00:00:03Z",
    )

    job = cast(SlurmPlannedJob, planning.submission.jobs[0])
    command = job.command
    assert result.status == "SUBMITTED"
    assert cast(SlurmCommandArgv, command).argv[:3] == (
        "apptainer",
        "exec",
        "--cleanenv",
    )
    assert "analysis.sif" in cast(SlurmCommandArgv, command).argv
    assert runner.calls[0][0] == "sbatch"
