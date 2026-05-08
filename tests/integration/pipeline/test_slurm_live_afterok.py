"""Integration tests for live afterok SLURM submission persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from loom.pipeline.execution import StageJobRunRequest, run_stage_job
from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
    SlurmLiveSubmissionStatus,
    plan_afterok_slurm_dry_run,
    read_slurm_live_manifest,
    submit_afterok_slurm,
)
from loom.pipeline.runtime import RunOptions, build_runtime_metadata
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationState
from loom.serialization import json_dumps_pretty
from tests.integration.pipeline.test_slurm_dry_run_planning import _prepared_store


def test_live_afterok_submission_updates_manifest_registry_and_stage_statuses(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        {
            "extract": (),
            "features": ("extract",),
            "train": ("extract",),
            "report": ("features", "train"),
        },
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="planning-live-afterok",
        created_at="2026-05-08T00:00:00Z",
    )
    runner = FakeSlurmCommandRunner(starting_job_id=700)

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
    status = store.read_run_status(run_uri)

    assert result.status == "SUBMITTED"
    assert [job["scheduler_job_id"] for job in result.submitted_jobs] == [
        "700",
        "701",
        "702",
        "703",
    ]
    assert result.submitted_jobs[1]["dependency_job_ids"] == ["700"]
    assert result.submitted_jobs[2]["dependency_job_ids"] == ["700"]
    assert result.submitted_jobs[3]["dependency_job_ids"] == ["701", "702"]
    assert "--dependency=afterok:701:702" in runner.calls[3][1]
    assert manifest.submission_status is SlurmLiveSubmissionStatus.SUBMITTED
    assert manifest.summary_counts["active"] == 4
    assert registry is not None
    assert registry.state is SubmittedOperationState.SUBMITTED
    assert registry.manifest_relative_path == planning.manifest_artifact.relative_path
    assert status is not None
    assert status.status is RunStatus.SUBMITTED
    for stage_name in ("extract", "features", "train", "report"):
        stage_status = store.read_stage_status(run_uri, stage_name)
        assert stage_status is not None
        assert stage_status.status is StageStatus.SUBMITTED


def test_live_afterok_partial_failure_persists_accepted_and_failed_facts(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(
        tmp_path,
        {
            "extract": (),
            "features": ("extract",),
            "report": ("features",),
        },
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="planning-partial-afterok",
        created_at="2026-05-08T00:00:00Z",
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sbatch": (
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "extract.sh"),
                    returncode=0,
                    stdout="810\n",
                ),
                SlurmCommandResult(
                    command="sbatch",
                    argv=("sbatch", "--parsable", "features.sh"),
                    returncode=1,
                    stderr="qos rejected",
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
    assert result.submitted_jobs[0]["scheduler_job_id"] == "810"
    assert result.failed_submissions[0]["logical_key"] == "stage:features"
    assert result.failed_submissions[0]["reason"] == "qos rejected"
    assert result.failed_submissions[0]["dependency_job_ids"] == ["810"]
    assert manifest.submission_status is SlurmLiveSubmissionStatus.PARTIAL
    assert registry is not None
    assert registry.state is SubmittedOperationState.PARTIAL
    assert store.read_stage_status(run_uri, "extract") is not None
    assert store.read_stage_status(run_uri, "features") is None
    assert store.read_stage_status(run_uri, "report") is None


def test_live_afterok_submitted_stage_job_materializes_worker_request_at_start(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_store(tmp_path, {"extract": ()})
    config = _single_stage_config()
    serialized = json_dumps_pretty(config)
    store.write_config_snapshot(run_uri, "resolved", serialized)
    store.write_config_snapshot(run_uri, "resolved_redacted", serialized)
    store.write_runtime_metadata(
        run_uri,
        build_runtime_metadata(
            RunOptions(run_uri=run_uri, executor="slurm-afterok"),
            stage_ids=("extract",),
        ).to_dict(),
    )
    planning = plan_afterok_slurm_dry_run(
        run_store=store,
        run_uri=run_uri,
        planning_id="planning-startable-afterok",
        created_at="2026-05-08T00:00:00Z",
    )
    submit_afterok_slurm(
        run_store=store,
        run_uri=run_uri,
        planning_result=planning,
        command_runner=FakeSlurmCommandRunner(starting_job_id=910),
        submitted_at="2026-05-08T00:00:03Z",
    )

    assert store.read_stage_worker_request(run_uri, "extract", attempt=1) is None

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(
            run_uri=run_uri,
            stage_name="extract",
            executor="local",
        ),
    )

    worker_request = store.read_stage_worker_request(run_uri, "extract", attempt=1)
    assert result.status is StageStatus.SUCCEEDED
    assert worker_request is not None
    metadata = cast(Mapping[str, object], worker_request["metadata"])
    submitted = cast(Mapping[str, object], metadata["submitted_operation"])
    assert submitted["backend"] == "slurm"


def _single_stage_config() -> dict[str, object]:
    return {
        "pipeline": {
            "name": "afterok-startable",
            "stages": [
                {
                    "name": "extract",
                    "factory": {
                        "_target_": (
                            "tests.support.pipeline_execution_stages.JsonProducerStage"
                        )
                    },
                    "outputs": {
                        "data": {
                            "artifact_type": "json",
                            "codec_key": "json.v1",
                        }
                    },
                }
            ],
        }
    }
