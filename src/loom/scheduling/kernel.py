"""The single pure scheduling kernel.  It only validates and selects proposals."""
# ruff: noqa: F403, F405

from __future__ import annotations
from collections.abc import Mapping, Sequence
from itertools import product
from .protocols import (
    HardConstraintEvaluator,
    PreferenceScorer,
    ResourcePlanner,
    SchedulingPolicy,
)
from .values import *


class SchedulingKernel:
    def __init__(
        self,
        *,
        planners: Mapping[str, ResourcePlanner],
        hard_evaluators: Mapping[str, HardConstraintEvaluator] = {},
        preference_scorers: Mapping[str, PreferenceScorer] = {},
        policy: SchedulingPolicy,
        claim_budget: ClaimSearchBudget = ClaimSearchBudget(64),
    ) -> None:
        self._planners, self._hard, self._preference, self._policy, self._budget = (
            dict(planners),
            dict(hard_evaluators),
            dict(preference_scorers),
            policy,
            claim_budget,
        )

    def decide(
        self, *, work: Sequence[WorkItem], candidates: Sequence[Candidate], as_of: int
    ) -> PolicyDecision:
        evaluations: list[WorkEvaluation] = []
        for item in sorted(
            work, key=lambda value: (value.ready_at, value.stage_work_id)
        ):
            for candidate in sorted(candidates, key=lambda value: value.candidate_id):
                result = self._evaluate(item, candidate, as_of)
                if result is not None:
                    evaluations.append(result)
        context = PolicyContext(as_of=as_of, evaluations=tuple(evaluations))
        try:
            decision = self._policy.select(context)
        except Exception:
            return PolicyDecision(PolicyDecisionState.WAIT, explanation="policy failed")
        if not isinstance(decision, PolicyDecision):
            return PolicyDecision(
                PolicyDecisionState.WAIT, explanation="invalid policy result"
            )
        if decision.state is PolicyDecisionState.WAIT:
            return decision
        if any(
            item.stage_work_id == decision.stage_work_id
            and item.candidate_id == decision.candidate_id
            for item in evaluations
        ):
            return decision
        return PolicyDecision(
            PolicyDecisionState.WAIT,
            explanation="policy selected unknown work or candidate",
        )

    def _evaluate(
        self, work: WorkItem, candidate: Candidate, as_of: int
    ) -> WorkEvaluation | None:
        groups: list[tuple[ResourceClaim, ...]] = []
        for kind, request in sorted(work.requests.items()):
            planner = self._planners.get(kind)
            if planner is None or kind not in candidate.inventory:
                return None
            try:
                opportunity = planner.validate_opportunity(
                    candidate.inventory[kind], candidate.availability[kind]
                )
                if (
                    not isinstance(opportunity, OpportunityValidationResult)
                    or opportunity.state is not OpportunityState.VALID
                    or opportunity.opportunity is None
                ):
                    return None
                search = planner.propose_claims(
                    request, opportunity.opportunity, self._budget
                )
                if (
                    not isinstance(search, ClaimSearchResult)
                    or search.state is not ClaimSearchState.COMPLETE
                ):
                    return None
                if len(search.claims) > self._budget.max_claims:
                    return None
                valid = []
                for claim in search.claims:
                    if claim.resource_kind != kind:
                        return None
                    checked = planner.validate_claim(request, claim)
                    if (
                        isinstance(checked, ClaimValidationResult)
                        and checked.state is ClaimValidationState.VALID
                    ):
                        valid.append(claim)
                if not valid:
                    return None
                groups.append(tuple(valid))
            except Exception:
                return None
        for claims in product(*groups) if groups else [()]:
            claim_tuple = tuple(claims)
            for spec in work.hard_constraints:
                evaluator = self._hard.get(spec.evaluator)
                if evaluator is None:
                    return None
                try:
                    hard = evaluator.evaluate(work, candidate, claim_tuple, spec)
                except Exception:
                    return None
                if (
                    not isinstance(hard, HardConstraintResult)
                    or hard.state is not HardEvaluationState.PASS
                ):
                    return None
            scores: dict[int, int] = {}
            for spec in work.preferences:
                scorer = self._preference.get(spec.scorer)
                if scorer is None:
                    return None
                try:
                    preference = scorer.evaluate(work, candidate, claim_tuple, spec)
                except Exception:
                    return None
                if (
                    not isinstance(preference, PreferenceResult)
                    or preference.state is not PreferenceEvaluationState.SCORE
                    or preference.score is None
                ):
                    return None
                if (
                    spec.fallback_after_seconds is not None
                    and preference.score.quality_band == "fallback"
                    and as_of < work.ready_at + spec.fallback_after_seconds
                ):
                    return None
                scores[spec.tier] = _checked_add(
                    scores.get(spec.tier, 0),
                    _checked_multiply(spec.weight, preference.score.utility),
                )
            vector = tuple(
                scores.get(index, 0) for index in range(max(scores, default=-1) + 1)
            )
            return WorkEvaluation(
                work.stage_work_id,
                candidate.candidate_id,
                claim_tuple,
                vector,
                work.ready_at,
            )
        return None


def _checked_add(left: int, right: int) -> int:
    value = left + right
    if not -(2**63) <= value < 2**63:
        raise SchedulingError("preference arithmetic overflow")
    return value


def _checked_multiply(left: int, right: int) -> int:
    value = left * right
    if not -(2**63) <= value < 2**63:
        raise SchedulingError("preference arithmetic overflow")
    return value
