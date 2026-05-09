"""Integration coverage for direct run-catalog scans."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.fingerprints import format_digest
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.runs import CatalogWarningCode, RunCatalog


def test_run_catalog_scan_current_extracts_metadata_summary(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    run_path = root / "run-1"
    run_uri = path_to_run_uri(run_path)
    checksum = format_digest("sha256", "a" * 64)
    artifact = ArtifactRef(
        artifact_id="build/out",
        uri="file:///tmp/out.json",
        artifact_type="json",
        codec_key="json.v1",
        checksum=checksum,
        fingerprint=format_digest("sha256", "b" * 64),
        producer_stage="build",
        metadata={"role": "output"},
    )

    store.create_run(
        run_uri, metadata={"owner": "integration", "tags": {"project": "demo"}}
    )
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:05Z",
            started_at="2020-01-01T00:00:01Z",
            finished_at="2020-01-01T00:00:04Z",
        ),
    )
    store.write_composition_manifest(run_uri, {"fingerprint": "config-fp"})
    store.write_plan(run_uri, {"pipeline_fingerprint": "pipeline-fp"})
    store.write_runtime_metadata(
        run_uri,
        {"executor": "local", "backend": "local", "tags": {"runtime": "yes"}},
    )
    store.write_provenance_document(run_uri, "git", {"commit": "abc123"})
    store.write_artifact_index(run_uri, {"build.out": artifact})
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:03Z",
            started_at="2020-01-01T00:00:02Z",
            finished_at="2020-01-01T00:00:03Z",
            metadata={"node": "local"},
        ),
    )
    store.write_stage_fingerprint(
        run_uri,
        "build",
        {"fingerprint": "stage-fp"},
        attempt=1,
    )
    store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="sub-1",
            backend="fake-slurm",
            mode="batch",
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
            state=SubmittedOperationState.COMPLETED,
            manifest_relative_path="submitted/sub-1/manifest.json",
            summary_counts={"completed": 1},
        ),
    )

    result = RunCatalog.open(root).scan_current()

    assert result.warnings == ()
    assert len(result.summaries) == 1
    summary = result.summaries[0]
    assert summary.run_uri == run_uri
    assert summary.path == str(run_path)
    assert summary.status == "SUCCEEDED"
    assert summary.created_at is not None
    assert summary.updated_at == "2020-01-01T00:00:05Z"
    assert summary.tags == {"project": "demo", "runtime": "yes"}
    assert summary.config_fingerprint == "config-fp"
    assert summary.pipeline_fingerprint == "pipeline-fp"
    assert summary.git_commit == "abc123"
    assert summary.executor == "local"
    assert summary.backend == "local"
    assert summary.stages[0].stage_name == "build"
    assert summary.stages[0].status == "SUCCEEDED"
    assert summary.stages[0].fingerprint == "stage-fp"
    assert summary.artifacts[0].artifact_id == "build/out"
    assert summary.artifacts[0].checksum == checksum
    assert summary.submitted_operations[0].submission_id == "sub-1"
    result_data = result.to_dict()
    summaries = cast(list[dict[str, object]], result_data["summaries"])
    assert summaries[0]["run_uri"] == run_uri


def test_run_catalog_scan_current_returns_warnings_for_bad_candidates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    root.mkdir()
    (root / "not-a-run").mkdir()
    partial = root / "partial"
    partial.mkdir()
    partial_run_uri = path_to_run_uri(partial)
    (partial / "run.json").write_text(
        (
            "{"
            '"schema_version": 1, '
            f'"run_uri": "{partial_run_uri}", '
            '"created_at": "2020-01-01T00:00:00Z", '
            '"metadata": {}'
            "}\n"
        ),
        encoding="utf-8",
    )

    result = RunCatalog.open(root).scan_current()

    assert result.summaries == ()
    assert [warning.code for warning in result.warnings] == [
        CatalogWarningCode.INVALID_RUN,
        CatalogWarningCode.PARTIAL_RUN,
    ]
