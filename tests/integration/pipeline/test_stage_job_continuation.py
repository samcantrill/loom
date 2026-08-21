"""Integration tests for self-finalizing stage-job continuation."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline.execution import StageJobRunRequest, run_stage_job
from loom.pipeline.event_sinks import EventSinkContext, EventSinkRegistry, EventSinkSubscription
from loom.pipeline.events import EventReference, PipelineEventRecord
from loom.pipeline.status import RunStatus, StageStatus
from tests.unit.loom.pipeline.execution.test_stage_job import (
    _consumer_stage,
    _mark_build_submitted,
    _prepare_run,
    _producer_stage,
)


pytestmark = pytest.mark.integration


def test_stage_job_finalizes_target_without_parent_process(tmp_path: Path) -> None:
    store, run_uri = _prepare_run(tmp_path)

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(
            run_uri=run_uri, stage_name="build", executor="local"
        ),
    )

    assert result.status == StageStatus.SUCCEEDED
    assert result.run_status == RunStatus.SUCCEEDED
    assert store.read_stage_worker_result(run_uri, "build", attempt=1) is None
    stage_status = store.read_stage_status(run_uri, "build")
    run_status = store.read_run_status(run_uri)
    assert stage_status is not None
    assert run_status is not None
    assert stage_status.status == StageStatus.SUCCEEDED
    assert run_status.status == RunStatus.SUCCEEDED


def test_stage_job_does_not_mutate_downstream_stage_status(tmp_path: Path) -> None:
    store, run_uri = _prepare_run(
        tmp_path, stages=(_producer_stage(), _consumer_stage())
    )

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(
            run_uri=run_uri, stage_name="build", executor="local"
        ),
    )

    assert result.run_status == RunStatus.RUNNING
    assert store.read_stage_status(run_uri, "consume") is None


def test_stage_job_continues_matching_submitted_prepared_attempt(
    tmp_path: Path,
) -> None:
    store, run_uri = _prepare_run(tmp_path)
    _mark_build_submitted(store, run_uri)

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(
            run_uri=run_uri,
            stage_name="build",
            executor="local",
        ),
    )

    assert result.status == StageStatus.SUCCEEDED
    assert result.run_status == RunStatus.SUCCEEDED


def test_stage_job_filtered_sink_observes_committed_completed_stage(tmp_path: Path) -> None:
    store, run_uri = _prepare_run(tmp_path)
    registry = EventSinkRegistry()
    observed: list[str] = []

    def sink(
        event: PipelineEventRecord | EventReference, context: EventSinkContext
    ) -> None:
        assert isinstance(event, PipelineEventRecord)
        status = store.read_stage_status(run_uri, "build")
        assert status is not None and status.status == StageStatus.SUCCEEDED
        assert store.read_stage_outputs(run_uri, "build")
        assert context.event_reference == event.to_event_reference()
        observed.append(event.event_type)

    registry.register(
        "audit.completed",
        sink,
        subscription=EventSinkSubscription(event_types=("stage.completed",)),
    )

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(run_uri=run_uri, stage_name="build", executor="local"),
        event_sink_registry=registry,
    )

    assert result.status == StageStatus.SUCCEEDED
    assert observed == ["stage.completed"]
