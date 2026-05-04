"""Integration tests for execution plan persistence."""

from pathlib import Path

from loom.pipeline import PipelineSpec
from loom.pipeline.planning import ExecutionPlan, plan_pipeline
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore


def test_plan_pipeline_persists_only_plan_document(tmp_path: Path) -> None:
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "_target_": "project.Build",
                    "outputs": {"data": {"artifact_type": "json"}},
                }
            ]
        },
    )
    run_store = LocalRunStore(tmp_path / "runs")
    run_store.create_run("run1")
    artifact_store = LocalArtifactStore(run_store.get_artifact_root("run1"))

    plan = plan_pipeline(
        spec,
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        persist=True,
    )
    persisted = run_store.read_plan("run1")

    assert persisted == plan.to_dict()
    assert ExecutionPlan.from_dict(persisted).to_dict() == plan.to_dict()
    assert (run_store.get_run_dir("run1") / "plan.json").exists()
    assert run_store.read_stage_status("run1", "build") is None
