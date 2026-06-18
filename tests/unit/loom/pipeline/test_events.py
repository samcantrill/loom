"""Unit tests for pipeline event models."""

from typing import Any, cast

import pytest

from loom.pipeline.events import (
    EVENT_SCHEMA_VERSION,
    LEGACY_EVENT_SCHEMA_VERSION,
    EventReference,
    EventResourceRef,
    EventScope,
    EventScopeKind,
    PipelineEvent,
    PipelineEventError,
    PipelineEventRecord,
    compatibility_event_id,
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


def test_event_resource_ref_round_trips_run_and_stage() -> None:
    run = EventResourceRef.run("run1")
    stage = EventResourceRef.stage("run1", "build")

    assert run.to_dict() == {"kind": "run", "identifiers": {"run_uri": "run1"}}
    assert stage.to_dict() == {
        "kind": "stage",
        "identifiers": {"run_uri": "run1", "stage_name": "build"},
    }
    assert EventResourceRef.from_dict(stage.to_dict()) == stage


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "Stage", "identifiers": {"run_uri": "run1"}},
        {"kind": "stage", "identifiers": {}},
        {"kind": "stage", "identifiers": {"bad": object()}},
        {"kind": "stage", "identifiers": {"run_uri": "run1"}, "extra": True},
    ],
)
def test_event_resource_ref_rejects_invalid_shapes(payload: dict[str, object]) -> None:
    with pytest.raises(PipelineEventError):
        EventResourceRef.from_dict(payload)


def test_event_reference_round_trips_durable_reference() -> None:
    timestamp = utc_timestamp()
    reference = EventReference(
        event_id="evt1",
        run_uri="run1",
        event_type="run.created",
        occurred_at=timestamp,
        durability="durable",
        sequence=1,
    )

    assert reference.to_dict() == {
        "event_id": "evt1",
        "run_uri": "run1",
        "event_type": "run.created",
        "occurred_at": timestamp,
        "durability": "durable",
        "sequence": 1,
    }
    assert EventReference.from_dict(reference.to_dict()) == reference


def test_event_reference_accepts_non_durable_shape_for_future_envelopes() -> None:
    timestamp = utc_timestamp()

    reference = EventReference.from_dict(
        {
            "event_id": "evt1",
            "run_uri": "run1",
            "event_type": "run.created",
            "occurred_at": timestamp,
            "durability": "non_durable",
            "dispatch_sequence": 1,
        }
    )

    assert reference.sequence is None
    assert reference.dispatch_sequence == 1


@pytest.mark.parametrize(
    "payload",
    [
        {
            "event_id": "evt1",
            "run_uri": "run1",
            "event_type": "run.created",
            "occurred_at": utc_timestamp(),
            "durability": "durable",
            "dispatch_sequence": 1,
        },
        {
            "event_id": "evt1",
            "run_uri": "run1",
            "event_type": "run.created",
            "occurred_at": utc_timestamp(),
            "durability": "non_durable",
            "sequence": 1,
        },
        {
            "event_id": "evt1",
            "run_uri": "run1",
            "event_type": "run.created",
            "occurred_at": utc_timestamp(),
            "durability": "unknown",
            "sequence": 1,
        },
    ],
)
def test_event_reference_rejects_invalid_durability(payload: dict[str, object]) -> None:
    with pytest.raises(PipelineEventError):
        EventReference.from_dict(payload)


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


def test_pipeline_event_record_round_trips_schema_v2() -> None:
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
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": compatibility_event_id("run1", 1),
        "run_uri": "run1",
        "sequence": 1,
        "occurred_at": timestamp,
        "event_type": "stage.blocked",
        "primary_resource": {
            "kind": "stage",
            "identifiers": {"run_uri": "run1", "stage_name": "build"},
        },
        "related_resources": [{"kind": "run", "identifiers": {"run_uri": "run1"}}],
        "payload": {"reason": "upstream"},
    }
    assert record.timestamp == timestamp
    assert record.scope == EventScope.stage("build")
    assert PipelineEventRecord.from_dict(record.to_dict()) == record
    assert record.to_event_reference() == EventReference(
        event_id=record.event_id,
        run_uri="run1",
        event_type="stage.blocked",
        occurred_at=timestamp,
        durability="durable",
        sequence=1,
    )


def test_pipeline_event_record_projects_schema_v1_without_rewriting_shape() -> None:
    timestamp = utc_timestamp()
    legacy = {
        "schema_version": LEGACY_EVENT_SCHEMA_VERSION,
        "run_uri": "run1",
        "sequence": 2,
        "timestamp": timestamp,
        "scope": {"kind": "STAGE", "stage_name": "build"},
        "event_type": "stage.started",
        "payload": {"source": "legacy"},
    }

    record = PipelineEventRecord.from_dict(legacy)

    assert record.schema_version == EVENT_SCHEMA_VERSION
    assert record.event_id == compatibility_event_id("run1", 2)
    assert record.occurred_at == timestamp
    assert record.primary_resource == EventResourceRef.stage("run1", "build")
    assert record.related_resources == (EventResourceRef.run("run1"),)
    assert record.payload == {"source": "legacy"}
    assert record.to_schema_v1_dict() == legacy


def test_pipeline_event_record_accepts_causal_predecessor_reference() -> None:
    timestamp = utc_timestamp()
    predecessor = EventReference(
        event_id="evt0",
        run_uri="run1",
        event_type="run.created",
        occurred_at=timestamp,
        durability="durable",
        sequence=1,
    )

    record = PipelineEventRecord(
        run_uri="run1",
        sequence=2,
        occurred_at=timestamp,
        event_type="run.completed",
        primary_resource=EventResourceRef.run("run1"),
        causal_predecessor=predecessor,
    )

    assert record.to_dict()["causal_predecessor"] == predecessor.to_dict()
    assert PipelineEventRecord.from_dict(record.to_dict()) == record


def test_pipeline_event_record_rejects_invalid_constructor_values() -> None:
    timestamp = utc_timestamp()

    with pytest.raises(PipelineEventError, match="payload"):
        PipelineEventRecord(
            run_uri="run1",
            sequence=1,
            occurred_at=timestamp,
            event_type="run.created",
            payload=cast(Any, []),
        )

    with pytest.raises(PipelineEventError, match="event_id"):
        PipelineEventRecord(
            run_uri="run1",
            sequence=1,
            occurred_at=timestamp,
            event_type="run.created",
            event_id="",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 3},
        {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": "evt1",
            "run_uri": "run1",
            "sequence": 0,
            "occurred_at": utc_timestamp(),
            "event_type": "run.created",
            "primary_resource": {"kind": "run", "identifiers": {"run_uri": "run1"}},
            "related_resources": [],
            "payload": {},
        },
        {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": "evt1",
            "run_uri": "run1",
            "sequence": 1,
            "occurred_at": "not-a-timestamp",
            "event_type": "run.created",
            "primary_resource": {"kind": "run", "identifiers": {"run_uri": "run1"}},
            "related_resources": [],
            "payload": {},
        },
        {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": "evt1",
            "run_uri": "run1",
            "sequence": 1,
            "occurred_at": utc_timestamp(),
            "event_type": "bad..type",
            "primary_resource": {"kind": "run", "identifiers": {"run_uri": "run1"}},
            "related_resources": [],
            "payload": {},
        },
        {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": "evt1",
            "run_uri": "run1",
            "sequence": 1,
            "occurred_at": utc_timestamp(),
            "event_type": "run.created",
            "primary_resource": {"kind": "run", "identifiers": {"run_uri": "run1"}},
            "related_resources": [],
            "payload": {},
            "timestamp": utc_timestamp(),
        },
        {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": "evt1",
            "run_uri": "run1",
            "sequence": 1,
            "occurred_at": utc_timestamp(),
            "event_type": "run.created",
            "primary_resource": {"kind": "run", "identifiers": {"run_uri": "run1"}},
            "related_resources": [],
            "payload": {},
            "causal_predecessor": {
                "kind": "run",
                "identifiers": {"run_uri": "run1"},
                "event_id": "evt0",
                "durability": "durable",
            },
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
