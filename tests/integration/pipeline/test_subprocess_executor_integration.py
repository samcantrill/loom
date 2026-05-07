"""Integration tests for serial subprocess execution."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from loom.pipeline import PipelineSpec
from loom.pipeline.execution import ExecutionFailure, PipelineRunner, RunRequest
from loom.pipeline.executors import SubprocessExecutor
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.provenance.models import ProvenanceCaptureOptions


def _spec(
    *,
    target: str = "tests.support.pipeline_execution_stages.JsonProducerStage",
) -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {"_target_": target},
                    "config": {"value": 123},
                    "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
                }
            ],
        }
    )


def _request(target: str) -> RunRequest:
    return RunRequest(
        pipeline=_spec(target=target),
        options={"executor": "subprocess"},
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )


def test_subprocess_executor_success_parent_finalizes_stage(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path / "runs")

    result = PipelineRunner(
        run_store=store,
        executor=SubprocessExecutor(run_store=store),
    ).run(
        _request("tests.support.pipeline_execution_stages.JsonProducerStage")
    )

    assert result.status == RunStatus.SUCCEEDED
    assert result.stage_results["build"].status == StageStatus.SUCCEEDED
    outputs = store.read_stage_outputs(result.run_uri, "build")
    assert outputs is not None
    artifact_store = LocalArtifactStore(store.local_artifact_root(result.run_uri))
    assert artifact_store.load(outputs["data"]) == {"value": 123}
    assert store.read_stage_worker_result(result.run_uri, "build", attempt=1) is not None
    provenance = store.read_stage_provenance(result.run_uri, "build")
    assert provenance is not None
    executor_metadata = cast(dict[str, object], provenance["executor_metadata"])
    assert executor_metadata["executor"] == "subprocess"
    assert executor_metadata["returncode"] == 0


def test_subprocess_executor_failure_parent_finalizes_failed_run(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(tmp_path / "runs")

    result = PipelineRunner(
        run_store=store,
        executor=SubprocessExecutor(run_store=store),
    ).run(
        _request("tests.support.pipeline_execution_stages.FailingStage")
    )

    assert result.status == RunStatus.FAILED
    assert result.stage_results["build"].status == StageStatus.FAILED
    worker_result = store.read_stage_worker_result(result.run_uri, "build", attempt=1)
    assert worker_result is not None
    persisted_failure = store.read_stage_failure(result.run_uri, "build")
    assert persisted_failure is not None
    failure = cast(ExecutionFailure, result.failure)
    assert failure.executor == "subprocess"
    assert failure.failure_type == "stage_exception"
    assert "stage failed intentionally" in failure.message
    assert failure.exit_code == 1
    status = store.read_run_status(result.run_uri)
    assert status is not None
    assert status.status == RunStatus.FAILED
