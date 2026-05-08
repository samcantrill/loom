"""Unit tests for SLURM generated-artifact path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline.executors.slurm import (
    SlurmPathError,
    resolve_slurm_generated_artifact_path,
    slurm_job_log_relative_path,
    slurm_job_script_relative_path,
    slurm_manifest_relative_path,
    slurm_plan_relative_path,
)


class RecordingPaths:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def local_generated_artifact_path(self, run_uri: str, relative_path: str) -> Path:
        self.calls.append((run_uri, relative_path))
        return Path("/runs/run-1") / relative_path


def test_slurm_relative_paths_are_under_submission_directory() -> None:
    assert slurm_manifest_relative_path("p1") == "slurm/submissions/p1/manifest.json"
    assert slurm_plan_relative_path("p1") == "slurm/submissions/p1/plan.json"
    assert (
        slurm_job_script_relative_path("p1", "stage:build")
        == "slurm/submissions/p1/scripts/stage-build.sh"
    )
    assert (
        slurm_job_log_relative_path("p1", "pipeline", "stdout")
        == "slurm/submissions/p1/logs/pipeline.stdout.log"
    )


def test_resolve_generated_artifact_delegates_to_store_paths() -> None:
    paths = RecordingPaths()

    resolved = resolve_slurm_generated_artifact_path(
        paths,  # type: ignore[arg-type]
        "file:///runs/run-1",
        "slurm/submissions/p1/manifest.json",
    )

    assert paths.calls == [("file:///runs/run-1", "slurm/submissions/p1/manifest.json")]
    assert resolved.relative_path == "slurm/submissions/p1/manifest.json"
    assert resolved.local_path == Path("/runs/run-1/slurm/submissions/p1/manifest.json")


@pytest.mark.parametrize("planning_id", ["../x", "bad/id", "bad id", ""])
def test_planning_id_rejects_unsafe_components(planning_id: str) -> None:
    with pytest.raises(SlurmPathError):
        slurm_manifest_relative_path(planning_id)


def test_log_stream_rejects_unknown_streams() -> None:
    with pytest.raises(SlurmPathError, match="stdout, stderr"):
        slurm_job_log_relative_path("p1", "pipeline", "debug")
