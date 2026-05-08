"""Integration coverage for submitted SLURM job cancellation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmCancellationAttempt,
    SlurmCommandResult,
    read_slurm_live_manifest,
)
from loom.pipeline.executors.slurm.cancellation import cancel_slurm_jobs
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.submitted import SubmittedOperationState
from tests.support.slurm_status_fixtures import write_submitted_slurm_fixture


def test_slurm_cancellation_success_persists_manifest_registry_and_statuses(
    tmp_path: Path,
) -> None:
    store, run_uri, manifest_path = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": (), "train": ("extract",), "report": ("train",)},
        starting_job_id=200,
    )
    runner = FakeSlurmCommandRunner()

    result = cancel_slurm_jobs(
        run_uri,
        run_store=store,
        command_runner=runner,
        cancelled_at="2026-05-08T00:00:10Z",
    )

    manifest = read_slurm_live_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    attempts = cast(tuple[SlurmCancellationAttempt, ...], manifest.cancellation_attempts)
    registry = store.latest_submitted_operation(run_uri)

    assert result.status == "CANCELLED"
    assert [call[1] for call in runner.calls] == [
        ("scancel", "200"),
        ("scancel", "201"),
        ("scancel", "202"),
    ]
    assert [attempt.scheduler_job_id for attempt in attempts] == ["200", "201", "202"]
    assert all(attempt.outcome == "cancelled" for attempt in attempts)
    assert _run_status(store, run_uri) == "CANCELLED"
    assert _stage_status(store, run_uri, "report") is StageStatus.CANCELLED
    assert registry is not None
    assert registry.state is SubmittedOperationState.CANCELLED


def test_slurm_cancellation_partial_failure_keeps_registry_active(
    tmp_path: Path,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": (), "train": ("extract",)},
        starting_job_id=300,
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "scancel": (
                SlurmCommandResult(
                    command="scancel",
                    argv=("scancel", "300"),
                    returncode=0,
                ),
                SlurmCommandResult(
                    command="scancel",
                    argv=("scancel", "301"),
                    returncode=1,
                    stderr="not authorized",
                ),
            )
        }
    )

    result = cancel_slurm_jobs(
        run_uri,
        run_store=store,
        command_runner=runner,
        cancelled_at="2026-05-08T00:00:10Z",
    )
    registry = store.latest_submitted_operation(run_uri)

    assert result.status == "PARTIAL"
    assert result.job_results[1].message == "not authorized"
    assert _stage_status(store, run_uri, "extract") is StageStatus.CANCELLED
    assert _stage_status(store, run_uri, "train") is StageStatus.SUBMITTED
    assert registry is not None
    assert registry.state is SubmittedOperationState.PARTIAL
    assert registry.active is True


def _run_status(store: LocalRunStore, run_uri: str) -> str:
    record = store.read_run_status(run_uri)
    assert record is not None
    return record.status.value


def _stage_status(
    store: LocalRunStore,
    run_uri: str,
    stage_name: str,
) -> StageStatus:
    record = store.read_stage_status(run_uri, stage_name)
    assert record is not None
    return record.status
