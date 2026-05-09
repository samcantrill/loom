"""Unit tests for diagnostics status and log inspection."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.diagnostics.inspection import (
    DiagnosticsInspectionError,
    inspect_run_artifact,
    inspect_run_artifacts,
    inspect_run_status,
    inspect_stage_logs,
)
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.pipeline.stores import LocalRunStore, path_to_run_uri, run_uri_to_path
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline import PipelineRunner, RunRequest
from tests.unit.loom.pipeline.execution.test_authority_adapter import (
    _pipeline,
    _store,
)


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


def _artifact_ref(
    *,
    artifact_id: str = "build/data",
    artifact_type: str = "json",
    producer_stage: str = "build",
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        uri=f"file:///tmp/{artifact_id}",
        artifact_type=artifact_type,
        codec_key="json.v1" if artifact_type == "json" else "text.v1",
        producer_stage=producer_stage,
        metadata={"label": artifact_id},
    )


def test_inspect_run_status_uses_store_scan(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    summary = inspect_run_status(run_uri, run_store=store)

    assert summary.run_uri == run_uri
    assert summary.status == "SUCCEEDED"
    assert summary.stages[0].stage_name == "build"
    assert summary.stages[0].status == "SUCCEEDED"
    assert summary.stages[0].log_available == {"stdout": False, "stderr": False}


def test_inspect_run_status_includes_submitted_operation_summaries(
    tmp_path: Path,
) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    record = SubmittedOperationRecord(
        run_uri=run_uri,
        submission_id="sub-1",
        backend="test-backend",
        mode="batch",
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:01Z",
        state=SubmittedOperationState.SUBMITTED,
        manifest_relative_path="submitted/sub-1/manifest.json",
        summary_counts={"submitted": 1},
    )
    store.write_submitted_operation(run_uri, record)

    summary = inspect_run_status(run_uri, run_store=store)

    assert summary.submitted_operations[0].submission_id == "sub-1"
    assert summary.submitted_operations[0].active is True
    operations = cast(
        list[dict[str, object]], summary.to_dict()["submitted_operations"]
    )
    assert operations[0]["backend"] == "test-backend"


def test_inspect_run_status_uses_authoritative_facts_over_corrupt_legacy_files(
    tmp_path: Path,
) -> None:
    authority = SQLitePerRunAuthorityStore(clock=lambda: "2020-01-01T00:00:00Z")
    store = _store(tmp_path, authority)
    run_uri = _run_uri(tmp_path)
    PipelineRunner(run_store=store).run(RunRequest(pipeline=_pipeline(), run_uri=run_uri))
    run_path = run_uri_to_path(run_uri)
    (run_path / "status.json").write_text("not json", encoding="utf-8")
    (run_path / "artifacts.json").write_text("not json", encoding="utf-8")
    (run_path / "stages" / "build" / "status.json").write_text(
        "not json", encoding="utf-8"
    )

    summary = inspect_run_status(run_uri, run_store=store)
    artifacts = inspect_run_artifacts(run_uri, run_store=store)

    assert summary.status == "SUCCEEDED"
    assert {stage.stage_name: stage.status for stage in summary.stages} == {
        "build": "SUCCEEDED",
        "report": "SUCCEEDED",
    }
    assert {artifact.key for artifact in artifacts.artifacts} == {
        "build.data",
        "report.text",
    }


def test_inspect_stage_logs_tails_each_stream(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_stage_log(run_uri, "build", "stdout", "a\nb\nc\n")
    store.write_stage_log(run_uri, "build", "stderr", "err\n")

    summary = inspect_stage_logs(
        run_uri, "build", streams=("stdout", "stderr"), tail=2, run_store=store
    )

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


def test_inspect_run_artifacts_sorts_and_summarizes_metadata(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_stage_provenance(run_uri, "build", {"tool": "loom"}, attempt=1)
    store.write_artifact_index(
        run_uri,
        {
            "report.text": _artifact_ref(
                artifact_id="report/text",
                artifact_type="text",
                producer_stage="report",
            ),
            "build.data": _artifact_ref(),
        },
    )

    summary = inspect_run_artifacts(run_uri, run_store=store)

    assert summary.artifact_count == 2
    assert [artifact.key for artifact in summary.artifacts] == [
        "build.data",
        "report.text",
    ]
    build = summary.artifacts[0]
    assert build.artifact_id == "build/data"
    assert build.stage_name == "build"
    assert build.output_name == "data"
    assert build.metadata == {"label": "build/data"}
    assert build.provenance_available is True
    assert build.to_dict()["artifact_type"] == "json"


def test_inspect_run_artifact_includes_stage_provenance(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_stage_provenance(run_uri, "build", {"tool": "loom"}, attempt=1)
    store.write_artifact_index(run_uri, {"build.data": _artifact_ref()})

    detail = inspect_run_artifact(run_uri, "build/data", run_store=store)

    assert detail.artifact.key == "build.data"
    assert detail.stage_provenance == {"tool": "loom"}
    assert detail.to_dict()["stage_provenance"] == {"tool": "loom"}


def test_inspect_run_artifact_rejects_missing_artifact(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)

    with pytest.raises(DiagnosticsInspectionError, match="unknown artifact"):
        inspect_run_artifact(run_uri, "missing/out", run_store=store)


def test_inspect_run_artifact_rejects_ambiguous_artifact_id(tmp_path: Path) -> None:
    store, run_uri = _store_with_stage(tmp_path)
    store.write_artifact_index(
        run_uri,
        {
            "build.data": _artifact_ref(artifact_id="duplicate/id"),
            "report.text": _artifact_ref(
                artifact_id="duplicate/id",
                artifact_type="text",
                producer_stage="report",
            ),
        },
    )

    with pytest.raises(DiagnosticsInspectionError, match="ambiguous artifact"):
        inspect_run_artifact(run_uri, "duplicate/id", run_store=store)
