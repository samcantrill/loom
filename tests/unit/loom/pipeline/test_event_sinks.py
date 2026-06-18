"""Tests for import-light event sink contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

import pytest

from loom.pipeline.event_sinks import (
    EVENT_OBSERVER_LINK_SCHEMA_VERSION,
    EVENT_SINK_FAILURE_SCHEMA_VERSION,
    EventObserverExternalRef,
    EventObserverLinkRecord,
    EventSinkContext,
    EventSinkError,
    EventSinkFailureRecord,
    EventSinkRegistry,
    EventSinkRegistryError,
)
from loom.pipeline.events import EventReference, EventScope, PipelineEventRecord
from loom.serialization import PlainData


RUN_URI = "file:///tmp/loom-runs/run-1"
OCCURRED_AT = "2020-01-01T00:00:00Z"


def _event_record() -> PipelineEventRecord:
    return PipelineEventRecord(
        run_uri=RUN_URI,
        sequence=1,
        timestamp=OCCURRED_AT,
        scope=EventScope.run(),
        event_type="run.started",
        payload={"source": "test"},
    )


def _observer_link(*, sink_name: str = "audit.sink") -> EventObserverLinkRecord:
    event_reference = _event_record().to_event_reference()
    return EventObserverLinkRecord(
        sink_name=sink_name,
        run_uri=RUN_URI,
        event_reference=event_reference,
        recorded_at="2020-01-01T00:00:01Z",
        external_ref=EventObserverExternalRef(
            kind="trace",
            identifiers={"trace_id": "trace-1"},
        ),
        metadata={"status": "linked"},
    )


@dataclass(slots=True)
class RecordingContext:
    run_uri: str
    event_reference: EventReference
    links: list[EventObserverLinkRecord] = field(default_factory=list)
    failures: list[EventSinkFailureRecord] = field(default_factory=list)

    def record_event_observer_link(self, link: EventObserverLinkRecord) -> None:
        self.links.append(link)

    def record_event_sink_failure(self, failure: EventSinkFailureRecord) -> None:
        self.failures.append(failure)


def test_observer_link_record_round_trips_plain_data() -> None:
    record = _observer_link()

    payload = record.to_dict()
    restored = EventObserverLinkRecord.from_dict(payload)

    assert payload["schema_version"] == EVENT_OBSERVER_LINK_SCHEMA_VERSION
    assert restored == record
    assert restored.external_ref.to_dict() == {
        "kind": "trace",
        "identifiers": {"trace_id": "trace-1"},
    }


def test_failure_record_round_trips_plain_data() -> None:
    event_reference = _event_record().to_event_reference()
    record = EventSinkFailureRecord(
        sink_name="audit.sink",
        run_uri=RUN_URI,
        event_reference=event_reference,
        failed_at="2020-01-01T00:00:02Z",
        failure_type="RuntimeError",
        failure_message="callback failed",
        detail={"retryable": False},
    )

    payload = record.to_dict()
    restored = EventSinkFailureRecord.from_dict(payload)

    assert payload["schema_version"] == EVENT_SINK_FAILURE_SCHEMA_VERSION
    assert restored == record
    assert restored.event_reference == event_reference


def test_observer_records_reject_malformed_shapes() -> None:
    event_reference = _event_record().to_event_reference()

    with pytest.raises(EventSinkError, match="sink_name"):
        EventObserverLinkRecord(
            sink_name="BadName",
            run_uri=RUN_URI,
            event_reference=event_reference,
            recorded_at="2020-01-01T00:00:01Z",
            external_ref=EventObserverExternalRef(
                kind="trace",
                identifiers={"trace_id": "trace-1"},
            ),
        )
    with pytest.raises(EventSinkError, match="plain-data-compatible"):
        EventSinkFailureRecord(
            sink_name="audit.sink",
            run_uri=RUN_URI,
            event_reference=event_reference,
            failed_at="2020-01-01T00:00:02Z",
            failure_type="RuntimeError",
            failure_message="callback failed",
            detail=cast(Mapping[str, PlainData], {"bad": object()}),
        )


def test_registry_rejects_duplicates_and_dispatches_in_order() -> None:
    registry = EventSinkRegistry()
    calls: list[str] = []
    event = _event_record()
    context = RecordingContext(
        run_uri=RUN_URI,
        event_reference=event.to_event_reference(),
    )

    def first(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        assert isinstance(event, PipelineEventRecord)
        calls.append("first")
        context.record_event_observer_link(_observer_link(sink_name="audit.one"))

    def failing(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        _ = event, context
        calls.append("failing")
        raise RuntimeError("boom")

    def last(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        _ = event, context
        calls.append("last")

    registry.register("audit.one", first)
    registry.register("audit.failing", failing)
    registry.register("audit.last", last)

    with pytest.raises(EventSinkRegistryError, match="already registered"):
        registry.register("audit.one", last)

    result = registry.dispatch(event, context)

    assert registry.names() == ("audit.one", "audit.failing", "audit.last")
    assert calls == ["first", "failing", "last"]
    assert result.succeeded is False
    assert [item.succeeded for item in result.sink_results] == [True, False, True]
    assert result.failures[0].sink_name == "audit.failing"
    assert context.failures == list(result.failures)
    assert [link.sink_name for link in context.links] == ["audit.one"]


def test_sink_context_protocol_is_narrow() -> None:
    event_reference = _event_record().to_event_reference()
    context = RecordingContext(run_uri=RUN_URI, event_reference=event_reference)

    assert isinstance(context, EventSinkContext)
    assert not hasattr(context, "write_run_status")
    assert not hasattr(context, "write_run_user_metadata")
    assert not hasattr(context, "record_output_commit")
