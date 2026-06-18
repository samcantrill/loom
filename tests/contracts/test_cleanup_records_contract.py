"""Contract tests for cleanup public record shapes."""

from __future__ import annotations

from typing import Any, cast

import pytest

from loom.pipeline.cleanup import (
    CollectionCleanupReport,
    CollectionCleanupResult,
    CleanupDeleteIntent,
    CleanupManagedRoot,
    CleanupRecordError,
    CleanupReport,
    CleanupReportEntry,
    CleanupReportEntryStatus,
    CleanupResult,
    CleanupResultEntry,
    CleanupResultOutcome,
    CleanupTargetKind,
    CleanupTargetRef,
    cleanup_result_event,
)
from loom.pipeline.stores import BackendRevision, CleanupResultFact


pytestmark = pytest.mark.contract


def _target() -> CleanupTargetRef:
    return CleanupTargetRef(
        kind=CleanupTargetKind.LOCAL_PATH,
        uri="file:///runs/run-1/tmp/payload",
        target_id="target-1",
        ownership_key="run-1",
        metadata={"loom_owned": True},
    )


def test_cleanup_target_and_managed_root_contract_shapes() -> None:
    target = _target()
    assert target.to_dict() == {
        "schema_version": 1,
        "kind": "local_path",
        "uri": "file:///runs/run-1/tmp/payload",
        "target_id": "target-1",
        "ownership_key": "run-1",
        "metadata": {"loom_owned": True},
    }
    assert CleanupTargetRef.from_dict(target.to_dict()) == target

    root = CleanupManagedRoot(
        root_id="root-1",
        uri="file:///runs/run-1",
        ownership_key="run-1",
        metadata={"owned_by": "loom"},
    )
    assert root.to_dict() == {
        "schema_version": 1,
        "root_id": "root-1",
        "uri": "file:///runs/run-1",
        "ownership_key": "run-1",
        "metadata": {"owned_by": "loom"},
    }
    assert CleanupManagedRoot.from_dict(root.to_dict()) == root


def test_cleanup_report_contract_shape() -> None:
    entry = CleanupReportEntry(
        candidate_id="candidate-1",
        target=_target(),
        status=CleanupReportEntryStatus.SELECTED,
        reason_code="approved",
        message="selected",
        selector_explanations=({"field": "all", "matched": True},),
        safety_decision={"status": "approved"},
    )
    report = CleanupReport(
        report_id="report-1",
        run_uri="file:///runs/run-1",
        created_at="2020-01-01T00:00:00Z",
        entries=(entry,),
        selector={"candidate_kinds": ["staged_payload"]},
        summary={"selected": 1},
    )
    payload = cast(dict[str, Any], report.to_dict())

    assert set(payload.keys()) == {
        "schema_version",
        "report_id",
        "run_uri",
        "created_at",
        "dry_run",
        "selector",
        "entries",
        "summary",
        "metadata",
    }
    assert payload["dry_run"] is True
    assert payload["entries"][0]["status"] == "selected"
    assert CleanupReport.from_dict(payload) == report


def test_cleanup_result_contract_shape_requires_structured_intent() -> None:
    intent = CleanupDeleteIntent(
        intent_id="intent-1",
        requested_by="tester",
        requested_at="2020-01-01T00:00:00Z",
        reason="test cleanup",
        candidate_ids=("candidate-1",),
    )
    result_entry = CleanupResultEntry(
        candidate_id="candidate-1",
        target=_target(),
        outcome=CleanupResultOutcome.DELETED,
        reason_code="deleted",
        completed_at="2020-01-01T00:00:01Z",
    )
    result = CleanupResult(
        result_id="result-1",
        run_uri="file:///runs/run-1",
        created_at="2020-01-01T00:00:01Z",
        intent=intent,
        entries=(result_entry,),
        summary={"deleted": 1},
    )
    payload = cast(dict[str, Any], result.to_dict())

    assert payload["intent"]["mode"] == "delete_selected_targets"
    assert payload["entries"][0]["outcome"] == "deleted"
    assert CleanupResult.from_dict(payload) == result

    with pytest.raises(CleanupRecordError):
        CleanupDeleteIntent(
            intent_id="intent-2",
            requested_by="tester",
            requested_at="2020-01-01T00:00:00Z",
            reason="not confirmed",
            confirmed=False,
        )


def test_collection_cleanup_contract_shapes_reuse_per_run_records() -> None:
    entry = CleanupReportEntry(
        candidate_id="candidate-1",
        target=_target(),
        status=CleanupReportEntryStatus.SELECTED,
        reason_code="approved",
    )
    report = CleanupReport(
        report_id="report-1",
        run_uri="file:///runs/run-1",
        created_at="2020-01-01T00:00:00Z",
        entries=(entry,),
        summary={"selected": 1},
    )
    collection_report = CollectionCleanupReport(
        collection_id="collection-1",
        created_at="2020-01-01T00:00:00Z",
        reports=(report,),
        selector={"candidate_kinds": ["staged_payload"]},
        summary={"runs": 1, "selected": 1},
    )
    report_payload = cast(dict[str, Any], collection_report.to_dict())

    assert report_payload["reports"][0]["report_id"] == "report-1"
    assert report_payload["summary"] == {"runs": 1, "selected": 1}
    assert CollectionCleanupReport.from_dict(report_payload) == collection_report

    intent = CleanupDeleteIntent(
        intent_id="intent-1",
        requested_by="tester",
        requested_at="2020-01-01T00:00:01Z",
        reason="collection cleanup",
    )
    result = CleanupResult(
        result_id="result-1",
        run_uri="file:///runs/run-1",
        created_at="2020-01-01T00:00:02Z",
        intent=intent,
        entries=(
            CleanupResultEntry(
                candidate_id="candidate-1",
                target=_target(),
                outcome=CleanupResultOutcome.DELETED,
                reason_code="deleted",
                completed_at="2020-01-01T00:00:02Z",
            ),
        ),
    )
    fact = CleanupResultFact(
        result=result,
        recorded_at="2020-01-01T00:00:03Z",
        revision=BackendRevision(sequence=3, token="rev-3"),
    )
    collection_result = CollectionCleanupResult(
        result_id="collection-result-1",
        collection_id="collection-1",
        created_at="2020-01-01T00:00:03Z",
        intent=intent,
        results=(fact,),
        summary={"runs": 1, "deleted": 1},
    )
    result_payload = cast(dict[str, Any], collection_result.to_dict())

    assert result_payload["results"][0]["result"]["result_id"] == "result-1"
    assert result_payload["summary"] == {"runs": 1, "deleted": 1}
    assert CollectionCleanupResult.from_dict(result_payload) == collection_result


def test_cleanup_result_event_contract_references_durable_fact() -> None:
    intent = CleanupDeleteIntent(
        intent_id="intent-1",
        requested_by="tester",
        requested_at="2020-01-01T00:00:00Z",
        reason="test cleanup",
    )
    result = CleanupResult(
        result_id="result-1",
        run_uri="file:///runs/run-1",
        created_at="2020-01-01T00:00:01Z",
        intent=intent,
        summary={"deleted": 1, "failed": 0},
    )
    fact = CleanupResultFact(
        result=result,
        recorded_at="2020-01-01T00:00:02Z",
        revision=BackendRevision(sequence=3, token="rev-3"),
    )

    payload = cleanup_result_event(fact).to_dict()

    assert payload["event_type"] == "cleanup.result.recorded"
    assert payload["timestamp"] == "2020-01-01T00:00:02Z"
    assert payload["payload"] == {
        "fact_type": "cleanup_result",
        "result_id": "result-1",
        "run_uri": "file:///runs/run-1",
        "intent_id": "intent-1",
        "revision": {"sequence": 3, "token": "rev-3", "created_at": None},
        "summary": {"deleted": 1, "failed": 0},
    }


def test_cleanup_records_reject_unknown_fields() -> None:
    payload = {**_target().to_dict(), "extra": True}
    with pytest.raises(CleanupRecordError):
        CleanupTargetRef.from_dict(payload)
