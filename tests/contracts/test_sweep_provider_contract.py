"""Contract tests for sweep provider and proposal protocols."""

from __future__ import annotations

import pytest

from loom.pipeline.sweep import (
    FiniteSweepProposalProvider,
    GridSweepProposalProvider,
    GridSweepSpec,
    ManualSweepProposalProvider,
    ManualSweepSpec,
    ManualTrialSpec,
    SweepProposalProvider,
    SweepProviderContext,
    SweepProviderIdentity,
    TrialProposal,
    provider_is_finite,
    provider_trial_count,
)

pytestmark = pytest.mark.contract


_PROVIDER_IDENTITY = SweepProviderIdentity(
    provider_name="sample-provider",
    provider_type="test",
    version="1.0.0",
    metadata={"namespace": "sweep"},
)


class FiniteFakeProvider:
    def __init__(self) -> None:
        self._count = 2

    @property
    def identity(self) -> SweepProviderIdentity:
        return _PROVIDER_IDENTITY

    def proposals(self, context: SweepProviderContext) -> tuple[TrialProposal, ...]:
        return (
            TrialProposal(trial_index=0, overrides={"alpha": 1}, provider_trial_id="a"),
            TrialProposal(trial_index=1, overrides={"alpha": 2}, provider_trial_id="b"),
        )

    def __len__(self) -> int:
        return self._count


class UnsizedFakeProvider:
    @property
    def identity(self) -> SweepProviderIdentity:
        return _PROVIDER_IDENTITY

    def proposals(self, context: SweepProviderContext) -> tuple[TrialProposal, ...]:
        return (TrialProposal(trial_index=0, overrides={"alpha": 1}),)


def test_sweep_proposal_provider_protocol_accepts_finite_and_unsized_providers() -> None:
    finite = FiniteFakeProvider()
    unsized = UnsizedFakeProvider()

    context = SweepProviderContext(sweep_id="sweep-1", sweep_name="test-sweep")

    assert isinstance(finite, SweepProposalProvider)
    assert isinstance(unsized, SweepProposalProvider)
    assert isinstance(finite, FiniteSweepProposalProvider)
    assert not isinstance(unsized, FiniteSweepProposalProvider)
    assert provider_is_finite(finite)
    assert not provider_is_finite(unsized)
    assert provider_trial_count(finite) == 2
    assert provider_trial_count(unsized) is None

    finite_payload = [proposal.to_dict() for proposal in finite.proposals(context)]
    unsized_payload = [proposal.to_dict() for proposal in unsized.proposals(context)]
    assert finite_payload == [
        {
            "provider_trial_id": "a",
            "trial_index": 0,
            "overrides": {"alpha": 1},
            "metadata": {},
        },
        {
            "provider_trial_id": "b",
            "trial_index": 1,
            "overrides": {"alpha": 2},
            "metadata": {},
        },
    ]
    assert unsized_payload == [
        {
            "provider_trial_id": None,
            "trial_index": 0,
            "overrides": {"alpha": 1},
            "metadata": {},
        }
    ]


def test_finite_provider_capability_requires_provider_surface() -> None:
    assert not isinstance([1, 2], FiniteSweepProposalProvider)
    assert not provider_is_finite([1, 2])
    assert provider_trial_count([1, 2]) is None


def test_sweep_provider_identity_round_trip_contract_shape() -> None:
    payload = _PROVIDER_IDENTITY.to_dict()
    restored = SweepProviderIdentity.from_dict(payload)

    assert restored == _PROVIDER_IDENTITY
    assert restored.to_dict() == payload


def test_first_party_grid_and_manual_providers_satisfy_provider_contracts() -> None:
    grid = GridSweepProposalProvider(
        GridSweepSpec(
            sweep_id="grid",
            grid={"pipeline.lr": [0.1, 0.01], "pipeline.seed": [1, 2]},
        )
    )
    manual = ManualSweepProposalProvider(
        ManualSweepSpec(
            sweep_id="manual",
            trials=(
                ManualTrialSpec(
                    name="baseline",
                    provider_trial_id="external-1",
                    overrides={"pipeline.variant": "baseline"},
                ),
            ),
        )
    )
    context = SweepProviderContext(sweep_id="grid")

    assert isinstance(grid, SweepProposalProvider)
    assert isinstance(grid, FiniteSweepProposalProvider)
    assert provider_trial_count(grid) == 4
    assert [
        proposal.overrides for proposal in grid.proposals(context)
    ] == [
        {"pipeline.lr": 0.1, "pipeline.seed": 1},
        {"pipeline.lr": 0.1, "pipeline.seed": 2},
        {"pipeline.lr": 0.01, "pipeline.seed": 1},
        {"pipeline.lr": 0.01, "pipeline.seed": 2},
    ]

    assert isinstance(manual, SweepProposalProvider)
    assert isinstance(manual, FiniteSweepProposalProvider)
    assert provider_trial_count(manual) == 1
    proposal = manual.proposals(SweepProviderContext(sweep_id="manual"))[0]
    assert proposal.provider_trial_id == "external-1"
    assert proposal.metadata["trial_name"] == "baseline"
