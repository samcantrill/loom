"""Integration tests for execution plan persistence."""

from pathlib import Path

from loom.pipeline import PipelineSpec
from loom.pipeline.planning import ExecutionPlan, explain_plan, plan_pipeline
from loom.pipeline.planning.explanations import (
    PLAN_EXPLANATION_KIND,
    PLAN_EXPLANATION_SCHEMA_VERSION,
)
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def test_plan_pipeline_persists_only_plan_document(tmp_path: Path) -> None:
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": "project.Build"},
                    "outputs": {"data": {"artifact_type": "json"}},
                }
            ]
        },
    )
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    run_store.create_run(run_uri)
    artifact_store = LocalArtifactStore(run_store.local_artifact_root(run_uri))

    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=artifact_store,
        persist=True,
    )
    persisted = run_store.read_plan(run_uri)

    assert persisted == plan.to_dict()
    assert ExecutionPlan.from_dict(persisted).to_dict() == plan.to_dict()
    assert (run_store.local_run_dir(run_uri) / "plan.json").exists()
    assert run_store.read_stage_status(run_uri, "build") is None


def test_plan_pipeline_explanation_is_derived_not_persisted(tmp_path: Path) -> None:
    spec = PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": "project.Build"},
                    "outputs": {"data": {"artifact_type": "json"}},
                }
            ]
        },
    )
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run2")
    run_store.create_run(run_uri)
    artifact_store = LocalArtifactStore(run_store.local_artifact_root(run_uri))

    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=artifact_store,
        persist=True,
    )
    persisted = run_store.read_plan(run_uri)
    assert persisted is not None
    assert persisted["kind"] != PLAN_EXPLANATION_KIND
    assert "stage_explanations" not in persisted

    explanation = explain_plan(plan)
    explanation_dict = explanation.to_dict()
    assert explanation.kind == PLAN_EXPLANATION_KIND
    assert explanation.schema_version == PLAN_EXPLANATION_SCHEMA_VERSION
    assert explanation_dict["stages"]
