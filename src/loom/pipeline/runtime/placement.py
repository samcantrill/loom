"""Resolve one immutable per-stage placement without coordinator identity."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import (
    DEFAULT_RESOURCE_VALIDATOR_REGISTRY,
    ResourceEntry,
    ResourceRequest,
    ResourceValidatorRegistry,
)
from loom.scheduling import (
    HardConstraintSpec,
    PreferenceSpec,
    ResolvedResourceRequest,
    ResourcePlanner,
    ResourceRequestResolution,
    ResourceResolutionState,
    SchedulingComponentDescriptor,
    SchedulingLimits,
)
from loom.serialization import PlainData, stable_json_dumps

from .scheduling_resources import scheduling_entry_view

RESOLVED_STAGE_PLACEMENT_SCHEMA_VERSION = 2


class ExecutionRouteKind(StrEnum):
    MANAGED_AGENT = "managed_agent"
    SLURM = "slurm"


@dataclass(frozen=True, slots=True)
class ExecutionRoute:
    kind: ExecutionRouteKind = ExecutionRouteKind.MANAGED_AGENT
    profile_id: str | None = None
    profile_descriptor: SchedulingComponentDescriptor | None = None
    profile_configuration_fingerprint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ExecutionRouteKind(self.kind))
        if self.kind is ExecutionRouteKind.MANAGED_AGENT:
            if any(
                value is not None
                for value in (
                    self.profile_id,
                    self.profile_descriptor,
                    self.profile_configuration_fingerprint,
                )
            ):
                raise RuntimeResourceError(
                    "managed_agent route must not contain a SLURM profile"
                )
            return
        if (
            not isinstance(self.profile_id, str)
            or not self.profile_id
            or any(char.isspace() or ord(char) < 32 for char in self.profile_id)
            or not isinstance(self.profile_descriptor, SchedulingComponentDescriptor)
            or not isinstance(self.profile_configuration_fingerprint, str)
            or not self.profile_configuration_fingerprint
        ):
            raise RuntimeResourceError(
                "slurm route requires an explicit profile identity and descriptor"
            )
        if (
            self.profile_descriptor.configuration_fingerprint
            != self.profile_configuration_fingerprint
        ):
            raise RuntimeResourceError(
                "slurm route profile descriptor and configuration conflict"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind.value,
            "profile_id": self.profile_id,
            "profile_descriptor": (
                None
                if self.profile_descriptor is None
                else self.profile_descriptor.to_dict()
            ),
            "profile_configuration_fingerprint": (
                self.profile_configuration_fingerprint
            ),
        }


@dataclass(frozen=True, slots=True)
class StagePlacementPolicy:
    """Trusted resolved run/pool/site policy for one stage."""

    pool_name: str = "default"
    target: str | None = None
    default_resources: ResourceRequest = field(default_factory=ResourceRequest)
    hard_maximums: ResourceRequest = field(default_factory=ResourceRequest)
    allowed_resource_kinds: tuple[str, ...] = ()
    hard_constraints: tuple[HardConstraintSpec, ...] = ()
    preferences: tuple[PreferenceSpec, ...] = ()
    route: ExecutionRoute = field(default_factory=ExecutionRoute)
    search_limits: SchedulingLimits = field(default_factory=SchedulingLimits)
    validator_ids: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.pool_name, str) or not self.pool_name:
            raise RuntimeResourceError("placement pool_name is required")
        if self.target is not None and (
            not isinstance(self.target, str) or not self.target
        ):
            raise RuntimeResourceError("placement target must be non-empty or None")
        for value, name in (
            (self.default_resources, "default_resources"),
            (self.hard_maximums, "hard_maximums"),
        ):
            if not isinstance(value, ResourceRequest):
                raise RuntimeResourceError(f"placement {name} must be ResourceRequest")
        if not isinstance(self.route, ExecutionRoute):
            raise RuntimeResourceError("placement route must be ExecutionRoute")
        if not isinstance(self.search_limits, SchedulingLimits):
            raise RuntimeResourceError(
                "placement search_limits must be SchedulingLimits"
            )
        allowed = tuple(self.allowed_resource_kinds)
        if any(not isinstance(kind, str) or not kind for kind in allowed):
            raise RuntimeResourceError("allowed resource kinds are invalid")
        hard = tuple(self.hard_constraints)
        preferences = tuple(self.preferences)
        if any(spec.descriptor is None for spec in hard):
            raise RuntimeResourceError("hard constraints must be registry-resolved")
        if any(spec.descriptor is None for spec in preferences):
            raise RuntimeResourceError("preferences must be registry-resolved")
        validator_ids = dict(self.validator_ids)
        if any(not kind or not identity for kind, identity in validator_ids.items()):
            raise RuntimeResourceError("validator identities must be non-empty")
        object.__setattr__(self, "allowed_resource_kinds", allowed)
        object.__setattr__(self, "hard_constraints", hard)
        object.__setattr__(self, "preferences", preferences)
        object.__setattr__(self, "validator_ids", MappingProxyType(validator_ids))


@dataclass(frozen=True, slots=True)
class ResolvedStagePlacement:
    resource_request: ResourceRequest
    scheduling_requests: Mapping[str, ResolvedResourceRequest]
    validator_ids: Mapping[str, str]
    planner_descriptors: Mapping[str, SchedulingComponentDescriptor]
    pool_name: str
    target: str | None
    hard_constraints: tuple[HardConstraintSpec, ...]
    preferences: tuple[PreferenceSpec, ...]
    route: ExecutionRoute
    search_limits: SchedulingLimits
    fingerprint: str
    schema_version: int = RESOLVED_STAGE_PLACEMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RESOLVED_STAGE_PLACEMENT_SCHEMA_VERSION:
            raise RuntimeResourceError("unsupported resolved placement schema version")
        if not isinstance(self.resource_request, ResourceRequest):
            raise RuntimeResourceError("resolved placement resource request is invalid")
        requests = dict(self.scheduling_requests)
        descriptors = dict(self.planner_descriptors)
        validators = dict(self.validator_ids)
        kinds = set(self.resource_request.entries)
        if (
            set(requests) != kinds
            or set(descriptors) != kinds
            or set(validators) != kinds
        ):
            raise RuntimeResourceError(
                "resolved resource, planner, and validator identities must cover the same kinds"
            )
        if any(request.resource_kind != kind for kind, request in requests.items()):
            raise RuntimeResourceError(
                "resolved scheduling request identity is invalid"
            )
        if any(descriptor.kind != kind for kind, descriptor in descriptors.items()):
            raise RuntimeResourceError(
                "resolved planner descriptor identity is invalid"
            )
        if not isinstance(self.fingerprint, str) or not self.fingerprint:
            raise RuntimeResourceError("resolved placement fingerprint is required")
        object.__setattr__(self, "scheduling_requests", MappingProxyType(requests))
        object.__setattr__(self, "planner_descriptors", MappingProxyType(descriptors))
        object.__setattr__(self, "validator_ids", MappingProxyType(validators))
        expected = _placement_fingerprint(self.to_dict(include_fingerprint=False))
        if self.fingerprint != expected:
            raise RuntimeResourceError(
                "resolved placement fingerprint does not match content"
            )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, PlainData]:
        data: dict[str, PlainData] = {
            "schema_version": self.schema_version,
            "resource_request": self.resource_request.to_dict(),
            "validator_ids": dict(sorted(self.validator_ids.items())),
            "planner_descriptors": {
                kind: descriptor.to_dict()
                for kind, descriptor in sorted(self.planner_descriptors.items())
            },
            "pool_name": self.pool_name,
            "target": self.target,
            "hard_constraints": [
                _hard_spec_data(spec) for spec in self.hard_constraints
            ],
            "preferences": [_preference_spec_data(spec) for spec in self.preferences],
            "route": self.route.to_dict(),
            "search_limits": {
                "max_work_items": self.search_limits.max_work_items,
                "max_candidates": self.search_limits.max_candidates,
                "max_claims_per_resource": self.search_limits.max_claims_per_resource,
                "max_composite_candidates": self.search_limits.max_composite_candidates,
            },
        }
        if include_fingerprint:
            data["fingerprint"] = self.fingerprint
        return data

    @classmethod
    def from_dict(
        cls,
        data: object,
        *,
        validator_registry: ResourceValidatorRegistry | None = None,
    ) -> ResolvedStagePlacement:
        mapping = _mapping(data, "ResolvedStagePlacement")
        allowed = {
            "schema_version",
            "resource_request",
            "validator_ids",
            "planner_descriptors",
            "pool_name",
            "target",
            "hard_constraints",
            "preferences",
            "route",
            "search_limits",
            "fingerprint",
        }
        unknown = set(mapping) - allowed
        if unknown:
            raise RuntimeResourceError(
                "ResolvedStagePlacement has unknown field(s): "
                + ", ".join(sorted(unknown))
            )
        registry = validator_registry or DEFAULT_RESOURCE_VALIDATOR_REGISTRY
        resource_request = ResourceRequest.from_dict(
            _required(mapping, "resource_request", "ResolvedStagePlacement"),
            registry=registry,
        )
        validator_ids = _string_mapping(
            _required(mapping, "validator_ids", "ResolvedStagePlacement"),
            "ResolvedStagePlacement.validator_ids",
        )
        descriptor_mapping = _mapping(
            _required(mapping, "planner_descriptors", "ResolvedStagePlacement"),
            "ResolvedStagePlacement.planner_descriptors",
        )
        descriptors = {
            kind: SchedulingComponentDescriptor.from_dict(value)
            for kind, value in descriptor_mapping.items()
        }
        hard_values = _sequence(
            mapping.get("hard_constraints", ()),
            "ResolvedStagePlacement.hard_constraints",
        )
        preference_values = _sequence(
            mapping.get("preferences", ()),
            "ResolvedStagePlacement.preferences",
        )
        route_data = _mapping(
            _required(mapping, "route", "ResolvedStagePlacement"),
            "ResolvedStagePlacement.route",
        )
        _exact_fields(
            route_data,
            {
                "kind",
                "profile_id",
                "profile_descriptor",
                "profile_configuration_fingerprint",
            },
            "ResolvedStagePlacement.route",
        )
        limits_data = _mapping(
            _required(mapping, "search_limits", "ResolvedStagePlacement"),
            "ResolvedStagePlacement.search_limits",
        )
        requests = {
            kind: ResolvedResourceRequest(kind, scheduling_entry_view(entry))
            for kind, entry in resource_request.entries.items()
        }
        return cls(
            schema_version=cast(
                int,
                _required(mapping, "schema_version", "ResolvedStagePlacement"),
            ),
            resource_request=resource_request,
            scheduling_requests=requests,
            validator_ids=validator_ids,
            planner_descriptors=descriptors,
            pool_name=cast(
                str, _required(mapping, "pool_name", "ResolvedStagePlacement")
            ),
            target=cast(str | None, mapping.get("target")),
            hard_constraints=tuple(
                _hard_spec_from_data(value) for value in hard_values
            ),
            preferences=tuple(
                _preference_spec_from_data(value) for value in preference_values
            ),
            route=ExecutionRoute(
                kind=ExecutionRouteKind(
                    cast(
                        str,
                        _required(route_data, "kind", "ResolvedStagePlacement.route"),
                    )
                ),
                profile_id=cast(str | None, route_data.get("profile_id")),
                profile_descriptor=(
                    None
                    if route_data.get("profile_descriptor") is None
                    else SchedulingComponentDescriptor.from_dict(
                        route_data["profile_descriptor"]
                    )
                ),
                profile_configuration_fingerprint=cast(
                    str | None,
                    route_data.get("profile_configuration_fingerprint"),
                ),
            ),
            search_limits=SchedulingLimits(
                max_work_items=cast(
                    int,
                    _required(
                        limits_data,
                        "max_work_items",
                        "ResolvedStagePlacement.search_limits",
                    ),
                ),
                max_candidates=cast(
                    int,
                    _required(
                        limits_data,
                        "max_candidates",
                        "ResolvedStagePlacement.search_limits",
                    ),
                ),
                max_claims_per_resource=cast(
                    int,
                    _required(
                        limits_data,
                        "max_claims_per_resource",
                        "ResolvedStagePlacement.search_limits",
                    ),
                ),
                max_composite_candidates=cast(
                    int,
                    _required(
                        limits_data,
                        "max_composite_candidates",
                        "ResolvedStagePlacement.search_limits",
                    ),
                ),
            ),
            fingerprint=cast(
                str, _required(mapping, "fingerprint", "ResolvedStagePlacement")
            ),
        )


def resolve_stage_placement(
    *,
    authored: ResourceRequest,
    runtime: ResourceRequest | None,
    policy: StagePlacementPolicy,
    planners: Mapping[str, ResourcePlanner],
    validator_registry: ResourceValidatorRegistry | None = None,
) -> ResolvedStagePlacement:
    """Resolve resources and an already-selected closed route for one stage."""

    if not isinstance(authored, ResourceRequest):
        raise RuntimeResourceError("authored resources must be ResourceRequest")
    if runtime is not None and not isinstance(runtime, ResourceRequest):
        raise RuntimeResourceError("runtime resources must be ResourceRequest or None")
    if not isinstance(policy, StagePlacementPolicy):
        raise RuntimeResourceError("policy must be StagePlacementPolicy")
    registry = validator_registry or DEFAULT_RESOURCE_VALIDATOR_REGISTRY
    kinds = (
        set(authored.entries)
        | set(policy.default_resources.entries)
        | set(runtime.entries if runtime is not None else ())
    )
    if policy.allowed_resource_kinds:
        disallowed = kinds - set(policy.allowed_resource_kinds)
        if disallowed:
            raise RuntimeResourceError(
                f"placement uses disallowed resource kind(s): {', '.join(sorted(disallowed))}"
            )

    entries: dict[str, ResourceEntry] = {}
    requests: dict[str, ResolvedResourceRequest] = {}
    descriptors: dict[str, SchedulingComponentDescriptor] = {}
    validator_ids: dict[str, str] = {}
    for kind in sorted(kinds):
        planner = planners.get(kind)
        if (
            planner is None
            or planner.resource_kind != kind
            or planner.descriptor.kind != kind
        ):
            raise RuntimeResourceError(
                f"no valid resource planner is active for {kind!r}"
            )
        base = authored.entries.get(kind) or policy.default_resources.entries.get(kind)
        refinement = runtime.entries.get(kind) if runtime is not None else None
        try:
            result = planner.resolve_request(
                scheduling_entry_view(base) if base is not None else None,
                scheduling_entry_view(refinement) if refinement is not None else None,
            )
        except Exception as exc:
            raise RuntimeResourceError(
                f"resource planner {kind!r} failed request resolution: {type(exc).__name__}"
            ) from exc
        if not isinstance(result, ResourceRequestResolution):
            raise RuntimeResourceError(
                f"resource planner {kind!r} returned an invalid request resolution"
            )
        if result.state is ResourceResolutionState.INVALID:
            raise RuntimeResourceError(
                result.explanation or f"resource request {kind!r} is invalid"
            )
        if result.state is ResourceResolutionState.ABSENT:
            continue
        assert result.request is not None
        maximum = policy.hard_maximums.entries.get(kind)
        if maximum is not None:
            maximum_view = scheduling_entry_view(maximum)
            if (
                maximum_view.unit != result.request.entry.unit
                or result.request.entry.amount.fraction > maximum_view.amount.fraction
            ):
                raise RuntimeResourceError(
                    f"resource request {kind!r} exceeds the site maximum"
                )
        entries[kind] = _entry_from_view(result.request.entry)
        requests[kind] = result.request
        descriptors[kind] = planner.descriptor
        validator_ids[kind] = policy.validator_ids.get(kind, f"builtin:{kind}:v1")

    canonical = ResourceRequest(entries=entries, validator_registry=registry)
    payload: dict[str, PlainData] = {
        "schema_version": RESOLVED_STAGE_PLACEMENT_SCHEMA_VERSION,
        "resource_request": canonical.to_dict(),
        "validator_ids": dict(sorted(validator_ids.items())),
        "planner_descriptors": {
            kind: descriptor.to_dict()
            for kind, descriptor in sorted(descriptors.items())
        },
        "pool_name": policy.pool_name,
        "target": policy.target,
        "hard_constraints": [_hard_spec_data(spec) for spec in policy.hard_constraints],
        "preferences": [_preference_spec_data(spec) for spec in policy.preferences],
        "route": policy.route.to_dict(),
        "search_limits": {
            "max_work_items": policy.search_limits.max_work_items,
            "max_candidates": policy.search_limits.max_candidates,
            "max_claims_per_resource": policy.search_limits.max_claims_per_resource,
            "max_composite_candidates": policy.search_limits.max_composite_candidates,
        },
    }
    return ResolvedStagePlacement(
        resource_request=canonical,
        scheduling_requests=requests,
        validator_ids=validator_ids,
        planner_descriptors=descriptors,
        pool_name=policy.pool_name,
        target=policy.target,
        hard_constraints=policy.hard_constraints,
        preferences=policy.preferences,
        route=policy.route,
        search_limits=policy.search_limits,
        fingerprint=_placement_fingerprint(payload),
    )


def _entry_from_view(view: object) -> ResourceEntry:
    entry = cast(ResolvedResourceRequest | object, view)
    amount = cast(object, getattr(entry, "amount"))
    denominator = cast(int, getattr(amount, "denominator"))
    numerator = cast(int, getattr(amount, "numerator"))
    attributes = dict(cast(Mapping[str, PlainData], getattr(entry, "attributes")))
    unit = cast(str | None, getattr(entry, "unit"))
    kind = cast(str, getattr(entry, "kind"))
    if denominator == 1:
        return ResourceEntry(
            kind=kind, amount=numerator, unit=unit, attributes=attributes
        )
    if unit == "share":
        attributes["share_denominator"] = denominator
        return ResourceEntry(
            kind=kind, amount=numerator, unit=unit, attributes=attributes
        )
    raise RuntimeResourceError(
        f"resolved resource {kind!r} cannot be represented by ResourceEntry exactly"
    )


def _hard_spec_data(spec: HardConstraintSpec) -> dict[str, PlainData]:
    assert spec.descriptor is not None
    return {
        "identifier": spec.identifier,
        "evaluator": spec.evaluator,
        "data": dict(spec.data),
        "descriptor": spec.descriptor.to_dict(),
    }


def _preference_spec_data(spec: PreferenceSpec) -> dict[str, PlainData]:
    assert spec.descriptor is not None
    return {
        "identifier": spec.identifier,
        "scorer": spec.scorer,
        "tier": spec.tier,
        "weight": spec.weight,
        "fallback_after_seconds": spec.fallback_after_seconds,
        "data": dict(spec.data),
        "utility_min": spec.utility_min,
        "utility_max": spec.utility_max,
        "quality_bands": list(spec.quality_bands),
        "fallback_band": spec.fallback_band,
        "descriptor": spec.descriptor.to_dict(),
    }


def _hard_spec_from_data(data: object) -> HardConstraintSpec:
    mapping = _mapping(data, "HardConstraintSpec")
    descriptor = SchedulingComponentDescriptor.from_dict(
        _required(mapping, "descriptor", "HardConstraintSpec")
    )
    raw_data = _mapping(mapping.get("data", {}), "HardConstraintSpec.data")
    return HardConstraintSpec(
        identifier=cast(str, _required(mapping, "identifier", "HardConstraintSpec")),
        evaluator=cast(str, _required(mapping, "evaluator", "HardConstraintSpec")),
        data=cast(Mapping[str, PlainData], raw_data),
        descriptor=descriptor,
    )


def _preference_spec_from_data(data: object) -> PreferenceSpec:
    mapping = _mapping(data, "PreferenceSpec")
    descriptor = SchedulingComponentDescriptor.from_dict(
        _required(mapping, "descriptor", "PreferenceSpec")
    )
    raw_data = _mapping(mapping.get("data", {}), "PreferenceSpec.data")
    return PreferenceSpec(
        identifier=cast(str, _required(mapping, "identifier", "PreferenceSpec")),
        scorer=cast(str, _required(mapping, "scorer", "PreferenceSpec")),
        tier=cast(int, mapping.get("tier", 0)),
        weight=cast(int, mapping.get("weight", 1)),
        fallback_after_seconds=cast(int | None, mapping.get("fallback_after_seconds")),
        data=cast(Mapping[str, PlainData], raw_data),
        utility_min=cast(int, mapping.get("utility_min", -(2**31))),
        utility_max=cast(int, mapping.get("utility_max", 2**31 - 1)),
        quality_bands=tuple(
            cast(
                tuple[str, ...] | list[str],
                mapping.get("quality_bands", ("preferred",)),
            )
        ),
        fallback_band=cast(str | None, mapping.get("fallback_band")),
        descriptor=descriptor,
    )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RuntimeResourceError(f"{path} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _exact_fields(value: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise RuntimeResourceError(f"{path} fields are unsupported")


def _sequence(value: object, path: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise RuntimeResourceError(f"{path} must be a sequence")
    return tuple(value)


def _required(mapping: Mapping[str, object], key: str, path: str) -> object:
    if key not in mapping:
        raise RuntimeResourceError(f"{path} is missing {key}")
    return mapping[key]


def _string_mapping(value: object, path: str) -> dict[str, str]:
    mapping = _mapping(value, path)
    if any(not isinstance(item, str) or not item for item in mapping.values()):
        raise RuntimeResourceError(f"{path} values must be non-empty strings")
    return {key: cast(str, item) for key, item in mapping.items()}


def _placement_fingerprint(data: Mapping[str, PlainData]) -> str:
    return hashlib.sha256(stable_json_dumps(data).encode("utf-8")).hexdigest()


__all__ = [
    "ExecutionRoute",
    "ExecutionRouteKind",
    "RESOLVED_STAGE_PLACEMENT_SCHEMA_VERSION",
    "ResolvedStagePlacement",
    "StagePlacementPolicy",
    "resolve_stage_placement",
]
