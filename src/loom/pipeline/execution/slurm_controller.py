"""Execution-owned live SLURM submission controller."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any, cast

from loom.fingerprints import hash_mapping
from loom.pipeline.execution.lifecycle import write_run_submitted, write_stage_submitted
from loom.pipeline.stores import AuthorityConfig
from loom.pipeline.stores.authority import PerRunAuthorityStore
from loom.pipeline.stores.run_store import (
    LegacyRunStore,
    LocalRunStorePaths,
    RunStatusStore,
    RunSubmittedOperationStore,
    StageStateStore,
)
from loom.pipeline.submitted import (
    SubmittedOperationRecord,
    SubmittedOperationState,
    submitted_stage_metadata,
)
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

from loom.pipeline.executors.slurm.artifacts import SlurmDryRunPlanningResult
from loom.pipeline.executors.slurm.authority import (
    SlurmLiveAuthorityFacts,
    slurm_live_authority_facts,
)
from loom.pipeline.executors.slurm.commands import (
    SlurmCommandResult,
    SlurmCommandRunner,
    command_result_from_exception,
    parse_sbatch_parsable_output,
)
from loom.pipeline.executors.slurm.errors import (
    SlurmActiveSubmissionError,
    SlurmCommandUnavailableError,
    SlurmJobIdParseError,
    SlurmManifestUpdateError,
    SlurmPlanningError,
    SlurmSubmissionError,
)
from loom.pipeline.executors.slurm.live import (
    SlurmFailedSubmission,
    SlurmLiveSubmissionManifest,
    SlurmLiveSubmissionStatus,
    SlurmSchedulerOperation,
    SlurmSchedulerOperationState,
    SlurmSubmittedJob,
    live_manifest_from_planned_submission,
    read_slurm_live_manifest,
    write_slurm_live_manifest,
)
from loom.pipeline.executors.slurm.manifest import SlurmMode, SlurmPlannedJob
from loom.pipeline.executors.slurm.submission import (
    SLURM_SUBMITTED_BACKEND,
    SlurmLiveSubmissionResult,
    default_slurm_command_runner as _executor_default_slurm_command_runner,
)
from loom.pipeline.executors.slurm.ready_stage import operation_marker

RunStore = LegacyRunStore


@dataclass(frozen=True, slots=True)
class SlurmSubmissionServices:
    """Durable capabilities required by live SLURM submission."""

    submitted_operations: RunSubmittedOperationStore
    run_status: RunStatusStore
    stage_state: StageStateStore
    local_paths: LocalRunStorePaths
    authority_config: AuthorityConfig | None = None
    authority_store: PerRunAuthorityStore | None = None

    def __post_init__(self) -> None:
        for name, protocol in (
            ("submitted_operations", RunSubmittedOperationStore),
            ("run_status", RunStatusStore),
            ("stage_state", StageStateStore),
            ("local_paths", LocalRunStorePaths),
        ):
            if not isinstance(getattr(self, name), protocol):
                raise TypeError(
                    f"SlurmSubmissionServices.{name} must satisfy {protocol.__name__}"
                )
        if self.authority_config is not None and not isinstance(
            self.authority_config, AuthorityConfig
        ):
            raise TypeError(
                "SlurmSubmissionServices.authority_config must be AuthorityConfig"
            )
        if self.authority_store is not None and not isinstance(
            self.authority_store, PerRunAuthorityStore
        ):
            raise TypeError(
                "SlurmSubmissionServices.authority_store must satisfy PerRunAuthorityStore"
            )

    @classmethod
    def from_legacy(cls, run_store: LegacyRunStore) -> "SlurmSubmissionServices":
        if not isinstance(run_store, LegacyRunStore):
            raise TypeError("run_store must satisfy LegacyRunStore")
        if not isinstance(run_store, LocalRunStorePaths):
            raise TypeError("run_store must satisfy LocalRunStorePaths")
        raw_config = getattr(run_store, "authority_config", None)
        config = raw_config() if callable(raw_config) else raw_config
        return cls(
            submitted_operations=run_store,
            run_status=run_store,
            stage_state=run_store,
            local_paths=run_store,
            authority_config=cast(AuthorityConfig | None, config),
            authority_store=cast(
                PerRunAuthorityStore | None,
                getattr(run_store, "authority_store", None),
            ),
        )


_SLURM_METHOD_FIELDS: dict[str, str] = {}
for _field_name, _protocol in (
    ("submitted_operations", RunSubmittedOperationStore),
    ("run_status", RunStatusStore),
    ("stage_state", StageStateStore),
    ("local_paths", LocalRunStorePaths),
):
    for _method_name, _method in _protocol.__dict__.items():
        if callable(_method) and not _method_name.startswith("_"):
            _SLURM_METHOD_FIELDS[_method_name] = _field_name


class _SlurmStoreFacade(
    RunSubmittedOperationStore, RunStatusStore, StageStateStore, LocalRunStorePaths
):
    __slots__ = ("_services",)

    def __init__(self, services: SlurmSubmissionServices) -> None:
        self._services = services

    def __getattribute__(self, name: str) -> object:
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        services = object.__getattribute__(self, "_services")
        if name == "authority_config":
            return lambda: services.authority_config
        if name == "authority_store":
            return services.authority_store
        field_name = _SLURM_METHOD_FIELDS.get(name)
        if field_name is None:
            raise AttributeError(name)
        return getattr(getattr(services, field_name), name)


def default_slurm_command_runner() -> SlurmCommandRunner:
    """Return the default live SLURM command runner."""

    return _executor_default_slurm_command_runner()


def _submit_single_job_slurm(
    *,
    run_store: RunStore,
    run_uri: str,
    planning_result: SlurmDryRunPlanningResult,
    command_runner: SlurmCommandRunner | None = None,
    submitted_at: str | None = None,
    queue_item_id: str | None = None,
) -> SlurmLiveSubmissionResult:
    """Submit a v6 single-job SLURM script and persist live submission facts."""

    if not isinstance(planning_result, SlurmDryRunPlanningResult):
        raise SlurmPlanningError("planning_result must be SlurmDryRunPlanningResult")
    submission = planning_result.submission
    if submission.mode != SlurmMode.SINGLE_JOB:
        raise SlurmPlanningError("submit_single_job_slurm requires slurm-single-job")
    _require_slurm_live_authority(run_store, operation="single-job submission")
    if queue_item_id is not None:
        return _submit_or_resume_queued_slurm(
            run_store=run_store,
            run_uri=run_uri,
            planning_result=planning_result,
            command_runner=command_runner,
            submitted_at=submitted_at,
            queue_item_id=queue_item_id,
        )

    _raise_if_active_submission(run_store=run_store, run_uri=run_uri)
    runner = command_runner or default_slurm_command_runner()
    now = submitted_at or utc_timestamp()
    manifest_path = planning_result.manifest_artifact.local_path
    draft = live_manifest_from_planned_submission(
        submission,
        status=SlurmLiveSubmissionStatus.SUBMITTING,
        updated_at=now,
        queue_item_id=queue_item_id,
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
        command_result = runner.sbatch(
            script.local_path,
            comment=_queue_operation_marker(draft, job.logical_key),
        )
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


def _submit_afterok_slurm(
    *,
    run_store: RunStore,
    run_uri: str,
    planning_result: SlurmDryRunPlanningResult,
    command_runner: SlurmCommandRunner | None = None,
    submitted_at: str | None = None,
    queue_item_id: str | None = None,
) -> SlurmLiveSubmissionResult:
    """Submit a v6 afterok SLURM DAG and persist accepted scheduler jobs."""

    if not isinstance(planning_result, SlurmDryRunPlanningResult):
        raise SlurmPlanningError("planning_result must be SlurmDryRunPlanningResult")
    submission = planning_result.submission
    if submission.mode != SlurmMode.AFTEROK:
        raise SlurmPlanningError("submit_afterok_slurm requires slurm-afterok")
    _require_slurm_live_authority(run_store, operation="afterok submission")
    if queue_item_id is not None:
        return _submit_or_resume_queued_slurm(
            run_store=run_store,
            run_uri=run_uri,
            planning_result=planning_result,
            command_runner=command_runner,
            submitted_at=submitted_at,
            queue_item_id=queue_item_id,
        )

    _raise_if_active_submission(run_store=run_store, run_uri=run_uri)
    runner = command_runner or default_slurm_command_runner()
    now = submitted_at or utc_timestamp()
    manifest_path = planning_result.manifest_artifact.local_path
    draft = live_manifest_from_planned_submission(
        submission,
        status=SlurmLiveSubmissionStatus.SUBMITTING,
        updated_at=now,
        queue_item_id=queue_item_id,
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
                comment=_queue_operation_marker(current, job.logical_key),
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


def _submit_or_resume_queued_slurm(
    *,
    run_store: RunStore,
    run_uri: str,
    planning_result: SlurmDryRunPlanningResult,
    command_runner: SlurmCommandRunner | None,
    submitted_at: str | None,
    queue_item_id: str,
) -> SlurmLiveSubmissionResult:
    """Drive one queued whole-run manifest through exact scheduler-call facts."""

    submission = planning_result.submission
    runner = command_runner or default_slurm_command_runner()
    manifest_path = planning_result.manifest_artifact.local_path
    latest = run_store.latest_submitted_operation(run_uri)
    if latest is None:
        now = submitted_at or utc_timestamp()
        current = live_manifest_from_planned_submission(
            submission,
            status=SlurmLiveSubmissionStatus.SUBMITTING,
            updated_at=now,
            queue_item_id=queue_item_id,
        )
        _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=current,
            state=SubmittedOperationState.SUBMITTING,
        )
    else:
        queue = latest.backend_metadata.get("queue")
        if (
            latest.submission_id != submission.planning_id
            or latest.mode != SlurmMode(submission.mode).value
            or latest.manifest_relative_path != submission.manifest_relative_path
            or not isinstance(queue, Mapping)
            or queue.get("queue_item_id") != queue_item_id
        ):
            raise SlurmActiveSubmissionError(
                "active submitted work belongs to another prepared queue launch"
            )
        try:
            current = read_slurm_live_manifest(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, TypeError) as exc:
            raise SlurmManifestUpdateError(
                "queued SLURM live manifest is unreadable"
            ) from exc
        if current.queue_item_id != queue_item_id:
            raise SlurmActiveSubmissionError(
                "queued SLURM live manifest has another queue item owner"
            )
        if current.submission_status is SlurmLiveSubmissionStatus.SUBMITTED:
            return _live_result(
                manifest=current,
                planning_result=planning_result,
                status=SlurmLiveSubmissionStatus.SUBMITTED,
            )

    jobs = cast(tuple[SlurmPlannedJob, ...], submission.jobs)
    submitted_jobs = list(cast(tuple[SlurmSubmittedJob, ...], current.submitted_jobs))
    submitted_by_key = {job.logical_key: job for job in submitted_jobs}
    operations = list(
        cast(tuple[SlurmSchedulerOperation, ...], current.scheduler_operations)
    )
    operations_by_key = {operation.logical_key: operation for operation in operations}

    for job in jobs:
        if job.logical_key in submitted_by_key:
            continue
        dependency_job_ids = tuple(
            submitted_by_key[key].scheduler_job_id
            for key in job.dependency_job_keys
            if key in submitted_by_key
        )
        if len(dependency_job_ids) != len(job.dependency_job_keys):
            return _record_queued_unknown(
                run_store=run_store,
                run_uri=run_uri,
                manifest_path=manifest_path,
                manifest=current,
                planning_result=planning_result,
                evidence="slurm_queue_dependency_handle_missing",
            )
        script = planning_result.script_artifacts.get(job.logical_key)
        if script is None or job.script_relative_path is None:
            raise SlurmPlanningError("queued SLURM job has no prepared script")
        operation = operations_by_key.get(job.logical_key)
        if operation is None:
            operation = _queued_operation(
                manifest=current,
                job=job,
                dependency_job_ids=dependency_job_ids,
                now=utc_timestamp(),
            )
            operations.append(operation)
            operations_by_key[job.logical_key] = operation
            current = replace(current, scheduler_operations=tuple(operations))
            _write_manifest_and_registry(
                run_store=run_store,
                run_uri=run_uri,
                manifest_path=manifest_path,
                manifest=current,
                state=SubmittedOperationState.SUBMITTING,
            )
        else:
            _validate_queued_operation_identity(
                manifest=current,
                job=job,
                dependency_job_ids=dependency_job_ids,
                operation=operation,
            )

        if operation.state in {
            SlurmSchedulerOperationState.SUBMITTING,
            SlurmSchedulerOperationState.UNKNOWN,
        }:
            discovery = _discover_queued_operation(runner, operation)
            if discovery is None or len(discovery) == 0:
                operation = replace(
                    operation,
                    state=SlurmSchedulerOperationState.UNKNOWN,
                    updated_at=utc_timestamp(),
                    evidence="slurm_operation_not_found"
                    if discovery is not None
                    else "slurm_discovery_unknown",
                )
                operations = _replace_scheduler_operation(operations, operation)
                current = replace(current, scheduler_operations=tuple(operations))
                return _record_queued_unknown(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    evidence=cast(str, operation.evidence),
                )
            if len(discovery) > 1:
                operation = replace(
                    operation,
                    state=SlurmSchedulerOperationState.CONFLICT,
                    updated_at=utc_timestamp(),
                    evidence="slurm_operation_multiple_matches",
                )
                operations = _replace_scheduler_operation(operations, operation)
                current = replace(current, scheduler_operations=tuple(operations))
                return _record_queued_unknown(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    evidence="slurm_operation_multiple_matches",
                )
            scheduler_job_id, scheduler_cluster = next(iter(discovery))
            command_result = SlurmCommandResult(
                command="slurm-operation-discovery",
                argv=("discover", operation.marker),
                returncode=0,
                stdout=scheduler_job_id,
            )
            submitted_job = _queued_submitted_job(
                job=job,
                scheduler_job_id=scheduler_job_id,
                scheduler_cluster=scheduler_cluster,
                command_result=command_result,
                dependency_job_ids=dependency_job_ids,
                submitted_at=utc_timestamp(),
            )
            operation = replace(
                operation,
                state=SlurmSchedulerOperationState.ACCEPTED,
                updated_at=utc_timestamp(),
                evidence="slurm_operation_reconciled",
            )
        elif operation.state is SlurmSchedulerOperationState.INTENT:
            operation = replace(
                operation,
                state=SlurmSchedulerOperationState.SUBMITTING,
                updated_at=utc_timestamp(),
                evidence="slurm_submit_call_started",
            )
            operations = _replace_scheduler_operation(operations, operation)
            current = replace(current, scheduler_operations=tuple(operations))
            _write_manifest_and_registry(
                run_store=run_store,
                run_uri=run_uri,
                manifest_path=manifest_path,
                manifest=current,
                state=SubmittedOperationState.SUBMITTING,
            )
            try:
                command_result = runner.sbatch(
                    script.local_path,
                    dependency_job_ids=dependency_job_ids,
                    comment=operation.marker,
                )
            except Exception:
                operation = replace(
                    operation,
                    state=SlurmSchedulerOperationState.UNKNOWN,
                    updated_at=utc_timestamp(),
                    evidence="slurm_submit_unknown",
                )
                operations = _replace_scheduler_operation(operations, operation)
                current = replace(current, scheduler_operations=tuple(operations))
                return _record_queued_unknown(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    evidence="slurm_submit_unknown",
                )
            if not command_result.ok:
                return _record_queued_rejection(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    operations=operations,
                    operation=operation,
                    job=job,
                    command_result=command_result,
                    dependency_job_ids=dependency_job_ids,
                )
            try:
                parsed = parse_sbatch_parsable_output(command_result.stdout)
            except SlurmJobIdParseError:
                operation = replace(
                    operation,
                    state=SlurmSchedulerOperationState.UNKNOWN,
                    updated_at=utc_timestamp(),
                    evidence="slurm_submit_unusable_success",
                )
                operations = _replace_scheduler_operation(operations, operation)
                current = replace(current, scheduler_operations=tuple(operations))
                return _record_queued_unknown(
                    run_store=run_store,
                    run_uri=run_uri,
                    manifest_path=manifest_path,
                    manifest=current,
                    planning_result=planning_result,
                    evidence="slurm_submit_unusable_success",
                )
            submitted_job = _queued_submitted_job(
                job=job,
                scheduler_job_id=parsed.job_id,
                scheduler_cluster=parsed.cluster,
                command_result=command_result,
                dependency_job_ids=dependency_job_ids,
                submitted_at=utc_timestamp(),
            )
            operation = replace(
                operation,
                state=SlurmSchedulerOperationState.ACCEPTED,
                updated_at=utc_timestamp(),
                evidence="slurm_submit_accepted",
            )
        else:
            return _record_queued_unknown(
                run_store=run_store,
                run_uri=run_uri,
                manifest_path=manifest_path,
                manifest=current,
                planning_result=planning_result,
                evidence="slurm_operation_not_resumable",
            )

        operations = _replace_scheduler_operation(operations, operation)
        submitted_jobs.append(submitted_job)
        submitted_by_key[job.logical_key] = submitted_job
        current = replace(
            current,
            updated_at=utc_timestamp(),
            submitted_jobs=tuple(submitted_jobs),
            scheduler_operations=tuple(operations),
        )
        registry = _write_manifest_and_registry(
            run_store=run_store,
            run_uri=run_uri,
            manifest_path=manifest_path,
            manifest=current,
            state=SubmittedOperationState.SUBMITTING,
        )
        if SlurmMode(submission.mode) is SlurmMode.AFTEROK:
            _write_submitted_stage(
                run_store=run_store,
                run_uri=run_uri,
                job=job,
                submitted_job=submitted_job,
                registry=registry,
                submitted_at=submitted_job.submitted_at,
            )

    submitted = replace(
        current,
        submission_status=SlurmLiveSubmissionStatus.SUBMITTED,
        updated_at=utc_timestamp(),
        submitted_at=current.submitted_at or utc_timestamp(),
        submitted_jobs=tuple(submitted_jobs),
        scheduler_operations=tuple(operations),
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
        message="queued SLURM submission accepted by scheduler",
    )
    return _live_result(
        manifest=submitted,
        planning_result=planning_result,
        status=SlurmLiveSubmissionStatus.SUBMITTED,
    )


def _queued_operation(
    *,
    manifest: SlurmLiveSubmissionManifest,
    job: SlurmPlannedJob,
    dependency_job_ids: tuple[str, ...],
    now: str,
) -> SlurmSchedulerOperation:
    if manifest.queue_item_id is None or job.script_relative_path is None:
        raise SlurmPlanningError("queued operation requires queue identity and script")
    semantic: dict[str, PlainData] = {
        "schema_version": 1,
        "queue_item_id": manifest.queue_item_id,
        "run_uri": manifest.run_uri,
        "submission_id": manifest.submission_id,
        "logical_key": job.logical_key,
        "script_relative_path": job.script_relative_path,
        "dependency_job_ids": list(dependency_job_ids),
    }
    digest = hash_mapping(semantic)
    return SlurmSchedulerOperation(
        operation_id=digest,
        operation_digest=digest,
        logical_key=job.logical_key,
        marker=operation_marker(digest),
        script_relative_path=job.script_relative_path,
        dependency_job_ids=dependency_job_ids,
        created_at=now,
        updated_at=now,
        state=SlurmSchedulerOperationState.INTENT,
        evidence="slurm_submit_intent_persisted",
    )


def _validate_queued_operation_identity(
    *,
    manifest: SlurmLiveSubmissionManifest,
    job: SlurmPlannedJob,
    dependency_job_ids: tuple[str, ...],
    operation: SlurmSchedulerOperation,
) -> None:
    expected = _queued_operation(
        manifest=manifest,
        job=job,
        dependency_job_ids=dependency_job_ids,
        now=operation.created_at,
    )
    if (
        operation.operation_id != expected.operation_id
        or operation.operation_digest != expected.operation_digest
        or operation.marker != expected.marker
        or operation.script_relative_path != expected.script_relative_path
        or operation.dependency_job_ids != expected.dependency_job_ids
    ):
        raise SlurmManifestUpdateError(
            "queued SLURM operation identity changed after persistence"
        )


def _discover_queued_operation(
    runner: SlurmCommandRunner,
    operation: SlurmSchedulerOperation,
) -> set[tuple[str, str | None]] | None:
    try:
        live = runner.discover_live_operations()
        retained = runner.discover_accounted_operations(
            started_after=operation.created_at
        )
    except Exception:
        return None
    if not live.ok or not retained.ok:
        return None
    matches_by_job: dict[str, set[str | None]] = {}
    try:
        for raw in live.stdout.splitlines():
            fields = raw.strip().split("|")
            if len(fields) == 2 and fields[1] == operation.marker:
                if not fields[0].isdecimal():
                    return None
                matches_by_job.setdefault(fields[0], set()).add(None)
        for raw in retained.stdout.splitlines():
            fields = raw.strip().split("|")
            if len(fields) == 3 and fields[1] == operation.marker:
                if not fields[0].isdecimal():
                    return None
                matches_by_job.setdefault(fields[0], set()).add(fields[2] or None)
    except Exception:
        return None
    matches: set[tuple[str, str | None]] = set()
    for job_id, clusters in matches_by_job.items():
        named = {cluster for cluster in clusters if cluster is not None}
        if len(named) <= 1:
            matches.add((job_id, next(iter(named)) if named else None))
        else:
            matches.update((job_id, cluster) for cluster in named)
    return matches


def _queued_submitted_job(
    *,
    job: SlurmPlannedJob,
    scheduler_job_id: str,
    scheduler_cluster: str | None,
    command_result: SlurmCommandResult,
    dependency_job_ids: tuple[str, ...],
    submitted_at: str,
) -> SlurmSubmittedJob:
    return SlurmSubmittedJob(
        logical_key=job.logical_key,
        scheduler_job_id=scheduler_job_id,
        scheduler_cluster=scheduler_cluster,
        raw_job_id_output=scheduler_job_id,
        submitted_at=submitted_at,
        command_record=command_result,
        dependency_job_ids=dependency_job_ids,
        script_relative_path=job.script_relative_path,
        stdout_relative_path=job.stdout_relative_path,
        stderr_relative_path=job.stderr_relative_path,
    )


def _replace_scheduler_operation(
    operations: Sequence[SlurmSchedulerOperation],
    replacement: SlurmSchedulerOperation,
) -> list[SlurmSchedulerOperation]:
    return [
        replacement if item.operation_id == replacement.operation_id else item
        for item in operations
    ]


def _record_queued_unknown(
    *,
    run_store: RunStore,
    run_uri: str,
    manifest_path: Path,
    manifest: SlurmLiveSubmissionManifest,
    planning_result: SlurmDryRunPlanningResult,
    evidence: str,
) -> SlurmLiveSubmissionResult:
    unknown = replace(
        manifest,
        submission_status=SlurmLiveSubmissionStatus.UNKNOWN,
        updated_at=utc_timestamp(),
    )
    _write_manifest_and_registry(
        run_store=run_store,
        run_uri=run_uri,
        manifest_path=manifest_path,
        manifest=unknown,
        state=SubmittedOperationState.UNKNOWN,
    )
    return _live_result(
        manifest=unknown,
        planning_result=planning_result,
        status=SlurmLiveSubmissionStatus.UNKNOWN,
    )


def _record_queued_rejection(
    *,
    run_store: RunStore,
    run_uri: str,
    manifest_path: Path,
    manifest: SlurmLiveSubmissionManifest,
    planning_result: SlurmDryRunPlanningResult,
    operations: Sequence[SlurmSchedulerOperation],
    operation: SlurmSchedulerOperation,
    job: SlurmPlannedJob,
    command_result: SlurmCommandResult,
    dependency_job_ids: tuple[str, ...],
) -> SlurmLiveSubmissionResult:
    rejected_operation = replace(
        operation,
        state=SlurmSchedulerOperationState.REJECTED,
        updated_at=utc_timestamp(),
        evidence="slurm_submit_definitely_rejected",
    )
    failed = _failed_manifest(
        manifest,
        logical_key=job.logical_key,
        reason=command_result.stderr or "sbatch returned a nonzero exit code",
        command_record=command_result,
        dependency_job_ids=dependency_job_ids,
    )
    has_jobs = bool(manifest.submitted_jobs)
    failed = replace(
        failed,
        submission_status=SlurmLiveSubmissionStatus.PARTIAL
        if has_jobs
        else SlurmLiveSubmissionStatus.FAILED,
        scheduler_operations=tuple(
            _replace_scheduler_operation(operations, rejected_operation)
        ),
    )
    state = (
        SubmittedOperationState.PARTIAL if has_jobs else SubmittedOperationState.FAILED
    )
    _write_manifest_and_registry(
        run_store=run_store,
        run_uri=run_uri,
        manifest_path=manifest_path,
        manifest=failed,
        state=state,
    )
    return _live_result(
        manifest=failed,
        planning_result=planning_result,
        status=SlurmLiveSubmissionStatus(failed.submission_status),
    )


def _raise_if_active_submission(*, run_store: RunStore, run_uri: str) -> None:
    active = run_store.latest_active_submitted_operation(run_uri)
    if active is None:
        return
    raise SlurmActiveSubmissionError(
        "run already has active submitted scheduler work; cancel it before resubmitting"
    )


def _require_slurm_live_authority(
    run_store: RunStore,
    *,
    operation: str,
) -> SlurmLiveAuthorityFacts:
    facts = slurm_live_authority_facts(run_store)
    if facts is None:
        raise SlurmSubmissionError(
            "live SLURM submission requires a service-profile authority-backed run store",
            code="executor.slurm.live_submission.missing_authority",
            context={"operation": operation},
        )
    return facts


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
                **(
                    {}
                    if manifest.queue_item_id is None
                    else {"queue": {"queue_item_id": manifest.queue_item_id}}
                ),
                **_authority_backend_metadata(run_store),
            },
        )
        run_store.write_submitted_operation(run_uri, record)
    except SlurmManifestUpdateError:
        raise
    except Exception as exc:
        raise SlurmManifestUpdateError(
            f"failed to write live SLURM manifest at {manifest_path}: {exc}"
        ) from exc
    return cast(SubmittedOperationRecord, record)


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
            "slurm": {"job_ids": [job.scheduler_job_id for job in submitted_jobs]},
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


def _queue_operation_marker(
    manifest: SlurmLiveSubmissionManifest, logical_key: str
) -> str | None:
    """Return the bounded scheduler-visible marker for one queued call."""

    if manifest.queue_item_id is None:
        return None
    marker = (
        f"loom-queue-v1:{manifest.queue_item_id}:{manifest.submission_id}:{logical_key}"
    )
    if len(marker) > 120:
        raise SlurmPlanningError("queued SLURM operation marker is too long")
    return marker


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
    run_store.write_stage_worker_request(
        run_uri,
        stage_name,
        {**dict(raw), "metadata": {**dict(existing_metadata), **dict(metadata)}},
        attempt=attempt,
    )


def _stage_name_from_logical_key(logical_key: str) -> str:
    if not logical_key.startswith("stage:"):
        raise SlurmPlanningError("afterok submitted jobs must use stage logical keys")
    stage_name = logical_key.removeprefix("stage:")
    if not stage_name:
        raise SlurmPlanningError("afterok stage logical key is missing a stage name")
    return stage_name


def _authority_backend_metadata(run_store: RunStore) -> dict[str, PlainData]:
    facts = slurm_live_authority_facts(run_store)
    if facts is None:
        return {}
    return {
        "authority": facts.to_metadata(),
    }


def submit_single_job_slurm(
    *,
    services: SlurmSubmissionServices,
    run_uri: str,
    planning_result: SlurmDryRunPlanningResult,
    command_runner: SlurmCommandRunner | None = None,
    submitted_at: str | None = None,
    queue_item_id: str | None = None,
) -> SlurmLiveSubmissionResult:
    """Run the single-job durable workflow with explicit services."""

    if not isinstance(services, SlurmSubmissionServices):
        raise SlurmPlanningError(
            "submit_single_job_slurm requires SlurmSubmissionServices"
        )
    return _submit_single_job_slurm(
        run_store=cast(LegacyRunStore, cast(Any, _SlurmStoreFacade)(services)),
        run_uri=run_uri,
        planning_result=planning_result,
        command_runner=command_runner,
        submitted_at=submitted_at,
        queue_item_id=queue_item_id,
    )


def submit_afterok_slurm(
    *,
    services: SlurmSubmissionServices,
    run_uri: str,
    planning_result: SlurmDryRunPlanningResult,
    command_runner: SlurmCommandRunner | None = None,
    submitted_at: str | None = None,
    queue_item_id: str | None = None,
) -> SlurmLiveSubmissionResult:
    """Run the afterok durable workflow with explicit services."""

    if not isinstance(services, SlurmSubmissionServices):
        raise SlurmPlanningError(
            "submit_afterok_slurm requires SlurmSubmissionServices"
        )
    return _submit_afterok_slurm(
        run_store=cast(LegacyRunStore, cast(Any, _SlurmStoreFacade)(services)),
        run_uri=run_uri,
        planning_result=planning_result,
        command_runner=command_runner,
        submitted_at=submitted_at,
        queue_item_id=queue_item_id,
    )


__all__ = [
    "SLURM_SUBMITTED_BACKEND",
    "SlurmSubmissionServices",
    "SlurmLiveSubmissionResult",
    "default_slurm_command_runner",
    "submit_afterok_slurm",
    "submit_single_job_slurm",
]
