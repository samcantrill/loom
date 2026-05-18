"""Unit tests for ``loom gc`` command orchestration."""

from __future__ import annotations

import io
import json
from typing import cast

import pytest

import loom.cli.gc as gc_command
from loom.cli.main import main
from loom.cli.results import CliWarning
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


pytestmark = pytest.mark.unit


def test_gc_json_parses_selector_and_includes_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def build_gc_result(
        collection: object,
        *,
        selector: object,
        delete: bool,
        yes: bool,
        delete_reason: str | None,
        authority_config: object,
    ) -> gc_command.GcCliResult:
        calls.update(
            {
                "collection": collection,
                "selector": selector,
                "delete": delete,
                "yes": yes,
                "delete_reason": delete_reason,
                "authority_config": authority_config,
            }
        )
        return gc_command.GcCliResult(
            collection=str(collection),
            action="dry_run",
            dry_run=True,
            report=_collection_report(),
            warnings=(
                CliWarning(
                    code="partial_run",
                    message="partial run skipped",
                    details={"run_uri": "file:///tmp/runs/partial"},
                ),
            ),
        )

    monkeypatch.setattr(gc_command, "build_gc_result", build_gc_result)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "gc",
                "/tmp/runs",
                "--older-than",
                "12h",
                "--retention-mode",
                "temporary",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    selector = calls["selector"]
    assert isinstance(selector, CleanupSelector)
    assert selector.older_than_seconds == 12 * 60 * 60
    assert selector.retention_modes == ("temporary",)
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == gc_command.GC_RESULT_SCHEMA_VERSION
    assert payload["warnings"][0]["code"] == "partial_run"
    assert payload["result"]["summary"]["runs"] == 1
    assert stderr.getvalue() == ""


def test_gc_text_includes_run_uri_for_each_candidate() -> None:
    result = gc_command.GcCliResult(
        collection="/tmp/runs",
        action="dry_run",
        dry_run=True,
        report=_collection_report(),
    )

    output = gc_command.format_gc_text(result)

    assert "OK gc /tmp/runs: dry-run runs=1 candidates=1 selected=1" in output
    assert "selected file:///tmp/runs/run-1 candidate-1: approved" in output


def _collection_report() -> CollectionCleanupReport:
    run_report = CleanupReport(
        report_id="report-1",
        run_uri="file:///tmp/runs/run-1",
        created_at="2020-01-01T00:00:00Z",
        dry_run=True,
        selector=cast(dict[str, PlainData], CleanupSelector().to_dict()),
        entries=(
            CleanupReportEntry(
                candidate_id="candidate-1",
                target=CleanupTargetRef(
                    kind=CleanupTargetKind.LOCAL_PATH,
                    uri="file:///tmp/runs/run-1/tmp.txt",
                ),
                status=CleanupReportEntryStatus.SELECTED,
                reason_code="approved",
            ),
        ),
        summary={"candidates": 1, "selected": 1, "skipped": 0, "rejected": 0},
    )
    return CollectionCleanupReport(
        collection_id="collection-1",
        created_at="2020-01-01T00:00:00Z",
        reports=(run_report,),
        selector=cast(dict[str, PlainData], CleanupSelector().to_dict()),
        summary={
            "runs": 1,
            "candidates": 1,
            "selected": 1,
            "skipped": 0,
            "rejected": 0,
            "dry_run": True,
        },
    )
