"""Integration tests for the local pipeline runner."""

from collections.abc import Callable
from itertools import count
from pathlib import Path

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.planning import PlanAction, PlanSelectors
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from tests.support.pipeline_execution_configs import local_execution_config

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _sequence_clock() -> Callable[[], str]:
    ticks = count(1)

    def clock() -> str:
        return f"2020-01-01T00:00:{next(ticks):02d}Z"

    return clock


def test_local_runner_executes_pipeline_and_writes_state(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store, clock=_sequence_clock()).run(
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
    assert run_store.read_run_lock("run1") is None
    events = run_store.read_events("run1")
    assert [event.event_type for event in events] == [
        "run.created",
        "run.planned",
        "stage.planned",
        "stage.planned",
        "run.started",
        "stage.started",
        "stage.completed",
        "stage.started",
        "stage.completed",
        "run.completed",
    ]
    assert all(event.timestamp.startswith("2020-01-01T00:00:") for event in events)
    stage_events = [event for event in events if event.scope.stage_name == "build"]
    assert [event.event_type for event in stage_events] == [
        "stage.planned",
        "stage.started",
        "stage.completed",
    ]


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
    assert any(
        event.event_type == "stage.skipped" and event.scope.stage_name == "report"
        for event in run_store.read_events("run1")
    )


def test_local_runner_keeps_factory_init_separate_from_stage_config(
    tmp_path: Path,
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    config = {
        "pipeline": {
            "name": "factory-init-demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.ConfiguredProducerStage",
                        "init": {"constructor_value": 7},
                    },
                    "config": {"runtime_value": 11},
                    "outputs": {
                        "data": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                }
            ],
        }
    }

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=config, run_id="run1")
    )
    artifact_store = LocalArtifactStore(run_store.local_artifact_root("run1"))
    payload = artifact_store.load(result.stage_results["build"].outputs["data"])

    assert result.status == RunStatus.SUCCEEDED
    assert payload == {
        "constructor": 7,
        "runtime": 11,
        "constructor_in_stage_config": False,
    }
