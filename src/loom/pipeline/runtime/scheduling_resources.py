"""Adapters and deterministic CPU/memory planners for the scheduling kernel.

The existing pipeline resource codec remains the sole authored schema.  This
module translates its already-validated values to scheduling's immutable view.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceEntry
from loom.scheduling import (
    CapacityAtom,
    ClaimSearchBudget,
    ClaimSearchResult,
    ClaimSearchState,
    ClaimValidationResult,
    ClaimValidationState,
    ExactQuantity,
    OpportunityState,
    OpportunityValidationResult,
    ResolvedResourceRequest,
    ResourceAvailabilityEnvelope,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    ResourceInventoryEnvelope,
    ResourceRequestResolution,
    ResourceResolutionState,
    SchedulingComponentDescriptor,
    ValidatedResourceEntryView,
    ValidatedResourceOpportunity,
)


_MEMORY_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}


def scheduling_entry_view(entry: ResourceEntry) -> ValidatedResourceEntryView:
    """Convert one canonical validated resource entry without changing its codec."""

    if entry.kind == "cpu":
        if not isinstance(entry.amount, int) or isinstance(entry.amount, bool):
            raise RuntimeResourceError(
                "managed CPU resources require a positive integer"
            )
        return ValidatedResourceEntryView(
            "cpu", ExactQuantity(entry.amount), "count", entry.attributes
        )
    if entry.kind == "memory":
        if not isinstance(entry.amount, int) or isinstance(entry.amount, bool):
            raise RuntimeResourceError(
                "managed memory resources require an exact integer amount"
            )
        multiplier = _MEMORY_UNITS.get(entry.unit or "")
        if multiplier is None:
            raise RuntimeResourceError(
                "managed memory resources require a binary byte unit"
            )
        return ValidatedResourceEntryView(
            "memory",
            ExactQuantity(entry.amount * multiplier),
            "B",
            entry.attributes,
        )
    if entry.unit == "share":
        denominator = entry.attributes.get("share_denominator")
        if (
            not isinstance(entry.amount, int)
            or isinstance(entry.amount, bool)
            or not isinstance(denominator, int)
            or isinstance(denominator, bool)
            or denominator <= 0
        ):
            raise RuntimeResourceError(
                "share resources require an integer amount and share_denominator"
            )
        return ValidatedResourceEntryView(
            entry.kind,
            ExactQuantity(entry.amount, denominator),
            entry.unit,
            entry.attributes,
        )
    if isinstance(entry.amount, float):
        raise RuntimeResourceError(
            "managed resources require exact non-float quantities"
        )
    return ValidatedResourceEntryView(
        entry.kind, ExactQuantity(entry.amount), entry.unit, entry.attributes
    )


class _CountPlanner:
    resource_kind: str
    unit: str
    descriptor: SchedulingComponentDescriptor
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def resolve_request(
        self,
        authored: ValidatedResourceEntryView | None,
        runtime: ValidatedResourceEntryView | None,
    ) -> ResourceRequestResolution:
        if authored is None and runtime is None:
            return ResourceRequestResolution(ResourceResolutionState.ABSENT)
        value = runtime or authored
        assert value is not None
        if value.kind != self.resource_kind or value.unit != self.unit:
            return ResourceRequestResolution(
                ResourceResolutionState.INVALID,
                explanation="wrong resource kind or unit",
            )
        if (
            authored is not None
            and runtime is not None
            and runtime.amount.fraction < authored.amount.fraction
        ):
            return ResourceRequestResolution(
                ResourceResolutionState.INVALID,
                explanation="runtime refinement weakens authored minimum",
            )
        if (
            authored is not None
            and runtime is not None
            and any(
                runtime.attributes.get(key) != expected
                for key, expected in authored.attributes.items()
            )
        ):
            return ResourceRequestResolution(
                ResourceResolutionState.INVALID,
                explanation="runtime refinement weakens authored attributes",
            )
        return ResourceRequestResolution(
            ResourceResolutionState.RESOLVED,
            ResolvedResourceRequest(self.resource_kind, value),
        )

    def validate_opportunity(
        self,
        inventory: ResourceInventoryEnvelope,
        availability: ResourceAvailabilityEnvelope,
    ) -> OpportunityValidationResult:
        if (
            inventory.resource_kind != self.resource_kind
            or availability.resource_kind != self.resource_kind
        ):
            return OpportunityValidationResult(
                OpportunityState.INVALID, explanation="resource kind mismatch"
            )
        if (
            inventory.candidate_id != availability.candidate_id
            or inventory.snapshot_revision != availability.snapshot_revision
        ):
            return OpportunityValidationResult(
                OpportunityState.INVALID,
                explanation="opportunity snapshots do not match",
            )
        if any(
            atom.owner_resource_kind != self.resource_kind or atom.unit != self.unit
            for atom in availability.atoms
        ):
            return OpportunityValidationResult(
                OpportunityState.INVALID,
                explanation="availability atom kind or unit is invalid",
            )
        return OpportunityValidationResult(
            OpportunityState.VALID,
            ValidatedResourceOpportunity(
                inventory.candidate_id,
                self.resource_kind,
                inventory.snapshot_revision,
                availability.data,
                availability.atoms,
            ),
        )

    def propose_claims(
        self,
        request: ResolvedResourceRequest,
        opportunity: ValidatedResourceOpportunity,
        budget: ClaimSearchBudget,
    ) -> ClaimSearchResult:
        claims, exhausted = _complete_exact_claims(
            resource_kind=self.resource_kind,
            contract=self.claim_contracts[0],
            requested=request.entry.amount.fraction,
            atoms=opportunity.available_atoms,
            snapshot_revision=opportunity.snapshot_revision,
            max_claims=budget.max_claims,
            max_expansions=budget.max_expansions,
        )
        if exhausted:
            return ClaimSearchResult(
                ClaimSearchState.EXHAUSTED,
                explanation="built-in exact claim search exceeded its bound",
            )
        if not claims:
            return ClaimSearchResult(ClaimSearchState.COMPLETE)
        return ClaimSearchResult(ClaimSearchState.COMPLETE, tuple(claims))

    def validate_claim(
        self, request: ResolvedResourceRequest, claim: ResourceClaim
    ) -> ClaimValidationResult:
        if (
            claim.resource_kind != self.resource_kind
            or claim.contract not in self.claim_contracts
        ):
            return ClaimValidationResult(
                ClaimValidationState.INVALID, "wrong claim contract"
            )
        if any(atom.unit != self.unit for atom in claim.atoms):
            return ClaimValidationResult(
                ClaimValidationState.INVALID, "claim atom unit is invalid"
            )
        claimed = sum((atom.amount.fraction for atom in claim.atoms), Fraction(0))
        if claimed != request.entry.amount.fraction:
            return ClaimValidationResult(
                ClaimValidationState.INVALID, "claim does not exactly meet request"
            )
        return ClaimValidationResult(ClaimValidationState.VALID)


class CpuResourcePlanner(_CountPlanner):
    resource_kind = "cpu"
    unit = "count"
    descriptor = SchedulingComponentDescriptor(
        "cpu", 1, "1", "builtin-cpu-planner-v1", "builtin"
    )
    claim_contracts = (
        ResourceClaimContractDescriptor("cpu", 1, "builtin-cpu-claim-v1"),
    )


class MemoryResourcePlanner(_CountPlanner):
    resource_kind = "memory"
    unit = "B"
    descriptor = SchedulingComponentDescriptor(
        "memory", 1, "1", "builtin-memory-planner-v1", "builtin"
    )
    claim_contracts = (
        ResourceClaimContractDescriptor("memory", 1, "builtin-memory-claim-v1"),
    )


def _complete_exact_claims(
    *,
    resource_kind: str,
    contract: ResourceClaimContractDescriptor,
    requested: Fraction,
    atoms: Sequence[CapacityAtom],
    snapshot_revision: str,
    max_claims: int,
    max_expansions: int,
) -> tuple[list[ResourceClaim], bool]:
    ordered = tuple(sorted(atoms, key=lambda atom: atom.local_capacity_key))
    claims: list[ResourceClaim] = []
    expansions = 0

    def visit(index: int, remaining: Fraction, selected: list[CapacityAtom]) -> bool:
        nonlocal expansions
        expansions += 1
        if expansions > max_expansions:
            return True
        if index == len(ordered):
            if remaining == 0:
                claims.append(
                    ResourceClaim(
                        resource_kind=resource_kind,
                        contract=contract,
                        atoms=tuple(selected),
                        provider_data_version=1,
                        provider_data={"snapshot_revision": snapshot_revision},
                    )
                )
            return len(claims) > max_claims
        atom = ordered[index]
        maximum = min(atom.amount.fraction, remaining)
        step = atom.granularity.fraction
        if index == len(ordered) - 1:
            amounts = (remaining,) if remaining > 0 else (Fraction(0),)
        else:
            amounts = tuple(
                step * units for units in range(int(maximum / step), -1, -1)
            )
        for amount in amounts:
            if amount < 0 or amount > maximum or amount % step:
                continue
            if amount:
                selected.append(
                    CapacityAtom(
                        atom.owner_resource_kind,
                        atom.local_capacity_key,
                        ExactQuantity(amount.numerator, amount.denominator),
                        atom.unit,
                        atom.granularity,
                    )
                )
            exhausted = visit(index + 1, remaining - amount, selected)
            if amount:
                selected.pop()
            if exhausted:
                return True
        return False

    exhausted = visit(0, requested, [])
    if exhausted:
        return [], True
    return claims, False
