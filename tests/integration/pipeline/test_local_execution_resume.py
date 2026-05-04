"""Integration tests for same-run-directory resume."""

from pathlib import Path

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.planning import PlanAction
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalRunStore
from tests.support.pipeline_execution_configs import local_execution_config


pytestmark = pytest.mark.integration


def test_same_run_rerun_reuses_unchanged_stages(tmp_path: Path) -> None:
    counter_path = tmp_path / "counter.txt"
    run_store = LocalRunStore(tmp_path / "runs")
    runner = PipelineRunner(run_store=run_store)

    first = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path), run_id="run1"
        )
    )
    second = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path),
            run_id="run1",
            open_existing=True,
        )
    )

    assert first.status == RunStatus.SUCCEEDED
    assert second.status == RunStatus.SUCCEEDED
    assert second.stage_results["build"].action == PlanAction.REUSE
    assert second.stage_results["report"].action == PlanAction.REUSE
    assert counter_path.read_text(encoding="utf-8") == "1"
    status = run_store.read_stage_status("run1", "build")
    assert status is not None
    assert status.status == StageStatus.SUCCEEDED


def test_changed_config_reruns_changed_stage_and_downstream(tmp_path: Path) -> None:
    counter_path = tmp_path / "counter.txt"
    run_store = LocalRunStore(tmp_path / "runs")
    runner = PipelineRunner(run_store=run_store)

    runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path, value=1),
            run_id="run1",
        )
    )
    second = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path, value=2),
            run_id="run1",
            open_existing=True,
        )
    )

    assert second.stage_results["build"].action == PlanAction.RUN
    assert second.stage_results["report"].action == PlanAction.RUN
    assert counter_path.read_text(encoding="utf-8") == "2"
