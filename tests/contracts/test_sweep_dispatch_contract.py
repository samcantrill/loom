"""Intentional sweep API and native result contracts."""

import pytest
from loom.pipeline.sweep import (
    SweepTrialStatus,
    SweepTrialOutcome,
    SweepStatusSummary,
    SweepAggregateStatus,
)


@pytest.mark.parametrize(
    "name",
    [
        "run_sweep_direct",
        "enqueue_sweep_trials",
        "DirectSweepRunResult",
        "QueueSweepDispatchResult",
        "SweepDispatchRequest",
        "build_queue_enqueue_request",
        "build_dispatch_requests",
    ],
)
def test_obsolete_dispatch_surfaces_are_removed(name):
    import loom.pipeline.sweep as sweep

    assert not hasattr(sweep, name)


def test_sweep_status_summary_contract_exposes_counts() -> None:
    trial = SweepTrialStatus(
        sweep_id="sweep-1",
        trial_id="trial-1",
        trial_index=0,
        outcome=SweepTrialOutcome.EARLY_STOPPED,
        run_uri="file:///runs/trial-1",
        run_status="CANCELLED",
        early_stopped=True,
    )
    summary = SweepStatusSummary(
        sweep_id="sweep-1",
        status=SweepAggregateStatus.SUCCEEDED,
        trials=(trial,),
    )

    assert summary.trial_count == 1
    assert summary.early_stopped_count == 1
    counts = summary.to_dict()["counts"]
    assert isinstance(counts, dict)
    assert counts["early_stopped"] == 1
