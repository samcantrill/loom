"""Diagnostics facades for persisted local run status and logs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from loom.serialization import PlainData, ensure_plain_data


DEFAULT_LOG_TAIL_LINES = 100
LOG_STREAMS = ("stdout", "stderr")


class DiagnosticsInspectionError(ValueError):
    """Raised when persisted diagnostics state cannot be inspected."""


@dataclass(frozen=True, slots=True)
class StageStatusSummary:
    stage_name: str
    status: str | None = None
    attempt: int | None = None
    message: str | None = None
    failure: Mapping[str, PlainData] | None = None
    input_count: int = 0
    output_count: int = 0
    provenance_available: bool = False
    log_paths: Mapping[str, str | None] = field(default_factory=dict)
    log_available: Mapping[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "status": self.status,
            "attempt": self.attempt,
            "message": self.message,
            "failure": None if self.failure is None else dict(self.failure),
            "input_count": self.input_count,
            "output_count": self.output_count,
            "provenance_available": self.provenance_available,
            "log_paths": dict(self.log_paths),
            "log_available": dict(self.log_available),
        }


@dataclass(frozen=True, slots=True)
class RunStatusSummary:
    run_uri: str
    status: str | None = None
    message: str | None = None
    artifact_count: int = 0
    stages: tuple[StageStatusSummary, ...] = ()

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "status": self.status,
            "message": self.message,
            "artifact_count": self.artifact_count,
            "stages": [stage.to_dict() for stage in self.stages],
        }


@dataclass(frozen=True, slots=True)
class LogStreamSummary:
    stream: str
    path: str
    available: bool
    content: str | None = None
    line_count: int = 0
    displayed_line_count: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stream": self.stream,
            "path": self.path,
            "available": self.available,
            "content": self.content,
            "line_count": self.line_count,
            "displayed_line_count": self.displayed_line_count,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class StageLogsSummary:
    run_uri: str
    stage_name: str
    streams: tuple[LogStreamSummary, ...]
    paths_only: bool = False

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "paths_only": self.paths_only,
            "streams": [stream.to_dict() for stream in self.streams],
        }


def inspect_run_status(run_uri: str, *, run_store: Any | None = None) -> RunStatusSummary:
    """Inspect persisted local run status through the store-owned facade."""

    store = _default_run_store() if run_store is None else run_store
    state = store.inspect_run_state(run_uri)
    run_status = state.run_status
    return RunStatusSummary(
        run_uri=state.run_uri,
        status=None if run_status is None else run_status.status.value,
        message=None if run_status is None else run_status.message,
        artifact_count=state.artifact_count,
        stages=tuple(_stage_summary(stage) for stage in state.stage_inspections),
    )


def inspect_stage_logs(
    run_uri: str,
    stage_name: str,
    *,
    streams: Iterable[str] = LOG_STREAMS,
    tail: int = DEFAULT_LOG_TAIL_LINES,
    paths_only: bool = False,
    run_store: Any | None = None,
) -> StageLogsSummary:
    """Inspect bounded persisted stage logs through public store APIs."""

    if tail <= 0:
        raise DiagnosticsInspectionError("tail must be a positive integer")
    selected = _normalize_streams(streams)
    store = _default_run_store() if run_store is None else run_store
    stages = set(store.list_run_stages(run_uri))
    if stage_name not in stages:
        raise DiagnosticsInspectionError(f"unknown stage {stage_name!r} for run {run_uri}")

    summaries = tuple(
        _stream_summary(
            store,
            run_uri=run_uri,
            stage_name=stage_name,
            stream=stream,
            tail=tail,
            paths_only=paths_only,
        )
        for stream in selected
    )
    if not paths_only and not any(summary.available for summary in summaries):
        names = ", ".join(selected)
        raise DiagnosticsInspectionError(
            f"no log content found for stage {stage_name!r} stream(s): {names}"
        )
    return StageLogsSummary(
        run_uri=run_uri,
        stage_name=stage_name,
        streams=summaries,
        paths_only=paths_only,
    )


def _stage_summary(stage: object) -> StageStatusSummary:
    status = getattr(stage, "status")
    return StageStatusSummary(
        stage_name=str(getattr(stage, "stage_name")),
        status=None if status is None else status.status.value,
        attempt=None if status is None else status.attempt,
        message=None if status is None else status.message,
        failure=_plain_mapping_or_none(getattr(stage, "failure")),
        input_count=int(getattr(stage, "input_count")),
        output_count=int(getattr(stage, "output_count")),
        provenance_available=bool(getattr(stage, "provenance_available")),
        log_paths={
            "stdout": _optional_str(getattr(stage, "stdout_path")),
            "stderr": _optional_str(getattr(stage, "stderr_path")),
        },
        log_available={
            "stdout": bool(getattr(stage, "stdout_available")),
            "stderr": bool(getattr(stage, "stderr_available")),
        },
    )


def _stream_summary(
    store: Any,
    *,
    run_uri: str,
    stage_name: str,
    stream: str,
    tail: int,
    paths_only: bool,
) -> LogStreamSummary:
    path = str(store.local_stage_log_path(run_uri, stage_name, stream))
    if paths_only:
        content = store.read_stage_log(run_uri, stage_name, stream)
        return LogStreamSummary(stream=stream, path=path, available=content is not None)

    content = store.read_stage_log(run_uri, stage_name, stream)
    if content is None:
        return LogStreamSummary(stream=stream, path=path, available=False)

    lines = content.splitlines()
    displayed = lines[-tail:]
    rendered = "\n".join(displayed)
    if content.endswith("\n") and rendered:
        rendered += "\n"
    return LogStreamSummary(
        stream=stream,
        path=path,
        available=True,
        content=rendered,
        line_count=len(lines),
        displayed_line_count=len(displayed),
        truncated=len(lines) > len(displayed),
    )


def _normalize_streams(streams: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(streams)
    if not selected:
        raise DiagnosticsInspectionError("at least one log stream is required")
    unknown = sorted(set(selected) - set(LOG_STREAMS))
    if unknown:
        names = ", ".join(unknown)
        raise DiagnosticsInspectionError(f"unknown log stream(s): {names}")
    return tuple(stream for stream in LOG_STREAMS if stream in selected)


def _default_run_store() -> Any:
    from loom.pipeline.stores import LocalRunStore

    return LocalRunStore()


def _plain_mapping_or_none(value: object) -> Mapping[str, PlainData] | None:
    if value is None:
        return None
    normalized = ensure_plain_data(value, path="failure")
    if not isinstance(normalized, dict):
        return {"value": normalized}
    return normalized


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = [
    "DEFAULT_LOG_TAIL_LINES",
    "LOG_STREAMS",
    "DiagnosticsInspectionError",
    "LogStreamSummary",
    "RunStatusSummary",
    "StageLogsSummary",
    "StageStatusSummary",
    "inspect_run_status",
    "inspect_stage_logs",
]
