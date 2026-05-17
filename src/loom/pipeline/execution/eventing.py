"""Local lifecycle event helpers for pipeline execution."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal, cast

from loom.pipeline.event_sinks import (
    EventObserverLinkRecord,
    EventSinkDispatchResult,
    EventSinkError,
    EventSinkFailureRecord,
    EventSinkRegistry,
)
from loom.pipeline.events import (
    EventReference,
    EventScope,
    PipelineEvent,
    PipelineEventRecord,
)
from loom.pipeline.stores import RunEventStore
from loom.serialization import PlainData, ensure_plain_data, thaw_plain_data

EventPersistenceMode = Literal["durable", "non_durable"]


@dataclass(frozen=True, slots=True)
class EventDispatchWarning:
    """Warning produced when event sink dispatch weakens durable inspection."""

    code: str
    message: str
    event_reference: EventReference
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("EventDispatchWarning.code must be a non-empty string")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("EventDispatchWarning.message must be a non-empty string")
        object.__setattr__(
            self, "event_reference", EventReference.from_dict(self.event_reference)
        )
        detail = ensure_plain_data(dict(self.detail), path="detail")
        if not isinstance(detail, dict):
            raise ValueError("EventDispatchWarning.detail must be a mapping")
        object.__setattr__(self, "detail", cast(dict[str, PlainData], detail))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "event_reference": self.event_reference.to_dict(),
            "detail": dict(self.detail),
        }


class RuntimeEventDispatcher:
    """Append runtime events and dispatch explicit sinks in the right order."""

    def __init__(
        self,
        *,
        registry: EventSinkRegistry | None = None,
        persistence: EventPersistenceMode = "durable",
    ) -> None:
        if registry is not None and not isinstance(registry, EventSinkRegistry):
            raise TypeError("registry must be an EventSinkRegistry when supplied")
        if persistence not in {"durable", "non_durable"}:
            raise ValueError("persistence must be 'durable' or 'non_durable'")
        self.registry = registry
        self.persistence: EventPersistenceMode = persistence
        self._dispatch_sequences: dict[str, int] = {}
        self._warnings: list[EventDispatchWarning] = []
        self._lock = Lock()

    @property
    def warnings(self) -> tuple[EventDispatchWarning, ...]:
        return tuple(self._warnings)

    def emit(
        self,
        run_store: RunEventStore,
        *,
        run_uri: str,
        event: PipelineEvent,
    ) -> PipelineEventRecord | EventReference:
        if self.persistence == "durable":
            record = run_store.append_event(run_uri, event)
            self._dispatch_if_configured(run_store, record)
            return record
        reference = self._non_durable_reference(run_uri=run_uri, event=event)
        self._warnings.append(
            EventDispatchWarning(
                code="event_persistence.non_durable",
                message=(
                    "event sink dispatch is non-durable because event "
                    "persistence is disabled"
                ),
                event_reference=reference,
                detail={"event_type": reference.event_type},
            )
        )
        self._dispatch_if_configured(run_store, reference)
        return reference

    def _dispatch_if_configured(
        self,
        run_store: RunEventStore,
        event: PipelineEventRecord | EventReference,
    ) -> EventSinkDispatchResult | None:
        registry = self.registry
        if registry is None or len(registry) == 0:
            return None
        context = _RuntimeEventSinkContext(
            run_store=run_store,
            event_reference=_event_reference(event),
        )
        return registry.dispatch(event, context)

    def _non_durable_reference(
        self,
        *,
        run_uri: str,
        event: PipelineEvent,
    ) -> EventReference:
        with self._lock:
            dispatch_sequence = self._dispatch_sequences.get(run_uri, 0) + 1
            self._dispatch_sequences[run_uri] = dispatch_sequence
        occurred_at = event.timestamp
        if occurred_at is None:
            raise ValueError("non-durable event dispatch requires an event timestamp")
        event_id = _non_durable_event_id(
            run_uri=run_uri,
            event_type=event.event_type,
            occurred_at=occurred_at,
            dispatch_sequence=dispatch_sequence,
        )
        return EventReference(
            event_id=event_id,
            run_uri=run_uri,
            event_type=event.event_type,
            occurred_at=occurred_at,
            durability="non_durable",
            dispatch_sequence=dispatch_sequence,
        )


@dataclass(slots=True)
class _RuntimeEventSinkContext:
    run_store: RunEventStore
    event_reference: EventReference

    @property
    def run_uri(self) -> str:
        return self.event_reference.run_uri

    def record_event_observer_link(self, link: EventObserverLinkRecord) -> None:
        record = EventObserverLinkRecord.from_dict(link)
        if record.event_reference != self.event_reference:
            raise EventSinkError("observer link event_reference must match context")
        recorder = getattr(self.run_store, "append_event_observer_link", None)
        if not callable(recorder):
            raise EventSinkError("run store cannot record event observer links")
        recorder(self.run_uri, record)

    def record_event_sink_failure(self, failure: EventSinkFailureRecord) -> None:
        record = EventSinkFailureRecord.from_dict(failure)
        if record.event_reference != self.event_reference:
            raise EventSinkError("sink failure event_reference must match context")
        recorder = getattr(self.run_store, "append_event_sink_failure", None)
        if not callable(recorder):
            raise EventSinkError("run store cannot record event sink failures")
        recorder(self.run_uri, record)


def emit_run_event(
    run_store: RunEventStore,
    *,
    run_uri: str,
    event_type: str,
    timestamp: str,
    payload: Mapping[str, PlainData] | None = None,
    event_dispatcher: RuntimeEventDispatcher | None = None,
) -> PipelineEventRecord | EventReference:
    return _emit_event(
        run_store,
        run_uri=run_uri,
        scope=EventScope.run(),
        event_type=event_type,
        timestamp=timestamp,
        payload=payload,
        event_dispatcher=event_dispatcher,
    )


def emit_stage_event(
    run_store: RunEventStore,
    *,
    run_uri: str,
    stage_name: str,
    event_type: str,
    timestamp: str,
    payload: Mapping[str, PlainData] | None = None,
    event_dispatcher: RuntimeEventDispatcher | None = None,
) -> PipelineEventRecord | EventReference:
    return _emit_event(
        run_store,
        run_uri=run_uri,
        scope=EventScope.stage(stage_name),
        event_type=event_type,
        timestamp=timestamp,
        payload=payload,
        event_dispatcher=event_dispatcher,
    )


def _emit_event(
    run_store: RunEventStore,
    *,
    run_uri: str,
    scope: EventScope,
    event_type: str,
    timestamp: str,
    payload: Mapping[str, PlainData] | None,
    event_dispatcher: RuntimeEventDispatcher | None,
) -> PipelineEventRecord | EventReference:
    normalized_payload = thaw_plain_data(dict(payload or {}), path="payload")
    if not isinstance(normalized_payload, dict):
        raise ValueError("event payload must be a mapping")
    event = PipelineEvent(
        scope=scope,
        event_type=event_type,
        timestamp=timestamp,
        payload=cast(dict[str, PlainData], normalized_payload),
    )
    if event_dispatcher is None:
        return run_store.append_event(run_uri, event)
    return event_dispatcher.emit(run_store, run_uri=run_uri, event=event)


def _event_reference(event: PipelineEventRecord | EventReference) -> EventReference:
    if isinstance(event, PipelineEventRecord):
        return event.to_event_reference()
    return EventReference.from_dict(event)


def _non_durable_event_id(
    *,
    run_uri: str,
    event_type: str,
    occurred_at: str,
    dispatch_sequence: int,
) -> str:
    digest = hashlib.sha256(
        f"{run_uri}\0{event_type}\0{occurred_at}\0{dispatch_sequence}".encode("utf-8")
    ).hexdigest()
    return f"non-durable-{digest[:32]}"


__all__ = [
    "EventDispatchWarning",
    "EventPersistenceMode",
    "RuntimeEventDispatcher",
    "emit_run_event",
    "emit_stage_event",
]
