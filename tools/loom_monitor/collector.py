"""Independent, failure-retaining collectors for the Loom monitor."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from loom.timestamps import utc_now

from .models import (
    AuthorityData,
    JobRecord,
    JobsData,
    LogsData,
    LogStreamRecord,
    MonitorSnapshot,
    Observation,
    PoolRecord,
    QueueData,
    QueueRecord,
    RunRecord,
    SelectedData,
    StageRecord,
    SubmittedOperationRecord,
    TimelineEntry,
)
from .presenter import one_line


Clock = Callable[[], datetime]


class MonitorCollector:
    """Collect queue, authority, scheduler, and log evidence independently."""

    def __init__(
        self,
        *,
        config_path: Path,
        service: Any,
        workspace_name: str,
        clock: Clock = utc_now,
        run_inspector: Callable[..., Any] | None = None,
        jobs_inspector: Callable[..., Any] | None = None,
        logs_inspector: Callable[..., Any] | None = None,
        authority_probe: Callable[[], AuthorityData] | None = None,
        run_store: Any | None = None,
        run_store_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config_path = config_path
        self.service = service
        self.workspace_name = workspace_name
        self._clock = clock
        self._run_inspector = run_inspector or self._native_run_inspector
        self._jobs_inspector = jobs_inspector or self._native_jobs_inspector
        self._logs_inspector = logs_inspector or _default_logs_inspector
        self._authority_probe = authority_probe or self._native_health
        self._run_store = run_store
        self._run_store_factory = run_store_factory or _default_run_store
        self._admissions: dict[str, Any] = {}
        self._lock = RLock()
        self._queue: Observation[QueueData] = Observation(source="queue")
        self._authority: Observation[AuthorityData] = Observation(source="authority")
        self._runs: dict[str, Observation[RunRecord]] = {}
        self._selected: Observation[SelectedData] = Observation(source="selected")
        self._jobs: Observation[JobsData] = Observation(source="scheduler")
        self._logs: Observation[LogsData] = Observation(source="logs")

    @classmethod
    def from_config(
        cls,
        config_path: str | Path,
        *,
        clock: Clock = utc_now,
    ) -> "MonitorCollector":
        """Attach read-only to a protected coordinator connection or local socket."""
        from loom.coordinator import CoordinatorClient

        path = Path(config_path).expanduser().resolve()
        service = (
            CoordinatorClient.from_unix_socket(path)
            if path.is_socket()
            else CoordinatorClient.from_connection_file(path)
        )
        return cls(
            config_path=path, service=service, workspace_name=path.stem, clock=clock
        )

    def close(self) -> None:
        """Release client IO without cancelling coordinator work."""
        self.service.close()

    def snapshot(self) -> MonitorSnapshot:
        with self._lock:
            return MonitorSnapshot(
                queue=self._queue,
                authority=self._authority,
                runs=dict(self._runs),
                selected=self._selected,
                jobs=self._jobs,
                logs=self._logs,
            )

    def now(self) -> datetime:
        """Return the collector clock for consistent presentation ages."""

        return self._clock()

    def refresh_queue(self) -> MonitorSnapshot:
        with self._lock:
            self._queue = self._queue.refreshing_now()
        try:
            data = self._read_queue()
        except Exception as exc:  # each source retains its prior successful value
            with self._lock:
                self._queue = self._queue.failed(exc, at=self._clock())
        else:
            with self._lock:
                self._queue = self._queue.succeeded(data, at=self._clock())
        return self.snapshot()

    def refresh_authority(self) -> MonitorSnapshot:
        with self._lock:
            self._authority = self._authority.refreshing_now()
        try:
            data = self._authority_probe()
        except Exception as exc:
            with self._lock:
                self._authority = self._authority.failed(exc, at=self._clock())
        else:
            with self._lock:
                self._authority = self._authority.succeeded(data, at=self._clock())
        return self.snapshot()

    def refresh_runs(self, run_uris: Iterable[str]) -> MonitorSnapshot:
        for run_uri in dict.fromkeys(run_uris):
            with self._lock:
                previous = self._runs.get(run_uri, Observation(source="authority/run"))
                self._runs[run_uri] = previous.refreshing_now()
            try:
                summary = self._run_inspector(
                    run_uri,
                    run_store=self._get_run_store(),
                )
                data = (
                    summary if isinstance(summary, RunRecord) else _project_run(summary)
                )
            except Exception as exc:
                with self._lock:
                    self._runs[run_uri] = self._runs[run_uri].failed(
                        exc, at=self._clock()
                    )
            else:
                with self._lock:
                    self._runs[run_uri] = self._runs[run_uri].succeeded(
                        data, at=self._clock()
                    )
        return self.snapshot()

    def refresh_selected(self, queue_item_id: str) -> MonitorSnapshot:
        with self._lock:
            self._selected = self._selected.refreshing_now()
        try:
            item = self.service.admission_for_queue_item(queue_item_id)
            # The native query does not claim to export coordinator audit history.
            audit_events: tuple[TimelineEntry, ...] = ()
            run_events: tuple[TimelineEntry, ...] = ()
            run_events_error = None
            try:
                run_events = tuple(
                    _run_event(event)
                    for event in self._get_run_store().read_events(item.run_uri)
                )
            except Exception as exc:
                run_events_error = one_line(str(exc))
            data = SelectedData(
                queue_item_id=queue_item_id,
                audit_events=audit_events,
                run_events=run_events,
                run_events_error=run_events_error,
            )
        except Exception as exc:
            with self._lock:
                self._selected = self._selected.failed(exc, at=self._clock())
        else:
            with self._lock:
                self._selected = self._selected.succeeded(data, at=self._clock())
        return self.snapshot()

    def refresh_jobs(self, run_uri: str) -> MonitorSnapshot:
        with self._lock:
            self._jobs = self._jobs.refreshing_now()
        try:
            report = self._jobs_inspector(
                run_uri,
                run_store=self._get_run_store(),
            )
            data = report if isinstance(report, JobsData) else _project_jobs(report)
        except Exception as exc:
            with self._lock:
                self._jobs = self._jobs.failed(exc, at=self._clock())
        else:
            with self._lock:
                self._jobs = self._jobs.succeeded(data, at=self._clock())
        return self.snapshot()

    def refresh_logs(
        self,
        run_uri: str,
        stage_name: str,
        *,
        tail: int = 100,
    ) -> MonitorSnapshot:
        with self._lock:
            self._logs = self._logs.refreshing_now()
        try:
            try:
                summary = self._logs_inspector(
                    run_uri,
                    stage_name,
                    tail=tail,
                    run_store=self._get_run_store(),
                )
                unavailable_reason = None
            except Exception as content_error:
                summary = self._logs_inspector(
                    run_uri,
                    stage_name,
                    tail=tail,
                    paths_only=True,
                    run_store=self._get_run_store(),
                )
                unavailable_reason = one_line(str(content_error))
            data = _project_logs(summary, unavailable_reason=unavailable_reason)
        except Exception as exc:
            with self._lock:
                self._logs = self._logs.failed(exc, at=self._clock())
        else:
            with self._lock:
                self._logs = self._logs.succeeded(data, at=self._clock())
        return self.snapshot()

    def _get_run_store(self) -> Any:
        with self._lock:
            if self._run_store is not None:
                return self._run_store
        created = self._run_store_factory()
        with self._lock:
            if self._run_store is None:
                self._run_store = created
            return self._run_store

    def _read_queue(self) -> QueueData:
        status = self.service.status()
        admissions = []
        cursor = None
        while True:
            page = self.service.admissions(limit=100, cursor=cursor)
            admissions.extend(page.admissions)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        self._admissions = {item.queue_item_id: item for item in admissions}
        items = tuple(
            QueueRecord(
                queue_item_id=item.queue_item_id,
                queue_name="admissions",
                pool_name=status.coordinator_id,
                pool_mode="native",
                run_uri=item.run_uri,
                status=item.state.value,
                enqueued_at=item.accepted_at,
                updated_at=item.accepted_at,
                dispatch_attempt=0,
                claim_owner=item.coordinator_id,
                recovery_detail=None
                if item.blocked_reason is None
                else {"reason": item.blocked_reason},
            )
            for item in admissions
        )
        counts = {
            state: sum(item.status == state for item in items)
            for state in (
                "WAITING",
                "ACTIVE",
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "BLOCKED",
            )
        }
        pool = PoolRecord(
            pool_name=status.coordinator_id,
            mode="native",
            controller_limit=None,
            queued=counts["WAITING"],
            claimed=0,
            dispatched=counts["ACTIVE"],
            succeeded=counts["SUCCEEDED"],
            failed=counts["FAILED"],
            cancelled=counts["CANCELLED"],
            unknown=counts["BLOCKED"],
            oldest_queued_at=min(
                (item.enqueued_at for item in items if item.status == "WAITING"),
                default=None,
            ),
        )
        return QueueData(workspace_name=self.workspace_name, pools=(pool,), items=items)

    def _detail_for_run(self, run_uri: str):
        found = next(
            (item for item in self._admissions.values() if item.run_uri == run_uri),
            None,
        )
        if found is None:
            self._read_queue()
            found = next(
                (item for item in self._admissions.values() if item.run_uri == run_uri),
                None,
            )
        if found is None:
            raise LookupError("run is not present in coordinator admissions")
        return self.service.admission(found.admission_id)

    def _native_health(self) -> AuthorityData:
        status = self.service.status()
        return AuthorityData(
            state=status.service_health, message=status.service_diagnostic
        )

    def _native_run_inspector(self, run_uri: str, *, run_store: Any) -> RunRecord:
        del run_store
        detail = self._detail_for_run(run_uri)
        facts = detail.authority
        if facts.get("availability") != "available":
            raise RuntimeError(str(facts.get("diagnostic", "authority unavailable")))
        artifacts = facts.get("artifacts", {})
        attempts = {
            item["stage_name"]: item["attempt"] for item in facts.get("attempts", ())
        }
        reasons = facts.get("stage_reasons", {})
        source = {"owner": "per-run-authority", "authoritative": True}
        stages = tuple(
            StageRecord(
                stage_name=name,
                status=str(state),
                attempt=attempts.get(name),
                message=reasons.get(name, {}).get("message"),
                failure=None,
                input_count=None,
                output_count=sum(str(key).startswith(name + ".") for key in artifacts),
                log_paths={},
                log_available={},
                state_source=source,
                log_source={"owner": "local-materialization"},
            )
            for name, state in facts.get("stages", {}).items()
        )
        return RunRecord(
            run_uri=run_uri,
            status=str(facts["state"]),
            message=None,
            artifact_count=len(artifacts),
            state_source=source,
            stages=stages,
            submitted_operations=(),
        )

    def _native_jobs_inspector(self, run_uri: str, *, run_store: Any) -> JobsData:
        del run_store
        detail = self._detail_for_run(run_uri)
        owner = detail.owners.get("slurm", {})
        if owner.get("availability") != "available":
            raise RuntimeError(str(owner.get("diagnostic", "SLURM owner unavailable")))
        jobs = []
        for assignment in owner.get("assignments", ()):
            submission = assignment.get("submission", {})
            job_id = assignment.get("job_id")
            if job_id is None:
                continue
            jobs.append(
                JobRecord(
                    logical_key=assignment["assignment_id"],
                    stage_name=assignment.get("stage_name"),
                    scheduler_job_id=job_id,
                    status=assignment["state"],
                    source="agent-observation",
                    scheduler_state=submission.get("scheduler_state") or "UNKNOWN",
                    loom_run_status=detail.authority.get("state"),
                    loom_stage_status=assignment.get("loom_result_status"),
                    exit_code=None,
                    dependency_state=None,
                    dependency_job_ids=(),
                    log_paths={},
                    warnings=(),
                )
            )
        return JobsData(run_uri=run_uri, jobs=tuple(jobs))


def _project_run(summary: Any) -> RunRecord:
    stages = tuple(
        StageRecord(
            stage_name=stage.stage_name,
            status=stage.status,
            attempt=stage.attempt,
            message=stage.message,
            failure=stage.failure,
            input_count=stage.input_count,
            output_count=stage.output_count,
            log_paths=dict(stage.log_paths),
            log_available=dict(stage.log_available),
            state_source=dict(stage.state_source),
            log_source=dict(stage.log_source),
            reliability_warning_count=(
                0 if stage.reliability is None else len(stage.reliability.diagnostics)
            ),
        )
        for stage in summary.stages
    )
    operations = tuple(
        SubmittedOperationRecord(
            submission_id=operation.submission_id,
            backend=operation.backend,
            mode=operation.mode,
            state=operation.state,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            active=operation.active,
        )
        for operation in summary.submitted_operations
    )
    return RunRecord(
        run_uri=summary.run_uri,
        status=summary.status,
        message=summary.message,
        artifact_count=summary.artifact_count,
        state_source=dict(summary.state_source),
        stages=stages,
        submitted_operations=operations,
    )


def _project_jobs(report: Any) -> JobsData:
    submission_id = report.submission.get("submission_id")
    submission_state = report.submission.get("state")
    return JobsData(
        run_uri=report.run_uri,
        jobs=tuple(
            JobRecord(
                logical_key=job.logical_key,
                stage_name=job.stage_name,
                scheduler_job_id=job.scheduler_job_id,
                status=job.status,
                source=job.source,
                scheduler_state=job.scheduler_state,
                loom_run_status=job.loom_run_status,
                loom_stage_status=job.loom_stage_status,
                exit_code=job.exit_code,
                dependency_state=job.dependency_state,
                dependency_job_ids=tuple(job.dependency_job_ids),
                log_paths=dict(job.log_paths),
                warnings=tuple(warning.message for warning in job.warnings),
            )
            for job in report.jobs
        ),
        submission_id=submission_id if isinstance(submission_id, str) else None,
        submission_state=(
            submission_state if isinstance(submission_state, str) else None
        ),
        warnings=tuple(warning.message for warning in report.warnings),
        failed_submission_count=len(report.failed_submissions),
    )


def _project_logs(summary: Any, *, unavailable_reason: str | None) -> LogsData:
    return LogsData(
        run_uri=summary.run_uri,
        stage_name=summary.stage_name,
        streams=tuple(
            LogStreamRecord(
                stream=stream.stream,
                path=stream.path,
                available=stream.available,
                content=stream.content,
                line_count=stream.line_count,
                displayed_line_count=stream.displayed_line_count,
                truncated=stream.truncated,
                state_source=dict(stream.state_source),
            )
            for stream in summary.streams
        ),
        unavailable_reason=unavailable_reason,
    )


def _run_event(event: Any) -> TimelineEntry:
    stage_name = getattr(event.scope, "stage_name", None)
    detail = _safe_event_detail(event.payload)
    summary = event.event_type.replace("_", " ")
    if stage_name:
        summary = f"{summary} · {stage_name}"
    if detail:
        summary = f"{summary} · {detail}"
    return TimelineEntry(
        occurred_at=event.occurred_at,
        source="AUTHORITY",
        event_type=event.event_type,
        summary=summary,
        stage_name=stage_name,
        sequence=event.sequence,
        warning=any(
            word in event.event_type.lower()
            for word in ("fail", "cancel", "interrupt", "block")
        ),
    )


def _safe_event_detail(detail: Mapping[str, Any]) -> str:
    allowed = (
        "reason_code",
        "reason",
        "message",
        "status",
        "owner_id",
        "adapter",
        "handle_id",
    )
    values: list[str] = []
    for key in allowed:
        value = detail.get(key)
        if isinstance(value, (str, int, float, bool)):
            values.append(f"{key}={one_line(str(value), limit=50)}")
    return " ".join(values)


def _default_logs_inspector(
    run_uri: str,
    stage_name: str,
    *,
    run_store: Any,
    tail: int,
    paths_only: bool = False,
) -> Any:
    from loom.diagnostics.inspection import inspect_stage_logs

    return inspect_stage_logs(
        run_uri,
        stage_name,
        tail=tail,
        paths_only=paths_only,
        run_store=run_store,
    )


def _default_run_store() -> Any:
    from loom.pipeline.stores import LocalRunStore

    return LocalRunStore()
