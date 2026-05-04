"""Executable docs examples from README and phase-10 examples."""

from pathlib import Path

import pytest

from loom.config import compose_config
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.planning import PlanAction
from loom.pipeline.stores import LocalRunStore


pytestmark = pytest.mark.integration


def _config_path(base: Path) -> Path:
    config = base / "demo_pipeline.yaml"
    config.write_text(
        """
name: demo
pipeline:
  name: demo
  stages:
    - name: build
      _target_: tests.support.pipeline_execution_stages.JsonProducerStage
      config:
        value: 1
      outputs:
        data:
          artifact_type: json
          codec_key: json.v1
    - name: report
      _target_: tests.support.pipeline_execution_stages.TextConsumerStage
      inputs:
        data: build.data
      outputs:
        text:
          artifact_type: text
          codec_key: text.v1
"""
    )
    return config


def test_readme_python_api_example_runs_and_reuses_same_run(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    runner = PipelineRunner(run_store=run_store)
    config = compose_config(_config_path(tmp_path)).resolved
    first = runner.run(RunRequest(config=config, run_id="run-1"))
    second = runner.run(
        RunRequest(config=config, run_id="run-1", open_existing=True)
    )

    assert first.status.name == "SUCCEEDED"
    assert second.stage_results["build"].action == PlanAction.REUSE
    assert second.stage_results["report"].action == PlanAction.REUSE
