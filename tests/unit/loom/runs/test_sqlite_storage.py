"""Unit tests for private run-catalog SQLite storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loom.pipeline.stores import RunFreshnessRecord
from loom.runs import (
    ArtifactSummary,
    CatalogWarningCode,
    RunSummary,
    StageSummary,
    SubmittedOperationSummary,
)
from loom.runs._extract import CurrentRunSummary
from loom.runs._sqlite import (
    CATALOG_SCHEMA_VERSION,
    catalog_db_path,
    catalog_sidecar_dir,
    read_catalog_summaries,
    rebuild_catalog,
)
from loom.runs._sqlite import _replace_catalog_records


def test_catalog_paths_are_private_sidecar_paths(tmp_path: Path) -> None:
    collection = tmp_path / "runs"

    assert catalog_sidecar_dir(collection) == collection / ".loom_catalog"
    assert catalog_db_path(collection) == collection / ".loom_catalog" / "catalog.sqlite"


def test_rebuild_missing_collection_warns_without_creating_sidecar(
    tmp_path: Path,
) -> None:
    collection = tmp_path / "missing"

    result = rebuild_catalog(collection)

    assert result.indexed_count == 0
    assert result.skipped_count == 1
    assert result.warnings[0].code == CatalogWarningCode.UNREADABLE_RUN
    assert not collection.exists()


def test_replace_catalog_records_persists_summary_and_filter_rows(
    tmp_path: Path,
) -> None:
    collection = tmp_path / "runs"
    record = _current_record("file:///runs/a")

    _replace_catalog_records(collection, [record], checked_at="2020-01-01T00:00:00Z")

    summaries = read_catalog_summaries(collection)
    assert len(summaries) == 1
    assert summaries[0].run_uri == "file:///runs/a"
    assert summaries[0].stages[0].stage_name == "build"
    assert summaries[0].artifacts[0].checksum == "sha256:abc"
    with sqlite3.connect(catalog_db_path(collection)) as connection:
        schema_version = connection.execute(
            "SELECT value FROM catalog_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
        filter_rows = connection.execute(
            "SELECT kind, key, value FROM filter_facts ORDER BY kind, key, value"
        ).fetchall()
        freshness = connection.execute(
            """
            SELECT freshness_token, freshness_updated_at, freshness_revision
            FROM run_summaries
            WHERE run_uri = ?
            """,
            ("file:///runs/a",),
        ).fetchone()

    assert schema_version == str(CATALOG_SCHEMA_VERSION)
    assert ("run_status", None, "SUCCEEDED") in filter_rows
    assert ("tag", "project", "demo") in filter_rows
    assert ("stage_status", "build", "SUCCEEDED") in filter_rows
    assert ("artifact_checksum", "build.out", "sha256:abc") in filter_rows
    assert freshness == ("token-file:///runs/a", "2020-01-01T00:00:00Z", 1)


def test_replace_catalog_records_removes_stale_rows(tmp_path: Path) -> None:
    collection = tmp_path / "runs"

    _replace_catalog_records(
        collection,
        [_current_record("file:///runs/old")],
        checked_at="2020-01-01T00:00:00Z",
    )
    _replace_catalog_records(
        collection,
        [_current_record("file:///runs/new")],
        checked_at="2020-01-01T00:00:01Z",
    )

    assert [summary.run_uri for summary in read_catalog_summaries(collection)] == [
        "file:///runs/new"
    ]


def test_incompatible_catalog_db_is_rebuilt(tmp_path: Path) -> None:
    collection = tmp_path / "runs"
    db_path = catalog_db_path(collection)
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE catalog_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO catalog_metadata(key, value) VALUES('schema_version', '999')"
        )

    _replace_catalog_records(
        collection,
        [_current_record("file:///runs/rebuilt")],
        checked_at="2020-01-01T00:00:00Z",
    )

    assert [summary.run_uri for summary in read_catalog_summaries(collection)] == [
        "file:///runs/rebuilt"
    ]


def _current_record(run_uri: str) -> CurrentRunSummary:
    return CurrentRunSummary(
        summary=RunSummary(
            run_uri=run_uri,
            status="SUCCEEDED",
            display_name=run_uri.rsplit("/", 1)[-1],
            path="/tmp/run",
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
            metadata={"owner": "unit"},
            tags={"project": "demo"},
            config_fingerprint="config-fp",
            pipeline_fingerprint="pipeline-fp",
            git_commit="abc123",
            executor="local",
            backend="local",
            stages=[
                StageSummary(
                    stage_name="build",
                    status="SUCCEEDED",
                    attempt=1,
                    fingerprint="stage-fp",
                )
            ],
            artifacts=[
                ArtifactSummary(
                    run_uri=run_uri,
                    artifact_id="build/out",
                    logical_name="build.out",
                    checksum="sha256:abc",
                )
            ],
            submitted_operations=[
                SubmittedOperationSummary(
                    submission_id="sub-1",
                    backend="local",
                    mode="batch",
                    state="COMPLETED",
                    created_at="2020-01-01T00:00:00Z",
                    updated_at="2020-01-01T00:00:01Z",
                )
            ],
        ),
        freshness=RunFreshnessRecord(
            run_uri=run_uri,
            token=f"token-{run_uri}",
            updated_at="2020-01-01T00:00:00Z",
            revision=1,
        ),
    )
