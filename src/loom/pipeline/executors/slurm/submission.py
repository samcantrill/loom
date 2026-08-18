"""Compatibility wrappers for execution-owned live SLURM submission."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loom.pipeline.executors.slurm.commands import (
    SlurmCommandRunner,
    SubprocessSlurmCommandRunner,
)
from loom.serialization import PlainData

if TYPE_CHECKING:
    from loom.pipeline.executors.slurm.artifacts import SlurmDryRunPlanningResult
    from loom.pipeline.stores.run_store import LegacyRunStore


SLURM_SUBMITTED_BACKEND = "slurm"


@dataclass(frozen=True, slots=True)
class SlurmLiveSubmissionResult:
    """Result of one live SLURM submission operation."""

    run_uri: str
    mode: str
    submission_id: str
    status: str
    manifest_path: str
    manifest_relative_path: str
    plan_path: str
    plan_relative_path: str
    submitted_jobs: Sequence[Mapping[str, PlainData]]
    failed_submissions: Sequence[Mapping[str, PlainData]]
    log_paths: Sequence[Mapping[str, PlainData]]
    job_count: int
    submitted_job_count: int
    failed_submission_count: int
    dry_run: bool = False

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "submission_id": self.submission_id,
            "status": self.status,
            "manifest_path": self.manifest_path,
            "manifest_relative_path": self.manifest_relative_path,
            "plan_path": self.plan_path,
            "plan_relative_path": self.plan_relative_path,
            "submitted_jobs": [dict(job) for job in self.submitted_jobs],
            "failed_submissions": [dict(item) for item in self.failed_submissions],
            "log_paths": [dict(log_path) for log_path in self.log_paths],
            "job_count": self.job_count,
            "submitted_job_count": self.submitted_job_count,
            "failed_submission_count": self.failed_submission_count,
        }


def default_slurm_command_runner() -> "SlurmCommandRunner":
    return SubprocessSlurmCommandRunner()


def submit_single_job_slurm(
    *,
    run_store: "LegacyRunStore",
    run_uri: str,
    planning_result: "SlurmDryRunPlanningResult",
    command_runner: "SlurmCommandRunner | None" = None,
    submitted_at: str | None = None,
) -> "SlurmLiveSubmissionResult":
    from loom.pipeline.execution.slurm_controller import (
        SlurmSubmissionServices,
        submit_single_job_slurm as _submit,
    )

    return _submit(
        services=SlurmSubmissionServices.from_legacy(run_store),
        run_uri=run_uri,
        planning_result=planning_result,
        command_runner=command_runner,
        submitted_at=submitted_at,
    )


def submit_afterok_slurm(
    *,
    run_store: "LegacyRunStore",
    run_uri: str,
    planning_result: "SlurmDryRunPlanningResult",
    command_runner: "SlurmCommandRunner | None" = None,
    submitted_at: str | None = None,
) -> "SlurmLiveSubmissionResult":
    from loom.pipeline.execution.slurm_controller import (
        SlurmSubmissionServices,
        submit_afterok_slurm as _submit,
    )

    return _submit(
        services=SlurmSubmissionServices.from_legacy(run_store),
        run_uri=run_uri,
        planning_result=planning_result,
        command_runner=command_runner,
        submitted_at=submitted_at,
    )


__all__ = [
    "SLURM_SUBMITTED_BACKEND",
    "SlurmLiveSubmissionResult",
    "default_slurm_command_runner",
    "submit_afterok_slurm",
    "submit_single_job_slurm",
]
