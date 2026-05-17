"""Unit tests for execution lifecycle event helpers."""

from pathlib import Path

from loom.pipeline.event_sinks import (
    EventObserverExternalRef,
    EventObserverLinkRecord,
    EventSinkContext,
    EventSinkRegistry,
)
from loom.pipeline.execution.eventing import (
    RuntimeEventDispatcher,
    emit_run_event,
    emit_stage_event,
)
from loom.pipeline.events import EventReference, EventScopeKind, PipelineEventRecord
from loom.pipeline.stores import LocalRunStore, path_to_run_uri


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def test_emit_run_event_uses_explicit_timestamp_and_payload(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    record = emit_run_event(
        store,
        run_uri=run_uri,
        event_type="run.started",
        timestamp="2020-01-01T00:00:00Z",
        payload={"stage_count": 2},
    )

    assert isinstance(record, PipelineEventRecord)
    assert record.sequence == 1
    assert record.timestamp == "2020-01-01T00:00:00Z"
    assert record.scope.kind is EventScopeKind.RUN
    assert record.event_type == "run.started"
    assert record.payload == {"stage_count": 2}


def test_emit_stage_event_records_stage_scope(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    record = emit_stage_event(
        store,
        run_uri=run_uri,
        stage_name="build",
        event_type="stage.completed",
        timestamp="2020-01-01T00:00:00Z",
        payload={"attempt": 1, "status": "SUCCEEDED"},
    )

    assert isinstance(record, PipelineEventRecord)
    assert record.scope.kind is EventScopeKind.STAGE
    assert record.scope.stage_name == "build"
    assert record.event_type == "stage.completed"
    assert record.payload == {"attempt": 1, "status": "SUCCEEDED"}


def test_durable_dispatch_happens_after_event_append(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    registry = EventSinkRegistry()
    observed: list[PipelineEventRecord] = []

    def sink(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        assert isinstance(event, PipelineEventRecord)
        assert store.read_events(run_uri) == (event,)
        assert context.event_reference == event.to_event_reference()
        observed.append(event)

    registry.register("audit.capture", sink)
    dispatcher = RuntimeEventDispatcher(registry=registry)

    record = emit_run_event(
        store,
        run_uri=run_uri,
        event_type="run.started",
        timestamp="2020-01-01T00:00:00Z",
        payload={"stage_count": 1},
        event_dispatcher=dispatcher,
    )

    assert record == observed[0]
    assert store.read_event_sink_failures(run_uri) == ()


def test_dispatch_records_observer_links_and_callback_failures(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    registry = EventSinkRegistry()
    calls: list[str] = []

    def linking_sink(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        calls.append("link")
        context.record_event_observer_link(
            EventObserverLinkRecord(
                sink_name="audit.link",
                run_uri=context.run_uri,
                event_reference=context.event_reference,
                recorded_at="2020-01-01T00:00:01Z",
                external_ref=EventObserverExternalRef(
                    kind="trace",
                    identifiers={"trace_id": "trace-1"},
                ),
            )
        )

    def failing_sink(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        _ = event, context
        calls.append("fail")
        raise RuntimeError("callback failed")

    def later_sink(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        _ = event, context
        calls.append("later")

    registry.register("audit.link", linking_sink)
    registry.register("audit.fail", failing_sink)
    registry.register("audit.later", later_sink)
    dispatcher = RuntimeEventDispatcher(registry=registry)

    record = emit_stage_event(
        store,
        run_uri=run_uri,
        stage_name="build",
        event_type="stage.completed",
        timestamp="2020-01-01T00:00:00Z",
        payload={"attempt": 1},
        event_dispatcher=dispatcher,
    )

    assert isinstance(record, PipelineEventRecord)
    assert calls == ["link", "fail", "later"]
    assert [link.sink_name for link in store.read_event_observer_links(run_uri)] == [
        "audit.link"
    ]
    failures = store.read_event_sink_failures(run_uri)
    assert len(failures) == 1
    assert failures[0].sink_name == "audit.fail"
    assert failures[0].event_reference == record.to_event_reference()


def test_non_durable_dispatch_uses_dispatch_sequence_and_warning(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    registry = EventSinkRegistry()
    observed: list[EventReference] = []

    def sink(
        event: PipelineEventRecord | EventReference,
        context: EventSinkContext,
    ) -> None:
        assert isinstance(event, EventReference)
        assert context.event_reference == event
        observed.append(event)

    registry.register("audit.capture", sink)
    dispatcher = RuntimeEventDispatcher(
        registry=registry,
        persistence="non_durable",
    )

    reference = emit_run_event(
        store,
        run_uri=run_uri,
        event_type="run.started",
        timestamp="2020-01-01T00:00:00Z",
        event_dispatcher=dispatcher,
    )

    assert isinstance(reference, EventReference)
    assert observed == [reference]
    assert reference.durability == "non_durable"
    assert reference.sequence is None
    assert reference.dispatch_sequence == 1
    assert store.read_events(run_uri) == ()
    assert dispatcher.warnings[0].to_dict()["code"] == "event_persistence.non_durable"
