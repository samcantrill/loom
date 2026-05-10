"""Integration coverage for run-catalog SQLite rebuilds."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import RunStatus, RunStatusRecord
from loom.pipeline.stores import path_to_run_uri
from loom.runs import CatalogWarningCode, RunCatalog
from loom.runs._sqlite import catalog_db_path, read_catalog_summaries


def test_run_catalog_rebuild_creates_sqlite_sidecar_from_collection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    run_uri = _create_run(root, root / "run-1")
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

    result = RunCatalog.open(root).rebuild()

    assert result.indexed_count == 1
    assert result.skipped_count == 1
    assert [warning.code for warning in result.warnings] == [
        CatalogWarningCode.LOCAL_LIFECYCLE_UNSUPPORTED
    ]
    assert catalog_db_path(root).exists()
    summaries = read_catalog_summaries(root)
    assert [summary.run_uri for summary in summaries] == [run_uri]
    assert summaries[0].status == "SUCCEEDED"


def test_run_catalog_rebuild_deletes_stale_rows_and_survives_db_deletion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    first_uri = _create_run(root, root / "run-1")
    catalog = RunCatalog.open(root)
    catalog.rebuild()

    _insert_stale_row(root, "file:///stale/run")
    assert catalog.rebuild().indexed_count == 1
    assert [summary.run_uri for summary in read_catalog_summaries(root)] == [first_uri]

    catalog_db_path(root).unlink()
    second_uri = _create_run(root, root / "run-2")
    result = catalog.rebuild()

    assert result.indexed_count == 2
    assert [summary.run_uri for summary in read_catalog_summaries(root)] == [
        first_uri,
        second_uri,
    ]


def test_run_catalog_rebuild_recovers_corrupt_sidecar_without_touching_run_store(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    _create_run(root, root / "run-1")
    run_json = root / "run-1" / "run.json"
    before = run_json.read_text(encoding="utf-8")
    db_path = catalog_db_path(root)
    db_path.parent.mkdir(parents=True)
    db_path.write_text("not a sqlite database", encoding="utf-8")

    result = RunCatalog.open(root).rebuild()

    assert result.indexed_count == 1
    assert len(read_catalog_summaries(root)) == 1
    assert run_json.read_text(encoding="utf-8") == before


def test_multiple_catalog_instances_can_rebuild_same_sidecar(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _create_run(root, root / "run-1")

    first = RunCatalog.open(root)
    second = RunCatalog.open(root)

    assert first.rebuild().indexed_count == 1
    assert second.rebuild().indexed_count == 1
    assert len(read_catalog_summaries(root)) == 1


def _create_run(root: Path, run_path: Path) -> str:
    store = create_authority_backed_serial_run_store(root)
    run_uri = path_to_run_uri(run_path)
    store.create_run(run_uri, metadata={"tags": {"suite": "integration"}})
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
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
