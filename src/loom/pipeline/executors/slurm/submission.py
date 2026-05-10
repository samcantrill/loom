"""Live SLURM submission services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from loom.pipeline.execution.lifecycle import write_run_submitted, write_stage_submitted
from loom.pipeline.stores.run_store import LegacyRunStore as RunStore, LocalRunStorePaths
from loom.pipeline.stores import AuthorityConfig
from loom.pipeline.submitted import (
    SubmittedOperationRecord,
    SubmittedOperationState,
    submitted_stage_metadata,
)
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
        failed_submissions=(),
        log_paths=(
            {
                "logical_key": submitted_job.logical_key,
                "stdout_relative_path": submitted_job.stdout_relative_path,
                "stderr_relative_path": submitted_job.stderr_relative_path,
            },
        ),
        job_count=len(jobs),
        submitted_job_count=1,
        failed_submission_count=0,
    )


def submit_afterok_slurm(
    *,
    run_store: RunStore,
    run_uri: str,
    planning_result: SlurmDryRunPlanningResult,
    command_runner: SlurmCommandRunner | None = None,
    submitted_at: str | None = None,
) -> SlurmLiveSubmissionResult:
    """Submit a v6 afterok SLURM DAG and persist accepted scheduler jobs."""

    if not isinstance(run_store, RunStore):
        raise SlurmPlanningError("submit_afterok_slurm requires RunStore")
    if not isinstance(run_store, LocalRunStorePaths):
        raise SlurmPlanningError(
            "submit_afterok_slurm requires local run-store path helpers"
        )
    if not isinstance(planning_result, SlurmDryRunPlanningResult):
        raise SlurmPlanningError("planning_result must be SlurmDryRunPlanningResult")
    submission = planning_result.submission
    if submission.mode != SlurmMode.AFTEROK:
        raise SlurmPlanningError("submit_afterok_slurm requires slurm-afterok")

    _raise_if_active_submission(run_store=run_store, run_uri=run_uri)
    runner = command_runner or default_slurm_command_runner()
    now = submitted_at or utc_timestamp()
    manifest_path = planning_result.manifest_artifact.local_path
    draft = live_manifest_from_planned_submission(
        submission,
        status=SlurmLiveSubmissionStatus.SUBMITTING,
        updated_at=now,
    )
    registry = _write_manifest_and_registry(
        run_store=run_store,
        run_uri=run_uri,
        manifest_path=manifest_path,
        manifest=draft,
        state=SubmittedOperationState.SUBMITTING,
    )

    jobs = cast(tuple[SlurmPlannedJob, ...], submission.jobs)
    submitted_jobs: list[SlurmSubmittedJob] = []
    scheduler_ids_by_key: dict[str, str] = {}
    current = draft
    for job in jobs:
        script = planning_result.script_artifacts.get(job.logical_key)
        if script is None:
            return _record_afterok_failure(
                run_store=run_store,
                run_uri=run_uri,
                manifest_path=manifest_path,
                manifest=current,
                planning_result=planning_result,
                logical_key=job.logical_key,
                reason="planned job has no generated script artifact",
                dependency_job_ids=_dependency_job_ids(job, scheduler_ids_by_key),
                command_record=None,
                submitted_jobs=submitted_jobs,
            )
        dependency_job_ids = _dependency_job_ids(job, scheduler_ids_by_key)
        missing_dependencies = tuple(
            key for key in job.dependency_job_keys if key not in scheduler_ids_by_key
        )
        if missing_dependencies:
            return _record_afterok_failure(
                run_store=run_store,
                run_uri=run_uri,
                manifest_path=manifest_path,
                manifest=current,
                planning_result=planning_result,
                logical_key=job.logical_key,
                reason="upstream scheduler job IDs are missing",
                dependency_job_ids=dependency_job_ids,
                command_record=None,
                submitted_jobs=submitted_jobs,
                context={"missing_dependency_job_keys": list(missing_dependencies)},
            )
        try:
            command_result = runner.sbatch(
                script.local_path,
                dependency_job_ids=dependency_job_ids,
            )
        except SlurmCommandUnavailableError as exc:
            command_result = command_result_from_exception(
                command="sbatch",
                argv=_sbatch_argv(script.local_path, dependency_job_ids),
                exc=exc,
            )
            if submitted_jobs:
                return _record_afterok_failure(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    logical_key=job.logical_key,
                    reason=str(exc) or type(exc).__name__,
                    dependency_job_ids=dependency_job_ids,
                    command_record=command_result,
                    submitted_jobs=submitted_jobs,
                )
            failed = _failed_manifest(
                current,
                logical_key=job.logical_key,
                reason=str(exc) or type(exc).__name__,
                command_record=command_result,
                dependency_job_ids=dependency_job_ids,
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
                argv=_sbatch_argv(script.local_path, dependency_job_ids),
                exc=exc,
            )
            if submitted_jobs:
                return _record_afterok_failure(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    logical_key=job.logical_key,
                    reason=str(exc) or type(exc).__name__,
                    dependency_job_ids=dependency_job_ids,
                    command_record=command_result,
                    submitted_jobs=submitted_jobs,
                )
            failed = _failed_manifest(
                current,
                logical_key=job.logical_key,
                reason=str(exc) or type(exc).__name__,
                command_record=command_result,
                dependency_job_ids=dependency_job_ids,
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
            if submitted_jobs:
                return _record_afterok_failure(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    logical_key=job.logical_key,
                    reason=command_result.stderr
                    or "sbatch returned a nonzero exit code",
                    dependency_job_ids=dependency_job_ids,
                    command_record=command_result,
                    submitted_jobs=submitted_jobs,
                )
            failed = _failed_manifest(
                current,
                logical_key=job.logical_key,
                reason=command_result.stderr or "sbatch returned a nonzero exit code",
                command_record=command_result,
                dependency_job_ids=dependency_job_ids,
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
            if submitted_jobs:
                return _record_afterok_failure(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    logical_key=job.logical_key,
                    reason=str(exc),
                    dependency_job_ids=dependency_job_ids,
                    command_record=command_result,
                    submitted_jobs=submitted_jobs,
                )
            failed = _failed_manifest(
                current,
                logical_key=job.logical_key,
                reason=str(exc),
                command_record=command_result,
                dependency_job_ids=dependency_job_ids,
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
            dependency_job_ids=dependency_job_ids,
            script_relative_path=job.script_relative_path,
            stdout_relative_path=job.stdout_relative_path,
            stderr_relative_path=job.stderr_relative_path,
        )
        submitted_jobs.append(submitted_job)
        scheduler_ids_by_key[job.logical_key] = parsed.job_id
        current = replace(
            current,
            updated_at=now,
            submitted_jobs=tuple(submitted_jobs),
        )
        registry = _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=current,
            state=SubmittedOperationState.SUBMITTING,
        )
        _write_submitted_stage(
            run_store=run_store,
            run_uri=run_uri,
            job=job,
            submitted_job=submitted_job,
            registry=registry,
            submitted_at=now,
        )

    submitted = replace(
        current,
        submission_status=SlurmLiveSubmissionStatus.SUBMITTED,
        updated_at=now,
        submitted_at=now,
        submitted_jobs=tuple(submitted_jobs),
    )
    _write_manifest_and_registry(
        run_store=run_store,
        run_uri=run_uri,
        manifest_path=manifest_path,
        manifest=submitted,
        state=SubmittedOperationState.SUBMITTED,
    )
    _write_run_submitted(
        run_store=run_store,
        run_uri=run_uri,
        manifest=submitted,
        message="SLURM afterok submission accepted by scheduler",
    )
    return _live_result(
        manifest=submitted,
        planning_result=planning_result,
        status=SlurmLiveSubmissionStatus.SUBMITTED,
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
) -> SubmittedOperationRecord:
    try:
        write_slurm_live_manifest(manifest_path, manifest)
    except SlurmManifestUpdateError:
        raise
    except Exception as exc:
        raise SlurmManifestUpdateError(
            f"failed to write live SLURM manifest at {manifest_path}: {exc}"
        ) from exc
    record = SubmittedOperationRecord(
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
            **_authority_backend_metadata(run_store),
        },
    )
    run_store.write_submitted_operation(run_uri, record)
    return record


def _failed_manifest(
    manifest: SlurmLiveSubmissionManifest,
    *,
    logical_key: str,
    reason: str,
    command_record: SlurmCommandResult | None,
    dependency_job_ids: Sequence[str] = (),
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
                dependency_job_ids=dependency_job_ids,
                command_record=command_record,
            ),
        ),
    )


def _write_run_submitted(
    *,
    run_store: RunStore,
    run_uri: str,
    manifest: SlurmLiveSubmissionManifest,
    message: str = "SLURM single-job submission accepted by scheduler",
) -> None:
    submitted_jobs = cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
    write_run_submitted(
        run_store,
        run_uri=run_uri,
        created_at=manifest.created_at,
        submitted_at=manifest.updated_at,
        message=message,
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


def _record_afterok_failure(
    *,
    run_store: RunStore,
    run_uri: str,
    manifest_path: Path,
    manifest: SlurmLiveSubmissionManifest,
    planning_result: SlurmDryRunPlanningResult,
    logical_key: str,
    reason: str,
    dependency_job_ids: Sequence[str],
    command_record: SlurmCommandResult | None,
    submitted_jobs: Sequence[SlurmSubmittedJob],
    context: Mapping[str, PlainData] | None = None,
) -> SlurmLiveSubmissionResult:
    if not submitted_jobs:
        failed = _failed_manifest(
            manifest,
            logical_key=logical_key,
            reason=reason,
            command_record=command_record,
            dependency_job_ids=dependency_job_ids,
        )
        _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=failed,
            state=SubmittedOperationState.FAILED,
        )
        raise SlurmSubmissionError(
            reason,
            code="executor.slurm.afterok.submission_failed",
            context={"logical_key": logical_key, **dict(context or {})},
        )
    partial = replace(
        manifest,
        submission_status=SlurmLiveSubmissionStatus.PARTIAL,
        updated_at=utc_timestamp(),
        submitted_at=manifest.submitted_at or manifest.updated_at,
        submitted_jobs=tuple(submitted_jobs),
        failed_submissions=(
            *manifest.failed_submissions,
            SlurmFailedSubmission(
                logical_key=logical_key,
                failed_at=utc_timestamp(),
                reason=reason,
                dependency_job_ids=dependency_job_ids,
                command_record=command_record,
            ),
        ),
    )
    _write_manifest_and_registry(
        run_store=run_store,
        run_uri=run_uri,
        manifest_path=manifest_path,
        manifest=partial,
        state=SubmittedOperationState.PARTIAL,
    )
    _write_run_submitted(
        run_store=run_store,
        run_uri=run_uri,
        manifest=partial,
        message="SLURM afterok submission partially accepted by scheduler",
    )
    return _live_result(
        manifest=partial,
        planning_result=planning_result,
        status=SlurmLiveSubmissionStatus.PARTIAL,
    )


def _live_result(
    *,
    manifest: SlurmLiveSubmissionManifest,
    planning_result: SlurmDryRunPlanningResult,
    status: SlurmLiveSubmissionStatus,
) -> SlurmLiveSubmissionResult:
    submitted_jobs = cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
    failed = cast(tuple[SlurmFailedSubmission, ...], manifest.failed_submissions)
    planned_jobs = cast(tuple[SlurmPlannedJob, ...], manifest.jobs)
    return SlurmLiveSubmissionResult(
        run_uri=manifest.run_uri,
        mode=cast(SlurmMode, manifest.mode).value,
        submission_id=manifest.submission_id,
        status=status.value,
        manifest_path=str(planning_result.manifest_artifact.local_path),
        manifest_relative_path=manifest.manifest_relative_path,
        plan_path=str(planning_result.plan_artifact.local_path),
        plan_relative_path=manifest.plan_relative_path,
        submitted_jobs=tuple(_submitted_job_summary(job) for job in submitted_jobs),
        failed_submissions=tuple(_failed_submission_summary(item) for item in failed),
        log_paths=tuple(_submitted_job_log_summary(job) for job in submitted_jobs),
        job_count=len(planned_jobs),
        submitted_job_count=len(submitted_jobs),
        failed_submission_count=len(failed),
    )


def _submitted_job_summary(job: SlurmSubmittedJob) -> Mapping[str, PlainData]:
    return {
        "logical_key": job.logical_key,
        "scheduler_job_id": job.scheduler_job_id,
        "scheduler_cluster": job.scheduler_cluster,
        "dependency_job_ids": list(job.dependency_job_ids),
        "script_relative_path": job.script_relative_path,
        "stdout_relative_path": job.stdout_relative_path,
        "stderr_relative_path": job.stderr_relative_path,
    }


def _submitted_job_log_summary(job: SlurmSubmittedJob) -> Mapping[str, PlainData]:
    return {
        "logical_key": job.logical_key,
        "stdout_relative_path": job.stdout_relative_path,
        "stderr_relative_path": job.stderr_relative_path,
    }


def _failed_submission_summary(item: SlurmFailedSubmission) -> Mapping[str, PlainData]:
    return {
        "logical_key": item.logical_key,
        "reason": item.reason,
        "dependency_job_ids": list(item.dependency_job_ids),
        "failed_at": item.failed_at,
    }


def _dependency_job_ids(
    job: SlurmPlannedJob,
    scheduler_ids_by_key: Mapping[str, str],
) -> tuple[str, ...]:
    return tuple(
        scheduler_ids_by_key[key]
        for key in job.dependency_job_keys
        if key in scheduler_ids_by_key
    )


def _sbatch_argv(
    script_path: Path, dependency_job_ids: Sequence[str]
) -> tuple[str, ...]:
    argv = ["sbatch", "--parsable"]
    if dependency_job_ids:
        argv.append("--dependency=afterok:" + ":".join(dependency_job_ids))
    argv.append(str(script_path))
    return tuple(argv)


def _write_submitted_stage(
    *,
    run_store: RunStore,
    run_uri: str,
    job: SlurmPlannedJob,
    submitted_job: SlurmSubmittedJob,
    registry: SubmittedOperationRecord,
    submitted_at: str,
) -> None:
    stage_name = _stage_name_from_logical_key(job.logical_key)
    status = run_store.read_stage_status(run_uri, stage_name)
    attempt = 1 if status is None else status.attempt
    metadata = submitted_stage_metadata(
        record=registry,
        stage_name=stage_name,
        attempt=attempt,
        continuation_executor="local",
        stage_metadata={
            "logical_key": job.logical_key,
            "scheduler_job_id": submitted_job.scheduler_job_id,
        },
    )
    _merge_worker_request_metadata(
        run_store=run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        metadata=metadata,
    )
    write_stage_submitted(
        run_store,
        run_uri=run_uri,
        stage_name=stage_name,
        attempt=attempt,
        submitted_at=submitted_at,
        owner={
            "component": "slurm-afterok",
            "scheduler_job_id": submitted_job.scheduler_job_id,
        },
        metadata=metadata,
    )


def _merge_worker_request_metadata(
    *,
    run_store: RunStore,
    run_uri: str,
    stage_name: str,
    attempt: int,
    metadata: Mapping[str, PlainData],
) -> None:
    raw = run_store.read_stage_worker_request(run_uri, stage_name, attempt=attempt)
    if raw is None:
        return
    existing_metadata = raw.get("metadata", {})
    if not isinstance(existing_metadata, Mapping):
        existing_metadata = {}
    merged = {
        **dict(raw),
        "metadata": {**dict(existing_metadata), **dict(metadata)},
    }
    run_store.write_stage_worker_request(run_uri, stage_name, merged, attempt=attempt)


def _stage_name_from_logical_key(logical_key: str) -> str:
    if not logical_key.startswith("stage:"):
        raise SlurmPlanningError("afterok submitted jobs must use stage logical keys")
    stage_name = logical_key.removeprefix("stage:")
    if not stage_name:
        raise SlurmPlanningError("afterok stage logical key is missing a stage name")
    return stage_name


def _authority_backend_metadata(run_store: RunStore) -> dict[str, PlainData]:
    raw_config = getattr(run_store, "authority_config", None)
    config = raw_config() if callable(raw_config) else None
    if not isinstance(config, AuthorityConfig):
        return {}
    reference = config.to_reference()
    return {
        "authority": {
            "backend_kind": config.backend_kind.value,
            "deployment_profile": config.deployment_profile.value,
            "reference": reference.redacted_dict(config.redaction_keys),
        }
    }


__all__ = [
    "SLURM_SUBMITTED_BACKEND",
    "SlurmLiveSubmissionResult",
    "default_slurm_command_runner",
    "submit_afterok_slurm",
    "submit_single_job_slurm",
]
