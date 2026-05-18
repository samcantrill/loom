"""Cleanup and retention planning contracts."""

from typing import TYPE_CHECKING

from loom.pipeline.cleanup.errors import (
    CleanupError,
    CleanupRecordError,
    CleanupSafetyError,
    CleanupSelectorError,
)
from loom.pipeline.cleanup.records import (
    CLEANUP_RECORD_SCHEMA_VERSION,
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
    CLEANUP_SAFETY_SCHEMA_VERSION,
    CleanupSafetyDecision,
    CleanupSafetyReason,
    CleanupSafetyStatus,
    assess_local_target_safety,
)
from loom.pipeline.cleanup.selectors import (
    CLEANUP_SELECTOR_SCHEMA_VERSION,
    CleanupSelection,
    CleanupSelectionStatus,
    CleanupSelector,
    CleanupSelectorExplanation,
    match_cleanup_candidate,
)

if TYPE_CHECKING:
    from loom.pipeline.cleanup.events import (
        cleanup_report_event,
        cleanup_result_event,
        emit_cleanup_report_event,
        emit_cleanup_result_event,
    )
    from loom.pipeline.cleanup.execution import execute_cleanup
    from loom.pipeline.cleanup.planning import plan_cleanup, record_cleanup_report

__all__ = [
    "CLEANUP_RECORD_SCHEMA_VERSION",
    "CLEANUP_SAFETY_SCHEMA_VERSION",
    "CLEANUP_SELECTOR_SCHEMA_VERSION",
    "CleanupDeleteIntent",
    "CleanupDeleteMode",
    "CleanupError",
    "CleanupManagedRoot",
    "CleanupRecordError",
    "CleanupReport",
    "CleanupReportEntry",
    "CleanupReportEntryStatus",
    "CleanupResult",
    "CleanupResultEntry",
    "CleanupResultOutcome",
    "CleanupSafetyDecision",
    "CleanupSafetyError",
    "CleanupSafetyReason",
    "CleanupSafetyStatus",
    "CleanupSelection",
    "CleanupSelectionStatus",
    "CleanupSelector",
    "CleanupSelectorError",
    "CleanupSelectorExplanation",
    "CleanupTargetKind",
    "CleanupTargetRef",
    "assess_local_target_safety",
    "cleanup_report_event",
    "cleanup_result_event",
    "emit_cleanup_report_event",
    "emit_cleanup_result_event",
    "execute_cleanup",
    "match_cleanup_candidate",
    "plan_cleanup",
    "record_cleanup_report",
]


def __getattr__(name: str) -> object:
    if name in {
        "cleanup_report_event",
        "cleanup_result_event",
        "emit_cleanup_report_event",
        "emit_cleanup_result_event",
    }:
        from loom.pipeline.cleanup import events

        return getattr(events, name)
    if name == "execute_cleanup":
        from loom.pipeline.cleanup import execution

        return getattr(execution, name)
    if name in {"plan_cleanup", "record_cleanup_report"}:
        from loom.pipeline.cleanup import planning

        return getattr(planning, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
