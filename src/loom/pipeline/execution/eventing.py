"""Local lifecycle event helpers for pipeline execution."""

from __future__ import annotations

from collections.abc import Mapping

from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.stores import RunEventStore
from loom.serialization import PlainData


def emit_run_event(
    run_store: RunEventStore,
    *,
    run_id: str,
    event_type: str,
    timestamp: str,
    payload: Mapping[str, PlainData] | None = None,
) -> PipelineEventRecord:
    return _emit_event(
        run_store,
        run_id=run_id,
        scope=EventScope.run(),
        event_type=event_type,
        timestamp=timestamp,
        payload=payload,
    )


def emit_stage_event(
    run_store: RunEventStore,
    *,
    run_id: str,
    stage_name: str,
    event_type: str,
    timestamp: str,
    payload: Mapping[str, PlainData] | None = None,
) -> PipelineEventRecord:
    return _emit_event(
        run_store,
        run_id=run_id,
        scope=EventScope.stage(stage_name),
        event_type=event_type,
        timestamp=timestamp,
        payload=payload,
    )


def _emit_event(
    run_store: RunEventStore,
    *,
    run_id: str,
    scope: EventScope,
    event_type: str,
    timestamp: str,
    payload: Mapping[str, PlainData] | None,
) -> PipelineEventRecord:
    return run_store.append_event(
        run_id,
        PipelineEvent(
            scope=scope,
            event_type=event_type,
            timestamp=timestamp,
            payload=dict(payload or {}),
        ),
    )


__all__ = ["emit_run_event", "emit_stage_event"]
