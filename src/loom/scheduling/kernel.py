"""The fixed pure scheduling kernel for already-ready managed work."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from math import prod
from typing import TypeVar, cast

from .protocols import (
    HardConstraintEvaluator,
    PreferenceScorer,
    ResourcePlanner,
    SchedulingPolicy,
)
from .values import (
    Candidate,
    CandidateEvaluation,
    CapacityAtom,
    ClaimSearchBudget,
    ClaimSearchResult,
    ClaimSearchState,
    ClaimValidationResult,
    ClaimValidationState,
    EligibilityState,
    HardConstraintResult,
    HardEvaluationState,
    OpportunityState,
    OpportunityValidationResult,
    PolicyContext,
    PolicyDecision,
    PolicyDecisionState,
    PreferenceEvaluationState,
    PreferenceResult,
    ResourceAvailabilityEnvelope,
    ResourceClaim,
    ResourceInventoryEnvelope,
    SchedulingComponentDescriptor,
    SchedulingDecision,
    SchedulingError,
    SchedulingExplanation,
    SchedulingLimits,
    SchedulingSnapshot,
    WorkEvaluation,
    WorkItem,
    WorkSearchState,
)

_MIN_SCORE = -(2**63)
_MAX_SCORE = 2**63 - 1
_ComponentT = TypeVar("_ComponentT")


@dataclass(frozen=True, slots=True)
class _CandidateResult:
    state: WorkSearchState
    evaluation: CandidateEvaluation | None = None
    explanation: str | None = None


class SchedulingKernel:
    """Validate a complete bounded snapshot and select without mutation."""

    def __init__(
        self,
        *,
        planners: Mapping[str, ResourcePlanner],
        policy: SchedulingPolicy,
        hard_evaluators: Mapping[str, HardConstraintEvaluator] | None = None,
        preference_scorers: Mapping[str, PreferenceScorer] | None = None,
        work_planners: Mapping[str, Mapping[str, ResourcePlanner]] | None = None,
        work_hard_evaluators: Mapping[str, Mapping[str, HardConstraintEvaluator]]
        | None = None,
        work_preference_scorers: Mapping[str, Mapping[str, PreferenceScorer]]
        | None = None,
        limits: SchedulingLimits | None = None,
        claim_budget: ClaimSearchBudget | None = None,
        component_epoch: str = "default",
    ) -> None:
        if not isinstance(component_epoch, str) or not component_epoch:
            raise SchedulingError("component_epoch is required")
        self._limits = limits or SchedulingLimits()
        self._claim_budget = claim_budget or ClaimSearchBudget(
            self._limits.max_claims_per_resource
        )
        self._component_epoch = component_epoch
        self._planners = dict(planners)
        self._hard = dict(hard_evaluators or {})
        self._preference = dict(preference_scorers or {})
        self._work_planners = _copy_work_component_mappings(work_planners)
        self._work_hard = _copy_work_component_mappings(work_hard_evaluators)
        self._work_preference = _copy_work_component_mappings(work_preference_scorers)
        self._policy = policy
        self._validate_components()

    def decide(
        self,
        *,
        work: Sequence[WorkItem],
        candidates: Sequence[Candidate],
        as_of: int,
    ) -> SchedulingDecision:
        return self.decide_snapshot(
            SchedulingSnapshot(
                as_of=as_of,
                work=tuple(work),
                candidates=tuple(candidates),
                component_epoch=self._component_epoch,
            )
        )

    def decide_snapshot(self, snapshot: SchedulingSnapshot) -> SchedulingDecision:
        if not isinstance(snapshot, SchedulingSnapshot):
            raise SchedulingError("decide_snapshot requires SchedulingSnapshot")
        if snapshot.component_epoch != self._component_epoch:
            return self._wait(
                (), "scheduling.component_epoch_mismatch", "component epoch mismatch"
            )
        if len(snapshot.work) > self._limits.max_work_items:
            return self._wait((), "scheduling.work_limit", "work item limit exceeded")
        if len(snapshot.candidates) > self._limits.max_candidates:
            return self._wait(
                (), "scheduling.candidate_limit", "candidate limit exceeded"
            )

        evaluations = tuple(
            self._evaluate_work(item, snapshot.candidates, snapshot.as_of)
            for item in sorted(snapshot.work, key=lambda value: value.order_key)
        )
        invalid = next(
            (value for value in evaluations if value.state is WorkSearchState.INVALID),
            None,
        )
        if invalid is not None:
            return self._wait(
                evaluations,
                "scheduling.invalid_evaluation",
                invalid.explanations[0]
                if invalid.explanations
                else "component evaluation was invalid",
            )

        context = PolicyContext(as_of=snapshot.as_of, evaluations=evaluations)
        try:
            decision = self._policy.select(context)
        except Exception as exc:
            return self._wait(
                evaluations,
                "scheduling.policy_exception",
                f"policy raised {type(exc).__name__}",
            )
        if not isinstance(decision, PolicyDecision):
            return self._wait(
                evaluations,
                "scheduling.policy_output_invalid",
                "policy returned an invalid result",
            )
        if decision.state is PolicyDecisionState.WAIT:
            return self._wait(
                evaluations,
                "scheduling.policy_wait",
                decision.explanation or "policy selected wait",
            )

        selected = _find_selected(
            evaluations,
            stage_work_id=decision.stage_work_id,
            candidate_id=decision.candidate_id,
        )
        if selected is None:
            return self._wait(
                evaluations,
                "scheduling.policy_selection_invalid",
                "policy selected an unknown or incomplete work/candidate pair",
            )
        return SchedulingDecision(
            state=PolicyDecisionState.SELECT,
            stage_work_id=selected.stage_work_id,
            candidate_id=selected.candidate_id,
            selected=selected,
            work_evaluations=evaluations,
            policy_descriptor=self._policy.descriptor,
            component_epoch=self._component_epoch,
        )

    def _evaluate_work(
        self, work: WorkItem, candidates: Sequence[Candidate], as_of: int
    ) -> WorkEvaluation:
        feasible: list[CandidateEvaluation] = []
        explanations: list[str] = []
        exhausted = False
        for candidate in sorted(candidates, key=lambda value: value.candidate_id):
            result = self._evaluate_candidate(work, candidate, as_of)
            if result.state is WorkSearchState.INVALID:
                return WorkEvaluation(
                    work,
                    WorkSearchState.INVALID,
                    explanations=(
                        result.explanation or "candidate evaluation invalid",
                    ),
                )
            if result.state is WorkSearchState.EXHAUSTED:
                exhausted = True
                explanations.append(result.explanation or "candidate search exhausted")
                continue
            if result.evaluation is not None:
                feasible.append(result.evaluation)
        if exhausted:
            return WorkEvaluation(
                work,
                WorkSearchState.EXHAUSTED,
                explanations=tuple(explanations) or ("work search exhausted",),
            )
        return WorkEvaluation(
            work,
            WorkSearchState.COMPLETE,
            candidates=tuple(feasible),
            explanations=tuple(explanations),
        )

    def _evaluate_candidate(
        self, work: WorkItem, candidate: Candidate, as_of: int
    ) -> _CandidateResult:
        if work.pool_name not in candidate.pool_names:
            return _CandidateResult(WorkSearchState.COMPLETE)
        candidate_target = candidate.attributes.get("agent_id", candidate.candidate_id)
        if work.target is not None and work.target != candidate_target:
            return _CandidateResult(WorkSearchState.COMPLETE)
        for check in candidate.mandatory_eligibility:
            if check.state is EligibilityState.INDETERMINATE:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=check.explanation
                    or f"mandatory check {check.code} is indeterminate",
                )
            if check.state is EligibilityState.REJECT:
                return _CandidateResult(WorkSearchState.COMPLETE)

        claim_groups: list[tuple[ResourceClaim, ...]] = []
        planners = self._work_planners.get(work.stage_work_id, self._planners)
        for kind, request in sorted(work.requests.items()):
            planner = planners.get(kind)
            if planner is None:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"no planner is active for {kind}",
                )
            inventory = candidate.inventory.get(kind)
            availability = candidate.availability.get(kind)
            if inventory is None or availability is None:
                return _CandidateResult(WorkSearchState.COMPLETE)
            envelope_error = _validate_envelopes(planner, inventory, availability)
            if envelope_error is not None:
                return _CandidateResult(
                    WorkSearchState.INVALID, explanation=envelope_error
                )
            try:
                opportunity = planner.validate_opportunity(inventory, availability)
            except Exception as exc:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"planner opportunity validation raised {type(exc).__name__}",
                )
            if not isinstance(opportunity, OpportunityValidationResult):
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation="planner returned an invalid opportunity result",
                )
            if opportunity.state is OpportunityState.INVALID:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=opportunity.explanation
                    or "resource opportunity is invalid",
                )
            assert opportunity.opportunity is not None
            if (
                opportunity.opportunity.candidate_id != candidate.candidate_id
                or opportunity.opportunity.resource_kind != kind
                or opportunity.opportunity.snapshot_revision
                != inventory.snapshot_revision
            ):
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation="planner changed opportunity identity",
                )
            try:
                search = planner.propose_claims(
                    request, opportunity.opportunity, self._claim_budget
                )
            except Exception as exc:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"planner claim search raised {type(exc).__name__}",
                )
            if not isinstance(search, ClaimSearchResult):
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation="planner returned an invalid claim-search result",
                )
            if search.state is ClaimSearchState.EXHAUSTED:
                return _CandidateResult(
                    WorkSearchState.EXHAUSTED,
                    explanation=search.explanation or f"{kind} claim search exhausted",
                )
            if len(search.claims) > self._claim_budget.max_claims:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"{kind} planner exceeded its claim budget",
                )
            if not search.claims:
                return _CandidateResult(WorkSearchState.COMPLETE)
            valid_claims: list[ResourceClaim] = []
            for claim in search.claims:
                claim_error = _validate_claim_envelope(
                    planner, claim, opportunity.opportunity.available_atoms
                )
                if claim_error is not None:
                    return _CandidateResult(
                        WorkSearchState.INVALID, explanation=claim_error
                    )
                try:
                    checked = planner.validate_claim(request, claim)
                except Exception as exc:
                    return _CandidateResult(
                        WorkSearchState.INVALID,
                        explanation=f"planner claim validation raised {type(exc).__name__}",
                    )
                if (
                    not isinstance(checked, ClaimValidationResult)
                    or checked.state is not ClaimValidationState.VALID
                ):
                    return _CandidateResult(
                        WorkSearchState.INVALID,
                        explanation=(
                            checked.explanation
                            if isinstance(checked, ClaimValidationResult)
                            else "planner returned an invalid claim-validation result"
                        ),
                    )
                valid_claims.append(claim)
            claim_groups.append(tuple(valid_claims))

        product_size = prod(len(group) for group in claim_groups) if claim_groups else 1
        if product_size > self._limits.max_composite_candidates:
            return _CandidateResult(
                WorkSearchState.EXHAUSTED,
                explanation="composite claim search exhausted",
            )

        placements: list[CandidateEvaluation] = []
        for claims in product(*claim_groups) if claim_groups else [()]:
            evaluated = self._evaluate_complete_placement(
                work, candidate, tuple(claims), as_of
            )
            if evaluated.state is WorkSearchState.INVALID:
                return evaluated
            if evaluated.evaluation is not None:
                placements.append(evaluated.evaluation)
        if not placements:
            return _CandidateResult(WorkSearchState.COMPLETE)
        best = min(
            placements,
            key=lambda value: (
                tuple(-score for score in value.preference_vector),
                value.stable_claim_key,
            ),
        )
        return _CandidateResult(WorkSearchState.COMPLETE, evaluation=best)

    def _evaluate_complete_placement(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        as_of: int,
    ) -> _CandidateResult:
        atom_keys = [atom.key for claim in claims for atom in claim.atoms]
        if len(atom_keys) != len(set(atom_keys)):
            return _CandidateResult(
                WorkSearchState.INVALID,
                explanation="composite placement duplicates a capacity atom",
            )
        hard_evaluators = self._work_hard.get(work.stage_work_id, self._hard)
        for spec in work.hard_constraints:
            evaluator = hard_evaluators.get(spec.evaluator)
            if evaluator is None or spec.descriptor is None:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"hard constraint {spec.identifier} is unresolved",
                )
            if evaluator.descriptor != spec.descriptor:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"hard constraint {spec.identifier} descriptor drifted",
                )
            try:
                result = evaluator.evaluate(work, candidate, claims, spec)
            except Exception as exc:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"hard evaluator raised {type(exc).__name__}",
                )
            if not isinstance(result, HardConstraintResult):
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation="hard evaluator returned an invalid result",
                )
            if result.state is HardEvaluationState.INDETERMINATE:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=result.explanation
                    or "hard evaluation is indeterminate",
                )
            if result.state is HardEvaluationState.REJECT:
                return _CandidateResult(WorkSearchState.COMPLETE)

        scores: dict[int, int] = {}
        fallback_eligible = False
        preference_scorers = self._work_preference.get(
            work.stage_work_id, self._preference
        )
        for spec in work.preferences:
            scorer = preference_scorers.get(spec.scorer)
            if scorer is None or spec.descriptor is None:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"preference {spec.identifier} is unresolved",
                )
            if scorer.descriptor != spec.descriptor:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"preference {spec.identifier} descriptor drifted",
                )
            try:
                result = scorer.evaluate(work, candidate, claims, spec)
            except Exception as exc:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"preference scorer raised {type(exc).__name__}",
                )
            if (
                not isinstance(result, PreferenceResult)
                or result.state is not PreferenceEvaluationState.SCORE
                or result.score is None
            ):
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation="preference scorer returned an invalid result",
                )
            score = result.score
            if not spec.utility_min <= score.utility <= spec.utility_max:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"preference {spec.identifier} utility is out of bounds",
                )
            if score.quality_band not in spec.quality_bands:
                return _CandidateResult(
                    WorkSearchState.INVALID,
                    explanation=f"preference {spec.identifier} returned an unknown band",
                )
            is_fallback = (
                spec.fallback_band is not None
                and score.quality_band == spec.fallback_band
            )
            if is_fallback:
                if as_of < work.ready_at + cast(int, spec.fallback_after_seconds):
                    return _CandidateResult(WorkSearchState.COMPLETE)
                fallback_eligible = True
            try:
                scores[spec.tier] = _checked_add(
                    scores.get(spec.tier, 0),
                    _checked_multiply(spec.weight, score.utility),
                )
            except SchedulingError as exc:
                return _CandidateResult(WorkSearchState.INVALID, explanation=str(exc))
        vector = tuple(
            scores.get(index, 0) for index in range(max(scores, default=-1) + 1)
        )
        return _CandidateResult(
            WorkSearchState.COMPLETE,
            evaluation=CandidateEvaluation(
                stage_work_id=work.stage_work_id,
                candidate_id=candidate.candidate_id,
                claims=claims,
                preference_vector=vector,
                fallback_eligible=fallback_eligible,
            ),
        )

    def _wait(
        self,
        evaluations: Sequence[WorkEvaluation],
        code: str,
        message: str,
    ) -> SchedulingDecision:
        return SchedulingDecision(
            state=PolicyDecisionState.WAIT,
            stage_work_id=None,
            candidate_id=None,
            selected=None,
            work_evaluations=tuple(evaluations),
            policy_descriptor=self._policy.descriptor,
            component_epoch=self._component_epoch,
            explanations=(SchedulingExplanation(code=code, message=message),),
        )

    def _validate_components(self) -> None:
        if not isinstance(self._policy, SchedulingPolicy):
            raise SchedulingError("policy does not satisfy SchedulingPolicy")
        _validate_planner_mapping(self._planners)
        _validate_component_mapping(
            self._hard, HardConstraintEvaluator, "hard evaluator"
        )
        _validate_component_mapping(
            self._preference, PreferenceScorer, "preference scorer"
        )
        for planners in self._work_planners.values():
            _validate_planner_mapping(planners)
        for hard_evaluators in self._work_hard.values():
            _validate_component_mapping(
                hard_evaluators, HardConstraintEvaluator, "hard evaluator"
            )
        for preference_scorers in self._work_preference.values():
            _validate_component_mapping(
                preference_scorers, PreferenceScorer, "preference scorer"
            )


def _copy_work_component_mappings(
    values: Mapping[str, Mapping[str, _ComponentT]] | None,
) -> dict[str, dict[str, _ComponentT]]:
    result: dict[str, dict[str, _ComponentT]] = {}
    for stage_work_id, components in (values or {}).items():
        if not isinstance(stage_work_id, str) or not stage_work_id:
            raise SchedulingError("work component binding requires stage_work_id")
        result[stage_work_id] = dict(components)
    return result


def _validate_planner_mapping(values: Mapping[str, object]) -> None:
    for kind, planner in values.items():
        if not isinstance(planner, ResourcePlanner):
            raise SchedulingError(f"planner {kind!r} does not satisfy ResourcePlanner")
        if planner.resource_kind != kind or planner.descriptor.kind != kind:
            raise SchedulingError(f"planner {kind!r} identity is inconsistent")
        if not planner.claim_contracts:
            raise SchedulingError(f"planner {kind!r} has no claim contract")
        if any(contract.kind != kind for contract in planner.claim_contracts):
            raise SchedulingError(f"planner {kind!r} claim contract is inconsistent")


def _validate_component_mapping(
    values: Mapping[str, object], protocol: type[object], label: str
) -> None:
    for kind, component in values.items():
        if not isinstance(component, protocol):
            raise SchedulingError(f"{label} {kind!r} does not satisfy its protocol")
        descriptor = getattr(component, "descriptor")
        if (
            not isinstance(descriptor, SchedulingComponentDescriptor)
            or descriptor.kind != kind
        ):
            raise SchedulingError(f"{label} {kind!r} identity is inconsistent")


def _validate_envelopes(
    planner: ResourcePlanner,
    inventory: ResourceInventoryEnvelope,
    availability: ResourceAvailabilityEnvelope,
) -> str | None:
    if inventory.snapshot_revision != availability.snapshot_revision:
        return "inventory and availability revisions do not match"
    supported = planner.descriptor.supported_data_versions
    if (
        inventory.data_version not in supported
        or availability.data_version not in supported
    ):
        return "resource opportunity data version is unsupported"
    inventory_atoms = {atom.key: atom for atom in inventory.atoms}
    for atom in availability.atoms:
        total = inventory_atoms.get(atom.key)
        if total is None:
            return "availability contains an atom absent from inventory"
        if atom.unit != total.unit or atom.granularity != total.granularity:
            return "availability atom unit or granularity differs from inventory"
        if atom.amount.fraction > total.amount.fraction:
            return "availability atom exceeds configured inventory"
    return None


def _validate_claim_envelope(
    planner: ResourcePlanner,
    claim: ResourceClaim,
    available_atoms: Sequence[CapacityAtom],
) -> str | None:
    if claim.resource_kind != planner.resource_kind:
        return "planner returned a claim in another resource namespace"
    if claim.contract not in planner.claim_contracts:
        return "planner returned an unregistered claim contract"
    available = {atom.key: atom for atom in available_atoms}
    for atom in claim.atoms:
        bound = available.get(atom.key)
        if bound is None:
            return "claim references an unavailable capacity atom"
        if atom.unit != bound.unit or atom.granularity != bound.granularity:
            return "claim atom unit or granularity differs from availability"
        if atom.amount.fraction > bound.amount.fraction:
            return "claim exceeds an available capacity atom"
    return None


def _find_selected(
    evaluations: Sequence[WorkEvaluation],
    *,
    stage_work_id: str | None,
    candidate_id: str | None,
) -> CandidateEvaluation | None:
    for work in evaluations:
        if (
            work.state is not WorkSearchState.COMPLETE
            or work.stage_work_id != stage_work_id
        ):
            continue
        for candidate in work.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
    return None


def _checked_add(left: int, right: int) -> int:
    value = left + right
    if not _MIN_SCORE <= value <= _MAX_SCORE:
        raise SchedulingError("preference arithmetic overflow")
    return value


def _checked_multiply(left: int, right: int) -> int:
    value = left * right
    if not _MIN_SCORE <= value <= _MAX_SCORE:
        raise SchedulingError("preference arithmetic overflow")
    return value


__all__ = ["SchedulingKernel"]
