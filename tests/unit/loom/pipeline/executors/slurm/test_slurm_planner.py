"""Unit tests for SLURM dry-run planning."""

from __future__ import annotations

from typing import cast

import pytest

from loom.pipeline.executors.slurm import (
    SlurmCommandArgv,
    SlurmMode,
    SlurmOptions,
    SlurmPlannedDependency,
    SlurmPlannedJob,
    SlurmSbatchDirective,
)
from loom.pipeline.executors.slurm.planning import (
    build_afterok_planned_submission,
    build_single_job_planned_submission,
)
from loom.pipeline.planning import (
    ExecutionPlan,
    FingerprintContext,
    FingerprintStatus,
    PlanAction,
    PlanSelectors,
    ResumeOptions,
    StagePlan,
)


def test_single_job_planned_submission_uses_prepared_run_continuation() -> None:
    first = build_single_job_planned_submission(
        run_uri="file:///runs/run-1",
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(launcher_argv=("uv", "run", "loom")),
    )
    second = build_single_job_planned_submission(
        run_uri="file:///runs/run-1",
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(launcher_argv=("uv", "run", "loom")),
    )

    assert first.to_dict() == second.to_dict()
    assert first.mode is SlurmMode.SINGLE_JOB
    first_jobs = cast(tuple[SlurmPlannedJob, ...], first.jobs)
    assert first_jobs[0].logical_key == "pipeline"
    command = cast(SlurmCommandArgv, first_jobs[0].command)
    assert command.argv == (
        "uv",
        "run",
        "loom",
        "prepared-run",
        "continue",
        "--run-uri",
        "file:///runs/run-1",
        "--executor",
        "local",
    )


def test_single_job_planning_wraps_continuation_in_apptainer() -> None:
    submission = build_single_job_planned_submission(
        run_uri="file:///runs/run-1",
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(),
        container_options={"image": {"reference": "analysis.sif"}},
        apptainer_options={"nv": True},
    )

    job = cast(tuple[SlurmPlannedJob, ...], submission.jobs)[0]
    command = cast(SlurmCommandArgv, job.command)

    assert command.argv[:4] == ("apptainer", "exec", "--cleanenv", "--nv")
    assert command.argv[-7:] == (
        "loom",
        "prepared-run",
        "continue",
        "--run-uri",
        "file:///runs/run-1",
        "--executor",
        "local",
    )
    assert command.metadata["container_runtime"] == "apptainer"
    assert command.to_dict()["metadata"] == dict(command.metadata)


@pytest.mark.parametrize(
    ("stage_upstreams", "expected_dependencies"),
    (
        (
            {"extract": (), "train": ("extract",), "report": ("train",)},
            {
                "stage:train": ("stage:extract",),
                "stage:report": ("stage:train",),
            },
        ),
        (
            {"extract": (), "clean": (), "join": ("extract", "clean")},
            {"stage:join": ("stage:extract", "stage:clean")},
        ),
        (
            {"extract": (), "train": ("extract",), "report": ("extract",)},
            {
                "stage:train": ("stage:extract",),
                "stage:report": ("stage:extract",),
            },
        ),
        (
            {
                "extract": (),
                "features": ("extract",),
                "train": ("extract",),
                "report": ("features", "train"),
            },
            {
                "stage:features": ("stage:extract",),
                "stage:train": ("stage:extract",),
                "stage:report": ("stage:features", "stage:train"),
            },
        ),
    ),
)
def test_afterok_planning_derives_logical_dependencies_from_stage_plan_upstreams(
    stage_upstreams: dict[str, tuple[str, ...]],
    expected_dependencies: dict[str, tuple[str, ...]],
) -> None:
    plan = _execution_plan(stage_upstreams)

    submission = build_afterok_planned_submission(
        run_uri="file:///runs/run-1",
        execution_plan=plan,
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(),
    )

    jobs = cast(tuple[SlurmPlannedJob, ...], submission.jobs)
    dependencies = cast(tuple[SlurmPlannedDependency, ...], submission.dependencies)
    assert [job.logical_key for job in jobs] == [
        f"stage:{stage_name}" for stage_name in stage_upstreams
    ]
    assert {
        dependency.job_key: tuple(dependency.upstream_job_keys)
        for dependency in dependencies
    } == expected_dependencies
    for job in jobs:
        command = cast(SlurmCommandArgv, job.command)
        assert command.command_args[:2] == ("stage-job", "run")
        assert "stage run" not in " ".join(command.argv)


def test_afterok_planning_omits_reused_upstreams_from_afterok_dependencies() -> None:
    plan = _execution_plan(
        {"cached": (), "run": ("cached",)},
        actions={"cached": PlanAction.SKIP, "run": PlanAction.RUN},
    )

    submission = build_afterok_planned_submission(
        run_uri="file:///runs/run-1",
        execution_plan=plan,
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(),
    )

    jobs = cast(tuple[SlurmPlannedJob, ...], submission.jobs)
    assert [job.logical_key for job in jobs] == ["stage:run"]
    assert submission.dependencies == ()


def test_afterok_planning_applies_stage_slurm_options_to_each_job() -> None:
    plan = _execution_plan({"build": (), "report": ("build",)})

    submission = build_afterok_planned_submission(
        run_uri="file:///runs/run-1",
        execution_plan=plan,
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(partition="shared", launcher_argv=("loom",)),
        stage_options={
            "report": SlurmOptions(
                partition="report",
                time="00:30:00",
                launcher_argv=("uv", "run", "loom"),
            )
        },
    )

    jobs = {
        job.logical_key: job for job in cast(tuple[SlurmPlannedJob, ...], submission.jobs)
    }
    build_directives = {
        directive.name: directive.value
        for directive in cast(
            tuple[SlurmSbatchDirective, ...],
            jobs["stage:build"].sbatch_directives,
        )
    }
    report_directives = {
        directive.name: directive.value
        for directive in cast(
            tuple[SlurmSbatchDirective, ...],
            jobs["stage:report"].sbatch_directives,
        )
    }
    build_command = cast(SlurmCommandArgv, jobs["stage:build"].command)
    report_command = cast(SlurmCommandArgv, jobs["stage:report"].command)

    assert build_directives["partition"] == "shared"
    assert report_directives["partition"] == "report"
    assert report_directives["time"] == "00:30:00"
    assert build_command.launcher_argv == ("loom",)
    assert report_command.launcher_argv == ("uv", "run", "loom")


def test_afterok_planning_applies_stage_specific_container_options() -> None:
    plan = _execution_plan({"build": (), "report": ("build",)})

    submission = build_afterok_planned_submission(
        run_uri="file:///runs/run-1",
        execution_plan=plan,
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(),
        container_options={"image": {"reference": "shared.sif"}},
        stage_container_options={
            "report": {"image": {"reference": "report.sif"}},
        },
        stage_apptainer_options={
            "report": {"command": "singularity", "cleanenv": False},
        },
    )

    jobs = {
        job.logical_key: job for job in cast(tuple[SlurmPlannedJob, ...], submission.jobs)
    }
    build_command = cast(SlurmCommandArgv, jobs["stage:build"].command)
    report_command = cast(SlurmCommandArgv, jobs["stage:report"].command)

    assert build_command.argv[:3] == ("apptainer", "exec", "--cleanenv")
    assert "shared.sif" in build_command.argv
    assert report_command.argv[:2] == ("singularity", "exec")
    assert "--cleanenv" not in report_command.argv
    assert "report.sif" in report_command.argv
    assert report_command.argv[-9:] == (
        "loom",
        "stage-job",
        "run",
        "--run-uri",
        "file:///runs/run-1",
        "--stage",
        "report",
        "--executor",
        "local",
    )


def _execution_plan(
    stage_upstreams: dict[str, tuple[str, ...]],
    *,
    actions: dict[str, PlanAction] | None = None,
) -> ExecutionPlan:
    selected_actions = actions or {}
    stage_order = tuple(stage_upstreams)
    stage_plans = tuple(
        _stage_plan(
            name=stage_name,
            upstream=upstream,
            action=selected_actions.get(stage_name, PlanAction.RUN),
        )
        for stage_name, upstream in stage_upstreams.items()
    )
    return ExecutionPlan(
        schema_version=1,
        run_uri="file:///runs/run-1",
        pipeline_name="demo",
        selectors=PlanSelectors(),
        resume=ResumeOptions(),
        fingerprint_context=FingerprintContext(
            python_version="3.12.0",
            loom_version="0.1.0",
        ),
        stage_order=stage_order,
        stage_plans=stage_plans,
        reasons=(),
        summary={
            "RUN": sum(1 for plan in stage_plans if plan.action == PlanAction.RUN),
            "REUSE": sum(1 for plan in stage_plans if plan.action == PlanAction.REUSE),
            "SKIP": sum(1 for plan in stage_plans if plan.action == PlanAction.SKIP),
            "STALE": 0,
            "BLOCKED": 0,
        },
    )


def _stage_plan(
    *,
    name: str,
    upstream: tuple[str, ...],
    action: PlanAction,
) -> StagePlan:
    return StagePlan(
        stage_name=name,
        action=action,
        base_action=action,
        fingerprint_status=FingerprintStatus.PENDING_INPUTS,
        fingerprint=None,
        resume_check=None,
        reasons=(),
        bound_inputs={},
        pending_inputs=(),
        reusable_outputs={},
        declared_outputs={},
        upstream_stages=upstream,
        downstream_stages=(),
        selected_by=(),
        invalidated_by=(),
    )
