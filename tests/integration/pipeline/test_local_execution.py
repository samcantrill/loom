"""Integration tests for the local pipeline runner."""

from pathlib import Path

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.planning import PlanAction, PlanSelectors
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalRunStore
from tests.support.pipeline_execution_configs import local_execution_config


pytestmark = pytest.mark.integration


def test_local_runner_executes_pipeline_and_writes_state(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=local_execution_config(), run_id="run1")
    )

    assert result.status == RunStatus.SUCCEEDED
    assert result.stage_results["build"].status == StageStatus.SUCCEEDED
    assert result.stage_results["report"].status == StageStatus.SUCCEEDED
    assert (tmp_path / "runs" / "run1" / "plan.json").is_file()
    assert (tmp_path / "runs" / "run1" / "status.json").is_file()
    assert (tmp_path / "runs" / "run1" / "stages" / "build" / "inputs.json").is_file()
    assert (tmp_path / "runs" / "run1" / "stages" / "build" / "outputs.json").is_file()
    assert (
        tmp_path / "runs" / "run1" / "stages" / "report" / "fingerprint.json"
    ).is_file()
    assert set(run_store.read_artifact_index("run1")) == {"build.data", "report.text"}


def test_local_runner_applies_selector_skip(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=local_execution_config(),
            run_id="run1",
            selectors=PlanSelectors(skip_stages=("report",)),
        )
    )

    assert result.status == RunStatus.SUCCEEDED
    assert result.stage_results["report"].action == PlanAction.SKIP
    status = run_store.read_stage_status("run1", "report")
    assert status is not None
    assert status.status == StageStatus.SKIPPED
