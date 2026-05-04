"""End-to-end local pipeline run through public Python APIs."""

from pathlib import Path

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.planning import PlanAction
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import LocalRunStore
from tests.support.pipeline_execution_configs import local_execution_config


pytestmark = pytest.mark.e2e


def test_local_pipeline_run_and_resume_from_config(tmp_path: Path) -> None:
    counter_path = tmp_path / "counter.txt"
    run_store = LocalRunStore(tmp_path / "runs")
    runner = PipelineRunner(run_store=run_store)

    result = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path), run_id="run1"
        )
    )
    resumed = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path),
            run_id="run1",
            open_existing=True,
        )
    )

    assert result.status == RunStatus.SUCCEEDED
    assert resumed.status == RunStatus.SUCCEEDED
    assert resumed.stage_results["build"].action == PlanAction.REUSE
    assert resumed.stage_results["report"].action == PlanAction.REUSE
    assert counter_path.read_text(encoding="utf-8") == "1"
    run_dir = tmp_path / "runs" / "run1"
    for relative in [
        "config/resolved.yaml",
        "plan.json",
        "status.json",
        "artifacts.json",
        "stages/build/inputs.json",
        "stages/build/outputs.json",
        "stages/build/fingerprint.json",
        "stages/build/provenance.json",
        "stages/report/inputs.json",
        "stages/report/outputs.json",
        "stages/report/fingerprint.json",
        "stages/report/provenance.json",
    ]:
        assert (run_dir / relative).is_file(), relative
