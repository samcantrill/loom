"""Integration tests for same-run-directory resume."""

import json
from pathlib import Path
from typing import cast

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.planning import PlanAction, PlanReasonCode
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.io.uris import uri_to_path
from loom.serialization import PlainData
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


def _branching_config(
    *, build_counter: Path, independent_counter: Path
) -> dict[str, PlainData]:
    config = local_execution_config(counter_path=build_counter)
    pipeline = cast(dict[str, object], config["pipeline"])
    stages = cast(list[object], pipeline["stages"])
    stages.append(
        {
            "name": "independent",
            "factory": {
                "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
            },
            "config": {"value": 9, "counter_path": str(independent_counter)},
            "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
        }
    )
    return config


class _MutableClock:
    def __init__(self, value: str) -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


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
    assert (
        "stage already has an output commit"
        in second.stage_results["build"].failure.message
    )
    assert second.stage_results["report"].action == PlanAction.BLOCKED
    assert counter_path.read_text(encoding="utf-8") == "1"


def test_checksum_corruption_repairs_only_affected_branch_with_commit_history(
    tmp_path: Path,
) -> None:
    build_counter = tmp_path / "build-counter.txt"
    independent_counter = tmp_path / "independent-counter.txt"
    authority = SQLitePerRunAuthorityStore()
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs", authority_store=authority
    )
    runner = PipelineRunner(run_store=run_store)
    run_uri = _run_uri(tmp_path)
    config = _branching_config(
        build_counter=build_counter,
        independent_counter=independent_counter,
    )
    first = runner.run(RunRequest(config=config, run_uri=run_uri))
    original_build = first.stage_results["build"].outputs["data"]
    uri_to_path(original_build.uri).write_bytes(b"corrupt payload")

    resumed = runner.run(RunRequest(config=config, run_uri=run_uri, open_existing=True))

    assert resumed.status is RunStatus.SUCCEEDED, (
        resumed.failed_stage,
        resumed.failure.message
        if resumed.failure is not None
        else resumed.stage_results,
        tuple(reason.code for reason in resumed.stage_results["build"].reasons),
    )
    assert resumed.stage_results["build"].action is PlanAction.RUN
    assert resumed.stage_results["report"].action is PlanAction.RUN
    assert resumed.stage_results["independent"].action is PlanAction.REUSE
    assert PlanReasonCode.ARTIFACT_CHECKSUM_MISMATCH in {
        reason.code for reason in resumed.stage_results["build"].reasons
    }
    assert PlanReasonCode.UPSTREAM_WILL_RUN in {
        reason.code for reason in resumed.stage_results["report"].reasons
    }
    assert build_counter.read_text(encoding="utf-8") == "2"
    assert independent_counter.read_text(encoding="utf-8") == "1"

    build_history = authority.list_output_commits(run_uri, stage_name="build")
    report_history = authority.list_output_commits(run_uri, stage_name="report")
    independent_history = authority.list_output_commits(
        run_uri, stage_name="independent"
    )
    assert len(build_history) == 2
    assert len(report_history) == 2
    assert len(independent_history) == 1
    assert (
        build_history[1].commit.supersedes_commit_id
        == build_history[0].commit.commit_id
    )
    assert (
        report_history[1].commit.supersedes_commit_id
        == report_history[0].commit.commit_id
    )

    snapshot = authority.snapshot(run_uri)
    stages = {stage.stage_name: stage for stage in snapshot.stages}
    assert [attempt.attempt for attempt in stages["build"].attempts] == [1, 2]
    assert [attempt.attempt for attempt in stages["report"].attempts] == [1, 2]
    assert [attempt.attempt for attempt in stages["independent"].attempts] == [1]
    assert stages["build"].latest_commit == build_history[1].commit
    assert stages["build"].artifact_facts == build_history[1].artifact_facts
    repaired_ref = resumed.stage_results["build"].outputs["data"]
    assert json.loads(uri_to_path(repaired_ref.uri).read_text(encoding="utf-8")) == {
        "value": 1
    }
    assert run_store.read_artifact_index(run_uri) == resumed.artifact_index


def test_explicit_resume_classifies_expired_active_attempt_before_attempt_two(
    tmp_path: Path,
) -> None:
    clock = _MutableClock("2020-01-01T00:00:00Z")
    authority = SQLitePerRunAuthorityStore(clock=clock)
    run_store = create_authority_backed_serial_run_store(
        tmp_path / "runs", authority_store=authority
    )
    run_uri = _run_uri(tmp_path)
    counter_path = tmp_path / "counter.txt"
    run_store.create_run(run_uri)
    authority.transition_run(
        run_uri, from_status=RunStatus.CREATED, to_status=RunStatus.RUNNING
    )
    first = authority.allocate_stage_attempt(
        run_uri, "build", owner_id="old-worker", lease_ttl_seconds=1
    )
    assert first.lease is not None
    authority.acquire_controller_lease(
        run_uri, owner_id="old-controller", lease_ttl_seconds=1
    )
    clock.value = "2020-01-01T00:00:02Z"

    resumed = PipelineRunner(run_store=run_store, clock=clock).run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path),
            run_uri=run_uri,
            open_existing=True,
        )
    )

    assert resumed.failure is None, resumed.failure.message if resumed.failure else ""
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.stage_results["build"].attempt == 2
    assert counter_path.read_text(encoding="utf-8") == "1"
    events = run_store.read_events(run_uri)
    names = [event.event_type for event in events]
    assert names.index("run.interrupted") < names.index("run.planned")
    assert names.index("stage.stale") < names.index("stage.started")
    snapshot = authority.snapshot(run_uri)
    build = next(stage for stage in snapshot.stages if stage.stage_name == "build")
    assert [attempt.attempt for attempt in build.attempts] == [1, 2]
