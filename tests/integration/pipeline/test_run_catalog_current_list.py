"""Integration coverage for current run-catalog list behavior."""

from __future__ import annotations

import sqlite3
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
from loom.runs import CatalogWarningCode, RunCatalog, RunFilter, RunFilterKind
from loom.runs._sqlite import catalog_db_path, read_catalog_summaries


def test_run_catalog_list_creates_current_sidecar_and_returns_warnings(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    run_uri = _create_catalog_run(
        store,
        root / "run-1",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
    )
    partial = root / "partial"
    partial.mkdir(parents=True)
    (partial / "run.json").write_text(
        (
            "{"
            '"schema_version": 1, '
            f'"run_uri": "{path_to_run_uri(partial)}", '
            '"created_at": "2020-01-01T00:00:00Z", '
            '"metadata": {}'
            "}\n"
        ),
        encoding="utf-8",
    )

    result = RunCatalog.open(root).list()

    assert [summary.run_uri for summary in result.summaries] == [run_uri]
    assert [warning.code for warning in result.warnings] == [
        CatalogWarningCode.PARTIAL_RUN
    ]
    assert result.filters == ()
    assert result.checked_at is not None
    assert catalog_db_path(root).exists()


def test_run_catalog_list_reconciles_new_changed_deleted_and_stale_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    first_uri = _create_catalog_run(
        store,
        root / "run-1",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
    )
    second_path = root / "run-2"
    second_uri = _create_catalog_run(
        store,
        second_path,
        status=RunStatus.FAILED,
        tag_value="other",
    )
    catalog = RunCatalog.open(root)
    assert [summary.run_uri for summary in catalog.list().summaries] == [
        first_uri,
        second_uri,
    ]

    _insert_stale_row(root, "file:///stale/run")
    _remove_run_dir(second_path)
    third_uri = _create_catalog_run(
        store,
        root / "run-3",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
    )
    store.write_run_status(
        first_uri,
        RunStatusRecord(
            run_uri=first_uri,
            status=RunStatus.FAILED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:05Z",
        ),
    )

    result = catalog.list(filters=[RunFilter(RunFilterKind.RUN_STATUS, "SUCCEEDED")])

    assert [summary.run_uri for summary in result.summaries] == [third_uri]
    assert [summary.run_uri for summary in read_catalog_summaries(root)] == [
        first_uri,
        third_uri,
    ]


def test_run_catalog_list_filters_all_supported_kinds(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    run_uri = _create_catalog_run(
        store,
        root / "run-1",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
        checksum=format_digest("sha256", "1" * 64),
    )
    _create_catalog_run(
        store,
        root / "run-2",
        status=RunStatus.FAILED,
        tag_value="other",
        checksum=format_digest("sha256", "2" * 64),
        config_fingerprint="config-other",
        pipeline_fingerprint="pipeline-other",
        git_commit="def456",
        executor="remote",
        backend="remote",
        artifact_id="other/out",
    )
    catalog = RunCatalog.open(root)

    filter_sets = [
        [RunFilter(RunFilterKind.RUN_STATUS, "SUCCEEDED")],
        [RunFilter(RunFilterKind.TAG, "demo", key="project")],
        [RunFilter(RunFilterKind.CONFIG_FINGERPRINT, "config-demo")],
        [RunFilter(RunFilterKind.PIPELINE_FINGERPRINT, "pipeline-demo")],
        [RunFilter(RunFilterKind.GIT_COMMIT, "abc123")],
        [RunFilter(RunFilterKind.STAGE_STATUS, "SUCCEEDED", key="build")],
        [RunFilter(RunFilterKind.ARTIFACT_IDENTITY, "build/out", key="build.out")],
        [
            RunFilter(
                RunFilterKind.ARTIFACT_CHECKSUM,
                format_digest("sha256", "1" * 64),
                key="build.out",
            )
        ],
        [RunFilter(RunFilterKind.EXECUTOR, "local")],
        [RunFilter(RunFilterKind.BACKEND, "local")],
    ]

    for filters in filter_sets:
        result = catalog.list(filters=filters)
        assert [summary.run_uri for summary in result.summaries] == [run_uri]
        assert result.filters == tuple(filters)


def test_run_catalog_list_recovers_missing_and_corrupt_sidecar(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    run_uri = _create_catalog_run(
        store,
        root / "run-1",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
    )
    catalog = RunCatalog.open(root)
    catalog.rebuild()
    catalog_db_path(root).unlink()
    assert [summary.run_uri for summary in catalog.list().summaries] == [run_uri]

    catalog_db_path(root).write_text("not sqlite", encoding="utf-8")
    assert [summary.run_uri for summary in catalog.list().summaries] == [run_uri]


def test_multiple_catalog_instances_can_list_and_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    run_uri = _create_catalog_run(
        store,
        root / "run-1",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
    )
    first = RunCatalog.open(root)
    second = RunCatalog.open(root)

    assert [summary.run_uri for summary in first.list().summaries] == [run_uri]
    assert second.rebuild().indexed_count == 1
    assert [summary.run_uri for summary in first.list().summaries] == [run_uri]


def test_run_catalog_list_filters_synthetic_large_collection(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    expected: list[str] = []
    for index in range(1000):
        status = RunStatus.SUCCEEDED if index % 10 == 0 else RunStatus.FAILED
        run_uri = _create_minimal_catalog_run(
            store,
            root / f"run-{index:03d}",
            status=status,
            tag_value="bulk",
        )
        if status is RunStatus.SUCCEEDED:
            expected.append(run_uri)

    result = RunCatalog.open(root).list(
        filters=[
            RunFilter(RunFilterKind.RUN_STATUS, "SUCCEEDED"),
            RunFilter(RunFilterKind.TAG, "bulk", key="project"),
        ]
    )

    assert [summary.run_uri for summary in result.summaries] == expected


def _create_catalog_run(
    store: LocalRunStore,
    run_path: Path,
    *,
    status: RunStatus,
    tag_value: str,
    checksum: str | None = None,
    config_fingerprint: str = "config-demo",
    pipeline_fingerprint: str = "pipeline-demo",
    git_commit: str = "abc123",
    executor: str = "local",
    backend: str = "local",
    artifact_id: str = "build/out",
) -> str:
    run_uri = path_to_run_uri(run_path)
    checksum = checksum or format_digest("sha256", "a" * 64)
    store.create_run(run_uri, metadata={"tags": {"project": tag_value}})
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=status,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_composition_manifest(run_uri, {"fingerprint": config_fingerprint})
    store.write_plan(run_uri, {"pipeline_fingerprint": pipeline_fingerprint})
    store.write_runtime_metadata(run_uri, {"executor": executor, "backend": backend})
    store.write_provenance_document(run_uri, "git", {"commit": git_commit})
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED
            if status is RunStatus.SUCCEEDED
            else StageStatus.FAILED,
            attempt=1,
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_artifact_index(
        run_uri,
        {
            "build.out": ArtifactRef(
                artifact_id=artifact_id,
                uri="file:///tmp/out.json",
                artifact_type="json",
                codec_key="json.v1",
                checksum=checksum,
                producer_stage="build",
            )
        },
    )
    return run_uri


def _create_minimal_catalog_run(
    store: LocalRunStore,
    run_path: Path,
    *,
    status: RunStatus,
    tag_value: str,
) -> str:
    run_uri = path_to_run_uri(run_path)
    store.create_run(run_uri, metadata={"tags": {"project": tag_value}})
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=status,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    return run_uri


def _insert_stale_row(root: Path, run_uri: str) -> None:
    with sqlite3.connect(catalog_db_path(root)) as connection:
        connection.execute(
            """
            INSERT INTO run_summaries(
                run_uri,
                summary_json,
                metadata_json,
                tags_json,
                freshness_token,
                freshness_updated_at,
                freshness_revision,
                indexed_at
            )
            VALUES (?, '{}', '{}', '{}', 'stale', '2020-01-01T00:00:00Z', 1,
                '2020-01-01T00:00:00Z')
            """,
            (run_uri,),
        )


def _remove_run_dir(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()
