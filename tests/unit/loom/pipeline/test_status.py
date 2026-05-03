"""Unit tests for status models and serialization helpers."""

from datetime import datetime, timezone

import pytest

from loom.pipeline.errors import StatusSerializationError
from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus, StageStatusRecord, parse_run_status, parse_stage_status
from loom.timestamps import utc_timestamp


def _ts(value: str) -> str:
    return utc_timestamp(datetime.fromisoformat(value).replace(tzinfo=timezone.utc))


def _common_ts() -> tuple[str, str]:
    return _ts("2026-01-01T00:00:00"), _ts("2026-01-01T00:01:00")


def test_run_status_parse() -> None:
    assert parse_run_status("SUCCEEDED") is RunStatus.SUCCEEDED
    assert parse_stage_status("FAILED") is StageStatus.FAILED


def test_run_status_round_trip() -> None:
    created, updated = _common_ts()
    record = RunStatusRecord(
        run_id="run-1",
        status=RunStatus.RUNNING,
        created_at=created,
        updated_at=updated,
        message="running",
        metadata={"x": 1},
    )
    payload = record.to_dict()
    assert payload["status"] == "RUNNING"
    assert RunStatusRecord.from_dict(payload) == record


def test_stage_status_round_trip_and_owner_metadata() -> None:
    _, updated = _common_ts()
    record = StageStatusRecord(
        run_id="run-1",
        stage_name="build",
        status=StageStatus.SUCCEEDED,
        updated_at=updated,
        message=None,
        attempt=3,
        owner={"owner": "agent"},
        metadata={"m": "n"},
    )
    payload = record.to_dict()
    assert payload["status"] == "SUCCEEDED"
    assert payload["stage_name"] == "build"
    assert payload["attempt"] == 3
    assert "stage_id" not in payload
    assert "attempts" not in payload
    assert StageStatusRecord.from_dict(payload) == record


def test_status_record_rejects_invalid_schema_version() -> None:
    created, updated = _common_ts()
    payload = {
        "run_id": "run-1",
        "status": "RUNNING",
        "created_at": created,
        "updated_at": updated,
        "schema_version": 999,
    }
    with pytest.raises(StatusSerializationError, match="unsupported schema_version"):
        RunStatusRecord.from_dict(payload)


def test_status_record_rejects_non_timestamp() -> None:
    with pytest.raises(StatusSerializationError, match="timestamp"):
        StageStatusRecord.from_dict(
            {
                "run_id": "run-1",
                "stage_name": "build",
                "status": "SUCCEEDED",
                "updated_at": "not-a-timestamp",
                "schema_version": 1,
                "attempt": 1,
            },
        )


def test_status_record_rejects_bad_attempts() -> None:
    _, updated = _common_ts()
    with pytest.raises(StatusSerializationError, match="positive integer"):
        StageStatusRecord.from_dict(
            {
                "run_id": "run-1",
                "stage_name": "build",
                "status": "SUCCEEDED",
                "updated_at": updated,
                "schema_version": 1,
                "attempt": 0,
            },
        )
