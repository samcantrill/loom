"""Unit tests for metadata-only run comparison helpers."""

from __future__ import annotations

from loom.runs import (
    ArtifactSummary,
    ComparisonStatus,
    RunSummary,
    StageSummary,
    SubmittedOperationSummary,
)
from loom.runs._compare import compare_summaries


def test_compare_summaries_builds_stable_sections_and_scalar_statuses() -> None:
    comparison = compare_summaries(
        RunSummary(
            run_uri="file:///runs/a",
            status="SUCCEEDED",
            config_fingerprint="config-a",
            pipeline_fingerprint="pipeline",
            git_commit="abc123",
            executor="local",
            backend="local",
        ),
        RunSummary(
            run_uri="file:///runs/b",
            status="FAILED",
            config_fingerprint="config-b",
            pipeline_fingerprint="pipeline",
            git_commit=None,
            executor="local",
            backend="slurm",
        ),
    )

    assert [section.name for section in comparison] == [
        "run",
        "fingerprints",
        "stages",
        "artifacts",
        "execution",
        "provenance",
    ]
    entries = {entry.key: entry for section in comparison for entry in section.entries}
    assert entries["run.status"].status == ComparisonStatus.DIFFERENT
    assert entries["fingerprints.config"].status == ComparisonStatus.DIFFERENT
    assert entries["fingerprints.pipeline"].status == ComparisonStatus.SAME
    assert entries["execution.executor"].status == ComparisonStatus.SAME
    assert entries["execution.backend"].status == ComparisonStatus.DIFFERENT
    assert entries["provenance.git.commit"].status == ComparisonStatus.UNKNOWN


def test_compare_summaries_marks_one_sided_stages_and_artifacts() -> None:
    comparison = compare_summaries(
        RunSummary(
            run_uri="file:///runs/a",
            stages=[StageSummary(stage_name="train", status="SUCCEEDED")],
            artifacts=[
                ArtifactSummary(
                    run_uri="file:///runs/a",
                    artifact_id="metrics",
                    logical_name="eval.metrics",
                    checksum="sha256:a",
                )
            ],
        ),
        RunSummary(
            run_uri="file:///runs/b",
            stages=[StageSummary(stage_name="eval", status="SUCCEEDED")],
            artifacts=[
                ArtifactSummary(
                    run_uri="file:///runs/b",
                    artifact_id="model",
                    logical_name="train.model",
                    checksum="sha256:b",
                )
            ],
        ),
    )

    entries = {entry.key: entry for section in comparison for entry in section.entries}
    assert entries["stages.train"].status == ComparisonStatus.LEFT_ONLY
    assert entries["stages.eval"].status == ComparisonStatus.RIGHT_ONLY
    assert entries["artifacts.eval.metrics"].status == ComparisonStatus.LEFT_ONLY
    assert entries["artifacts.train.model"].status == ComparisonStatus.RIGHT_ONLY


def test_compare_summaries_uses_stable_keys_for_duplicate_artifact_names() -> None:
    comparison = compare_summaries(
        RunSummary(
            run_uri="file:///runs/a",
            artifacts=[
                ArtifactSummary(
                    run_uri="file:///runs/a",
                    artifact_id="metrics/first",
                    logical_name="metrics",
                    checksum="sha256:a",
                ),
                ArtifactSummary(
                    run_uri="file:///runs/a",
                    artifact_id="metrics/second",
                    logical_name="metrics",
                    checksum="sha256:b",
                ),
            ],
        ),
        RunSummary(
            run_uri="file:///runs/b",
            artifacts=[
                ArtifactSummary(
                    run_uri="file:///runs/b",
                    artifact_id="metrics/first",
                    logical_name="metrics",
                    checksum="sha256:a",
                ),
                ArtifactSummary(
                    run_uri="file:///runs/b",
                    artifact_id="metrics/second",
                    logical_name="metrics",
                    checksum="sha256:c",
                ),
            ],
        ),
    )

    entries = {entry.key: entry for section in comparison for entry in section.entries}
    assert entries["artifacts.metrics.checksum"].status == ComparisonStatus.SAME
    assert entries["artifacts.metrics/second.checksum"].status == (
        ComparisonStatus.DIFFERENT
    )


def test_compare_summaries_compares_submitted_operation_metadata() -> None:
    comparison = compare_summaries(
        RunSummary(
            run_uri="file:///runs/a",
            submitted_operations=[
                SubmittedOperationSummary(
                    submission_id="sub-1",
                    backend="slurm",
                    mode="batch",
                    state="COMPLETED",
                    created_at="2020-01-01T00:00:00Z",
                    updated_at="2020-01-01T00:00:01Z",
                    summary_counts={"completed": 1},
                )
            ],
        ),
        RunSummary(
            run_uri="file:///runs/b",
            submitted_operations=[
                SubmittedOperationSummary(
                    submission_id="sub-1",
                    backend="slurm",
                    mode="batch",
                    state="FAILED",
                    created_at="2020-01-01T00:00:00Z",
                    updated_at="2020-01-01T00:00:02Z",
                    summary_counts={"failed": 1},
                )
            ],
        ),
    )

    entries = {entry.key: entry for section in comparison for entry in section.entries}
    assert entries["execution.submitted.sub-1.backend"].status == ComparisonStatus.SAME
    assert (
        entries["execution.submitted.sub-1.state"].status
        == ComparisonStatus.DIFFERENT
    )
    assert (
        entries["execution.submitted.sub-1.summary_counts"].status
        == ComparisonStatus.DIFFERENT
    )
