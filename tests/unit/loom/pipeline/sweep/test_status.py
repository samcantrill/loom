"""Unit tests for sweep status aggregation."""

from __future__ import annotations

from types import SimpleNamespace

from loom.pipeline.status import RunStatus
from loom.pipeline.stores import BackendRevision, TrialReference, TrialState
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    SweepAggregateStatus,
    SweepTrialOutcome,
    build_sweep_status,
    plan_sweep,
)
from loom.queue import QueueItemStatus


def test_build_sweep_status_prefers_run_lifecycle_and_derives_early_stop() -> None:
    plan = _plan()
    run_statuses = {
        "file:///tmp/status/trial-0001": SimpleNamespace(
            status=RunStatus.CANCELLED,
            metadata={"reason_code": "early_stop"},
        ),
        "file:///tmp/status/trial-0002": SimpleNamespace(
            status=RunStatus.SUCCEEDED,
            metadata={},
        ),
    }

    summary = build_sweep_status(plan, run_statuses=run_statuses)

    assert summary.status is SweepAggregateStatus.SUCCEEDED
    assert summary.early_stopped_count == 1
    assert [trial.outcome for trial in summary.trials] == [
        SweepTrialOutcome.EARLY_STOPPED,
        SweepTrialOutcome.SUCCEEDED,
    ]


def test_build_sweep_status_uses_queue_and_coordination_when_run_status_missing() -> None:
    plan = _plan()
    queue_item = SimpleNamespace(
        queue_item_id="queue-item-1",
        run_uri="file:///tmp/status/trial-0001",
        status=QueueItemStatus.QUEUED,
        metadata={"trial_id": "trial-0001"},
    )
    coordination = TrialReference(
        trial_id="trial-0002",
        sweep_id="status",
        run_uri="file:///tmp/status/trial-0002",
        state=TrialState.RUNNING,
        revision=BackendRevision(sequence=1, token="external"),
    )

    summary = build_sweep_status(
        plan,
        queue_items=(queue_item,),
        coordination_trials=(coordination,),
    )

    assert summary.status is SweepAggregateStatus.RUNNING
    assert summary.counts["queued"] == 1
    assert summary.counts["running"] == 1
    assert summary.trials[0].queue_item_id == "queue-item-1"
    assert summary.trials[1].coordination_state == "running"


def _plan():
    return plan_sweep(
        ManualSweepSpec(
            sweep_id="status",
            run_uri_root="file:///tmp/status",
            trials=(
                ManualTrialSpec(overrides={"pipeline.variant": "a"}),
                ManualTrialSpec(overrides={"pipeline.variant": "b"}),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )
