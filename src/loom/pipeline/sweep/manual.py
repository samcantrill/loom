"""First-party deterministic manual sweep provider."""

from __future__ import annotations

from loom.serialization import PlainData

from .providers import SweepProviderContext, SweepProviderIdentity, TrialProposal
from .spec import ManualSweepSpec


class ManualSweepProposalProvider:
    """Finite provider that preserves an explicit trusted trial list."""

    def __init__(self, spec: ManualSweepSpec) -> None:
        self.spec = spec

    @property
    def identity(self) -> SweepProviderIdentity:
        return SweepProviderIdentity(
            provider_name="manual",
            provider_type="loom.manual",
            version="1",
            metadata={
                "mode": "manual",
                "external_trial_list": True,
            },
        )

    def __len__(self) -> int:
        return len(self.spec.trials)

    def proposals(self, context: SweepProviderContext) -> tuple[TrialProposal, ...]:
        proposals: list[TrialProposal] = []
        for index, trial in enumerate(self.spec.trials):
            metadata: dict[str, PlainData] = {
                "mode": "manual",
                **dict(trial.metadata),
            }
            if trial.name is not None:
                metadata.setdefault("trial_name", trial.name)
            proposals.append(
                TrialProposal(
                    provider_trial_id=trial.provider_trial_id
                    or f"manual-{index + 1:04d}",
                    trial_index=index,
                    overrides=dict(trial.overrides),
                    metadata=metadata,
                )
            )
        return tuple(proposals)


__all__ = [
    "ManualSweepProposalProvider",
]
