"""Integration coverage for SLURM model path helpers and local run stores."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline.executors.slurm import (
    resolve_slurm_manifest_path,
    slurm_job_script_relative_path,
    slurm_manifest_relative_path,
)
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.stores.errors import UnsafeStorePathError


def test_slurm_path_helper_uses_local_run_store_generated_artifact_contract(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    run_uri = path_to_run_uri(root / "run-1")
    store.create_run(run_uri)

    manifest = resolve_slurm_manifest_path(store, run_uri, "planning-1")
    script_relative = slurm_job_script_relative_path("planning-1", "stage:build")
    script = store.local_generated_artifact_path(run_uri, script_relative)

    assert manifest.relative_path == "slurm/submissions/planning-1/manifest.json"
    assert manifest.local_path == store.local_run_dir(run_uri) / manifest.relative_path
    assert script == (
        store.local_run_dir(run_uri)
        / "slurm"
        / "submissions"
        / "planning-1"
        / "scripts"
        / "stage-build.sh"
    )
    assert manifest.local_path.is_relative_to(store.local_run_dir(run_uri))
    assert script.is_relative_to(store.local_run_dir(run_uri))


@pytest.mark.parametrize("planning_id", ["bad id", "../escape", "bad/id"])
def test_slurm_planning_id_rejects_unsafe_submission_components(
    planning_id: str,
) -> None:
    with pytest.raises(Exception):
        slurm_manifest_relative_path(planning_id)


def test_store_rejects_unsafe_relative_path_even_when_called_through_helper(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = LocalRunStore(root=root)
    run_uri = path_to_run_uri(root / "run-1")
    store.create_run(run_uri)

    with pytest.raises(UnsafeStorePathError):
        store.local_generated_artifact_path(
            run_uri,
            "slurm/submissions/p1/../manifest.json",
        )
