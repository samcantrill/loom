"""Unit tests for ``loom runs`` command orchestration."""

from __future__ import annotations

import io
import json

import pytest

import loom.cli.runs as runs_command
from loom.cli.main import main
from loom.runs import (
    CatalogIndexResult,
    CatalogWarning,
    ComparisonEntry,
    ComparisonSection,
    ComparisonStatus,
    ListRunsResult,
    RunComparison,
    RunFilter,
    RunFilterKind,
    RunSummary,
)


pytestmark = pytest.mark.unit


def test_runs_index_json_preserves_warning_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runs_command,
        "build_runs_index_result",
        lambda collection: CatalogIndexResult(
            indexed_count=1,
            skipped_count=1,
            warnings=[
                CatalogWarning(
                    "partial_run",
                    "missing status",
                    run_uri="file:///tmp/runs/partial",
                    path="/tmp/runs/partial/run.json",
                    details={"field": "status"},
                )
            ],
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["runs", "index", "/tmp/runs", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == runs_command.RUNS_INDEX_SCHEMA_VERSION
    assert payload["warnings"] == [
        {
            "code": "partial_run",
            "message": "missing status",
            "details": {
                "field": "status",
                "path": "/tmp/runs/partial/run.json",
                "run_uri": "file:///tmp/runs/partial",
            },
        }
    ]
    assert payload["result"]["indexed_count"] == 1
    assert stderr.getvalue() == ""


def test_runs_list_builds_filters_and_formats_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def build_runs_list_result(
        collection: object,
        filters: tuple[RunFilter, ...],
    ) -> ListRunsResult:
        calls["collection"] = collection
        calls["filters"] = filters
        return ListRunsResult(
            summaries=[
                RunSummary(
                    run_uri="file:///tmp/runs/a",
                    status="SUCCEEDED",
                    config_fingerprint="config-a",
                    pipeline_fingerprint="pipeline-a",
                    git_commit="abc123",
                )
            ]
        )

    monkeypatch.setattr(runs_command, "build_runs_list_result", build_runs_list_result)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "runs",
                "list",
                "/tmp/runs",
                "--status",
                "SUCCEEDED",
                "--tag",
                "project=demo",
                "--config-fingerprint",
                "config-a",
                "--pipeline-fingerprint",
                "pipeline-a",
                "--commit",
                "abc123",
                "--stage-status",
                "build=SUCCEEDED",
                "--artifact",
                "build.out=build/out",
                "--artifact-checksum",
                "build.out=sha256:abc",
                "--executor",
                "local",
                "--backend",
                "local",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    filters = calls["filters"]
    assert isinstance(filters, tuple)
    assert [(item.kind, item.key, item.value) for item in filters] == [
        (RunFilterKind.RUN_STATUS, None, "SUCCEEDED"),
        (RunFilterKind.TAG, "project", "demo"),
        (RunFilterKind.CONFIG_FINGERPRINT, None, "config-a"),
        (RunFilterKind.PIPELINE_FINGERPRINT, None, "pipeline-a"),
        (RunFilterKind.GIT_COMMIT, None, "abc123"),
        (RunFilterKind.STAGE_STATUS, "build", "SUCCEEDED"),
        (RunFilterKind.ARTIFACT_IDENTITY, "build.out", "build/out"),
        (RunFilterKind.ARTIFACT_CHECKSUM, "build.out", "sha256:abc"),
        (RunFilterKind.EXECUTOR, None, "local"),
        (RunFilterKind.BACKEND, None, "local"),
    ]
    assert "runs list /tmp/runs: 1 run" in stdout.getvalue()
    assert "SUCCEEDED file:///tmp/runs/a" in stdout.getvalue()
    assert "source=unknown" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_runs_list_rejects_malformed_tag_filter() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["runs", "list", "/tmp/runs", "--tag", "project"],
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )

    assert stdout.getvalue() == ""
    assert "expected KEY=VALUE" in stderr.getvalue()


def test_runs_diff_text_shows_non_same_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runs_command,
        "build_runs_diff_result",
        lambda collection, left, right: RunComparison(
            left_run_uri=left,
            right_run_uri=right,
            sections=[
                ComparisonSection(
                    name="run",
                    entries=[
                        ComparisonEntry(
                            key="run.status",
                            status=ComparisonStatus.DIFFERENT,
                            left="SUCCEEDED",
                            right="FAILED",
                        ),
                        ComparisonEntry(
                            key="fingerprints.config",
                            status=ComparisonStatus.SAME,
                            left="config",
                            right="config",
                        ),
                    ],
                )
            ],
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "runs",
                "diff",
                "/tmp/runs",
                "file:///tmp/runs/a",
                "file:///tmp/runs/b",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    output = stdout.getvalue()
    assert "different=1" in output
    assert "same=1" in output
    assert "run.status: different left=SUCCEEDED right=FAILED" in output
    assert "fingerprints.config" not in output
    assert stderr.getvalue() == ""


def test_runs_missing_action_is_usage_error() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["runs"], stdout=stdout, stderr=stderr) == 2

    assert stdout.getvalue() == ""
    assert "usage: loom runs" in stderr.getvalue()
