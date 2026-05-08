"""Unit tests for submitted-operation records and predicates."""

from typing import cast

import pytest

from loom.pipeline.submitted import (
    SubmittedOperationError,
    SubmittedOperationRecord,
    SubmittedOperationState,
    latest_active_submitted_operation,
    latest_submitted_operation,
    submitted_stage_metadata,
)


def _record(
    submission_id: str = "sub-1",
    *,
    state: SubmittedOperationState = SubmittedOperationState.SUBMITTED,
    created_at: str = "2020-01-01T00:00:00Z",
    summary_counts: dict[str, int] | None = None,
) -> SubmittedOperationRecord:
    return SubmittedOperationRecord(
        run_uri="file:///tmp/run1",
        submission_id=submission_id,
        backend="test-backend",
        mode="batch",
        created_at=created_at,
        updated_at="2020-01-01T00:00:01Z",
        state=state,
        manifest_relative_path=f"submitted/{submission_id}/manifest.json",
        summary_counts=summary_counts or {},
        backend_metadata={"safe": True},
    )


def test_submitted_operation_record_round_trips_plain_data() -> None:
    record = _record(summary_counts={"submitted": 2})

    payload = record.to_dict()

    assert payload["schema_version"] == 1
    assert SubmittedOperationRecord.from_dict(payload) == record
    assert record.active is True
    assert record.terminal is False


def test_submitted_operation_latest_sort_uses_created_at_then_submission_id() -> None:
    older = _record("b", created_at="2020-01-01T00:00:00Z")
    tie_first = _record("a", created_at="2020-01-01T00:00:01Z")
    tie_last = _record("c", created_at="2020-01-01T00:00:01Z")

    assert latest_submitted_operation((tie_last, older, tie_first)) == tie_last


def test_latest_active_uses_state_or_summary_counts() -> None:
    terminal_with_active_counts = _record(
        "a",
        state=SubmittedOperationState.COMPLETED,
        summary_counts={"submitted": 1},
    )
    inactive_newer = _record(
        "z",
        state=SubmittedOperationState.COMPLETED,
        created_at="2020-01-01T00:00:02Z",
    )

    assert terminal_with_active_counts.active is True
    assert inactive_newer.terminal is True
    assert (
        latest_active_submitted_operation((inactive_newer, terminal_with_active_counts))
        == terminal_with_active_counts
    )


def test_submitted_operation_rejects_unsafe_manifest_path() -> None:
    with pytest.raises(SubmittedOperationError, match="relative"):
        _record().__class__(
            **{**_record().to_dict(), "manifest_relative_path": "/tmp/manifest.json"}
        )

    with pytest.raises(SubmittedOperationError, match="path segments"):
        _record().__class__(
            **{**_record().to_dict(), "manifest_relative_path": "../manifest.json"}
        )

    with pytest.raises(SubmittedOperationError, match="path segments"):
        _record().__class__(
            **{
                **_record().to_dict(),
                "manifest_relative_path": "submitted//manifest.json",
            }
        )

    with pytest.raises(SubmittedOperationError, match="whitespace"):
        _record().__class__(
            **{
                **_record().to_dict(),
                "manifest_relative_path": "submitted/manifest path.json",
            }
        )


def test_submitted_stage_metadata_links_stage_to_record() -> None:
    record = _record()

    metadata = submitted_stage_metadata(
        record=record,
        stage_name="build",
        attempt=2,
        continuation_executor="local",
        stage_metadata={"job_key": "build"},
    )

    submitted = cast(dict[str, object], metadata["submitted_operation"])
    assert submitted["submission_id"] == "sub-1"
    assert submitted["stage_name"] == "build"
    assert submitted["attempt"] == 2
