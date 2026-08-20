"""Pure correlation and formatting rules for the Loom monitor."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from loom.timestamps import parse_timestamp

from .models import (
    AttentionKind,
    AttentionRecord,
    JobRecord,
    MonitorSnapshot,
    MonitorView,
    Observation,
    QueueRecord,
    RunRecord,
    StageRecord,
    TimelineEntry,
    WorkRecord,
)


ACTIVE_QUEUE_STATUSES = frozenset({"CLAIMED", "DISPATCHED"})
TERMINAL_QUEUE_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"})
FAILED_RUN_STATUSES = frozenset({"FAILED", "INTERRUPTED"})
TERMINAL_RUN_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"})
FAILED_STAGE_STATUSES = frozenset({"FAILED", "BLOCKED"})
ACTIVE_STAGE_STATUSES = frozenset({"RUNNING", "SUBMITTED"})
SETTLED_STAGE_STATUSES = frozenset(
    {"SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED", "CANCELLED"}
)
TERMINAL_JOB_STATUSES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMEOUT",
        "PREEMPTED",
        "OUT_OF_MEMORY",
        "NODE_FAIL",
        "BOOT_FAIL",
        "DEADLINE",
        "REVOKED",
        "SPECIAL_EXIT",
    }
)


def display_run_name(run_uri: str, *, width: int = 24) -> str:
    """Return a compact run label without discarding the underlying URI."""

    candidate = run_uri.rstrip("/").rsplit("/", maxsplit=1)[-1] or run_uri
    if len(candidate) <= width:
        return candidate
    return f"…{candidate[-(width - 1) :]}"


def format_age(timestamp: str | datetime | None, *, now: datetime) -> str:
    """Format a compact non-negative age for a Loom timestamp."""

    if timestamp is None:
        return "—"
    try:
        value = parse_timestamp(timestamp) if isinstance(timestamp, str) else timestamp
        seconds = max(0, int((now.astimezone(timezone.utc) - value).total_seconds()))
    except (TypeError, ValueError):
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s" if minutes < 10 else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def format_duration(start: str | None, end: str | datetime | None) -> str:
    """Format a bounded elapsed duration between two Loom timestamps."""

    if start is None or end is None:
        return "—"
    try:
        start_at = parse_timestamp(start)
        end_at = parse_timestamp(end) if isinstance(end, str) else end
        seconds = max(0, int((end_at - start_at).total_seconds()))
    except (TypeError, ValueError):
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s" if minutes < 10 else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def observation_age(observation: Observation[Any], *, now: datetime) -> str:
    return format_age(observation.last_success_at, now=now)


def source_indicator(
    observation: Observation[Any],
    *,
    now: datetime,
    ready: str,
    unavailable: str,
) -> str:
    """Render truthful source health while retaining stale observations."""

    if observation.refreshing:
        return f"{ready} REFRESHING"
    if observation.error is not None:
        if observation.value is not None:
            return (
                f"{ready} STALE {observation_age(observation, now=now)}"
                f" — {one_line(observation.error)}"
            )
        return f"{ready} {unavailable} — {one_line(observation.error)}"
    if observation.value is None:
        return f"{ready} {unavailable}"
    return f"{ready} {observation_age(observation, now=now)}"


def build_work_records(snapshot: MonitorSnapshot) -> tuple[WorkRecord, ...]:
    """Correlate queue-owned and authority-owned facts without merging owners."""

    queue = snapshot.queue.value
    if queue is None:
        return ()
    records: list[WorkRecord] = []
    for item in queue.items:
        run_observation = snapshot.runs.get(item.run_uri)
        run = None if run_observation is None else run_observation.value
        current = current_stage(run)
        divergent = states_divergent(item.status, None if run is None else run.status)
        attention = attention_for_item(
            item,
            run_observation=run_observation,
            divergent=divergent,
        )
        jobs = snapshot.jobs.value
        if jobs is not None and jobs.run_uri == item.run_uri:
            scheduler_attention: list[AttentionRecord] = []
            if jobs.warnings or any(job.warnings for job in jobs.jobs):
                scheduler_attention.append(
                    AttentionRecord(
                        kind=AttentionKind.UNCERTAIN,
                        subject=item.queue_item_id,
                        message="scheduler status includes warnings",
                        queue_item_id=item.queue_item_id,
                    )
                )
            if any(job.dependency_state for job in jobs.jobs):
                scheduler_attention.append(
                    AttentionRecord(
                        kind=AttentionKind.WAITING,
                        subject=item.queue_item_id,
                        message="scheduler dependency is blocking submitted work",
                        queue_item_id=item.queue_item_id,
                    )
                )
            attention = (*attention, *scheduler_attention)
        records.append(
            WorkRecord(
                item=item,
                run=run,
                run_observation=run_observation,
                current_stage=None if current is None else current.stage_name,
                execution=execution_label(item),
                evidence=evidence_label(
                    snapshot.queue,
                    run_observation=run_observation,
                    divergent=divergent,
                ),
                divergent=divergent,
                attention=attention,
            )
        )
    return tuple(sorted(records, key=work_sort_key))


def current_stage(run: RunRecord | None) -> StageRecord | None:
    if run is None:
        return None
    for statuses in (
        FAILED_STAGE_STATUSES,
        ACTIVE_STAGE_STATUSES,
        {"PENDING", "STALE"},
    ):
        match = next((stage for stage in run.stages if stage.status in statuses), None)
        if match is not None:
            return match
    return run.stages[-1] if run.stages else None


def states_divergent(queue_status: str, run_status: str | None) -> bool:
    """Detect actionable lifecycle disagreement without inventing a true state."""

    if run_status is None:
        return False
    if queue_status in ACTIVE_QUEUE_STATUSES and run_status in TERMINAL_RUN_STATUSES:
        return True
    expected_terminal = {
        "SUCCEEDED": {"SUCCEEDED"},
        "FAILED": {"FAILED", "INTERRUPTED"},
        "CANCELLED": {"CANCELLED"},
    }
    allowed = expected_terminal.get(queue_status)
    return allowed is not None and run_status not in allowed


def attention_for_item(
    item: QueueRecord,
    *,
    run_observation: Observation[RunRecord] | None,
    divergent: bool,
) -> tuple[AttentionRecord, ...]:
    attention: list[AttentionRecord] = []
    if item.recovery_detail is not None:
        attention.append(
            AttentionRecord(
                kind=AttentionKind.RECOVERY,
                subject=item.queue_item_id,
                message="queue recovery evidence requires inspection",
                queue_item_id=item.queue_item_id,
            )
        )
    elif item.status == "UNKNOWN":
        attention.append(
            AttentionRecord(
                kind=AttentionKind.RECOVERY,
                subject=item.queue_item_id,
                message="queue item state is UNKNOWN",
                queue_item_id=item.queue_item_id,
            )
        )

    run = None if run_observation is None else run_observation.value
    if item.status in ACTIVE_QUEUE_STATUSES:
        if item.cancellation_requested_at is not None:
            attention.append(
                AttentionRecord(
                    kind=AttentionKind.UNCERTAIN,
                    subject=item.queue_item_id,
                    message="cancellation was requested but terminal completion is not proven",
                    queue_item_id=item.queue_item_id,
                )
            )
        if run_observation is None or run_observation.value is None:
            message = "authority state has not been observed"
            if run_observation is not None and run_observation.error:
                message = (
                    f"authority state unavailable: {one_line(run_observation.error)}"
                )
            attention.append(
                AttentionRecord(
                    kind=AttentionKind.UNCERTAIN,
                    subject=item.queue_item_id,
                    message=message,
                    queue_item_id=item.queue_item_id,
                )
            )
        elif run_observation.error is not None:
            attention.append(
                AttentionRecord(
                    kind=AttentionKind.UNCERTAIN,
                    subject=item.queue_item_id,
                    message=f"authority observation is stale: {one_line(run_observation.error)}",
                    queue_item_id=item.queue_item_id,
                )
            )
        if item.pool_mode == "managed" and (
            item.active_attempt is None
            or item.active_attempt.live_observation != "same_session"
        ):
            attention.append(
                AttentionRecord(
                    kind=AttentionKind.UNCERTAIN,
                    subject=item.queue_item_id,
                    message="managed process liveness is not observed by this monitor",
                    queue_item_id=item.queue_item_id,
                )
            )
    if divergent:
        attention.append(
            AttentionRecord(
                kind=AttentionKind.UNCERTAIN,
                subject=item.queue_item_id,
                message=(
                    f"queue={item.status} and authority="
                    f"{None if run is None else run.status} diverge"
                ),
                queue_item_id=item.queue_item_id,
            )
        )

    failed_stages = (
        ()
        if run is None
        else tuple(
            stage for stage in run.stages if stage.status in FAILED_STAGE_STATUSES
        )
    )
    if item.status == "FAILED" or (
        run is not None and run.status in FAILED_RUN_STATUSES
    ):
        attention.append(
            AttentionRecord(
                kind=AttentionKind.FAILED,
                subject=display_run_name(item.run_uri),
                message=(
                    f"stage={failed_stages[0].stage_name}"
                    if failed_stages
                    else "run or queue item failed"
                ),
                queue_item_id=item.queue_item_id,
            )
        )
    elif failed_stages:
        attention.append(
            AttentionRecord(
                kind=AttentionKind.FAILED,
                subject=display_run_name(item.run_uri),
                message=f"stage={failed_stages[0].stage_name}",
                queue_item_id=item.queue_item_id,
            )
        )
    return tuple(_deduplicate_attention(attention))


def _deduplicate_attention(
    records: Iterable[AttentionRecord],
) -> Iterable[AttentionRecord]:
    seen: set[tuple[AttentionKind, str]] = set()
    for record in records:
        key = (record.kind, record.message)
        if key not in seen:
            seen.add(key)
            yield record


def all_attention(work: Sequence[WorkRecord]) -> tuple[AttentionRecord, ...]:
    rank = {
        AttentionKind.RECOVERY: 0,
        AttentionKind.UNCERTAIN: 1,
        AttentionKind.FAILED: 2,
        AttentionKind.WAITING: 3,
    }
    records = [record for item in work for record in item.attention]
    if records:
        oldest_waiting = min(
            (item for item in work if item.item.status == "QUEUED"),
            key=lambda item: (item.item.enqueued_at, item.item.queue_item_id),
            default=None,
        )
        if oldest_waiting is not None:
            records.append(
                AttentionRecord(
                    kind=AttentionKind.WAITING,
                    subject=oldest_waiting.item.queue_item_id,
                    message="oldest ordinary queued item (informational, not a stuck alert)",
                    queue_item_id=oldest_waiting.item.queue_item_id,
                )
            )
    return tuple(
        sorted(
            records,
            key=lambda record: (rank[record.kind], record.subject, record.message),
        )
    )


def work_sort_key(work: WorkRecord) -> tuple[object, ...]:
    if work.attention:
        group = 0
    elif work.item.status in ACTIVE_QUEUE_STATUSES:
        group = 1
    elif work.item.status == "QUEUED":
        group = 2
    else:
        group = 3
    terminal_time = "" if group != 3 else _reverse_timestamp(work.item.updated_at)
    return (
        group,
        terminal_time,
        work.item.enqueued_at,
        work.item.queue_item_id,
    )


def _reverse_timestamp(value: str) -> int:
    try:
        return -int(parse_timestamp(value).timestamp())
    except ValueError:
        return 0


def filter_work(
    work: Sequence[WorkRecord],
    *,
    view: MonitorView,
    pool_name: str | None,
    query: str,
) -> tuple[WorkRecord, ...]:
    query = query.casefold().strip()
    selected: list[WorkRecord] = []
    for record in work:
        if pool_name is not None and record.item.pool_name != pool_name:
            continue
        if (
            view is MonitorView.ACTIVE
            and record.item.status not in ACTIVE_QUEUE_STATUSES
        ):
            continue
        if view is MonitorView.WAITING and record.item.status != "QUEUED":
            continue
        if view is MonitorView.ATTENTION and not record.attention:
            continue
        if (
            view is MonitorView.TERMINAL
            and record.item.status not in TERMINAL_QUEUE_STATUSES
        ):
            continue
        if query and query not in _search_text(record):
            continue
        selected.append(record)
    return tuple(selected)


def _search_text(record: WorkRecord) -> str:
    values = [
        record.item.queue_item_id,
        record.item.run_uri,
        record.item.pool_name,
        record.item.status,
        "" if record.run is None or record.run.status is None else record.run.status,
        "" if record.current_stage is None else record.current_stage,
        *(f"{key}={value}" for key, value in record.item.tags.items()),
    ]
    return " ".join(values).casefold()


def fifo_positions(items: Sequence[QueueRecord]) -> Mapping[str, tuple[int, int]]:
    by_pool: dict[str, list[QueueRecord]] = {}
    for item in items:
        if item.status == "QUEUED":
            by_pool.setdefault(item.pool_name, []).append(item)
    positions: dict[str, tuple[int, int]] = {}
    for queued in by_pool.values():
        ordered = sorted(
            queued, key=lambda item: (item.enqueued_at, item.queue_item_id)
        )
        for index, item in enumerate(ordered, start=1):
            positions[item.queue_item_id] = (index, len(ordered))
    return positions


def execution_label(item: QueueRecord) -> str:
    attempt = item.active_attempt
    if attempt is not None and attempt.process is not None:
        pid = attempt.process.get("pid")
        if isinstance(pid, int):
            return f"pid={pid}"
    if item.dispatch_handle_id:
        adapter = item.adapter or "dispatch"
        return f"{adapter}:{item.dispatch_handle_id}"
    if item.adapter:
        return item.adapter
    return "—"


def evidence_label(
    queue_observation: Observation[Any],
    *,
    run_observation: Observation[RunRecord] | None,
    divergent: bool,
) -> str:
    if divergent:
        return "DIVERGENT"
    if queue_observation.error is not None:
        return "stale"
    if run_observation is None:
        return "persisted"
    if run_observation.error is not None:
        return "stale" if run_observation.value is not None else "unavailable"
    if run_observation.value is None:
        return "unavailable"
    label = run_observation.value.state_source.get("label")
    return "fresh" if label == "authoritative_service_truth" else "persisted"


def stage_progress(stages: Sequence[StageRecord]) -> tuple[int, int]:
    return sum(stage.status in SETTLED_STAGE_STATUSES for stage in stages), len(stages)


def job_progress(jobs: Sequence[JobRecord]) -> tuple[int, int]:
    return (
        sum(job.scheduler_state.upper() in TERMINAL_JOB_STATUSES for job in jobs),
        len(jobs),
    )


def merged_timeline(
    *,
    queue_entries: Sequence[TimelineEntry],
    run_entries: Sequence[TimelineEntry],
    scheduler_entries: Sequence[TimelineEntry] = (),
) -> tuple[TimelineEntry, ...]:
    return tuple(
        sorted(
            (*queue_entries, *run_entries, *scheduler_entries),
            key=lambda entry: (_timestamp_sort_key(entry.occurred_at), entry.source),
        )
    )


def _timestamp_sort_key(value: str) -> tuple[int, str]:
    try:
        return int(parse_timestamp(value).timestamp() * 1_000_000), value
    except ValueError:
        return 0, value


def sanitize_terminal_text(value: str) -> str:
    """Remove terminal controls while preserving log newlines and tabs."""

    result: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        code = ord(character)
        if character == "\x1b":
            index = _skip_escape(value, index)
            continue
        if character in {"\n", "\t"} or (code >= 32 and not 127 <= code <= 159):
            result.append(character)
        index += 1
    return "".join(result)


def _skip_escape(value: str, index: int) -> int:
    index += 1
    if index >= len(value):
        return index
    introducer = value[index]
    if introducer == "[":
        index += 1
        while index < len(value):
            if 0x40 <= ord(value[index]) <= 0x7E:
                return index + 1
            index += 1
        return index
    if introducer == "]":
        index += 1
        while index < len(value):
            if value[index] == "\x07":
                return index + 1
            if (
                value[index] == "\x1b"
                and index + 1 < len(value)
                and value[index + 1] == "\\"
            ):
                return index + 2
            index += 1
        return index
    return index + 1


def one_line(value: str, *, limit: int = 100) -> str:
    text = " ".join(sanitize_terminal_text(value).split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


__all__ = [
    "ACTIVE_QUEUE_STATUSES",
    "TERMINAL_QUEUE_STATUSES",
    "all_attention",
    "build_work_records",
    "current_stage",
    "display_run_name",
    "fifo_positions",
    "filter_work",
    "format_age",
    "format_duration",
    "job_progress",
    "merged_timeline",
    "one_line",
    "sanitize_terminal_text",
    "source_indicator",
    "stage_progress",
    "states_divergent",
]
