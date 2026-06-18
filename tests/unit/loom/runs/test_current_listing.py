"""Unit tests for current run-catalog listing helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.runs import (
    ArtifactSummary,
    CatalogValidationError,
    RunFilter,
    RunFilterKind,
    RunSummary,
    StageSummary,
)
from loom.runs._extract import CurrentRunSummary
from loom.runs._sqlite import _query_catalog_summaries, _replace_catalog_records
from loom.pipeline.stores import RunFreshnessRecord


def test_query_catalog_summaries_applies_and_filters_and_orders_by_run_uri(
    tmp_path: Path,
) -> None:
    collection = tmp_path / "runs"
    _replace_catalog_records(
        collection,
        [
            _record(
                "file:///runs/b",
                status="SUCCEEDED",
                tags={"project": "demo", "kind": "train"},
                stage_status="FAILED",
                artifact_checksum="sha256:b",
            ),
            _record(
                "file:///runs/a",
                status="SUCCEEDED",
                tags={"project": "demo", "kind": "eval"},
                stage_status="SUCCEEDED",
                artifact_checksum="sha256:a",
            ),
            _record(
                "file:///runs/c",
                status="FAILED",
                tags={"project": "other", "kind": "train"},
                stage_status="FAILED",
                artifact_checksum="sha256:c",
            ),
        ],
        checked_at="2020-01-01T00:00:00Z",
    )

    summaries = _query_catalog_summaries(
        collection,
        [
            RunFilter(RunFilterKind.RUN_STATUS, "SUCCEEDED"),
            RunFilter(RunFilterKind.TAG, "demo", key="project"),
        ],
    )

    assert [summary.run_uri for summary in summaries] == [
        "file:///runs/a",
        "file:///runs/b",
    ]


def test_query_catalog_summaries_supports_keyed_stage_and_artifact_filters(
    tmp_path: Path,
) -> None:
    collection = tmp_path / "runs"
    _replace_catalog_records(
        collection,
        [
            _record(
                "file:///runs/a",
                stage_status="SUCCEEDED",
                artifact_checksum="sha256:a",
            ),
            _record(
                "file:///runs/b",
                stage_status="FAILED",
                artifact_checksum="sha256:b",
            ),
        ],
        checked_at="2020-01-01T00:00:00Z",
    )

    stage_match = _query_catalog_summaries(
        collection, [RunFilter(RunFilterKind.STAGE_STATUS, "FAILED", key="build")]
    )
    any_artifact_match = _query_catalog_summaries(
        collection, [RunFilter(RunFilterKind.ARTIFACT_CHECKSUM, "sha256:a")]
    )
    keyed_artifact_match = _query_catalog_summaries(
        collection,
        [RunFilter(RunFilterKind.ARTIFACT_IDENTITY, "build/out", key="build.out")],
    )

    assert [summary.run_uri for summary in stage_match] == ["file:///runs/b"]
    assert [summary.run_uri for summary in any_artifact_match] == ["file:///runs/a"]
    assert [summary.run_uri for summary in keyed_artifact_match] == [
        "file:///runs/a",
        "file:///runs/b",
    ]


def test_query_catalog_summaries_rejects_keys_for_run_level_filters(
    tmp_path: Path,
) -> None:
    collection = tmp_path / "runs"
    _replace_catalog_records(
        collection,
        [_record("file:///runs/a")],
        checked_at="2020-01-01T00:00:00Z",
    )

    with pytest.raises(CatalogValidationError, match="run_status"):
        _query_catalog_summaries(
            collection, [RunFilter(RunFilterKind.RUN_STATUS, "SUCCEEDED", key="status")]
        )


def _record(
    run_uri: str,
    *,
    status: str = "SUCCEEDED",
    tags: dict[str, str] | None = None,
    stage_status: str = "SUCCEEDED",
    artifact_checksum: str = "sha256:a",
) -> CurrentRunSummary:
    return CurrentRunSummary(
        summary=RunSummary(
            run_uri=run_uri,
            status=status,
            tags=tags or {"project": "demo"},
            config_fingerprint="config-fp",
            pipeline_fingerprint="pipeline-fp",
            git_commit="abc123",
            executor="local",
            backend="local",
            stages=[StageSummary(stage_name="build", status=stage_status)],
            artifacts=[
                ArtifactSummary(
                    run_uri=run_uri,
                    artifact_id="build/out",
                    logical_name="build.out",
                    checksum=artifact_checksum,
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
