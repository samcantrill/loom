"""Immutable, dependency-light values used at the scheduling boundary.

These values deliberately describe snapshots and proposals only.  They do not
hold a store, a clock, a provider, or a callable selected from durable data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from types import MappingProxyType
from typing import Any


class SchedulingError(ValueError):
    """Raised when a scheduling boundary value is malformed."""


@dataclass(frozen=True, slots=True, order=True)
class ExactQuantity:
    """A normalized exact rational quantity (never a float)."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or not isinstance(self.numerator, int):
            raise SchedulingError("ExactQuantity.numerator must be an integer")
        if (
            isinstance(self.denominator, bool)
            or not isinstance(self.denominator, int)
            or self.denominator <= 0
        ):
            raise SchedulingError(
                "ExactQuantity.denominator must be a positive integer"
            )
        value = Fraction(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)

    @classmethod
    def integer(cls, value: int) -> "ExactQuantity":
        return cls(value)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def __add__(self, other: object) -> "ExactQuantity":
        if not isinstance(other, ExactQuantity):
            return NotImplemented
        value = self.fraction + other.fraction
        return ExactQuantity(value.numerator, value.denominator)

    def __sub__(self, other: object) -> "ExactQuantity":
        if not isinstance(other, ExactQuantity):
            return NotImplemented
        value = self.fraction - other.fraction
        return ExactQuantity(value.numerator, value.denominator)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SchedulingError(f"{name} must be a non-empty string")
    return value


def _mapping(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchedulingError(f"{name} must be a mapping")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class SchedulingComponentDescriptor:
    kind: str
    contract_version: int
    implementation_version: str
    implementation_fingerprint: str
    configuration_fingerprint: str
    supported_data_versions: tuple[int, ...] = (1,)

    def __post_init__(self) -> None:
        _text(self.kind, "descriptor.kind")
        _text(self.implementation_version, "descriptor.implementation_version")
        _text(self.implementation_fingerprint, "descriptor.implementation_fingerprint")
        _text(self.configuration_fingerprint, "descriptor.configuration_fingerprint")
        if (
            not isinstance(self.contract_version, int)
            or isinstance(self.contract_version, bool)
            or self.contract_version <= 0
        ):
            raise SchedulingError("descriptor.contract_version must be positive")
        versions = tuple(self.supported_data_versions)
        if not versions or any(
            not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in versions
        ):
            raise SchedulingError(
                "descriptor.supported_data_versions must contain positive integers"
            )
        object.__setattr__(self, "supported_data_versions", versions)

    @property
    def key(self) -> tuple[str, int, str, str, str]:
        return (
            self.kind,
            self.contract_version,
            self.implementation_version,
            self.implementation_fingerprint,
            self.configuration_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class ResourceClaimContractDescriptor:
    kind: str
    contract_version: int
    fingerprint: str
    supported_data_versions: tuple[int, ...] = (1,)

    def __post_init__(self) -> None:
        _text(self.kind, "claim contract kind")
        _text(self.fingerprint, "claim contract fingerprint")
        if (
            not isinstance(self.contract_version, int)
            or isinstance(self.contract_version, bool)
            or self.contract_version <= 0
        ):
            raise SchedulingError("claim contract version must be positive")
        versions = tuple(self.supported_data_versions)
        if not versions or any(
            not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in versions
        ):
            raise SchedulingError("claim contract supported data versions are invalid")
        object.__setattr__(self, "supported_data_versions", versions)


@dataclass(frozen=True, slots=True)
class ValidatedResourceEntryView:
    kind: str
    amount: ExactQuantity
    unit: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.kind, "resource entry kind")
        if not isinstance(self.amount, ExactQuantity):
            raise SchedulingError("resource entry amount must be ExactQuantity")
        if self.unit is not None:
            _text(self.unit, "resource entry unit")
        object.__setattr__(
            self, "attributes", _mapping(self.attributes, "resource entry attributes")
        )


@dataclass(frozen=True, slots=True)
class ResolvedResourceRequest:
    resource_kind: str
    entry: ValidatedResourceEntryView

    def __post_init__(self) -> None:
        _text(self.resource_kind, "resolved resource kind")
        if self.entry.kind != self.resource_kind:
            raise SchedulingError("resolved resource kind must match entry kind")


class ResourceResolutionState(str, Enum):
    ABSENT = "absent"
    RESOLVED = "resolved"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ResourceRequestResolution:
    state: ResourceResolutionState
    request: ResolvedResourceRequest | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        if self.state is ResourceResolutionState.RESOLVED and self.request is None:
            raise SchedulingError("resolved resource result requires a request")
        if (
            self.state is not ResourceResolutionState.RESOLVED
            and self.request is not None
        ):
            raise SchedulingError("only resolved resource result may contain a request")


@dataclass(frozen=True, slots=True)
class ResourceInventoryEnvelope:
    candidate_id: str
    resource_kind: str
    snapshot_revision: str
    data_version: int = 1
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.candidate_id, "inventory candidate_id")
        _text(self.resource_kind, "inventory resource_kind")
        _text(self.snapshot_revision, "inventory snapshot_revision")
        object.__setattr__(self, "data", _mapping(self.data, "inventory data"))


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityEnvelope:
    candidate_id: str
    resource_kind: str
    snapshot_revision: str
    data_version: int = 1
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.candidate_id, "availability candidate_id")
        _text(self.resource_kind, "availability resource_kind")
        _text(self.snapshot_revision, "availability snapshot_revision")
        object.__setattr__(self, "data", _mapping(self.data, "availability data"))


@dataclass(frozen=True, slots=True)
class ValidatedResourceOpportunity:
    candidate_id: str
    resource_kind: str
    snapshot_revision: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.candidate_id, "opportunity candidate_id")
        _text(self.resource_kind, "opportunity resource_kind")
        _text(self.snapshot_revision, "opportunity snapshot_revision")
        object.__setattr__(self, "data", _mapping(self.data, "opportunity data"))


class OpportunityState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class OpportunityValidationResult:
    state: OpportunityState
    opportunity: ValidatedResourceOpportunity | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        if (self.state is OpportunityState.VALID) != (self.opportunity is not None):
            raise SchedulingError(
                "valid opportunity result must contain exactly one opportunity"
            )


@dataclass(frozen=True, slots=True)
class CapacityAtom:
    owner_resource_kind: str
    local_capacity_key: str
    amount: ExactQuantity
    unit: str
    granularity: ExactQuantity

    def __post_init__(self) -> None:
        _text(self.owner_resource_kind, "atom owner_resource_kind")
        _text(self.local_capacity_key, "atom local_capacity_key")
        _text(self.unit, "atom unit")
        if not isinstance(self.amount, ExactQuantity) or self.amount.fraction <= 0:
            raise SchedulingError("atom amount must be positive ExactQuantity")
        if (
            not isinstance(self.granularity, ExactQuantity)
            or self.granularity.fraction <= 0
        ):
            raise SchedulingError("atom granularity must be positive ExactQuantity")
        if self.amount.fraction % self.granularity.fraction:
            raise SchedulingError(
                "atom amount must be an exact multiple of granularity"
            )


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    resource_kind: str
    contract: ResourceClaimContractDescriptor
    atoms: tuple[CapacityAtom, ...]
    provider_data_version: int
    provider_data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.resource_kind, "claim resource_kind")
        if not isinstance(self.contract, ResourceClaimContractDescriptor):
            raise SchedulingError(
                "claim contract must be ResourceClaimContractDescriptor"
            )
        atoms = tuple(self.atoms)
        if not atoms or any(not isinstance(atom, CapacityAtom) for atom in atoms):
            raise SchedulingError(
                "claim atoms must be a non-empty tuple of CapacityAtom"
            )
        if any(atom.owner_resource_kind != self.resource_kind for atom in atoms):
            raise SchedulingError("claim atom namespace must match claim resource_kind")
        keys = [(atom.owner_resource_kind, atom.local_capacity_key) for atom in atoms]
        if len(keys) != len(set(keys)):
            raise SchedulingError("claim atoms must not duplicate capacity keys")
        if (
            not isinstance(self.provider_data_version, int)
            or self.provider_data_version <= 0
        ):
            raise SchedulingError("claim provider_data_version must be positive")
        object.__setattr__(self, "atoms", atoms)
        object.__setattr__(
            self, "provider_data", _mapping(self.provider_data, "claim provider_data")
        )


class ClaimSearchState(str, Enum):
    COMPLETE = "complete"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class ClaimSearchBudget:
    max_claims: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_claims, int)
            or isinstance(self.max_claims, bool)
            or self.max_claims <= 0
        ):
            raise SchedulingError("claim search budget must be positive")


@dataclass(frozen=True, slots=True)
class ClaimSearchResult:
    state: ClaimSearchState
    claims: tuple[ResourceClaim, ...] = ()
    explanation: str | None = None

    def __post_init__(self) -> None:
        claims = tuple(self.claims)
        if any(not isinstance(claim, ResourceClaim) for claim in claims):
            raise SchedulingError(
                "claim search claims must contain ResourceClaim values"
            )
        if self.state is ClaimSearchState.EXHAUSTED and claims:
            raise SchedulingError(
                "exhausted claim search may not present partial claims"
            )
        object.__setattr__(self, "claims", claims)


class ClaimValidationState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ClaimValidationResult:
    state: ClaimValidationState
    explanation: str | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    inventory: Mapping[str, ResourceInventoryEnvelope]
    availability: Mapping[str, ResourceAvailabilityEnvelope]
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id")
        inventory = dict(self.inventory)
        availability = dict(self.availability)
        if set(inventory) != set(availability):
            raise SchedulingError(
                "candidate inventory and availability resource kinds must match"
            )
        if any(
            value.candidate_id != self.candidate_id or key != value.resource_kind
            for key, value in inventory.items()
        ):
            raise SchedulingError("candidate inventory is inconsistent")
        if any(
            value.candidate_id != self.candidate_id or key != value.resource_kind
            for key, value in availability.items()
        ):
            raise SchedulingError("candidate availability is inconsistent")
        object.__setattr__(self, "inventory", MappingProxyType(inventory))
        object.__setattr__(self, "availability", MappingProxyType(availability))
        object.__setattr__(
            self, "attributes", _mapping(self.attributes, "candidate attributes")
        )


class HardEvaluationState(str, Enum):
    PASS = "pass"
    REJECT = "reject"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class HardConstraintResult:
    state: HardEvaluationState
    explanation: str | None = None


class PreferenceEvaluationState(str, Enum):
    SCORE = "score"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class PreferenceScore:
    utility: int
    quality_band: str = "preferred"

    def __post_init__(self) -> None:
        if not isinstance(self.utility, int) or isinstance(self.utility, bool):
            raise SchedulingError("preference utility must be an integer")
        _text(self.quality_band, "preference quality_band")


@dataclass(frozen=True, slots=True)
class PreferenceResult:
    state: PreferenceEvaluationState
    score: PreferenceScore | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        if (self.state is PreferenceEvaluationState.SCORE) != (self.score is not None):
            raise SchedulingError(
                "score result must contain exactly one preference score"
            )


@dataclass(frozen=True, slots=True)
class HardConstraintSpec:
    identifier: str
    evaluator: str

    def __post_init__(self) -> None:
        _text(self.identifier, "hard constraint identifier")
        _text(self.evaluator, "hard constraint evaluator")


@dataclass(frozen=True, slots=True)
class PreferenceSpec:
    identifier: str
    scorer: str
    tier: int = 0
    weight: int = 1
    fallback_after_seconds: int | None = None

    def __post_init__(self) -> None:
        _text(self.identifier, "preference identifier")
        _text(self.scorer, "preference scorer")
        if (
            not isinstance(self.tier, int)
            or self.tier < 0
            or not isinstance(self.weight, int)
            or self.weight < 0
        ):
            raise SchedulingError(
                "preference tier and weight must be non-negative integers"
            )
        if self.fallback_after_seconds is not None and (
            not isinstance(self.fallback_after_seconds, int)
            or self.fallback_after_seconds < 0
        ):
            raise SchedulingError(
                "preference fallback_after_seconds must be non-negative"
            )


@dataclass(frozen=True, slots=True)
class WorkItem:
    stage_work_id: str
    ready_at: int
    requests: Mapping[str, ResolvedResourceRequest]
    hard_constraints: tuple[HardConstraintSpec, ...] = ()
    preferences: tuple[PreferenceSpec, ...] = ()

    def __post_init__(self) -> None:
        _text(self.stage_work_id, "stage_work_id")
        if not isinstance(self.ready_at, int):
            raise SchedulingError("ready_at must be an integer snapshot time")
        requests = dict(self.requests)
        if any(key != request.resource_kind for key, request in requests.items()):
            raise SchedulingError("work request keys must match resource kind")
        object.__setattr__(self, "requests", MappingProxyType(requests))
        object.__setattr__(self, "hard_constraints", tuple(self.hard_constraints))
        object.__setattr__(self, "preferences", tuple(self.preferences))


@dataclass(frozen=True, slots=True)
class WorkEvaluation:
    stage_work_id: str
    candidate_id: str
    claims: tuple[ResourceClaim, ...]
    preference_vector: tuple[int, ...]
    explanations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.stage_work_id, "evaluation stage_work_id")
        _text(self.candidate_id, "evaluation candidate_id")
        object.__setattr__(self, "claims", tuple(self.claims))
        object.__setattr__(self, "preference_vector", tuple(self.preference_vector))


@dataclass(frozen=True, slots=True)
class PolicyContext:
    as_of: int
    evaluations: tuple[WorkEvaluation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, int):
            raise SchedulingError("policy context as_of must be an integer")
        object.__setattr__(self, "evaluations", tuple(self.evaluations))


class PolicyDecisionState(str, Enum):
    SELECT = "select"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    state: PolicyDecisionState
    stage_work_id: str | None = None
    candidate_id: str | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        selected = self.stage_work_id is not None or self.candidate_id is not None
        if self.state is PolicyDecisionState.SELECT and (
            not self.stage_work_id or not self.candidate_id
        ):
            raise SchedulingError(
                "select decision requires work and candidate identity"
            )
        if self.state is PolicyDecisionState.WAIT and selected:
            raise SchedulingError("wait decision must not name work or candidate")
