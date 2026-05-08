"""Contract tests for planned SLURM dry-run manifest serialization."""

from __future__ import annotations

from pathlib import Path

from loom.pipeline.executors.slurm import (
    SlurmGeneratedArtifactPath,
    SlurmMode,
    SlurmOptions,
    SlurmPlannedDependency,
    SlurmPlannedJob,
    SlurmPlannedSubmission,
    SlurmSbatchDirective,
    build_single_job_command_argv,
)
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
    assert '"schema_version":1' in rendered
    assert '"mode":"slurm-single-job"' in rendered
    assert '"dry_run":true' in rendered
    assert '"logical_key":"pipeline"' in rendered
    assert '"type":"afterok"' in rendered
    assert '"argv":["uv","run","loom","prepared-run","continue"' in rendered
    assert "submitted" not in rendered
    assert "scheduler_job_id" not in rendered
    assert "scheduler_state" not in rendered
    assert "raw_adapter" not in rendered


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
