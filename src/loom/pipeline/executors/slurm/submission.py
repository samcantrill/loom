"""Live SLURM submission services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from loom.pipeline.execution.lifecycle import write_run_submitted
from loom.pipeline.stores.run_store import LocalRunStorePaths, RunStore
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

from .artifacts import SlurmDryRunPlanningResult
from .commands import (
    SlurmCommandResult,
    SlurmCommandRunner,
    SubprocessSlurmCommandRunner,
    command_result_from_exception,
    parse_sbatch_parsable_output,
)
from .errors import (
    SlurmActiveSubmissionError,
    SlurmCommandUnavailableError,
    SlurmJobIdParseError,
    SlurmManifestUpdateError,
    SlurmPlanningError,
    SlurmSubmissionError,
)
from .live import (
    SlurmFailedSubmission,
    SlurmLiveSubmissionManifest,
    SlurmLiveSubmissionStatus,
    SlurmSubmittedJob,
    live_manifest_from_planned_submission,
    write_slurm_live_manifest,
)
from .manifest import SlurmMode, SlurmPlannedJob

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
    log_paths: Sequence[Mapping[str, PlainData]]
    job_count: int
    submitted_job_count: int
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
            "log_paths": [dict(log_path) for log_path in self.log_paths],
            "job_count": self.job_count,
            "submitted_job_count": self.submitted_job_count,
        }


def default_slurm_command_runner() -> SlurmCommandRunner:
    """Return the default live SLURM command runner."""

    return SubprocessSlurmCommandRunner()


def submit_single_job_slurm(
    *,
    run_store: RunStore,
    run_uri: str,
    planning_result: SlurmDryRunPlanningResult,
    command_runner: SlurmCommandRunner | None = None,
    submitted_at: str | None = None,
) -> SlurmLiveSubmissionResult:
    """Submit a v6 single-job SLURM script and persist live submission facts."""

    if not isinstance(run_store, RunStore):
        raise SlurmPlanningError("submit_single_job_slurm requires RunStore")
    if not isinstance(run_store, LocalRunStorePaths):
        raise SlurmPlanningError(
            "submit_single_job_slurm requires local run-store path helpers"
        )
    if not isinstance(planning_result, SlurmDryRunPlanningResult):
        raise SlurmPlanningError("planning_result must be SlurmDryRunPlanningResult")
    submission = planning_result.submission
    if submission.mode != SlurmMode.SINGLE_JOB:
        raise SlurmPlanningError("submit_single_job_slurm requires slurm-single-job")

    _raise_if_active_submission(run_store=run_store, run_uri=run_uri)
    runner = command_runner or default_slurm_command_runner()
    now = submitted_at or utc_timestamp()
    manifest_path = planning_result.manifest_artifact.local_path
    draft = live_manifest_from_planned_submission(
        submission,
        status=SlurmLiveSubmissionStatus.SUBMITTING,
        updated_at=now,
    )
    _write_manifest_and_registry(
        run_store=run_store,
        run_uri=run_uri,
        manifest_path=manifest_path,
        manifest=draft,
        state=SubmittedOperationState.SUBMITTING,
    )

    jobs = cast(tuple[SlurmPlannedJob, ...], submission.jobs)
    if len(jobs) != 1:
        failed = replace(
            draft,
            submission_status=SlurmLiveSubmissionStatus.FAILED,
            updated_at=utc_timestamp(),
            failed_submissions=(
                SlurmFailedSubmission(
                    logical_key="pipeline",
                    failed_at=utc_timestamp(),
                    reason="single-job live submission expected exactly one planned job",
                ),
            ),
        )
        _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=failed,
            state=SubmittedOperationState.FAILED,
        )
        raise SlurmSubmissionError(
            "single-job live submission expected exactly one planned job",
            code="executor.slurm.live_single_job.invalid_job_count",
            context={"job_count": len(jobs)},
        )
    job = jobs[0]
    script = planning_result.script_artifacts.get(job.logical_key)
    if script is None:
        failed = _failed_manifest(
            draft,
            logical_key=job.logical_key,
            reason="planned job has no generated script artifact",
            command_record=None,
        )
        _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=failed,
            state=SubmittedOperationState.FAILED,
        )
        raise SlurmSubmissionError(
            "planned job has no generated script artifact",
            code="executor.slurm.live_single_job.missing_script",
            context={"logical_key": job.logical_key},
        )

    try:
        command_result = runner.sbatch(script.local_path)
    except SlurmCommandUnavailableError as exc:
        command_result = command_result_from_exception(
            command="sbatch",
            argv=("sbatch", "--parsable", str(script.local_path)),
            exc=exc,
        )
        failed = _failed_manifest(
            draft,
            logical_key=job.logical_key,
            reason=str(exc) or type(exc).__name__,
            command_record=command_result,
        )
        _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=failed,
            state=SubmittedOperationState.FAILED,
        )
        raise
    except Exception as exc:
        command_result = command_result_from_exception(
            command="sbatch",
            argv=("sbatch", "--parsable", str(script.local_path)),
            exc=exc,
        )
        failed = _failed_manifest(
            draft,
            logical_key=job.logical_key,
            reason=str(exc) or type(exc).__name__,
            command_record=command_result,
        )
        _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=failed,
            state=SubmittedOperationState.FAILED,
        )
        raise SlurmSubmissionError(
            "sbatch command failed before returning a result",
            code="executor.slurm.sbatch.exception",
            context={"error_type": type(exc).__name__},
        ) from exc
    if not command_result.ok:
        failed = _failed_manifest(
            draft,
            logical_key=job.logical_key,
            reason=command_result.stderr or "sbatch returned a nonzero exit code",
            command_record=command_result,
        )
        _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=failed,
            state=SubmittedOperationState.FAILED,
        )
        raise SlurmSubmissionError(
            "sbatch returned a nonzero exit code",
            code="executor.slurm.sbatch.nonzero_exit",
            context={"returncode": command_result.returncode},
        )
    try:
        parsed = parse_sbatch_parsable_output(command_result.stdout)
    except SlurmJobIdParseError as exc:
        failed = _failed_manifest(
            draft,
            logical_key=job.logical_key,
            reason=str(exc),
            command_record=command_result,
        )
        _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=failed,
            state=SubmittedOperationState.FAILED,
        )
        raise SlurmSubmissionError(
            "sbatch output did not contain a parseable scheduler job ID",
            code="executor.slurm.sbatch.unparseable_job_id",
            context={"stdout": command_result.stdout},
        ) from exc

    submitted_job = SlurmSubmittedJob(
        logical_key=job.logical_key,
        scheduler_job_id=parsed.job_id,
        scheduler_cluster=parsed.cluster,
        raw_job_id_output=parsed.raw_output,
        submitted_at=now,
        command_record=command_result,
        script_relative_path=job.script_relative_path,
        stdout_relative_path=job.stdout_relative_path,
        stderr_relative_path=job.stderr_relative_path,
    )
    submitted = replace(
        draft,
        submission_status=SlurmLiveSubmissionStatus.SUBMITTED,
        updated_at=now,
        submitted_at=now,
        submitted_jobs=(submitted_job,),
    )
    _write_manifest_and_registry(
        run_store=run_store,
        run_uri=run_uri,
        manifest_path=manifest_path,
        manifest=submitted,
        state=SubmittedOperationState.SUBMITTED,
    )
    _write_run_submitted(run_store=run_store, run_uri=run_uri, manifest=submitted)
    return SlurmLiveSubmissionResult(
        run_uri=run_uri,
        mode=SlurmMode.SINGLE_JOB.value,
        submission_id=submitted.submission_id,
        status=SlurmLiveSubmissionStatus.SUBMITTED.value,
        manifest_path=str(manifest_path),
        manifest_relative_path=submitted.manifest_relative_path,
        plan_path=str(planning_result.plan_artifact.local_path),
        plan_relative_path=submitted.plan_relative_path,
        submitted_jobs=(
            {
                "logical_key": submitted_job.logical_key,
                "scheduler_job_id": submitted_job.scheduler_job_id,
                "scheduler_cluster": submitted_job.scheduler_cluster,
                "script_relative_path": submitted_job.script_relative_path,
                "stdout_relative_path": submitted_job.stdout_relative_path,
                "stderr_relative_path": submitted_job.stderr_relative_path,
            },
        ),
        log_paths=(
            {
                "logical_key": submitted_job.logical_key,
                "stdout_relative_path": submitted_job.stdout_relative_path,
                "stderr_relative_path": submitted_job.stderr_relative_path,
            },
        ),
        job_count=len(jobs),
        submitted_job_count=1,
    )


def _raise_if_active_submission(*, run_store: RunStore, run_uri: str) -> None:
    active = run_store.latest_active_submitted_operation(run_uri)
    if active is None:
        return
    raise SlurmActiveSubmissionError(
        "run already has active submitted scheduler work; cancel it before resubmitting"
    )


def _write_manifest_and_registry(
    *,
    run_store: RunStore,
    run_uri: str,
    manifest_path: Path,
    manifest: SlurmLiveSubmissionManifest,
    state: SubmittedOperationState,
) -> None:
    try:
        write_slurm_live_manifest(manifest_path, manifest)
    except SlurmManifestUpdateError:
        raise
    except Exception as exc:
        raise SlurmManifestUpdateError(
            f"failed to write live SLURM manifest at {manifest_path}: {exc}"
        ) from exc
    run_store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id=manifest.submission_id,
            backend=SLURM_SUBMITTED_BACKEND,
            mode=cast(SlurmMode, manifest.mode).value,
            created_at=manifest.created_at,
            updated_at=manifest.updated_at,
            state=state,
            manifest_relative_path=manifest.manifest_relative_path,
            summary_counts=manifest.summary_counts,
            backend_metadata={
                "live_schema_version": manifest.schema_version,
                "manifest_kind": "loom.slurm_live_manifest",
            },
        ),
    )


def _failed_manifest(
    manifest: SlurmLiveSubmissionManifest,
    *,
    logical_key: str,
    reason: str,
    command_record: SlurmCommandResult | None,
) -> SlurmLiveSubmissionManifest:
    failed_at = utc_timestamp()
    return replace(
        manifest,
        submission_status=SlurmLiveSubmissionStatus.FAILED,
        updated_at=failed_at,
        failed_submissions=(
            *manifest.failed_submissions,
            SlurmFailedSubmission(
                logical_key=logical_key,
                failed_at=failed_at,
                reason=reason,
                command_record=command_record,
            ),
        ),
    )


def _write_run_submitted(
    *,
    run_store: RunStore,
    run_uri: str,
    manifest: SlurmLiveSubmissionManifest,
) -> None:
    submitted_jobs = cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
    write_run_submitted(
        run_store,
        run_uri=run_uri,
        created_at=manifest.created_at,
        submitted_at=manifest.updated_at,
        message="SLURM single-job submission accepted by scheduler",
        metadata={
            "submitted_operation": {
                "backend": SLURM_SUBMITTED_BACKEND,
                "mode": cast(SlurmMode, manifest.mode).value,
                "submission_id": manifest.submission_id,
                "manifest_relative_path": manifest.manifest_relative_path,
            },
            "slurm": {
                "job_ids": [job.scheduler_job_id for job in submitted_jobs],
            },
        },
    )


__all__ = [
    "SLURM_SUBMITTED_BACKEND",
    "SlurmLiveSubmissionResult",
    "default_slurm_command_runner",
    "submit_single_job_slurm",
]
