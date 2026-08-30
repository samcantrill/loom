from __future__ import annotations

import json
from types import SimpleNamespace

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
from loom.diagnostics.run_inspection import MAX_INSPECTION_RESPONSE_BYTES


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
    dispatch_handle: object | None = None

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
        axes=_all_axes(
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
        stages=(RunInspectionStage("train", "SUCCEEDED", 1, "stage.completed"),),
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
        truncation=(
            RunInspectionTruncation("stages", 1, 1),
            RunInspectionTruncation("locations", 1, 1),
        ),
        queue_item_id="queue-1",
        admission_id="admission-1",
    )
    assert RunInspectionResult.from_dict(result.to_dict()) == result
    payload = result.to_dict()
    payload["secret"] = "must not pass"
    with pytest.raises(ValueError, match="fields"):
        RunInspectionResult.from_dict(payload)
    payload = result.to_dict()
    payload["axes"] = payload["axes"][:-1]  # type: ignore[index]
    with pytest.raises(ValueError, match="every run inspection axis"):
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
    assert isinstance(result, RunInspectionResult)
    assert result.queue_item_id == "item-1"
    assert _axis(result, RunInspectionAxisName.ADMISSION).state == "QUEUED"


def test_service_less_missing_reference_is_explicit_without_queue_read() -> None:
    queue = _ExactQueue()
    result = RunInspectionProjection(
        run_store=_ServiceLessStore(_Operation(None)), queue_service=queue
    ).inspect("file:///tmp/run")
    assert queue.ids == []
    assert isinstance(result, RunInspectionResult)
    assert (
        _axis(result, RunInspectionAxisName.ADMISSION).code == "queue_reference_missing"
    )


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
    assert isinstance(result, RunInspectionResult)
    assert result.queue_item_id == "item-1"
    assert (
        _axis(result, RunInspectionAxisName.ADMISSION).code
        == "queue_reference_mismatch"
    )


def test_known_run_remains_inspectable_when_authority_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Store(_ServiceLessStore):
        def open_run(self, run_uri: str) -> None:
            assert run_uri == "file:///tmp/run"

    def unavailable(*args: object, **kwargs: object) -> object:
        raise RuntimeError("SECRET_AUTHORITY_FAILURE")

    monkeypatch.setattr(
        "loom.diagnostics.inspection._authoritative_read",
        unavailable,
    )
    result = RunInspectionProjection(run_store=Store(None)).inspect("file:///tmp/run")

    assert isinstance(result, RunInspectionResult)
    lifecycle = _axis(result, RunInspectionAxisName.LIFECYCLE)
    assert lifecycle.availability == "unavailable"
    assert lifecycle.code == "authority_unavailable"
    assert "SECRET_AUTHORITY_FAILURE" not in json.dumps(result.to_dict())


def test_authority_lifecycle_wins_a_disagreeing_managed_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ServiceLessStore(None)
    snapshot = SimpleNamespace(
        status=SimpleNamespace(value="SUCCEEDED"),
        revision=SimpleNamespace(
            sequence=7,
            created_at="2026-08-30T00:00:00Z",
        ),
        stages=(
            SimpleNamespace(
                stage_name="train",
                status=SimpleNamespace(value="SUCCEEDED"),
                attempts=(),
                artifact_facts=(),
                reason=SimpleNamespace(code="stage.completed"),
            ),
        ),
    )
    monkeypatch.setattr(
        "loom.diagnostics.inspection._authoritative_read",
        lambda *args, **kwargs: SimpleNamespace(
            snapshot=snapshot,
            local_store=store,
        ),
    )

    class Daemon:
        def admission_for_run_uri(self, run_uri: str) -> object:
            assert run_uri == "file:///tmp/run"
            return SimpleNamespace(
                admission_id="admission-1",
                queue_item_id="queue-1",
                state=SimpleNamespace(value="FAILED"),
                accepted_at="2026-08-30T00:00:00Z",
            )

        def admission(self, admission_id: str) -> object:
            assert admission_id == "admission-1"
            raise RuntimeError("SECRET_OWNER_FAILURE")

    result = RunInspectionProjection(run_store=store, daemon=Daemon()).inspect(
        "file:///tmp/run"
    )

    assert isinstance(result, RunInspectionResult)
    assert result.summary == "SUCCEEDED"
    assert _axis(result, RunInspectionAxisName.LIFECYCLE).state == "SUCCEEDED"
    assert _axis(result, RunInspectionAxisName.ADMISSION).state == "FAILED"
    assert result.stages == (
        RunInspectionStage("train", "SUCCEEDED", code="stage.completed"),
    )
    assert result.admission_id == "admission-1"
    assert result.queue_item_id == "queue-1"
    assert "SECRET_OWNER_FAILURE" not in json.dumps(result.to_dict())


def test_projection_truncates_257_locations_in_stable_order() -> None:
    class Artifact:
        artifact_type = "json"
        checksum = None

        def __init__(self, index: int) -> None:
            self.uri = f"file:///artifacts/{index:03d}"

    class Store(_ServiceLessStore):
        def __init__(self) -> None:
            super().__init__(None)

        def open_run(self, run_uri: str) -> None:
            assert run_uri == "file:///tmp/run"

        def read_artifact_index(self, run_uri: str) -> dict[str, object]:
            return {
                f"item-{index:03d}": Artifact(index) for index in reversed(range(257))
            }

    result = RunInspectionProjection(run_store=Store()).inspect("file:///tmp/run")

    assert isinstance(result, RunInspectionResult)
    assert len(result.locations) == 256
    assert result.locations[0].logical_id == "artifact:item-000"
    assert result.locations[-1].logical_id == "artifact:item-255"
    truncation = next(
        item for item in result.truncation if item.collection == "locations"
    )
    assert truncation.total_count == 257
    assert truncation.returned_count == 256


def test_projection_enforces_response_budget_without_reading_content() -> None:
    class Artifact:
        artifact_type = "json"
        checksum = None

        def __init__(self, index: int) -> None:
            self.uri = f"file:///artifacts/{index}-" + "x" * 6_000

    class Store(_ServiceLessStore):
        def __init__(self) -> None:
            super().__init__(None)
            self.content_reads = 0

        def read_artifact_index(self, run_uri: str) -> dict[str, object]:
            return {f"artifact-{index:03d}": Artifact(index) for index in range(256)}

        def read_artifact(self, *args: object) -> bytes:
            self.content_reads += 1
            raise AssertionError("artifact content must not be read")

        def read_stage_log(self, *args: object) -> str:
            self.content_reads += 1
            raise AssertionError("log content must not be read")

    store = Store()
    result = RunInspectionProjection(run_store=store).inspect("file:///tmp/run")

    assert isinstance(result, RunInspectionResult)
    encoded = json.dumps(
        {"ok": True, "result": result.to_dict()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(encoded) <= MAX_INSPECTION_RESPONSE_BYTES
    locations = next(
        item for item in result.truncation if item.collection == "locations"
    )
    assert locations.total_count == 256
    assert locations.returned_count < locations.total_count
    assert store.content_reads == 0


def _axis(
    result: RunInspectionResult,
    name: RunInspectionAxisName,
) -> RunInspectionAxis:
    return next(axis for axis in result.axes if axis.name is name)


def _all_axes(*overrides: RunInspectionAxis) -> tuple[RunInspectionAxis, ...]:
    selected = {axis.name: axis for axis in overrides}
    return tuple(
        selected.get(
            name,
            RunInspectionAxis(
                name,
                "unavailable",
                "unavailable",
                "unavailable",
                None,
                None,
                "unavailable",
                "owner_unavailable",
            ),
        )
        for name in RunInspectionAxisName
    )
