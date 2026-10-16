"""Integration coverage for direct run-catalog scans."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.fingerprints import format_digest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from loom.runs import CatalogWarningCode, RunCatalog


def test_run_catalog_scan_current_extracts_metadata_summary(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = create_authority_backed_serial_run_store(
        root,
        authority_store=SQLitePerRunAuthorityStore(),
    )
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
            status=RunStatus.RUNNING,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
            started_at="2020-01-01T00:00:01Z",
        ),
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
    store.write_composition_manifest(
        run_uri,
        {
            "schema_version": 1,
            "fingerprint_records": [
                {
                    "algorithm": "sha256",
                    "label": "artifact_safe_config",
                    "digest": "config-fp",
                }
            ],
        },
    )
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
            status=StageStatus.RUNNING,
            attempt=1,
            updated_at="2020-01-01T00:00:02Z",
            started_at="2020-01-01T00:00:02Z",
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
    assert summary.updated_at is not None
    assert summary.tags == {"project": "demo", "runtime": "yes"}
    assert summary.config_fingerprint == "config-fp"
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
        CatalogWarningCode.LOCAL_LIFECYCLE_UNSUPPORTED,
    ]


@pytest.mark.optional_dependency
def test_native_run_projects_current_fingerprints_timing_and_only_committed_artifacts(
    tmp_path: Path,
) -> None:
    import json
    from loom.runs._query_acquire import acquire_run
    from tests.support.native_run_fixture import run_native_fixture
    from tests.support.pipeline_execution_configs import local_execution_config

    config = tmp_path / "pipeline.json"
    config.write_text(
        json.dumps(local_execution_config(value=7)).replace("build", "source")
    )
    admission, local = run_native_fixture(config)
    assert admission.state.value == "SUCCEEDED"
    authority = SQLitePerRunAuthorityStore(admission.run_uri, read_only=True)
    snapshot = authority.open_run(admission.run_uri)
    composition = local.read_composition_manifest(admission.run_uri)
    assert composition is not None
    records = composition["fingerprint_records"]
    assert isinstance(records, list)
    identities = [
        r["digest"]
        for r in records
        if isinstance(r, dict) and r.get("label") == "artifact_safe_config"
    ]
    assert len(identities) == 1 and identities[0]

    index = local.read_artifact_index(admission.run_uri)
    index["source.uncommitted"] = ArtifactRef(
        artifact_id="uncommitted", uri="file:///not-published", artifact_type="json"
    )
    local.write_artifact_index(admission.run_uri, index)
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in local.local_run_dir(admission.run_uri).rglob("*.json")
    }

    scan = RunCatalog.open(local.root).scan_current()
    assert scan.warnings == ()
    summary = scan.summaries[0]
    assert summary.config_fingerprint == identities[0]
    assert "pipeline_fingerprint" not in summary.to_dict()
    assert snapshot.started_at and summary.started_at == snapshot.started_at
    assert snapshot.finished_at and summary.finished_at == snapshot.finished_at
    assert {a.logical_name for a in summary.artifacts} == {"source.data", "report.text"}
    record = acquire_run(local.root, admission.run_uri, authority)
    assert record.warnings == []
    assert record.sources["native"]["config_fingerprint"] == identities[0]
    assert record.sources["native"]["started_at"] == snapshot.started_at
    assert record.sources["native"]["finished_at"] == snapshot.finished_at
    for actual, projected, stage in zip(
        summary.stages, record.stages, snapshot.stages, strict=True
    ):
        attempt = stage.attempts[-1]
        commit = stage.latest_commit
        assert attempt.start_confirmed_at and commit is not None
        assert (
            actual.started_at
            == projected.sources["native"]["started_at"]
            == attempt.start_confirmed_at
        )
        assert (
            actual.finished_at
            == projected.sources["native"]["finished_at"]
            == commit.committed_at
        )
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before
