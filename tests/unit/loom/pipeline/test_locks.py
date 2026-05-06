"""Unit tests for run lock record models."""

from types import MappingProxyType
from typing import Any, cast

import pytest

from loom.pipeline.locks import (
    LOCK_SCHEMA_VERSION,
    RunLockRecord,
    RunLockValidationError,
)


def test_run_lock_record_round_trips_plain_data() -> None:
    owner = {"worker": "local", "nested": {"attempt": 1}}

    record = RunLockRecord(
        run_uri="run1",
        token="abc123",
        acquired_at="2020-01-01T00:00:00Z",
        owner=owner,
    )

    assert record.schema_version == LOCK_SCHEMA_VERSION
    assert isinstance(record.owner, MappingProxyType)
    assert record.to_dict() == {
        "schema_version": 1,
        "run_uri": "run1",
        "token": "abc123",
        "acquired_at": "2020-01-01T00:00:00Z",
        "owner": owner,
    }
    assert RunLockRecord.from_dict(record.to_dict()) == record


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "schema_version": 2,
            "run_uri": "run1",
            "token": "abc123",
            "acquired_at": "2020-01-01T00:00:00Z",
            "owner": {},
        },
        {
            "schema_version": 1,
            "run_uri": "",
            "token": "abc123",
            "acquired_at": "2020-01-01T00:00:00Z",
            "owner": {},
        },
        {
            "schema_version": 1,
            "run_uri": "run1",
            "token": "",
            "acquired_at": "2020-01-01T00:00:00Z",
            "owner": {},
        },
        {
            "schema_version": 1,
            "run_uri": "run1",
            "token": "abc123",
            "acquired_at": "not-a-timestamp",
            "owner": {},
        },
        {
            "schema_version": 1,
            "run_uri": "run1",
            "token": "abc123",
            "acquired_at": "2020-01-01T00:00:00Z",
            "owner": [],
        },
        {
            "schema_version": 1,
            "run_uri": "run1",
            "token": "abc123",
            "acquired_at": "2020-01-01T00:00:00Z",
            "owner": {},
            "extra": True,
        },
    ],
)
def test_run_lock_record_rejects_malformed_payloads(payload: object) -> None:
    with pytest.raises(RunLockValidationError):
        RunLockRecord.from_dict(payload)


def test_run_lock_record_rejects_non_plain_owner() -> None:
    with pytest.raises(RunLockValidationError, match="owner"):
        RunLockRecord(
            run_uri="run1",
            token="abc123",
            acquired_at="2020-01-01T00:00:00Z",
            owner=cast(Any, {"bad": object()}),
        )
