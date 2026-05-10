"""Submitted SLURM job cancellation services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus, StageStatusRecord
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.run_store import LegacyRunStore as RunStore, LocalRunStorePaths
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.serialization import PlainData, ensure_plain_data, json_loads
from loom.serialization.errors import PlainDataError
from loom.timestamps import utc_timestamp

from .commands import (
    SlurmCommandResult,
    SlurmCommandRunner,
    SubprocessSlurmCommandRunner,
    command_result_from_exception,
)
from .errors import SlurmCommandUnavailableError, SlurmLiveOperationError
from .live import (
    SlurmCancellationAttempt,
    SlurmLiveSubmissionManifest,
    SlurmLiveSubmissionStatus,
    SlurmSchedulerStatusSnapshot,
    SlurmSubmittedJob,
    read_slurm_live_manifest,
    write_slurm_live_manifest,
)
from .submission import SLURM_SUBMITTED_BACKEND

_FINAL_RUN_STATUSES = {
    RunStatus.SUCCEEDED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.INTERRUPTED,
}
_FINAL_STAGE_STATUSES = {
    StageStatus.SUCCEEDED,
    StageStatus.FAILED,
    StageStatus.CANCELLED,
    StageStatus.SKIPPED,
}
_DO_NOT_OVERWRITE_STAGE_STATUSES = {StageStatus.SUCCEEDED, StageStatus.FAILED}
_TERMINAL_SCHEDULER_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "SPECIAL_EXIT",
    "TIMEOUT",
}


class SlurmCancellationError(SlurmLiveOperationError):
    """Raised when submitted SLURM jobs cannot be cancelled."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


@dataclass(frozen=True, slots=True)
class SlurmJobCancellationResult:
    """Cancellation result for one submitted scheduler job."""

    logical_key: str
    scheduler_job_id: str
    outcome: str
    stage_name: str | None = None
    stage_status_before: str | None = None
    stage_status_after: str | None = None
    message: str | None = None
    command_record: SlurmCommandResult | None = None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "logical_key": self.logical_key,
            "stage_name": self.stage_name,
            "scheduler_job_id": self.scheduler_job_id,
            "outcome": self.outcome,
            "stage_status_before": self.stage_status_before,
            "stage_status_after": self.stage_status_after,
            "message": self.message,
            "command_record": None
            if self.command_record is None
            else self.command_record.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SlurmCancellationResult:
    """Result of one submitted SLURM cancellation operation."""

    run_uri: str
    submission_id: str
    status: str
    manifest_path: str
    manifest_relative_path: str
    job_results: Sequence[SlurmJobCancellationResult]
    run_status_before: str | None = None
    run_status_after: str | None = None
    cancelled_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    unknown_count: int = 0
    dry_run: bool = False
    warnings: Sequence[Mapping[str, PlainData]] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status in {"CANCELLED", "COMPLETED"}

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "submission_id": self.submission_id,
            "status": self.status,
            "dry_run": self.dry_run,
            "manifest_path": self.manifest_path,
            "manifest_relative_path": self.manifest_relative_path,
            "run_status_before": self.run_status_before,
            "run_status_after": self.run_status_after,
            "cancelled_count": self.cancelled_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "unknown_count": self.unknown_count,
            "job_results": [result.to_dict() for result in self.job_results],
            "warnings": [dict(warning) for warning in self.warnings],
        }


def default_slurm_cancel_command_runner() -> SlurmCommandRunner:
    """Return the default command runner for submitted-job cancellation."""

    return SubprocessSlurmCommandRunner()


def cancel_slurm_jobs(
    run_uri: str,
    *,
    run_store: RunStore | None = None,
    command_runner: SlurmCommandRunner | None = None,
    cancelled_at: str | None = None,
) -> SlurmCancellationResult:
    """Cancel non-terminal jobs in the latest active SLURM submission."""

    store = LocalRunStore() if run_store is None else run_store
    if not isinstance(store, RunStore):
        raise SlurmCancellationError(
            "job cancellation requires a run store",
            code="executor.slurm.cancel.invalid_run_store",
        )
    if not isinstance(store, LocalRunStorePaths):
        raise SlurmCancellationError(
            "job cancellation requires local run-store path helpers",
            code="executor.slurm.cancel.missing_local_paths",
        )

    now = cancelled_at or utc_timestamp()
    record = store.latest_active_submitted_operation(run_uri)
    if record is None:
        raise SlurmCancellationError(
            "run has no active submitted operation to cancel",
            code="executor.slurm.cancel.no_active_submission",
            context={"run_uri": run_uri},
        )
    if record.backend != SLURM_SUBMITTED_BACKEND:
        raise SlurmCancellationError(
            f"latest active submitted operation uses unsupported backend: {record.backend}",
            code="executor.slurm.cancel.unsupported_backend",
            context={"backend": record.backend, "submission_id": record.submission_id},
        )

    manifest_path = _manifest_path(store, run_uri=run_uri, record=record)
    manifest = _read_live_manifest(manifest_path)
    state = store.inspect_run_state(run_uri)
    stage_statuses = {
        stage.stage_name: stage.status for stage in state.stage_inspections
    }
    latest_snapshots = _latest_snapshots_by_job(manifest)
    runner = command_runner or default_slurm_cancel_command_runner()

    results: list[SlurmJobCancellationResult] = []
    attempts: list[SlurmCancellationAttempt] = []
    cancelled_job_ids: list[str] = []
    for submitted in cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs):
        stage_name = _stage_name_from_logical_key(submitted.logical_key)
        stage_status = None if stage_name is None else stage_statuses.get(stage_name)
        terminal_reason = _terminal_skip_reason(
            submitted,
            run_status=state.run_status,
            stage_status=stage_status,
            latest_snapshot=latest_snapshots.get(submitted.scheduler_job_id),
        )
        if terminal_reason is not None:
            result, attempt = _skipped_terminal_result(
                submitted,
                stage_name=stage_name,
                stage_status=stage_status,
                reason=terminal_reason,
                attempted_at=now,
            )
            results.append(result)
            attempts.append(attempt)
            continue

        command_result = _run_scancel(runner, submitted.scheduler_job_id)
        if command_result.ok:
            stage_status_after = _mark_stage_cancelled_if_safe(
                store,
                run_uri=run_uri,
                submitted=submitted,
                stage_name=stage_name,
                stage_status=stage_status,
                cancelled_at=now,
            )
            message = "cancelled"
            outcome = "cancelled"
            cancelled_job_ids.append(submitted.scheduler_job_id)
        else:
            stage_status_after = None if stage_status is None else stage_status.status.value
            message = _command_failure_message(command_result)
            outcome = "failed"
        result = SlurmJobCancellationResult(
            logical_key=submitted.logical_key,
            stage_name=stage_name,
            scheduler_job_id=submitted.scheduler_job_id,
            outcome=outcome,
            stage_status_before=None
            if stage_status is None
            else stage_status.status.value,
            stage_status_after=stage_status_after,
            message=message,
            command_record=command_result,
        )
        results.append(result)
        attempts.append(_attempt_from_result(result, attempted_at=now))

    status, registry_state = _aggregate_status(results)
    run_status_before = None if state.run_status is None else state.run_status.status.value
    run_status_after = run_status_before
    if status == "CANCELLED" and _can_mark_run_cancelled(state.run_status, results):
        run_status_after = _mark_run_cancelled_if_safe(
            store,
            run_uri=run_uri,
            run_status=state.run_status,
            cancelled_job_ids=cancelled_job_ids,
            cancelled_at=now,
        )

    updated_manifest = replace(
        manifest,
        updated_at=now,
        completed_at=now if status in {"CANCELLED", "COMPLETED"} else manifest.completed_at,
        submission_status=_manifest_status_for(status),
        cancellation_attempts=tuple(manifest.cancellation_attempts) + tuple(attempts),
    )
    write_slurm_live_manifest(manifest_path, updated_manifest)
    updated_record = replace(
        record,
        updated_at=now,
        state=registry_state,
        summary_counts=_registry_summary_counts(status, results),
        backend_metadata=_updated_backend_metadata(record, results, captured_at=now),
    )
    store.write_submitted_operation(run_uri, updated_record)

    return SlurmCancellationResult(
        run_uri=run_uri,
        submission_id=record.submission_id,
        status=status,
        manifest_path=str(manifest_path),
        manifest_relative_path=record.manifest_relative_path,
        run_status_before=run_status_before,
        run_status_after=run_status_after,
        job_results=tuple(results),
        cancelled_count=sum(1 for result in results if result.outcome == "cancelled"),
        failed_count=sum(1 for result in results if result.outcome == "failed"),
        skipped_count=sum(
            1 for result in results if result.outcome == "skipped_terminal"
        ),
        unknown_count=sum(1 for result in results if result.outcome == "unknown"),
    )


def _run_scancel(runner: SlurmCommandRunner, scheduler_job_id: str) -> SlurmCommandResult:
    try:
        return runner.scancel(job_ids=(scheduler_job_id,))
    except SlurmCommandUnavailableError as exc:
        return command_result_from_exception(
            command="scancel",
            argv=("scancel", scheduler_job_id),
            exc=exc,
        )
    except Exception as exc:
        return command_result_from_exception(
            command="scancel",
            argv=("scancel", scheduler_job_id),
            exc=exc,
        )


def _mark_stage_cancelled_if_safe(
    store: RunStore,
    *,
    run_uri: str,
    submitted: SlurmSubmittedJob,
    stage_name: str | None,
    stage_status: StageStatusRecord | None,
    cancelled_at: str,
) -> str | None:
    if stage_name is None or stage_status is None:
        return None
    if stage_status.status in _DO_NOT_OVERWRITE_STAGE_STATUSES:
        return stage_status.status.value
    if stage_status.status is StageStatus.CANCELLED:
        return StageStatus.CANCELLED.value
    record = replace(
        stage_status,
        status=StageStatus.CANCELLED,
        updated_at=cancelled_at,
        finished_at=cancelled_at,
        message="submitted SLURM job cancelled",
        metadata=_merge_plain_metadata(
            stage_status.metadata,
            {"slurm": {"cancelled_job_id": submitted.scheduler_job_id}},
        ),
    )
    store.write_stage_status(run_uri, stage_name, record)
    return StageStatus.CANCELLED.value


def _mark_run_cancelled_if_safe(
    store: RunStore,
    *,
    run_uri: str,
    run_status: RunStatusRecord | None,
    cancelled_job_ids: Sequence[str],
    cancelled_at: str,
) -> str | None:
    if run_status is None:
        return None
    if run_status.status in _FINAL_RUN_STATUSES:
        return run_status.status.value
    record = replace(
        run_status,
        status=RunStatus.CANCELLED,
        updated_at=cancelled_at,
        finished_at=cancelled_at,
        message="submitted SLURM jobs cancelled",
        metadata=_merge_plain_metadata(
            run_status.metadata,
            {"slurm": {"cancelled_job_ids": list(cancelled_job_ids)}},
        ),
    )
    store.write_run_status(run_uri, record)
    return RunStatus.CANCELLED.value


def _can_mark_run_cancelled(
    run_status: RunStatusRecord | None,
    results: Sequence[SlurmJobCancellationResult],
) -> bool:
    if run_status is None or run_status.status in _FINAL_RUN_STATUSES:
        return False
    if any(result.stage_status_before == StageStatus.FAILED.value for result in results):
        return False
    return all(
        result.outcome in {"cancelled", "skipped_terminal"} for result in results
    )


def _terminal_skip_reason(
    submitted: SlurmSubmittedJob,
    *,
    run_status: RunStatusRecord | None,
    stage_status: StageStatusRecord | None,
    latest_snapshot: SlurmSchedulerStatusSnapshot | None,
) -> str | None:
    if submitted.logical_key == "pipeline" and run_status is not None:
        if run_status.status in _FINAL_RUN_STATUSES:
            return f"run status is {run_status.status.value}"
    if stage_status is not None and stage_status.status in _FINAL_STAGE_STATUSES:
        return f"stage status is {stage_status.status.value}"
    if latest_snapshot is not None and _normalize_scheduler_state(latest_snapshot.state) in _TERMINAL_SCHEDULER_STATES:
        return f"scheduler snapshot state is {latest_snapshot.state}"
    return None


def _skipped_terminal_result(
    submitted: SlurmSubmittedJob,
    *,
    stage_name: str | None,
    stage_status: StageStatusRecord | None,
    reason: str,
    attempted_at: str,
) -> tuple[SlurmJobCancellationResult, SlurmCancellationAttempt]:
    command_record = SlurmCommandResult(
        command="scancel",
        argv=("scancel", submitted.scheduler_job_id),
        returncode=0,
        stderr=reason,
        started_at=attempted_at,
        finished_at=attempted_at,
    )
    result = SlurmJobCancellationResult(
        logical_key=submitted.logical_key,
        stage_name=stage_name,
        scheduler_job_id=submitted.scheduler_job_id,
        outcome="skipped_terminal",
        stage_status_before=None if stage_status is None else stage_status.status.value,
        stage_status_after=None if stage_status is None else stage_status.status.value,
        message=reason,
        command_record=command_record,
    )
    return result, _attempt_from_result(result, attempted_at=attempted_at)


def _attempt_from_result(
    result: SlurmJobCancellationResult, *, attempted_at: str
) -> SlurmCancellationAttempt:
    command_record = result.command_record or SlurmCommandResult(
        command="scancel",
        argv=("scancel", result.scheduler_job_id),
        returncode=127,
        stderr=result.message or result.outcome,
        started_at=attempted_at,
        finished_at=attempted_at,
    )
    return SlurmCancellationAttempt(
        logical_key=result.logical_key,
        scheduler_job_id=result.scheduler_job_id,
        attempted_at=attempted_at,
        outcome=result.outcome,
        message=result.message,
        command_record=command_record,
    )


def _aggregate_status(
    results: Sequence[SlurmJobCancellationResult],
) -> tuple[str, SubmittedOperationState]:
    failed = sum(1 for result in results if result.outcome == "failed")
    unknown = sum(1 for result in results if result.outcome == "unknown")
    cancelled = sum(1 for result in results if result.outcome == "cancelled")
    skipped = sum(1 for result in results if result.outcome == "skipped_terminal")
    if unknown:
        return "UNKNOWN", SubmittedOperationState.UNKNOWN
    if failed:
        if cancelled or skipped:
            return "PARTIAL", SubmittedOperationState.PARTIAL
        return "UNKNOWN", SubmittedOperationState.UNKNOWN
    if cancelled:
        return "CANCELLED", SubmittedOperationState.CANCELLED
    return "COMPLETED", SubmittedOperationState.COMPLETED


def _manifest_status_for(status: str) -> SlurmLiveSubmissionStatus:
    if status == "CANCELLED":
        return SlurmLiveSubmissionStatus.CANCELLED
    if status == "COMPLETED":
        return SlurmLiveSubmissionStatus.COMPLETED
    if status == "PARTIAL":
        return SlurmLiveSubmissionStatus.PARTIAL
    return SlurmLiveSubmissionStatus.UNKNOWN


def _updated_backend_metadata(
    record: SubmittedOperationRecord,
    results: Sequence[SlurmJobCancellationResult],
    *,
    captured_at: str,
) -> dict[str, PlainData]:
    metadata = dict(record.backend_metadata)
    metadata["slurm_cancellation"] = _plain_mapping(
        {
            "captured_at": captured_at,
            "jobs": [
                {
                    "logical_key": result.logical_key,
                    "scheduler_job_id": result.scheduler_job_id,
                    "outcome": result.outcome,
                    "message": result.message,
                }
                for result in results
            ],
        },
        path="submitted_operation.backend_metadata.slurm_cancellation",
    )
    return _plain_mapping(metadata, path="submitted_operation.backend_metadata")


def _registry_summary_counts(
    status: str,
    results: Sequence[SlurmJobCancellationResult],
) -> dict[str, int]:
    cancelled = sum(1 for result in results if result.outcome == "cancelled")
    failed = sum(1 for result in results if result.outcome == "failed")
    skipped = sum(1 for result in results if result.outcome == "skipped_terminal")
    unknown = sum(1 for result in results if result.outcome == "unknown")
    counts = {
        "cancelled": cancelled,
        "failed": failed,
        "completed": skipped,
        "unknown": unknown,
    }
    active = failed + unknown
    if status in {"PARTIAL", "UNKNOWN"}:
        counts["active"] = max(1, active)
        counts["submitted"] = max(1, active)
    return counts


def _command_failure_message(result: SlurmCommandResult) -> str:
    if result.stderr:
        return result.stderr
    if result.stdout:
        return result.stdout
    return f"scancel exited with status {result.returncode}"


def _manifest_path(
    store: LocalRunStorePaths,
    *,
    run_uri: str,
    record: SubmittedOperationRecord,
) -> Path:
    return store.local_generated_artifact_path(run_uri, record.manifest_relative_path)


def _read_live_manifest(path: Path) -> SlurmLiveSubmissionManifest:
    try:
        data = json_loads(path.read_text(encoding="utf-8"), path=str(path))
    except OSError as exc:
        raise SlurmCancellationError(
            f"failed to read SLURM live manifest: {path}",
            code="executor.slurm.cancel.manifest_read_error",
            context={"manifest_path": str(path)},
        ) from exc
    return read_slurm_live_manifest(data)


def _latest_snapshots_by_job(
    manifest: SlurmLiveSubmissionManifest,
) -> dict[str, SlurmSchedulerStatusSnapshot]:
    snapshots: dict[str, SlurmSchedulerStatusSnapshot] = {}
    for snapshot in cast(
        tuple[SlurmSchedulerStatusSnapshot, ...], manifest.status_snapshots
    ):
        snapshots[snapshot.scheduler_job_id] = snapshot
    return snapshots


def _stage_name_from_logical_key(logical_key: str) -> str | None:
    prefix = "stage:"
    return logical_key[len(prefix) :] if logical_key.startswith(prefix) else None


def _normalize_scheduler_state(value: str) -> str:
    return value.strip().upper().split()[0]


def _merge_plain_metadata(
    existing: Mapping[str, PlainData],
    updates: Mapping[str, object],
) -> dict[str, PlainData]:
    merged = dict(existing)
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            nested = dict(cast(Mapping[str, object], merged[key]))
            nested.update(value)
            merged[key] = _plain_mapping(nested, path=f"metadata.{key}")
        else:
            merged[key] = _plain_mapping({key: value}, path=f"metadata.{key}")[key]
    return _plain_mapping(merged, path="metadata")


def _plain_mapping(value: object, *, path: str) -> dict[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise SlurmCancellationError(
            f"{path} must be plain-data-compatible",
            code="executor.slurm.cancel.invalid_plain_data",
            context={"error": str(exc)},
        ) from exc
    if not isinstance(normalized, dict):
        raise SlurmCancellationError(
            f"{path} must be a mapping",
            code="executor.slurm.cancel.invalid_plain_data",
        )
    return normalized


__all__ = [
    "SlurmCancellationError",
    "SlurmCancellationResult",
    "SlurmJobCancellationResult",
    "cancel_slurm_jobs",
    "default_slurm_cancel_command_runner",
]
