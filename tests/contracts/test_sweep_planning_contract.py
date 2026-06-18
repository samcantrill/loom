"""Contract tests for first-party sweep planning records."""

from __future__ import annotations

import sys

import pytest

from loom.pipeline.sweep import (
    GridSweepProposalProvider,
    GridSweepSpec,
    ManualSweepSpec,
    ManualTrialSpec,
    SweepProviderContext,
    plan_sweep,
)

pytestmark = pytest.mark.contract


def test_grid_planning_contract_uses_plain_provider_proposals() -> None:
    provider = GridSweepProposalProvider(
        GridSweepSpec(
            sweep_id="grid-contract",
            grid={"pipeline.alpha": [1, 2], "pipeline.beta": ["x"]},
        )
    )

    proposals = provider.proposals(SweepProviderContext(sweep_id="grid-contract"))

    assert [proposal.to_dict() for proposal in proposals] == [
        {
            "provider_trial_id": "grid-0001",
            "trial_index": 0,
            "overrides": {"pipeline.alpha": 1, "pipeline.beta": "x"},
            "metadata": {"mode": "grid", "axis_order": ["pipeline.alpha", "pipeline.beta"]},
        },
        {
            "provider_trial_id": "grid-0002",
            "trial_index": 1,
            "overrides": {"pipeline.alpha": 2, "pipeline.beta": "x"},
            "metadata": {"mode": "grid", "axis_order": ["pipeline.alpha", "pipeline.beta"]},
        },
    ]


def test_manual_planning_contract_represents_external_generated_trial_lists() -> None:
    plan = plan_sweep(
        ManualSweepSpec(
            sweep_id="manual-contract",
            run_uri_root="file:///tmp/manual-contract",
            trials=(
                ManualTrialSpec(
                    name="suggestion-1",
                    provider_trial_id="external-optimizer-1",
                    overrides={"pipeline.alpha": 0.5},
                    metadata={"external_provider": "fake-adapter", "rank": 1},
                ),
            ),
        ),
        created_at="2026-05-14T00:00:00Z",
    )

    trial = plan.trials[0]

    assert "optuna" not in sys.modules
    assert trial.trial_id == "trial-0001"
    assert trial.provider_trial_id == "external-optimizer-1"
    assert trial.metadata["external_provider"] == "fake-adapter"
    assert trial.metadata["trial_name"] == "suggestion-1"
