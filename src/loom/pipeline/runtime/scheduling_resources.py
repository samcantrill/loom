"""Adapters and deterministic CPU/memory planners for the scheduling kernel.

The existing pipeline resource codec remains the sole authored schema.  This
module translates its already-validated values to scheduling's immutable view.
"""

from __future__ import annotations


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
        return ValidatedResourceEntryView("cpu", ExactQuantity(entry.amount), "count")
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
            "memory", ExactQuantity(entry.amount * multiplier), "B"
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
        amount = availability.data.get("amount")
        key = availability.data.get("capacity_key", self.resource_kind)
        if (
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount < 0
            or not isinstance(key, str)
            or not key
        ):
            return OpportunityValidationResult(
                OpportunityState.INVALID, explanation="invalid available capacity"
            )
        return OpportunityValidationResult(
            OpportunityState.VALID,
            ValidatedResourceOpportunity(
                inventory.candidate_id,
                self.resource_kind,
                inventory.snapshot_revision,
                {"amount": amount, "capacity_key": key},
            ),
        )

    def propose_claims(
        self,
        request: ResolvedResourceRequest,
        opportunity: ValidatedResourceOpportunity,
        budget: ClaimSearchBudget,
    ) -> ClaimSearchResult:
        if request.entry.amount.fraction > opportunity.data["amount"]:
            return ClaimSearchResult(ClaimSearchState.COMPLETE)
        claim = ResourceClaim(
            self.resource_kind,
            self.claim_contracts[0],
            (
                CapacityAtom(
                    self.resource_kind,
                    opportunity.data["capacity_key"],
                    request.entry.amount,
                    self.unit,
                    ExactQuantity(1),
                ),
            ),
            1,
            {"snapshot_revision": opportunity.snapshot_revision},
        )
        return ClaimSearchResult(ClaimSearchState.COMPLETE, (claim,))

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
        if len(claim.atoms) != 1 or claim.atoms[0].amount != request.entry.amount:
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
