"""Cleanup audit event projection helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from loom.pipeline.event_sinks import EventObserverLinkRecord, EventSinkFailureRecord
from loom.pipeline.events import (
    EventScope,
    EventReference,
    PipelineEvent,
    PipelineEventRecord,
)
from loom.pipeline.execution.eventing import RuntimeEventDispatcher
from loom.pipeline.stores import (
    CleanupReportFact,
    CleanupResultFact,
    PerRunAuthorityStore,
)
from loom.serialization import PlainData, thaw_plain_data

CLEANUP_REPORT_RECORDED_EVENT_TYPE = "cleanup.report.recorded"
CLEANUP_RESULT_RECORDED_EVENT_TYPE = "cleanup.result.recorded"


def cleanup_report_event(fact: CleanupReportFact) -> PipelineEvent:
    """Project a recorded cleanup report fact into a compact audit event."""

    return PipelineEvent(
        scope=EventScope.run(),
        event_type=CLEANUP_REPORT_RECORDED_EVENT_TYPE,
        timestamp=fact.recorded_at,
        payload={
            "fact_type": "cleanup_report",
            "report_id": fact.report_id,
            "run_uri": fact.run_uri,
            "revision": fact.revision.to_dict(),
            "dry_run": fact.report.dry_run,
            "summary": _plain_mapping(fact.report.summary),
        },
    )


def cleanup_result_event(fact: CleanupResultFact) -> PipelineEvent:
    """Project a recorded cleanup result fact into a compact audit event."""

    return PipelineEvent(
        scope=EventScope.run(),
        event_type=CLEANUP_RESULT_RECORDED_EVENT_TYPE,
        timestamp=fact.recorded_at,
        payload={
            "fact_type": "cleanup_result",
            "result_id": fact.result_id,
            "run_uri": fact.run_uri,
            "intent_id": fact.result.intent.intent_id,
            "revision": fact.revision.to_dict(),
            "summary": _plain_mapping(fact.result.summary),
        },
    )


def emit_cleanup_report_event(
    store: PerRunAuthorityStore,
    fact: CleanupReportFact,
    *,
    event_dispatcher: RuntimeEventDispatcher | None = None,
) -> PipelineEventRecord | EventReference:
    """Append or dispatch the audit event for a cleanup report fact."""

    return _emit_cleanup_event(
        store,
        run_uri=fact.run_uri,
        event=cleanup_report_event(fact),
        event_dispatcher=event_dispatcher,
    )


def emit_cleanup_result_event(
    store: PerRunAuthorityStore,
    fact: CleanupResultFact,
    *,
    event_dispatcher: RuntimeEventDispatcher | None = None,
) -> PipelineEventRecord | EventReference:
    """Append or dispatch the audit event for a cleanup result fact."""

    return _emit_cleanup_event(
        store,
        run_uri=fact.run_uri,
        event=cleanup_result_event(fact),
        event_dispatcher=event_dispatcher,
    )


def _emit_cleanup_event(
    store: PerRunAuthorityStore,
    *,
    run_uri: str,
    event: PipelineEvent,
    event_dispatcher: RuntimeEventDispatcher | None,
) -> PipelineEventRecord | EventReference:
    if event_dispatcher is None:
        return store.append_audit_event(run_uri, event)
    return event_dispatcher.emit(
        _CleanupEventStoreAdapter(store),
        run_uri=run_uri,
        event=event,
    )


@dataclass(slots=True)
class _CleanupEventStoreAdapter:
    store: PerRunAuthorityStore

    def append_event(
        self,
        run_uri: str,
        event: PipelineEvent,
    ) -> PipelineEventRecord:
        return self.store.append_audit_event(run_uri, event)

    def read_events(self, run_uri: str) -> tuple[PipelineEventRecord, ...]:
        return ()

    def append_event_sink_failure(self, run_uri: str, failure: object) -> object:
        return self.store.append_event_sink_failure(
            run_uri,
            EventSinkFailureRecord.from_dict(failure),
        )

    def append_event_observer_link(self, run_uri: str, link: object) -> object:
        return self.store.append_event_observer_link(
            run_uri,
            EventObserverLinkRecord.from_dict(link),
        )


def _plain_mapping(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    thawed = thaw_plain_data(value, path="summary")
    if isinstance(thawed, dict):
        return cast(dict[str, PlainData], thawed)
    return {}


__all__ = [
    "CLEANUP_REPORT_RECORDED_EVENT_TYPE",
    "CLEANUP_RESULT_RECORDED_EVENT_TYPE",
    "cleanup_report_event",
    "cleanup_result_event",
    "emit_cleanup_report_event",
    "emit_cleanup_result_event",
]
