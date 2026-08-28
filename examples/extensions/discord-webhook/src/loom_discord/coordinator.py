"""Bounded, best-effort Discord reporting for a local Loom coordinator."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from loom.queue import LocalDaemonAdmissionState, LocalDaemonStatus
from loom.serialization import PlainData

from .sink import DEFAULT_TIMEOUT_SECONDS, MAX_CONTENT_LENGTH, _send_webhook_content


MAX_ACTIVE_RUNS = 8
MAX_ACTIVE_STAGE_NAMES = 4
_TERMINAL_ADMISSION_STATES = frozenset(
    {
        LocalDaemonAdmissionState.SUCCEEDED.value,
        LocalDaemonAdmissionState.FAILED.value,
        LocalDaemonAdmissionState.CANCELLED.value,
        LocalDaemonAdmissionState.BLOCKED.value,
    }
)


@dataclass(frozen=True, slots=True)
class _ActiveRun:
    queue_item_id: str
    admission_state: str
    authority_availability: str
    authority_state: str
    succeeded_stages: int
    total_stages: int
    active_stages: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _CoordinatorProjection:
    service_health: str
    service_diagnostic: str | None
    admission_counts: tuple[tuple[str, int], ...]
    authority_run_counts: tuple[tuple[str, int], ...]
    authority_stage_counts: tuple[tuple[str, int], ...]
    active_runs: tuple[_ActiveRun, ...]
    omitted_active_runs: int


class DiscordCoordinatorReporter:
    """Project typed coordinator status to a bounded Discord message.

    The last attempted projection is process-local by design. A failed attempt is
    not retried until a meaningful change or a caller-forced heartbeat occurs.
    """

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not webhook_url:
            raise ValueError("webhook_url must be non-empty")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a positive finite number")
        self._webhook_url = webhook_url
        self._timeout_seconds = timeout_seconds
        self._last_projection: _CoordinatorProjection | None = None

    def report(self, status: LocalDaemonStatus, *, force: bool = False) -> bool:
        """Attempt one report, returning false only when it is unchanged."""

        projection = _project_status(status)
        if not force and projection == self._last_projection:
            return False
        # Record before external I/O so a transient failure cannot cause one
        # request per polling interval. Heartbeats and changed status retry.
        self._last_projection = projection
        _send_webhook_content(
            self._webhook_url,
            _format_projection(status.as_of, projection),
            timeout_seconds=self._timeout_seconds,
        )
        return True


def _project_status(status: LocalDaemonStatus) -> _CoordinatorProjection:
    admission_counts = Counter(admission.state.value for admission in status.admissions)
    views_by_queue_item = {
        _string(view.get("queue_item_id")): view
        for view in status.runs
        if _string(view.get("queue_item_id")) is not None
    }
    authority_run_counts: Counter[str] = Counter()
    authority_stage_counts: Counter[str] = Counter()
    active_runs: list[_ActiveRun] = []
    for admission in status.admissions:
        view = views_by_queue_item.get(admission.queue_item_id)
        authority = _mapping(None if view is None else view.get("authority"))
        availability = _string(authority.get("availability")) or "unavailable"
        authority_state = _string(authority.get("state")) or "unavailable"
        authority_run_counts[authority_state] += 1
        stages = _mapping(authority.get("stages")) if availability == "available" else {}
        stage_states = tuple(
            sorted(
                (stage_name, state)
                for stage_name, value in stages.items()
                if isinstance(stage_name, str) and (state := _string(value)) is not None
            )
        )
        authority_stage_counts.update(state for _, state in stage_states)
        if admission.state.value not in _TERMINAL_ADMISSION_STATES:
            active_runs.append(
                _ActiveRun(
                    queue_item_id=admission.queue_item_id,
                    admission_state=admission.state.value,
                    authority_availability=availability,
                    authority_state=authority_state,
                    succeeded_stages=sum(
                        state == "SUCCEEDED" for _, state in stage_states
                    ),
                    total_stages=len(stage_states),
                    active_stages=tuple(
                        (name, state)
                        for name, state in stage_states
                        if state in {"RUNNING", "SUBMITTED"}
                    ),
                )
            )
    active_runs.sort(key=lambda item: item.queue_item_id)
    displayed_active_runs = tuple(active_runs[:MAX_ACTIVE_RUNS])
    return _CoordinatorProjection(
        service_health=status.service_health,
        service_diagnostic=status.service_diagnostic,
        admission_counts=tuple(sorted(admission_counts.items())),
        authority_run_counts=tuple(sorted(authority_run_counts.items())),
        authority_stage_counts=tuple(sorted(authority_stage_counts.items())),
        active_runs=displayed_active_runs,
        omitted_active_runs=len(active_runs) - len(displayed_active_runs),
    )


def _format_projection(as_of: str, projection: _CoordinatorProjection) -> str:
    """Render the projection while retaining health and counts under truncation."""

    lines = [
        "Loom coordinator report (non-atomic status)",
        f"As of: {_clip(as_of, 100)}",
        f"Service: {_clip(projection.service_health, 100)}",
    ]
    if projection.service_diagnostic is not None:
        lines.append(f"Diagnostic: {_clip(projection.service_diagnostic, 200)}")
    lines.extend(
        (
            f"Admissions: {_format_counts(projection.admission_counts)}",
            f"Authority runs: {_format_counts(projection.authority_run_counts)}",
            f"Authority stages: {_format_counts(projection.authority_stage_counts)}",
        )
    )
    if projection.omitted_active_runs:
        lines.append(f"Active runs omitted: {projection.omitted_active_runs}")
    for active in projection.active_runs:
        lines.append(
            "Active: "
            f"item={_clip(active.queue_item_id, 120)} "
            f"admission={active.admission_state} "
            f"authority={active.authority_state}/{active.authority_availability} "
            f"progress={active.succeeded_stages}/{active.total_stages}"
        )
        if active.active_stages:
            rendered_stages = ", ".join(
                f"{_clip(name, 80)} ({state})"
                for name, state in active.active_stages[:MAX_ACTIVE_STAGE_NAMES]
            )
            omitted = len(active.active_stages) - MAX_ACTIVE_STAGE_NAMES
            if omitted > 0:
                rendered_stages += f", +{omitted} more"
            lines.append(f"  Stages: {rendered_stages}")
    return _bound_lines(lines)


def _bound_lines(lines: list[str]) -> str:
    content = "\n".join(lines)
    if len(content) <= MAX_CONTENT_LENGTH:
        return content
    clipped_marker = "…active detail clipped"
    kept: list[str] = []
    for line in lines:
        candidate = "\n".join((*kept, line))
        if len(candidate) + 1 + len(clipped_marker) > MAX_CONTENT_LENGTH:
            break
        kept.append(line)
    return "\n".join(kept + [clipped_marker])


def _format_counts(counts: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{state}={count}" for state, count in counts) or "none"


def _mapping(value: PlainData | None) -> Mapping[str, PlainData]:
    return value if isinstance(value, Mapping) else {}


def _string(value: PlainData | None) -> str | None:
    return value if isinstance(value, str) else None


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"
