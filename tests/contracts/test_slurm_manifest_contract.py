"""Contract tests for planned SLURM dry-run manifest serialization."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline.executors.slurm import (
    SLURM_LIVE_SUBMISSION_SCHEMA_VERSION,
    SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION,
    SlurmCommandResult,
    SlurmGeneratedArtifactPath,
    SlurmLiveSubmissionManifest,
    SlurmLiveSubmissionStatus,
    SlurmMode,
    SlurmOptions,
    SlurmPlannedDependency,
    SlurmPlannedJob,
    SlurmPlannedSubmission,
    SlurmSbatchDirective,
    SlurmSubmittedJob,
    build_single_job_command_argv,
    live_manifest_from_planned_submission,
)
from loom.pipeline.executors.slurm.errors import SlurmManifestError
from loom.pipeline.executors.slurm.artifacts import SlurmDryRunPlanningResult
from loom.serialization import ensure_plain_data, stable_json_dumps


def test_slurm_planned_submission_manifest_schema_is_stable_plain_data() -> None:
    command = build_single_job_command_argv(
        "file:///runs/run-1",
        launcher_argv=("uv", "run", "loom"),
    )
    manifest = SlurmPlannedSubmission(
        run_uri="file:///runs/run-1",
        mode=SlurmMode.SINGLE_JOB,
        planning_id="p1",
        created_at="2026-05-08T00:00:00Z",
        plan_relative_path="slurm/submissions/p1/plan.json",
        manifest_relative_path="slurm/submissions/p1/manifest.json",
        options=SlurmOptions(partition="debug", extra_sbatch={"requeue": True}),
        jobs=(
            SlurmPlannedJob(
                logical_key="pipeline",
                mode=SlurmMode.SINGLE_JOB,
                command=command,
                resources={"cpu": {"amount": 4, "unit": "count"}},
                sbatch_directives=(
                    SlurmSbatchDirective(
                        name="partition",
                        value="debug",
                        source="option",
                    ),
                    SlurmSbatchDirective(
                        name="cpus-per-task",
                        value="4",
                        source="resource:cpu",
                    ),
                ),
                script_relative_path="slurm/submissions/p1/scripts/pipeline.sh",
                stdout_relative_path="slurm/submissions/p1/logs/pipeline.stdout.log",
                stderr_relative_path="slurm/submissions/p1/logs/pipeline.stderr.log",
                manifest_relative_path="slurm/submissions/p1/manifest.json",
            ),
        ),
        dependencies=(
            SlurmPlannedDependency(job_key="pipeline", upstream_job_keys=()),
        ),
        generated_command_argv=(command,),
        resources={"pipeline": {"cpu": {"amount": 4, "unit": "count"}}},
    )

    payload = manifest.to_dict()
    normalized = ensure_plain_data(payload)
    rendered = stable_json_dumps(normalized)

    assert SlurmPlannedSubmission.from_dict(normalized).to_dict() == payload
    assert stable_json_dumps(payload) == rendered
    assert f'"schema_version":{SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION}' in rendered
    assert '"mode":"slurm-single-job"' in rendered
    assert '"dry_run":true' in rendered
    assert '"logical_key":"pipeline"' in rendered
    assert '"type":"afterok"' in rendered
    assert '"argv":["uv","run","loom","prepared-run","continue"' in rendered
    assert "submitted" not in rendered
    assert "scheduler_job_id" not in rendered
    assert "scheduler_state" not in rendered
    assert "raw_adapter" not in rendered


def test_slurm_live_manifest_schema_extends_canonical_manifest_path() -> None:
    command = build_single_job_command_argv("file:///runs/run-1")
    planned = SlurmPlannedSubmission(
        run_uri="file:///runs/run-1",
        mode=SlurmMode.SINGLE_JOB,
        planning_id="p1",
        created_at="2026-05-08T00:00:00Z",
        plan_relative_path="slurm/submissions/p1/plan.json",
        manifest_relative_path="slurm/submissions/p1/manifest.json",
        jobs=(
            SlurmPlannedJob(
                logical_key="pipeline",
                mode=SlurmMode.SINGLE_JOB,
                command=command,
                script_relative_path="slurm/submissions/p1/scripts/pipeline.sh",
                stdout_relative_path="slurm/submissions/p1/logs/pipeline.stdout.log",
                stderr_relative_path="slurm/submissions/p1/logs/pipeline.stderr.log",
            ),
        ),
        generated_command_argv=(command,),
    )
    command_record = SlurmCommandResult(
        command="sbatch",
        argv=("sbatch", "--parsable", "pipeline.sh"),
        returncode=0,
        stdout="123456;cluster-a\n",
        started_at="2026-05-08T00:00:01Z",
        finished_at="2026-05-08T00:00:02Z",
    )
    manifest = live_manifest_from_planned_submission(
        planned,
        status=SlurmLiveSubmissionStatus.SUBMITTED,
        updated_at="2026-05-08T00:00:02Z",
        submit_host="submit-host",
        submit_user="submit-user",
    )
    manifest = SlurmLiveSubmissionManifest(
        **{
            **manifest.to_dict(),
            "submitted_jobs": [
                SlurmSubmittedJob(
                    logical_key="pipeline",
                    scheduler_job_id="123456",
                    scheduler_cluster="cluster-a",
                    raw_job_id_output="123456;cluster-a\n",
                    submitted_at="2026-05-08T00:00:02Z",
                    command_record=command_record,
                    script_relative_path="slurm/submissions/p1/scripts/pipeline.sh",
                    stdout_relative_path="slurm/submissions/p1/logs/pipeline.stdout.log",
                    stderr_relative_path="slurm/submissions/p1/logs/pipeline.stderr.log",
                ).to_dict()
            ],
        }
    )

    payload = ensure_plain_data(manifest.to_dict())
    rendered = stable_json_dumps(payload)

    assert SlurmLiveSubmissionManifest.from_dict(payload).to_dict() == manifest.to_dict()
    assert f'"schema_version":{SLURM_LIVE_SUBMISSION_SCHEMA_VERSION}' in rendered
    assert '"dry_run":false' in rendered
    assert '"manifest_relative_path":"slurm/submissions/p1/manifest.json"' in rendered
    assert '"submission_status":"SUBMITTED"' in rendered
    assert '"scheduler_job_id":"123456"' in rendered
    assert "submission.json" not in rendered
    assert "raw_adapter" not in rendered


def test_slurm_live_manifest_rejects_dependency_ids_without_upstream_submission() -> None:
    command = build_single_job_command_argv("file:///runs/run-1")
    payload = {
        "schema_version": SLURM_LIVE_SUBMISSION_SCHEMA_VERSION,
        "run_uri": "file:///runs/run-1",
        "mode": SlurmMode.AFTEROK.value,
        "dry_run": False,
        "planning_id": "p1",
        "submission_id": "p1",
        "created_at": "2026-05-08T00:00:00Z",
        "updated_at": "2026-05-08T00:00:02Z",
        "plan_relative_path": "slurm/submissions/p1/plan.json",
        "manifest_relative_path": "slurm/submissions/p1/manifest.json",
        "options": SlurmOptions().to_dict(),
        "jobs": [
            SlurmPlannedJob(
                logical_key="stage:build",
                mode=SlurmMode.AFTEROK,
                command=command,
            ).to_dict(),
            SlurmPlannedJob(
                logical_key="stage:train",
                mode=SlurmMode.AFTEROK,
                command=command,
                dependency_job_keys=("stage:build",),
            ).to_dict(),
        ],
        "dependencies": [
            SlurmPlannedDependency(
                job_key="stage:train",
                upstream_job_keys=("stage:build",),
            ).to_dict(),
        ],
        "generated_command_argv": [],
        "resources": {},
        "submission_status": SlurmLiveSubmissionStatus.SUBMITTED.value,
        "submitted_at": "2026-05-08T00:00:02Z",
        "completed_at": None,
        "submit_host": None,
        "submit_user": None,
        "submitted_jobs": [
            SlurmSubmittedJob(
                logical_key="stage:train",
                scheduler_job_id="123",
                raw_job_id_output="123\n",
                submitted_at="2026-05-08T00:00:02Z",
                dependency_job_ids=("999",),
                command_record=SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "train.sh"),
                    returncode=0,
                    stdout="123\n",
                ),
            ).to_dict(),
        ],
        "failed_submissions": [],
        "status_snapshots": [],
        "cancellation_attempts": [],
    }

    with pytest.raises(SlurmManifestError):
        SlurmLiveSubmissionManifest.from_dict(payload)


def test_slurm_dry_run_planning_result_serializes_stable_artifact_paths() -> None:
    command = build_single_job_command_argv("file:///runs/run-1")
    submission = SlurmPlannedSubmission(
        run_uri="file:///runs/run-1",
        mode=SlurmMode.SINGLE_JOB,
        planning_id="p1",
        created_at="2026-05-08T00:00:00Z",
        plan_relative_path="slurm/submissions/p1/plan.json",
        manifest_relative_path="slurm/submissions/p1/manifest.json",
        jobs=(
            SlurmPlannedJob(
                logical_key="pipeline",
                mode=SlurmMode.SINGLE_JOB,
                command=command,
                script_relative_path="slurm/submissions/p1/scripts/pipeline.sh",
            ),
        ),
        generated_command_argv=(command,),
    )
    result = SlurmDryRunPlanningResult(
        submission=submission,
        plan_artifact=SlurmGeneratedArtifactPath(
            relative_path="slurm/submissions/p1/plan.json",
            local_path=Path("/tmp/runs/run-1/slurm/submissions/p1/plan.json"),
        ),
        manifest_artifact=SlurmGeneratedArtifactPath(
            relative_path="slurm/submissions/p1/manifest.json",
            local_path=Path("/tmp/runs/run-1/slurm/submissions/p1/manifest.json"),
        ),
        script_artifacts={
            "pipeline": SlurmGeneratedArtifactPath(
                relative_path="slurm/submissions/p1/scripts/pipeline.sh",
                local_path=Path(
                    "/tmp/runs/run-1/slurm/submissions/p1/scripts/pipeline.sh"
                ),
            )
        },
    )

    payload = ensure_plain_data(result.to_dict())
    rendered = stable_json_dumps(payload)

    assert stable_json_dumps(result.to_dict()) == rendered
    assert '"relative_path":"slurm/submissions/p1/manifest.json"' in rendered
    assert '"script_artifacts":{"pipeline":' in rendered
    assert "scheduler_job_id" not in rendered
