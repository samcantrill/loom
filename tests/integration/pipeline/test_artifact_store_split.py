"""Integration smoke tests for artifact/materialization-only wrappers."""

from pathlib import Path

import pytest

from loom.pipeline.stores import LocalRunArtifactStore, LocalRunStore, path_to_run_uri

pytestmark = pytest.mark.integration


def test_local_artifact_wrappers_share_existing_run_layout(tmp_path: Path) -> None:
    local_store = LocalRunStore(root=tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    local_store.create_run(run_uri, metadata={"owner": "integration"})

    run_artifacts = LocalRunArtifactStore(local_store=local_store)
    stage_artifacts = run_artifacts.stage_artifacts(run_uri, "build")

    run_artifacts.write_config_snapshot(run_uri, "resolved", "pipeline: {}\n")
    stage_artifacts.write_stage_log("stderr", "diagnostic")

    assert local_store.read_config_snapshot(run_uri, "resolved") == "pipeline: {}\n"
    assert local_store.read_stage_log(run_uri, "build", "stderr") == "diagnostic"
    assert local_store.read_run_user_metadata(run_uri) == {"owner": "integration"}
    assert not hasattr(run_artifacts, "read_run_status")
    assert not hasattr(stage_artifacts, "read_stage_status")
