"""Adapters and deterministic CPU/memory planners for the scheduling kernel.

The existing pipeline resource codec remains the sole authored schema.  This
module translates its already-validated values to scheduling's immutable view.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    if entry.kind == "gpu":
        return _gpu_entry_view(entry)
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


def _gpu_entry_view(entry: ResourceEntry) -> ValidatedResourceEntryView:
    mode = entry.attributes.get("allocation_mode", "exclusive")
    attributes = dict(entry.attributes)
    if mode == "exclusive":
        if not isinstance(entry.amount, int):
            raise RuntimeResourceError("managed GPU requests require an integer count")
        return ValidatedResourceEntryView(
            "gpu", ExactQuantity(entry.amount), "count", attributes
        )
    if mode == "vram_share":
        multiplier = _MEMORY_UNITS.get(entry.unit or "")
        if multiplier is None or not isinstance(entry.amount, int):
            raise RuntimeResourceError("managed GPU VRAM shares require exact bytes")
        return ValidatedResourceEntryView(
            "gpu", ExactQuantity(entry.amount * multiplier), "B", attributes
        )
    if mode == "provider_fraction":
        denominator = attributes.get("share_denominator")
        if not isinstance(entry.amount, int) or not isinstance(denominator, int):
            raise RuntimeResourceError("managed GPU fractions require exact integers")
        attributes["share_denominator"] = ExactQuantity(
            entry.amount, denominator
        ).denominator
        return ValidatedResourceEntryView(
            "gpu", ExactQuantity(entry.amount, denominator), "share", attributes
        )
    raise RuntimeResourceError("managed GPU allocation mode is unsupported")


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


class GpuResourcePlanner:
    """Exact configured-device GPU planner; it never infers a share from VRAM."""

    resource_kind = "gpu"
    descriptor = SchedulingComponentDescriptor(
        "gpu", 1, "1", "builtin-gpu-planner-v1", "builtin"
    )
    claim_contracts = (
        ResourceClaimContractDescriptor("gpu", 1, "builtin-gpu-claim-v1"),
    )

    def resolve_request(self, authored, runtime) -> ResourceRequestResolution:
        if authored is None and runtime is None:
            return ResourceRequestResolution(ResourceResolutionState.ABSENT)
        value = runtime or authored
        assert value is not None
        if value.kind != self.resource_kind:
            return ResourceRequestResolution(
                ResourceResolutionState.INVALID, explanation="wrong resource kind"
            )
        if authored is not None and runtime is not None:
            if (
                runtime.unit != authored.unit
                or runtime.amount.fraction < authored.amount.fraction
            ):
                return ResourceRequestResolution(
                    ResourceResolutionState.INVALID,
                    explanation="runtime refinement weakens authored GPU request",
                )
            if any(
                runtime.attributes.get(key) != expected
                for key, expected in authored.attributes.items()
            ):
                return ResourceRequestResolution(
                    ResourceResolutionState.INVALID,
                    explanation="runtime refinement weakens authored GPU attributes",
                )
        error = self._request_error(value)
        if error is not None:
            return ResourceRequestResolution(
                ResourceResolutionState.INVALID, explanation=error
            )
        return ResourceRequestResolution(
            ResourceResolutionState.RESOLVED, ResolvedResourceRequest("gpu", value)
        )

    def validate_opportunity(
        self, inventory, availability
    ) -> OpportunityValidationResult:
        if (
            inventory.resource_kind != "gpu"
            or availability.resource_kind != "gpu"
            or inventory.candidate_id != availability.candidate_id
            or inventory.snapshot_revision != availability.snapshot_revision
            or inventory.data_version != availability.data_version
        ):
            return OpportunityValidationResult(
                OpportunityState.INVALID,
                explanation="GPU opportunity snapshots do not match",
            )
        devices = inventory.data.get("devices")
        if not isinstance(devices, tuple) or not devices:
            return OpportunityValidationResult(
                OpportunityState.INVALID,
                explanation="GPU inventory devices are invalid",
            )
        configured: dict[str, Mapping[str, object]] = {}
        for value in devices:
            if not isinstance(value, Mapping):
                return OpportunityValidationResult(
                    OpportunityState.INVALID,
                    explanation="GPU inventory device is invalid",
                )
            device_id = value.get("id")
            vram = value.get("vram_bytes")
            mode = value.get("allocation_mode")
            provider = value.get("provider")
            if (
                not isinstance(device_id, str)
                or not device_id
                or device_id in configured
                or not isinstance(vram, int)
                or isinstance(vram, bool)
                or vram <= 0
                or mode not in {"exclusive", "vram_share", "provider_fraction"}
                or not isinstance(provider, str)
                or not provider
                or value.get("healthy", True) is not True
            ):
                return OpportunityValidationResult(
                    OpportunityState.INVALID,
                    explanation="GPU inventory device is invalid",
                )
            configured[device_id] = value
        inventory_atoms = {atom.local_capacity_key: atom for atom in inventory.atoms}
        available_atoms = {atom.local_capacity_key: atom for atom in availability.atoms}
        if set(inventory_atoms) != set(configured) or not set(available_atoms).issubset(
            configured
        ):
            return OpportunityValidationResult(
                OpportunityState.INVALID,
                explanation="GPU atoms do not match configured device IDs",
            )
        for device_id, device in configured.items():
            atom = inventory_atoms[device_id]
            if atom.owner_resource_kind != "gpu" or atom.unit not in {
                "count",
                "B",
                "share",
            }:
                return OpportunityValidationResult(
                    OpportunityState.INVALID,
                    explanation="GPU inventory atom is invalid",
                )
            expected_unit = {
                "exclusive": "count",
                "vram_share": "B",
                "provider_fraction": "share",
            }[str(device["allocation_mode"])]
            if atom.unit != expected_unit:
                return OpportunityValidationResult(
                    OpportunityState.INVALID,
                    explanation="GPU allocation mode contradicts atom unit",
                )
            available = available_atoms.get(device_id)
            if available is not None and (
                available.unit != atom.unit
                or available.amount.fraction > atom.amount.fraction
            ):
                return OpportunityValidationResult(
                    OpportunityState.INVALID,
                    explanation="GPU availability atom is invalid",
                )
        return OpportunityValidationResult(
            OpportunityState.VALID,
            ValidatedResourceOpportunity(
                inventory.candidate_id,
                "gpu",
                inventory.snapshot_revision,
                inventory.data,
                availability.atoms,
            ),
        )

    def propose_claims(self, request, opportunity, budget) -> ClaimSearchResult:
        error = self._request_error(request.entry)
        if error is not None:
            return ClaimSearchResult(ClaimSearchState.COMPLETE, explanation=error)
        devices = {
            str(item["id"]): item
            for item in opportunity.data["devices"]
            if isinstance(item, Mapping)
        }
        mode = str(request.entry.attributes.get("allocation_mode"))
        provider = request.entry.attributes.get("provider")
        requested_ids = request.entry.attributes.get("device_ids")
        candidates = []
        for atom in sorted(
            opportunity.available_atoms, key=lambda item: item.local_capacity_key
        ):
            device = devices.get(atom.local_capacity_key)
            if device is None or device.get("allocation_mode") != mode:
                continue
            if provider is not None and device.get("provider") != provider:
                continue
            if (
                requested_ids is not None
                and atom.local_capacity_key not in requested_ids
            ):
                continue
            if mode == "exclusive" and not self._exclusive_eligible(
                request.entry, device, atom
            ):
                continue
            candidates.append(atom)
        if mode == "exclusive":
            count = int(request.entry.amount.fraction)
            if len(candidates) < count:
                return ClaimSearchResult(ClaimSearchState.COMPLETE)
            if len(candidates) > budget.max_expansions:
                return ClaimSearchResult(
                    ClaimSearchState.EXHAUSTED,
                    explanation="GPU device search exceeded its bound",
                )
            from itertools import combinations

            claims = [
                self._claim(
                    tuple(selection), mode, provider, opportunity.snapshot_revision
                )
                for selection in combinations(candidates, count)
                if self._same_fabric_group(
                    tuple(selection),
                    devices,
                    request.entry.attributes.get("fabric_group"),
                )
            ]
            if len(claims) > budget.max_claims:
                return ClaimSearchResult(
                    ClaimSearchState.EXHAUSTED,
                    explanation="GPU claim search exceeded its bound",
                )
            return ClaimSearchResult(ClaimSearchState.COMPLETE, tuple(claims))
        claims, exhausted = _complete_exact_claims(
            resource_kind="gpu",
            contract=self.claim_contracts[0],
            requested=request.entry.amount.fraction,
            atoms=candidates,
            snapshot_revision=opportunity.snapshot_revision,
            max_claims=budget.max_claims,
            max_expansions=budget.max_expansions,
        )
        if exhausted:
            return ClaimSearchResult(
                ClaimSearchState.EXHAUSTED,
                explanation="GPU claim search exceeded its bound",
            )
        return ClaimSearchResult(
            ClaimSearchState.COMPLETE,
            tuple(
                ResourceClaim(
                    "gpu",
                    claim.contract,
                    claim.atoms,
                    1,
                    {
                        "snapshot_revision": opportunity.snapshot_revision,
                        "allocation_mode": mode,
                        "provider": str(provider),
                        "device_ids": [atom.local_capacity_key for atom in claim.atoms],
                    },
                )
                for claim in claims
            ),
        )

    def validate_claim(self, request, claim) -> ClaimValidationResult:
        if claim.resource_kind != "gpu" or claim.contract not in self.claim_contracts:
            return ClaimValidationResult(
                ClaimValidationState.INVALID, "wrong GPU claim contract"
            )
        mode = request.entry.attributes.get("allocation_mode")
        if claim.provider_data.get("allocation_mode") != mode:
            return ClaimValidationResult(
                ClaimValidationState.INVALID, "GPU claim allocation mode differs"
            )
        if mode == "exclusive":
            if len(claim.atoms) != request.entry.amount.numerator or any(
                atom.unit != "count" or atom.amount != ExactQuantity(1)
                for atom in claim.atoms
            ):
                return ClaimValidationResult(
                    ClaimValidationState.INVALID,
                    "GPU exclusive claim is not exact devices",
                )
        elif (
            sum((atom.amount.fraction for atom in claim.atoms), Fraction(0))
            != request.entry.amount.fraction
        ):
            return ClaimValidationResult(
                ClaimValidationState.INVALID, "GPU claim does not exactly meet request"
            )
        return ClaimValidationResult(ClaimValidationState.VALID)

    def _request_error(self, entry: ValidatedResourceEntryView) -> str | None:
        mode = entry.attributes.get("allocation_mode")
        if mode == "exclusive":
            if entry.unit != "count" or entry.amount.denominator != 1:
                return "exclusive GPU request requires integer device count"
            return None
        if mode == "vram_share":
            if entry.unit != "B" or not isinstance(
                entry.attributes.get("provider"), str
            ):
                return "GPU VRAM sharing requires byte-exact named provider"
            return None
        if mode == "provider_fraction":
            if entry.unit != "share" or not isinstance(
                entry.attributes.get("provider"), str
            ):
                return "GPU fractional sharing requires named provider"
            return None
        return "GPU allocation mode is unsupported"

    @staticmethod
    def _exclusive_eligible(
        entry: ValidatedResourceEntryView,
        device: Mapping[str, object],
        atom: CapacityAtom,
    ) -> bool:
        minimum = _minimum_vram_bytes(entry.attributes.get("minimum_vram"))
        models = entry.attributes.get("models")
        features = entry.attributes.get("features", ())
        vram = device.get("vram_bytes")
        if not isinstance(vram, int):
            return False
        if models is not None and (
            not isinstance(models, tuple)
            or any(not isinstance(model, str) for model in models)
        ):
            return False
        if not isinstance(features, tuple) or any(
            not isinstance(feature, str) for feature in features
        ):
            return False
        available_features = device.get("features", ())
        if not isinstance(available_features, tuple) or any(
            not isinstance(feature, str) for feature in available_features
        ):
            return False
        if atom.unit != "count" or atom.amount != ExactQuantity(1) or vram < minimum:
            return False
        if models is not None:
            model = device.get("model")
            if not isinstance(model, str) or model not in models:
                return False
        return all(feature in available_features for feature in features)

    def _claim(self, atoms, mode, provider, revision) -> ResourceClaim:
        return ResourceClaim(
            "gpu",
            self.claim_contracts[0],
            atoms,
            1,
            {
                "snapshot_revision": revision,
                "allocation_mode": mode,
                "provider": provider or "exclusive",
                "device_ids": [atom.local_capacity_key for atom in atoms],
            },
        )

    @staticmethod
    def _same_fabric_group(atoms, devices, required_group) -> bool:
        if required_group is None:
            return True
        if not isinstance(required_group, str):
            return False
        return all(
            devices[atom.local_capacity_key].get("fabric_group") == required_group
            for atom in atoms
        )


def _minimum_vram_bytes(value: object) -> int:
    if value is None:
        return 0
    if not isinstance(value, Mapping):
        return -1
    amount = value.get("amount")
    unit = value.get("unit")
    multiplier = _MEMORY_UNITS.get(unit) if isinstance(unit, str) else None
    if not isinstance(amount, int) or isinstance(amount, bool) or multiplier is None:
        return -1
    return amount * multiplier


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
