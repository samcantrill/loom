"""Resident resource providers and their composition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Generator, Mapping, Sequence
from fractions import Fraction
from threading import RLock
from typing import Any

from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)

from ._agent_progress import _cooperative, _external, _Progress, _steps
from ._managed_contracts import (
    AgentResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ClaimResult,
    ManagedLocalError,
    ObserveRequest,
    ObserveResult,
    ResourceAvailabilityStatus,
    _provider_call,
)
from .gpu.occupancy import (
    GpuOccupancyMonitor,
    GpuOccupancySnapshot,
    _sample_gpu_occupancy,
)


def _provider_group_descriptor(
    providers: Sequence[
        tuple[
            SchedulingComponentDescriptor,
            Sequence[ResourceClaimContractDescriptor],
        ]
    ],
) -> SchedulingComponentDescriptor:
    """Derive one inert runtime owner from an exact same-kind provider set."""

    members = tuple(sorted(providers, key=lambda item: item[0].key))
    if not members:
        raise ManagedLocalError("provider group must not be empty")
    kind = members[0][0].kind
    if any(descriptor.kind != kind for descriptor, _ in members):
        raise ManagedLocalError("provider group kinds must match")
    if len({descriptor.key for descriptor, _ in members}) != len(members):
        raise ManagedLocalError("provider group identities must be unique")
    if len(members) == 1:
        return members[0][0]
    encoded = json.dumps(
        {
            "providers": [
                {
                    "descriptor": descriptor.to_dict(),
                    "claim_contracts": [
                        contract.to_dict()
                        for contract in sorted(contracts, key=lambda item: item.key)
                    ],
                }
                for descriptor, contracts in members
            ]
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return SchedulingComponentDescriptor(
        kind,
        1,
        "1",
        "loom.agent-resource-provider-composite.v1",
        hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )


class _CompositeAgentResourceProvider:
    """One journal owner for disjoint physical providers of the same kind."""

    def __init__(self, providers: Sequence[AgentResourceProvider]) -> None:
        members = tuple(sorted(providers, key=lambda item: item.descriptor.key))
        if len(members) < 2:
            raise ManagedLocalError("composite provider requires multiple members")
        kind = members[0].descriptor.kind
        if any(member.descriptor.kind != kind for member in members):
            raise ManagedLocalError("composite provider kinds must match")
        if len({member.descriptor.key for member in members}) != len(members):
            raise ManagedLocalError("composite provider identities must be unique")
        contracts = tuple(
            sorted(
                {contract for member in members for contract in member.claim_contracts},
                key=lambda item: item.key,
            )
        )
        if not contracts or any(contract.kind != kind for contract in contracts):
            raise ManagedLocalError("composite provider contracts are invalid")
        self.descriptor = _provider_group_descriptor(
            tuple((member.descriptor, member.claim_contracts) for member in members)
        )
        self.claim_contracts = contracts
        self._members = members
        self._atom_owners: dict[tuple[str, str], int] = {}
        self._observed_atoms: dict[tuple[str, str], CapacityAtom] = {}
        self._claim_allocations: dict[str, tuple[CapacityAtom, ...]] = {}
        self._lock = RLock()

    @property
    def members(self) -> tuple[AgentResourceProvider, ...]:
        return self._members

    def observe(self, request: ObserveRequest) -> ObserveResult:
        with self._lock:
            observations: list[tuple[AgentResourceProvider, ObserveResult]] = []
            owners: dict[tuple[str, str], int] = {}
            atoms: list[CapacityAtom] = []
            live_claim_ids: set[str] = set()
            statuses: list[ResourceAvailabilityStatus] = []
            status_owners: dict[tuple[str, str], int] = {}
            for index, member in enumerate(self._members):
                result = member.observe(
                    ObserveRequest(
                        request.agent_id,
                        request.session_id,
                        f"{request.operation_id}:provider:{index}",
                    )
                )
                if not isinstance(result, ObserveResult):
                    raise ManagedLocalError("provider observation is invalid")
                observations.append((member, result))
                live_claim_ids.update(result.live_claim_ids)
                for status in result.resource_status:
                    key = (status.resource_kind, status.local_capacity_key)
                    if key in status_owners:
                        raise ManagedLocalError(
                            "same-kind providers expose overlapping resource statuses"
                        )
                    status_owners[key] = index
                    statuses.append(status)
                for atom in result.atoms:
                    if atom.owner_resource_kind != self.descriptor.kind:
                        raise ManagedLocalError(
                            "provider observation kind conflicts with composition"
                        )
                    if atom.key in owners:
                        raise ManagedLocalError(
                            "same-kind providers expose overlapping capacity atoms"
                        )
                    owners[atom.key] = index
                    atoms.append(atom)
            self._atom_owners.update(owners)
            self._observed_atoms = {atom.key: atom for atom in atoms}
            revision_payload = {
                str(index): result.availability_revision
                for index, (_, result) in enumerate(observations)
            }
            revision = hashlib.sha256(
                json.dumps(
                    revision_payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            return ObserveResult(
                request.operation_id,
                f"composite-{self.descriptor.kind}-{revision}",
                tuple(sorted(atoms, key=lambda item: item.key)),
                tuple(sorted(live_claim_ids)),
                tuple(
                    sorted(
                        statuses,
                        key=lambda item: (item.resource_kind, item.local_capacity_key),
                    )
                ),
            )

    def restore_capacity_holding(self, command: ClaimCommand) -> None:
        with self._lock:
            for member, nested in self._commands(command):
                member.restore_capacity_holding(nested)

    @_cooperative
    def prepare(self, command: ClaimCommand) -> Generator[_Progress, Any, ClaimResult]:
        with self._lock:
            prepared: list[tuple[AgentResourceProvider, ClaimCommand]] = []
            for member, nested in self._commands(command):
                result = yield from _steps(_provider_call, member.prepare, nested)
                if result.outcome is not ClaimOutcome.PREPARED:
                    aborts = [
                        _provider_call(prior.abort, prior_command)
                        for prior, prior_command in reversed(prepared)
                    ]
                    outcome = (
                        ClaimOutcome.DECLINED
                        if result.outcome is ClaimOutcome.DECLINED
                        and all(
                            item.outcome is ClaimOutcome.RELEASED for item in aborts
                        )
                        else ClaimOutcome.INDETERMINATE
                    )
                    return self._result(command, outcome, result.detail)
                prepared.append((member, nested))
            return self._result(command, ClaimOutcome.PREPARED)

    def reconcile(self, command: ClaimCommand) -> ClaimResult:
        return self._apply(command, "reconcile", ClaimOutcome.PREPARED)

    def activate(self, command: ClaimCommand) -> ClaimResult:
        return self._apply(command, "activate", ClaimOutcome.ACTIVE)

    def abort(self, command: ClaimCommand) -> ClaimResult:
        return self._apply(command, "abort", ClaimOutcome.RELEASED)

    def release(self, command: ClaimCommand) -> ClaimResult:
        return self._apply(command, "release", ClaimOutcome.RELEASED)

    def worker_environment(self, command: ClaimCommand) -> dict[str, str]:
        with self._lock:
            environment: dict[str, str] = {}
            for member, nested in self._commands(command):
                contribution = dict(member.worker_environment(nested))
                for key, value in contribution.items():
                    if key in environment and environment[key] != value:
                        raise ManagedLocalError(
                            "provider worker environment contributions conflict"
                        )
                    environment[key] = value
            return environment

    def _apply(
        self, command: ClaimCommand, operation: str, expected: ClaimOutcome
    ) -> ClaimResult:
        with self._lock:
            results = [
                _provider_call(getattr(member, operation), nested)
                for member, nested in self._commands(command)
            ]
            if all(result.outcome is expected for result in results):
                return self._result(command, expected)
            detail = next(
                (result.detail for result in results if result.detail is not None),
                f"composite provider {operation} was indeterminate",
            )
            return self._result(command, ClaimOutcome.INDETERMINATE, detail)

    def _commands(
        self, command: ClaimCommand
    ) -> tuple[tuple[AgentResourceProvider, ClaimCommand], ...]:
        if command.provider_descriptor != self.descriptor:
            raise ManagedLocalError("composite provider identity conflicts")
        if command.claim.contract not in self.claim_contracts:
            raise ManagedLocalError("composite provider claim contract is unsupported")
        allocated_atoms = self._claim_allocations.get(command.claim.fingerprint)
        if allocated_atoms is None:
            self.observe(
                ObserveRequest(
                    command.assignment.agent_id,
                    command.assignment.session_id,
                    f"{command.operation_id}:owners",
                )
            )
            if all(atom.key in self._atom_owners for atom in command.claim.atoms):
                allocated_atoms = command.claim.atoms
            else:
                allocated_atoms = self._allocate_aggregate_claim(command.claim)
            self._claim_allocations[command.claim.fingerprint] = allocated_atoms
        grouped: dict[int, list[CapacityAtom]] = {}
        for atom in allocated_atoms:
            owner_index = self._atom_owners.get(atom.key)
            if owner_index is None:
                raise ManagedLocalError("claim atom has no configured provider owner")
            grouped.setdefault(owner_index, []).append(atom)
        result: list[tuple[AgentResourceProvider, ClaimCommand]] = []
        for index, member in enumerate(self._members):
            atoms = grouped.get(index)
            if not atoms:
                continue
            if command.claim.contract not in member.claim_contracts:
                raise ManagedLocalError(
                    "claim contract is unsupported by an owning provider"
                )
            claim = ResourceClaim(
                command.claim.resource_kind,
                command.claim.contract,
                tuple(atoms),
                command.claim.provider_data_version,
                command.claim.provider_data,
            )
            result.append(
                (
                    member,
                    ClaimCommand(
                        command.assignment,
                        f"{command.operation_id}:provider:{index}",
                        claim,
                        member.descriptor,
                    ),
                )
            )
        if not result:
            raise ManagedLocalError("composite claim has no provider owners")
        return tuple(result)

    def _allocate_aggregate_claim(
        self, claim: ResourceClaim
    ) -> tuple[CapacityAtom, ...]:
        if len(claim.atoms) != 1:
            raise ManagedLocalError("claim atom has no configured provider owner")
        requested = claim.atoms[0]
        remaining = requested.amount.fraction
        allocated: list[CapacityAtom] = []
        for key, atom in sorted(self._observed_atoms.items()):
            owner_index = self._atom_owners[key]
            member = self._members[owner_index]
            if (
                claim.contract not in member.claim_contracts
                or atom.unit != requested.unit
                or atom.granularity != requested.granularity
            ):
                continue
            granularity = atom.granularity.fraction
            units = int(min(atom.amount.fraction, remaining) / granularity)
            if units <= 0:
                continue
            amount = granularity * units
            allocated.append(
                CapacityAtom(
                    atom.owner_resource_kind,
                    atom.local_capacity_key,
                    ExactQuantity(amount.numerator, amount.denominator),
                    atom.unit,
                    atom.granularity,
                )
            )
            remaining -= amount
            if not remaining:
                break
        if remaining:
            raise ManagedLocalError(
                "aggregate claim exceeds compatible provider capacity"
            )
        return tuple(allocated)

    @staticmethod
    def _result(
        command: ClaimCommand, outcome: ClaimOutcome, detail: str | None = None
    ) -> ClaimResult:
        return ClaimResult(
            outcome, command.operation_id, command.claim.fingerprint, detail
        )


def _compose_agent_resource_providers(
    providers: Sequence[AgentResourceProvider],
) -> dict[str, AgentResourceProvider]:
    """Group configured providers by resource kind without losing members."""

    configured = tuple(providers)
    if not configured or any(
        not isinstance(provider, AgentResourceProvider) for provider in configured
    ):
        raise ManagedLocalError("agent resource provider composition is invalid")
    if len({provider.descriptor.key for provider in configured}) != len(configured):
        raise ManagedLocalError("agent resource provider identities must be unique")
    grouped: dict[str, list[AgentResourceProvider]] = {}
    for provider in configured:
        grouped.setdefault(provider.descriptor.kind, []).append(provider)
    return {
        kind: (
            members[0]
            if len(members) == 1
            else _CompositeAgentResourceProvider(members)
        )
        for kind, members in sorted(grouped.items())
    }


class AtomResourceProvider:
    """In-process CPU/memory provider accounting only configured capacity.

    It deliberately makes no enforcement claim.  A caller must remove external
    use from ``atoms`` before configuring this provider.
    """

    def __init__(
        self,
        descriptor: SchedulingComponentDescriptor,
        claim_contracts: Sequence[ResourceClaimContractDescriptor],
        atoms: Sequence[CapacityAtom],
    ) -> None:
        self.descriptor = descriptor
        self.claim_contracts = tuple(claim_contracts)
        if not self.claim_contracts:
            raise ManagedLocalError("provider claim contracts must not be empty")
        self._capacity = {atom.key: atom for atom in atoms}
        self._claims: dict[str, tuple[ClaimCommand, ClaimOutcome]] = {}
        self._revision = 1
        self._lock = RLock()

    def observe(self, request: ObserveRequest) -> ObserveResult:
        with self._lock:
            return self._observe(request)

    def worker_environment(self, command: ClaimCommand) -> dict[str, str]:
        """CPU and memory accounting have no worker-visible contribution."""
        self._require_provider_identity(command)
        return {}

    def restore_capacity_holding(self, command: ClaimCommand) -> None:
        """Restore one durable non-released claim before any fresh offer."""
        with self._lock:
            self._require_provider_identity(command)
            existing = self._claims.get(command.assignment.assignment_id)
            if existing is not None:
                if existing[0].claim != command.claim:
                    raise ManagedLocalError("retained provider claim conflicts")
                return
            used = {atom.key: atom.amount.fraction for atom in self._capacity.values()}
            for prior, state in self._claims.values():
                if state in {ClaimOutcome.PREPARED, ClaimOutcome.ACTIVE}:
                    for atom in prior.claim.atoms:
                        used[atom.key] = used.get(atom.key, 0) - atom.amount.fraction
            for atom in command.claim.atoms:
                if used.get(atom.key, 0) < atom.amount.fraction:
                    raise ManagedLocalError("retained provider claim exceeds capacity")
            self._claims[command.assignment.assignment_id] = (
                command,
                ClaimOutcome.PREPARED,
            )
            self._revision += 1

    def live_claim_ids_for_session(self, session_id: str) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                sorted(
                    command.assignment.claim_id
                    for command, state in self._claims.values()
                    if state in {ClaimOutcome.PREPARED, ClaimOutcome.ACTIVE}
                    and command.assignment.session_id == session_id
                )
            )

    def _observe(self, request: ObserveRequest) -> ObserveResult:
        if not isinstance(request, ObserveRequest):
            raise ManagedLocalError("observe request is invalid")
        used: dict[tuple[str, str], Fraction] = {}
        live_claim_ids: set[str] = set()
        for command, state in self._claims.values():
            if state not in {ClaimOutcome.PREPARED, ClaimOutcome.ACTIVE}:
                continue
            live_claim_ids.add(command.assignment.claim_id)
            for atom in command.claim.atoms:
                used[atom.key] = used.get(atom.key, Fraction(0)) + atom.amount.fraction
        result: list[CapacityAtom] = []
        for key, atom in self._capacity.items():
            available = atom.amount.fraction - used.get(key, Fraction(0))
            if available > 0:
                result.append(
                    CapacityAtom(
                        atom.owner_resource_kind,
                        atom.local_capacity_key,
                        ExactQuantity(available.numerator, available.denominator),
                        atom.unit,
                        atom.granularity,
                    )
                )
        return ObserveResult(
            operation_id=request.operation_id,
            availability_revision=(
                f"provider-{self.descriptor.kind}-"
                f"{self.descriptor.configuration_fingerprint}-{self._revision}"
            ),
            atoms=tuple(sorted(result, key=lambda item: item.key)),
            live_claim_ids=tuple(sorted(live_claim_ids)),
        )

    def prepare(self, command: ClaimCommand) -> ClaimResult:
        with self._lock:
            return self._prepare(command)

    def _prepare(self, command: ClaimCommand) -> ClaimResult:
        identity_error = self._provider_identity_error(command)
        if identity_error is not None:
            return identity_error
        if command.claim.contract not in self.claim_contracts:
            return ClaimResult(
                ClaimOutcome.INDETERMINATE,
                command.operation_id,
                command.claim.fingerprint,
                "claim contract is not supported by provider",
            )
        prior = self._claims.get(command.assignment.assignment_id)
        if prior is not None:
            if prior[0].claim.fingerprint != command.claim.fingerprint:
                return ClaimResult(
                    ClaimOutcome.INDETERMINATE,
                    command.operation_id,
                    command.claim.fingerprint,
                    "assignment claim conflicts",
                )
            return ClaimResult(
                prior[1], command.operation_id, command.claim.fingerprint
            )
        remaining = {
            atom.key: atom.amount.fraction
            for atom in self.observe(
                ObserveRequest(
                    command.assignment.agent_id,
                    command.assignment.session_id,
                    f"{command.operation_id}:observe",
                )
            ).atoms
        }
        if any(
            remaining.get(atom.key, 0) < atom.amount.fraction
            for atom in command.claim.atoms
        ):
            return ClaimResult(
                ClaimOutcome.DECLINED,
                command.operation_id,
                command.claim.fingerprint,
                "configured capacity unavailable",
            )
        self._claims[command.assignment.assignment_id] = (
            command,
            ClaimOutcome.PREPARED,
        )
        self._revision += 1
        return ClaimResult(
            ClaimOutcome.PREPARED, command.operation_id, command.claim.fingerprint
        )

    def reconcile(self, command: ClaimCommand) -> ClaimResult:
        with self._lock:
            return self._reconcile(command)

    def _reconcile(self, command: ClaimCommand) -> ClaimResult:
        identity_error = self._provider_identity_error(command)
        if identity_error is not None:
            return identity_error
        prior = self._claims.get(command.assignment.assignment_id)
        if prior is None:
            return ClaimResult(
                ClaimOutcome.INDETERMINATE,
                command.operation_id,
                command.claim.fingerprint,
                "no durable provider claim",
            )
        return ClaimResult(prior[1], command.operation_id, command.claim.fingerprint)

    def activate(self, command: ClaimCommand) -> ClaimResult:
        with self._lock:
            return self._activate(command)

    def _activate(self, command: ClaimCommand) -> ClaimResult:
        identity_error = self._provider_identity_error(command)
        if identity_error is not None:
            return identity_error
        prior = self._claims.get(command.assignment.assignment_id)
        if prior is None or prior[0].claim.fingerprint != command.claim.fingerprint:
            return ClaimResult(
                ClaimOutcome.INDETERMINATE,
                command.operation_id,
                command.claim.fingerprint,
                "claim not prepared",
            )
        if prior[1] is ClaimOutcome.RELEASED:
            return ClaimResult(
                ClaimOutcome.INDETERMINATE,
                command.operation_id,
                command.claim.fingerprint,
                "claim released",
            )
        self._claims[command.assignment.assignment_id] = (command, ClaimOutcome.ACTIVE)
        self._revision += 1
        return ClaimResult(
            ClaimOutcome.ACTIVE, command.operation_id, command.claim.fingerprint
        )

    def abort(self, command: ClaimCommand) -> ClaimResult:
        with self._lock:
            return self._release(command)

    def release(self, command: ClaimCommand) -> ClaimResult:
        with self._lock:
            return self._release(command)

    def _release(self, command: ClaimCommand) -> ClaimResult:
        identity_error = self._provider_identity_error(command)
        if identity_error is not None:
            return identity_error
        prior = self._claims.get(command.assignment.assignment_id)
        if (
            prior is not None
            and prior[0].claim.fingerprint != command.claim.fingerprint
        ):
            return ClaimResult(
                ClaimOutcome.INDETERMINATE,
                command.operation_id,
                command.claim.fingerprint,
                "assignment claim conflicts",
            )
        if prior is not None and prior[1] is ClaimOutcome.RELEASED:
            return ClaimResult(
                ClaimOutcome.RELEASED,
                command.operation_id,
                command.claim.fingerprint,
            )
        self._claims[command.assignment.assignment_id] = (
            command,
            ClaimOutcome.RELEASED,
        )
        self._revision += 1
        return ClaimResult(
            ClaimOutcome.RELEASED, command.operation_id, command.claim.fingerprint
        )

    def _provider_identity_error(self, command: ClaimCommand) -> ClaimResult | None:
        if command.provider_descriptor == self.descriptor:
            return None
        return ClaimResult(
            ClaimOutcome.INDETERMINATE,
            command.operation_id,
            command.claim.fingerprint,
            "provider descriptor does not match configured provider",
        )

    def _require_provider_identity(self, command: ClaimCommand) -> None:
        if command.provider_descriptor != self.descriptor:
            raise ManagedLocalError(
                "retained claim provider descriptor conflicts with configuration"
            )


class CpuResourceProvider(AtomResourceProvider):
    """Configured CPU accounting provider; it does not claim OS enforcement."""

    def __init__(
        self,
        atoms: Sequence[CapacityAtom],
        *,
        configuration_fingerprint: str = "configured",
    ) -> None:
        super().__init__(
            SchedulingComponentDescriptor(
                "cpu",
                1,
                "1",
                "loom.cpu.provider.v1",
                configuration_fingerprint,
            ),
            (ResourceClaimContractDescriptor("cpu", 1, "loom.cpu.claim.v1"),),
            atoms,
        )


class MemoryResourceProvider(AtomResourceProvider):
    """Configured memory accounting provider; it does not claim an RSS cap."""

    def __init__(
        self,
        atoms: Sequence[CapacityAtom],
        *,
        configuration_fingerprint: str = "configured",
    ) -> None:
        super().__init__(
            SchedulingComponentDescriptor(
                "memory",
                1,
                "1",
                "loom.memory.provider.v1",
                configuration_fingerprint,
            ),
            (ResourceClaimContractDescriptor("memory", 1, "loom.memory.claim.v1"),),
            atoms,
        )


def _configured_provider_descriptor(
    resource_kind: str,
    atoms: Sequence[CapacityAtom],
    *,
    bindings: Mapping[str, str] | None = None,
) -> SchedulingComponentDescriptor:
    """Build safe identity for one concrete provider configuration.

    Private binding values contribute to the digest but are never serialized.
    A mapping change therefore fences retained claims without disclosing the
    agent-local device path, token, or runtime selector that changed.
    """

    configured_atoms = tuple(sorted(atoms, key=lambda item: item.key))
    if any(atom.owner_resource_kind != resource_kind for atom in configured_atoms):
        raise ManagedLocalError("provider atoms must match its resource kind")
    private_bindings = dict(bindings or {})
    if private_bindings and set(private_bindings) != {
        atom.local_capacity_key for atom in configured_atoms
    }:
        raise ManagedLocalError("provider bindings must exactly cover its atoms")
    payload = {
        "resource_kind": resource_kind,
        "atoms": [atom.to_dict() for atom in configured_atoms],
        "bindings": [
            {"capacity_key": key, "private_value": private_bindings[key]}
            for key in sorted(private_bindings)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    configuration_fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return SchedulingComponentDescriptor(
        resource_kind,
        1,
        "1",
        f"loom.{resource_kind}.provider.v1",
        configuration_fingerprint,
    )


class GpuResourceProvider(AtomResourceProvider):
    """Configured GPU accounting plus private exact-claim binding lookup.

    The mapping intentionally stores only on the agent.  Coordinator-visible
    claims name configured IDs through atoms, never their device paths/tokens.
    """

    def __init__(
        self,
        claim_contracts: Sequence[ResourceClaimContractDescriptor],
        atoms: Sequence[CapacityAtom],
        *,
        bindings: Mapping[str, str],
        occupancy_monitor: GpuOccupancyMonitor | None = None,
    ) -> None:
        super().__init__(
            _configured_provider_descriptor("gpu", atoms, bindings=bindings),
            claim_contracts,
            atoms,
        )
        self._bindings = dict(bindings)
        if set(self._bindings) != {atom.local_capacity_key for atom in atoms}:
            raise ManagedLocalError("GPU bindings must exactly cover configured atoms")
        if any(not value or "\0" in value for value in self._bindings.values()):
            raise ManagedLocalError("GPU binding values are invalid")
        if occupancy_monitor is not None and not isinstance(
            occupancy_monitor, GpuOccupancyMonitor
        ):
            raise ManagedLocalError("GPU occupancy monitor is invalid")
        if occupancy_monitor is not None and set(
            occupancy_monitor.selected_uuids
        ) != set(self._bindings.values()):
            raise ManagedLocalError(
                "GPU occupancy monitor UUIDs conflict with bindings"
            )
        self._occupancy_monitor = occupancy_monitor
        self._occupancy_decision: tuple[tuple[str, bool, str], ...] | None = None

    @property
    def configured_atoms(self) -> tuple[CapacityAtom, ...]:
        """Stable device capacity for inventory and coordinator upper bounds."""
        return tuple(sorted(self._capacity.values(), key=lambda atom: atom.key))

    def refresh_occupancy(self, force: bool = False) -> GpuOccupancySnapshot | None:
        """Refresh the optional local process cache without holding claim state."""

        if self._occupancy_monitor is None:
            return None
        return self._occupancy_monitor.refresh(force=force)

    def _observe(self, request: ObserveRequest) -> ObserveResult:
        base = super()._observe(request)
        if self._occupancy_monitor is None:
            return base
        snapshot = self._occupancy_monitor.cached_snapshot()
        held_keys = {
            atom.local_capacity_key
            for command, outcome in self._claims.values()
            if outcome in {ClaimOutcome.PREPARED, ClaimOutcome.ACTIVE}
            for atom in command.claim.atoms
        }
        available_by_key = {atom.local_capacity_key: atom for atom in base.atoms}
        statuses: list[ResourceAvailabilityStatus] = []
        filtered: list[CapacityAtom] = []
        for key, uuid in sorted(self._bindings.items()):
            observed_at = snapshot.observed_at if snapshot is not None else None
            if key in held_keys:
                available, reason = False, "loom_claimed"
            elif snapshot is None:
                available, reason = False, "observation_unavailable"
            elif not self._occupancy_monitor.snapshot_is_fresh(snapshot):
                available, reason = False, "observation_stale"
            else:
                observed = snapshot.for_uuid(uuid)
                if observed is None or observed.reason_code == "device_missing":
                    available, reason = False, "device_missing"
                elif not observed.query_succeeded:
                    available, reason = False, "observation_unavailable"
                elif observed.has_gpu_process:
                    available, reason = (
                        self._occupancy_monitor.policy.external_process_policy
                        == "allow",
                        "external_process_detected",
                    )
                else:
                    available, reason = True, "available"
            statuses.append(
                ResourceAvailabilityStatus("gpu", key, available, reason, observed_at)
            )
            if available and key in available_by_key:
                filtered.append(available_by_key[key])
        decision = tuple(
            (item.local_capacity_key, item.available, item.reason_code)
            for item in statuses
        )
        if decision != self._occupancy_decision:
            self._occupancy_decision = decision
            self._revision += 1
        return ObserveResult(
            request.operation_id,
            (
                f"provider-{self.descriptor.kind}-"
                f"{self.descriptor.configuration_fingerprint}-{self._revision}"
            ),
            tuple(filtered),
            base.live_claim_ids,
            tuple(statuses),
        )

    @_cooperative
    def prepare(self, command: ClaimCommand) -> Generator[_Progress, Any, ClaimResult]:
        if self._occupancy_monitor is None:
            return super().prepare(command)
        with self._lock:
            identity_error = self._provider_identity_error(command)
            if identity_error is not None:
                return identity_error
            prior = self._claims.get(command.assignment.assignment_id)
            if prior is not None:
                if prior[0].claim.fingerprint != command.claim.fingerprint:
                    return ClaimResult(
                        ClaimOutcome.INDETERMINATE,
                        command.operation_id,
                        command.claim.fingerprint,
                        "assignment claim conflicts",
                    )
                return ClaimResult(
                    prior[1], command.operation_id, command.claim.fingerprint
                )
        monitor = self._occupancy_monitor
        # Admission always samples afresh, independently of the offer cache.
        # Only sampling leaves the state owner; applying facts and the claim's
        # freshness/fail-closed decision remain one manager-side transition.
        snapshot = yield from _external(
            "bulk",
            _sample_gpu_occupancy,
            monitor._observer,
            monitor.selected_uuids,
            monitor._utc_clock,
            monitor._monotonic_clock,
        )
        monitor._apply_snapshot(snapshot)
        with self._lock:
            result = self._prepare(command)
            if result.outcome is not ClaimOutcome.DECLINED:
                return result
            observed = self._observe(
                ObserveRequest(
                    command.assignment.agent_id,
                    command.assignment.session_id,
                    f"{command.operation_id}:decision",
                )
            )
            status_by_key = {
                item.local_capacity_key: item for item in observed.resource_status
            }
            reason = next(
                (
                    status_by_key[atom.local_capacity_key].reason_code
                    for atom in command.claim.atoms
                    if atom.local_capacity_key in status_by_key
                    and not status_by_key[atom.local_capacity_key].available
                ),
                result.detail,
            )
            return ClaimResult(
                result.outcome,
                result.operation_id,
                result.claim_fingerprint,
                reason,
            )

    def binding_for_claim(self, command: ClaimCommand) -> tuple[str, ...]:
        """Return private worker bindings only for the exact active claim."""
        with self._lock:
            self._require_provider_identity(command)
            prior = self._claims.get(command.assignment.assignment_id)
            if prior is None or prior[1] is not ClaimOutcome.ACTIVE:
                raise ManagedLocalError("GPU claim is not active")
            if prior[0].claim.fingerprint != command.claim.fingerprint:
                raise ManagedLocalError(
                    "GPU claim binding differs from journalled claim"
                )
            try:
                return tuple(
                    self._bindings[atom.local_capacity_key]
                    for atom in command.claim.atoms
                )
            except KeyError as exc:
                raise ManagedLocalError(
                    "GPU configured binding is unavailable"
                ) from exc

    def worker_environment(self, command: ClaimCommand) -> dict[str, str]:
        """Return the sole GPU environment value derived from an active claim."""
        return {"CUDA_VISIBLE_DEVICES": ",".join(self.binding_for_claim(command))}
