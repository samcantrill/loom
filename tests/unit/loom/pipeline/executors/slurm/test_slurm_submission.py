"""Unit coverage for live single-job SLURM submission persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmActiveSubmissionError,
    SlurmCommandUnavailableError,
    SlurmDryRunPlanningResult,
    SlurmFailedSubmission,
    SlurmGeneratedArtifactPath,
    SlurmLiveSubmissionStatus,
    SlurmOptions,
    build_single_job_planned_submission,
    read_slurm_live_manifest,
    submit_single_job_slurm,
)
from loom.pipeline.status import RunStatus
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
