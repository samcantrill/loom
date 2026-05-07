"""Unit tests for diagnostics status and log inspection."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.diagnostics.inspection import (
    DiagnosticsInspectionError,
    inspect_run_status,
    inspect_stage_logs,
)
from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus, StageStatusRecord
from loom.pipeline.stores import LocalRunStore, path_to_run_uri


pytestmark = pytest.mark.unit


def _run_uri(tmp_path: Path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def _store_with_stage(tmp_path: Path) -> tuple[LocalRunStore, str]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:02Z",
        ),
    )
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:02Z",
        ),
    )
    return store, run_uri


def test_inspect_run_status_uses_store_scan(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    summary = inspect_run_status(run_uri, run_store=store)

    assert summary.run_uri == run_uri
    assert summary.status == "SUCCEEDED"
    assert summary.stages[0].stage_name == "build"
    assert summary.stages[0].status == "SUCCEEDED"
    assert summary.stages[0].log_available == {"stdout": False, "stderr": False}


def test_inspect_stage_logs_tails_each_stream(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_stage_log(run_uri, "build", "stdout", "a\nb\nc\n")
    store.write_stage_log(run_uri, "build", "stderr", "err\n")

    summary = inspect_stage_logs(run_uri, "build", streams=("stdout", "stderr"), tail=2, run_store=store)

    assert summary.streams[0].stream == "stdout"
    assert summary.streams[0].content == "b\nc\n"
    assert summary.streams[0].line_count == 3
    assert summary.streams[0].displayed_line_count == 2
    assert summary.streams[0].truncated is True
    assert summary.streams[1].content == "err\n"


def test_inspect_stage_logs_paths_only_allows_missing_logs(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    summary = inspect_stage_logs(run_uri, "build", paths_only=True, run_store=store)

    assert [stream.available for stream in summary.streams] == [False, False]
    assert all(stream.content is None for stream in summary.streams)


def test_inspect_stage_logs_rejects_missing_stage(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    with pytest.raises(DiagnosticsInspectionError, match="unknown stage"):
        inspect_stage_logs(run_uri, "missing", run_store=store)


def test_inspect_stage_logs_requires_content_without_paths_only(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    with pytest.raises(DiagnosticsInspectionError, match="no log content"):
        inspect_stage_logs(run_uri, "build", run_store=store)
