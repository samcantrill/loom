"""Unit tests for pipeline event models."""

from typing import Any, cast

import pytest

from loom.pipeline.events import (
    EventScope,
    EventScopeKind,
    PipelineEvent,
    PipelineEventError,
    PipelineEventRecord,
)
from loom.timestamps import utc_timestamp


def test_event_scope_round_trips_run_and_stage_scopes() -> None:
    assert EventScope.run().to_dict() == {"kind": "RUN", "stage_name": None}
    assert EventScope.from_dict({"kind": "RUN", "stage_name": None}) == EventScope.run()
    assert EventScope.stage("build").to_dict() == {
        "kind": "STAGE",
        "stage_name": "build",
    }
    assert EventScope.from_dict(
        {"kind": "STAGE", "stage_name": "build"}
    ) == EventScope.stage("build")


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "RUN", "stage_name": "build"},
        {"kind": "STAGE", "stage_name": None},
        {"kind": "BAD", "stage_name": None},
        {"kind": "RUN", "stage_name": None, "extra": True},
    ],
)
def test_event_scope_rejects_invalid_shapes(payload: dict[str, object]) -> None:
    with pytest.raises(PipelineEventError):
        EventScope.from_dict(payload)


def test_pipeline_event_validates_payload_and_optional_timestamp() -> None:
    timestamp = utc_timestamp()
    payload: dict[str, Any] = {"labels": ["x"]}
    event = PipelineEvent(
        scope=EventScope.stage("build"),
        event_type="stage.started",
        payload=payload,
        timestamp=timestamp,
    )
    payload["labels"].append("mutated")

    assert event.payload == {"labels": ("x",)}
    assert event.to_dict() == {
        "scope": {"kind": "STAGE", "stage_name": "build"},
        "event_type": "stage.started",
        "payload": {"labels": ["x"]},
        "timestamp": timestamp,
    }
    with pytest.raises(TypeError):
        cast(Any, event.payload)["labels"] = ["changed"]


@pytest.mark.parametrize(
    "event_type", ["", ".bad", "bad.", "bad..name", "Stage.Started"]
)
def test_pipeline_event_rejects_invalid_event_types(event_type: str) -> None:
    with pytest.raises(PipelineEventError):
        PipelineEvent(scope=EventScope.run(), event_type=event_type)


def test_pipeline_event_record_round_trips() -> None:
    timestamp = utc_timestamp()
    record = PipelineEventRecord(
        run_uri="run1",
        sequence=1,
        timestamp=timestamp,
        scope=EventScope.stage("build"),
        event_type="stage.blocked",
        payload={"reason": "upstream"},
    )

    assert record.to_dict() == {
        "schema_version": 1,
        "run_uri": "run1",
        "sequence": 1,
        "timestamp": timestamp,
        "scope": {"kind": "STAGE", "stage_name": "build"},
        "event_type": "stage.blocked",
        "payload": {"reason": "upstream"},
    }
    assert PipelineEventRecord.from_dict(record.to_dict()) == record


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2},
        {
            "schema_version": 1,
            "run_uri": "run1",
            "sequence": 0,
            "timestamp": utc_timestamp(),
            "scope": {"kind": "RUN", "stage_name": None},
            "event_type": "run.created",
            "payload": {},
        },
        {
            "schema_version": 1,
            "run_uri": "run1",
            "sequence": 1,
            "timestamp": "not-a-timestamp",
            "scope": {"kind": "RUN", "stage_name": None},
            "event_type": "run.created",
            "payload": {},
        },
        {
            "schema_version": 1,
            "run_uri": "run1",
            "sequence": 1,
            "timestamp": utc_timestamp(),
            "scope": {"kind": "RUN", "stage_name": None},
            "event_type": "bad..type",
            "payload": {},
        },
        {
            "schema_version": 1,
            "run_uri": "run1",
            "sequence": 1,
            "timestamp": utc_timestamp(),
            "scope": {"kind": "RUN", "stage_name": None},
            "event_type": "run.created",
            "payload": {},
            "extra": True,
        },
    ],
)
def test_pipeline_event_record_rejects_invalid_payloads(
    payload: dict[str, object],
) -> None:
    with pytest.raises(PipelineEventError):
        PipelineEventRecord.from_dict(payload)


def test_pipeline_event_rejects_non_plain_payload() -> None:
    with pytest.raises(PipelineEventError):
        PipelineEvent(
            scope=EventScope.run(),
            event_type="run.created",
            payload=cast(Any, {"bad": object()}),
        )


def test_scope_kind_is_public_enum() -> None:
    assert EventScopeKind.RUN.value == "RUN"
    assert EventScopeKind.STAGE.value == "STAGE"
