"""Unit tests for sweep coordination projection helpers."""

from __future__ import annotations


from loom.pipeline.stores import TrialState
from loom.pipeline.sweep import (
    ManualSweepSpec,
    ManualTrialSpec,
    project_sweep_coordination,
    plan_sweep,
)
from tests.support.authority_stores import InMemoryWorkspaceCoordinationStore


def test_project_sweep_coordination_records_planned_trials_idempotently() -> None:
    plan = _plan()
    store = InMemoryWorkspaceCoordinationStore()

    first = project_sweep_coordination(
        plan,
        store,
        workspace_id="workspace-1",
        workspace_root_uri="file:///workspace",
    )
    second = project_sweep_coordination(
        plan,
        store,
        workspace_id="workspace-1",
        trial_states={"trial-0001": TrialState.RUNNING},
    )

    assert first.identity.workspace_revision is not None
    assert first.identity.sweep_revision is not None
    assert second.identity.workspace_revision is None
    assert second.identity.sweep_revision is None
    trials = store.list_trials("coord")
    assert [trial.trial_id for trial in trials] == ["trial-0001", "trial-0002"]
    assert [trial.state for trial in trials] == [
        TrialState.RUNNING,
        TrialState.PENDING,
    ]
    assert trials[0].metadata["proposal_overrides"] == {"pipeline.variant": "a"}


def _plan():
    return plan_sweep(
        ManualSweepSpec(
            sweep_id="coord",
            run_uri_root="file:///tmp/coord",
            trials=(
                ManualTrialSpec(overrides={"pipeline.variant": "a"}),
                ManualTrialSpec(overrides={"pipeline.variant": "b"}),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )


def test_trial_state_mapper_accepts_run_status():
    from loom.pipeline.sweep import trial_state_from_run_status

    assert trial_state_from_run_status("SUCCEEDED") is TrialState.COMPLETED
