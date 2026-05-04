"""Unit tests for topological planning."""

from loom.pipeline import PipelineSpec, StageStatus, StageStatusRecord
from loom.pipeline.planning import (
    PlanAction,
    PlanReasonCode,
    PlanSelectors,
    build_stage_fingerprint,
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
    return run_store, LocalArtifactStore(run_store.local_artifact_root("run1"))


def _succeeded(run_id: str, stage_name: str) -> StageStatusRecord:
    return StageStatusRecord(
        run_id=run_id,
        stage_name=stage_name,
        status=StageStatus.SUCCEEDED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
    )


def _seed_reusable_build(run_store, artifact_store) -> None:
    spec = _spec()
    build = spec.get_stage("build")
    output = artifact_store.save(
        {"x": 1},
        run_id="run1",
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status("run1", "build", _succeeded("run1", "build"))
    run_store.write_stage_inputs("run1", "build", {}, attempt=1)
    run_store.write_stage_outputs("run1", "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(
        "run1",
        "build",
        build_stage_fingerprint(build, bound_inputs={}).to_dict(),
        attempt=1,
    )
    run_store.write_artifact_index("run1", {"build.data": output})


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


def test_from_stage_forces_selected_reusable_stage_and_invalidates_downstream(
    tmp_path,
) -> None:
    run_store, artifact_store = _stores(tmp_path)
    _seed_reusable_build(run_store, artifact_store)

    plan = plan_pipeline(
        _spec(),
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        selectors=PlanSelectors(from_stage="build"),
    )

    build, report = plan.stage_plans
    assert build.action == PlanAction.RUN
    assert build.base_action == PlanAction.REUSE
    assert build.reusable_outputs == {}
    assert build.selected_by == (PlanReasonCode.FROM_STAGE_SELECTED,)
    assert PlanReasonCode.FROM_STAGE_SELECTED in {reason.code for reason in build.reasons}
    assert report.action == PlanAction.RUN
    assert report.pending_inputs[0].reason.code == PlanReasonCode.UPSTREAM_WILL_RUN
