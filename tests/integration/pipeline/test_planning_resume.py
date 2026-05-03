"""Integration tests for planning against local stores."""

from pathlib import Path

import pytest

from loom.pipeline import PipelineSpec, StageStatus, StageStatusRecord
from loom.pipeline.planning import (
    PlanAction,
    PlanReasonCode,
    PlanSelectors,
    ResumeStateError,
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


def _stores(tmp_path: Path) -> tuple[LocalRunStore, LocalArtifactStore]:
    run_store = LocalRunStore(tmp_path / "runs")
    run_store.create_run("run1")
    artifact_store = LocalArtifactStore(run_store.get_artifact_root("run1"))
    return run_store, artifact_store


def _succeeded(run_id: str, stage_name: str) -> StageStatusRecord:
    return StageStatusRecord(
        run_id=run_id,
        stage_name=stage_name,
        status=StageStatus.SUCCEEDED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
    )


def _seed_reusable_build(
    run_store: LocalRunStore, artifact_store: LocalArtifactStore
) -> None:
    spec = _spec()
    build = spec.get_stage("build")
    fingerprint = build_stage_fingerprint(build, bound_inputs={})
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
    run_store.write_stage_fingerprint("run1", "build", fingerprint.to_dict(), attempt=1)
    run_store.write_artifact_index("run1", {"build.data": output})


def test_planner_reuses_valid_upstream_and_binds_downstream_input(
    tmp_path: Path,
) -> None:
    run_store, artifact_store = _stores(tmp_path)
    _seed_reusable_build(run_store, artifact_store)

    plan = plan_pipeline(
        _spec(), run_id="run1", run_store=run_store, artifact_store=artifact_store
    )

    build, report = plan.stage_plans
    assert build.action == PlanAction.REUSE
    assert report.action == PlanAction.RUN
    assert report.bound_inputs["data"].artifact_ref == build.reusable_outputs["data"]
    assert report.fingerprint is not None


def test_only_stage_blocks_when_upstream_provider_is_unavailable(
    tmp_path: Path,
) -> None:
    run_store, artifact_store = _stores(tmp_path)

    plan = plan_pipeline(
        _spec(),
        run_id="run1",
        run_store=run_store,
        artifact_store=artifact_store,
        selectors=PlanSelectors(only_stages=("report",)),
    )

    assert plan.stage_plans[0].action == PlanAction.BLOCKED
    assert plan.stage_plans[1].action == PlanAction.BLOCKED
    assert (
        plan.stage_plans[1].pending_inputs[0].reason.code
        == PlanReasonCode.UNAVAILABLE_UPSTREAM_INPUT
    )


def test_corrupt_store_json_raises_resume_state_error(tmp_path: Path) -> None:
    run_store, artifact_store = _stores(tmp_path)
    status_path = run_store.get_stage_dir("run1", "build") / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ResumeStateError):
        plan_pipeline(
            _spec(), run_id="run1", run_store=run_store, artifact_store=artifact_store
        )
