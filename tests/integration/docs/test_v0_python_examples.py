"""Executable docs examples from README and examples/."""

import os
import subprocess
import sys
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


@pytest.mark.parametrize(
    "script",
    [
        Path("examples/local_pipeline/run_pipeline.py"),
        Path("examples/config_recipes/compose_config.py"),
        Path("examples/target_instantiation/instantiate_targets.py"),
    ],
)
def test_v0_example_scripts_execute(script: Path, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["LOOM_EXAMPLE_RUN_ROOT"] = str(tmp_path / "runs")

    result = subprocess.run(
        [sys.executable, str(repo_root / script)],
        cwd=repo_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip()
