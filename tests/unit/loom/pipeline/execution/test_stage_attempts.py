"""Unit tests for durable stage-attempt preparation."""

from pathlib import Path
from typing import cast

import pytest

from loom.pipeline import PipelineSpec
from loom.pipeline.execution import prepare_stage_attempt
from loom.pipeline.execution.errors import PlanExecutionError
from loom.pipeline.planning import (
    PlanSelectors,
    StageFingerprintRecord,
    StagePlan,
    plan_pipeline,
)
from loom.pipeline.reliability import StageAttemptTransactionState
from loom.pipeline.runtime import ResolvedStageRuntimeOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri


def _spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                    },
                    "outputs": {"data": {"artifact_type": "json"}},
                }
            ]
        }
    )


def _planned_stage(
    tmp_path: Path,
) -> tuple[LocalRunStore, str, PipelineSpec, StagePlan]:
    store = LocalRunStore(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    store.create_run(run_uri)
    spec = _spec()
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(tmp_path / "runs" / "run1" / "artifacts"),
        persist=True,
    )
    return store, run_uri, spec, plan.ordered_stage_plans[0]


def test_prepare_stage_attempt_writes_durable_request_without_running_stage(
    tmp_path: Path,
) -> None:
    store, run_uri, spec, stage_plan = _planned_stage(tmp_path)
    stage = spec.get_stage("build")

    request = prepare_stage_attempt(
        run_store=store,
        run_uri=run_uri,
        stage=stage,
        stage_plan=stage_plan,
        resolved_runtime=ResolvedStageRuntimeOptions(
            stage_id="build",
            executor="local",
        ),
        executor_metadata={
            "command": ["python", "--token=secret"],
            "environment": {"TOKEN": "secret", "PATH": "/bin"},
        },
        metadata={"source": "unit-test"},
        clock=lambda: "2020-01-01T00:00:00Z",
    )

    assert request.run_uri == run_uri
    assert request.stage_name == "build"
    assert request.attempt == 1
    assert request.executor_metadata == {
        "command": ("python", "[redacted]"),
        "environment": {"key_count": 2, "keys": ("PATH", "TOKEN")},
    }
    assert (
        store.read_stage_worker_request(run_uri, "build", attempt=1)
        == request.to_dict()
    )
    assert store.read_stage_inputs(run_uri, "build") == {}
    fingerprint = cast(StageFingerprintRecord, request.fingerprint)
    assert store.read_stage_fingerprint(run_uri, "build") == fingerprint.to_dict()
    status = store.read_stage_status(run_uri, "build")
    assert status is not None
    assert status.status == StageStatus.PENDING
    assert status.attempt == 1
    assert status.metadata["prepared"] is True
    transactions = store.list_stage_attempt_transactions(run_uri, stage_name="build")
    assert [transaction.state for transaction in transactions] == [
        StageAttemptTransactionState.PREPARED
    ]
    assert transactions[0].status.stage_status is StageStatus.PENDING
    assert transactions[0].causal_parent_id is None
    assert store.local_stage_workspace_dir(run_uri, "build").is_dir()
    assert not store.local_stage_worker_result_path(run_uri, "build").exists()


def test_prepare_stage_attempt_rejects_non_run_stage_plan(tmp_path: Path) -> None:
    store, run_uri, spec, _stage_plan = _planned_stage(tmp_path)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(tmp_path / "runs" / "run1" / "artifacts"),
        selectors=PlanSelectors(skip_stages=("build",)),
    )

    with pytest.raises(PlanExecutionError, match="requires a RUN stage plan"):
        prepare_stage_attempt(
            run_store=store,
            run_uri=run_uri,
            stage=spec.get_stage("build"),
            stage_plan=plan.ordered_stage_plans[0],
        )
