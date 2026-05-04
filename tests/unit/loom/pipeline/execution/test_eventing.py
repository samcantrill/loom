"""Unit tests for execution lifecycle event helpers."""

from pathlib import Path

from loom.pipeline.execution.eventing import emit_run_event, emit_stage_event
from loom.pipeline.events import EventScopeKind
from loom.pipeline.stores import LocalRunStore


def test_emit_run_event_uses_explicit_timestamp_and_payload(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    store.create_run("run1")

    record = emit_run_event(
        store,
        run_id="run1",
        event_type="run.started",
        timestamp="2020-01-01T00:00:00Z",
        payload={"stage_count": 2},
    )

    assert record.sequence == 1
    assert record.timestamp == "2020-01-01T00:00:00Z"
    assert record.scope.kind is EventScopeKind.RUN
    assert record.event_type == "run.started"
    assert record.payload == {"stage_count": 2}


def test_emit_stage_event_records_stage_scope(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    store.create_run("run1")

    record = emit_stage_event(
        store,
        run_id="run1",
        stage_name="build",
        event_type="stage.completed",
        timestamp="2020-01-01T00:00:00Z",
        payload={"attempt": 1, "status": "SUCCEEDED"},
    )

    assert record.scope.kind is EventScopeKind.STAGE
    assert record.scope.stage_name == "build"
    assert record.event_type == "stage.completed"
    assert record.payload == {"attempt": 1, "status": "SUCCEEDED"}
