"""Public run-catalog contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import RunStatus, RunStatusRecord
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.runs import ListRunsResult, RunCatalog, RunFilter, RunFilterKind


def test_run_catalog_list_returns_public_result_envelope(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = create_authority_backed_serial_run_store(
        root,
        authority_store=SQLitePerRunAuthorityStore(),
    )
    run_path = root / "run-1"
    run_uri = path_to_run_uri(run_path)
    store.create_run(run_uri, metadata={"tags": {"project": "contract"}})
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    run_filter = RunFilter(RunFilterKind.TAG, "contract", key="project")

    result = RunCatalog.open(root).list(filters=[run_filter])

    assert isinstance(result, ListRunsResult)
    assert result.filters == (run_filter,)
    assert result.warnings == ()
    data = result.to_dict()
    summaries = cast(list[dict[str, object]], data["summaries"])
    assert summaries[0]["run_uri"] == run_uri
    assert data["filters"] == [run_filter.to_dict()]
    assert data["checked_at"] is not None
