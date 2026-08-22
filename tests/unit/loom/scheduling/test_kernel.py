from __future__ import annotations

from loom.scheduling import (
    Candidate,
    CapacityAtom,
    ClaimSearchBudget,
    ClaimSearchResult,
    ClaimSearchState,
    ClaimValidationResult,
    ClaimValidationState,
    ExactQuantity,
    FifoSchedulingPolicy,
    OpportunityState,
    OpportunityValidationResult,
    PolicyDecisionState,
    ResolvedResourceRequest,
    ResourceAvailabilityEnvelope,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    ResourceInventoryEnvelope,
    ResourceRequestResolution,
    ResourceResolutionState,
    SchedulingComponentDescriptor,
    SchedulingKernel,
    ValidatedResourceEntryView,
    ValidatedResourceOpportunity,
    WorkItem,
)
from loom.pipeline.resources import ResourceEntry
from loom.pipeline.runtime import CpuResourcePlanner, scheduling_entry_view


class CpuPlanner:
    descriptor = SchedulingComponentDescriptor("cpu", 1, "1", "cpu-v1", "test")
    resource_kind = "cpu"
    claim_contracts = (ResourceClaimContractDescriptor("cpu", 1, "cpu-claim"),)

    def resolve_request(self, authored, runtime):
        if authored is None:
            return ResourceRequestResolution(ResourceResolutionState.ABSENT)
        return ResourceRequestResolution(
            ResourceResolutionState.RESOLVED,
            ResolvedResourceRequest("cpu", authored),
        )

    def validate_opportunity(self, inventory, availability):
        return OpportunityValidationResult(
            OpportunityState.VALID,
            ValidatedResourceOpportunity(
                inventory.candidate_id, "cpu", inventory.snapshot_revision
            ),
        )

    def propose_claims(self, request, opportunity, budget):
        return ClaimSearchResult(
            ClaimSearchState.COMPLETE,
            (
                ResourceClaim(
                    "cpu",
                    self.claim_contracts[0],
                    (
                        CapacityAtom(
                            "cpu", "0", request.entry.amount, "count", ExactQuantity(1)
                        ),
                    ),
                    1,
                ),
            ),
        )

    def validate_claim(self, request, claim):
        return ClaimValidationResult(ClaimValidationState.VALID)


class ExhaustedPlanner(CpuPlanner):
    def propose_claims(self, request, opportunity, budget):
        return ClaimSearchResult(ClaimSearchState.EXHAUSTED)


def _candidate(name: str) -> Candidate:
    return Candidate(
        name,
        {"cpu": ResourceInventoryEnvelope(name, "cpu", "1")},
        {"cpu": ResourceAvailabilityEnvelope(name, "cpu", "1")},
    )


def _work(name: str = "work") -> WorkItem:
    return WorkItem(
        name,
        1,
        {
            "cpu": ResolvedResourceRequest(
                "cpu", ValidatedResourceEntryView("cpu", ExactQuantity(1), "count")
            )
        },
    )


def test_exact_quantity_is_normalized_and_rejects_float() -> None:
    assert ExactQuantity(2, 4) == ExactQuantity(1, 2)
    try:
        ExactQuantity(1.5)  # type: ignore[arg-type]
    except ValueError:
        pass
    else:
        raise AssertionError("float quantity was accepted")


def test_kernel_selects_a_complete_claim_and_is_deterministic() -> None:
    kernel = SchedulingKernel(
        planners={"cpu": CpuPlanner()}, policy=FifoSchedulingPolicy()
    )
    decision = kernel.decide(
        work=(_work(),), candidates=(_candidate("b"), _candidate("a")), as_of=1
    )
    assert decision.state is PolicyDecisionState.SELECT
    assert (decision.stage_work_id, decision.candidate_id) == ("work", "a")


def test_exhausted_search_is_not_infeasibility_or_a_policy_candidate() -> None:
    kernel = SchedulingKernel(
        planners={"cpu": ExhaustedPlanner()},
        policy=FifoSchedulingPolicy(),
        claim_budget=ClaimSearchBudget(1),
    )
    decision = kernel.decide(work=(_work(),), candidates=(_candidate("a"),), as_of=1)
    assert decision.state is PolicyDecisionState.WAIT


def test_runtime_resource_adapter_preserves_cpu_minimum_and_normalizes_memory() -> None:
    assert scheduling_entry_view(
        ResourceEntry("cpu", 2, "count")
    ).amount == ExactQuantity(2)
    memory = scheduling_entry_view(ResourceEntry("memory", 2, "MiB"))
    assert (memory.amount, memory.unit) == (ExactQuantity(2 * 1024**2), "B")
    planner = CpuResourcePlanner()
    result = planner.resolve_request(
        ValidatedResourceEntryView("cpu", ExactQuantity(2), "count"),
        ValidatedResourceEntryView("cpu", ExactQuantity(1), "count"),
    )
    assert result.state is ResourceResolutionState.INVALID
