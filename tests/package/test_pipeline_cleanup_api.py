"""Package-level import checks for cleanup contracts."""

from __future__ import annotations

import subprocess
import sys
from textwrap import dedent

import pytest


pytestmark = pytest.mark.package


def test_pipeline_cleanup_public_exports() -> None:
    import loom.pipeline.cleanup as cleanup

    assert set(cleanup.__all__) == {
        "CLEANUP_RECORD_SCHEMA_VERSION",
        "CLEANUP_SAFETY_SCHEMA_VERSION",
        "CLEANUP_SELECTOR_SCHEMA_VERSION",
        "CleanupDeleteIntent",
        "CleanupDeleteMode",
        "CleanupError",
        "CollectionCleanupReport",
        "CollectionCleanupResult",
        "CollectionCleanupTarget",
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
        "execute_collection_gc",
        "match_cleanup_candidate",
        "plan_collection_gc",
        "plan_cleanup",
        "record_cleanup_report",
    }


def test_cleanup_import_does_not_import_cli_diagnostics_or_execution() -> None:
    script = dedent(
        """
        import sys

        import loom.pipeline.cleanup

        for forbidden in (
            "loom.cli",
            "loom.diagnostics",
            "loom.pipeline.execution",
            "loom.pipeline.executors",
            "fastapi",
            "starlette",
        ):
            if forbidden in sys.modules:
                raise SystemExit(f"{forbidden} imported through cleanup")
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
