"""Immutable, dependency-light values for pure managed-stage scheduling."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType
from typing import cast

from loom.serialization import (
    PlainData,
    freeze_plain_data,
    stable_json_dumps,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError

SCHEDULING_DATA_VERSION = 1
MAX_COMPONENT_DATA_BYTES = 8_192
MAX_EXPLANATION_LENGTH = 1_024


class SchedulingError(ValueError):
    """Raised when scheduling boundary data is malformed."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SchedulingError(f"{name} must be a non-empty string")
    return value


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SchedulingError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SchedulingError(f"{name} must be a non-negative integer")
    return value


def _plain_mapping(
    value: Mapping[str, PlainData], name: str, *, bounded: bool = False
) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=name)
        plain = thaw_plain_data(frozen, path=name)
    except PlainDataError as exc:
        raise SchedulingError(str(exc)) from exc
    if not isinstance(plain, dict):
        raise SchedulingError(f"{name} must be a mapping")
    if (
        bounded
        and len(stable_json_dumps(plain).encode("utf-8")) > MAX_COMPONENT_DATA_BYTES
    ):
        raise SchedulingError(f"{name} exceeds {MAX_COMPONENT_DATA_BYTES} bytes")
    return cast(Mapping[str, PlainData], frozen)


def _plain(mapping: Mapping[str, PlainData], name: str) -> dict[str, PlainData]:
    value = thaw_plain_data(mapping, path=name)
    if not isinstance(value, dict):  # pragma: no cover - guarded by construction
        raise SchedulingError(f"{name} must be a mapping")
    return value


def _explanation(value: str | None) -> str | None:
    if value is None:
        return None
    _text(value, "explanation")
    if len(value) > MAX_EXPLANATION_LENGTH:
        raise SchedulingError(
            f"explanation must not exceed {MAX_EXPLANATION_LENGTH} characters"
        )
    return value


@dataclass(frozen=True, slots=True, order=True)
class ExactQuantity:
    """A normalized exact rational quantity; floats never cross this boundary."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or not isinstance(self.numerator, int):
            raise SchedulingError("ExactQuantity.numerator must be an integer")
        _positive_int(self.denominator, "ExactQuantity.denominator")
        value = Fraction(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)

    @classmethod
    def integer(cls, value: int) -> ExactQuantity:
        return cls(value)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def __add__(self, other: object) -> ExactQuantity:
        if not isinstance(other, ExactQuantity):
            return NotImplemented
        value = self.fraction + other.fraction
        return ExactQuantity(value.numerator, value.denominator)

    def __sub__(self, other: object) -> ExactQuantity:
        if not isinstance(other, ExactQuantity):
            return NotImplemented
        value = self.fraction - other.fraction
        return ExactQuantity(value.numerator, value.denominator)

    def to_dict(self) -> dict[str, PlainData]:
        return {"numerator": self.numerator, "denominator": self.denominator}

    @classmethod
    def from_dict(cls, data: object) -> ExactQuantity:
        mapping = _object_mapping(data, "ExactQuantity")
        _reject_unknown(mapping, {"numerator", "denominator"}, "ExactQuantity")
        return cls(
            cast(int, _required(mapping, "numerator", "ExactQuantity")),
            cast(int, mapping.get("denominator", 1)),
        )


@dataclass(frozen=True, slots=True)
class SchedulingComponentDescriptor:
    kind: str
    contract_version: int
    implementation_version: str
    implementation_fingerprint: str
    configuration_fingerprint: str
    supported_data_versions: tuple[int, ...] = (SCHEDULING_DATA_VERSION,)

    def __post_init__(self) -> None:
        _text(self.kind, "descriptor.kind")
        _positive_int(self.contract_version, "descriptor.contract_version")
        _text(self.implementation_version, "descriptor.implementation_version")
        _text(self.implementation_fingerprint, "descriptor.implementation_fingerprint")
        _text(self.configuration_fingerprint, "descriptor.configuration_fingerprint")
        versions = tuple(sorted(set(self.supported_data_versions)))
        if not versions:
            raise SchedulingError(
                "descriptor.supported_data_versions must not be empty"
            )
        for version in versions:
            _positive_int(version, "descriptor.supported_data_versions entry")
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

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "contract_version": self.contract_version,
            "implementation_version": self.implementation_version,
            "implementation_fingerprint": self.implementation_fingerprint,
            "configuration_fingerprint": self.configuration_fingerprint,
            "supported_data_versions": list(self.supported_data_versions),
        }

    @classmethod
    def from_dict(cls, data: object) -> SchedulingComponentDescriptor:
        mapping = _object_mapping(data, "SchedulingComponentDescriptor")
        _reject_unknown(
            mapping,
            {
                "kind",
                "contract_version",
                "implementation_version",
                "implementation_fingerprint",
                "configuration_fingerprint",
                "supported_data_versions",
            },
            "SchedulingComponentDescriptor",
        )
        return cls(
            kind=cast(str, _required(mapping, "kind", "SchedulingComponentDescriptor")),
            contract_version=cast(
                int,
                _required(mapping, "contract_version", "SchedulingComponentDescriptor"),
            ),
            implementation_version=cast(
                str,
                _required(
                    mapping, "implementation_version", "SchedulingComponentDescriptor"
                ),
            ),
            implementation_fingerprint=cast(
                str,
                _required(
                    mapping,
                    "implementation_fingerprint",
                    "SchedulingComponentDescriptor",
                ),
            ),
            configuration_fingerprint=cast(
                str,
                _required(
                    mapping,
                    "configuration_fingerprint",
                    "SchedulingComponentDescriptor",
                ),
            ),
            supported_data_versions=tuple(
                cast(Sequence[int], mapping.get("supported_data_versions", (1,)))
            ),
        )


@dataclass(frozen=True, slots=True)
class ResourceClaimContractDescriptor:
    kind: str
    contract_version: int
    fingerprint: str
    supported_data_versions: tuple[int, ...] = (SCHEDULING_DATA_VERSION,)

    def __post_init__(self) -> None:
        _text(self.kind, "claim contract kind")
        _positive_int(self.contract_version, "claim contract version")
        _text(self.fingerprint, "claim contract fingerprint")
        versions = tuple(sorted(set(self.supported_data_versions)))
        if not versions:
            raise SchedulingError("claim contract supported data versions are empty")
        for version in versions:
            _positive_int(version, "claim contract supported data version")
        object.__setattr__(self, "supported_data_versions", versions)

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.kind, self.contract_version, self.fingerprint)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "contract_version": self.contract_version,
            "fingerprint": self.fingerprint,
            "supported_data_versions": list(self.supported_data_versions),
        }

    @classmethod
    def from_dict(cls, data: object) -> ResourceClaimContractDescriptor:
        mapping = _object_mapping(data, "ResourceClaimContractDescriptor")
        return cls(
            kind=cast(
                str, _required(mapping, "kind", "ResourceClaimContractDescriptor")
            ),
            contract_version=cast(
                int,
                _required(
                    mapping, "contract_version", "ResourceClaimContractDescriptor"
                ),
            ),
            fingerprint=cast(
                str,
                _required(mapping, "fingerprint", "ResourceClaimContractDescriptor"),
            ),
            supported_data_versions=tuple(
                cast(Sequence[int], mapping.get("supported_data_versions", (1,)))
            ),
        )


@dataclass(frozen=True, slots=True)
class ValidatedResourceEntryView:
    kind: str
    amount: ExactQuantity
    unit: str | None = None
    attributes: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.kind, "resource entry kind")
        if not isinstance(self.amount, ExactQuantity):
            raise SchedulingError("resource entry amount must be ExactQuantity")
        if self.amount.fraction <= 0:
            raise SchedulingError("resource entry amount must be positive")
        if self.unit is not None:
            _text(self.unit, "resource entry unit")
        object.__setattr__(
            self,
            "attributes",
            _plain_mapping(self.attributes, "resource entry attributes", bounded=True),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind,
            "amount": self.amount.to_dict(),
            "unit": self.unit,
            "attributes": _plain(self.attributes, "resource entry attributes"),
        }


@dataclass(frozen=True, slots=True)
class ResolvedResourceRequest:
    resource_kind: str
    entry: ValidatedResourceEntryView

    def __post_init__(self) -> None:
        _text(self.resource_kind, "resolved resource kind")
        if not isinstance(self.entry, ValidatedResourceEntryView):
            raise SchedulingError("resolved request entry is invalid")
        if self.entry.kind != self.resource_kind:
            raise SchedulingError("resolved resource kind must match entry kind")


class ResourceResolutionState(StrEnum):
    ABSENT = "absent"
    RESOLVED = "resolved"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ResourceRequestResolution:
    state: ResourceResolutionState
    request: ResolvedResourceRequest | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", ResourceResolutionState(self.state))
        if (self.state is ResourceResolutionState.RESOLVED) != (
            self.request is not None
        ):
            raise SchedulingError("resolved result must contain exactly one request")
        object.__setattr__(self, "explanation", _explanation(self.explanation))


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

    @property
    def key(self) -> tuple[str, str]:
        return (self.owner_resource_kind, self.local_capacity_key)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "owner_resource_kind": self.owner_resource_kind,
            "local_capacity_key": self.local_capacity_key,
            "amount": self.amount.to_dict(),
            "unit": self.unit,
            "granularity": self.granularity.to_dict(),
        }


def _atoms(values: Sequence[CapacityAtom], name: str) -> tuple[CapacityAtom, ...]:
    atoms = tuple(values)
    if any(not isinstance(atom, CapacityAtom) for atom in atoms):
        raise SchedulingError(f"{name} must contain CapacityAtom values")
    keys = [atom.key for atom in atoms]
    if len(keys) != len(set(keys)):
        raise SchedulingError(f"{name} must not duplicate capacity keys")
    return atoms


@dataclass(frozen=True, slots=True)
class ResourceInventoryEnvelope:
    candidate_id: str
    resource_kind: str
    snapshot_revision: str
    data_version: int = SCHEDULING_DATA_VERSION
    data: Mapping[str, PlainData] = field(default_factory=dict)
    atoms: tuple[CapacityAtom, ...] = ()

    def __post_init__(self) -> None:
        _text(self.candidate_id, "inventory candidate_id")
        _text(self.resource_kind, "inventory resource_kind")
        _text(self.snapshot_revision, "inventory snapshot_revision")
        _positive_int(self.data_version, "inventory data_version")
        object.__setattr__(
            self, "data", _plain_mapping(self.data, "inventory data", bounded=True)
        )
        atoms = _atoms(self.atoms, "inventory atoms")
        if any(atom.owner_resource_kind != self.resource_kind for atom in atoms):
            raise SchedulingError("inventory atom namespace must match resource kind")
        object.__setattr__(self, "atoms", atoms)


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityEnvelope:
    candidate_id: str
    resource_kind: str
    snapshot_revision: str
    data_version: int = SCHEDULING_DATA_VERSION
    data: Mapping[str, PlainData] = field(default_factory=dict)
    atoms: tuple[CapacityAtom, ...] = ()

    def __post_init__(self) -> None:
        _text(self.candidate_id, "availability candidate_id")
        _text(self.resource_kind, "availability resource_kind")
        _text(self.snapshot_revision, "availability snapshot_revision")
        _positive_int(self.data_version, "availability data_version")
        object.__setattr__(
            self, "data", _plain_mapping(self.data, "availability data", bounded=True)
        )
        atoms = _atoms(self.atoms, "availability atoms")
        if any(atom.owner_resource_kind != self.resource_kind for atom in atoms):
            raise SchedulingError(
                "availability atom namespace must match resource kind"
            )
        object.__setattr__(self, "atoms", atoms)


@dataclass(frozen=True, slots=True)
class ValidatedResourceOpportunity:
    candidate_id: str
    resource_kind: str
    snapshot_revision: str
    data: Mapping[str, PlainData] = field(default_factory=dict)
    available_atoms: tuple[CapacityAtom, ...] = ()

    def __post_init__(self) -> None:
        _text(self.candidate_id, "opportunity candidate_id")
        _text(self.resource_kind, "opportunity resource_kind")
        _text(self.snapshot_revision, "opportunity snapshot_revision")
        object.__setattr__(
            self, "data", _plain_mapping(self.data, "opportunity data", bounded=True)
        )
        atoms = _atoms(self.available_atoms, "opportunity available_atoms")
        if any(atom.owner_resource_kind != self.resource_kind for atom in atoms):
            raise SchedulingError("opportunity atom namespace must match resource kind")
        object.__setattr__(self, "available_atoms", atoms)


class OpportunityState(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class OpportunityValidationResult:
    state: OpportunityState
    opportunity: ValidatedResourceOpportunity | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", OpportunityState(self.state))
        if (self.state is OpportunityState.VALID) != (self.opportunity is not None):
            raise SchedulingError("valid result must contain exactly one opportunity")
        object.__setattr__(self, "explanation", _explanation(self.explanation))


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    resource_kind: str
    contract: ResourceClaimContractDescriptor
    atoms: tuple[CapacityAtom, ...]
    provider_data_version: int
    provider_data: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.resource_kind, "claim resource_kind")
        if not isinstance(self.contract, ResourceClaimContractDescriptor):
            raise SchedulingError("claim contract is invalid")
        if self.contract.kind != self.resource_kind:
            raise SchedulingError("claim contract kind must match resource kind")
        atoms = _atoms(self.atoms, "claim atoms")
        if not atoms:
            raise SchedulingError("claim atoms must not be empty")
        if any(atom.owner_resource_kind != self.resource_kind for atom in atoms):
            raise SchedulingError("claim atom namespace must match resource kind")
        _positive_int(self.provider_data_version, "claim provider_data_version")
        if self.provider_data_version not in self.contract.supported_data_versions:
            raise SchedulingError("claim provider data version is not supported")
        object.__setattr__(self, "atoms", atoms)
        object.__setattr__(
            self,
            "provider_data",
            _plain_mapping(self.provider_data, "claim provider_data", bounded=True),
        )

    @property
    def fingerprint(self) -> str:
        payload = {
            "resource_kind": self.resource_kind,
            "contract": self.contract.to_dict(),
            "atoms": [atom.to_dict() for atom in self.atoms],
            "provider_data_version": self.provider_data_version,
            "provider_data": _plain(self.provider_data, "claim provider_data"),
        }
        return hashlib.sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()


class ClaimSearchState(StrEnum):
    COMPLETE = "complete"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class ClaimSearchBudget:
    max_claims: int
    max_expansions: int = 4_096

    def __post_init__(self) -> None:
        _positive_int(self.max_claims, "claim search budget")
        _positive_int(self.max_expansions, "claim search expansion budget")


@dataclass(frozen=True, slots=True)
class ClaimSearchResult:
    state: ClaimSearchState
    claims: tuple[ResourceClaim, ...] = ()
    explanation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", ClaimSearchState(self.state))
        claims = tuple(self.claims)
        if any(not isinstance(claim, ResourceClaim) for claim in claims):
            raise SchedulingError("claim search returned an invalid claim")
        if self.state is ClaimSearchState.EXHAUSTED and claims:
            raise SchedulingError("exhausted search must not expose partial claims")
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "explanation", _explanation(self.explanation))


class ClaimValidationState(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ClaimValidationResult:
    state: ClaimValidationState
    explanation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", ClaimValidationState(self.state))
        object.__setattr__(self, "explanation", _explanation(self.explanation))


class EligibilityState(StrEnum):
    PASS = "pass"
    REJECT = "reject"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class MandatoryEligibility:
    code: str
    state: EligibilityState
    explanation: str | None = None

    def __post_init__(self) -> None:
        _text(self.code, "mandatory eligibility code")
        object.__setattr__(self, "state", EligibilityState(self.state))
        object.__setattr__(self, "explanation", _explanation(self.explanation))


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: str
    inventory: Mapping[str, ResourceInventoryEnvelope]
    availability: Mapping[str, ResourceAvailabilityEnvelope]
    attributes: Mapping[str, PlainData] = field(default_factory=dict)
    mandatory_eligibility: tuple[MandatoryEligibility, ...] = ()
    pool_names: tuple[str, ...] = ("default",)

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id")
        inventory = dict(self.inventory)
        availability = dict(self.availability)
        if set(inventory) != set(availability):
            raise SchedulingError("inventory and availability kinds must match")
        for kind, envelope in inventory.items():
            if (
                not isinstance(envelope, ResourceInventoryEnvelope)
                or envelope.candidate_id != self.candidate_id
                or envelope.resource_kind != kind
            ):
                raise SchedulingError("candidate inventory is inconsistent")
        for kind, envelope in availability.items():
            if (
                not isinstance(envelope, ResourceAvailabilityEnvelope)
                or envelope.candidate_id != self.candidate_id
                or envelope.resource_kind != kind
            ):
                raise SchedulingError("candidate availability is inconsistent")
        eligibility = tuple(self.mandatory_eligibility)
        if any(not isinstance(item, MandatoryEligibility) for item in eligibility):
            raise SchedulingError("candidate mandatory eligibility is invalid")
        codes = [item.code for item in eligibility]
        if len(codes) != len(set(codes)):
            raise SchedulingError(
                "candidate mandatory eligibility codes must be unique"
            )
        pool_names = tuple(self.pool_names)
        if not pool_names or any(
            not isinstance(pool_name, str) or not pool_name for pool_name in pool_names
        ):
            raise SchedulingError("candidate pool names must be non-empty strings")
        if len(pool_names) != len(set(pool_names)):
            raise SchedulingError("candidate pool names must be unique")
        object.__setattr__(self, "inventory", MappingProxyType(inventory))
        object.__setattr__(self, "availability", MappingProxyType(availability))
        object.__setattr__(
            self,
            "attributes",
            _plain_mapping(self.attributes, "candidate attributes", bounded=True),
        )
        object.__setattr__(self, "mandatory_eligibility", eligibility)
        object.__setattr__(self, "pool_names", tuple(sorted(pool_names)))


class HardEvaluationState(StrEnum):
    PASS = "pass"
    REJECT = "reject"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class HardConstraintResult:
    state: HardEvaluationState
    explanation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", HardEvaluationState(self.state))
        object.__setattr__(self, "explanation", _explanation(self.explanation))


class PreferenceEvaluationState(StrEnum):
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
        object.__setattr__(self, "state", PreferenceEvaluationState(self.state))
        if (self.state is PreferenceEvaluationState.SCORE) != (self.score is not None):
            raise SchedulingError("score result must contain exactly one score")
        object.__setattr__(self, "explanation", _explanation(self.explanation))


@dataclass(frozen=True, slots=True)
class HardConstraintSpec:
    identifier: str
    evaluator: str
    data: Mapping[str, PlainData] = field(default_factory=dict)
    descriptor: SchedulingComponentDescriptor | None = None

    def __post_init__(self) -> None:
        _text(self.identifier, "hard constraint identifier")
        _text(self.evaluator, "hard constraint evaluator")
        object.__setattr__(
            self,
            "data",
            _plain_mapping(self.data, "hard constraint data", bounded=True),
        )
        if self.descriptor is not None and self.descriptor.kind != self.evaluator:
            raise SchedulingError("hard constraint descriptor does not match evaluator")


@dataclass(frozen=True, slots=True)
class PreferenceSpec:
    identifier: str
    scorer: str
    tier: int = 0
    weight: int = 1
    fallback_after_seconds: int | None = None
    data: Mapping[str, PlainData] = field(default_factory=dict)
    utility_min: int = -(2**31)
    utility_max: int = 2**31 - 1
    quality_bands: tuple[str, ...] = ("preferred",)
    fallback_band: str | None = None
    descriptor: SchedulingComponentDescriptor | None = None

    def __post_init__(self) -> None:
        _text(self.identifier, "preference identifier")
        _text(self.scorer, "preference scorer")
        _non_negative_int(self.tier, "preference tier")
        _non_negative_int(self.weight, "preference weight")
        if self.fallback_after_seconds is not None:
            _non_negative_int(
                self.fallback_after_seconds, "preference fallback_after_seconds"
            )
        if (
            not isinstance(self.utility_min, int)
            or isinstance(self.utility_min, bool)
            or not isinstance(self.utility_max, int)
            or isinstance(self.utility_max, bool)
            or self.utility_min > self.utility_max
        ):
            raise SchedulingError("preference utility range is invalid")
        bands = tuple(self.quality_bands)
        if not bands or any(not isinstance(band, str) or not band for band in bands):
            raise SchedulingError("preference quality bands are invalid")
        if len(bands) != len(set(bands)):
            raise SchedulingError("preference quality bands must be unique")
        if self.fallback_band is not None and self.fallback_band not in bands:
            raise SchedulingError("fallback band must be a declared quality band")
        if (self.fallback_after_seconds is None) != (self.fallback_band is None):
            raise SchedulingError(
                "fallback duration and band must be configured together"
            )
        object.__setattr__(self, "quality_bands", bands)
        object.__setattr__(
            self, "data", _plain_mapping(self.data, "preference data", bounded=True)
        )
        if self.descriptor is not None and self.descriptor.kind != self.scorer:
            raise SchedulingError("preference descriptor does not match scorer")


@dataclass(frozen=True, slots=True, order=True)
class WorkOrderKey:
    negative_priority: int
    enqueue_order: int
    ready_at: int
    topological_order: int
    stage_name: str
    attempt: int
    stage_work_id: str


@dataclass(frozen=True, slots=True)
class WorkItem:
    stage_work_id: str
    ready_at: int
    requests: Mapping[str, ResolvedResourceRequest]
    hard_constraints: tuple[HardConstraintSpec, ...] = ()
    preferences: tuple[PreferenceSpec, ...] = ()
    run_priority: int = 0
    enqueue_order: int = 0
    topological_order: int = 0
    stage_name: str = ""
    attempt: int = 1
    pool_name: str = "default"
    target: str | None = None

    def __post_init__(self) -> None:
        _text(self.stage_work_id, "stage_work_id")
        if not isinstance(self.ready_at, int) or isinstance(self.ready_at, bool):
            raise SchedulingError("ready_at must be an integer snapshot time")
        if not isinstance(self.run_priority, int) or isinstance(
            self.run_priority, bool
        ):
            raise SchedulingError("run_priority must be an integer")
        _non_negative_int(self.enqueue_order, "enqueue_order")
        _non_negative_int(self.topological_order, "topological_order")
        _positive_int(self.attempt, "attempt")
        _text(self.pool_name, "pool_name")
        if self.target is not None:
            _text(self.target, "target")
        requests = dict(self.requests)
        if any(
            not isinstance(request, ResolvedResourceRequest)
            or request.resource_kind != key
            for key, request in requests.items()
        ):
            raise SchedulingError("work request keys must match resource kind")
        hard = tuple(self.hard_constraints)
        preferences = tuple(self.preferences)
        if any(not isinstance(spec, HardConstraintSpec) for spec in hard):
            raise SchedulingError("work hard constraints are invalid")
        if any(not isinstance(spec, PreferenceSpec) for spec in preferences):
            raise SchedulingError("work preferences are invalid")
        stage_name = self.stage_name or self.stage_work_id
        _text(stage_name, "stage_name")
        object.__setattr__(self, "requests", MappingProxyType(requests))
        object.__setattr__(self, "hard_constraints", hard)
        object.__setattr__(self, "preferences", preferences)
        object.__setattr__(self, "stage_name", stage_name)

    @property
    def order_key(self) -> WorkOrderKey:
        return WorkOrderKey(
            -self.run_priority,
            self.enqueue_order,
            self.ready_at,
            self.topological_order,
            self.stage_name,
            self.attempt,
            self.stage_work_id,
        )


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    stage_work_id: str
    candidate_id: str
    claims: tuple[ResourceClaim, ...]
    preference_vector: tuple[int, ...]
    explanations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.stage_work_id, "evaluation stage_work_id")
        _text(self.candidate_id, "evaluation candidate_id")
        claims = tuple(self.claims)
        if any(not isinstance(claim, ResourceClaim) for claim in claims):
            raise SchedulingError("candidate evaluation claims are invalid")
        vector = tuple(self.preference_vector)
        if any(
            not isinstance(value, int) or isinstance(value, bool) for value in vector
        ):
            raise SchedulingError("preference vector must contain integers")
        explanations = tuple(self.explanations)
        for value in explanations:
            _explanation(value)
        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "preference_vector", vector)
        object.__setattr__(self, "explanations", explanations)

    @property
    def stable_claim_key(self) -> tuple[str, ...]:
        return tuple(claim.fingerprint for claim in self.claims)


class WorkSearchState(StrEnum):
    COMPLETE = "complete"
    EXHAUSTED = "exhausted"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class WorkEvaluation:
    work: WorkItem
    state: WorkSearchState
    candidates: tuple[CandidateEvaluation, ...] = ()
    explanations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.work, WorkItem):
            raise SchedulingError("work evaluation requires WorkItem")
        object.__setattr__(self, "state", WorkSearchState(self.state))
        candidates = tuple(self.candidates)
        if any(
            not isinstance(candidate, CandidateEvaluation)
            or candidate.stage_work_id != self.work.stage_work_id
            for candidate in candidates
        ):
            raise SchedulingError("work evaluation candidates are inconsistent")
        if self.state is not WorkSearchState.COMPLETE and candidates:
            raise SchedulingError(
                "incomplete work evaluation must not expose candidates"
            )
        explanations = tuple(self.explanations)
        for value in explanations:
            _explanation(value)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "explanations", explanations)

    @property
    def stage_work_id(self) -> str:
        return self.work.stage_work_id


@dataclass(frozen=True, slots=True)
class PolicyContext:
    as_of: int
    evaluations: tuple[WorkEvaluation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, int) or isinstance(self.as_of, bool):
            raise SchedulingError("policy context as_of must be an integer")
        evaluations = tuple(self.evaluations)
        if any(not isinstance(value, WorkEvaluation) for value in evaluations):
            raise SchedulingError("policy evaluations are invalid")
        object.__setattr__(self, "evaluations", evaluations)


class PolicyDecisionState(StrEnum):
    SELECT = "select"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    state: PolicyDecisionState
    stage_work_id: str | None = None
    candidate_id: str | None = None
    explanation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", PolicyDecisionState(self.state))
        selected = self.stage_work_id is not None or self.candidate_id is not None
        if self.state is PolicyDecisionState.SELECT and (
            not self.stage_work_id or not self.candidate_id
        ):
            raise SchedulingError(
                "select decision requires work and candidate identity"
            )
        if self.state is PolicyDecisionState.WAIT and selected:
            raise SchedulingError("wait decision must not name work or candidate")
        object.__setattr__(self, "explanation", _explanation(self.explanation))


@dataclass(frozen=True, slots=True)
class SchedulingExplanation:
    code: str
    message: str
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.code, "scheduling explanation code")
        _explanation(self.message)
        object.__setattr__(
            self,
            "detail",
            _plain_mapping(self.detail, "scheduling explanation detail", bounded=True),
        )


@dataclass(frozen=True, slots=True)
class SchedulingSnapshot:
    as_of: int
    work: tuple[WorkItem, ...]
    candidates: tuple[Candidate, ...]
    component_epoch: str

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, int) or isinstance(self.as_of, bool):
            raise SchedulingError("snapshot as_of must be an integer")
        _text(self.component_epoch, "snapshot component_epoch")
        work = tuple(self.work)
        candidates = tuple(self.candidates)
        if any(not isinstance(item, WorkItem) for item in work):
            raise SchedulingError("snapshot work is invalid")
        if any(not isinstance(item, Candidate) for item in candidates):
            raise SchedulingError("snapshot candidates are invalid")
        work_ids = [item.stage_work_id for item in work]
        candidate_ids = [item.candidate_id for item in candidates]
        if len(work_ids) != len(set(work_ids)):
            raise SchedulingError("snapshot work IDs must be unique")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise SchedulingError("snapshot candidate IDs must be unique")
        object.__setattr__(self, "work", work)
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True, slots=True)
class SchedulingDecision:
    state: PolicyDecisionState
    stage_work_id: str | None
    candidate_id: str | None
    selected: CandidateEvaluation | None
    work_evaluations: tuple[WorkEvaluation, ...]
    policy_descriptor: SchedulingComponentDescriptor
    component_epoch: str
    explanations: tuple[SchedulingExplanation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", PolicyDecisionState(self.state))
        if not isinstance(self.policy_descriptor, SchedulingComponentDescriptor):
            raise SchedulingError("decision policy descriptor is invalid")
        _text(self.component_epoch, "decision component_epoch")
        if self.state is PolicyDecisionState.SELECT:
            if (
                not self.stage_work_id
                or not self.candidate_id
                or self.selected is None
                or self.selected.stage_work_id != self.stage_work_id
                or self.selected.candidate_id != self.candidate_id
            ):
                raise SchedulingError("selected decision identity is inconsistent")
        elif (
            self.stage_work_id is not None
            or self.candidate_id is not None
            or self.selected is not None
        ):
            raise SchedulingError("wait decision must not contain a selection")
        object.__setattr__(self, "work_evaluations", tuple(self.work_evaluations))
        object.__setattr__(self, "explanations", tuple(self.explanations))


@dataclass(frozen=True, slots=True)
class SchedulingLimits:
    max_work_items: int = 256
    max_candidates: int = 256
    max_claims_per_resource: int = 64
    max_composite_candidates: int = 1_024

    def __post_init__(self) -> None:
        _positive_int(self.max_work_items, "max_work_items")
        _positive_int(self.max_candidates, "max_candidates")
        _positive_int(self.max_claims_per_resource, "max_claims_per_resource")
        _positive_int(self.max_composite_candidates, "max_composite_candidates")


def _object_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise SchedulingError(f"{name} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], key: str, name: str) -> object:
    if key not in mapping:
        raise SchedulingError(f"{name} is missing {key}")
    return mapping[key]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], name: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise SchedulingError(
            f"{name} has unknown field(s): {', '.join(sorted(unknown))}"
        )


__all__ = [
    "Candidate",
    "CandidateEvaluation",
    "CapacityAtom",
    "ClaimSearchBudget",
    "ClaimSearchResult",
    "ClaimSearchState",
    "ClaimValidationResult",
    "ClaimValidationState",
    "EligibilityState",
    "ExactQuantity",
    "HardConstraintResult",
    "HardConstraintSpec",
    "HardEvaluationState",
    "MandatoryEligibility",
    "MAX_COMPONENT_DATA_BYTES",
    "OpportunityState",
    "OpportunityValidationResult",
    "PolicyContext",
    "PolicyDecision",
    "PolicyDecisionState",
    "PreferenceEvaluationState",
    "PreferenceResult",
    "PreferenceScore",
    "PreferenceSpec",
    "ResolvedResourceRequest",
    "ResourceAvailabilityEnvelope",
    "ResourceClaim",
    "ResourceClaimContractDescriptor",
    "ResourceInventoryEnvelope",
    "ResourceRequestResolution",
    "ResourceResolutionState",
    "SCHEDULING_DATA_VERSION",
    "SchedulingComponentDescriptor",
    "SchedulingDecision",
    "SchedulingError",
    "SchedulingExplanation",
    "SchedulingLimits",
    "SchedulingSnapshot",
    "ValidatedResourceEntryView",
    "ValidatedResourceOpportunity",
    "WorkEvaluation",
    "WorkItem",
    "WorkOrderKey",
    "WorkSearchState",
]
