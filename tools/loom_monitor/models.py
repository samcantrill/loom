"""Immutable presentation records for the repository-local Loom monitor."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from loom.serialization import PlainData


T = TypeVar("T")


class MonitorView(StrEnum):
    """Work-list views exposed by the monitor."""

    ACTIVE = "Active"
    WAITING = "Waiting"
    ATTENTION = "Attention"
    TERMINAL = "Terminal"
    ALL = "All"


class AttentionKind(StrEnum):
    """Tool-local operational attention categories."""

    RECOVERY = "RECOVERY"
    UNCERTAIN = "UNCERTAIN"
    FAILED = "FAILED"
    WAITING = "WAITING"


@dataclass(frozen=True, slots=True)
class Observation(Generic[T]):
    """Latest value and independent refresh state for one observation source."""

    source: str
    value: T | None = None
    observed_at: datetime | None = None
    last_success_at: datetime | None = None
    error: str | None = None
    refreshing: bool = False

    def refreshing_now(self) -> "Observation[T]":
        return replace(self, refreshing=True)

    def succeeded(self, value: T, *, at: datetime) -> "Observation[T]":
        return Observation(
            source=self.source,
            value=value,
            observed_at=at,
            last_success_at=at,
        )

    def failed(self, error: BaseException | str, *, at: datetime) -> "Observation[T]":
        message = str(error).strip() or type(error).__name__
        return Observation(
            source=self.source,
            value=self.value,
            observed_at=at,
            last_success_at=self.last_success_at,
            error=message,
        )

    @property
    def available(self) -> bool:
        return self.value is not None

    @property
    def stale(self) -> bool:
        return self.value is not None and self.error is not None


@dataclass(frozen=True, slots=True)
class ActiveAttempt:
    queue_item_id: str
    owner_id: str | None
    session_id: str | None
    evidence_source: str
    live_observation: str
    process: Mapping[str, PlainData] | None = None
    assignment: Mapping[str, PlainData] | None = None
    logs: Mapping[str, PlainData] | None = None


@dataclass(frozen=True, slots=True)
class QueueRecord:
    queue_item_id: str
    queue_name: str
    pool_name: str
    pool_mode: str
    run_uri: str
    status: str
    enqueued_at: str
    updated_at: str
    dispatch_attempt: int
    requested_resources: Mapping[str, int] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    claim_owner: str | None = None
    claimed_at: str | None = None
    adapter: str | None = None
    dispatch_handle_id: str | None = None
    dispatched_at: str | None = None
    cancellation_requested_at: str | None = None
    cancellation_requested_by: str | None = None
    cancellation_reason: str | None = None
    active_attempt: ActiveAttempt | None = None
    recovery_detail: Mapping[str, PlainData] | None = None


@dataclass(frozen=True, slots=True)
class PoolRecord:
    pool_name: str
    mode: str
    controller_limit: int
    queued: int
    claimed: int
    dispatched: int
    succeeded: int
    failed: int
    cancelled: int
    unknown: int
    oldest_queued_at: str | None = None
    recovery_count: int = 0

    @property
    def active(self) -> int:
        return self.claimed + self.dispatched


@dataclass(frozen=True, slots=True)
class QueueData:
    workspace_name: str
    pools: tuple[PoolRecord, ...]
    items: tuple[QueueRecord, ...]


@dataclass(frozen=True, slots=True)
class StageRecord:
    stage_name: str
    status: str | None
    attempt: int | None
    message: str | None
    failure: Mapping[str, PlainData] | None
    input_count: int
    output_count: int
    log_paths: Mapping[str, str | None]
    log_available: Mapping[str, bool]
    state_source: Mapping[str, PlainData]
    log_source: Mapping[str, PlainData]
    reliability_warning_count: int = 0


@dataclass(frozen=True, slots=True)
class SubmittedOperationRecord:
    submission_id: str
    backend: str
    mode: str
    state: str
    created_at: str
    updated_at: str
    active: bool


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_uri: str
    status: str | None
    message: str | None
    artifact_count: int
    state_source: Mapping[str, PlainData]
    stages: tuple[StageRecord, ...]
    submitted_operations: tuple[SubmittedOperationRecord, ...]


@dataclass(frozen=True, slots=True)
class JobRecord:
    logical_key: str
    stage_name: str | None
    scheduler_job_id: str
    status: str
    source: str
    scheduler_state: str
    loom_run_status: str | None
    loom_stage_status: str | None
    exit_code: str | None
    dependency_state: str | None
    dependency_job_ids: tuple[str, ...]
    log_paths: Mapping[str, str | None]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JobsData:
    run_uri: str
    jobs: tuple[JobRecord, ...]
    submission_id: str | None = None
    submission_state: str | None = None
    warnings: tuple[str, ...] = ()
    failed_submission_count: int = 0


@dataclass(frozen=True, slots=True)
class LogStreamRecord:
    stream: str
    path: str
    available: bool
    content: str | None
    line_count: int
    displayed_line_count: int
    truncated: bool
    state_source: Mapping[str, PlainData]


@dataclass(frozen=True, slots=True)
class LogsData:
    run_uri: str
    stage_name: str
    streams: tuple[LogStreamRecord, ...]
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    occurred_at: str
    source: str
    event_type: str
    summary: str
    stage_name: str | None = None
    sequence: int | None = None
    warning: bool = False


@dataclass(frozen=True, slots=True)
class SelectedData:
    queue_item_id: str
    audit_events: tuple[TimelineEntry, ...]
    run_events: tuple[TimelineEntry, ...]
    run_events_error: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorityData:
    state: str
    message: str | None = None
    workspace_id: str | None = None
    service_generation: str | None = None


@dataclass(frozen=True, slots=True)
class MonitorSnapshot:
    """One immutable set of independently observed monitor facts."""

    queue: Observation[QueueData]
    authority: Observation[AuthorityData]
    runs: Mapping[str, Observation[RunRecord]] = field(default_factory=dict)
    selected: Observation[SelectedData] = field(
        default_factory=lambda: Observation(source="selected")
    )
    jobs: Observation[JobsData] = field(
        default_factory=lambda: Observation(source="scheduler")
    )
    logs: Observation[LogsData] = field(
        default_factory=lambda: Observation(source="logs")
    )


@dataclass(frozen=True, slots=True)
class AttentionRecord:
    kind: AttentionKind
    subject: str
    message: str
    queue_item_id: str


@dataclass(frozen=True, slots=True)
class WorkRecord:
    item: QueueRecord
    run: RunRecord | None
    run_observation: Observation[RunRecord] | None
    current_stage: str | None
    execution: str
    evidence: str
    divergent: bool
    attention: tuple[AttentionRecord, ...]
