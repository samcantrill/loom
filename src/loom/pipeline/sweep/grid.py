"""First-party deterministic grid sweep provider."""

from __future__ import annotations

from itertools import product

from .providers import SweepProviderContext, SweepProviderIdentity, TrialProposal
from .spec import GridSweepSpec


class GridSweepProposalProvider:
    """Finite provider that expands a trusted grid spec in authored order."""

    def __init__(self, spec: GridSweepSpec) -> None:
        self.spec = spec

    @property
    def identity(self) -> SweepProviderIdentity:
        return SweepProviderIdentity(
            provider_name="grid",
            provider_type="loom.grid",
            version="1",
            metadata={
                "mode": "grid",
                "axis_order": list(self.spec.grid),
            },
        )

    def __len__(self) -> int:
        count = 1
        for values in self.spec.grid.values():
            count *= len(values)
        return count

    def proposals(self, context: SweepProviderContext) -> tuple[TrialProposal, ...]:
        axis_names = tuple(self.spec.grid)
        axis_values = tuple(self.spec.grid[name] for name in axis_names)
        proposals: list[TrialProposal] = []
        for index, values in enumerate(product(*axis_values)):
            overrides = dict(zip(axis_names, values, strict=True))
            proposals.append(
                TrialProposal(
                    provider_trial_id=f"grid-{index + 1:04d}",
                    trial_index=index,
                    overrides=overrides,
                    metadata={
                        "mode": "grid",
                        "axis_order": list(axis_names),
                    },
                )
            )
        return tuple(proposals)


__all__ = [
    "GridSweepProposalProvider",
]
