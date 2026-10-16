"""Unit tests for topological planning."""

import pytest

from loom.pipeline import PipelineSpec, StageStatus, StageStatusRecord
from loom.pipeline.planning import (
    PlanAction,
    PlanReasonCode,
    PlanSelectors,
    PlanningValidationError,
    PlanPersistenceError,
    ResumeOptions,
    build_stage_fingerprint,
    plan_pipeline,
)
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def _spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": "project.Build"},
                    "outputs": {
                        "data": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                },
                {
                    "name": "report",
                    "factory": {"_target_": "project.Report"},
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
                    "factory": {"_target_": "project.Prepare"},
                    "outputs": {
                        "ready": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                },
                {
                    "name": "publish",
                    "factory": {"_target_": "project.Publish"},
                    "depends_on": ["prepare"],
                    "outputs": {
                        "text": {"artifact_type": "text", "codec_key": "text.v1"}
                    },
                },
            ],
        },
    )


def _run_uri(tmp_path) -> str:
    return path_to_run_uri(tmp_path / "runs" / "run1")


def _stores(tmp_path):
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)
    return (
        run_store,
        LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        run_uri,
    )


def _succeeded(run_uri: str, stage_name: str) -> StageStatusRecord:
    return StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.SUCCEEDED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
    )


def _seed_reusable_build(run_store, artifact_store, run_uri: str) -> None:
    spec = _spec()
    build = spec.get_stage("build")
    output = artifact_store.save(
        {"x": 1},
        stage_name="build",
        name="data",
        artifact_type="json",
        codec_key="json.v1",
    )
    run_store.write_stage_status(run_uri, "build", _succeeded(run_uri, "build"))
    run_store.write_stage_inputs(run_uri, "build", {}, attempt=1)
    run_store.write_stage_outputs(run_uri, "build", {"data": output}, attempt=1)
    run_store.write_stage_fingerprint(
        run_uri,
        "build",
        build_stage_fingerprint(build, bound_inputs={}).to_dict(),
        attempt=1,
    )
    run_store.write_artifact_index(run_uri, {"build.data": output})


def test_fresh_plan_runs_first_stage_and_pends_downstream_inputs(tmp_path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    plan = plan_pipeline(
        _spec(),
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
        artifact_store=artifact_store,
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
    run_store, artifact_store, run_uri = _stores(tmp_path)
    plan = plan_pipeline(
        _spec(),
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
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
    run_store, artifact_store, run_uri = _stores(tmp_path)
    plan = plan_pipeline(
        _control_spec(),
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
        artifact_store=artifact_store,
        selectors=PlanSelectors(skip_stages=("prepare",)),
    )

    assert plan.stage_plans[0].action == PlanAction.SKIP
    assert plan.stage_plans[1].action == PlanAction.BLOCKED
    assert plan.stage_plans[1].invalidated_by[0].code == PlanReasonCode.UPSTREAM_SKIPPED


def test_from_stage_forces_selected_reusable_stage_and_invalidates_downstream(
    tmp_path,
) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    _seed_reusable_build(run_store, artifact_store, run_uri)

    plan = plan_pipeline(
        _spec(),
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
        artifact_store=artifact_store,
        selectors=PlanSelectors(from_stage="build"),
    )

    build, report = plan.stage_plans
    assert build.action == PlanAction.RUN
    assert build.base_action == PlanAction.REUSE
    assert build.reusable_outputs == {}
    assert build.selected_by == (PlanReasonCode.FROM_STAGE_SELECTED,)
    assert PlanReasonCode.FROM_STAGE_SELECTED in {
        reason.code for reason in build.reasons
    }
    assert report.action == PlanAction.RUN
    assert report.pending_inputs[0].reason.code == PlanReasonCode.UPSTREAM_WILL_RUN


def test_only_stage_runs_with_reusable_provider(tmp_path) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    _seed_reusable_build(run_store, artifact_store, run_uri)

    plan = plan_pipeline(
        _spec(),
        run_uri=run_uri,
        stage_state=run_store,
        artifact_index=run_store,
        plans=run_store,
        artifact_store=artifact_store,
        selectors=PlanSelectors(only_stages=("report",)),
    )

    build, report = plan.stage_plans
    assert build.action == PlanAction.REUSE
    assert report.action == PlanAction.RUN
    assert report.pending_inputs == ()


def test_disabled_resume_plans_without_state_or_artifact_stores(tmp_path) -> None:
    run_root = tmp_path / "uncreated-run"
    plan = plan_pipeline(
        _spec(), run_uri=run_root.as_uri(), resume=ResumeOptions(enabled=False)
    )

    assert [stage.action for stage in plan.stage_plans] == [
        PlanAction.RUN,
        PlanAction.RUN,
    ]
    check = plan.stage_plans[0].resume_check
    assert check is not None
    assert check.reasons[0].code == PlanReasonCode.RESUME_DISABLED
    assert not run_root.exists()


def test_enabled_resume_requires_its_state_owners() -> None:
    with pytest.raises(PlanningValidationError, match="resume requires"):
        plan_pipeline(_spec(), run_uri="file:///uncreated-run")


def test_persistence_requires_a_plan_owner() -> None:
    with pytest.raises(PlanPersistenceError, match="persistence requires plans"):
        plan_pipeline(
            _spec(),
            run_uri="file:///uncreated-run",
            resume=ResumeOptions(enabled=False),
            persist=True,
        )


def test_planning_uses_distinct_state_index_and_plan_owners(
    tmp_path, monkeypatch
) -> None:
    state, artifacts, run_uri = _stores(tmp_path)
    _seed_reusable_build(state, artifacts, run_uri)
    retained_index = state.read_artifact_index(run_uri)
    expected_run_uri = run_uri
    calls = []

    class IndexOwner:
        def read_artifact_index(self, run_uri):
            assert run_uri == expected_run_uri
            calls.append("index.read")
            return retained_index

        def write_artifact_index(self, run_uri, index):
            pytest.fail("planning must not rewrite the artifact index")

    class PlanOwner:
        document = None

        def write_plan(self, run_uri, plan):
            assert run_uri == expected_run_uri
            calls.append("plan.write")
            self.document = dict(plan)

        def read_plan(self, run_uri):
            assert run_uri == expected_run_uri
            calls.append("plan.read")
            return self.document

    def wrong_owner(*args, **kwargs):
        pytest.fail("stage state must not supply the artifact index or plan storage")

    monkeypatch.setattr(state, "read_artifact_index", wrong_owner)
    monkeypatch.setattr(state, "write_plan", wrong_owner)
    monkeypatch.setattr(state, "read_plan", wrong_owner)
    plans = PlanOwner()
    plan = plan_pipeline(
        _spec(),
        run_uri=run_uri,
        stage_state=state,
        artifact_index=IndexOwner(),
        artifact_store=artifacts,
        plans=plans,
        persist=True,
    )

    assert plan.stage_plans[0].action is PlanAction.REUSE
    assert plan.stage_plans[0].reusable_outputs["data"] == retained_index["build.data"]
    assert plans.document == plan.to_dict()
    assert calls == ["index.read", "plan.write", "plan.read"]
