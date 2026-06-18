"""Unit coverage for scheduler-aware SLURM status inspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

import loom.pipeline.executors.slurm.authority as slurm_authority
from loom.pipeline.executors.slurm import (
    FakeSlurmCommandRunner,
    SlurmCommandResult,
    SlurmSchedulerStatusSnapshot,
    read_slurm_live_manifest,
)
from loom.pipeline.executors.slurm.status import (
    SlurmStatusInspectionError,
    inspect_slurm_job_status,
)
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores import AuthorityServiceHealth, AuthorityServiceHealthState
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.serialization import PlainData
from tests.support.slurm_status_fixtures import write_submitted_slurm_fixture

pytestmark = pytest.mark.unit


class _ProbeRequiredAuthority(SQLitePerRunAuthorityStore):
    requires_live_endpoint_readiness = True


def test_slurm_status_requires_authority_backed_store(tmp_path: Path) -> None:
    with pytest.raises(SlurmStatusInspectionError) as exc_info:
        inspect_slurm_job_status(
            "file:///tmp/run",
            run_store=LocalRunStore(tmp_path / "runs"),
            command_runner=FakeSlurmCommandRunner(),
        )

    assert exc_info.value.code == "executor.slurm.status.missing_authority"


def test_slurm_status_rejects_unreachable_http_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        authority_store=_ProbeRequiredAuthority(),
    )

    monkeypatch.setattr(
        slurm_authority,
        "probe_http_authority_readiness",
        lambda endpoint: AuthorityServiceHealth(
            state=AuthorityServiceHealthState.UNAVAILABLE,
            message=f"{endpoint} unreachable",
        ),
    )

    with pytest.raises(SlurmStatusInspectionError) as exc_info:
        inspect_slurm_job_status(
            run_uri,
            run_store=store,
            command_runner=FakeSlurmCommandRunner(),
        )

    assert exc_info.value.code == "executor.slurm.status.missing_authority"


def test_slurm_status_prefers_sacct_final_and_persists_snapshots(
    tmp_path: Path,
) -> None:
    store, run_uri, manifest_path = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=700,
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": (
                SlurmCommandResult(
                    command="sacct",
                    argv=("sacct",),
                    returncode=0,
                    stdout="700|COMPLETED|0:0\n",
                ),
            ),
            "squeue": (
                SlurmCommandResult(command="squeue", argv=("squeue",), returncode=0),
            ),
        }
    )

    report = inspect_slurm_job_status(
        run_uri,
        run_store=store,
        command_runner=runner,
        captured_at="2026-05-08T00:00:10Z",
    )

    job = report.jobs[0]
    manifest = read_slurm_live_manifest(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    registry = store.latest_submitted_operation(run_uri)

    assert job.status == "SUCCEEDED"
    assert job.source == "sacct"
    assert job.scheduler_state == "COMPLETED"
    assert job.exit_code == "0:0"
    snapshots = cast(tuple[SlurmSchedulerStatusSnapshot, ...], manifest.status_snapshots)
    assert snapshots[-1].source == "sacct"
    assert snapshots[-1].state == "COMPLETED"
    assert registry is not None
    slurm_status = cast(
        dict[str, PlainData], registry.backend_metadata["slurm_status"]
    )
    authority = cast(dict[str, PlainData], registry.backend_metadata["authority"])
    jobs = cast(list[dict[str, PlainData]], slurm_status["jobs"])
    assert authority["mutation_source"] == "authority_service"
    assert slurm_status["mutation_source"] == "authority_service"
    assert jobs[0]["status"] == "SUCCEEDED"


def test_slurm_status_reports_dependency_blocked_worker_not_started(
    tmp_path: Path,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": (), "train": ("extract",)},
        starting_job_id=800,
    )
    runner = FakeSlurmCommandRunner(
        scripted_results={
            "sacct": (
                SlurmCommandResult(command="sacct", argv=("sacct",), returncode=0),
            ),
            "squeue": (
                SlurmCommandResult(
                    command="squeue",
                    argv=("squeue",),
                    returncode=0,
                    stdout="801|PENDING|DependencyNeverSatisfied\n",
                ),
            ),
        }
    )

    report = inspect_slurm_job_status(
        run_uri,
        run_store=store,
        command_runner=runner,
        captured_at="2026-05-08T00:00:10Z",
    )

    train = next(job for job in report.jobs if job.logical_key == "stage:train")

    assert train.status == "DEPENDENCY_BLOCKED"
    assert train.source == "squeue"
    assert train.dependency_state == "BLOCKED"
    assert train.dependency_job_ids == ("800",)
    assert [warning.code for warning in train.warnings] == [
        "executor.slurm.status.worker_never_started"
    ]


def test_slurm_status_falls_back_to_manifest_when_commands_are_missing(
    tmp_path: Path,
) -> None:
    store, run_uri, _ = write_submitted_slurm_fixture(
        tmp_path,
        {"extract": ()},
        starting_job_id=900,
    )
    runner = FakeSlurmCommandRunner(unavailable_commands=("sacct", "squeue"))

    report = inspect_slurm_job_status(
        run_uri,
        run_store=store,
        command_runner=runner,
        captured_at="2026-05-08T00:00:10Z",
    )

    assert report.jobs[0].status == "SUBMITTED"
    assert report.jobs[0].source == "manifest"
    assert {warning.code for warning in report.warnings} == {
        "executor.slurm.status.sacct_unavailable",
        "executor.slurm.status.squeue_unavailable",
        "executor.slurm.status.scheduler_state_uncertain",
    }
    assert {warning.code for warning in report.jobs[0].warnings} == {
        "executor.slurm.status.job_state_uncertain"
    }
