"""Unit tests for cleanup dry-run planning."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline.cleanup import (
    CleanupManagedRoot,
    CleanupReport,
    CleanupReportEntryStatus,
    CleanupSelector,
    plan_cleanup,
    record_cleanup_report,
)
from loom.pipeline.stores import (
    BackendRevision,
    CleanupCandidate,
    CleanupCandidateKind,
    CleanupReportFact,
    PerRunAuthorityStore,
    LifecycleReason,
    path_to_run_uri,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


class DryRunStore:
    def __init__(self, candidates: tuple[CleanupCandidate, ...]) -> None:
        self.candidates = candidates
        self.reports: list[CleanupReportFact] = []
        self.append_report_calls = 0

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        assert run_uri == RUN_URI
        return self.candidates

    def append_cleanup_report(
        self, run_uri: str, report: CleanupReport
    ) -> CleanupReportFact:
        assert run_uri == RUN_URI
        self.append_report_calls += 1
        fact = CleanupReportFact(
            report=report,
            recorded_at="2020-01-10T00:00:00Z",
            revision=BackendRevision(sequence=2, token="rev-2"),
        )
        self.reports.append(fact)
        return fact

    def list_cleanup_reports(self, run_uri: str) -> tuple[CleanupReportFact, ...]:
        assert run_uri == RUN_URI
        return tuple(self.reports)


RUN_URI = "file:///runs/r1"
NOW = datetime(2020, 1, 10, tzinfo=timezone.utc)


def test_plan_cleanup_selects_safe_candidate_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "tmp" / "payload.bin"
    target.parent.mkdir()
    target.write_text("payload", encoding="utf-8")
    store = DryRunStore(
        (
            _candidate(
                uri=path_to_run_uri(target),
                detail={"ownership_key": "run-r1", "retention_mode": "temporary"},
            ),
        )
    )

    report = plan_cleanup(
        cast(PerRunAuthorityStore, store),
        RUN_URI,
        managed_roots=(
            CleanupManagedRoot(
                root_id="run-root",
                uri=path_to_run_uri(tmp_path),
                ownership_key="run-r1",
            ),
        ),
        now=NOW,
        report_id="report-1",
    )

    assert store.append_report_calls == 0
    assert report.report_id == "report-1"
    assert report.dry_run is True
    assert report.summary == {
        "candidates": 1,
        "selected": 1,
        "skipped": 0,
        "rejected": 0,
        "dry_run": True,
    }
    assert report.entries[0].status is CleanupReportEntryStatus.SELECTED
    assert report.entries[0].reason_code == "approved"


def test_plan_cleanup_explains_selector_skips_and_safety_rejections() -> None:
    store = DryRunStore(
        (
            _candidate(
                candidate_id="skip-1",
                kind=CleanupCandidateKind.WORKER_HANDOFF,
                uri="file:///runs/r1/tmp/handoff",
            ),
            _candidate(
                candidate_id="reject-1",
                uri="s3://bucket/key",
                detail={"ownership_key": "run-r1"},
            ),
        )
    )

    report = plan_cleanup(
        cast(PerRunAuthorityStore, store),
        RUN_URI,
        selector=CleanupSelector(candidate_kinds=("staged_payload",)),
        managed_roots=(
            CleanupManagedRoot(
                root_id="run-root",
                uri="file:///runs/r1",
                ownership_key="run-r1",
            ),
        ),
        now=NOW,
        report_id="report-1",
    )

    assert store.append_report_calls == 0
    assert report.summary["selected"] == 0
    assert report.summary["skipped"] == 1
    assert report.summary["rejected"] == 1
    assert report.entries[0].status is CleanupReportEntryStatus.SKIPPED
    assert report.entries[0].reason_code == "selector_skipped"
    assert report.entries[1].status is CleanupReportEntryStatus.REJECTED
    assert report.entries[1].reason_code == "unsupported_target_kind"


def test_record_cleanup_report_is_explicit_append_path() -> None:
    store = DryRunStore(())
    report = plan_cleanup(
        cast(PerRunAuthorityStore, store),
        RUN_URI,
        now=NOW,
        report_id="report-1",
    )

    fact = record_cleanup_report(cast(PerRunAuthorityStore, store), report)

    assert store.append_report_calls == 1
    assert fact.report == report
    assert store.list_cleanup_reports(RUN_URI) == (fact,)


def test_plan_cleanup_accepts_single_pass_managed_roots_iterable(
    tmp_path: Path,
) -> None:
    targets = (tmp_path / "tmp" / "one.bin", tmp_path / "tmp" / "two.bin")
    for target in targets:
        target.parent.mkdir(exist_ok=True)
        target.write_text("payload", encoding="utf-8")
    store = DryRunStore(
        tuple(
            _candidate(
                candidate_id=f"cleanup-{index}",
                uri=path_to_run_uri(target),
                detail={"ownership_key": "run-r1"},
            )
            for index, target in enumerate(targets, start=1)
        )
    )
    roots = iter(
        (
            CleanupManagedRoot(
                root_id="run-root",
                uri=path_to_run_uri(tmp_path),
                ownership_key="run-r1",
            ),
        )
    )

    report = plan_cleanup(
        cast(PerRunAuthorityStore, store),
        RUN_URI,
        managed_roots=roots,
        now=NOW,
    )

    assert [entry.status for entry in report.entries] == [
        CleanupReportEntryStatus.SELECTED,
        CleanupReportEntryStatus.SELECTED,
    ]


def _candidate(
    *,
    candidate_id: str = "cleanup-1",
    kind: CleanupCandidateKind = CleanupCandidateKind.STAGED_PAYLOAD,
    uri: str,
    detail: dict[str, PlainData] | None = None,
) -> CleanupCandidate:
    return CleanupCandidate(
        candidate_id=candidate_id,
        kind=kind,
        uri=uri,
        reason=LifecycleReason(
            code="temporary_payload",
            detail={} if detail is None else detail,
        ),
        recorded_at="2020-01-01T00:00:00Z",
        revision=BackendRevision(sequence=1, token="rev-1"),
    )
