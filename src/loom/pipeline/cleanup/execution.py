"""Intent-gated cleanup execution."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlparse

from loom.pipeline.cleanup.errors import CleanupError
from loom.pipeline.cleanup.events import emit_cleanup_result_event
from loom.pipeline.cleanup.records import (
    CleanupDeleteIntent,
    CleanupDeleteMode,
    CleanupManagedRoot,
    CleanupReport,
    CleanupReportEntry,
    CleanupReportEntryStatus,
    CleanupResult,
    CleanupResultEntry,
    CleanupResultOutcome,
    CleanupTargetKind,
    CleanupTargetRef,
)
from loom.pipeline.cleanup.safety import (
    CleanupSafetyDecision,
    CleanupSafetyStatus,
    assess_local_target_safety,
)
from loom.pipeline.execution.eventing import RuntimeEventDispatcher
from loom.pipeline.stores import CleanupResultFact, PerRunAuthorityStore
from loom.serialization import PlainData, thaw_plain_data
from loom.timestamps import utc_timestamp


def execute_cleanup(
    store: PerRunAuthorityStore,
    run_uri: str,
    report: CleanupReport,
    intent: CleanupDeleteIntent,
    *,
    managed_roots: Iterable[CleanupManagedRoot] = (),
    result_id: str | None = None,
    created_at: str | None = None,
    require_ownership: bool = True,
    event_dispatcher: RuntimeEventDispatcher | None = None,
    emit_event: bool = True,
    metadata: Mapping[str, PlainData] | None = None,
) -> CleanupResultFact:
    """Execute selected cleanup report entries and append one result fact."""

    _validate_execution_inputs(run_uri, report, intent)
    roots = tuple(managed_roots)
    timestamp = created_at or utc_timestamp()
    allowed_candidate_ids = set(intent.candidate_ids)
    entries = tuple(
        _execute_entry(
            entry,
            intent=intent,
            allowed_candidate_ids=allowed_candidate_ids,
            managed_roots=roots,
            completed_at=timestamp,
            require_ownership=require_ownership,
        )
        for entry in report.entries
    )
    result = CleanupResult(
        result_id=result_id or f"cleanup-result-{uuid.uuid4().hex}",
        run_uri=run_uri,
        created_at=timestamp,
        intent=intent,
        entries=entries,
        summary=_summary(entries),
        metadata={
            "report_id": report.report_id,
            **_plain_metadata(metadata),
        },
    )
    fact = store.append_cleanup_result(run_uri, result)
    if emit_event:
        emit_cleanup_result_event(
            store,
            fact,
            event_dispatcher=event_dispatcher,
        )
    return fact


def _validate_execution_inputs(
    run_uri: str,
    report: CleanupReport,
    intent: CleanupDeleteIntent,
) -> None:
    if not isinstance(report, CleanupReport):
        raise CleanupError("report must be a CleanupReport")
    if not isinstance(intent, CleanupDeleteIntent):
        raise CleanupError("intent must be a CleanupDeleteIntent")
    if report.run_uri != run_uri:
        raise CleanupError("cleanup report run_uri does not match run")
    if intent.mode is not CleanupDeleteMode.DELETE_SELECTED_TARGETS:
        raise CleanupError("unsupported cleanup delete intent mode")


def _execute_entry(
    entry: CleanupReportEntry,
    *,
    intent: CleanupDeleteIntent,
    allowed_candidate_ids: set[str],
    managed_roots: tuple[CleanupManagedRoot, ...],
    completed_at: str,
    require_ownership: bool,
) -> CleanupResultEntry:
    if entry.status is CleanupReportEntryStatus.SKIPPED:
        return _result_entry(
            entry,
            CleanupResultOutcome.SKIPPED,
            "dry_run_skipped",
            completed_at,
            message=entry.message,
        )
    if entry.status is CleanupReportEntryStatus.REJECTED:
        return _result_entry(
            entry,
            CleanupResultOutcome.REJECTED,
            "dry_run_rejected",
            completed_at,
            message=entry.message,
        )
    if allowed_candidate_ids and entry.candidate_id not in allowed_candidate_ids:
        return _result_entry(
            entry,
            CleanupResultOutcome.SKIPPED,
            "not_in_delete_intent",
            completed_at,
            message="candidate was not included in cleanup delete intent",
            detail={"intent_id": intent.intent_id},
        )
    safety = assess_local_target_safety(
        entry.target,
        managed_roots,
        require_ownership=require_ownership,
    )
    if safety.status is not CleanupSafetyStatus.APPROVED:
        outcome = (
            CleanupResultOutcome.SKIPPED
            if safety.status is CleanupSafetyStatus.SKIPPED
            else CleanupResultOutcome.REJECTED
        )
        return _result_entry(
            entry,
            outcome,
            safety.reason_code.value,
            completed_at,
            message=safety.message,
            detail=_safety_detail(safety),
        )
    return _delete_selected_entry(entry, safety=safety, completed_at=completed_at)


def _delete_selected_entry(
    entry: CleanupReportEntry,
    *,
    safety: CleanupSafetyDecision,
    completed_at: str,
) -> CleanupResultEntry:
    path = _safe_local_path(entry.target, safety=safety)
    if path is None:
        return _result_entry(
            entry,
            CleanupResultOutcome.REJECTED,
            "unsupported_target_kind",
            completed_at,
            message="cleanup target is not a supported local path",
            detail={"safety_decision": safety.to_dict()},
        )
    try:
        if path.is_symlink():
            return _result_entry(
                entry,
                CleanupResultOutcome.REJECTED,
                "target_is_symlink",
                completed_at,
                message="target became a symlink before deletion",
                detail={
                    "path": str(path),
                    **_safety_detail(safety),
                },
            )
        if not path.exists():
            return _result_entry(
                entry,
                CleanupResultOutcome.SKIPPED,
                "target_missing",
                completed_at,
                message="target does not exist",
                detail={
                    "path": str(path),
                    **_safety_detail(safety),
                },
            )
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        return _result_entry(
            entry,
            CleanupResultOutcome.FAILED,
            "delete_failed",
            completed_at,
            message=str(exc) or type(exc).__name__,
            detail={
                "path": str(path),
                "exception_type": type(exc).__name__,
                **_safety_detail(safety),
            },
        )
    return _result_entry(
        entry,
        CleanupResultOutcome.DELETED,
        "deleted",
        completed_at,
        message="target deleted",
        detail={"path": str(path), **_safety_detail(safety)},
    )


def _safe_local_path(
    target: CleanupTargetRef,
    *,
    safety: CleanupSafetyDecision,
) -> Path | None:
    if target.kind is not CleanupTargetKind.LOCAL_PATH:
        return None
    safety_path = safety.detail.get("path")
    if isinstance(safety_path, str) and safety_path:
        return Path(os.path.abspath(safety_path))
    parsed = urlparse(target.uri)
    if parsed.scheme == "file" and parsed.netloc not in ("", "localhost"):
        return None
    if parsed.scheme not in ("", "file"):
        return None
    raw_path = unquote(parsed.path if parsed.scheme == "file" else target.uri)
    if not raw_path:
        return None
    return Path(os.path.abspath(raw_path))


def _result_entry(
    report_entry: CleanupReportEntry,
    outcome: CleanupResultOutcome,
    reason_code: str,
    completed_at: str,
    *,
    message: str | None = None,
    detail: Mapping[str, PlainData] | None = None,
) -> CleanupResultEntry:
    return CleanupResultEntry(
        candidate_id=report_entry.candidate_id,
        target=report_entry.target,
        outcome=outcome,
        reason_code=reason_code,
        completed_at=completed_at,
        message=message,
        detail={} if detail is None else detail,
    )


def _safety_detail(safety: CleanupSafetyDecision) -> dict[str, PlainData]:
    detail: dict[str, PlainData] = {
        "safety_status": safety.status.value,
        "safety_reason_code": safety.reason_code.value,
    }
    if safety.managed_root_id is not None:
        detail["managed_root_id"] = safety.managed_root_id
    thawed = thaw_plain_data(safety.detail, path="safety.detail")
    if isinstance(thawed, dict):
        detail.update(cast(dict[str, PlainData], thawed))
    return detail


def _summary(entries: tuple[CleanupResultEntry, ...]) -> dict[str, PlainData]:
    deleted = sum(1 for entry in entries if entry.outcome is CleanupResultOutcome.DELETED)
    skipped = sum(1 for entry in entries if entry.outcome is CleanupResultOutcome.SKIPPED)
    rejected = sum(
        1 for entry in entries if entry.outcome is CleanupResultOutcome.REJECTED
    )
    failed = sum(1 for entry in entries if entry.outcome is CleanupResultOutcome.FAILED)
    return {
        "candidates": len(entries),
        "deleted": deleted,
        "skipped": skipped,
        "rejected": rejected,
        "failed": failed,
    }


def _plain_metadata(
    metadata: Mapping[str, PlainData] | None,
) -> dict[str, PlainData]:
    if metadata is None:
        return {}
    thawed = thaw_plain_data(metadata, path="metadata")
    if isinstance(thawed, dict):
        return cast(dict[str, PlainData], thawed)
    return {}


__all__ = [
    "execute_cleanup",
]
