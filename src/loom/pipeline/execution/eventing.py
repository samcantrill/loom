"""Local lifecycle event helpers for pipeline execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.stores import RunEventStore
from loom.serialization import PlainData, thaw_plain_data


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
    normalized_payload = thaw_plain_data(dict(payload or {}), path="payload")
    if not isinstance(normalized_payload, dict):
        raise ValueError("event payload must be a mapping")
    return run_store.append_event(
        run_id,
        PipelineEvent(
            scope=scope,
            event_type=event_type,
            timestamp=timestamp,
            payload=cast(dict[str, PlainData], normalized_payload),
        ),
    )


__all__ = ["emit_run_event", "emit_stage_event"]
