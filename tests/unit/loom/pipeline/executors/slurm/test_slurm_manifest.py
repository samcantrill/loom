"""Unit tests for SLURM planned submission manifests."""

from __future__ import annotations

import pytest

from loom.pipeline.executors.slurm import (
    SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION,
    SlurmDependencyType,
    SlurmManifestError,
    SlurmMode,
    SlurmPlannedDependency,
    SlurmPlannedJob,
    SlurmPlannedSubmission,
    SlurmSbatchDirective,
    build_stage_job_command_argv,
    pipeline_job_key,
    stage_job_key,
    validate_logical_job_key,
)


def test_logical_job_keys_validate_pipeline_and_stage_names() -> None:
    assert pipeline_job_key() == "pipeline"
    assert stage_job_key("build") == "stage:build"
    assert validate_logical_job_key("stage:build") == "stage:build"

    with pytest.raises(SlurmManifestError, match="stage_name"):
        stage_job_key("bad name")
    with pytest.raises(SlurmManifestError, match="logical_job_key"):
        validate_logical_job_key("build")


def test_dependency_records_use_afterok_and_logical_keys() -> None:
    dependency = SlurmPlannedDependency(
        job_key="stage:report",
        upstream_job_keys=("stage:build",),
    )

    assert dependency.dependency_type is SlurmDependencyType.AFTEROK
    assert dependency.to_dict() == {
        "job_key": "stage:report",
        "type": "afterok",
        "upstream_job_keys": ["stage:build"],
    }
    assert SlurmPlannedDependency.from_dict(dependency.to_dict()) == dependency

    with pytest.raises(SlurmManifestError, match="afterok"):
        SlurmPlannedDependency.from_dict(
            {
                "job_key": "stage:report",
                "type": "afterany",
                "upstream_job_keys": ["stage:build"],
            }
        )


def test_planned_job_round_trip_omits_scheduler_job_id() -> None:
    job = SlurmPlannedJob(
        logical_key="stage:build",
        mode=SlurmMode.AFTEROK,
        command=build_stage_job_command_argv("file:///runs/run-1", "build"),
        dependency_job_keys=("pipeline",),
        resources={"cpu": {"amount": 2, "unit": "count"}},
        sbatch_directives=(
            SlurmSbatchDirective(
                name="cpus-per-task",
                value="2",
                source="resource:cpu",
            ),
        ),
        script_relative_path="slurm/submissions/p1/scripts/stage-build.sh",
        stdout_relative_path="slurm/submissions/p1/logs/stage-build.stdout.log",
        stderr_relative_path="slurm/submissions/p1/logs/stage-build.stderr.log",
    )

    payload = job.to_dict()

    assert "scheduler_job_id" not in payload
    assert SlurmPlannedJob.from_dict(payload) == job


def test_planned_job_allows_null_scheduler_job_id_but_rejects_value() -> None:
    payload = {
        "logical_key": "pipeline",
        "mode": "slurm-single-job",
        "command": {
            "launcher_argv": ["loom"],
            "command_args": [
                "prepared-run",
                "continue",
                "--run-uri",
                "file:///runs/run-1",
                "--executor",
                "local",
            ],
        },
        "scheduler_job_id": None,
    }
    assert SlurmPlannedJob.from_dict(payload).logical_key == "pipeline"

    payload["scheduler_job_id"] = "123"
    with pytest.raises(SlurmManifestError, match="scheduler_job_id"):
        SlurmPlannedJob.from_dict(payload)


def test_planned_submission_round_trip_is_schema_versioned() -> None:
    command = build_stage_job_command_argv("file:///runs/run-1", "build")
    job = SlurmPlannedJob(
        logical_key="stage:build",
        mode=SlurmMode.AFTEROK,
        command=command,
        manifest_relative_path="slurm/submissions/p1/manifest.json",
    )
    dependency = SlurmPlannedDependency(
        job_key="stage:build",
        upstream_job_keys=("pipeline",),
    )
    manifest = SlurmPlannedSubmission(
        run_uri="file:///runs/run-1",
        mode=SlurmMode.AFTEROK,
        planning_id="p1",
        created_at="2026-05-08T00:00:00Z",
        plan_relative_path="slurm/submissions/p1/plan.json",
        jobs=(job,),
        dependencies=(dependency,),
        generated_command_argv=(command,),
        resources={"stage:build": {"cpu": {"amount": 2}}},
    )

    payload = manifest.to_dict()

    assert payload["schema_version"] == SLURM_PLANNED_SUBMISSION_SCHEMA_VERSION
    assert payload["dry_run"] is True
    assert payload["mode"] == "slurm-afterok"
    assert payload["manifest_relative_path"] == "slurm/submissions/p1/manifest.json"
    assert "submitted_status" not in payload
    assert "scheduler_state" not in payload
    assert SlurmPlannedSubmission.from_dict(payload) == manifest

    payload["unknown"] = "x"
    with pytest.raises(SlurmManifestError, match="unknown field"):
        SlurmPlannedSubmission.from_dict(payload)
