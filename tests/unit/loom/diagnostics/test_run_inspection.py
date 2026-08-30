from __future__ import annotations

import pytest

from loom.diagnostics import (
    RunInspectionAxis,
    RunInspectionAxisName,
    RunInspectionFailure,
    RunInspectionFailureCode,
    RunInspectionLocation,
    RunInspectionResult,
    RunInspectionStage,
    RunInspectionTruncation,
    RunLocationReachability,
    decode_run_inspection_response,
    inspect_run,
)
from loom.diagnostics.run_inspection import RunInspectionProjection


class _ServiceLessStore:
    authority_store = None

    def __init__(self, operation: object | None) -> None:
        self.local_store = self
        self._operation = operation

    def read_artifact_index(self, run_uri: str) -> dict[str, object]:
        return {}

    def latest_submitted_operation(self, run_uri: str) -> object | None:
        return self._operation


class _Operation:
    backend = "other"
    updated_at = "2026-08-30T00:00:00Z"

    def __init__(self, queue_item_id: str | None) -> None:
        self.backend_metadata = (
            {} if queue_item_id is None else {"queue": {"queue_item_id": queue_item_id}}
        )


class _QueueItem:
    run_uri = "file:///tmp/run"
    dispatch_attempt = 1
    updated_at = "2026-08-30T00:00:00Z"
    dispatch_handle = None

    class status:
        value = "QUEUED"


class _ExactQueue:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def read_item(self, queue_item_id: str) -> _QueueItem:
        self.ids.append(queue_item_id)
        return _QueueItem()


def test_result_codec_is_strict_and_round_trips() -> None:
    result = RunInspectionResult(
        run_uri="file:///tmp/run",
        as_of="2026-08-30T00:00:00Z",
        summary="SUCCEEDED",
        axes=(
            RunInspectionAxis(
                RunInspectionAxisName.LIFECYCLE,
                "authority",
                "available",
                "SUCCEEDED",
                3,
                "2026-08-30T00:00:00Z",
                "current",
            ),
        ),
        stages=(RunInspectionStage("train", "SUCCEEDED", 1),),
        locations=(
            RunInspectionLocation(
                "artifact:train:model",
                "file:///tmp/model",
                "artifact",
                "recorded",
                "model",
                "sha256:abc",
                RunLocationReachability.COORDINATOR_LOCAL,
            ),
        ),
        truncation=(RunInspectionTruncation("stages", 1, 1),),
    )
    assert RunInspectionResult.from_dict(result.to_dict()) == result
    payload = result.to_dict()
    payload["secret"] = "must not pass"
    with pytest.raises(ValueError, match="fields"):
        RunInspectionResult.from_dict(payload)


def test_closed_failure_contains_no_run_facts() -> None:
    result = inspect_run("not-a-uri")
    assert result == RunInspectionFailure(RunInspectionFailureCode.INVALID_REQUEST)
    assert decode_run_inspection_response(result.to_dict()) == result
    assert set(result.to_dict()) == {"schema_version", "code"}


def test_result_rejects_more_than_the_fixed_collection_limit() -> None:
    with pytest.raises(ValueError, match="at most 256"):
        RunInspectionResult(
            run_uri="file:///tmp/run",
            as_of="2026-08-30T00:00:00Z",
            summary="unknown",
            axes=(),
            stages=tuple(
                RunInspectionStage(f"stage-{index}", "UNKNOWN") for index in range(257)
            ),
            locations=(),
            truncation=(),
        )


def test_service_less_projection_uses_the_retained_exact_queue_item_only() -> None:
    queue = _ExactQueue()
    result = RunInspectionProjection(
        run_store=_ServiceLessStore(_Operation("item-1")), queue_service=queue
    ).inspect("file:///tmp/run")
    assert queue.ids == ["item-1"]
    assert result.axes[0].state == "QUEUED"  # type: ignore[union-attr]


def test_service_less_missing_reference_is_explicit_without_queue_read() -> None:
    queue = _ExactQueue()
    result = RunInspectionProjection(
        run_store=_ServiceLessStore(_Operation(None)), queue_service=queue
    ).inspect("file:///tmp/run")
    assert queue.ids == []
    assert result.axes[0].code == "queue_reference_missing"  # type: ignore[union-attr]


def test_service_less_rejects_a_mismatched_dispatch_handle_reference() -> None:
    item = _QueueItem()

    class Handle:
        dispatch_attempt = 1
        dispatched_at = "2026-08-30T00:00:00Z"
        evidence = {"queue_item_id": "other-item"}

    item.dispatch_handle = Handle()

    class Queue:
        def read_item(self, queue_item_id: str) -> _QueueItem:
            return item

    result = RunInspectionProjection(
        run_store=_ServiceLessStore(_Operation("item-1")), queue_service=Queue()
    ).inspect("file:///tmp/run")
    assert result == RunInspectionFailure(RunInspectionFailureCode.NOT_FOUND)
