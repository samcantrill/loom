"""Integration tests for local execution failure persistence."""

from pathlib import Path
from typing import cast

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.planning import PlanAction
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalRunStore
from loom.serialization import PlainData


pytestmark = pytest.mark.integration


def _failure_config(target: str) -> dict[str, PlainData]:
    return cast(
        dict[str, PlainData],
        {
            "pipeline": {
                "name": "failure-demo",
                "stages": [
                    {
                        "name": "build",
                        "_target_": target,
                        "outputs": {
                            "data": {"artifact_type": "json", "codec_key": "json.v1"}
                        },
                    },
                    {
                        "name": "report",
                        "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage",
                        "inputs": {"data": "build.data"},
                        "outputs": {
                            "text": {"artifact_type": "text", "codec_key": "text.v1"}
                        },
                    },
                ],
            }
        },
    )


def test_stage_exception_persists_failure_before_failed_status(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.FailingStage"
            ),
            run_id="run1",
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.stage_results["build"].status == StageStatus.FAILED
    assert result.stage_results["report"].action == PlanAction.BLOCKED
    failure = run_store.read_stage_failure("run1", "build")
    status = run_store.read_stage_status("run1", "build")
    assert failure is not None
    assert status is not None
    assert failure["failure_type"] == "stage_exception"
    assert status.status == StageStatus.FAILED


def test_invalid_outputs_fail_with_inspectable_state(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.BadOutputStage"
            ),
            run_id="run1",
        )
    )

    assert result.status == RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_type == "output_validation"
    assert (tmp_path / "runs" / "run1" / "stages" / "build" / "failure.json").is_file()
