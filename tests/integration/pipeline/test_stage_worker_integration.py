"""Integration tests for direct stage-worker execution."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, cast

from loom.pipeline import PipelineSpec
from loom.pipeline.execution import (
    ExecutionFailure,
    StageWorkerRunRequest,
    create_authority_backed_serial_run_store,
    prepare_stage_attempt,
    run_stage_worker,
)
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, path_to_run_uri


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
                    "config": {"value": 42},
                    "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
                }
            ],
        }
    )


def _prepare(tmp_path: Path, *, target: str) -> tuple[Any, str]:
    store = create_authority_backed_serial_run_store(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    spec = _spec(target=target)
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
    )
    return store, run_uri


def test_direct_worker_success_writes_result_handoff_and_artifact(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepare(
        tmp_path,
        target="tests.support.pipeline_execution_stages.JsonProducerStage",
    )

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
    )

    artifact_store = LocalArtifactStore(store.local_artifact_root(run_uri))
    assert result.status == StageStatus.SUCCEEDED
    assert artifact_store.load(result.outputs["data"]) == {"value": 42}
    assert store.read_stage_worker_result(run_uri, "build", attempt=1) == result.to_dict()
    assert store.read_stage_outputs(run_uri, "build") is None


def test_direct_worker_failure_writes_failed_result_handoff(tmp_path: Path) -> None:
    store, run_uri = _prepare(
        tmp_path,
        target="tests.support.pipeline_execution_stages.FailingStage",
    )

    result = run_stage_worker(
        run_store=store,
        request=StageWorkerRunRequest(run_uri=run_uri, stage_name="build"),
    )

    assert result.status == StageStatus.FAILED
    assert result.exit_code == 1
    failure = cast(ExecutionFailure, result.failure)
    assert failure.failure_type == "stage_exception"
    assert "stage failed intentionally" in failure.message
    assert store.read_stage_worker_result(run_uri, "build", attempt=1) == result.to_dict()
    assert store.read_stage_failure(run_uri, "build") is None


def test_direct_worker_cli_success_smoke(tmp_path: Path) -> None:
    from loom.cli.main import main

    _store, run_uri = _prepare(
        tmp_path,
        target="tests.support.pipeline_execution_stages.JsonProducerStage",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "stage",
                "run",
                "--run-uri",
                run_uri,
                "--stage",
                "build",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.stage.run.v1"
    assert payload["ok"] is True
    assert payload["result"]["stage_name"] == "build"
    assert stderr.getvalue() == ""
