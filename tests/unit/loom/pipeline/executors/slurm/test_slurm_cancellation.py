"""Unit coverage for submitted SLURM job cancellation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

import loom.pipeline.executors.slurm.authority as slurm_authority
from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmCancellationAttempt,
    SlurmCommandResult,
    read_slurm_live_manifest,
)
from loom.pipeline.executors.slurm.cancellation import (
    SlurmCancellationError,
    cancel_slurm_jobs,
)
from loom.pipeline.status import StageStatus, StageStatusRecord
from loom.pipeline.stores import (
    AuthorityServiceHealth,
    AuthorityServiceHealthState,
    LocalRunStore,
)
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.submitted import SubmittedOperationState
from tests.support.slurm_status_fixtures import write_submitted_slurm_fixture

pytestmark = pytest.mark.unit


class _ProbeRequiredAuthority(SQLitePerRunAuthorityStore):
    requires_live_endpoint_readiness = True


def test_cancel_slurm_jobs_requires_authority_backed_store(tmp_path: Path) -> None:
    with pytest.raises(SlurmCancellationError) as exc_info:
        cancel_slurm_jobs(
            "file:///tmp/run",
            run_store=LocalRunStore(tmp_path / "runs"),
            command_runner=FakeSlurmCommandRunner(),
        )

    assert exc_info.value.code == "executor.slurm.cancel.missing_authority"


def test_cancel_slurm_jobs_rejects_unreachable_http_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        authority_store=_ProbeRequiredAuthority(),
    )
    runner = FakeSlurmCommandRunner()

    monkeypatch.setattr(
        slurm_authority,
        "probe_http_authority_readiness",
        lambda endpoint: AuthorityServiceHealth(
            state=AuthorityServiceHealthState.UNAVAILABLE,
            message=f"{endpoint} unreachable",
        ),
    )

    with pytest.raises(SlurmCancellationError) as exc_info:
        cancel_slurm_jobs(
            run_uri,
            run_store=store,
            command_runner=runner,
        )

    assert exc_info.value.code == "executor.slurm.cancel.missing_authority"
    assert runner.calls == []


def test_cancel_slurm_jobs_marks_run_and_submitted_stages_cancelled(
    tmp_path: Path,
) -> None:
    store, run_uri, manifest_path = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": (), "train": ("extract",)},
        starting_job_id=700,
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
    assert registry is not None
    slurm_cancellation = cast(
        dict[str, object], registry.backend_metadata["slurm_cancellation"]
    )
    authority = cast(dict[str, object], registry.backend_metadata["authority"])

    assert result.status == "CANCELLED"
    assert result.ok is True
    assert result.cancelled_count == 2
    assert [attempt.outcome for attempt in attempts] == ["cancelled", "cancelled"]
    assert _run_status(store, run_uri) == "CANCELLED"
    assert _stage_status(store, run_uri, "extract") is StageStatus.CANCELLED
    assert _stage_status(store, run_uri, "train") is StageStatus.CANCELLED
    assert authority["mutation_source"] == "authority_service"
    assert slurm_cancellation["mutation_source"] == "authority_service"
    assert registry.state is SubmittedOperationState.CANCELLED
    assert registry.active is False


def test_cancel_slurm_jobs_records_partial_failure_without_full_run_cancel(
    tmp_path: Path,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": (), "train": ("extract",)},
        starting_job_id=800,
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "scancel": (
                SlurmCommandResult(
                    command="scancel",
                    argv=("scancel", "800"),
                    returncode=0,
                ),
                SlurmCommandResult(
                    command="scancel",
                    argv=("scancel", "801"),
                    returncode=1,
                    stderr="job already finished",
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
    assert result.ok is False
    assert result.cancelled_count == 1
    assert result.failed_count == 1
    assert _run_status(store, run_uri) == "SUBMITTED"
    assert _stage_status(store, run_uri, "extract") is StageStatus.CANCELLED
    assert _stage_status(store, run_uri, "train") is StageStatus.SUBMITTED
    assert registry is not None
    assert registry.state is SubmittedOperationState.PARTIAL
    assert registry.active is True


def test_cancel_slurm_jobs_missing_scancel_records_unknown_without_mutation(
    tmp_path: Path,
) -> None:
    store, run_uri, manifest_path = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=900,
    )
    runner = FakeSlurmCommandRunner(unavailable_commands=("scancel",))

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

    assert result.status == "UNKNOWN"
    assert result.ok is False
    assert result.failed_count == 1
    assert attempts[0].outcome == "failed"
    assert _attempt_command_record(attempts[0]).returncode == 127
    assert _run_status(store, run_uri) == "SUBMITTED"
    assert _stage_status(store, run_uri, "extract") is StageStatus.SUBMITTED
    assert registry is not None
    assert registry.state is SubmittedOperationState.UNKNOWN
    assert registry.active is True


def test_cancel_slurm_jobs_skips_final_stage_without_overwrite(
    tmp_path: Path,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=1000,
    )
    store.write_stage_status(
        run_uri,
        "extract",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="extract",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2026-05-08T00:00:09Z",
        ),
    )
    runner = FakeSlurmCommandRunner()

    result = cancel_slurm_jobs(
        run_uri,
        run_store=store,
        command_runner=runner,
        cancelled_at="2026-05-08T00:00:10Z",
    )
    registry = store.latest_submitted_operation(run_uri)

    assert result.status == "COMPLETED"
    assert result.ok is True
    assert result.skipped_count == 1
    assert result.job_results[0].outcome == "skipped_terminal"
    assert _stage_status(store, run_uri, "extract") is StageStatus.SUCCEEDED
    assert runner.calls == []
    assert registry is not None
    assert registry.state is SubmittedOperationState.COMPLETED


def test_cancel_slurm_jobs_does_not_mark_run_cancelled_over_failed_stage(
    tmp_path: Path,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": (), "train": ("extract",)},
        starting_job_id=1100,
    )
    store.write_stage_status(
        run_uri,
        "train",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="train",
            status=StageStatus.FAILED,
            attempt=1,
            updated_at="2026-05-08T00:00:09Z",
        ),
    )
    runner = FakeSlurmCommandRunner()

    result = cancel_slurm_jobs(
        run_uri,
        run_store=store,
        command_runner=runner,
        cancelled_at="2026-05-08T00:00:10Z",
    )

    assert result.status == "CANCELLED"
    assert _run_status(store, run_uri) == "SUBMITTED"
    assert _stage_status(store, run_uri, "extract") is StageStatus.CANCELLED
    assert _stage_status(store, run_uri, "train") is StageStatus.FAILED
    assert runner.calls == [("scancel", ("scancel", "1100"))]


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


def _attempt_command_record(
    attempt: SlurmCancellationAttempt,
) -> SlurmCommandResult:
    command_record = attempt.command_record
    assert isinstance(command_record, SlurmCommandResult)
    return command_record
