"""Integration coverage for run-catalog metadata comparison."""

from __future__ import annotations

from pathlib import Path

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
from loom.runs import (
    CatalogWarningCode,
    ComparisonEntry,
    ComparisonStatus,
    RunCatalog,
    RunComparison,
)


def test_run_catalog_compare_identical_runs_reports_same_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    left_uri = _create_run(
        store,
        root / "left",
        config="config",
        checksum=format_digest("sha256", "a" * 64),
    )
    right_uri = _create_run(
        store,
        root / "right",
        config="config",
        checksum=format_digest("sha256", "a" * 64),
    )

    result = RunCatalog.open(root).compare(left_uri, right_uri)

    entries = _entries(result)
    assert entries["run.status"].status == ComparisonStatus.SAME
    assert entries["fingerprints.config"].status == ComparisonStatus.SAME
    assert entries["stages.build.status"].status == ComparisonStatus.SAME
    assert entries["artifacts.build.out.checksum"].status == ComparisonStatus.SAME
    assert entries["execution.executor"].status == ComparisonStatus.SAME
    assert entries["provenance.git.commit"].status == ComparisonStatus.SAME


def test_run_catalog_compare_reports_differences_and_one_sided_children(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    left_uri = _create_run(
        store,
        root / "left",
        status=RunStatus.SUCCEEDED,
        config="config-left",
        pipeline="pipeline-left",
        checksum=format_digest("sha256", "1" * 64),
        stage_name="build",
        artifact_logical_name="build.out",
        git_commit="abc123",
    )
    right_uri = _create_run(
        store,
        root / "right",
        status=RunStatus.FAILED,
        config="config-right",
        pipeline="pipeline-right",
        checksum=format_digest("sha256", "2" * 64),
        stage_name="eval",
        artifact_logical_name="eval.out",
        git_commit="def456",
    )

    result = RunCatalog.open(root).compare(left_uri, right_uri)

    entries = _entries(result)
    assert entries["run.status"].status == ComparisonStatus.DIFFERENT
    assert entries["fingerprints.config"].status == ComparisonStatus.DIFFERENT
    assert entries["fingerprints.pipeline"].status == ComparisonStatus.DIFFERENT
    assert entries["stages.build"].status == ComparisonStatus.LEFT_ONLY
    assert entries["stages.eval"].status == ComparisonStatus.RIGHT_ONLY
    assert entries["artifacts.build.out"].status == ComparisonStatus.LEFT_ONLY
    assert entries["artifacts.eval.out"].status == ComparisonStatus.RIGHT_ONLY
    assert entries["provenance.git.commit"].status == ComparisonStatus.DIFFERENT


def test_run_catalog_compare_warns_for_missing_run(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    left_uri = _create_run(
        store,
        root / "left",
        config="config",
        checksum=format_digest("sha256", "a" * 64),
    )
    missing_uri = path_to_run_uri(root / "missing")

    result = RunCatalog.open(root).compare(left_uri, missing_uri)

    assert [warning.code for warning in result.warnings] == [
        CatalogWarningCode.DISAPPEARED_RUN
    ]
    entries = _entries(result)
    assert entries["run.status"].status == ComparisonStatus.UNKNOWN
    assert result.right_run_uri == missing_uri


def test_run_catalog_compare_propagates_partial_run_warnings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    left_uri = _create_run(
        store,
        root / "left",
        config="config",
        checksum=format_digest("sha256", "a" * 64),
    )
    right_path = root / "partial"
    right_path.mkdir(parents=True)
    right_uri = path_to_run_uri(right_path)
    (right_path / "run.json").write_text(
        (
            "{"
            '"schema_version": 1, '
            f'"run_uri": "{right_uri}", '
            '"created_at": "2020-01-01T00:00:00Z", '
            '"metadata": {}'
            "}\n"
        ),
        encoding="utf-8",
    )

    result = RunCatalog.open(root).compare(left_uri, right_uri)

    assert [warning.code for warning in result.warnings] == [
        CatalogWarningCode.PARTIAL_RUN,
        CatalogWarningCode.DISAPPEARED_RUN,
    ]


def _create_run(
    store: LocalRunStore,
    run_path: Path,
    *,
    status: RunStatus = RunStatus.SUCCEEDED,
    config: str,
    checksum: str,
    pipeline: str = "pipeline",
    stage_name: str = "build",
    artifact_logical_name: str = "build.out",
    git_commit: str = "abc123",
) -> str:
    run_uri = path_to_run_uri(run_path)
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=status,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_composition_manifest(run_uri, {"fingerprint": config})
    store.write_plan(run_uri, {"pipeline_fingerprint": pipeline})
    store.write_runtime_metadata(run_uri, {"executor": "local", "backend": "local"})
    store.write_provenance_document(run_uri, "git", {"commit": git_commit})
    store.write_stage_status(
        run_uri,
        stage_name,
        StageStatusRecord(
            run_uri=run_uri,
            stage_name=stage_name,
            status=StageStatus.SUCCEEDED
            if status is RunStatus.SUCCEEDED
            else StageStatus.FAILED,
            attempt=1,
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="sub-1",
            backend="local",
            mode="batch",
            state=SubmittedOperationState.COMPLETED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
            manifest_relative_path="submitted/sub-1/manifest.json",
        ),
    )
    store.write_artifact_index(
        run_uri,
        {
            artifact_logical_name: ArtifactRef(
                artifact_id=artifact_logical_name.replace(".", "/"),
                uri="file:///tmp/out.json",
                artifact_type="json",
                codec_key="json.v1",
                checksum=checksum,
                producer_stage=stage_name,
            )
        },
    )
    return run_uri


def _entries(result: RunComparison) -> dict[str, ComparisonEntry]:
    return {entry.key: entry for section in result.sections for entry in section.entries}
