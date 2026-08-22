"""Structural extension protocols for the pure scheduling subsystem."""

# ruff: noqa: F403, F405
from __future__ import annotations
from typing import Protocol, runtime_checkable
from .values import *


@runtime_checkable
class ResourcePlanner(Protocol):
    descriptor: SchedulingComponentDescriptor
    resource_kind: str
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def resolve_request(
        self,
        authored: ValidatedResourceEntryView | None,
        runtime: ValidatedResourceEntryView | None,
    ) -> ResourceRequestResolution: ...
    def validate_opportunity(
        self,
        inventory: ResourceInventoryEnvelope,
        availability: ResourceAvailabilityEnvelope,
    ) -> OpportunityValidationResult: ...
    def propose_claims(
        self,
        request: ResolvedResourceRequest,
        opportunity: ValidatedResourceOpportunity,
        budget: ClaimSearchBudget,
    ) -> ClaimSearchResult: ...
    def validate_claim(
        self, request: ResolvedResourceRequest, claim: ResourceClaim
    ) -> ClaimValidationResult: ...


@runtime_checkable
class HardConstraintEvaluator(Protocol):
    descriptor: SchedulingComponentDescriptor

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: HardConstraintSpec,
    ) -> HardConstraintResult: ...


@runtime_checkable
class PreferenceScorer(Protocol):
    descriptor: SchedulingComponentDescriptor

    def evaluate(
        self,
        work: WorkItem,
        candidate: Candidate,
        claims: tuple[ResourceClaim, ...],
        spec: PreferenceSpec,
    ) -> PreferenceResult: ...


@runtime_checkable
class SchedulingPolicy(Protocol):
    descriptor: SchedulingComponentDescriptor

    def select(self, context: PolicyContext) -> PolicyDecision: ...
