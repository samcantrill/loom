"""Unit coverage for live single-job SLURM submission persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmActiveSubmissionError,
    SlurmCommandResult,
    SlurmCommandUnavailableError,
    SlurmDryRunPlanningResult,
    SlurmFailedSubmission,
    SlurmGeneratedArtifactPath,
    SlurmLiveSubmissionStatus,
    SlurmOptions,
    SlurmPlannedJob,
    SlurmSubmissionError,
    build_afterok_planned_submission,
    build_single_job_planned_submission,
    read_slurm_live_manifest,
    submit_afterok_slurm,
    submit_single_job_slurm,
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
from loom.pipeline.status import RunStatus
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState

pytestmark = pytest.mark.unit


def test_submit_single_job_slurm_persists_scheduler_identity(
    tmp_path: Path,
) -> None:
    store, run_uri, planning = _planning_result(tmp_path)
    runner = FakeSlurmCommandRunner(starting_job_id=1234)

    result = submit_single_job_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=runner,
        submitted_at="2026-05-08T00:00:03Z",
    )

    manifest = read_slurm_live_manifest(
        json.loads(planning.manifest_artifact.local_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)
    status = store.read_run_status(run_uri)

    assert result.status == "SUBMITTED"
    assert result.submitted_jobs[0]["scheduler_job_id"] == "1234"
    assert runner.calls[0][0] == "sbatch"
    assert manifest.submission_status is SlurmLiveSubmissionStatus.SUBMITTED
    assert manifest.summary_counts["active"] == 1
    assert registry is not None
    assert registry.state is SubmittedOperationState.SUBMITTED
    assert registry.active is True
    assert status is not None
    assert status.status is RunStatus.SUBMITTED
    assert status.metadata["slurm"] == {"job_ids": ["1234"]}


def test_submit_single_job_slurm_marks_unavailable_sbatch_failed(
    tmp_path: Path,
) -> None:
    store, run_uri, planning = _planning_result(tmp_path)
    runner = FakeSlurmCommandRunner(unavailable_commands=("sbatch",))

    with pytest.raises(SlurmCommandUnavailableError):
        submit_single_job_slurm(
            run_store=store,
            run_uri=run_uri,
            planning_result=planning,
            command_runner=runner,
            submitted_at="2026-05-08T00:00:03Z",
        )

    manifest = read_slurm_live_manifest(
        json.loads(planning.manifest_artifact.local_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)

    assert manifest.submission_status is SlurmLiveSubmissionStatus.FAILED
    failed = cast(SlurmFailedSubmission, manifest.failed_submissions[0])
    assert failed.logical_key == "pipeline"
    assert registry is not None
    assert registry.state is SubmittedOperationState.FAILED
    assert registry.active is False
    assert store.read_run_status(run_uri) is None


def test_submit_single_job_slurm_rejects_existing_active_submission(
    tmp_path: Path,
) -> None:
    store, run_uri, planning = _planning_result(tmp_path)
    store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="existing",
            backend="slurm",
            mode="slurm-single-job",
            created_at="2026-05-08T00:00:00Z",
            updated_at="2026-05-08T00:00:01Z",
            state=SubmittedOperationState.SUBMITTED,
            manifest_relative_path="slurm/submissions/existing/manifest.json",
            summary_counts={"submitted": 1, "active": 1},
        ),
    )

    with pytest.raises(SlurmActiveSubmissionError):
        submit_single_job_slurm(
            run_store=store,
            run_uri=run_uri,
            planning_result=planning,
            command_runner=FakeSlurmCommandRunner(),
        )


def test_submit_afterok_slurm_submits_in_order_with_scheduler_dependencies(
    tmp_path: Path,
) -> None:
    store, run_uri, planning = _afterok_planning_result(
        tmp_path,
        {
            "extract": (),
            "train": ("extract",),
            "report": ("train",),
        },
    )
    runner = FakeSlurmCommandRunner(starting_job_id=2000)

    result = submit_afterok_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=runner,
        submitted_at="2026-05-08T00:00:03Z",
    )

    manifest = read_slurm_live_manifest(
        json.loads(planning.manifest_artifact.local_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)
    run_status = store.read_run_status(run_uri)

    assert result.status == "SUBMITTED"
    assert result.job_count == 3
    assert result.submitted_job_count == 3
    assert [job["logical_key"] for job in result.submitted_jobs] == [
        "stage:extract",
        "stage:train",
        "stage:report",
    ]
    assert [job["scheduler_job_id"] for job in result.submitted_jobs] == [
        "2000",
        "2001",
        "2002",
    ]
    assert result.submitted_jobs[1]["dependency_job_ids"] == ["2000"]
    assert result.submitted_jobs[2]["dependency_job_ids"] == ["2001"]
    assert runner.calls[0][1][0:2] == ("sbatch", "--parsable")
    assert "--dependency=afterok:2000" in runner.calls[1][1]
    assert "--dependency=afterok:2001" in runner.calls[2][1]
    assert manifest.submission_status is SlurmLiveSubmissionStatus.SUBMITTED
    assert manifest.summary_counts["submitted"] == 3
    assert registry is not None
    assert registry.state is SubmittedOperationState.SUBMITTED
    assert run_status is not None
    assert run_status.status is RunStatus.SUBMITTED
    for stage_name in ("extract", "train", "report"):
        stage_status = store.read_stage_status(run_uri, stage_name)
        assert stage_status is not None
        assert stage_status.status is StageStatus.SUBMITTED
        submitted_metadata = cast(
            Mapping[str, object],
            stage_status.metadata["submitted_operation"],
        )
        assert submitted_metadata["submission_id"] == result.submission_id


def test_submit_afterok_slurm_partial_failure_preserves_accepted_jobs(
    tmp_path: Path,
) -> None:
    store, run_uri, planning = _afterok_planning_result(
        tmp_path,
        {
            "extract": (),
            "train": ("extract",),
            "report": ("train",),
        },
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": (
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "extract.sh"),
                    returncode=0,
                    stdout="3100\n",
                ),
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "train.sh"),
                    returncode=1,
                    stderr="partition unavailable",
                ),
            )
        }
    )

    result = submit_afterok_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=runner,
        submitted_at="2026-05-08T00:00:03Z",
    )

    manifest = read_slurm_live_manifest(
        json.loads(planning.manifest_artifact.local_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)

    assert result.status == "PARTIAL"
    assert result.submitted_job_count == 1
    assert result.failed_submission_count == 1
    assert result.submitted_jobs[0]["logical_key"] == "stage:extract"
    assert result.submitted_jobs[0]["scheduler_job_id"] == "3100"
    assert result.failed_submissions[0]["logical_key"] == "stage:train"
    assert result.failed_submissions[0]["dependency_job_ids"] == ["3100"]
    assert result.failed_submissions[0]["reason"] == "partition unavailable"
    assert manifest.submission_status is SlurmLiveSubmissionStatus.PARTIAL
    assert manifest.summary_counts["submitted"] == 1
    assert registry is not None
    assert registry.state is SubmittedOperationState.PARTIAL
    assert store.read_stage_status(run_uri, "extract") is not None
    assert store.read_stage_status(run_uri, "train") is None


def test_submit_afterok_slurm_rejects_first_job_failure(
    tmp_path: Path,
) -> None:
    store, run_uri, planning = _afterok_planning_result(tmp_path, {"extract": ()})
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": (
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "extract.sh"),
                    returncode=1,
                    stderr="invalid account",
                ),
            )
        }
    )

    with pytest.raises(SlurmSubmissionError):
        submit_afterok_slurm(
            run_store=store,
            run_uri=run_uri,
            planning_result=planning,
            command_runner=runner,
        )

    manifest = read_slurm_live_manifest(
        json.loads(planning.manifest_artifact.local_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)

    assert manifest.submission_status is SlurmLiveSubmissionStatus.FAILED
    assert registry is not None
    assert registry.state is SubmittedOperationState.FAILED
    assert store.read_run_status(run_uri) is None


def test_submit_afterok_slurm_rejects_existing_active_submission(
    tmp_path: Path,
) -> None:
    store, run_uri, planning = _afterok_planning_result(tmp_path, {"extract": ()})
    store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="existing",
            backend="slurm",
            mode="slurm-afterok",
            created_at="2026-05-08T00:00:00Z",
            updated_at="2026-05-08T00:00:01Z",
            state=SubmittedOperationState.SUBMITTED,
            manifest_relative_path="slurm/submissions/existing/manifest.json",
            summary_counts={"submitted": 1, "active": 1},
        ),
    )

    with pytest.raises(SlurmActiveSubmissionError):
        submit_afterok_slurm(
            run_store=store,
            run_uri=run_uri,
            planning_result=planning,
            command_runner=FakeSlurmCommandRunner(),
        )


def _planning_result(
    tmp_path: Path,
) -> tuple[LocalRunStore, str, SlurmDryRunPlanningResult]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "demo")
    store.create_run(run_uri)
    submission = build_single_job_planned_submission(
        run_uri=run_uri,
        planning_id="planning-1",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(),
    )
    manifest_artifact = SlurmGeneratedArtifactPath(
        relative_path="slurm/submissions/planning-1/manifest.json",
        local_path=store.local_generated_artifact_path(
            run_uri,
            "slurm/submissions/planning-1/manifest.json",
        ),
    )
    plan_artifact = SlurmGeneratedArtifactPath(
        relative_path="slurm/submissions/planning-1/plan.json",
        local_path=store.local_generated_artifact_path(
            run_uri,
            "slurm/submissions/planning-1/plan.json",
        ),
    )
    script_artifact = SlurmGeneratedArtifactPath(
        relative_path="slurm/submissions/planning-1/scripts/pipeline.sh",
        local_path=store.local_generated_artifact_path(
            run_uri,
            "slurm/submissions/planning-1/scripts/pipeline.sh",
        ),
    )
    script_artifact.local_path.parent.mkdir(parents=True, exist_ok=True)
    script_artifact.local_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    plan_artifact.local_path.parent.mkdir(parents=True, exist_ok=True)
    plan_artifact.local_path.write_text("{}", encoding="utf-8")
    manifest_artifact.local_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_artifact.local_path.write_text("{}", encoding="utf-8")
    return (
        store,
        run_uri,
        SlurmDryRunPlanningResult(
            submission=submission,
            manifest_artifact=manifest_artifact,
            plan_artifact=plan_artifact,
            script_artifacts={"pipeline": script_artifact},
        ),
    )


def _afterok_planning_result(
    tmp_path: Path,
    stage_upstreams: dict[str, tuple[str, ...]],
) -> tuple[LocalRunStore, str, SlurmDryRunPlanningResult]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "demo")
    store.create_run(run_uri)
    submission = build_afterok_planned_submission(
        run_uri=run_uri,
        execution_plan=_execution_plan(run_uri, stage_upstreams),
        planning_id="planning-afterok",
        created_at="2026-05-08T00:00:00Z",
        options=SlurmOptions(),
    )
    manifest_artifact = SlurmGeneratedArtifactPath(
        relative_path="slurm/submissions/planning-afterok/manifest.json",
        local_path=store.local_generated_artifact_path(
            run_uri,
            "slurm/submissions/planning-afterok/manifest.json",
        ),
    )
    plan_artifact = SlurmGeneratedArtifactPath(
        relative_path="slurm/submissions/planning-afterok/plan.json",
        local_path=store.local_generated_artifact_path(
            run_uri,
            "slurm/submissions/planning-afterok/plan.json",
        ),
    )
    script_artifacts: dict[str, SlurmGeneratedArtifactPath] = {}
    for job in cast(tuple[SlurmPlannedJob, ...], submission.jobs):
        script_relative_path = job.script_relative_path
        assert script_relative_path is not None
        script = SlurmGeneratedArtifactPath(
            relative_path=script_relative_path,
            local_path=store.local_generated_artifact_path(
                run_uri,
                script_relative_path,
            ),
        )
        script.local_path.parent.mkdir(parents=True, exist_ok=True)
        script.local_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        script_artifacts[job.logical_key] = script
    plan_artifact.local_path.parent.mkdir(parents=True, exist_ok=True)
    plan_artifact.local_path.write_text("{}", encoding="utf-8")
    manifest_artifact.local_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_artifact.local_path.write_text("{}", encoding="utf-8")
    return (
        store,
        run_uri,
        SlurmDryRunPlanningResult(
            submission=submission,
            manifest_artifact=manifest_artifact,
            plan_artifact=plan_artifact,
            script_artifacts=script_artifacts,
        ),
    )


def _execution_plan(
    run_uri: str,
    stage_upstreams: dict[str, tuple[str, ...]],
) -> ExecutionPlan:
    stage_plans = tuple(
        StagePlan(
            stage_name=stage_name,
            action=PlanAction.RUN,
            base_action=PlanAction.RUN,
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
        for stage_name, upstream in stage_upstreams.items()
    )
    return ExecutionPlan(
        schema_version=1,
        run_uri=run_uri,
        pipeline_name="demo",
        selectors=PlanSelectors(),
        resume=ResumeOptions(),
        fingerprint_context=FingerprintContext(
            python_version="3.12.0",
            loom_version="0.1.0",
        ),
        stage_order=tuple(stage_upstreams),
        stage_plans=stage_plans,
        reasons=(),
        summary={
            "RUN": len(stage_plans),
            "REUSE": 0,
            "SKIP": 0,
            "STALE": 0,
            "BLOCKED": 0,
        },
    )
