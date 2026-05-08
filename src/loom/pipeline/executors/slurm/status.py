"""Scheduler-aware SLURM status inspection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.inspection import RunStateInspection, RunStageInspection
from loom.pipeline.stores.run_store import LocalRunStorePaths, RunStore
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData, ensure_plain_data, json_loads
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_timestamp

from .commands import (
    SlurmCommandResult,
    SlurmCommandRunner,
    SubprocessSlurmCommandRunner,
    bound_scheduler_output,
)
from .errors import SlurmCommandUnavailableError, SlurmLiveOperationError
from .live import (
    SlurmFailedSubmission,
    SlurmLiveSubmissionManifest,
    SlurmSchedulerStatusSnapshot,
    SlurmSubmittedJob,
    read_slurm_live_manifest,
    write_slurm_live_manifest,
)
from .submission import SLURM_SUBMITTED_BACKEND

_FINAL_RUN_STATUS = {
    RunStatus.SUCCEEDED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
    RunStatus.INTERRUPTED.value,
}
_FINAL_STAGE_STATUS = {
    StageStatus.SUCCEEDED.value,
    StageStatus.FAILED.value,
    StageStatus.CANCELLED.value,
    StageStatus.SKIPPED.value,
}
_SLURM_SUCCESS_STATES = frozenset({"COMPLETED"})
_SLURM_FAILURE_STATES = frozenset(
    {
        "BOOT_FAIL",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "SPECIAL_EXIT",
        "TIMEOUT",
    }
)
_SLURM_CANCELLED_STATES = frozenset({"CANCELLED"})
_SLURM_ACTIVE_STATES = frozenset(
    {
        "COMPLETING",
        "CONFIGURING",
        "PENDING",
        "RESIZING",
        "RUNNING",
        "STAGE_OUT",
        "STOPPED",
        "SUSPENDED",
    }
)
_DEPENDENCY_REASONS = ("DEPENDENCY", "DEPENDENCIES")


class SlurmStatusInspectionError(SlurmLiveOperationError):
    """Raised when SLURM scheduler status cannot be inspected."""

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
class SlurmStatusWarning:
    """Machine-readable scheduler status warning."""

    code: str
    message: str
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class SlurmSchedulerFact:
    """One parsed scheduler status fact for a submitted job."""

    scheduler_job_id: str
    source: str
    state: str
    exit_code: str | None = None
    reason: str | None = None
    raw: Mapping[str, PlainData] = field(default_factory=dict)

    @property
    def normalized_state(self) -> str:
        return _normalize_slurm_state(self.state)

    @property
    def is_final(self) -> bool:
        state = self.normalized_state
        return (
            state in _SLURM_SUCCESS_STATES
            or state in _SLURM_FAILURE_STATES
            or state in _SLURM_CANCELLED_STATES
        )

    @property
    def dependency_blocked(self) -> bool:
        state = self.normalized_state
        reason = "" if self.reason is None else self.reason.upper()
        return state == "DEPENDENCY" or any(item in reason for item in _DEPENDENCY_REASONS)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "scheduler_job_id": self.scheduler_job_id,
            "source": self.source,
            "state": self.state,
            "normalized_state": self.normalized_state,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "raw": dict(self.raw),
        }


@dataclass(frozen=True, slots=True)
class SlurmJobStatusSummary:
    """User-facing status for one submitted SLURM job."""

    logical_key: str
    scheduler_job_id: str
    status: str
    source: str
    scheduler_state: str
    loom_run_status: str | None = None
    loom_stage_status: str | None = None
    stage_name: str | None = None
    exit_code: str | None = None
    dependency_state: str | None = None
    dependency_job_ids: Sequence[str] = ()
    log_paths: Mapping[str, str | None] = field(default_factory=dict)
    backend_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    warnings: Sequence[SlurmStatusWarning] = ()

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "logical_key": self.logical_key,
            "stage_name": self.stage_name,
            "scheduler_job_id": self.scheduler_job_id,
            "status": self.status,
            "source": self.source,
            "scheduler_state": self.scheduler_state,
            "exit_code": self.exit_code,
            "dependency_state": self.dependency_state,
            "dependency_job_ids": list(self.dependency_job_ids),
            "loom_run_status": self.loom_run_status,
            "loom_stage_status": self.loom_stage_status,
            "log_paths": dict(self.log_paths),
            "backend_metadata": dict(self.backend_metadata),
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class SlurmJobsStatusReport:
    """Scheduler-aware status report for the latest SLURM submission."""

    run_uri: str
    run_status: str | None
    submission: Mapping[str, PlainData]
    manifest_path: str
    manifest_relative_path: str
    jobs: Sequence[SlurmJobStatusSummary]
    failed_submissions: Sequence[Mapping[str, PlainData]] = ()
    warnings: Sequence[SlurmStatusWarning] = ()

    @property
    def job_count(self) -> int:
        return len(self.jobs)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "run_status": self.run_status,
            "submission": dict(self.submission),
            "manifest_path": self.manifest_path,
            "manifest_relative_path": self.manifest_relative_path,
            "job_count": self.job_count,
            "jobs": [job.to_dict() for job in self.jobs],
            "failed_submissions": [dict(item) for item in self.failed_submissions],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def default_slurm_status_command_runner() -> SlurmCommandRunner:
    """Return the default command runner for status inspection."""

    return SubprocessSlurmCommandRunner()


def inspect_slurm_job_status(
    run_uri: str,
    *,
    run_store: RunStore | None = None,
    command_runner: SlurmCommandRunner | None = None,
    captured_at: str | None = None,
) -> SlurmJobsStatusReport:
    """Inspect scheduler job status for the latest submitted SLURM operation."""

    store = LocalRunStore() if run_store is None else run_store
    if not isinstance(store, RunStore):
        raise SlurmStatusInspectionError(
            "scheduler status requires a run store",
            code="executor.slurm.status.invalid_run_store",
        )
    if not isinstance(store, LocalRunStorePaths):
        raise SlurmStatusInspectionError(
            "scheduler status requires local run-store path helpers",
            code="executor.slurm.status.missing_local_paths",
        )

    now = captured_at or utc_timestamp()
    state = store.inspect_run_state(run_uri)
    record = _latest_submission(state)
    if record.backend != SLURM_SUBMITTED_BACKEND:
        raise SlurmStatusInspectionError(
            f"latest submitted operation uses unsupported backend: {record.backend}",
            code="executor.slurm.status.unsupported_backend",
            context={
                "backend": record.backend,
                "submission_id": record.submission_id,
            },
        )

    manifest_path = _manifest_path(store, run_uri=run_uri, record=record)
    manifest = _read_live_manifest(manifest_path)
    submitted_jobs = cast(tuple[SlurmSubmittedJob, ...], manifest.submitted_jobs)
    job_ids = tuple(job.scheduler_job_id for job in submitted_jobs)
    runner = command_runner or default_slurm_status_command_runner()

    warnings: list[SlurmStatusWarning] = []
    sacct_facts, sacct_warnings = _query_sacct(runner, job_ids=job_ids)
    squeue_facts, squeue_warnings = _query_squeue(runner, job_ids=job_ids)
    warnings.extend(sacct_warnings)
    warnings.extend(squeue_warnings)

    stage_by_name = {stage.stage_name: stage for stage in state.stage_inspections}
    latest_snapshots = _latest_snapshots_by_job(manifest)
    jobs: list[SlurmJobStatusSummary] = []
    for submitted in submitted_jobs:
        summary = _job_summary(
            submitted,
            state=state,
            stage_by_name=stage_by_name,
            sacct_fact=sacct_facts.get(submitted.scheduler_job_id),
            squeue_fact=squeue_facts.get(submitted.scheduler_job_id),
            snapshot=latest_snapshots.get(submitted.scheduler_job_id),
        )
        jobs.append(summary)

    if not sacct_facts and not squeue_facts and job_ids:
        warnings.append(
            SlurmStatusWarning(
                code="executor.slurm.status.scheduler_state_uncertain",
                message="no current scheduler data was available; using persisted manifest state",
                details={"job_ids": list(job_ids)},
            )
        )

    snapshots = tuple(_snapshot_from_summary(job, captured_at=now) for job in jobs)
    _persist_status_snapshot(
        store=store,
        run_uri=run_uri,
        record=record,
        manifest_path=manifest_path,
        manifest=manifest,
        snapshots=snapshots,
        jobs=jobs,
        warnings=warnings,
        captured_at=now,
    )

    return SlurmJobsStatusReport(
        run_uri=run_uri,
        run_status=None
        if state.run_status is None
        else state.run_status.status.value,
        submission=record.to_summary_dict(),
        manifest_path=str(manifest_path),
        manifest_relative_path=record.manifest_relative_path,
        jobs=tuple(jobs),
        failed_submissions=tuple(
            item.to_dict()
            for item in cast(
                tuple[SlurmFailedSubmission, ...], manifest.failed_submissions
            )
        ),
        warnings=tuple(warnings),
    )


def _latest_submission(state: RunStateInspection) -> SubmittedOperationRecord:
    if not state.submitted_operations:
        raise SlurmStatusInspectionError(
            "run has no submitted operations to inspect",
            code="executor.slurm.status.no_submitted_operation",
            context={"run_uri": state.run_uri},
        )
    return state.submitted_operations[-1]


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
        raise SlurmStatusInspectionError(
            f"failed to read SLURM live manifest: {path}",
            code="executor.slurm.status.manifest_read_error",
            context={"manifest_path": str(path)},
        ) from exc
    return read_slurm_live_manifest(data)


def _query_sacct(
    runner: SlurmCommandRunner, *, job_ids: Sequence[str]
) -> tuple[dict[str, SlurmSchedulerFact], tuple[SlurmStatusWarning, ...]]:
    try:
        result = runner.sacct(job_ids=job_ids)
    except SlurmCommandUnavailableError as exc:
        return {}, (
            SlurmStatusWarning(
                code="executor.slurm.status.sacct_unavailable",
                message="sacct is unavailable; accounting state could not be queried",
                details={"error": str(exc)},
            ),
        )
    except Exception as exc:
        return {}, (
            SlurmStatusWarning(
                code="executor.slurm.status.sacct_error",
                message="sacct failed before returning scheduler status",
                details={"error": str(exc), "error_type": type(exc).__name__},
            ),
        )
    if not result.ok:
        return {}, (
            SlurmStatusWarning(
                code="executor.slurm.status.sacct_nonzero",
                message="sacct returned a nonzero exit status",
                details=_command_details(result),
            ),
        )
    return _parse_sacct_output(result), ()


def _query_squeue(
    runner: SlurmCommandRunner, *, job_ids: Sequence[str]
) -> tuple[dict[str, SlurmSchedulerFact], tuple[SlurmStatusWarning, ...]]:
    try:
        result = runner.squeue(job_ids=job_ids)
    except SlurmCommandUnavailableError as exc:
        return {}, (
            SlurmStatusWarning(
                code="executor.slurm.status.squeue_unavailable",
                message="squeue is unavailable; active queue state could not be queried",
                details={"error": str(exc)},
            ),
        )
    except Exception as exc:
        return {}, (
            SlurmStatusWarning(
                code="executor.slurm.status.squeue_error",
                message="squeue failed before returning scheduler status",
                details={"error": str(exc), "error_type": type(exc).__name__},
            ),
        )
    if not result.ok:
        return {}, (
            SlurmStatusWarning(
                code="executor.slurm.status.squeue_nonzero",
                message="squeue returned a nonzero exit status",
                details=_command_details(result),
            ),
        )
    return _parse_squeue_output(result), ()


def _parse_sacct_output(result: SlurmCommandResult) -> dict[str, SlurmSchedulerFact]:
    facts: dict[str, SlurmSchedulerFact] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        job_id = _root_job_id(parts[0])
        if job_id is None:
            continue
        state = bound_scheduler_output(parts[1], field="sacct.state")
        exit_code = None
        if len(parts) >= 3 and parts[2]:
            exit_code = bound_scheduler_output(parts[2], field="sacct.exit_code")
        fact = SlurmSchedulerFact(
            scheduler_job_id=job_id,
            source="sacct",
            state=state or "UNKNOWN",
            exit_code=exit_code,
            raw={"line": bound_scheduler_output(raw_line, field="sacct.line")},
        )
        existing = facts.get(job_id)
        if existing is None or (fact.is_final and not existing.is_final):
            facts[job_id] = fact
    return facts


def _parse_squeue_output(result: SlurmCommandResult) -> dict[str, SlurmSchedulerFact]:
    facts: dict[str, SlurmSchedulerFact] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            continue
        job_id = _root_job_id(parts[0])
        if job_id is None:
            continue
        state = bound_scheduler_output(parts[1], field="squeue.state") or "UNKNOWN"
        reason = None
        if len(parts) >= 3 and parts[2]:
            reason = bound_scheduler_output(parts[2], field="squeue.reason")
        facts[job_id] = SlurmSchedulerFact(
            scheduler_job_id=job_id,
            source="squeue",
            state=state,
            reason=reason,
            raw={"line": bound_scheduler_output(raw_line, field="squeue.line")},
        )
    return facts


def _root_job_id(value: str) -> str | None:
    candidate = value.strip().split(".", 1)[0].split("_", 1)[0]
    return candidate if candidate.isdecimal() else None


def _latest_snapshots_by_job(
    manifest: SlurmLiveSubmissionManifest,
) -> dict[str, SlurmSchedulerStatusSnapshot]:
    snapshots: dict[str, SlurmSchedulerStatusSnapshot] = {}
    for snapshot in cast(
        tuple[SlurmSchedulerStatusSnapshot, ...], manifest.status_snapshots
    ):
        previous = snapshots.get(snapshot.scheduler_job_id)
        if previous is None or _timestamp_key(snapshot.captured_at) >= _timestamp_key(
            previous.captured_at
        ):
            snapshots[snapshot.scheduler_job_id] = snapshot
    return snapshots


def _timestamp_key(value: str) -> tuple[int, str]:
    try:
        return (1, parse_timestamp(value).isoformat())
    except ValueError:
        return (0, value)


def _job_summary(
    submitted: SlurmSubmittedJob,
    *,
    state: RunStateInspection,
    stage_by_name: Mapping[str, RunStageInspection],
    sacct_fact: SlurmSchedulerFact | None,
    squeue_fact: SlurmSchedulerFact | None,
    snapshot: SlurmSchedulerStatusSnapshot | None,
) -> SlurmJobStatusSummary:
    stage_name = _stage_name_from_logical_key(submitted.logical_key)
    stage = None if stage_name is None else stage_by_name.get(stage_name)
    loom_run_status = None if state.run_status is None else state.run_status.status.value
    loom_stage_status = (
        None if stage is None or stage.status is None else stage.status.status.value
    )
    warnings: list[SlurmStatusWarning] = []
    selected_fact: SlurmSchedulerFact | None = None
    status: str
    source: str

    if sacct_fact is not None and sacct_fact.is_final and squeue_fact is not None:
        warnings.append(
            SlurmStatusWarning(
                code="executor.slurm.status.conflicting_scheduler_state",
                message="sacct reports a final state while squeue still reports the job active",
                details={
                    "scheduler_job_id": submitted.scheduler_job_id,
                    "sacct_state": sacct_fact.state,
                    "squeue_state": squeue_fact.state,
                },
            )
        )

    final_store_status = _final_store_status(
        submitted.logical_key,
        loom_run_status=loom_run_status,
        loom_stage_status=loom_stage_status,
    )
    if final_store_status is not None:
        status = final_store_status
        source = "run_store"
        selected_fact = sacct_fact or squeue_fact or _snapshot_fact(snapshot)
    elif sacct_fact is not None and sacct_fact.is_final:
        status = _status_from_scheduler_fact(sacct_fact)
        source = "sacct"
        selected_fact = sacct_fact
    elif squeue_fact is not None:
        status = _status_from_scheduler_fact(squeue_fact)
        source = "squeue"
        selected_fact = squeue_fact
    elif snapshot is not None:
        selected_fact = cast(SlurmSchedulerFact, _snapshot_fact(snapshot))
        status = _status_from_scheduler_fact(selected_fact)
        source = "snapshot"
        warnings.append(
            SlurmStatusWarning(
                code="executor.slurm.status.stale_snapshot",
                message="using persisted scheduler snapshot because no current scheduler state was available",
                details={
                    "scheduler_job_id": submitted.scheduler_job_id,
                    "captured_at": snapshot.captured_at,
                },
            )
        )
    else:
        status = "SUBMITTED"
        source = "manifest"

    if selected_fact is None:
        scheduler_state = "SUBMITTED"
        exit_code = None
        backend_fact: Mapping[str, PlainData] | None = None
        dependency_state = _dependency_state_from_manifest(submitted)
    else:
        scheduler_state = selected_fact.normalized_state
        exit_code = selected_fact.exit_code
        backend_fact = selected_fact.to_dict()
        dependency_state = _dependency_state_from_fact(selected_fact, submitted)

    if _worker_never_started(status, loom_stage_status):
        warnings.append(
            SlurmStatusWarning(
                code="executor.slurm.status.worker_never_started",
                message="scheduler reported a terminal job outcome before the Loom stage worker finalized the stage",
                details={
                    "logical_key": submitted.logical_key,
                    "stage_name": stage_name,
                    "scheduler_job_id": submitted.scheduler_job_id,
                    "loom_stage_status": loom_stage_status,
                    "scheduler_state": scheduler_state,
                },
            )
        )

    if source == "manifest":
        warnings.append(
            SlurmStatusWarning(
                code="executor.slurm.status.job_state_uncertain",
                message="job status is based only on persisted submission data",
                details={"scheduler_job_id": submitted.scheduler_job_id},
            )
        )

    backend_metadata = _plain_mapping(
        {
            "selected_source": source,
            "scheduler_fact": backend_fact,
            "sacct": None if sacct_fact is None else sacct_fact.to_dict(),
            "squeue": None if squeue_fact is None else squeue_fact.to_dict(),
        },
        path="backend_metadata",
    )
    return SlurmJobStatusSummary(
        logical_key=submitted.logical_key,
        stage_name=stage_name,
        scheduler_job_id=submitted.scheduler_job_id,
        status=status,
        source=source,
        scheduler_state=scheduler_state,
        exit_code=exit_code,
        dependency_state=dependency_state,
        dependency_job_ids=tuple(submitted.dependency_job_ids),
        loom_run_status=loom_run_status,
        loom_stage_status=loom_stage_status,
        log_paths={
            "stdout_relative_path": submitted.stdout_relative_path,
            "stderr_relative_path": submitted.stderr_relative_path,
        },
        backend_metadata=backend_metadata,
        warnings=tuple(warnings),
    )


def _stage_name_from_logical_key(logical_key: str) -> str | None:
    prefix = "stage:"
    return logical_key[len(prefix) :] if logical_key.startswith(prefix) else None


def _final_store_status(
    logical_key: str,
    *,
    loom_run_status: str | None,
    loom_stage_status: str | None,
) -> str | None:
    if logical_key == "pipeline" and loom_run_status in _FINAL_RUN_STATUS:
        return _status_from_loom_status(loom_run_status)
    if loom_stage_status in _FINAL_STAGE_STATUS:
        return _status_from_loom_status(loom_stage_status)
    return None


def _status_from_loom_status(status: str | None) -> str:
    if status == "SUCCEEDED":
        return "SUCCEEDED"
    if status == "CANCELLED":
        return "CANCELLED"
    if status == "SKIPPED":
        return "SKIPPED"
    if status in {"FAILED", "INTERRUPTED"}:
        return "FAILED"
    return "UNKNOWN"


def _snapshot_fact(
    snapshot: SlurmSchedulerStatusSnapshot | None,
) -> SlurmSchedulerFact | None:
    if snapshot is None:
        return None
    return SlurmSchedulerFact(
        scheduler_job_id=snapshot.scheduler_job_id,
        source=snapshot.source,
        state=snapshot.state,
        exit_code=snapshot.exit_code,
        raw={"snapshot": snapshot.to_dict()},
    )


def _status_from_scheduler_fact(fact: SlurmSchedulerFact) -> str:
    if fact.dependency_blocked:
        return "DEPENDENCY_BLOCKED"
    state = fact.normalized_state
    if state in _SLURM_SUCCESS_STATES:
        return "SUCCEEDED"
    if state in _SLURM_CANCELLED_STATES:
        return "CANCELLED"
    if state in _SLURM_FAILURE_STATES:
        return "FAILED"
    if state == "RUNNING":
        return "RUNNING"
    if state in _SLURM_ACTIVE_STATES:
        return "SUBMITTED"
    return "UNKNOWN"


def _normalize_slurm_state(value: str) -> str:
    state = value.strip().upper().split()[0].replace(" ", "_")
    return state.split("+", 1)[0] if "+" in state else state


def _dependency_state_from_fact(
    fact: SlurmSchedulerFact, submitted: SlurmSubmittedJob
) -> str | None:
    if fact.dependency_blocked:
        return "BLOCKED"
    if submitted.dependency_job_ids and fact.normalized_state in {"PENDING", "SUBMITTED"}:
        return "WAITING"
    if submitted.dependency_job_ids:
        return "RELEASED"
    return None


def _dependency_state_from_manifest(submitted: SlurmSubmittedJob) -> str | None:
    return "WAITING" if submitted.dependency_job_ids else None


def _worker_never_started(status: str, loom_stage_status: str | None) -> bool:
    return loom_stage_status == "SUBMITTED" and status in {
        "CANCELLED",
        "DEPENDENCY_BLOCKED",
        "FAILED",
    }


def _snapshot_from_summary(
    summary: SlurmJobStatusSummary, *, captured_at: str
) -> SlurmSchedulerStatusSnapshot:
    return SlurmSchedulerStatusSnapshot(
        logical_key=summary.logical_key,
        scheduler_job_id=summary.scheduler_job_id,
        captured_at=captured_at,
        source=summary.source,
        state=summary.scheduler_state,
        exit_code=summary.exit_code,
        details=_plain_mapping(
            {
                "status": summary.status,
                "dependency_state": summary.dependency_state,
                "loom_run_status": summary.loom_run_status,
                "loom_stage_status": summary.loom_stage_status,
                "warnings": [warning.to_dict() for warning in summary.warnings],
            },
            path="snapshot.details",
        ),
    )


def _persist_status_snapshot(
    *,
    store: RunStore,
    run_uri: str,
    record: SubmittedOperationRecord,
    manifest_path: Path,
    manifest: SlurmLiveSubmissionManifest,
    snapshots: Sequence[SlurmSchedulerStatusSnapshot],
    jobs: Sequence[SlurmJobStatusSummary],
    warnings: Sequence[SlurmStatusWarning],
    captured_at: str,
) -> None:
    updated_manifest = replace(
        manifest,
        updated_at=captured_at,
        status_snapshots=tuple(manifest.status_snapshots) + tuple(snapshots),
    )
    write_slurm_live_manifest(manifest_path, updated_manifest)
    backend_metadata = dict(record.backend_metadata)
    backend_metadata["slurm_status"] = _plain_mapping(
        {
            "captured_at": captured_at,
            "job_count": len(jobs),
            "jobs": [
                {
                    "logical_key": job.logical_key,
                    "scheduler_job_id": job.scheduler_job_id,
                    "status": job.status,
                    "source": job.source,
                    "scheduler_state": job.scheduler_state,
                    "exit_code": job.exit_code,
                }
                for job in jobs
            ],
            "warnings": [warning.to_dict() for warning in warnings],
        },
        path="submitted_operation.backend_metadata.slurm_status",
    )
    store.write_submitted_operation(
        run_uri,
        replace(record, updated_at=captured_at, backend_metadata=backend_metadata),
    )


def _command_details(result: SlurmCommandResult) -> dict[str, PlainData]:
    return {
        "command": result.command,
        "argv": list(result.argv),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _plain_mapping(value: object, *, path: str) -> dict[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=path)
    except PlainDataError as exc:
        raise SlurmStatusInspectionError(
            f"{path} must be plain-data-compatible",
            code="executor.slurm.status.invalid_plain_data",
            context={"error": str(exc)},
        ) from exc
    if not isinstance(normalized, dict):
        raise SlurmStatusInspectionError(
            f"{path} must be a mapping",
            code="executor.slurm.status.invalid_plain_data",
        )
    return normalized


__all__ = [
    "SlurmJobsStatusReport",
    "SlurmJobStatusSummary",
    "SlurmSchedulerFact",
    "SlurmStatusInspectionError",
    "SlurmStatusWarning",
    "default_slurm_status_command_runner",
    "inspect_slurm_job_status",
]
