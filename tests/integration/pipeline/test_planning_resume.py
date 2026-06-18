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


def _run_uri(tmp_path: Path, name: str = "run1") -> str:
    return path_to_run_uri(tmp_path / "runs" / name)


def _stores(tmp_path: Path) -> tuple[LocalRunStore, LocalArtifactStore, str]:
    run_store = LocalRunStore(tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    run_store.create_run(run_uri)
    artifact_store = LocalArtifactStore(run_store.local_artifact_root(run_uri))
    return run_store, artifact_store, run_uri


def _succeeded(run_uri: str, stage_name: str) -> StageStatusRecord:
    return StageStatusRecord(
        run_uri=run_uri,
        stage_name=stage_name,
        status=StageStatus.SUCCEEDED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
    )


def _seed_reusable_build(
    run_store: LocalRunStore, artifact_store: LocalArtifactStore, run_uri: str
) -> None:
    spec = _spec()
    build = spec.get_stage("build")
    fingerprint = build_stage_fingerprint(build, bound_inputs={})
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
        run_uri, "build", fingerprint.to_dict(), attempt=1
    )
    run_store.write_artifact_index(run_uri, {"build.data": output})


def test_planner_reuses_valid_upstream_and_binds_downstream_input(
    tmp_path: Path,
) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    _seed_reusable_build(run_store, artifact_store, run_uri)

    plan = plan_pipeline(
        _spec(), run_uri=run_uri, run_store=run_store, artifact_store=artifact_store
    )

    build, report = plan.stage_plans
    assert build.action == PlanAction.REUSE
    assert report.action == PlanAction.RUN
    assert report.bound_inputs["data"].artifact_ref == build.reusable_outputs["data"]
    assert report.fingerprint is not None


def test_from_stage_forces_reusable_selected_stage_and_reruns_downstream(
    tmp_path: Path,
) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)
    _seed_reusable_build(run_store, artifact_store, run_uri)

    plan = plan_pipeline(
        _spec(),
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=artifact_store,
        selectors=PlanSelectors(from_stage="build"),
    )

    build, report = plan.stage_plans
    assert build.action == PlanAction.RUN
    assert build.base_action == PlanAction.REUSE
    assert build.reusable_outputs == {}
    assert build.selected_by == (PlanReasonCode.FROM_STAGE_SELECTED,)
    assert {reason.code for reason in build.reasons} >= {
        PlanReasonCode.FROM_STAGE_SELECTED,
        PlanReasonCode.FINGERPRINT_MATCH,
    }
    assert report.action == PlanAction.RUN
    assert report.pending_inputs[0].reason.code == PlanReasonCode.UPSTREAM_WILL_RUN


def test_only_stage_blocks_when_upstream_provider_is_unavailable(
    tmp_path: Path,
) -> None:
    run_store, artifact_store, run_uri = _stores(tmp_path)

    plan = plan_pipeline(
        _spec(),
        run_uri=run_uri,
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
    run_store, artifact_store, run_uri = _stores(tmp_path)
    status_path = run_store.local_stage_dir(run_uri, "build") / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ResumeStateError):
        plan_pipeline(
            _spec(), run_uri=run_uri, run_store=run_store, artifact_store=artifact_store
        )
