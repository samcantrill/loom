"""Integration tests for direct sweep dispatch through PipelineRunner."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.pipeline import OutputSpec, PipelineSpec, StageFactorySpec, StageSpec
from loom.pipeline.execution import PipelineRunner, RunRequest
from loom.pipeline.execution.authority_adapter import create_authority_backed_serial_run_store
from loom.pipeline.status import RunStatus
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    SweepRunStatus,
    plan_sweep,
    run_sweep_direct,
)
from loom.provenance.models import ProvenanceCaptureOptions


pytestmark = pytest.mark.integration


def test_direct_dispatch_runs_remaining_trials_after_failure(tmp_path: Path) -> None:
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="direct-integration",
            run_uri_root=f"file://{tmp_path / 'runs' / 'direct-integration'}",
            trials=(
                ManualTrialSpec(
                    name="fail",
                    overrides={"pipeline.variant": "fail"},
                ),
                ManualTrialSpec(
                    name="ok",
                    overrides={"pipeline.variant": "ok"},
                ),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    result = run_sweep_direct(
        plan,
        runner=object(),
        request_template=_request("tests.support.pipeline_execution_stages.JsonProducerStage"),
        request_factory=lambda trial, _dispatch: _request(
            "tests.support.pipeline_execution_stages.FailingStage"
            if trial.metadata.get("trial_name") == "fail"
            else "tests.support.pipeline_execution_stages.JsonProducerStage"
        ),
        runner_factory=lambda _trial, _dispatch, request: _runner(tmp_path, request),
        requested_at="2026-05-14T00:00:00Z",
        sweep_dir=str(tmp_path / "sweep"),
    )

    assert result.status == SweepRunStatus.FAILED
    assert result.failed_count == 1
    assert result.succeeded_count == 1
    assert [trial.run_status for trial in result.trial_results] == [
        RunStatus.FAILED.value,
        RunStatus.SUCCEEDED.value,
    ]


def test_direct_dispatch_preserves_early_stopped_trial_outcome(tmp_path: Path) -> None:
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="direct-early",
            run_uri_root=f"file://{tmp_path / 'runs' / 'direct-early'}",
            trials=(
                ManualTrialSpec(name="stop", overrides={"pipeline.variant": "stop"}),
                ManualTrialSpec(name="ok", overrides={"pipeline.variant": "ok"}),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    result = run_sweep_direct(
        plan,
        runner=object(),
        request_template=_request("tests.support.pipeline_execution_stages.JsonProducerStage"),
        request_factory=lambda trial, _dispatch: _request(
            "tests.support.pipeline_execution_stages.EarlyStopStage"
            if trial.metadata.get("trial_name") == "stop"
            else "tests.support.pipeline_execution_stages.JsonProducerStage"
        ),
        runner_factory=lambda _trial, _dispatch, request: _runner(tmp_path, request),
        requested_at="2026-05-14T00:00:00Z",
    )

    assert result.status == SweepRunStatus.SUCCEEDED
    assert result.early_stopped_count == 1
    assert [trial.run_status for trial in result.trial_results] == [
        RunStatus.CANCELLED.value,
        RunStatus.SUCCEEDED.value,
    ]


def _request(target_path: str) -> RunRequest:
    return RunRequest(
        pipeline=PipelineSpec(
            stages=(
                StageSpec(
                    name="build",
                    factory=StageFactorySpec(target_path=target_path),
                    outputs={"data": OutputSpec(artifact_type="json")},
                ),
            )
        ),
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )


def _runner(tmp_path: Path, request: RunRequest) -> PipelineRunner:
    if request.run_uri is None:
        raise AssertionError("direct dispatch must assign run_uri")
    return PipelineRunner(
        run_store=create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_store=SQLitePerRunAuthorityStore(
                request.run_uri,
                clock=lambda: "2026-05-14T00:00:00Z",
            ),
        )
    )
