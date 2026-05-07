"""Unit tests for durable direct stage-worker execution."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineSpec
from loom.pipeline.execution import (
    StageExecutionRequest,
    StageExecutionResult,
    ExecutionFailure,
    StageWorkerRunRequest,
    StageWorkerStateError,
    prepare_stage_attempt,
    run_stage_worker,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import StageStatus, StageStatusRecord
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.serialization import json_dumps_pretty


pytestmark = pytest.mark.unit


class FakeExecutor:
    name = "fake"

    def __init__(self) -> None:
        self.request: StageExecutionRequest | None = None

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult:
        self.request = request
        return StageExecutionResult(
            stage_name=request.stage.name,
            status=StageStatus.SUCCEEDED,
            outputs={
                "data": ArtifactRef(
                    artifact_id="build/data",
                    uri="file:///tmp/build-data.json",
                    artifact_type="json",
                    codec_key="json.v1",
                    producer_stage="build",
                )
            },
            failure=None,
            started_at="2020-01-01T00:00:01Z",
            finished_at="2020-01-01T00:00:02Z",
            executor_name=self.name,
            attempt=request.attempt,
            stdout_path=str(request.stdout_path),
            stderr_path=str(request.stderr_path),
            executor_metadata={"fake": True},
        )


def _spec(*, target: str = "tests.support.pipeline_execution_stages.JsonProducerStage") -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": target},
                    "config": {"value": 7},
                    "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
                }
            ],
        }
    )


def _prepared_run(
    tmp_path: Path,
    *,
    persist_plan: bool = True,
    target: str = "tests.support.pipeline_execution_stages.JsonProducerStage",
) -> tuple[LocalRunStore, str]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    spec = _spec(target=target)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=persist_plan,
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty(
            {
                "pipeline": {
                    "name": "snapshot-demo",
                    "stages": [{"name": "build"}],
                }
            }
        ),
    )
    prepare_stage_attempt(
        run_store=store,
        run_uri=run_uri,
        stage=spec.get_stage("build"),
        stage_plan=plan.ordered_stage_plans[0],
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            executor="local",
        ),
        clock=lambda: "2020-01-01T00:00:00Z",
    )
    return store, run_uri


def test_run_stage_worker_infers_attempt_and_writes_only_worker_result(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_run(tmp_path)
    executor = FakeExecutor()

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
        executor=executor,
    )

    assert result.status == StageStatus.SUCCEEDED
    assert result.attempt == 1
    assert result.executor_name == "local"
    assert result.executor_metadata == {"fake": True}
    assert store.read_stage_worker_result(run_uri, "build", attempt=1) == result.to_dict()
    assert store.read_stage_outputs(run_uri, "build") is None
    assert store.read_stage_failure(run_uri, "build") is None
    assert store.read_stage_provenance(run_uri, "build") is None
    assert store.read_artifact_index(run_uri) == {}
    status = store.read_stage_status(run_uri, "build")
    assert status is not None
    assert status.status == StageStatus.PENDING
    assert executor.request is not None
    assert executor.request.stage.factory.target_path.endswith("JsonProducerStage")
    assert executor.request.context.resolved_config["pipeline"] == {
        "name": "snapshot-demo",
        "stages": [{"name": "build"}],
    }


def test_run_stage_worker_allows_exact_attempt(tmp_path: Path) -> None:
    store, run_uri = _prepared_run(tmp_path)

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build", attempt=1),
        executor=FakeExecutor(),
    )

    assert result.attempt == 1


def test_run_stage_worker_rejects_completed_status_for_inference(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepared_run(tmp_path)
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED,
            attempt=1,
            updated_at="2020-01-01T00:00:03Z",
            started_at="2020-01-01T00:00:01Z",
            finished_at="2020-01-01T00:00:02Z",
        ),
    )

    with pytest.raises(StageWorkerStateError, match="not PENDING or RUNNING"):
        run_stage_worker(
            run_store=store,
            request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
            executor=FakeExecutor(),
        )


def test_run_stage_worker_requires_persisted_plan(tmp_path: Path) -> None:
    store, run_uri = _prepared_run(tmp_path, persist_plan=False)

    with pytest.raises(StageWorkerStateError, match="no persisted execution plan"):
        run_stage_worker(
            run_store=store,
            request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
            executor=FakeExecutor(),
        )


def test_run_stage_worker_records_target_construction_failure(tmp_path: Path) -> None:
    store, run_uri = _prepared_run(tmp_path, target="tests.support.pipeline_execution_stages.MissingStage")

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
        clock=lambda: "2020-01-01T00:00:04Z",
    )

    assert result.status == StageStatus.FAILED
    failure = cast(ExecutionFailure, result.failure)
    assert failure.failure_type == "target_construction"
    assert result.exit_code == 1
    assert store.read_stage_worker_result(run_uri, "build", attempt=1) == result.to_dict()
