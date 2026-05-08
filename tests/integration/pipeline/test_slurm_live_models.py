"""Integration coverage for SLURM live model and fake command flows."""

from __future__ import annotations

from typing import cast

from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmLiveSubmissionManifest,
    SlurmLiveSubmissionStatus,
    SlurmMode,
    SlurmOptions,
    SlurmSubmittedJob,
    build_single_job_planned_submission,
    live_manifest_from_planned_submission,
    parse_sbatch_parsable_output,
)


def test_fake_sbatch_flow_records_live_manifest_job_identity() -> None:
    planned = build_single_job_planned_submission(
        run_uri="file:///runs/run-1",
        planning_id="p1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(),
    )
    runner = FakeSlurmCommandRunner(starting_job_id=900)
    command_result = runner.sbatch("/runs/run-1/slurm/submissions/p1/scripts/pipeline.sh")
    parsed = parse_sbatch_parsable_output(command_result.stdout)
    draft = live_manifest_from_planned_submission(
        planned,
        status=SlurmLiveSubmissionStatus.SUBMITTED,
        updated_at="2026-05-08T00:00:03Z",
        submit_host="submit-host",
        submit_user="submit-user",
    )
    manifest = SlurmLiveSubmissionManifest(
        **{
            **draft.to_dict(),
            "submitted_jobs": [
                SlurmSubmittedJob(
                    logical_key="pipeline",
                    scheduler_job_id=parsed.job_id,
                    scheduler_cluster=parsed.cluster,
                    raw_job_id_output=parsed.raw_output,
                    submitted_at="2026-05-08T00:00:03Z",
                    command_record=command_result,
                    script_relative_path="slurm/submissions/p1/scripts/pipeline.sh",
                    stdout_relative_path="slurm/submissions/p1/logs/pipeline.stdout.log",
                    stderr_relative_path="slurm/submissions/p1/logs/pipeline.stderr.log",
                ).to_dict()
            ],
        }
    )

    assert runner.calls[0][0] == "sbatch"
    assert manifest.mode == SlurmMode.SINGLE_JOB
    assert manifest.submission_status == SlurmLiveSubmissionStatus.SUBMITTED
    assert manifest.summary_counts["submitted"] == 1
    assert manifest.manifest_relative_path == "slurm/submissions/p1/manifest.json"
    submitted_job = cast(SlurmSubmittedJob, manifest.submitted_jobs[0])
    assert submitted_job.scheduler_job_id == "900"


def test_fake_runner_can_model_delayed_empty_status_data() -> None:
    runner = FakeSlurmCommandRunner()

    assert runner.squeue(job_ids=("900",)).stdout == ""
    assert runner.sacct(job_ids=("900",)).stdout == ""
    assert [call[0] for call in runner.calls] == ["squeue", "sacct"]
