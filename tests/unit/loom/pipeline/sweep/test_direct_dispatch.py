"""Unit tests for direct sequential sweep dispatch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.pipeline import OutputSpec, PipelineSpec, StageFactorySpec, StageSpec
from loom.pipeline.execution import RunRequest
from loom.pipeline.status import RunStatus
from loom.serialization import PlainData
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    SweepProtocolError,
    SweepRunStatus,
    build_dispatch_requests,
    build_trial_run_request,
    plan_sweep,
    run_sweep_direct,
    write_sweep_plan,
)
from loom.provenance.models import ProvenanceCaptureOptions


class _FakeRunner:
    def __init__(self, statuses: list[RunStatus]) -> None:
        self.statuses = list(statuses)
        self.requests: list[RunRequest] = []

    def run(self, request: RunRequest) -> object:
        self.requests.append(request)
        status = self.statuses.pop(0)
        metadata = (
            {"reason_code": "early_stop", "reason": {"code": "early_stop"}}
            if status == RunStatus.CANCELLED
            else {}
        )
        return SimpleNamespace(
            run_uri=request.run_uri,
            status=status,
            finished_at="2026-05-14T00:00:00Z",
            metadata=metadata,
        )


def test_build_dispatch_requests_and_trial_run_request_preserve_trial_metadata() -> None:
    plan = _plan()
    template = _template_request(metadata={"caller": "unit"})
    dispatch_request = build_dispatch_requests(
        plan,
        requested_at="2026-05-14T00:00:00Z",
    )[0]

    request = build_trial_run_request(template, plan.trials[0], dispatch_request)

    assert request.run_uri == "file:///tmp/direct/trial-0001"
    assert request.failure_policy.stop_on_first_failure is True
    assert request.metadata["caller"] == "unit"
    assert request.metadata["sweep_id"] == "direct"
    assert request.metadata["trial_id"] == "trial-0001"
    assert request.metadata["proposal_overrides"] == {"pipeline.variant": "a"}


def test_run_sweep_direct_continues_after_failed_trials() -> None:
    plan = _plan()
    runner = _FakeRunner([RunStatus.FAILED, RunStatus.SUCCEEDED])

    result = run_sweep_direct(
        plan,
        runner=runner,
        request_template=_template_request(),
        requested_at="2026-05-14T00:00:00Z",
    )

    assert [request.run_uri for request in runner.requests] == [
        "file:///tmp/direct/trial-0001",
        "file:///tmp/direct/trial-0002",
    ]
    assert result.status == SweepRunStatus.FAILED
    assert result.failed_count == 1
    assert result.succeeded_count == 1


def test_run_sweep_direct_counts_early_stopped_trials_without_failed_sweep() -> None:
    plan = _plan()
    runner = _FakeRunner([RunStatus.CANCELLED, RunStatus.SUCCEEDED])

    result = run_sweep_direct(
        plan,
        runner=runner,
        request_template=_template_request(),
        requested_at="2026-05-14T00:00:00Z",
    )

    assert result.status == SweepRunStatus.SUCCEEDED
    assert result.early_stopped_count == 1
    assert result.failed_count == 0


def test_run_sweep_direct_rejects_incompatible_existing_manifests(
    tmp_path: Path,
) -> None:
    plan = _plan()
    changed = plan_sweep(
        ManualSweepSpec(
            sweep_id="direct",
            run_uri_root="file:///tmp/direct",
            trials=(
                ManualTrialSpec(overrides={"pipeline.variant": "a"}),
                ManualTrialSpec(overrides={"pipeline.variant": "b"}),
                ManualTrialSpec(overrides={"pipeline.variant": "c"}),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )
    write_sweep_plan(plan, tmp_path)

    with pytest.raises(SweepProtocolError, match="trial_count_mismatch"):
        run_sweep_direct(
            changed,
            runner=_FakeRunner([RunStatus.SUCCEEDED]),
            request_template=_template_request(),
            sweep_dir=str(tmp_path),
        )


def _plan():
    return plan_sweep(
        ManualSweepSpec(
            sweep_id="direct",
            run_uri_root="file:///tmp/direct",
            trials=(
                ManualTrialSpec(overrides={"pipeline.variant": "a"}),
                ManualTrialSpec(overrides={"pipeline.variant": "b"}),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )


def _template_request(
    *,
    metadata: dict[str, PlainData] | None = None,
) -> RunRequest:
    return RunRequest(
        pipeline=PipelineSpec(
            stages=(
                StageSpec(
                    name="build",
                    factory=StageFactorySpec(
                        target_path="tests.support.pipeline_execution_stages.JsonProducerStage"
                    ),
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
        metadata=metadata or {},
    )
