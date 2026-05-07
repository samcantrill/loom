"""Contract tests for the direct worker handoff boundary."""

from __future__ import annotations

from pathlib import Path

from loom.pipeline import PipelineSpec
from loom.pipeline.execution import (
    StageWorkerRunRequest,
    prepare_stage_attempt,
    run_stage_worker,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def test_direct_worker_writes_only_worker_result_handoff(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    spec = PipelineSpec.from_config(
        {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                    },
                    "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
                }
            ],
        }
    )
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    prepare_stage_attempt(
        run_store=store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(stage_id="build", executor="local"),
        clock=lambda: "2020-01-01T00:00:00Z",
    )

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
    )

    assert result.status == StageStatus.SUCCEEDED
    assert store.read_stage_worker_result(run_uri, "build", attempt=1) == result.to_dict()
    assert store.read_stage_outputs(run_uri, "build") is None
    assert store.read_stage_failure(run_uri, "build") is None
    assert store.read_stage_provenance(run_uri, "build") is None
    assert store.read_artifact_index(run_uri) == {}
    assert store.read_run_status(run_uri) is None
    status = store.read_stage_status(run_uri, "build")
    assert status is not None
    assert status.status == StageStatus.PENDING
    assert status.metadata["prepared"] is True
