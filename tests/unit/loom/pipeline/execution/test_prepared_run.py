"""Unit tests for prepared-run metadata safety."""

from __future__ import annotations

import pytest

from loom.pipeline.execution import (
    PREPARED_RUN_CONTINUATION_WHOLE_RUN,
    PREPARED_RUN_SCHEMA_VERSION,
    PreparedRunPayloadError,
    PreparedRunRecord,
    StageWorkerRequest,
)


def _record(**overrides: object) -> PreparedRunRecord:
    kwargs: dict[str, object] = {
        "schema_version": PREPARED_RUN_SCHEMA_VERSION,
        "run_uri": "file:///tmp/run",
        "prepared_at": "2020-01-01T00:00:00Z",
        "executor_name": "local",
        "continuation_type": PREPARED_RUN_CONTINUATION_WHOLE_RUN,
        "plan": {
            "plan_path": "plan.json",
            "plan_digest": "sha256:abc",
            "plan_summary": {"stage_count": 2},
        },
        "config": {
            "composition_manifest_ref": "config/composition_manifest.json",
            "redacted_snapshot_ref": "config/resolved.redacted.yaml",
            "summary": {"source_count": 1},
        },
        "provenance": {"command_ref": "provenance/command.json"},
        "runtime": {
            "document_ref": "runtime.json",
            "executor": "local",
            "stage_count": 2,
            "resource_summary": {"cpu": 1},
        },
        "metadata": {
            "planner": {"kind": "test", "data": {"planning_id": "p1"}},
        },
    }
    kwargs.update(overrides)
    return PreparedRunRecord(**kwargs)  # type: ignore[arg-type]


def test_prepared_run_record_round_trips_safe_plain_data() -> None:
    record = _record()

    assert PreparedRunRecord.from_dict(record.to_dict()) == record
    assert record.to_dict() == {
        "schema_version": 1,
        "run_uri": "file:///tmp/run",
        "prepared_at": "2020-01-01T00:00:00Z",
        "executor_name": "local",
        "continuation_type": "whole_run",
        "plan": {
            "plan_path": "plan.json",
            "plan_digest": "sha256:abc",
            "plan_summary": {"stage_count": 2},
        },
        "config": {
            "composition_manifest_ref": "config/composition_manifest.json",
            "redacted_snapshot_ref": "config/resolved.redacted.yaml",
            "summary": {"source_count": 1},
        },
        "provenance": {"command_ref": "provenance/command.json"},
        "runtime": {
            "document_ref": "runtime.json",
            "executor": "local",
            "stage_count": 2,
            "resource_summary": {"cpu": 1},
        },
        "metadata": {"planner": {"kind": "test", "data": {"planning_id": "p1"}}},
    }


def test_prepared_run_is_not_stage_worker_request_payload() -> None:
    record = _record()

    with pytest.raises(Exception):
        StageWorkerRequest.from_dict(record.to_dict())


@pytest.mark.parametrize(
    ("field", "payload", "expected_category"),
    [
        ("config", {"resolved_config": {"token": "secret"}}, "opaque_payload"),
        ("plan", {"plan_summary": {"resolver_outputs": ["secret"]}}, "unsafe_field"),
        (
            "runtime",
            {"resource_summary": {"environment": {"TOKEN": "secret"}}},
            "unsafe_field",
        ),
        (
            "runtime",
            {"resource_summary": {"scheduler_job_id": "123"}},
            "unsafe_field",
        ),
        (
            "metadata",
            {"adapter": {"kind": "raw", "data": {"raw_adapter_payload": {}}}},
            "unsafe_field",
        ),
        (
            "metadata",
            {
                "facts": {
                    "kind": "scheduler_facts",
                    "data": {"partition": "debug"},
                }
            },
            "unsafe_field",
        ),
    ],
)
def test_prepared_run_rejects_unsafe_payload_categories(
    field: str,
    payload: dict[str, object],
    expected_category: str,
) -> None:
    with pytest.raises(PreparedRunPayloadError) as exc_info:
        _record(**{field: payload})

    assert exc_info.value.category == expected_category


def test_prepared_run_rejects_arbitrary_opaque_metadata() -> None:
    with pytest.raises(PreparedRunPayloadError) as exc_info:
        _record(metadata={"opaque": {"arbitrary": "mapping"}})

    assert exc_info.value.category == "opaque_payload"
    assert exc_info.value.field == "metadata.opaque.arbitrary"


def test_prepared_run_rejects_non_plain_payloads() -> None:
    with pytest.raises(PreparedRunPayloadError) as exc_info:
        _record(plan={"plan_path": object()})  # type: ignore[dict-item]

    assert exc_info.value.category == "plain_data"
