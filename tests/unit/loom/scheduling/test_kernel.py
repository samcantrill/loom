from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import pytest

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceEntry, ResourceRequest
from loom.pipeline.runtime import (
    CpuResourcePlanner,
    ExecutionRoute,
    ExecutionRouteKind,
    MemoryResourcePlanner,
    ResolvedStagePlacement,
    StagePlacementPolicy,
    resolve_stage_placement,
    scheduling_entry_view,
)
from loom.scheduling import (
    Candidate,
    CapacityAtom,
    ClaimSearchResult,
    ClaimSearchState,
    ClaimValidationResult,
    ClaimValidationState,
    ComponentRegistry,
    ExactQuantity,
    FifoSchedulingPolicy,
    HardConstraintSpec,
    OpportunityState,
    OpportunityValidationResult,
    PolicyContext,
    PolicyDecision,
    PolicyDecisionState,
    PreferenceEvaluationState,
    PreferenceResult,
    PreferenceScore,
    PreferenceSpec,
    ResolvedResourceRequest,
    ResourceAvailabilityEnvelope,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    ResourceInventoryEnvelope,
    ResourceRequestResolution,
    ResourceResolutionState,
    SchedulingComponentDescriptor,
    SchedulingError,
    SchedulingKernel,
    SchedulingLimits,
    TargetConstraintEvaluator,
    ValidatedResourceEntryView,
    ValidatedResourceOpportunity,
    WorkItem,
    WorkSearchState,
)
from loom.serialization import PlainData


def _descriptor(kind: str) -> SchedulingComponentDescriptor:
    return SchedulingComponentDescriptor(kind, 1, "1", f"test:{kind}:v1", "test")


def _atom(kind: str, key: str, amount: int, unit: str = "count") -> CapacityAtom:
    return CapacityAtom(kind, key, ExactQuantity(amount), unit, ExactQuantity(1))


def _resource_envelopes(
    candidate_id: str,
    kind: str,
    atoms: tuple[CapacityAtom, ...],
    *,
    data: Mapping[str, PlainData] | None = None,
) -> tuple[ResourceInventoryEnvelope, ResourceAvailabilityEnvelope]:
    plain_data = dict(data or {})
    return (
        ResourceInventoryEnvelope(
            candidate_id, kind, "revision-1", data=plain_data, atoms=atoms
        ),
        ResourceAvailabilityEnvelope(
            candidate_id, kind, "revision-1", data=plain_data, atoms=atoms
        ),
    )


def _candidate(
    name: str,
    *,
    cpu: int = 4,
    attributes: Mapping[str, PlainData] | None = None,
    extra: Mapping[str, tuple[ResourceInventoryEnvelope, ResourceAvailabilityEnvelope]]
    | None = None,
) -> Candidate:
    inventory, availability = _resource_envelopes(
        name, "cpu", (_atom("cpu", "shared", cpu),)
    )
    inventories = {"cpu": inventory}
    availabilities = {"cpu": availability}
    for kind, envelopes in (extra or {}).items():
        inventories[kind], availabilities[kind] = envelopes
    return Candidate(
        name,
        inventories,
        availabilities,
        attributes=dict(attributes or {}),
    )


def _request(kind: str = "cpu", amount: int = 1) -> ResolvedResourceRequest:
    unit = "B" if kind == "memory" else "count"
    return ResolvedResourceRequest(
        kind, ValidatedResourceEntryView(kind, ExactQuantity(amount), unit)
    )


def _work(
    name: str = "work",
    *,
    kind: str = "cpu",
    ready_at: int = 1,
    preferences: tuple[PreferenceSpec, ...] = (),
    hard: tuple[HardConstraintSpec, ...] = (),
) -> WorkItem:
    return WorkItem(
        name,
        ready_at,
        {kind: _request(kind)},
        hard_constraints=hard,
        preferences=preferences,
    )


class _ExhaustedPlanner:
    descriptor = _descriptor("slow")
    resource_kind = "slow"
    claim_contracts = (ResourceClaimContractDescriptor("slow", 1, "slow-v1"),)

    def resolve_request(self, authored, runtime):
        value = runtime or authored
        if value is None:
            return ResourceRequestResolution(ResourceResolutionState.ABSENT)
        return ResourceRequestResolution(
            ResourceResolutionState.RESOLVED,
            ResolvedResourceRequest("slow", value),
        )

    def validate_opportunity(self, inventory, availability):
        return _valid_opportunity(inventory, availability)

    def propose_claims(self, request, opportunity, budget):
        return ClaimSearchResult(ClaimSearchState.EXHAUSTED)

    def validate_claim(self, request, claim):
        return ClaimValidationResult(ClaimValidationState.VALID)


class _ConditionalExhaustedPlanner(CpuResourcePlanner):
    def propose_claims(self, request, opportunity, budget):
        if opportunity.data.get("exhausted") is True:
            return ClaimSearchResult(ClaimSearchState.EXHAUSTED)
        return super().propose_claims(request, opportunity, budget)


class _EpochCpuPlanner(CpuResourcePlanner):
    def __init__(self, version: str) -> None:
        self.version = version
        self.descriptor = replace(
            CpuResourcePlanner.descriptor,
            implementation_version=version,
            implementation_fingerprint=f"test:cpu:{version}",
        )

    def propose_claims(self, request, opportunity, budget):
        if opportunity.data.get("planner_version") != self.version:
            return ClaimSearchResult(ClaimSearchState.COMPLETE)
        return super().propose_claims(request, opportunity, budget)


class _OversizedClaimPlanner(CpuResourcePlanner):
    def propose_claims(self, request, opportunity, budget):
        return ClaimSearchResult(
            ClaimSearchState.COMPLETE,
            (
                ResourceClaim(
                    "cpu",
                    self.claim_contracts[0],
                    (_atom("cpu", "shared", 100),),
                    1,
                ),
            ),
        )


class _ScorePreference:
    descriptor = _descriptor("score")

    def evaluate(self, work, candidate, claims, spec):
        del work, claims
        scores = candidate.attributes.get("scores", {})
        assert isinstance(scores, Mapping)
        return PreferenceResult(
            PreferenceEvaluationState.SCORE,
            PreferenceScore(
                int(scores.get(spec.identifier, 0)),
                str(candidate.attributes.get("band", "preferred")),
            ),
        )


class _UnknownPolicy:
    descriptor = _descriptor("unknown-policy")

    def select(self, context: PolicyContext) -> PolicyDecision:
        return PolicyDecision(PolicyDecisionState.SELECT, "missing", "missing")


class _MutatingPreference:
    descriptor = _descriptor("mutating")

    def evaluate(self, work, candidate, claims, spec):
        del work, claims, spec
        candidate.attributes["changed"] = True  # type: ignore[index]
        return PreferenceResult(PreferenceEvaluationState.SCORE, PreferenceScore(0))


def _valid_opportunity(inventory, availability):
    return OpportunityValidationResult(
        OpportunityState.VALID,
        ValidatedResourceOpportunity(
            inventory.candidate_id,
            inventory.resource_kind,
            inventory.snapshot_revision,
            availability.data,
            availability.atoms,
        ),
    )


def test_exact_quantity_and_component_data_are_exact_and_immutable() -> None:
    assert ExactQuantity(2, 4) == ExactQuantity(1, 2)
    assert ExactQuantity.from_dict(ExactQuantity(3, 2).to_dict()) == ExactQuantity(3, 2)
    with pytest.raises(SchedulingError):
        ExactQuantity(1.5)  # type: ignore[arg-type]
    with pytest.raises(SchedulingError, match="positive"):
        ValidatedResourceEntryView("cpu", ExactQuantity(0), "count")
    with pytest.raises(SchedulingError, match="callable"):
        Candidate("a", {}, {}, attributes={"bad": lambda: None})  # type: ignore[dict-item]


def test_component_registry_freezes_active_and_retained_identity() -> None:
    registry = ComponentRegistry(epoch_id="epoch-1")
    planner = CpuResourcePlanner()
    registry.register(planner)
    registry.register(planner)  # exact composition replay is harmless
    registry.freeze()

    assert registry.active("cpu") is planner
    assert registry.retained(planner.descriptor) is planner
    with pytest.raises(SchedulingError, match="frozen"):
        registry.register(MemoryResourcePlanner())
    drifted = SchedulingComponentDescriptor("cpu", 1, "2", "different", "test")
    with pytest.raises(SchedulingError, match="unavailable"):
        registry.retained(drifted)


def test_kernel_selects_a_complete_claim_deterministically() -> None:
    kernel = SchedulingKernel(
        planners={"cpu": CpuResourcePlanner()},
        policy=FifoSchedulingPolicy(),
    )
    decision = kernel.decide(
        work=(_work(),), candidates=(_candidate("b"), _candidate("a")), as_of=1
    )

    assert decision.state is PolicyDecisionState.SELECT
    assert (decision.stage_work_id, decision.candidate_id) == ("work", "a")
    assert decision.selected is not None
    assert decision.selected.claims[0].atoms[0].amount == ExactQuantity(1)


def test_kernel_can_evaluate_mixed_epoch_work_with_exact_planner_bindings() -> None:
    old_planner = _EpochCpuPlanner("old")
    new_planner = _EpochCpuPlanner("new")
    old_inventory, old_availability = _resource_envelopes(
        "old-agent",
        "cpu",
        (_atom("cpu", "old", 4),),
        data={"planner_version": "old"},
    )
    new_inventory, new_availability = _resource_envelopes(
        "new-agent",
        "cpu",
        (_atom("cpu", "new", 4),),
        data={"planner_version": "new"},
    )
    kernel = SchedulingKernel(
        planners={"cpu": new_planner},
        work_planners={
            "old-work": {"cpu": old_planner},
            "new-work": {"cpu": new_planner},
        },
        policy=FifoSchedulingPolicy(),
        component_epoch="epoch-2",
    )

    decision = kernel.decide(
        work=(_work("old-work", ready_at=1), _work("new-work", ready_at=2)),
        candidates=(
            Candidate(
                "old-agent",
                {"cpu": old_inventory},
                {"cpu": old_availability},
            ),
            Candidate(
                "new-agent",
                {"cpu": new_inventory},
                {"cpu": new_availability},
            ),
        ),
        as_of=2,
    )

    assert decision.state is PolicyDecisionState.SELECT
    assert (decision.stage_work_id, decision.candidate_id) == (
        "old-work",
        "old-agent",
    )
    assert tuple(
        evaluation.candidates[0].candidate_id
        for evaluation in decision.work_evaluations
    ) == ("old-agent", "new-agent")


def test_complete_claim_products_are_permutation_stable_and_composite_bounded() -> None:
    cpu_atoms = (_atom("cpu", "b", 1), _atom("cpu", "a", 1))
    cpu_inventory, cpu_availability = _resource_envelopes("agent", "cpu", cpu_atoms)
    memory_atoms = (
        _atom("memory", "b", 1, "B"),
        _atom("memory", "a", 1, "B"),
    )
    memory_inventory, memory_availability = _resource_envelopes(
        "agent", "memory", memory_atoms
    )
    candidate = Candidate(
        "agent",
        {"cpu": cpu_inventory, "memory": memory_inventory},
        {"cpu": cpu_availability, "memory": memory_availability},
    )
    kernel = SchedulingKernel(
        planners={"cpu": CpuResourcePlanner()}, policy=FifoSchedulingPolicy()
    )
    first = kernel.decide(work=(_work(),), candidates=(candidate,), as_of=1)

    reversed_inventory, reversed_availability = _resource_envelopes(
        "agent", "cpu", tuple(reversed(cpu_atoms))
    )
    second = kernel.decide(
        work=(_work(),),
        candidates=(
            Candidate(
                "agent",
                {"cpu": reversed_inventory},
                {"cpu": reversed_availability},
            ),
        ),
        as_of=1,
    )
    assert first.selected is not None and second.selected is not None
    assert first.selected.stable_claim_key == second.selected.stable_claim_key

    bounded = SchedulingKernel(
        planners={"cpu": CpuResourcePlanner(), "memory": MemoryResourcePlanner()},
        policy=FifoSchedulingPolicy(),
        limits=SchedulingLimits(max_composite_candidates=3),
    ).decide(
        work=(
            WorkItem(
                "composite",
                1,
                {"cpu": _request("cpu"), "memory": _request("memory")},
            ),
        ),
        candidates=(candidate,),
        as_of=1,
    )
    assert bounded.state is PolicyDecisionState.WAIT
    assert bounded.work_evaluations[0].state is WorkSearchState.EXHAUSTED


def test_exhausted_earlier_work_is_visible_and_safely_bypassed() -> None:
    slow_envelopes = _resource_envelopes("a", "slow", (_atom("slow", "slow", 1),))
    kernel = SchedulingKernel(
        planners={"slow": _ExhaustedPlanner(), "cpu": CpuResourcePlanner()},
        policy=FifoSchedulingPolicy(),
    )
    decision = kernel.decide(
        work=(
            _work("first", kind="slow", ready_at=1),
            _work("second", ready_at=2),
        ),
        candidates=(_candidate("a", extra={"slow": slow_envelopes}),),
        as_of=2,
    )

    assert decision.state is PolicyDecisionState.SELECT
    assert decision.stage_work_id == "second"
    assert decision.work_evaluations[0].state is WorkSearchState.EXHAUSTED
    assert decision.work_evaluations[0].candidates == ()


def test_one_exhausted_candidate_discards_partial_candidates_for_that_work() -> None:
    candidate_a = _candidate("a")
    inventory, availability = _resource_envelopes(
        "b", "cpu", (_atom("cpu", "shared", 4),), data={"exhausted": True}
    )
    candidate_b = Candidate("b", {"cpu": inventory}, {"cpu": availability})
    kernel = SchedulingKernel(
        planners={"cpu": _ConditionalExhaustedPlanner()},
        policy=FifoSchedulingPolicy(),
    )

    decision = kernel.decide(
        work=(_work(),), candidates=(candidate_a, candidate_b), as_of=1
    )

    assert decision.state is PolicyDecisionState.WAIT
    assert decision.work_evaluations[0].state is WorkSearchState.EXHAUSTED
    assert decision.work_evaluations[0].candidates == ()


def test_claim_outside_available_atoms_fails_closed() -> None:
    kernel = SchedulingKernel(
        planners={"cpu": _OversizedClaimPlanner()},
        policy=FifoSchedulingPolicy(),
    )

    decision = kernel.decide(work=(_work(),), candidates=(_candidate("a"),), as_of=1)

    assert decision.state is PolicyDecisionState.WAIT
    assert decision.work_evaluations[0].state is WorkSearchState.INVALID
    assert "exceeds" in decision.explanations[0].message


def test_hard_rules_and_policy_result_validation_cannot_be_bypassed() -> None:
    target = TargetConstraintEvaluator()
    hard = HardConstraintSpec(
        "target-1", "target", {"target": "machine-b"}, target.descriptor
    )
    kernel = SchedulingKernel(
        planners={"cpu": CpuResourcePlanner()},
        hard_evaluators={"target": target},
        policy=_UnknownPolicy(),
    )
    rejected = kernel.decide(
        work=(_work(hard=(hard,)),),
        candidates=(_candidate("a", attributes={"target": "machine-a"}),),
        as_of=1,
    )
    assert rejected.state is PolicyDecisionState.WAIT

    unknown = SchedulingKernel(
        planners={"cpu": CpuResourcePlanner()}, policy=_UnknownPolicy()
    ).decide(work=(_work(),), candidates=(_candidate("a"),), as_of=1)
    assert unknown.state is PolicyDecisionState.WAIT
    assert unknown.explanations[0].code == "scheduling.policy_selection_invalid"


def test_pool_and_target_are_mandatory_kernel_checks() -> None:
    decision = SchedulingKernel(planners={}, policy=FifoSchedulingPolicy()).decide(
        work=(
            WorkItem(
                "work",
                1,
                {},
                pool_name="pool-b",
                target="machine-b",
            ),
        ),
        candidates=(
            Candidate("machine-0", {}, {}, pool_names=("pool-a",)),
            Candidate("machine-a", {}, {}, pool_names=("pool-b",)),
            Candidate("machine-b", {}, {}, pool_names=("pool-b",)),
        ),
        as_of=1,
    )

    assert decision.state is PolicyDecisionState.SELECT
    assert decision.candidate_id == "machine-b"


def test_site_tiers_dominate_lower_tiers_and_fallback_uses_snapshot_time() -> None:
    scorer = _ScorePreference()
    tier_zero = PreferenceSpec(
        "tier-zero", "score", tier=0, descriptor=scorer.descriptor
    )
    tier_one = PreferenceSpec("tier-one", "score", tier=1, descriptor=scorer.descriptor)
    fallback = PreferenceSpec(
        "fallback",
        "score",
        tier=0,
        fallback_after_seconds=5,
        quality_bands=("preferred", "fallback"),
        fallback_band="fallback",
        descriptor=scorer.descriptor,
    )
    kernel = SchedulingKernel(
        planners={"cpu": CpuResourcePlanner()},
        preference_scorers={"score": scorer},
        policy=FifoSchedulingPolicy(),
    )
    decision = kernel.decide(
        work=(_work(preferences=(tier_zero, tier_one)),),
        candidates=(
            _candidate("a", attributes={"scores": {"tier-zero": 0, "tier-one": 100}}),
            _candidate("b", attributes={"scores": {"tier-zero": 1, "tier-one": 0}}),
        ),
        as_of=1,
    )
    assert decision.candidate_id == "b"

    gated = kernel.decide(
        work=(_work(ready_at=10, preferences=(fallback,)),),
        candidates=(
            _candidate(
                "a", attributes={"scores": {"fallback": 10}, "band": "fallback"}
            ),
        ),
        as_of=14,
    )
    assert gated.state is PolicyDecisionState.WAIT
    released = kernel.decide(
        work=(_work(ready_at=10, preferences=(fallback,)),),
        candidates=(
            _candidate(
                "a", attributes={"scores": {"fallback": 10}, "band": "fallback"}
            ),
        ),
        as_of=15,
    )
    assert released.state is PolicyDecisionState.SELECT


def test_preference_overflow_and_mutation_attempts_are_typed_waits() -> None:
    scorer = _ScorePreference()
    overflow = PreferenceSpec(
        "overflow",
        "score",
        weight=4,
        utility_min=-(2**63),
        utility_max=2**63 - 1,
        descriptor=scorer.descriptor,
    )
    kernel = SchedulingKernel(
        planners={"cpu": CpuResourcePlanner()},
        preference_scorers={"score": scorer},
        policy=FifoSchedulingPolicy(),
    )
    decision = kernel.decide(
        work=(_work(preferences=(overflow,)),),
        candidates=(_candidate("a", attributes={"scores": {"overflow": 2**62}}),),
        as_of=1,
    )
    assert decision.state is PolicyDecisionState.WAIT
    assert "overflow" in decision.explanations[0].message

    mutating = _MutatingPreference()
    mutation = SchedulingKernel(
        planners={"cpu": CpuResourcePlanner()},
        preference_scorers={"mutating": mutating},
        policy=FifoSchedulingPolicy(),
    ).decide(
        work=(
            _work(
                preferences=(
                    PreferenceSpec(
                        "mutation", "mutating", descriptor=mutating.descriptor
                    ),
                )
            ),
        ),
        candidates=(_candidate("a"),),
        as_of=1,
    )
    assert mutation.state is PolicyDecisionState.WAIT
    assert "TypeError" in mutation.explanations[0].message


def test_runtime_placement_preserves_minima_route_and_fingerprint() -> None:
    authored = ResourceRequest(entries={"cpu": ResourceEntry("cpu", 2, "count")})
    with pytest.raises(RuntimeResourceError, match="weakens"):
        resolve_stage_placement(
            authored=authored,
            runtime=ResourceRequest(entries={"cpu": ResourceEntry("cpu", 1, "count")}),
            policy=StagePlacementPolicy(),
            planners={"cpu": CpuResourcePlanner()},
        )

    managed = resolve_stage_placement(
        authored=authored,
        runtime=ResourceRequest(entries={"cpu": ResourceEntry("cpu", 3, "count")}),
        policy=StagePlacementPolicy(pool_name="training"),
        planners={"cpu": CpuResourcePlanner()},
    )
    slurm = resolve_stage_placement(
        authored=authored,
        runtime=None,
        policy=StagePlacementPolicy(
            pool_name="training",
            route=ExecutionRoute(
                ExecutionRouteKind.SLURM,
                "gpu",
                SchedulingComponentDescriptor(
                    kind="slurm_profile",
                    contract_version=1,
                    implementation_version="1",
                    implementation_fingerprint="profile-implementation",
                    configuration_fingerprint="profile-fingerprint",
                ),
                "profile-fingerprint",
            ),
        ),
        planners={"cpu": CpuResourcePlanner()},
    )

    assert managed.resource_request.entries["cpu"].amount == 3
    assert managed.route.kind is ExecutionRouteKind.MANAGED_AGENT
    assert managed.fingerprint != slurm.fingerprint
    assert "max_parallel_stages" not in managed.to_dict()
    assert ResolvedStagePlacement.from_dict(managed.to_dict()) == managed
    legacy = managed.to_dict()
    legacy["schema_version"] = 1
    legacy["route"] = {
        "kind": "slurm",
        "profile_name": "gpu",
        "profile_fingerprint": "profile-fingerprint",
    }
    with pytest.raises(RuntimeResourceError, match="fields are unsupported"):
        ResolvedStagePlacement.from_dict(legacy)
    with pytest.raises(RuntimeResourceError, match="explicit profile"):
        ExecutionRoute(ExecutionRouteKind.SLURM)


def test_runtime_placement_rejects_malformed_planner_resolution() -> None:
    class MalformedResolutionPlanner(CpuResourcePlanner):
        def resolve_request(self, authored, runtime) -> ResourceRequestResolution:
            del authored, runtime
            return cast(ResourceRequestResolution, object())

    with pytest.raises(RuntimeResourceError, match="invalid request resolution"):
        resolve_stage_placement(
            authored=ResourceRequest(entries={"cpu": ResourceEntry("cpu", 1, "count")}),
            runtime=None,
            policy=StagePlacementPolicy(),
            planners={"cpu": MalformedResolutionPlanner()},
        )


def test_runtime_resource_adapter_normalizes_memory_and_preserves_attributes() -> None:
    view = scheduling_entry_view(
        ResourceEntry("memory", 2, "MiB", {"mode": "resident"})
    )
    assert (view.amount, view.unit) == (ExactQuantity(2 * 1024**2), "B")
    assert view.attributes == {"mode": "resident"}
