"""Durable, assignment-scoped local admission primitives.

This module is deliberately independent of the legacy ``run_stage_job`` path.
It is the small local half of the Stage 29 saga: coordinator code owns logical
reservations, this journal owns physical claims and the worker receives one
already-granted assignment.  In particular, none of these operations allocate
an attempt or take a run lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Protocol, cast

from loom.pipeline.executors import Executor
from loom.pipeline.orchestration import SchedulingProjectionState, StageWorkRecord
from loom.pipeline.resources import ResourceValidatorRegistry
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LegacyRunStore, LifecycleReason, OutputCommit
from loom.pipeline.stores.authority import (
    ExecutionFence,
    PreparedAttemptExecutionAuthority,
)
from loom.plugins.entrypoints import PluginRecord
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import utc_timestamp

from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    STAGE_WORKER_RESULT_SCHEMA_VERSION,
    ExecutionFailure,
    StageWorkerRequest,
    StageWorkerResult,
)
from loom.pipeline.execution.stage_worker import (
    ArtifactStoreFactory,
    execute_stage_worker_request,
)


class ManagedLocalError(ValueError):
    """An assignment, journal, or provider invariant was violated."""


class ManagedProcessStartError(ManagedLocalError):
    """The launcher proved that no managed root was created or can later run."""


class ClaimOutcome(StrEnum):
    PREPARED = "prepared"
    DECLINED = "declined"
    ACTIVE = "active"
    RELEASED = "released"
    INDETERMINATE = "indeterminate"


class AssignmentState(StrEnum):
    REQUEST_DURABLE = "request_durable"
    DECLINED = "declined"
    PREPARE_UNKNOWN = "prepare_unknown"
    PREPARED = "prepared"
    ACCEPTED = "accepted"
    GRANTED = "granted"
    ACTIVE = "active"
    ACTIVATION_UNKNOWN = "activation_unknown"
    START_INTENT = "start_intent"
    PROCESS_STARTED = "process_started"
    START_FAILED = "start_failed"
    START_UNKNOWN = "start_unknown"
    RESULT_DURABLE = "result_durable"
    TERMINAL_ACKNOWLEDGED = "terminal_acknowledged"
    PROVIDERS_RELEASED = "providers_released"
    RELEASED = "released"


_AGENT_SUCCESS_ORDER = (
    AssignmentState.REQUEST_DURABLE,
    AssignmentState.PREPARED,
    AssignmentState.ACCEPTED,
    AssignmentState.GRANTED,
    AssignmentState.ACTIVE,
    AssignmentState.START_INTENT,
    AssignmentState.PROCESS_STARTED,
    AssignmentState.RESULT_DURABLE,
    AssignmentState.TERMINAL_ACKNOWLEDGED,
    AssignmentState.PROVIDERS_RELEASED,
    AssignmentState.RELEASED,
)
_COORDINATOR_SUCCESS_ORDER = (
    "reserved",
    "bound",
    "accepted",
    "granted",
    "running",
    "terminal",
    "logical_released",
    "released",
)


@dataclass(frozen=True, slots=True)
class ManagedAssignment:
    """The closed managed-agent target and the exact Phase 1 attempt binding."""

    assignment_id: str
    run_uri: str
    stage_work_id: str
    stage_name: str
    attempt: int
    attempt_id: str
    agent_id: str
    session_id: str
    offer_id: str
    claim_id: str

    def __post_init__(self) -> None:
        for name in (
            "assignment_id",
            "run_uri",
            "stage_work_id",
            "stage_name",
            "attempt_id",
            "agent_id",
            "session_id",
            "offer_id",
            "claim_id",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ManagedLocalError(f"{name} must be a non-empty string")
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise ManagedLocalError("attempt must be a positive integer")


@dataclass(frozen=True, slots=True)
class ManagedExecutionReceipt:
    assignment: ManagedAssignment
    fence: ExecutionFence
    worker_result: StageWorkerResult
    output_commit: OutputCommit | None
    availability_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, ManagedAssignment):
            raise ManagedLocalError("receipt assignment is invalid")
        if not isinstance(self.fence, ExecutionFence):
            raise ManagedLocalError("receipt fence is invalid")
        if not isinstance(self.worker_result, StageWorkerResult):
            raise ManagedLocalError("receipt worker result is invalid")
        if self.output_commit is not None and not isinstance(
            self.output_commit, OutputCommit
        ):
            raise ManagedLocalError("receipt output commit is invalid")
        if (
            not isinstance(self.availability_revision, str)
            or not self.availability_revision
        ):
            raise ManagedLocalError("receipt availability revision is required")


class _ManagedWorkerHandle:
    """Same-process containment handle for one gated managed worker thread."""

    def __init__(
        self,
        process_execution_id: str,
        worker: Callable[[], StageWorkerResult],
    ) -> None:
        self.process_execution_id = process_execution_id
        self._worker = worker
        self._run_gate = Event()
        self._result: StageWorkerResult | None = None
        self._error: BaseException | None = None
        self._cancel_before_run = False
        self._cancellation_seen = False
        self._thread = Thread(
            target=self._run,
            name=f"loom-managed-{process_execution_id}",
            daemon=False,
        )

    def start(self) -> None:
        try:
            self._thread.start()
        except RuntimeError as exc:
            raise ManagedProcessStartError("managed root was not created") from exc

    def release_to_run(self) -> None:
        self._run_gate.set()

    def cancel_before_run(self) -> None:
        self._cancel_before_run = True
        self._cancellation_seen = True
        self._run_gate.set()
        self._thread.join()

    @property
    def cancellation_seen(self) -> bool:
        return self._cancellation_seen

    def wait(
        self, cancellation_requested: Callable[[], bool] | None = None
    ) -> StageWorkerResult:
        while self._thread.is_alive():
            self._thread.join(timeout=0.05)
            if cancellation_requested is not None and cancellation_requested():
                self._cancellation_seen = True
        if cancellation_requested is not None and cancellation_requested():
            self._cancellation_seen = True
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise ManagedLocalError("managed root exited without a worker result")
        return self._result

    def _run(self) -> None:
        self._run_gate.wait()
        if self._cancel_before_run:
            return
        try:
            self._result = self._worker()
        except BaseException as exc:  # noqa: BLE001 - retained for owner reconciliation.
            self._error = exc


@dataclass(frozen=True, slots=True)
class ClaimCommand:
    """Idempotent provider command; its operation ID is stable across replay."""

    assignment: ManagedAssignment
    operation_id: str
    claim: ResourceClaim
    provider_descriptor: SchedulingComponentDescriptor

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, ManagedAssignment):
            raise ManagedLocalError("command assignment is invalid")
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ManagedLocalError("operation_id must be a non-empty string")
        if not isinstance(self.claim, ResourceClaim):
            raise ManagedLocalError("claim must be a ResourceClaim")
        if not isinstance(self.provider_descriptor, SchedulingComponentDescriptor):
            raise ManagedLocalError(
                "provider_descriptor must be a scheduling component descriptor"
            )
        if self.provider_descriptor.kind != self.claim.resource_kind:
            raise ManagedLocalError(
                "provider descriptor kind must match the claim resource kind"
            )


@dataclass(frozen=True, slots=True)
class ClaimResult:
    outcome: ClaimOutcome
    operation_id: str
    claim_fingerprint: str
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", ClaimOutcome(self.outcome))
        for name in ("operation_id", "claim_fingerprint"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ManagedLocalError(f"{name} must be a non-empty string")
        if self.detail is not None and not isinstance(self.detail, str):
            raise ManagedLocalError("detail must be a string when set")


@dataclass(frozen=True, slots=True)
class ObserveRequest:
    agent_id: str
    session_id: str
    operation_id: str

    def __post_init__(self) -> None:
        for name in ("agent_id", "session_id", "operation_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ManagedLocalError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ObserveResult:
    operation_id: str
    availability_revision: str
    atoms: tuple[CapacityAtom, ...]
    live_claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ManagedLocalError("operation_id must be a non-empty string")
        if (
            not isinstance(self.availability_revision, str)
            or not self.availability_revision
        ):
            raise ManagedLocalError("availability_revision must be a non-empty string")
        if any(not isinstance(atom, CapacityAtom) for atom in self.atoms):
            raise ManagedLocalError("observe atoms must be CapacityAtom values")
        if any(
            not isinstance(value, str) or not value for value in self.live_claim_ids
        ):
            raise ManagedLocalError("live claim IDs must be non-empty strings")
        if len(set(self.live_claim_ids)) != len(self.live_claim_ids):
            raise ManagedLocalError("live claim IDs must be unique")


@dataclass(frozen=True, slots=True)
class ManagedOfferSnapshot:
    """Coordinator-retained, one-use view of one agent availability revision."""

    agent_id: str
    session_id: str
    offer_revision: str
    snapshot_revision: str
    inventory_revision: str
    availability_revision: str
    component_descriptors: tuple[SchedulingComponentDescriptor, ...]
    provider_descriptors: tuple[SchedulingComponentDescriptor, ...]
    atoms: tuple[CapacityAtom, ...]
    reflected_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "agent_id",
            "session_id",
            "offer_revision",
            "snapshot_revision",
            "inventory_revision",
            "availability_revision",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ManagedLocalError(f"{name} must be a non-empty string")
        if not self.component_descriptors or any(
            not isinstance(item, SchedulingComponentDescriptor)
            for item in self.component_descriptors
        ):
            raise ManagedLocalError("offer component descriptors must not be empty")
        if len({item.kind for item in self.component_descriptors}) != len(
            self.component_descriptors
        ):
            raise ManagedLocalError("offer component descriptor kinds must be unique")
        if not self.provider_descriptors or any(
            not isinstance(item, SchedulingComponentDescriptor)
            for item in self.provider_descriptors
        ):
            raise ManagedLocalError("offer provider descriptors must not be empty")
        if len({item.kind for item in self.provider_descriptors}) != len(
            self.provider_descriptors
        ):
            raise ManagedLocalError("offer provider descriptor kinds must be unique")
        if any(not isinstance(item, CapacityAtom) for item in self.atoms) or len(
            {item.key for item in self.atoms}
        ) != len(self.atoms):
            raise ManagedLocalError("offer capacity atoms must be unique")
        component_kinds = {item.kind for item in self.component_descriptors}
        provider_kinds = {item.kind for item in self.provider_descriptors}
        atom_kinds = {item.owner_resource_kind for item in self.atoms}
        if component_kinds != provider_kinds:
            raise ManagedLocalError(
                "offer planner and provider descriptor kinds must match"
            )
        if not atom_kinds.issubset(component_kinds):
            raise ManagedLocalError(
                "offer capacity atom owners require planner and provider descriptors"
            )
        if any(
            not isinstance(value, str) or not value
            for value in self.reflected_claim_ids
        ) or len(set(self.reflected_claim_ids)) != len(self.reflected_claim_ids):
            raise ManagedLocalError(
                "offer reflected claim IDs must be non-empty and unique"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "offer_revision": self.offer_revision,
            "snapshot_revision": self.snapshot_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "component_descriptors": [
                item.to_dict() for item in self.component_descriptors
            ],
            "provider_descriptors": [
                item.to_dict() for item in self.provider_descriptors
            ],
            "atoms": [item.to_dict() for item in self.atoms],
            "reflected_claim_ids": list(self.reflected_claim_ids),
        }


class AgentResourceProvider(Protocol):
    """Versioned physical-resource lifecycle; outcomes never imply OS isolation."""

    descriptor: SchedulingComponentDescriptor
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def observe(self, request: ObserveRequest) -> ObserveResult: ...
    def prepare(self, command: ClaimCommand) -> ClaimResult: ...
    def reconcile(self, command: ClaimCommand) -> ClaimResult: ...
    def activate(self, command: ClaimCommand) -> ClaimResult: ...
    def abort(self, command: ClaimCommand) -> ClaimResult: ...
    def release(self, command: ClaimCommand) -> ClaimResult: ...


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


class SQLiteAgentJournal:
    """Durable local journal for the agent-owned side of an assignment.

    The journal is intentionally append/replay oriented.  ``record_event``
    makes a fact durable before it can be delivered and refuses an event gap.
    """

    def __init__(self, path: str | Path, *, _allow_initialize: bool = True) -> None:
        self.path = Path(path)
        self._allow_initialize = _allow_initialize
        self._process_handles: dict[str, _ManagedWorkerHandle] = {}
        self._process_handles_lock = RLock()

    def _initialize(self) -> None:
        """Create the current journal schema at an explicit owner boundary."""

        with self._transaction():
            pass

    def _open_existing(self) -> None:
        """Verify the current journal without creating or repairing it."""

        if not self.path.is_file():
            raise ManagedLocalError("agent journal is missing")
        with _connect_sqlite(self.path, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            _require_agent_journal_schema(conn)

    def persist_request(
        self, assignment: ManagedAssignment, request: Mapping[str, PlainData]
    ) -> AssignmentState:
        payload = _json(request)
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT request_json, state FROM assignments WHERE assignment_id = ?",
                (assignment.assignment_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO assignments (assignment_id, identity_json, request_json, state, grant_fence, process_execution_id, result_json) VALUES (?, ?, ?, ?, NULL, NULL, NULL)",
                    (
                        assignment.assignment_id,
                        _json(_assignment_dict(assignment)),
                        payload,
                        AssignmentState.REQUEST_DURABLE.value,
                    ),
                )
                return AssignmentState.REQUEST_DURABLE
            if row["request_json"] != payload:
                raise ManagedLocalError(
                    "assignment request conflicts with durable request"
                )
            return AssignmentState(row["state"])

    def prepare_composite(
        self,
        assignment: ManagedAssignment,
        commands: Sequence[ClaimCommand],
        providers: Mapping[str, AgentResourceProvider],
    ) -> AssignmentState:
        self._require_request(assignment)
        ordered = tuple(sorted(commands, key=lambda item: item.claim.resource_kind))
        if not ordered:
            raise ManagedLocalError("composite claim must not be empty")
        encoded_commands = _json(
            {"commands": [_claim_command_dict(command) for command in ordered]}
        )
        with self._transaction() as conn:
            row = self._assignment(conn, assignment.assignment_id)
            state = AssignmentState(row["state"])
            if (
                row["claims_json"] is not None
                and row["claims_json"] != encoded_commands
            ):
                raise ManagedLocalError("assignment claim commands conflict")
            if row["claims_json"] is None:
                conn.execute(
                    "UPDATE assignments SET claims_json = ? WHERE assignment_id = ?",
                    (encoded_commands, assignment.assignment_id),
                )
            if bool(row["declined"]):
                return AssignmentState.DECLINED
            if state in {
                AssignmentState.PREPARED,
                AssignmentState.ACCEPTED,
                AssignmentState.GRANTED,
                AssignmentState.ACTIVE,
                AssignmentState.ACTIVATION_UNKNOWN,
                AssignmentState.START_INTENT,
                AssignmentState.PROCESS_STARTED,
                AssignmentState.START_FAILED,
                AssignmentState.START_UNKNOWN,
                AssignmentState.RESULT_DURABLE,
                AssignmentState.TERMINAL_ACKNOWLEDGED,
                AssignmentState.PROVIDERS_RELEASED,
                AssignmentState.RELEASED,
            }:
                return state
            if state is AssignmentState.DECLINED:
                return state
            if state not in {
                AssignmentState.REQUEST_DURABLE,
                AssignmentState.PREPARE_UNKNOWN,
            }:
                raise ManagedLocalError("assignment cannot prepare in current state")
            reconcile = state is AssignmentState.PREPARE_UNKNOWN

        prepared: list[tuple[AgentResourceProvider, ClaimCommand]] = []
        for command in ordered:
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            result = _provider_call(
                provider.reconcile if reconcile else provider.prepare,
                command,
            )
            if result.outcome is not ClaimOutcome.PREPARED:
                aborts = [
                    _provider_call(previous.abort, previous_command)
                    for previous, previous_command in reversed(prepared)
                ]
                aborts_complete = all(
                    item.outcome is ClaimOutcome.RELEASED for item in aborts
                )
                if result.outcome is ClaimOutcome.DECLINED and aborts_complete:
                    return self._set_declined(assignment.assignment_id)
                return self._set_state(
                    assignment.assignment_id, AssignmentState.PREPARE_UNKNOWN
                )
            prepared.append((provider, command))
        return self._set_state(assignment.assignment_id, AssignmentState.PREPARED)

    def accept(self, assignment_id: str) -> AssignmentState:
        return self._advance(
            assignment_id, AssignmentState.PREPARED, AssignmentState.ACCEPTED
        )

    def decline_before_prepare(self, assignment_id: str) -> AssignmentState:
        """Prove a durable request acquired no provider claims."""

        return self._advance(
            assignment_id, AssignmentState.REQUEST_DURABLE, AssignmentState.DECLINED
        )

    def abort_pregrant(
        self,
        assignment_id: str,
        commands: Sequence[ClaimCommand],
        providers: Mapping[str, AgentResourceProvider],
    ) -> AssignmentState:
        """Release every exact prepared claim before remote grant."""

        with self._transaction() as conn:
            state = AssignmentState(self._assignment(conn, assignment_id)["state"])
            if state is AssignmentState.DECLINED:
                return state
            if state not in {AssignmentState.PREPARED, AssignmentState.ACCEPTED}:
                raise ManagedLocalError("only prepared pre-grant claims can be aborted")
        for command in sorted(
            commands, key=lambda item: item.claim.resource_kind, reverse=True
        ):
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            if (
                _provider_call(provider.abort, command).outcome
                is not ClaimOutcome.RELEASED
            ):
                raise ManagedLocalError("pre-grant claim abort is indeterminate")
        return self._set_declined(assignment_id)

    def cancel_pregrant(
        self, assignment_id: str, providers: Mapping[str, AgentResourceProvider]
    ) -> AssignmentState:
        """Settle a durable no-start local claim using its retained exact commands."""

        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if state is AssignmentState.REQUEST_DURABLE:
                conn.execute(
                    "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                    (AssignmentState.DECLINED.value, assignment_id),
                )
                return AssignmentState.DECLINED
            if state is AssignmentState.DECLINED:
                return state
            if state not in {AssignmentState.PREPARED, AssignmentState.ACCEPTED}:
                raise ManagedLocalError("local assignment is not proven pre-grant")
            identity = json.loads(cast(str, row["identity_json"]))
            commands = json.loads(cast(str, row["claims_json"]))
        values = commands.get("commands") if isinstance(commands, dict) else None
        if not isinstance(values, list):
            raise ManagedLocalError("retained local claim commands are invalid")
        assignment = ManagedAssignment(
            assignment_id=cast(str, identity["assignment_id"]),
            run_uri=cast(str, identity["run_uri"]),
            stage_work_id=cast(str, identity["stage_work_id"]),
            stage_name=cast(str, identity["stage_name"]),
            attempt=cast(int, identity["attempt"]),
            attempt_id=cast(str, identity["attempt_id"]),
            agent_id=cast(str, identity["agent_id"]),
            session_id=cast(str, identity["session_id"]),
            offer_id=cast(str, identity["offer_id"]),
            claim_id=cast(str, identity["claim_id"]),
        )
        return self.abort_pregrant(
            assignment_id,
            tuple(_claim_command_from_dict(assignment, value) for value in values),
            providers,
        )

    def grant(self, assignment_id: str, fence: str) -> AssignmentState:
        if not fence:
            raise ManagedLocalError("grant fence is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            current = row["grant_fence"]
            if current is not None and current != fence:
                raise ManagedLocalError("assignment grant fence conflicts")
            if _agent_at_or_after(state, AssignmentState.GRANTED):
                return state
            if state is not AssignmentState.ACCEPTED:
                raise ManagedLocalError("assignment is not accepted")
            conn.execute(
                "UPDATE assignments SET state = ?, grant_fence = ? WHERE assignment_id = ?",
                (AssignmentState.GRANTED.value, fence, assignment_id),
            )
            return AssignmentState.GRANTED

    def activate_composite(
        self,
        assignment_id: str,
        commands: Sequence[ClaimCommand],
        providers: Mapping[str, AgentResourceProvider],
    ) -> AssignmentState:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if _agent_at_or_after(state, AssignmentState.ACTIVE):
                return state
            if state not in {
                AssignmentState.GRANTED,
                AssignmentState.ACTIVATION_UNKNOWN,
            }:
                raise ManagedLocalError("assignment is not grant-activatable")
            reconcile = state is AssignmentState.ACTIVATION_UNKNOWN
        for command in sorted(commands, key=lambda item: item.claim.resource_kind):
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            result = _provider_call(
                provider.reconcile if reconcile else provider.activate,
                command,
            )
            if result.outcome is not ClaimOutcome.ACTIVE:
                return self._set_state(
                    assignment_id, AssignmentState.ACTIVATION_UNKNOWN
                )
        return self._set_state(assignment_id, AssignmentState.ACTIVE)

    def start_once(
        self,
        assignment_id: str,
        process_execution_id: str,
        launcher: Callable[[], str],
    ) -> str:
        """Persist intent before exactly one launcher invocation."""
        if not isinstance(process_execution_id, str) or not process_execution_id:
            raise ManagedLocalError("process_execution_id is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if _agent_at_or_after(state, AssignmentState.PROCESS_STARTED):
                existing = str(row["process_execution_id"])
                if existing != process_execution_id:
                    raise ManagedLocalError("process execution identity conflicts")
                return existing
            if state in {AssignmentState.START_INTENT, AssignmentState.START_UNKNOWN}:
                raise ManagedLocalError(
                    "launch outcome is unknown and cannot be invoked again"
                )
            if state is not AssignmentState.ACTIVE:
                raise ManagedLocalError("assignment is not active for launch")
            conn.execute(
                "UPDATE assignments SET state = ?, process_execution_id = ? "
                "WHERE assignment_id = ?",
                (
                    AssignmentState.START_INTENT.value,
                    process_execution_id,
                    assignment_id,
                ),
            )
        try:
            process_id = launcher()
        except ManagedProcessStartError:
            self._set_start_failed(assignment_id)
            raise
        except Exception:
            self._set_state(assignment_id, AssignmentState.START_UNKNOWN)
            raise
        if not isinstance(process_id, str) or not process_id:
            self._set_start_failed(assignment_id)
            raise ManagedProcessStartError("launcher proved no process identifier")
        if process_id != process_execution_id:
            self._set_state(assignment_id, AssignmentState.START_UNKNOWN)
            raise ManagedLocalError("launcher returned an unexpected process identity")
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (AssignmentState.PROCESS_STARTED.value, assignment_id),
            )
        return process_id

    def confirm_supervised_start(
        self, assignment_id: str, process_execution_id: str
    ) -> AssignmentState:
        """Join an exact durable supervisor receipt after application restart."""

        if not isinstance(process_execution_id, str) or not process_execution_id:
            raise ManagedLocalError("process_execution_id is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            current = row["process_execution_id"]
            if current is None or str(current) != process_execution_id:
                raise ManagedLocalError("process execution identity conflicts")
            if _agent_at_or_after(state, AssignmentState.PROCESS_STARTED):
                return state
            if state not in {
                AssignmentState.START_INTENT,
                AssignmentState.START_UNKNOWN,
            }:
                raise ManagedLocalError(
                    "assignment has no supervised start intent to confirm"
                )
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (AssignmentState.PROCESS_STARTED.value, assignment_id),
            )
        return AssignmentState.PROCESS_STARTED

    def attach_process_handle(
        self, assignment_id: str, handle: _ManagedWorkerHandle
    ) -> None:
        if not isinstance(handle, _ManagedWorkerHandle):
            raise ManagedLocalError("managed process handle is invalid")
        with self._process_handles_lock:
            current = self._process_handles.get(assignment_id)
            if current is not None and current is not handle:
                raise ManagedLocalError("managed process handle conflicts")
            self._process_handles[assignment_id] = handle

    def process_handle(self, assignment_id: str) -> _ManagedWorkerHandle | None:
        with self._process_handles_lock:
            return self._process_handles.get(assignment_id)

    def definitive_start_failed(self, assignment_id: str) -> bool:
        with self._transaction() as conn:
            return bool(self._assignment(conn, assignment_id)["start_failed"])

    def record_event(
        self,
        assignment_id: str,
        sequence: int,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> int:
        if sequence < 1 or not event_id:
            raise ManagedLocalError("event sequence and ID are required")
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT event_id, payload_json FROM events WHERE assignment_id = ? AND sequence = ?",
                (assignment_id, sequence),
            ).fetchone()
            encoded = _json(payload)
            if existing is not None:
                if (
                    existing["event_id"] != event_id
                    or existing["payload_json"] != encoded
                ):
                    raise ManagedLocalError("event replay conflicts")
                return sequence
            expected = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0]
            )
            if sequence != expected:
                raise ManagedLocalError("agent event sequence gap")
            conn.execute(
                "INSERT INTO events (assignment_id, sequence, event_id, payload_json, acknowledged_sequence) VALUES (?, ?, ?, ?, NULL)",
                (assignment_id, sequence, event_id, encoded),
            )
            return sequence

    def append_event(
        self,
        assignment_id: str,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> int:
        if not event_id:
            raise ManagedLocalError("event ID is required")
        encoded = _json(payload)
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            existing = conn.execute(
                "SELECT sequence, payload_json FROM events "
                "WHERE assignment_id = ? AND event_id = ?",
                (assignment_id, event_id),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != encoded:
                    raise ManagedLocalError("event replay conflicts")
                return cast(int, existing["sequence"])
            sequence = cast(
                int,
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0],
            )
            conn.execute(
                "INSERT INTO events "
                "(assignment_id, sequence, event_id, payload_json, acknowledged_sequence) "
                "VALUES (?, ?, ?, ?, NULL)",
                (assignment_id, sequence, event_id, encoded),
            )
            return sequence

    def acknowledge(self, assignment_id: str, sequence: int) -> int:
        with self._transaction() as conn:
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM events WHERE assignment_id = ? AND sequence <= ?",
                    (assignment_id, sequence),
                ).fetchone()[0]
            )
            if count != sequence:
                raise ManagedLocalError("cannot acknowledge an event gap")
            conn.execute(
                "UPDATE events SET acknowledged_sequence = ? WHERE assignment_id = ? AND sequence <= ?",
                (sequence, assignment_id, sequence),
            )
            return sequence

    def record_result(
        self, assignment_id: str, result: Mapping[str, PlainData]
    ) -> AssignmentState:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            start_failed = state is AssignmentState.START_FAILED
            if not start_failed and not _agent_at_or_after(
                state, AssignmentState.PROCESS_STARTED
            ):
                raise ManagedLocalError("result requires a confirmed process start")
            encoded = _json(result)
            if (
                start_failed
                and StageWorkerResult.from_dict(result).status is not StageStatus.FAILED
            ):
                raise ManagedLocalError(
                    "definitive start failure requires a failed result"
                )
            if row["result_json"] is not None and row["result_json"] != encoded:
                raise ManagedLocalError("result conflicts with durable result")
            if _agent_at_or_after(state, AssignmentState.RESULT_DURABLE):
                if row["result_json"] is None:
                    raise ManagedLocalError("durable result payload is missing")
                return state
            conn.execute(
                "UPDATE assignments SET state = ?, result_json = ? WHERE assignment_id = ?",
                (AssignmentState.RESULT_DURABLE.value, encoded, assignment_id),
            )
            return AssignmentState.RESULT_DURABLE

    def record_cancelled_before_start(
        self, assignment_id: str, result: Mapping[str, PlainData]
    ) -> AssignmentState:
        """Record positive no-launch cancellation without fabricating a start."""

        parsed = StageWorkerResult.from_dict(result)
        if parsed.status is not StageStatus.CANCELLED:
            raise ManagedLocalError("no-start result must be cancelled")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            encoded = _json(result)
            if state is AssignmentState.RESULT_DURABLE:
                if row["result_json"] != encoded:
                    raise ManagedLocalError("result conflicts with durable result")
                return state
            if state is not AssignmentState.ACTIVE:
                raise ManagedLocalError(
                    "no-start cancellation requires an active unstarted assignment"
                )
            if row["process_execution_id"] is not None:
                raise ManagedLocalError(
                    "no-start cancellation conflicts with start intent"
                )
            conn.execute(
                "UPDATE assignments SET state = ?, result_json = ? "
                "WHERE assignment_id = ?",
                (AssignmentState.RESULT_DURABLE.value, encoded, assignment_id),
            )
            return AssignmentState.RESULT_DURABLE

    def acknowledge_terminal(self, assignment_id: str) -> AssignmentState:
        return self._advance(
            assignment_id,
            AssignmentState.RESULT_DURABLE,
            AssignmentState.TERMINAL_ACKNOWLEDGED,
        )

    def mark_providers_released(self, assignment_id: str) -> AssignmentState:
        return self._advance(
            assignment_id,
            AssignmentState.TERMINAL_ACKNOWLEDGED,
            AssignmentState.PROVIDERS_RELEASED,
        )

    def publish_availability(
        self, assignment_id: str, availability_revision: str
    ) -> AssignmentState:
        if not isinstance(availability_revision, str) or not availability_revision:
            raise ManagedLocalError("fresh availability revision is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            current = row["availability_revision"]
            if state is AssignmentState.RELEASED:
                if current != availability_revision:
                    raise ManagedLocalError("availability revision conflicts")
                return state
            if state is not AssignmentState.PROVIDERS_RELEASED:
                raise ManagedLocalError(
                    "fresh availability requires released providers"
                )
            conn.execute(
                "UPDATE assignments SET state = ?, availability_revision = ? "
                "WHERE assignment_id = ?",
                (
                    AssignmentState.RELEASED.value,
                    availability_revision,
                    assignment_id,
                ),
            )
            return AssignmentState.RELEASED

    def release_declined(
        self, assignment_id: str, availability_revision: str
    ) -> AssignmentState:
        if not isinstance(availability_revision, str) or not availability_revision:
            raise ManagedLocalError("fresh availability revision is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            current = row["availability_revision"]
            if state is AssignmentState.RELEASED:
                if current != availability_revision:
                    raise ManagedLocalError("availability revision conflicts")
                return state
            if state is not AssignmentState.DECLINED:
                raise ManagedLocalError("assignment is not definitively declined")
            conn.execute(
                "UPDATE assignments SET state = ?, availability_revision = ? "
                "WHERE assignment_id = ?",
                (
                    AssignmentState.RELEASED.value,
                    availability_revision,
                    assignment_id,
                ),
            )
            return AssignmentState.RELEASED

    def read_state(self, assignment_id: str) -> AssignmentState:
        with self._transaction() as conn:
            return AssignmentState(self._assignment(conn, assignment_id)["state"])

    def find_state(self, assignment_id: str) -> AssignmentState | None:
        """Return one exact durable local fact without treating absence as progress."""

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            return None if row is None else AssignmentState(row["state"])

    def read_grant_fence(self, assignment_id: str) -> str | None:
        with self._transaction() as conn:
            value = self._assignment(conn, assignment_id)["grant_fence"]
        return None if value is None else str(value)

    def read_availability_revision(self, assignment_id: str) -> str | None:
        """Return the already-published release revision for outbox replay."""

        with self._transaction() as conn:
            value = self._assignment(conn, assignment_id)["availability_revision"]
        return None if value is None else str(value)

    def read_result(self, assignment_id: str) -> StageWorkerResult | None:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            if row["result_json"] is None:
                return None
            return StageWorkerResult.from_dict(
                json.loads(cast(str, row["result_json"]))
            )

    def retained_claim_commands(self) -> tuple[ClaimCommand, ...]:
        """Return exact claims still lacking durable provider-release proof."""
        if not self.path.is_file():
            if not self._allow_initialize:
                raise ManagedLocalError("agent journal is missing")
            return ()
        with _connect_sqlite(self.path, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = tuple(
                    conn.execute(
                        "SELECT identity_json, claims_json, state FROM assignments "
                        "WHERE claims_json IS NOT NULL"
                    )
                )
            except sqlite3.DatabaseError as exc:
                raise ManagedLocalError(
                    "agent journal retained-claim read failed"
                ) from exc
        retained: list[ClaimCommand] = []
        released = {
            AssignmentState.DECLINED.value,
            AssignmentState.PROVIDERS_RELEASED.value,
            AssignmentState.RELEASED.value,
        }
        for row in rows:
            if cast(str, row["state"]) in released:
                continue
            retained.extend(_claim_commands_from_row(row))
        return tuple(retained)

    def assignment_claim_commands(self, assignment_id: str) -> tuple[ClaimCommand, ...]:
        """Return an assignment's exact commands, including after release."""

        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            if row["claims_json"] is None:
                raise ManagedLocalError("assignment claim evidence is unavailable")
            return _claim_commands_from_row(row)

    @contextmanager
    def _transaction(self):
        if not self.path.is_file():
            if not self._allow_initialize:
                raise ManagedLocalError("agent journal is missing")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with _connect_sqlite(
            self.path, require_existing=not self._allow_initialize
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            if not self._allow_initialize:
                _require_agent_journal_schema(conn)
                try:
                    yield conn
                except Exception:
                    conn.rollback()
                    raise
                else:
                    conn.commit()
                return
            conn.execute(
                "CREATE TABLE IF NOT EXISTS assignments ("
                "assignment_id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, "
                "request_json TEXT NOT NULL, claims_json TEXT, state TEXT NOT NULL, "
                "grant_fence TEXT, process_execution_id TEXT, result_json TEXT, "
                "availability_revision TEXT, declined INTEGER NOT NULL DEFAULT 0, "
                "start_failed INTEGER NOT NULL DEFAULT 0)"
            )
            columns = {
                cast(str, row["name"])
                for row in conn.execute("PRAGMA table_info(assignments)")
            }
            if "claims_json" not in columns:
                conn.execute("ALTER TABLE assignments ADD COLUMN claims_json TEXT")
            if "availability_revision" not in columns:
                conn.execute(
                    "ALTER TABLE assignments ADD COLUMN availability_revision TEXT"
                )
            if "declined" not in columns:
                conn.execute(
                    "ALTER TABLE assignments ADD COLUMN declined INTEGER NOT NULL "
                    "DEFAULT 0"
                )
            if "start_failed" not in columns:
                conn.execute(
                    "ALTER TABLE assignments ADD COLUMN start_failed INTEGER NOT NULL "
                    "DEFAULT 0"
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events (assignment_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, payload_json TEXT NOT NULL, acknowledged_sequence INTEGER, PRIMARY KEY (assignment_id, sequence), UNIQUE (assignment_id, event_id))"
            )
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _require_request(self, assignment: ManagedAssignment) -> None:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment.assignment_id)
            if row["identity_json"] != _json(_assignment_dict(assignment)):
                raise ManagedLocalError("assignment identity conflicts")

    def _advance(
        self, assignment_id: str, prior: AssignmentState, next_state: AssignmentState
    ) -> AssignmentState:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if state is next_state:
                return state
            if _agent_at_or_after(state, next_state):
                return state
            if state is not prior:
                raise ManagedLocalError(f"assignment is not {prior.value}")
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (next_state.value, assignment_id),
            )
            return next_state

    def _set_state(self, assignment_id: str, state: AssignmentState) -> AssignmentState:
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (state.value, assignment_id),
            )
        return state

    def _set_declined(self, assignment_id: str) -> AssignmentState:
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            conn.execute(
                "UPDATE assignments SET state = ?, declined = 1 "
                "WHERE assignment_id = ?",
                (AssignmentState.DECLINED.value, assignment_id),
            )
        return AssignmentState.DECLINED

    def _set_start_failed(self, assignment_id: str) -> AssignmentState:
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            conn.execute(
                "UPDATE assignments SET state = ?, start_failed = 1 "
                "WHERE assignment_id = ?",
                (AssignmentState.START_FAILED.value, assignment_id),
            )
        return AssignmentState.START_FAILED

    @staticmethod
    def _assignment(conn: sqlite3.Connection, assignment_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
        if row is None:
            raise ManagedLocalError("assignment is not durable")
        return row


def _claim_commands_from_row(row: sqlite3.Row) -> tuple[ClaimCommand, ...]:
    try:
        identity = json.loads(cast(str, row["identity_json"]))
        assignment = ManagedAssignment(
            assignment_id=cast(str, identity["assignment_id"]),
            run_uri=cast(str, identity["run_uri"]),
            stage_work_id=cast(str, identity["stage_work_id"]),
            stage_name=cast(str, identity["stage_name"]),
            attempt=cast(int, identity["attempt"]),
            attempt_id=cast(str, identity["attempt_id"]),
            agent_id=cast(str, identity["agent_id"]),
            session_id=cast(str, identity["session_id"]),
            offer_id=cast(str, identity["offer_id"]),
            claim_id=cast(str, identity["claim_id"]),
        )
        commands = json.loads(cast(str, row["claims_json"]))
        values = commands.get("commands") if isinstance(commands, dict) else None
        if not isinstance(values, list):
            raise ManagedLocalError("retained agent claims are corrupt")
        return tuple(_claim_command_from_dict(assignment, value) for value in values)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ManagedLocalError("retained agent claims are corrupt") from exc


class SQLiteCoordinatorAssignments:
    """Coordinator-owned logical reservations with one atomic admission CAS.

    Scheduling remains pure outside this store.  This store only admits the
    selected closed managed target, rechecks the run slot and all exact atoms,
    and retains a bounded decision receipt for audit.  It never launches work.
    """

    _LIVE = frozenset(
        {"reserved", "bound", "accepted", "granted", "running", "unknown"}
    )
    _CAPACITY_HOLDING = _LIVE | {"terminal", "logical_released"}
    _TRANSITIONS = frozenset(
        {
            ("reserved", "bound"),
            ("bound", "accepted"),
            ("bound", "unknown"),
            ("bound", "terminal"),
            ("accepted", "granted"),
            ("granted", "running"),
            ("granted", "unknown"),
            ("granted", "terminal"),
            ("running", "terminal"),
            ("unknown", "terminal"),
            ("terminal", "logical_released"),
            ("logical_released", "released"),
        }
    )

    def __init__(
        self,
        path: str | Path,
        capacity: Sequence[CapacityAtom],
        *,
        _allow_initialize: bool = True,
    ) -> None:
        self.path = Path(path)
        self._allow_initialize = _allow_initialize
        self._capacity = {atom.key: atom for atom in capacity}
        if not self._capacity or len(self._capacity) != len(tuple(capacity)):
            raise ManagedLocalError(
                "coordinator capacity atoms must be non-empty and unique"
            )

    def _initialize(self) -> None:
        """Create the current coordinator-assignment schema explicitly."""

        with self._transaction():
            pass

    def _open_existing(self) -> None:
        """Verify the current assignment schema without creating or repairing it."""

        if not self.path.is_file():
            raise ManagedLocalError("coordinator assignment store is missing")
        with _connect_sqlite(self.path, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            _require_coordinator_assignment_schema(conn)

    def publish_offer(self, snapshot: ManagedOfferSnapshot) -> str:
        """Persist one exact current offer; an older revision never revives."""
        if not isinstance(snapshot, ManagedOfferSnapshot):
            raise ManagedLocalError("managed offer snapshot is invalid")
        for atom in snapshot.atoms:
            configured = self._capacity.get(atom.key)
            if (
                configured is None
                or configured.unit != atom.unit
                or configured.granularity != atom.granularity
                or atom.amount.fraction > configured.amount.fraction
            ):
                raise ManagedLocalError(
                    "offer atom exceeds configured coordinator capacity"
                )
        payload = _json(snapshot.to_dict())
        with self._transaction() as conn:
            current = conn.execute(
                "SELECT snapshot_json, is_current FROM coordinator_offers "
                "WHERE agent_id = ? AND session_id = ? AND offer_revision = ?",
                (snapshot.agent_id, snapshot.session_id, snapshot.offer_revision),
            ).fetchone()
            if current is not None:
                if current["snapshot_json"] != payload:
                    raise ManagedLocalError("managed offer replay conflicts")
                return snapshot.offer_revision
            reused_availability = conn.execute(
                "SELECT offer_revision FROM coordinator_offers "
                "WHERE agent_id = ? AND session_id = ? "
                "AND availability_revision = ?",
                (
                    snapshot.agent_id,
                    snapshot.session_id,
                    snapshot.availability_revision,
                ),
            ).fetchone()
            if reused_availability is not None:
                raise ManagedLocalError(
                    "managed offer requires a fresh availability revision"
                )
            conn.execute(
                "UPDATE coordinator_offers SET is_current = 0 "
                "WHERE agent_id = ? AND session_id = ? AND is_current = 1",
                (snapshot.agent_id, snapshot.session_id),
            )
            conn.execute(
                "INSERT INTO coordinator_offers "
                "(agent_id, session_id, offer_revision, snapshot_revision, "
                "availability_revision, snapshot_json, consumed, is_current) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, 1)",
                (
                    snapshot.agent_id,
                    snapshot.session_id,
                    snapshot.offer_revision,
                    snapshot.snapshot_revision,
                    snapshot.availability_revision,
                    payload,
                ),
            )
        return snapshot.offer_revision

    def reserve(
        self,
        assignment: ManagedAssignment,
        claims: Sequence[ResourceClaim],
        *,
        max_parallel_stages: int,
        decision_receipt: Mapping[str, PlainData],
    ) -> str:
        if max_parallel_stages < 1:
            raise ManagedLocalError("max_parallel_stages must be positive")
        claims = tuple(claims)
        receipt = _validate_decision_receipt(
            decision_receipt, assignment=assignment, claims=claims
        )
        receipt_value = cast(Mapping[str, object], json.loads(receipt))
        atoms = tuple(atom for claim in claims for atom in claim.atoms)
        if not atoms:
            raise ManagedLocalError("logical reservation requires capacity atoms")
        if any(atom.key not in self._capacity for atom in atoms):
            raise ManagedLocalError("claim uses atom outside configured capacity")
        requested: dict[tuple[str, str], Fraction] = {}
        for atom in atoms:
            requested[atom.key] = (
                requested.get(atom.key, Fraction(0)) + atom.amount.fraction
            )
        identity = _json(_assignment_dict(assignment))
        with self._transaction() as conn:
            current = conn.execute(
                "SELECT identity_json, receipt_json, state "
                "FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment.assignment_id,),
            ).fetchone()
            if current is not None:
                stored_atoms = {
                    (
                        cast(str, row["resource_kind"]),
                        cast(str, row["capacity_key"]),
                    ): Fraction(
                        cast(int, row["numerator"]),
                        cast(int, row["denominator"]),
                    )
                    for row in conn.execute(
                        "SELECT resource_kind, capacity_key, numerator, denominator "
                        "FROM coordinator_atoms WHERE assignment_id = ?",
                        (assignment.assignment_id,),
                    )
                }
                if (
                    current["identity_json"] != identity
                    or current["receipt_json"] != receipt
                    or stored_atoms != requested
                ):
                    raise ManagedLocalError(
                        "assignment reservation replay conflicts with durable state"
                    )
                return str(current["state"])
            try:
                stage_work_row = conn.execute(
                    "SELECT record_json FROM stage_work WHERE stage_work_id = ?",
                    (assignment.stage_work_id,),
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                raise ManagedLocalError(
                    "coordinator stage-work state is missing"
                ) from exc
            if stage_work_row is None:
                raise ManagedLocalError("assigned stage work is missing")
            try:
                stage_work = StageWorkRecord.from_dict(
                    json.loads(cast(str, stage_work_row["record_json"]))
                )
            except Exception as exc:
                raise ManagedLocalError("assigned stage work is invalid") from exc
            if (
                stage_work.run_uri != assignment.run_uri
                or stage_work.stage_name != assignment.stage_name
                or stage_work.attempt != assignment.attempt
                or stage_work.attempt_id != assignment.attempt_id
                or stage_work.scheduling_state is not SchedulingProjectionState.READY
            ):
                raise ManagedLocalError("assigned stage work is stale or ineligible")
            if receipt_value["stage_work_revision"] != stage_work.projection_revision:
                raise ManagedLocalError(
                    "stage-work revision changed before reservation"
                )
            work = conn.execute(
                "SELECT assignment_id FROM coordinator_assignments WHERE stage_work_id = ? AND state IN ('reserved','bound','accepted','granted','running','unknown')",
                (assignment.stage_work_id,),
            ).fetchone()
            has_slurm_assignments = (
                conn.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                    "AND name = 'slurm_stage_assignments'"
                ).fetchone()
                is not None
            )
            slurm_work = (
                conn.execute(
                    "SELECT assignment_id FROM slurm_stage_assignments "
                    "WHERE stage_work_id = ? AND state NOT IN ('rejected','released')",
                    (assignment.stage_work_id,),
                ).fetchone()
                if has_slurm_assignments
                else None
            )
            if work is not None or slurm_work is not None:
                raise ManagedLocalError("stage work already has a live assignment")
            active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ? AND state IN ('reserved','bound','accepted','granted','running','unknown')",
                    (assignment.run_uri,),
                ).fetchone()[0]
            )
            if has_slurm_assignments:
                active += int(
                    conn.execute(
                        "SELECT COUNT(*) FROM slurm_stage_assignments WHERE run_uri = ? "
                        "AND state NOT IN ('rejected','released')",
                        (assignment.run_uri,),
                    ).fetchone()[0]
                )
            if active >= max_parallel_stages:
                raise ManagedLocalError("run active-assignment limit reached")
            offer_row = conn.execute(
                "SELECT snapshot_json, snapshot_revision, consumed, is_current "
                "FROM coordinator_offers WHERE agent_id = ? AND session_id = ? "
                "AND offer_revision = ?",
                (assignment.agent_id, assignment.session_id, assignment.offer_id),
            ).fetchone()
            if offer_row is None or not bool(offer_row["is_current"]):
                raise ManagedLocalError("assignment offer is missing or stale")
            if bool(offer_row["consumed"]):
                raise ManagedLocalError(
                    "availability revision already has an unresolved admission"
                )
            if offer_row["snapshot_revision"] != receipt_value["snapshot_revision"]:
                raise ManagedLocalError("decision snapshot revision is stale")
            offer = cast(
                Mapping[str, object],
                json.loads(cast(str, offer_row["snapshot_json"])),
            )
            offered_descriptors = tuple(
                SchedulingComponentDescriptor.from_dict(value)
                for value in cast(
                    Sequence[Mapping[str, object]],
                    offer["component_descriptors"],
                )
            )
            receipt_descriptors = tuple(
                SchedulingComponentDescriptor.from_dict(value)
                for value in cast(
                    Sequence[Mapping[str, object]],
                    receipt_value["component_descriptors"],
                )
            )
            offered_by_kind = {
                descriptor.kind: descriptor for descriptor in offered_descriptors
            }
            if any(
                offered_by_kind.get(descriptor.kind) != descriptor
                for descriptor in receipt_descriptors
            ):
                raise ManagedLocalError(
                    "decision components do not match the durable offer"
                )
            offered_provider_descriptors = tuple(
                SchedulingComponentDescriptor.from_dict(value)
                for value in cast(
                    Sequence[Mapping[str, object]],
                    offer["provider_descriptors"],
                )
            )
            receipt_provider_descriptors = tuple(
                SchedulingComponentDescriptor.from_dict(value)
                for value in cast(
                    Sequence[Mapping[str, object]],
                    receipt_value["provider_descriptors"],
                )
            )
            offered_providers_by_kind = {
                descriptor.kind: descriptor
                for descriptor in offered_provider_descriptors
            }
            if any(
                offered_providers_by_kind.get(descriptor.kind) != descriptor
                for descriptor in receipt_provider_descriptors
            ):
                raise ManagedLocalError(
                    "decision providers do not match the durable offer"
                )
            offered_atoms = {
                atom.key: atom
                for atom in (
                    _capacity_atom_from_dict(value)
                    for value in cast(Sequence[Mapping[str, object]], offer["atoms"])
                )
            }
            reflected_claim_ids = set(cast(Sequence[str], offer["reflected_claim_ids"]))
            capacity_rows = tuple(
                conn.execute(
                    "SELECT a.resource_kind, a.capacity_key, a.numerator, "
                    "a.denominator, x.claim_id, x.state "
                    "FROM coordinator_atoms a JOIN coordinator_assignments x "
                    "ON x.assignment_id = a.assignment_id "
                    "WHERE x.agent_id = ? AND x.session_id = ? "
                    "AND x.state IN ('reserved','bound','accepted','granted',"
                    "'running','unknown','terminal','logical_released')",
                    (assignment.agent_id, assignment.session_id),
                )
            )
            reflectable_claim_ids = {
                cast(str, row["claim_id"])
                for row in capacity_rows
                if row["state"]
                in {"accepted", "granted", "running", "terminal", "logical_released"}
            }
            if not reflected_claim_ids.issubset(reflectable_claim_ids):
                raise ManagedLocalError(
                    "offer reflects a claim that is not accepted and live"
                )
            reflected_amounts: dict[tuple[str, str], Fraction] = {}
            for row in capacity_rows:
                if cast(str, row["claim_id"]) not in reflected_claim_ids:
                    continue
                key = (
                    cast(str, row["resource_kind"]),
                    cast(str, row["capacity_key"]),
                )
                reflected_amounts[key] = reflected_amounts.get(
                    key, Fraction(0)
                ) + Fraction(row["numerator"], row["denominator"])
            for key, configured in self._capacity.items():
                offered_amount = offered_atoms.get(key)
                if (
                    offered_amount.amount.fraction if offered_amount else Fraction(0)
                ) + reflected_amounts.get(
                    key, Fraction(0)
                ) > configured.amount.fraction:
                    raise ManagedLocalError(
                        "offer net atoms conflict with reflected logical claims"
                    )
            for key, amount in requested.items():
                used = sum(
                    (
                        Fraction(row["numerator"], row["denominator"])
                        for row in capacity_rows
                        if (
                            cast(str, row["resource_kind"]),
                            cast(str, row["capacity_key"]),
                        )
                        == key
                        if cast(str, row["claim_id"]) not in reflected_claim_ids
                    ),
                    Fraction(0),
                )
                offered = offered_atoms.get(key)
                if offered is None or used + amount > offered.amount.fraction:
                    raise ManagedLocalError("logical capacity atom is unavailable")
            conn.execute(
                "INSERT INTO coordinator_assignments "
                "(assignment_id, identity_json, run_uri, stage_work_id, state, "
                "receipt_json, agent_id, session_id, offer_id, claim_id) "
                "VALUES (?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?)",
                (
                    assignment.assignment_id,
                    identity,
                    assignment.run_uri,
                    assignment.stage_work_id,
                    receipt,
                    assignment.agent_id,
                    assignment.session_id,
                    assignment.offer_id,
                    assignment.claim_id,
                ),
            )
            conn.executemany(
                "INSERT INTO coordinator_atoms (assignment_id, resource_kind, capacity_key, numerator, denominator) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        assignment.assignment_id,
                        key[0],
                        key[1],
                        amount.numerator,
                        amount.denominator,
                    )
                    for key, amount in requested.items()
                ],
            )
            decided = replace(
                stage_work,
                scheduling_state=SchedulingProjectionState.DECIDED,
                scheduling_diagnostics={
                    "assignment_id": assignment.assignment_id,
                    "policy_epoch": cast(str, receipt_value["policy_epoch"]),
                },
            )
            conn.execute(
                "UPDATE stage_work SET record_json = ? WHERE stage_work_id = ?",
                (_json(decided.to_dict()), assignment.stage_work_id),
            )
            conn.execute(
                "UPDATE coordinator_offers SET consumed = 1 "
                "WHERE agent_id = ? AND session_id = ? AND offer_revision = ?",
                (assignment.agent_id, assignment.session_id, assignment.offer_id),
            )
            return "reserved"

    def advance(self, assignment_id: str, *, expected: str, next_state: str) -> str:
        if (expected, next_state) not in self._TRANSITIONS:
            raise ManagedLocalError("invalid coordinator assignment transition")
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ManagedLocalError("assignment is not reserved")
            if row["state"] == next_state:
                return next_state
            if _coordinator_at_or_after(cast(str, row["state"]), next_state):
                return cast(str, row["state"])
            if row["state"] != expected:
                raise ManagedLocalError("stale coordinator assignment transition")
            conn.execute(
                "UPDATE coordinator_assignments SET state = ? WHERE assignment_id = ?",
                (next_state, assignment_id),
            )
            return next_state

    def release_unaccepted(
        self, assignment_id: str, *, reopen_offer: bool = False
    ) -> str:
        """Release a bound assignment proven to have no physical acceptance."""

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state, agent_id, session_id, offer_id, stage_work_id "
                "FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ManagedLocalError("assignment is not reserved")
            if row["state"] == "released":
                return "released"
            if row["state"] != "bound":
                raise ManagedLocalError(
                    "only an unaccepted bound assignment can be released"
                )
            conn.execute(
                "UPDATE coordinator_assignments SET state = 'released' "
                "WHERE assignment_id = ?",
                (assignment_id,),
            )
            stage_work_row = conn.execute(
                "SELECT record_json FROM stage_work WHERE stage_work_id = ?",
                (row["stage_work_id"],),
            ).fetchone()
            if stage_work_row is None:
                raise ManagedLocalError("released assignment stage work is missing")
            try:
                stage_work = StageWorkRecord.from_dict(
                    json.loads(cast(str, stage_work_row["record_json"]))
                )
            except Exception as exc:
                raise ManagedLocalError(
                    "released assignment stage work is invalid"
                ) from exc
            if (
                stage_work.scheduling_state is not SchedulingProjectionState.DECIDED
                or stage_work.scheduling_diagnostics.get("assignment_id")
                != assignment_id
            ):
                raise ManagedLocalError(
                    "released assignment does not own its stage-work decision"
                )
            reopened = replace(
                stage_work,
                scheduling_state=SchedulingProjectionState.READY,
                scheduling_diagnostics={},
                projection_revision=stage_work.projection_revision + 1,
            )
            conn.execute(
                "UPDATE stage_work SET record_json = ? WHERE stage_work_id = ?",
                (_json(reopened.to_dict()), reopened.stage_work_id),
            )
            if reopen_offer:
                conn.execute(
                    "UPDATE coordinator_offers SET consumed = 0 WHERE "
                    "agent_id = ? AND session_id = ? AND offer_revision = ? "
                    "AND is_current = 1",
                    (row["agent_id"], row["session_id"], row["offer_id"]),
                )
            return "released"

    def cancellation_release_unstarted(self, assignment_id: str) -> str:
        """Release an exact reservation only after the caller proves no local request."""

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ManagedLocalError("assignment is not reserved")
            if row["state"] == "released":
                return "released"
            if row["state"] != "reserved":
                raise ManagedLocalError("only an unbound reservation can be released")
            conn.execute(
                "UPDATE coordinator_assignments SET state = 'released' WHERE assignment_id = ?",
                (assignment_id,),
            )
            return "released"

    def cancellation_release_pregrant(self, assignment_id: str) -> str:
        """Release one exact reservation after journal-owned no-start settlement."""

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ManagedLocalError("assignment is not reserved")
            if row["state"] == "released":
                return "released"
            if row["state"] not in {"bound", "accepted"}:
                raise ManagedLocalError("local assignment is not proven pre-grant")
            conn.execute(
                "UPDATE coordinator_assignments SET state = 'released' WHERE assignment_id = ?",
                (assignment_id,),
            )
            return "released"

    def list_run_live_states(self, run_uri: str) -> tuple[tuple[str, str], ...]:
        """Return coordinator-owned nonterminal assignment facts for cancellation."""

        with self._transaction() as conn:
            return tuple(
                (str(row["assignment_id"]), str(row["state"]))
                for row in conn.execute(
                    "SELECT assignment_id, state FROM coordinator_assignments "
                    "WHERE run_uri = ? AND state != 'released' ORDER BY assignment_id",
                    (run_uri,),
                )
            )

    def retained_scheduling_descriptors(
        self,
    ) -> tuple[SchedulingComponentDescriptor, ...]:
        """Return exact components referenced by capacity-holding decisions."""

        references: dict[
            tuple[str, int, str, str, str], SchedulingComponentDescriptor
        ] = {}
        with self._transaction() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT x.receipt_json, w.record_json "
                    "FROM coordinator_assignments x JOIN stage_work w "
                    "ON w.stage_work_id = x.stage_work_id "
                    "WHERE x.state IN ('reserved','bound','accepted','granted',"
                    "'running','unknown','terminal','logical_released') "
                    "ORDER BY x.assignment_id"
                )
            )
        try:
            for row in rows:
                receipt = json.loads(cast(str, row["receipt_json"]))
                if not isinstance(receipt, Mapping):
                    raise ManagedLocalError("retained decision receipt is invalid")
                policy = SchedulingComponentDescriptor.from_dict(
                    receipt.get("policy_descriptor")
                )
                references[policy.key] = policy
                raw_components = receipt.get("component_descriptors")
                if not isinstance(raw_components, list):
                    raise ManagedLocalError(
                        "retained decision component descriptors are invalid"
                    )
                for raw in raw_components:
                    descriptor = SchedulingComponentDescriptor.from_dict(raw)
                    references[descriptor.key] = descriptor
                stage_work = StageWorkRecord.from_dict(
                    json.loads(cast(str, row["record_json"]))
                )
                for descriptor in stage_work.placement.planner_descriptors.values():
                    references[descriptor.key] = descriptor
                for spec in stage_work.placement.hard_constraints:
                    if spec.descriptor is None:
                        raise ManagedLocalError(
                            "retained hard evaluator descriptor is unavailable"
                        )
                    references[spec.descriptor.key] = spec.descriptor
                for spec in stage_work.placement.preferences:
                    if spec.descriptor is None:
                        raise ManagedLocalError(
                            "retained preference scorer descriptor is unavailable"
                        )
                    references[spec.descriptor.key] = spec.descriptor
        except ManagedLocalError:
            raise
        except Exception as exc:
            raise ManagedLocalError(
                "retained scheduling component references are invalid"
            ) from exc
        return tuple(sorted(references.values(), key=lambda item: item.key))

    def record_event(
        self,
        assignment_id: str,
        sequence: int,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> int:
        if sequence < 1 or not event_id:
            raise ManagedLocalError("event sequence and ID are required")
        encoded = _json(payload)
        with self._transaction() as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM coordinator_assignments WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()
                is None
            ):
                raise ManagedLocalError("assignment is not reserved")
            existing = conn.execute(
                "SELECT event_id, payload_json FROM coordinator_events "
                "WHERE assignment_id = ? AND sequence = ?",
                (assignment_id, sequence),
            ).fetchone()
            if existing is not None:
                if (
                    existing["event_id"] != event_id
                    or existing["payload_json"] != encoded
                ):
                    raise ManagedLocalError("coordinator event replay conflicts")
                return sequence
            expected = cast(
                int,
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM coordinator_events "
                    "WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0],
            )
            if sequence != expected:
                raise ManagedLocalError("coordinator event sequence gap")
            conn.execute(
                "INSERT INTO coordinator_events "
                "(assignment_id, sequence, event_id, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (assignment_id, sequence, event_id, encoded),
            )
            return sequence

    def state(self, assignment_id: str) -> str:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ManagedLocalError("assignment is not reserved")
            return cast(str, row["state"])

    @contextmanager
    def _transaction(self):
        if not self.path.is_file():
            if not self._allow_initialize:
                raise ManagedLocalError("coordinator assignment store is missing")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with _connect_sqlite(
            self.path, require_existing=not self._allow_initialize
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            if not self._allow_initialize:
                _require_coordinator_assignment_schema(conn)
                try:
                    yield conn
                except Exception:
                    conn.rollback()
                    raise
                else:
                    conn.commit()
                return
            conn.execute(
                "CREATE TABLE IF NOT EXISTS coordinator_assignments ("
                "assignment_id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, "
                "run_uri TEXT NOT NULL, stage_work_id TEXT NOT NULL, "
                "state TEXT NOT NULL, receipt_json TEXT NOT NULL, "
                "agent_id TEXT NOT NULL DEFAULT '', session_id TEXT NOT NULL DEFAULT '', "
                "offer_id TEXT NOT NULL DEFAULT '', claim_id TEXT NOT NULL DEFAULT '')"
            )
            columns = {
                cast(str, row["name"])
                for row in conn.execute("PRAGMA table_info(coordinator_assignments)")
            }
            for name in ("agent_id", "session_id", "offer_id", "claim_id"):
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE coordinator_assignments "
                        f"ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
                    )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS coordinator_atoms (assignment_id TEXT NOT NULL, resource_kind TEXT NOT NULL, capacity_key TEXT NOT NULL, numerator INTEGER NOT NULL, denominator INTEGER NOT NULL, PRIMARY KEY (assignment_id, resource_kind, capacity_key))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS coordinator_events ("
                "assignment_id TEXT NOT NULL, sequence INTEGER NOT NULL, "
                "event_id TEXT NOT NULL, payload_json TEXT NOT NULL, "
                "PRIMARY KEY (assignment_id, sequence), "
                "UNIQUE (assignment_id, event_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS coordinator_offers ("
                "agent_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                "offer_revision TEXT NOT NULL, snapshot_revision TEXT NOT NULL, "
                "availability_revision TEXT NOT NULL, "
                "snapshot_json TEXT NOT NULL, consumed INTEGER NOT NULL, "
                "is_current INTEGER NOT NULL, "
                "PRIMARY KEY (agent_id, session_id, offer_revision), "
                "UNIQUE (agent_id, session_id, availability_revision))"
            )
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()


def _connect_sqlite(
    path: Path, *, require_existing: bool = False
) -> sqlite3.Connection:
    target: str | Path = (
        f"{path.resolve().as_uri()}?mode=rw" if require_existing else path
    )
    return sqlite3.connect(target, uri=require_existing)


def _require_agent_journal_schema(conn: sqlite3.Connection) -> None:
    _require_sqlite_columns(
        conn,
        "assignments",
        {
            "assignment_id",
            "identity_json",
            "request_json",
            "claims_json",
            "state",
            "grant_fence",
            "process_execution_id",
            "result_json",
            "availability_revision",
            "declined",
            "start_failed",
        },
        "agent journal",
    )
    _require_sqlite_columns(
        conn,
        "events",
        {
            "assignment_id",
            "sequence",
            "event_id",
            "payload_json",
            "acknowledged_sequence",
        },
        "agent journal",
    )


def _require_coordinator_assignment_schema(conn: sqlite3.Connection) -> None:
    _require_sqlite_columns(
        conn,
        "coordinator_assignments",
        {
            "assignment_id",
            "identity_json",
            "run_uri",
            "stage_work_id",
            "state",
            "receipt_json",
            "agent_id",
            "session_id",
            "offer_id",
            "claim_id",
        },
        "coordinator assignment store",
    )
    _require_sqlite_columns(
        conn,
        "coordinator_atoms",
        {
            "assignment_id",
            "resource_kind",
            "capacity_key",
            "numerator",
            "denominator",
        },
        "coordinator assignment store",
    )
    _require_sqlite_columns(
        conn,
        "coordinator_events",
        {"assignment_id", "sequence", "event_id", "payload_json"},
        "coordinator assignment store",
    )
    _require_sqlite_columns(
        conn,
        "coordinator_offers",
        {
            "agent_id",
            "session_id",
            "offer_revision",
            "snapshot_revision",
            "availability_revision",
            "snapshot_json",
            "consumed",
            "is_current",
        },
        "coordinator assignment store",
    )


def _require_sqlite_columns(
    conn: sqlite3.Connection,
    table: str,
    required: set[str],
    owner: str,
) -> None:
    try:
        columns = {
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")
        }
    except sqlite3.DatabaseError as exc:
        raise ManagedLocalError(f"{owner} schema is unavailable") from exc
    if not required.issubset(columns):
        raise ManagedLocalError(f"{owner} schema is unsupported")


def grant_and_start_managed_assignment(
    *,
    authority: PreparedAttemptExecutionAuthority,
    journal: SQLiteAgentJournal,
    assignment: ManagedAssignment,
    request: Mapping[str, PlainData],
    commands: Sequence[ClaimCommand],
    providers: Mapping[str, AgentResourceProvider],
    launcher: Callable[[], str],
    process_execution_id: str | None = None,
) -> ExecutionFence:
    """Execute the bounded local admission-to-start saga for one reservation.

    The caller has already made the coordinator's logical reservation.  This
    function deliberately has no run lock and neither allocates attempts nor
    lets the worker write authority lifecycle truth.
    """
    authority.bind_prepared_attempt(
        assignment.run_uri,
        assignment_id=assignment.assignment_id,
        attempt_id=assignment.attempt_id,
    )
    journal.persist_request(assignment, request)
    prepared = journal.prepare_composite(assignment, commands, providers)
    if prepared is AssignmentState.DECLINED:
        authority.unbind_prepared_attempt(
            assignment.run_uri,
            assignment_id=assignment.assignment_id,
            attempt_id=assignment.attempt_id,
        )
        raise ManagedLocalError("managed assignment was definitively declined")
    if not _agent_at_or_after(prepared, AssignmentState.PREPARED):
        raise ManagedLocalError("managed assignment preparation is indeterminate")
    journal.accept(assignment.assignment_id)
    fence = authority.grant_prepared_attempt(
        assignment.run_uri,
        assignment_id=assignment.assignment_id,
        attempt_id=assignment.attempt_id,
    )
    journal.grant(assignment.assignment_id, fence.fencing_token)
    activation = journal.activate_composite(
        assignment.assignment_id, commands, providers
    )
    if not _agent_at_or_after(activation, AssignmentState.ACTIVE):
        raise ManagedLocalError("managed assignment activation is indeterminate")
    process_id = process_execution_id or f"{assignment.assignment_id}:root"
    journal.start_once(assignment.assignment_id, process_id, launcher)
    authority.confirm_execution_started(assignment.run_uri, fence=fence)
    return fence


def run_managed_local_assignment(
    *,
    coordinator: SQLiteCoordinatorAssignments,
    authority: PreparedAttemptExecutionAuthority,
    journal: SQLiteAgentJournal,
    assignment: ManagedAssignment,
    worker_request: StageWorkerRequest,
    claims: Sequence[ResourceClaim],
    commands: Sequence[ClaimCommand],
    providers: Mapping[str, AgentResourceProvider],
    run_store: LegacyRunStore,
    max_parallel_stages: int,
    decision_receipt: Mapping[str, PlainData],
    process_execution_id: str | None = None,
    executor: Executor | None = None,
    artifact_store_factory: ArtifactStoreFactory | None = None,
    selected_plugin_records: tuple[PluginRecord, ...] = (),
    resource_validator_registry: ResourceValidatorRegistry | None = None,
    process_launcher: Callable[
        [str, Callable[[], StageWorkerResult]], _ManagedWorkerHandle
    ]
    | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
    execution_started: Callable[[], None] | None = None,
) -> ManagedExecutionReceipt:
    """Run one exact local assignment through the durable Phase 2 saga.

    The coordinator, authority, and journal remain separate transaction owners.
    Each cross-owner fact is replayable, while this bounded composition drives
    them synchronously for local tests and later command facades.
    """

    _require_worker_assignment_match(assignment, worker_request)
    commands = tuple(commands)
    claims = tuple(claims)
    if tuple(command.claim for command in commands) != claims:
        raise ManagedLocalError("provider commands must match logical claims exactly")
    if any(command.assignment != assignment for command in commands):
        raise ManagedLocalError("provider commands must target the exact assignment")
    if len({command.operation_id for command in commands}) != len(commands):
        raise ManagedLocalError("provider command operation IDs must be unique")
    claim_kinds = tuple(claim.resource_kind for claim in claims)
    if len(set(claim_kinds)) != len(claim_kinds):
        raise ManagedLocalError(
            "managed assignment requires one claim per resource kind"
        )
    validated_decision = cast(
        Mapping[str, object],
        json.loads(
            _validate_decision_receipt(
                decision_receipt,
                assignment=assignment,
                claims=claims,
            )
        ),
    )
    recorded_provider_descriptors = {
        descriptor.kind: descriptor
        for descriptor in (
            SchedulingComponentDescriptor.from_dict(item)
            for item in cast(
                Sequence[Mapping[str, object]],
                validated_decision["provider_descriptors"],
            )
        )
    }
    for claim, command in zip(claims, commands, strict=True):
        provider = providers.get(claim.resource_kind)
        if provider is None:
            raise ManagedLocalError("no provider for claim resource kind")
        if command.provider_descriptor != recorded_provider_descriptors.get(
            claim.resource_kind
        ):
            raise ManagedLocalError(
                "command provider descriptor does not match decision evidence"
            )
        if provider.descriptor != command.provider_descriptor:
            raise ManagedLocalError(
                "decision provider descriptor does not match configured provider"
            )
        if claim.contract not in provider.claim_contracts:
            raise ManagedLocalError(
                "decision claim contract is not supported by configured provider"
            )
    coordinator.reserve(
        assignment,
        claims,
        max_parallel_stages=max_parallel_stages,
        decision_receipt=decision_receipt,
    )
    authority.bind_prepared_attempt(
        assignment.run_uri,
        assignment_id=assignment.assignment_id,
        attempt_id=assignment.attempt_id,
    )
    coordinator.advance(
        assignment.assignment_id, expected="reserved", next_state="bound"
    )
    journal.persist_request(assignment, worker_request.to_dict())
    _emit_assignment_event(
        journal,
        coordinator,
        assignment.assignment_id,
        "request_and_inputs_durable",
        {"attempt_id": assignment.attempt_id},
    )

    prepared = journal.prepare_composite(assignment, commands, providers)
    if prepared is AssignmentState.DECLINED:
        authority.unbind_prepared_attempt(
            assignment.run_uri,
            assignment_id=assignment.assignment_id,
            attempt_id=assignment.attempt_id,
        )
        availability_revision = _fresh_availability_revision(
            assignment=assignment,
            providers=providers,
            operation="declined",
        )
        journal.release_declined(assignment.assignment_id, availability_revision)
        coordinator.release_unaccepted(assignment.assignment_id)
        _emit_assignment_event(
            journal,
            coordinator,
            assignment.assignment_id,
            "definitive_decline_released",
            {"availability_revision": availability_revision},
        )
        raise ManagedLocalError("managed assignment was definitively declined")
    if not _agent_at_or_after(prepared, AssignmentState.PREPARED):
        coordinator.advance(
            assignment.assignment_id, expected="bound", next_state="unknown"
        )
        _emit_assignment_event(
            journal,
            coordinator,
            assignment.assignment_id,
            "preparation_unknown",
            {"attempt_id": assignment.attempt_id},
        )
        raise ManagedLocalError("managed assignment preparation is indeterminate")

    journal.accept(assignment.assignment_id)
    coordinator.advance(
        assignment.assignment_id, expected="bound", next_state="accepted"
    )
    _emit_assignment_event(
        journal,
        coordinator,
        assignment.assignment_id,
        "accepted",
        {"claim_id": assignment.claim_id},
    )
    fence = authority.grant_prepared_attempt(
        assignment.run_uri,
        assignment_id=assignment.assignment_id,
        attempt_id=assignment.attempt_id,
    )
    journal.grant(assignment.assignment_id, fence.fencing_token)
    coordinator.advance(
        assignment.assignment_id, expected="accepted", next_state="granted"
    )
    activation = journal.activate_composite(
        assignment.assignment_id, commands, providers
    )
    if not _agent_at_or_after(activation, AssignmentState.ACTIVE):
        coordinator.advance(
            assignment.assignment_id, expected="granted", next_state="unknown"
        )
        _emit_assignment_event(
            journal,
            coordinator,
            assignment.assignment_id,
            "activation_unknown",
            {"fence": fence.fencing_token},
        )
        raise ManagedLocalError("managed assignment activation is indeterminate")

    def finalize_result(
        worker_result: StageWorkerResult, *, coordinator_expected: str
    ) -> ManagedExecutionReceipt:
        journal.record_result(assignment.assignment_id, worker_result.to_dict())
        _emit_assignment_event(
            journal,
            coordinator,
            assignment.assignment_id,
            "result_and_output_durable",
            {"status": worker_result.status.value},
        )
        output_commit: OutputCommit | None = None
        if worker_result.status is StageStatus.SUCCEEDED:
            output_commit = authority.record_output_commit(
                assignment.run_uri,
                assignment.stage_name,
                attempt_id=assignment.attempt_id,
                fencing_token=fence.fencing_token,
                outputs=worker_result.outputs,
                assignment_id=assignment.assignment_id,
            )
        else:
            authority.record_managed_attempt_terminal(
                assignment.run_uri,
                fence=fence,
                status=worker_result.status,
                reason=_worker_terminal_reason(worker_result),
            )
        coordinator.advance(
            assignment.assignment_id,
            expected=coordinator_expected,
            next_state="terminal",
        )
        journal.acknowledge_terminal(assignment.assignment_id)
        coordinator.advance(
            assignment.assignment_id,
            expected="terminal",
            next_state="logical_released",
        )
        _emit_assignment_event(
            journal,
            coordinator,
            assignment.assignment_id,
            "authority_terminal_logical_release",
            {"status": worker_result.status.value},
        )
        for command in commands:
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            release_command = _operation_command(command, "release")
            released = _provider_call(provider.release, release_command)
            if released.outcome is not ClaimOutcome.RELEASED:
                raise ManagedLocalError("provider release is indeterminate")
        journal.mark_providers_released(assignment.assignment_id)
        availability_revision = _fresh_availability_revision(
            assignment=assignment,
            providers=providers,
            operation="released",
        )
        journal.publish_availability(assignment.assignment_id, availability_revision)
        coordinator.advance(
            assignment.assignment_id,
            expected="logical_released",
            next_state="released",
        )
        _emit_assignment_event(
            journal,
            coordinator,
            assignment.assignment_id,
            "provider_released_availability_fresh",
            {"availability_revision": availability_revision},
        )
        return ManagedExecutionReceipt(
            assignment=assignment,
            fence=fence,
            worker_result=worker_result,
            output_commit=output_commit,
            availability_revision=availability_revision,
        )

    durable_result = journal.read_result(assignment.assignment_id)
    if durable_result is not None and journal.definitive_start_failed(
        assignment.assignment_id
    ):
        return finalize_result(durable_result, coordinator_expected="granted")

    process_id = process_execution_id or f"{assignment.assignment_id}:root"

    def execute_exact_worker() -> StageWorkerResult:
        environment: dict[str, str] = {}
        for command in commands:
            provider = providers[command.claim.resource_kind]
            if isinstance(provider, GpuResourceProvider):
                environment.update(provider.worker_environment(command))
        if environment:
            if (
                executor is not None
                or artifact_store_factory is not None
                or resource_validator_registry is not None
            ):
                raise ManagedLocalError(
                    "GPU-bound local workers require process-compatible default "
                    "execution services"
                )
            return _execute_gpu_worker_process(
                run_store=run_store,
                worker_request=worker_request,
                environment=environment,
                selected_plugin_records=selected_plugin_records,
            )
        return execute_stage_worker_request(
            run_store=run_store,
            worker_request=worker_request,
            executor=executor,
            artifact_store_factory=artifact_store_factory,
            selected_plugin_records=selected_plugin_records,
            resource_validator_registry=resource_validator_registry,
        )

    def launch_exact_worker() -> str:
        launch = process_launcher or _launch_managed_worker
        handle = launch(process_id, execute_exact_worker)
        if not isinstance(handle, _ManagedWorkerHandle):
            raise ManagedLocalError("launcher returned an invalid containment handle")
        if handle.process_execution_id != process_id:
            raise ManagedLocalError("launcher returned an unexpected process identity")
        journal.attach_process_handle(assignment.assignment_id, handle)
        return handle.process_execution_id

    try:
        journal.start_once(
            assignment.assignment_id,
            process_id,
            launch_exact_worker,
        )
    except ManagedProcessStartError as exc:
        worker_result = _start_failed_worker_result(worker_request, exc)
        journal.record_result(assignment.assignment_id, worker_result.to_dict())
        return finalize_result(worker_result, coordinator_expected="granted")
    except Exception:
        coordinator.advance(
            assignment.assignment_id, expected="granted", next_state="unknown"
        )
        raise
    handle = journal.process_handle(assignment.assignment_id)
    if handle is None:
        raise ManagedLocalError(
            "managed start intent has no same-process containment handle"
        )
    if cancellation_requested is not None and cancellation_requested():
        handle.cancel_before_run()
        return finalize_result(
            _cancelled_worker_result(worker_request),
            coordinator_expected="granted",
        )
    authority.confirm_execution_started(assignment.run_uri, fence=fence)
    coordinator.advance(
        assignment.assignment_id, expected="granted", next_state="running"
    )
    _emit_assignment_event(
        journal,
        coordinator,
        assignment.assignment_id,
        "process_started",
        {"process_execution_id": process_id, "fence": fence.fencing_token},
    )
    worker_result = journal.read_result(assignment.assignment_id)
    if worker_result is None:
        handle.release_to_run()
        if execution_started is not None:
            execution_started()
        try:
            worker_result = handle.wait(cancellation_requested)
        except BaseException as exc:  # noqa: BLE001 - the managed root is contained.
            worker_result = _managed_root_failed_worker_result(worker_request, exc)
        if handle.cancellation_seen:
            worker_result = _cancelled_worker_result(worker_request)
    return finalize_result(worker_result, coordinator_expected="running")


def _assignment_dict(value: ManagedAssignment) -> dict[str, PlainData]:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def _agent_at_or_after(state: AssignmentState, checkpoint: AssignmentState) -> bool:
    try:
        return _AGENT_SUCCESS_ORDER.index(state) >= _AGENT_SUCCESS_ORDER.index(
            checkpoint
        )
    except ValueError:
        return False


def _coordinator_at_or_after(state: str, checkpoint: str) -> bool:
    try:
        return _COORDINATOR_SUCCESS_ORDER.index(
            state
        ) >= _COORDINATOR_SUCCESS_ORDER.index(checkpoint)
    except ValueError:
        return False


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


def _claim_command_dict(command: ClaimCommand) -> dict[str, PlainData]:
    claim = command.claim
    return {
        "assignment_id": command.assignment.assignment_id,
        "operation_id": command.operation_id,
        "provider_descriptor": command.provider_descriptor.to_dict(),
        "resource_kind": claim.resource_kind,
        "contract": claim.contract.to_dict(),
        "atoms": [atom.to_dict() for atom in claim.atoms],
        "provider_data_version": claim.provider_data_version,
        "provider_data": thaw_plain_data(
            claim.provider_data, path="claim.provider_data"
        ),
        "claim_fingerprint": claim.fingerprint,
    }


def _claim_command_from_dict(
    assignment: ManagedAssignment, data: object
) -> ClaimCommand:
    expected = {
        "assignment_id",
        "operation_id",
        "provider_descriptor",
        "resource_kind",
        "contract",
        "atoms",
        "provider_data_version",
        "provider_data",
        "claim_fingerprint",
    }
    if not isinstance(data, Mapping) or set(data) != expected:
        raise ManagedLocalError("retained claim command is invalid")
    if data.get("assignment_id") != assignment.assignment_id:
        raise ManagedLocalError("retained claim assignment conflicts")
    atoms_data = data.get("atoms")
    if not isinstance(atoms_data, Sequence):
        raise ManagedLocalError("retained claim atoms are invalid")
    claim = ResourceClaim(
        resource_kind=cast(str, data.get("resource_kind")),
        contract=ResourceClaimContractDescriptor.from_dict(data.get("contract")),
        atoms=tuple(
            _capacity_atom_from_dict(cast(Mapping[str, object], atom))
            for atom in atoms_data
        ),
        provider_data_version=cast(int, data.get("provider_data_version")),
        provider_data=cast(Mapping[str, PlainData], data.get("provider_data", {})),
    )
    if data.get("claim_fingerprint") != claim.fingerprint:
        raise ManagedLocalError("retained claim fingerprint conflicts")
    try:
        provider_descriptor = SchedulingComponentDescriptor.from_dict(
            data["provider_descriptor"]
        )
    except Exception as exc:
        raise ManagedLocalError(
            "retained claim provider descriptor is invalid"
        ) from exc
    return ClaimCommand(
        assignment,
        cast(str, data["operation_id"]),
        claim,
        provider_descriptor,
    )


def _operation_command(command: ClaimCommand, operation: str) -> ClaimCommand:
    return ClaimCommand(
        assignment=command.assignment,
        operation_id=f"{command.operation_id}:{operation}",
        claim=command.claim,
        provider_descriptor=command.provider_descriptor,
    )


def _provider_call(
    operation: Callable[[ClaimCommand], ClaimResult], command: ClaimCommand
) -> ClaimResult:
    try:
        result = operation(command)
    except Exception as exc:  # noqa: BLE001 - provider failures are indeterminate facts.
        return ClaimResult(
            ClaimOutcome.INDETERMINATE,
            command.operation_id,
            command.claim.fingerprint,
            f"provider raised {type(exc).__name__}",
        )
    if not isinstance(result, ClaimResult):
        return ClaimResult(
            ClaimOutcome.INDETERMINATE,
            command.operation_id,
            command.claim.fingerprint,
            "provider returned a malformed result",
        )
    if (
        result.operation_id != command.operation_id
        or result.claim_fingerprint != command.claim.fingerprint
    ):
        return ClaimResult(
            ClaimOutcome.INDETERMINATE,
            command.operation_id,
            command.claim.fingerprint,
            "provider result identity mismatch",
        )
    return result


def _require_worker_assignment_match(
    assignment: ManagedAssignment, request: StageWorkerRequest
) -> None:
    if not isinstance(request, StageWorkerRequest):
        raise ManagedLocalError("worker_request must be a StageWorkerRequest")
    if (
        request.run_uri != assignment.run_uri
        or request.stage_name != assignment.stage_name
        or request.attempt != assignment.attempt
    ):
        raise ManagedLocalError(
            "worker request does not match the exact assigned attempt"
        )


def _execute_gpu_worker_process(
    *,
    run_store: LegacyRunStore,
    worker_request: StageWorkerRequest,
    environment: Mapping[str, str],
    selected_plugin_records: tuple[PluginRecord, ...],
) -> StageWorkerResult:
    """Execute a GPU-bound local stage with a process-private environment."""
    import subprocess

    child_environment = dict(os.environ)
    child_environment.update(environment)
    command = [
        sys.executable,
        "-m",
        "loom.pipeline.execution._managed_local_worker",
        "--run-uri",
        worker_request.run_uri,
        "--stage",
        worker_request.stage_name,
        "--attempt",
        str(worker_request.attempt),
    ]
    for record in selected_plugin_records:
        command.extend(("--plugin", f"{record.group}:{record.name}"))
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_environment,
    )
    try:
        stdout, stderr = process.communicate()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        raise
    raw_result = run_store.read_stage_worker_result(
        worker_request.run_uri,
        worker_request.stage_name,
        attempt=worker_request.attempt,
    )
    if raw_result is None:
        detail = (stderr or stdout).strip()[-1_000:]
        raise ManagedLocalError(
            "GPU worker process exited without a durable result"
            + (f": {detail}" if detail else "")
        )
    result = StageWorkerResult.from_dict(raw_result)
    if (
        result.run_uri != worker_request.run_uri
        or result.stage_name != worker_request.stage_name
        or result.attempt != worker_request.attempt
    ):
        raise ManagedLocalError("GPU worker result identity conflicts")
    successful = result.status in {StageStatus.SUCCEEDED, StageStatus.CANCELLED}
    if successful != (process.returncode == 0):
        raise ManagedLocalError("GPU worker result conflicts with process exit")
    return replace(
        result,
        executor_metadata={
            **dict(result.executor_metadata),
            "gpu_worker_process_boundary": True,
        },
    )


def _emit_assignment_event(
    journal: SQLiteAgentJournal,
    coordinator: SQLiteCoordinatorAssignments,
    assignment_id: str,
    kind: str,
    payload: Mapping[str, PlainData],
) -> None:
    event_id = f"{assignment_id}:{kind}"
    event_payload: dict[str, PlainData] = {"kind": kind, **dict(payload)}
    sequence = journal.append_event(assignment_id, event_id, event_payload)
    coordinator.record_event(assignment_id, sequence, event_id, event_payload)
    journal.acknowledge(assignment_id, sequence)


def _fresh_availability_revision(
    *,
    assignment: ManagedAssignment,
    providers: Mapping[str, AgentResourceProvider],
    operation: str,
) -> str:
    observations: list[PlainData] = []
    for resource_kind, provider in sorted(providers.items()):
        result = provider.observe(
            ObserveRequest(
                assignment.agent_id,
                assignment.session_id,
                f"{assignment.assignment_id}:observe:{operation}:{resource_kind}",
            )
        )
        if assignment.claim_id in result.live_claim_ids:
            raise ManagedLocalError(
                "fresh availability still reflects the released assignment as live"
            )
        observations.append(
            {
                "resource_kind": resource_kind,
                "descriptor": provider.descriptor.to_dict(),
                "availability_revision": result.availability_revision,
                "atoms": [atom.to_dict() for atom in result.atoms],
                "live_claim_ids": list(result.live_claim_ids),
            }
        )
    encoded = _json({"observations": observations})
    return "availability-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _worker_terminal_reason(result: StageWorkerResult) -> LifecycleReason:
    if result.status is StageStatus.FAILED:
        failure = result.failure
        return LifecycleReason(
            code="managed_worker_failed",
            message=(
                failure.message if isinstance(failure, ExecutionFailure) else None
            ),
            detail={"attempt": result.attempt},
        )
    if result.status is StageStatus.CANCELLED:
        return LifecycleReason(
            code="managed_worker_cancelled",
            message="managed worker cancelled",
            detail={"attempt": result.attempt},
        )
    raise ManagedLocalError("successful worker result has no failure reason")


def _start_failed_worker_result(
    request: StageWorkerRequest, error: ManagedProcessStartError
) -> StageWorkerResult:
    failed_at = utc_timestamp()
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        failed_at=failed_at,
        executor=request.executor_name,
        failure_type="executor_infrastructure",
        message=str(error),
        exception_type=type(error).__name__,
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        details={"process_created": False},
    )
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=StageStatus.FAILED,
        started_at=failed_at,
        finished_at=failed_at,
        executor_name=request.executor_name,
        failure=failure,
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        executor_metadata={"process_created": False},
    )


def _cancelled_worker_result(request: StageWorkerRequest) -> StageWorkerResult:
    cancelled_at = utc_timestamp()
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=StageStatus.CANCELLED,
        started_at=cancelled_at,
        finished_at=cancelled_at,
        executor_name=request.executor_name,
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        executor_metadata={"cancellation_epoch_effective": True},
    )


def _launch_managed_worker(
    process_execution_id: str,
    worker: Callable[[], StageWorkerResult],
) -> _ManagedWorkerHandle:
    handle = _ManagedWorkerHandle(process_execution_id, worker)
    handle.start()
    return handle


def _managed_root_failed_worker_result(
    request: StageWorkerRequest, error: BaseException
) -> StageWorkerResult:
    failed_at = utc_timestamp()
    message = str(error) or type(error).__name__
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        failed_at=failed_at,
        executor=request.executor_name,
        failure_type="executor_infrastructure",
        message=message,
        exception_type=f"{type(error).__module__}.{type(error).__name__}",
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        details={"process_created": True},
    )
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=StageStatus.FAILED,
        started_at=failed_at,
        finished_at=failed_at,
        executor_name=request.executor_name,
        failure=failure,
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        exit_code=1,
        executor_metadata={"process_created": True},
    )


def _capacity_atom_from_dict(value: Mapping[str, object]) -> CapacityAtom:
    try:
        return CapacityAtom(
            owner_resource_kind=cast(str, value["owner_resource_kind"]),
            local_capacity_key=cast(str, value["local_capacity_key"]),
            amount=ExactQuantity.from_dict(value["amount"]),
            unit=cast(str, value["unit"]),
            granularity=ExactQuantity.from_dict(value["granularity"]),
        )
    except Exception as exc:
        raise ManagedLocalError(
            "durable offer contains an invalid capacity atom"
        ) from exc


def _validate_decision_receipt(
    value: Mapping[str, PlainData],
    *,
    assignment: ManagedAssignment,
    claims: Sequence[ResourceClaim],
) -> str:
    if not isinstance(value, Mapping):
        raise ManagedLocalError("decision receipt must be a mapping")
    required_text = (
        "policy_epoch",
        "stage_work_id",
        "candidate_id",
        "snapshot_revision",
        "offer_revision",
        "as_of",
    )
    for name in required_text:
        if not isinstance(value.get(name), str) or not value[name]:
            raise ManagedLocalError(f"decision receipt requires {name}")
    if value["stage_work_id"] != assignment.stage_work_id:
        raise ManagedLocalError("decision receipt stage work does not match assignment")
    if value["candidate_id"] != assignment.agent_id:
        raise ManagedLocalError("decision receipt candidate does not match assignment")
    if value["offer_revision"] != assignment.offer_id:
        raise ManagedLocalError("decision receipt offer does not match assignment")
    stage_work_revision = value.get("stage_work_revision")
    if (
        isinstance(stage_work_revision, bool)
        or not isinstance(stage_work_revision, int)
        or stage_work_revision < 1
    ):
        raise ManagedLocalError("decision receipt requires stage_work_revision")
    if not isinstance(value.get("fallback_eligible"), bool):
        raise ManagedLocalError("decision receipt requires fallback_eligible")
    for name in ("policy_descriptor", "score_summary"):
        if not isinstance(value.get(name), Mapping):
            raise ManagedLocalError(f"decision receipt requires {name}")
    reason_codes = value.get("reason_codes")
    if not isinstance(reason_codes, Sequence) or isinstance(reason_codes, str):
        raise ManagedLocalError("decision receipt requires reason_codes")
    if any(not isinstance(code, str) or not code for code in reason_codes):
        raise ManagedLocalError("decision reason codes must be non-empty strings")
    component_descriptors = value.get("component_descriptors")
    if not isinstance(component_descriptors, Sequence) or isinstance(
        component_descriptors, str
    ):
        raise ManagedLocalError("decision receipt requires component_descriptors")
    try:
        parsed_components = tuple(
            SchedulingComponentDescriptor.from_dict(descriptor)
            for descriptor in component_descriptors
        )
    except Exception as exc:
        raise ManagedLocalError("decision component descriptors are invalid") from exc
    if not parsed_components or len({item.kind for item in parsed_components}) != len(
        parsed_components
    ):
        raise ManagedLocalError(
            "decision component descriptors must be non-empty and unique"
        )
    if {item.kind for item in parsed_components} != {
        claim.resource_kind for claim in claims
    }:
        raise ManagedLocalError(
            "decision component descriptors do not match reservation resources"
        )
    provider_descriptors = value.get("provider_descriptors")
    if not isinstance(provider_descriptors, Sequence) or isinstance(
        provider_descriptors, str
    ):
        raise ManagedLocalError("decision receipt requires provider_descriptors")
    try:
        parsed_providers = tuple(
            SchedulingComponentDescriptor.from_dict(descriptor)
            for descriptor in provider_descriptors
        )
    except Exception as exc:
        raise ManagedLocalError("decision provider descriptors are invalid") from exc
    if not parsed_providers or len({item.kind for item in parsed_providers}) != len(
        parsed_providers
    ):
        raise ManagedLocalError(
            "decision provider descriptors must be non-empty and unique"
        )
    if {item.kind for item in parsed_providers} != {
        claim.resource_kind for claim in claims
    }:
        raise ManagedLocalError(
            "decision provider descriptors do not match reservation resources"
        )
    contract_descriptors = value.get("claim_contract_descriptors")
    if not isinstance(contract_descriptors, Sequence) or isinstance(
        contract_descriptors, str
    ):
        raise ManagedLocalError("decision receipt requires claim_contract_descriptors")
    try:
        recorded_contracts = tuple(
            ResourceClaimContractDescriptor.from_dict(descriptor)
            for descriptor in contract_descriptors
        )
    except Exception as exc:
        raise ManagedLocalError("decision claim contracts are invalid") from exc
    expected_contracts = tuple(
        sorted({claim.contract for claim in claims}, key=lambda item: item.key)
    )
    if recorded_contracts != expected_contracts:
        raise ManagedLocalError("decision claim contracts do not match reservation")
    secret_names = {"secret", "password", "credential", "private_key"}

    def reject_secrets(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if isinstance(key, str) and key.lower() in secret_names:
                    raise ManagedLocalError("decision receipt contains secret material")
                reject_secrets(nested)
        elif isinstance(item, Sequence) and not isinstance(item, str | bytes):
            for nested in item:
                reject_secrets(nested)

    reject_secrets(value)
    encoded = _json(value)
    if len(encoded.encode("utf-8")) > 16_384:
        raise ManagedLocalError("decision receipt exceeds its bounded limit")
    return encoded


def _json(value: Mapping[str, PlainData]) -> str:
    try:
        frozen = freeze_plain_data(value, path="managed local journal")
    except ValueError as exc:
        raise ManagedLocalError(str(exc)) from exc
    return json.dumps(
        thaw_plain_data(frozen, path="managed local journal"),
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "AgentResourceProvider",
    "AssignmentState",
    "AtomResourceProvider",
    "ClaimCommand",
    "ClaimOutcome",
    "ClaimResult",
    "CpuResourceProvider",
    "ManagedAssignment",
    "ManagedExecutionReceipt",
    "ManagedLocalError",
    "ManagedOfferSnapshot",
    "ManagedProcessStartError",
    "MemoryResourceProvider",
    "GpuResourceProvider",
    "ObserveRequest",
    "ObserveResult",
    "SQLiteAgentJournal",
    "SQLiteCoordinatorAssignments",
    "grant_and_start_managed_assignment",
    "run_managed_local_assignment",
]
