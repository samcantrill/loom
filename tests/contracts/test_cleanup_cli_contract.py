"""Contract tests for cleanup CLI JSON payloads."""

from __future__ import annotations

import json
from typing import cast

import pytest

from loom.cli.clean import CLEAN_RESULT_SCHEMA_VERSION, CleanCliResult
from loom.cli.formatting import format_json_envelope
from loom.cli.gc import GC_RESULT_SCHEMA_VERSION, GcCliResult
from loom.pipeline.cleanup import (
    CleanupReport,
    CleanupReportEntry,
    CleanupReportEntryStatus,
    CleanupSelector,
    CleanupTargetKind,
    CleanupTargetRef,
    CollectionCleanupReport,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.contract


def test_clean_cli_result_payload_is_plain_data() -> None:
    result = CleanCliResult(
        run_uri="file:///tmp/run",
        action="dry_run",
        dry_run=True,
        report=_report("file:///tmp/run"),
    )

    payload = result.to_dict()
    encoded = format_json_envelope(
        schema_version=CLEAN_RESULT_SCHEMA_VERSION,
        ok=True,
        warnings=(),
        payload_name="result",
        payload=payload,
    )

    decoded = json.loads(encoded)
    assert decoded["schema_version"] == CLEAN_RESULT_SCHEMA_VERSION
    assert decoded["result"]["report"]["entries"][0]["target"]["kind"] == "local_path"
    assert decoded["result"]["result"] is None


def test_gc_cli_result_payload_is_plain_data() -> None:
    result = GcCliResult(
        collection="/tmp/runs",
        action="dry_run",
        dry_run=True,
        report=CollectionCleanupReport(
            collection_id="collection-1",
            created_at="2020-01-01T00:00:00Z",
            reports=(_report("file:///tmp/runs/run-1"),),
            selector=cast(dict[str, PlainData], CleanupSelector().to_dict()),
            summary={
                "runs": 1,
                "candidates": 1,
                "selected": 1,
                "skipped": 0,
                "rejected": 0,
                "dry_run": True,
            },
        ),
    )

    encoded = format_json_envelope(
        schema_version=GC_RESULT_SCHEMA_VERSION,
        ok=True,
        warnings=(),
        payload_name="result",
        payload=result.to_dict(),
    )

    decoded = json.loads(encoded)
    assert decoded["schema_version"] == GC_RESULT_SCHEMA_VERSION
    assert decoded["result"]["report"]["reports"][0]["run_uri"].endswith("run-1")
    assert decoded["result"]["result"] is None


def _report(run_uri: str) -> CleanupReport:
    return CleanupReport(
        report_id="report-1",
        run_uri=run_uri,
        created_at="2020-01-01T00:00:00Z",
        dry_run=True,
        selector=cast(dict[str, PlainData], CleanupSelector().to_dict()),
        entries=(
            CleanupReportEntry(
                candidate_id="candidate-1",
                target=CleanupTargetRef(
                    kind=CleanupTargetKind.LOCAL_PATH,
                    uri=f"{run_uri}/tmp.txt",
                ),
                status=CleanupReportEntryStatus.SELECTED,
                reason_code="approved",
            ),
        ),
        summary={"candidates": 1, "selected": 1, "skipped": 0, "rejected": 0},
    )
