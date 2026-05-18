"""Unit tests for ``loom clean`` command orchestration."""

from __future__ import annotations

import io
import json
from typing import cast

import pytest

import loom.cli.clean as clean_command
from loom.cli.main import main
from loom.pipeline.cleanup import (
    CleanupReport,
    CleanupReportEntry,
    CleanupReportEntryStatus,
    CleanupSelector,
    CleanupTargetKind,
    CleanupTargetRef,
)
from loom.serialization import PlainData


pytestmark = pytest.mark.unit


def test_clean_json_parses_selector_and_formats_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def build_clean_result(
        run_uri: str,
        *,
        selector: object,
        delete: bool,
        yes: bool,
        delete_reason: str | None,
        authority_config: object,
    ) -> clean_command.CleanCliResult:
        calls.update(
            {
                "run_uri": run_uri,
                "selector": selector,
                "delete": delete,
                "yes": yes,
                "delete_reason": delete_reason,
                "authority_config": authority_config,
            }
        )
        return clean_command.CleanCliResult(
            run_uri=run_uri,
            action="dry_run",
            dry_run=True,
            report=_report(run_uri),
        )

    monkeypatch.setattr(clean_command, "build_clean_result", build_clean_result)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "clean",
                "file:///tmp/run",
                "--older-than",
                "7d",
                "--candidate-kind",
                "staged_payload",
                "--metadata",
                "stage_name=build",
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
    assert selector.older_than_seconds == 7 * 24 * 60 * 60
    assert selector.candidate_kinds == ("staged_payload",)
    assert selector.metadata_equals == {"stage_name": "build"}
    assert calls["delete"] is False
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == clean_command.CLEAN_RESULT_SCHEMA_VERSION
    assert payload["result"]["report"]["entries"][0]["candidate_id"] == "candidate-1"
    assert stderr.getvalue() == ""


def test_clean_text_summarizes_rejected_candidates() -> None:
    result = clean_command.CleanCliResult(
        run_uri="file:///tmp/run",
        action="dry_run",
        dry_run=True,
        report=CleanupReport(
            report_id="report-1",
            run_uri="file:///tmp/run",
            created_at="2020-01-01T00:00:00Z",
            dry_run=True,
            entries=(
                CleanupReportEntry(
                    candidate_id="candidate-1",
                    target=CleanupTargetRef(
                        kind=CleanupTargetKind.LOCAL_PATH,
                        uri="file:///tmp/run/tmp.txt",
                    ),
                    status=CleanupReportEntryStatus.REJECTED,
                    reason_code="outside_managed_root",
                ),
            ),
            summary={"candidates": 1, "selected": 0, "skipped": 0, "rejected": 1},
        ),
    )

    output = clean_command.format_clean_text(result)

    assert "OK clean file:///tmp/run: dry-run candidates=1 selected=0" in output
    assert "rejected candidate-1: outside_managed_root" in output


def test_clean_delete_passes_confirmation_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def build_clean_result(
        run_uri: str,
        *,
        selector: object,
        delete: bool,
        yes: bool,
        delete_reason: str | None,
        authority_config: object,
    ) -> clean_command.CleanCliResult:
        calls.update(
            {
                "run_uri": run_uri,
                "selector": selector,
                "delete": delete,
                "yes": yes,
                "delete_reason": delete_reason,
                "authority_config": authority_config,
            }
        )
        return clean_command.CleanCliResult(
            run_uri=run_uri,
            action="delete",
            dry_run=False,
            report=_report(run_uri),
        )

    monkeypatch.setattr(clean_command, "build_clean_result", build_clean_result)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "clean",
                "file:///tmp/run",
                "--delete",
                "--yes",
                "--delete-reason",
                "manual maintenance",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert calls["delete"] is True
    assert calls["yes"] is True
    assert calls["delete_reason"] == "manual maintenance"
    assert "OK clean file:///tmp/run: dry-run" in stdout.getvalue()
    assert stderr.getvalue() == ""


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
                    uri="file:///tmp/run/tmp.txt",
                ),
                status=CleanupReportEntryStatus.SELECTED,
                reason_code="approved",
            ),
        ),
        summary={"candidates": 1, "selected": 1, "skipped": 0, "rejected": 0},
    )
