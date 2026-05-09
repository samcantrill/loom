"""Unit tests for direct run-catalog scan helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom.pipeline.stores import RunFreshnessRecord, path_to_run_uri
from loom.runs import CatalogWarningCode
from loom.runs._extract import extract_current_summary
from loom.runs._scan import scan_current_collection


class ChangingFreshnessStore:
    def __init__(self, run_uri: str) -> None:
        self.run_uri = run_uri
        self.revision = 0

    def read_run_freshness(self, run_uri: str) -> RunFreshnessRecord | None:
        self.revision += 1
        return RunFreshnessRecord(
            run_uri=run_uri,
            token=f"token-{self.revision}",
            updated_at="2020-01-01T00:00:00Z",
            revision=self.revision,
        )

    def read_run_document(self, run_uri: str) -> dict[str, Any]:
        return {
            "run_uri": run_uri,
            "created_at": "2020-01-01T00:00:00Z",
            "metadata": {},
        }

    def read_run_user_metadata(self, run_uri: str) -> dict[str, Any]:
        return {}

    def read_run_status(self, run_uri: str) -> None:
        return None

    def read_runtime_metadata(self, run_uri: str) -> None:
        return None

    def read_composition_manifest(self, run_uri: str) -> None:
        return None

    def read_plan(self, run_uri: str) -> None:
        return None

    def read_provenance_document(self, run_uri: str, name: str) -> None:
        return None

    def list_run_stages(self, run_uri: str) -> tuple[str, ...]:
        return ()

    def read_stage_status(self, run_uri: str, stage_name: str) -> None:
        return None

    def read_stage_fingerprint(self, run_uri: str, stage_name: str) -> None:
        return None

    def read_artifact_index(self, run_uri: str) -> dict[str, Any]:
        return {}

    def list_submitted_operations(self, run_uri: str) -> tuple[Any, ...]:
        return ()


def test_scan_current_collection_classifies_invalid_and_partial_candidates(
    tmp_path: Path,
) -> None:
    collection = tmp_path / "runs"
    collection.mkdir()
    (collection / ".loom_catalog").mkdir()
    (collection / "not-a-run").mkdir()
    (collection / "notes.txt").write_text("not a run", encoding="utf-8")

    partial = collection / "partial"
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

    unsupported = collection / "unsupported"
    unsupported.mkdir()
    unsupported_run_uri = path_to_run_uri(unsupported)
    (unsupported / "run.json").write_text(
        (
            "{"
            '"schema_version": 999, '
            f'"run_uri": "{unsupported_run_uri}", '
            '"created_at": "2020-01-01T00:00:00Z", '
            '"metadata": {}'
            "}\n"
        ),
        encoding="utf-8",
    )

    result = scan_current_collection(collection)

    assert result.summaries == ()
    assert [warning.code for warning in result.warnings] == [
        CatalogWarningCode.INVALID_RUN,
        CatalogWarningCode.INVALID_RUN,
        CatalogWarningCode.PARTIAL_RUN,
        CatalogWarningCode.UNSUPPORTED_SCHEMA,
    ]
    assert all(
        ".loom_catalog" not in (warning.path or "") for warning in result.warnings
    )


def test_extract_current_summary_warns_when_freshness_keeps_changing(
    tmp_path: Path,
) -> None:
    run_uri = path_to_run_uri(tmp_path / "runs" / "run")
    summary, warning = extract_current_summary(
        ChangingFreshnessStore(run_uri),
        run_uri=run_uri,
        path=tmp_path / "runs" / "run",
        max_retries=1,
    )

    assert summary is None
    assert warning is not None
    assert warning.code == CatalogWarningCode.ACTIVELY_CHANGING_RUN
