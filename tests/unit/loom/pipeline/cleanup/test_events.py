"""Unit tests for cleanup audit event projection."""

from __future__ import annotations

import pytest

from loom.pipeline.cleanup import (
    CleanupDeleteIntent,
    CleanupReport,
    CleanupResult,
    cleanup_report_event,
    cleanup_result_event,
)
from loom.pipeline.stores import BackendRevision, CleanupReportFact, CleanupResultFact


pytestmark = pytest.mark.unit


def test_cleanup_report_event_is_compact_projection() -> None:
    fact = CleanupReportFact(
        report=CleanupReport(
            report_id="report-1",
            run_uri="file:///runs/r1",
            created_at="2020-01-01T00:00:00Z",
            summary={"selected": 2},
        ),
        recorded_at="2020-01-01T00:00:01Z",
        revision=BackendRevision(sequence=2, token="rev-2"),
    )

    event = cleanup_report_event(fact)

    assert event.event_type == "cleanup.report.recorded"
    assert event.timestamp == fact.recorded_at
    assert event.payload == {
        "fact_type": "cleanup_report",
        "report_id": "report-1",
        "run_uri": "file:///runs/r1",
        "revision": {"sequence": 2, "token": "rev-2", "created_at": None},
        "dry_run": True,
        "summary": {"selected": 2},
    }


def test_cleanup_result_event_references_result_fact_and_intent() -> None:
    intent = CleanupDeleteIntent(
        intent_id="intent-1",
        requested_by="tester",
        requested_at="2020-01-01T00:00:00Z",
        reason="test cleanup",
    )
    fact = CleanupResultFact(
        result=CleanupResult(
            result_id="result-1",
            run_uri="file:///runs/r1",
            created_at="2020-01-01T00:00:01Z",
            intent=intent,
            summary={"deleted": 1},
        ),
        recorded_at="2020-01-01T00:00:02Z",
        revision=BackendRevision(sequence=3, token="rev-3"),
    )

    event = cleanup_result_event(fact)

    assert event.event_type == "cleanup.result.recorded"
    assert event.payload == {
        "fact_type": "cleanup_result",
        "result_id": "result-1",
        "run_uri": "file:///runs/r1",
        "intent_id": "intent-1",
        "revision": {"sequence": 3, "token": "rev-3", "created_at": None},
        "summary": {"deleted": 1},
    }
