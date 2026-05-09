"""Public run-catalog comparison contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from loom.pipeline.status import RunStatus, RunStatusRecord
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.runs import ComparisonStatus, RunCatalog, RunComparison


def test_run_catalog_compare_returns_serializable_public_result(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    left_uri = _create_run(store, root / "left", RunStatus.SUCCEEDED)
    right_uri = _create_run(store, root / "right", RunStatus.FAILED)

    result = RunCatalog.open(root).compare(left_uri, right_uri)

    assert isinstance(result, RunComparison)
    assert result.left_run_uri == left_uri
    assert result.right_run_uri == right_uri
    data = result.to_dict()
    sections = cast(list[dict[str, object]], data["sections"])
    assert [section["name"] for section in sections] == [
        "run",
        "fingerprints",
        "stages",
        "artifacts",
        "execution",
        "provenance",
    ]
    run_entries = cast(list[dict[str, object]], sections[0]["entries"])
    assert run_entries[0]["key"] == "run.status"
    assert run_entries[0]["status"] == ComparisonStatus.DIFFERENT.value
    assert data["checked_at"] is not None


def _create_run(store: LocalRunStore, run_path: Path, status: RunStatus) -> str:
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
    return run_uri
