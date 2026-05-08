"""Integration tests for self-finalizing stage-job continuation."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline.execution import StageJobRunRequest, run_stage_job
from loom.pipeline.status import RunStatus, StageStatus
from tests.unit.loom.pipeline.execution.test_stage_job import (
    _consumer_stage,
    _prepare_run,
    _producer_stage,
)


pytestmark = pytest.mark.integration


def test_stage_job_finalizes_target_without_parent_process(tmp_path: Path) -> None:
    store, run_uri = _prepare_run(tmp_path)

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(run_uri=run_uri, stage_name="build", executor="local"),
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
    store, run_uri = _prepare_run(tmp_path, stages=(_producer_stage(), _consumer_stage()))

    result = run_stage_job(
        run_store=store,
        request=StageJobRunRequest(run_uri=run_uri, stage_name="build", executor="local"),
    )

    assert result.run_status == RunStatus.RUNNING
    assert store.read_stage_status(run_uri, "consume") is None
