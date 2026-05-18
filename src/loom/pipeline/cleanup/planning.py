"""Authority-backed cleanup dry-run planning."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from urllib.parse import urlparse

from loom.pipeline.cleanup.records import (
    CleanupManagedRoot,
    CleanupReport,
    CleanupReportEntry,
    CleanupReportEntryStatus,
    CleanupTargetKind,
    CleanupTargetRef,
)
from loom.pipeline.cleanup.safety import (
    CleanupSafetyDecision,
    CleanupSafetyStatus,
    assess_local_target_safety,
)
from loom.pipeline.cleanup.selectors import (
    CleanupSelector,
    match_cleanup_candidate,
)
from loom.pipeline.stores import CleanupCandidate, CleanupReportFact, PerRunAuthorityStore
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp


def plan_cleanup(
    store: PerRunAuthorityStore,
    run_uri: str,
    *,
    selector: CleanupSelector | Mapping[str, PlainData] | None = None,
    managed_roots: Iterable[CleanupManagedRoot] = (),
    now: datetime | None = None,
    report_id: str | None = None,
    created_at: str | None = None,
    require_ownership: bool = True,
    metadata: Mapping[str, PlainData] | None = None,
) -> CleanupReport:
    """Return a cleanup dry-run report without mutating authority state."""

    normalized_selector = _selector(selector)
    normalized_roots = tuple(managed_roots)
    candidates = store.list_cleanup_candidates(run_uri)
    entries = tuple(
        _plan_entry(
            candidate,
            selector=normalized_selector,
            managed_roots=normalized_roots,
            now=now,
            require_ownership=require_ownership,
            metadata=metadata,
        )
        for candidate in candidates
    )
    return CleanupReport(
        report_id=report_id or f"cleanup-report-{uuid.uuid4().hex}",
        run_uri=run_uri,
        created_at=created_at or utc_timestamp(now),
        dry_run=True,
        selector=normalized_selector.to_dict(),
        entries=entries,
        summary=_summary(entries),
    )


def record_cleanup_report(
    store: PerRunAuthorityStore,
    report: CleanupReport,
) -> CleanupReportFact:
    """Explicitly append a durable cleanup report fact."""

    return store.append_cleanup_report(report.run_uri, report)


def _plan_entry(
    candidate: CleanupCandidate,
    *,
    selector: CleanupSelector,
    managed_roots: tuple[CleanupManagedRoot, ...],
    now: datetime | None,
    require_ownership: bool,
    metadata: Mapping[str, PlainData] | None,
) -> CleanupReportEntry:
    target = _target_for_candidate(candidate)
    selection = match_cleanup_candidate(
        candidate,
        selector,
        metadata=metadata,
        now=now,
    )
    selector_explanations = tuple(
        explanation.to_dict() for explanation in selection.explanations
    )
    if not selection.selected:
        return CleanupReportEntry(
            candidate_id=candidate.candidate_id,
            target=target,
            status=CleanupReportEntryStatus.SKIPPED,
            reason_code="selector_skipped",
            message="candidate did not match cleanup selector",
            selector_explanations=selector_explanations,
            metadata=_entry_metadata(candidate),
        )
    safety = assess_local_target_safety(
        target,
        managed_roots,
        require_ownership=require_ownership,
    )
    return CleanupReportEntry(
        candidate_id=candidate.candidate_id,
        target=target,
        status=_entry_status_for_safety(safety),
        reason_code=safety.reason_code.value,
        message=safety.message,
        selector_explanations=selector_explanations,
        safety_decision=safety.to_dict(),
        metadata=_entry_metadata(candidate),
    )


def _selector(
    value: CleanupSelector | Mapping[str, PlainData] | None,
) -> CleanupSelector:
    if value is None:
        return CleanupSelector()
    if isinstance(value, CleanupSelector):
        return value
    return CleanupSelector.from_dict(value)


def _target_for_candidate(candidate: CleanupCandidate) -> CleanupTargetRef:
    detail = _candidate_detail(candidate)
    return CleanupTargetRef(
        kind=_target_kind(candidate.uri),
        uri=candidate.uri,
        target_id=_optional_string(detail.get("target_id")) or candidate.candidate_id,
        ownership_key=_optional_string(detail.get("ownership_key")),
        metadata={
            **detail,
            "candidate_kind": candidate.kind.value,
            "reason_code": candidate.reason.code,
            "recorded_at": candidate.recorded_at,
        },
    )


def _target_kind(uri: str) -> CleanupTargetKind:
    scheme = urlparse(uri).scheme
    if scheme in ("", "file"):
        return CleanupTargetKind.LOCAL_PATH
    if scheme in {"http", "https"}:
        return CleanupTargetKind.EXTERNAL_REF
    return CleanupTargetKind.REMOTE_REF


def _entry_status_for_safety(
    safety: CleanupSafetyDecision,
) -> CleanupReportEntryStatus:
    if safety.status is CleanupSafetyStatus.APPROVED:
        return CleanupReportEntryStatus.SELECTED
    if safety.status is CleanupSafetyStatus.SKIPPED:
        return CleanupReportEntryStatus.SKIPPED
    return CleanupReportEntryStatus.REJECTED


def _summary(entries: tuple[CleanupReportEntry, ...]) -> dict[str, PlainData]:
    selected = sum(
        1 for entry in entries if entry.status is CleanupReportEntryStatus.SELECTED
    )
    skipped = sum(
        1 for entry in entries if entry.status is CleanupReportEntryStatus.SKIPPED
    )
    rejected = sum(
        1 for entry in entries if entry.status is CleanupReportEntryStatus.REJECTED
    )
    return {
        "candidates": len(entries),
        "selected": selected,
        "skipped": skipped,
        "rejected": rejected,
        "dry_run": True,
    }


def _candidate_detail(candidate: CleanupCandidate) -> Mapping[str, PlainData]:
    return candidate.reason.detail


def _entry_metadata(candidate: CleanupCandidate) -> Mapping[str, PlainData]:
    return {
        "candidate_kind": candidate.kind.value,
        "reason_code": candidate.reason.code,
        "recorded_at": candidate.recorded_at,
        "revision": candidate.revision.to_dict(),
    }


def _optional_string(value: PlainData) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "plan_cleanup",
    "record_cleanup_report",
]
