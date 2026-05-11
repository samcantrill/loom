"""Integration tests for same-run-directory resume."""

from pathlib import Path

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.planning import PlanAction
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.support.pipeline_execution_configs import local_execution_config

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _run_uri(tmp_path: Path, name: str = "run1") -> str:
    return path_to_run_uri(tmp_path / "runs" / name)


def _run_store(tmp_path: Path):
    return create_authority_backed_serial_run_store(
        tmp_path / "runs",
        authority_store=SQLitePerRunAuthorityStore(),
    )


def test_same_run_rerun_reuses_unchanged_stages(tmp_path: Path) -> None:
    counter_path = tmp_path / "counter.txt"
    run_store = _run_store(tmp_path)
    runner = PipelineRunner(run_store=run_store)
    run_uri = _run_uri(tmp_path)

    first = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path), run_uri=run_uri
        )
    )
    second = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path),
            run_uri=run_uri,
            open_existing=True,
        )
    )

    assert first.status == RunStatus.SUCCEEDED
    assert second.status == RunStatus.SUCCEEDED
    assert second.stage_results["build"].action == PlanAction.REUSE
    assert second.stage_results["report"].action == PlanAction.REUSE
    assert counter_path.read_text(encoding="utf-8") == "1"
    status = run_store.read_stage_status(run_uri, "build")
    assert status is not None
    assert status.status == StageStatus.SUCCEEDED
    assert run_store.read_run_lock(run_uri) is None
    events = run_store.read_events(run_uri)
    reused_events = [event for event in events if event.event_type == "stage.reused"]
    assert [event.scope.stage_name for event in reused_events] == ["build", "report"]
    opened_events = [event for event in events if event.event_type == "run.opened"]
    assert opened_events[-1].payload == {"open_existing": True}


def test_changed_config_rerun_fails_closed_without_overwriting_authority_commit(
    tmp_path: Path,
) -> None:
    counter_path = tmp_path / "counter.txt"
    run_store = _run_store(tmp_path)
    runner = PipelineRunner(run_store=run_store)
    run_uri = _run_uri(tmp_path)

    runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path, value=1),
            run_uri=run_uri,
        )
    )
    second = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path, value=2),
            run_uri=run_uri,
            open_existing=True,
        )
    )

    assert second.status == RunStatus.FAILED
    assert second.stage_results["build"].action == PlanAction.RUN
    assert second.stage_results["build"].failure is not None
    assert second.stage_results["build"].failure.failure_type == "store_commit"
    assert "stage already has an output commit" in second.stage_results[
        "build"
    ].failure.message
    assert second.stage_results["report"].action == PlanAction.BLOCKED
    assert counter_path.read_text(encoding="utf-8") == "1"
