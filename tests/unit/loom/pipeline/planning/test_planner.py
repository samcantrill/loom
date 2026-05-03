"""Unit tests for topological planning."""

from loom.pipeline import PipelineSpec
from loom.pipeline.planning import (
    PlanAction,
    PlanReasonCode,
    PlanSelectors,
    plan_pipeline,
)
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore


def _spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "_target_": "project.Build",
                    "outputs": {
                        "data": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                },
                {
                    "name": "report",
                    "_target_": "project.Report",
                    "inputs": {"data": "build.data"},
                    "outputs": {
                        "text": {"artifact_type": "text", "codec_key": "text.v1"}
                    },
                },
            ],
        },
    )


def _control_spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "control-demo",
            "stages": [
                {
                    "name": "prepare",
                    "_target_": "project.Prepare",
                    "outputs": {
                        "ready": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                },
                {
                    "name": "publish",
                    "_target_": "project.Publish",
                    "depends_on": ["prepare"],
                    "outputs": {
                        "text": {"artifact_type": "text", "codec_key": "text.v1"}
                    },
                },
            ],
        },
    )


def _stores(tmp_path):
    run_store = LocalRunStore(tmp_path / "runs")
    run_store.create_run("run1")
    return run_store, LocalArtifactStore(run_store.get_artifact_root("run1"))


def test_fresh_plan_runs_first_stage_and_pends_downstream_inputs(tmp_path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    plan = plan_pipeline(
        _spec(), run_id="run1", run_store=run_store, artifact_store=artifact_store
    )

    assert plan.stage_order == ("build", "report")
    assert [stage.action for stage in plan.stage_plans] == [
        PlanAction.RUN,
        PlanAction.RUN,
    ]
    report = plan.stage_plans[1]
    assert report.fingerprint_status.value == "PENDING_INPUTS"
    assert report.pending_inputs[0].reason.code == PlanReasonCode.UPSTREAM_WILL_RUN


def test_skip_selector_blocks_downstream_consumers(tmp_path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    plan = plan_pipeline(
        _spec(),
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        selectors=PlanSelectors(skip_stages=("build",)),
    )

    assert plan.stage_plans[0].action == PlanAction.SKIP
    assert [reason.code for reason in plan.stage_plans[0].reasons] == [
        PlanReasonCode.SKIPPED_BY_SELECTOR
    ]
    assert plan.stage_plans[1].action == PlanAction.BLOCKED
    assert (
        plan.stage_plans[1].pending_inputs[0].reason.code
        == PlanReasonCode.UPSTREAM_SKIPPED
    )


def test_skip_selector_blocks_control_dependency_consumers(tmp_path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    plan = plan_pipeline(
        _control_spec(),
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        selectors=PlanSelectors(skip_stages=("prepare",)),
    )

    assert plan.stage_plans[0].action == PlanAction.SKIP
    assert plan.stage_plans[1].action == PlanAction.BLOCKED
    assert plan.stage_plans[1].invalidated_by[0].code == PlanReasonCode.UPSTREAM_SKIPPED
