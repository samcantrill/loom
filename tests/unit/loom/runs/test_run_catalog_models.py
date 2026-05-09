"""Unit tests for public run catalog models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from loom.runs import (
    CATALOG_WARNING_CODES,
    ArtifactSummary,
    CatalogFeatureUnavailableError,
    CatalogIndexResult,
    CatalogValidationError,
    CatalogWarning,
    CatalogWarningCode,
    ComparisonEntry,
    ComparisonSection,
    ComparisonStatus,
    ListRunsResult,
    RunCatalog,
    RunComparison,
    RunFilter,
    RunFilterKind,
    RunSummary,
    StageSummary,
    SubmittedOperationSummary,
)


def test_warning_codes_are_public_compatibility_values() -> None:
    assert CATALOG_WARNING_CODES == (
        "invalid_run",
        "unreadable_run",
        "partial_run",
        "actively_changing_run",
        "disappeared_run",
        "unsupported_schema",
        "stale_or_corrupt_catalog",
        "unrecoverable_catalog_error",
    )
    warning = CatalogWarning(
        code=CatalogWarningCode.INVALID_RUN,
        message="invalid",
        run_uri="file:///runs/a",
        details={"reason": "missing run.json"},
    )

    assert warning.to_dict() == {
        "code": "invalid_run",
        "message": "invalid",
        "run_uri": "file:///runs/a",
        "path": None,
        "details": {"reason": "missing run.json"},
    }


def test_run_summary_uses_run_uri_and_plain_serialization() -> None:
    summary = RunSummary(
        run_uri="file:///runs/a",
        status="SUCCEEDED",
        tags={"project": "demo"},
        metadata={"owner": "test"},
        config_fingerprint="sha256:abc",
        stages=[StageSummary(stage_name="build", status="SUCCEEDED", attempt=1)],
        artifacts=[
            ArtifactSummary(
                run_uri="file:///runs/a",
                artifact_id="build/out",
                checksum="sha256:def",
            )
        ],
        submitted_operations=[
            SubmittedOperationSummary(
                submission_id="sub-1",
                backend="slurm",
                mode="batch",
                state="COMPLETED",
                created_at="2020-01-01T00:00:00Z",
                updated_at="2020-01-01T00:00:01Z",
                active=False,
                summary_counts={"completed": 1},
            )
        ],
    )

    data = summary.to_dict()

    assert data["run_uri"] == "file:///runs/a"
    assert "run_id" not in data
    assert data["tags"] == {"project": "demo"}
    assert data["stages"] == [
        {
            "stage_name": "build",
            "status": "SUCCEEDED",
            "attempt": 1,
            "fingerprint": None,
            "started_at": None,
            "finished_at": None,
            "metadata": {},
        }
    ]
    with pytest.raises(TypeError):
        summary.tags["project"] = "other"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        summary.run_uri = "file:///runs/b"  # type: ignore[misc]


def test_filter_model_represents_exact_match_filter_set() -> None:
    assert RunFilter(RunFilterKind.RUN_STATUS, "FAILED").to_dict() == {
        "kind": "run_status",
        "key": None,
        "value": "FAILED",
    }
    assert RunFilter("tag", "demo", key="project").to_dict() == {
        "kind": "tag",
        "key": "project",
        "value": "demo",
    }
    kinds = {kind.value for kind in RunFilterKind}
    assert {
        "run_status",
        "tag",
        "config_fingerprint",
        "pipeline_fingerprint",
        "git_commit",
        "stage_status",
        "artifact_identity",
        "artifact_checksum",
        "executor",
        "backend",
    } <= kinds
    with pytest.raises(CatalogValidationError, match="tag filters require key"):
        RunFilter(RunFilterKind.TAG, "demo")


def test_result_and_comparison_models_serialize() -> None:
    warning = CatalogWarning("partial_run", "missing stage metadata")
    summary = RunSummary(run_uri="file:///runs/a")
    list_result = ListRunsResult(
        summaries=[summary],
        warnings=[warning],
        filters=[RunFilter("run_status", "SUCCEEDED")],
        checked_at="2020-01-01T00:00:00Z",
    )
    index_result = CatalogIndexResult(indexed_count=1, warnings=[warning])
    comparison = RunComparison(
        left_run_uri="file:///runs/a",
        right_run_uri="file:///runs/b",
        sections=[
            ComparisonSection(
                name="run",
                entries=[
                    ComparisonEntry(
                        key="status",
                        status=ComparisonStatus.DIFFERENT,
                        left="FAILED",
                        right="SUCCEEDED",
                    )
                ],
            )
        ],
        warnings=[warning],
    )

    assert list_result.to_dict()["summaries"] == [summary.to_dict()]
    assert index_result.to_dict()["indexed_count"] == 1
    comparison_data = comparison.to_dict()
    sections = cast(list[dict[str, object]], comparison_data["sections"])
    entries = cast(list[dict[str, object]], sections[0]["entries"])
    assert entries[0]["status"] == "different"
    assert {status.value for status in ComparisonStatus} == {
        "same",
        "different",
        "left_only",
        "right_only",
        "unknown",
    }


def test_run_catalog_deferred_methods_raise_catalog_error() -> None:
    catalog = RunCatalog.open("runs")

    with pytest.raises(CatalogFeatureUnavailableError):
        catalog.list()
    with pytest.raises(CatalogFeatureUnavailableError):
        catalog.compare("left", "right")
