"""Independent, failure-retaining collectors for the Loom monitor."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from loom.timestamps import utc_now

from .models import (
    ActiveAttempt,
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
        self._run_inspector = run_inspector or _default_run_inspector
        self._jobs_inspector = jobs_inspector or _default_jobs_inspector
        self._logs_inspector = logs_inspector or _default_logs_inspector
        self._authority_probe = authority_probe or _default_authority_probe
        self._run_store = run_store
        self._run_store_factory = run_store_factory or _default_run_store
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
        """Load one trusted queue config and open its durable repository."""

        from loom.queue import QueueService, load_queue_spec

        path = Path(config_path).expanduser().resolve()
        spec = load_queue_spec(path)
        service = QueueService.from_spec(spec)
        service.start()
        workspace_name = _workspace_name(path, spec.metadata)
        return cls(
            config_path=path,
            service=service,
            workspace_name=workspace_name,
            clock=clock,
        )

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
                data = _project_run(summary)
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
            inspection = self.service.inspect_item(queue_item_id)
            item = inspection.item
            if item is None:
                raise ValueError(f"queue item no longer exists: {queue_item_id}")
            audit_events = tuple(
                _queue_event(event) for event in inspection.audit_events
            )
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
            data = _project_jobs(report)
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
        from loom.queue.status import build_queue_pool_status

        service_status = self.service.status()
        recovery = {
            record.queue_item_id: record for record in service_status.recovery_records
        }
        pool_modes = {
            pool.pool_name: pool.mode.value for pool in self.service.spec.pools
        }
        pools: list[PoolRecord] = []
        items: list[QueueRecord] = []
        for configured_pool in self.service.spec.pools:
            pool_name = configured_pool.pool_name
            status = build_queue_pool_status(self.service, pool_name=pool_name)
            snapshot = self.service.read_pool_snapshot(pool_name)
            active = {
                attempt.queue_item_id: attempt for attempt in status.active_attempts
            }
            queued_times = [
                item.enqueued_at
                for item in snapshot.items
                if item.status.value == "QUEUED"
            ]
            pool_recovery = sum(
                record.queue_item_id in {item.queue_item_id for item in snapshot.items}
                for record in recovery.values()
            )
            pools.append(
                PoolRecord(
                    pool_name=pool_name,
                    mode=configured_pool.mode.value,
                    controller_limit=status.controller_max_active_items,
                    queued=status.counts.queued,
                    claimed=status.counts.claimed,
                    dispatched=status.counts.dispatched,
                    succeeded=status.counts.succeeded,
                    failed=status.counts.failed,
                    cancelled=status.counts.cancelled,
                    unknown=status.counts.unknown,
                    oldest_queued_at=min(queued_times) if queued_times else None,
                    recovery_count=pool_recovery,
                )
            )
            items.extend(
                _project_queue_item(
                    item,
                    pool_mode=pool_modes[pool_name],
                    active_attempt=active.get(item.queue_item_id),
                    recovery_record=recovery.get(item.queue_item_id),
                )
                for item in snapshot.items
            )
        return QueueData(
            workspace_name=self.workspace_name,
            pools=tuple(pools),
            items=tuple(items),
        )


def _project_queue_item(
    item: Any,
    *,
    pool_mode: str,
    active_attempt: Any | None,
    recovery_record: Any | None,
) -> QueueRecord:
    claim = item.claim
    handle = item.dispatch_handle
    cancellation = item.cancellation
    attempt = None
    if active_attempt is not None:
        attempt = ActiveAttempt(
            queue_item_id=active_attempt.queue_item_id,
            owner_id=active_attempt.owner_id,
            session_id=active_attempt.session_id,
            evidence_source=active_attempt.evidence_source,
            live_observation=active_attempt.live_observation,
            process=active_attempt.process,
            assignment=active_attempt.assignment,
            logs=active_attempt.logs,
        )
    return QueueRecord(
        queue_item_id=item.queue_item_id,
        queue_name=item.queue_name,
        pool_name=item.pool_name,
        pool_mode=pool_mode,
        run_uri=item.run_uri,
        status=item.status.value,
        enqueued_at=item.enqueued_at,
        updated_at=item.updated_at,
        dispatch_attempt=item.dispatch_attempt,
        requested_resources=dict(item.launch_contract.resources),
        tags=dict(item.run_intent.tags),
        claim_owner=None if claim is None else claim.owner_id,
        claimed_at=None if claim is None else claim.claimed_at,
        adapter=item.launch_contract.adapter,
        dispatch_handle_id=None if handle is None else handle.handle_id,
        dispatched_at=None if handle is None else handle.dispatched_at,
        cancellation_requested_at=(
            None if cancellation is None else cancellation.requested_at
        ),
        cancellation_requested_by=(
            None if cancellation is None else cancellation.requested_by
        ),
        cancellation_reason=None if cancellation is None else cancellation.reason,
        active_attempt=attempt,
        recovery_detail=None if recovery_record is None else recovery_record.detail,
    )


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


def _queue_event(event: Any) -> TimelineEntry:
    detail = _safe_event_detail(event.detail)
    summary = event.event_type.replace("_", " ")
    if detail:
        summary = f"{summary} · {detail}"
    return TimelineEntry(
        occurred_at=event.timestamp,
        source="QUEUE",
        event_type=event.event_type,
        summary=summary,
        sequence=event.sequence,
        warning=any(
            word in event.event_type.lower() for word in ("fail", "cancel", "defer")
        ),
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


def _workspace_name(path: Path, metadata: Mapping[str, Any]) -> str:
    for key in ("workspace_id", "workspace", "project", "name"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return path.parent.name or path.stem


def _default_run_inspector(run_uri: str, *, run_store: Any) -> Any:
    from loom.diagnostics.inspection import inspect_run_status

    return inspect_run_status(run_uri, run_store=run_store)


def _default_jobs_inspector(run_uri: str, *, run_store: Any) -> Any:
    from loom.pipeline.executors.slurm.status import inspect_slurm_job_status

    return inspect_slurm_job_status(run_uri, run_store=run_store)


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
    from loom.pipeline.execution import create_authority_backed_serial_run_store
    from loom.pipeline.stores import authority_config_from_env

    return create_authority_backed_serial_run_store(
        "runs",
        authority_config=authority_config_from_env(),
        workspace_root=Path.cwd(),
        owner_id="loom-monitor",
    )


def _default_authority_probe() -> AuthorityData:
    from loom.pipeline.stores import authority_config_from_env
    from loom.pipeline.stores.authority_factory import resolve_authority_for_factory

    config = authority_config_from_env()
    resolution = resolve_authority_for_factory(
        config,
        workspace_root=Path.cwd(),
        readiness_timeout_seconds=2.0,
    )
    readiness = resolution.readiness
    if readiness is not None:
        if not readiness.ready:
            diagnostics = "; ".join(
                diagnostic.message for diagnostic in readiness.diagnostics
            )
            raise RuntimeError(diagnostics or readiness.readiness.value)
        return AuthorityData(
            state="READY",
            workspace_id=readiness.workspace_id,
            service_generation=readiness.service_generation,
        )
    if resolution.reference is None:
        registry_record = (
            None if resolution.registry is None else resolution.registry.record
        )
        if config.endpoint is not None or registry_record is not None:
            diagnostics = "; ".join(
                diagnostic.message for diagnostic in resolution.result.diagnostics
            )
            raise RuntimeError(diagnostics or "authority readiness was unavailable")
        return AuthorityData(
            state="UNOBSERVED",
            message="no authority endpoint or live registry reference was found",
            workspace_id=config.workspace_id,
        )
    diagnostics = "; ".join(
        diagnostic.message for diagnostic in resolution.result.diagnostics
    )
    raise RuntimeError(diagnostics or "authority readiness was unavailable")


__all__ = ["MonitorCollector"]
