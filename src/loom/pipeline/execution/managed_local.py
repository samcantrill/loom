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
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from threading import RLock
from typing import Protocol, cast

from loom.pipeline.executors import Executor
from loom.pipeline.orchestration import SchedulingProjectionState, StageWorkRecord
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LegacyRunStore, LifecycleReason, OutputCommit
from loom.pipeline.resources import ResourceValidatorRegistry
from loom.plugins.entrypoints import PluginRecord
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.pipeline.stores.authority import (
    ExecutionFence,
    PreparedAttemptExecutionAuthority,
)

from .models import ExecutionFailure, StageWorkerRequest, StageWorkerResult
from .stage_worker import ArtifactStoreFactory, execute_stage_worker_request


class ManagedLocalError(ValueError):
    """An assignment, journal, or provider invariant was violated."""


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


@dataclass(frozen=True, slots=True)
class ClaimCommand:
    """Idempotent provider command; its operation ID is stable across replay."""

    assignment: ManagedAssignment
    operation_id: str
    claim: ResourceClaim

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, ManagedAssignment):
            raise ManagedLocalError("command assignment is invalid")
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ManagedLocalError("operation_id must be a non-empty string")
        if not isinstance(self.claim, ResourceClaim):
            raise ManagedLocalError("claim must be a ResourceClaim")


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


class SQLiteAgentJournal:
    """Durable local journal for the agent-owned side of an assignment.

    The journal is intentionally append/replay oriented.  ``record_event``
    makes a fact durable before it can be delivered and refuses an event gap.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

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
                    return self._set_state(
                        assignment.assignment_id, AssignmentState.DECLINED
                    )
                return self._set_state(
                    assignment.assignment_id, AssignmentState.PREPARE_UNKNOWN
                )
            prepared.append((provider, command))
        return self._set_state(assignment.assignment_id, AssignmentState.PREPARED)

    def accept(self, assignment_id: str) -> AssignmentState:
        return self._advance(
            assignment_id, AssignmentState.PREPARED, AssignmentState.ACCEPTED
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
        except Exception:
            self._set_state(assignment_id, AssignmentState.START_UNKNOWN)
            raise
        if not isinstance(process_id, str) or not process_id:
            self._set_state(assignment_id, AssignmentState.START_FAILED)
            raise ManagedLocalError("launcher proved no process identifier")
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
            if not _agent_at_or_after(state, AssignmentState.PROCESS_STARTED):
                raise ManagedLocalError("result requires a confirmed process start")
            encoded = _json(result)
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

    def read_result(self, assignment_id: str) -> StageWorkerResult | None:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            if row["result_json"] is None:
                return None
            return StageWorkerResult.from_dict(
                json.loads(cast(str, row["result_json"]))
            )

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS assignments ("
                "assignment_id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, "
                "request_json TEXT NOT NULL, claims_json TEXT, state TEXT NOT NULL, "
                "grant_fence TEXT, process_execution_id TEXT, result_json TEXT, "
                "availability_revision TEXT)"
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

    @staticmethod
    def _assignment(conn: sqlite3.Connection, assignment_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
        if row is None:
            raise ManagedLocalError("assignment is not durable")
        return row


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

    def __init__(self, path: str | Path, capacity: Sequence[CapacityAtom]) -> None:
        self.path = Path(path)
        self._capacity = {atom.key: atom.amount.fraction for atom in capacity}

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
            if work is not None:
                raise ManagedLocalError("stage work already has a live assignment")
            unresolved = conn.execute(
                "SELECT assignment_id FROM coordinator_assignments "
                "WHERE agent_id = ? AND session_id = ? AND offer_id = ? "
                "AND state IN ('reserved','bound')",
                (assignment.agent_id, assignment.session_id, assignment.offer_id),
            ).fetchone()
            if unresolved is not None:
                raise ManagedLocalError(
                    "availability revision already has an unresolved admission"
                )
            active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ? AND state IN ('reserved','bound','accepted','granted','running','unknown')",
                    (assignment.run_uri,),
                ).fetchone()[0]
            )
            if active >= max_parallel_stages:
                raise ManagedLocalError("run active-assignment limit reached")
            for key, amount in requested.items():
                used = sum(
                    (
                        Fraction(row["numerator"], row["denominator"])
                        for row in conn.execute(
                            "SELECT numerator, denominator FROM coordinator_atoms a JOIN coordinator_assignments x ON x.assignment_id = a.assignment_id WHERE a.resource_kind = ? AND a.capacity_key = ? AND x.state IN ('reserved','bound','accepted','granted','running','unknown','terminal','logical_released')",
                            key,
                        )
                    ),
                    Fraction(0),
                )
                if used + amount > self._capacity[key]:
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
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
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()


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
    recorded_descriptors = {
        descriptor.kind: descriptor
        for descriptor in (
            SchedulingComponentDescriptor.from_dict(item)
            for item in cast(
                Sequence[Mapping[str, object]],
                validated_decision["component_descriptors"],
            )
        )
    }
    for claim in claims:
        provider = providers.get(claim.resource_kind)
        if provider is None:
            raise ManagedLocalError("no provider for claim resource kind")
        if provider.descriptor != recorded_descriptors.get(claim.resource_kind):
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
        coordinator.advance(
            assignment.assignment_id, expected="bound", next_state="terminal"
        )
        coordinator.advance(
            assignment.assignment_id,
            expected="terminal",
            next_state="logical_released",
        )
        availability_revision = _fresh_availability_revision(
            assignment=assignment,
            providers=providers,
            operation="declined",
        )
        journal.release_declined(assignment.assignment_id, availability_revision)
        coordinator.advance(
            assignment.assignment_id,
            expected="logical_released",
            next_state="released",
        )
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

    process_id = process_execution_id or f"{assignment.assignment_id}:root"
    result_holder: list[StageWorkerResult] = []

    def launch_exact_worker() -> str:
        result_holder.append(
            execute_stage_worker_request(
                run_store=run_store,
                worker_request=worker_request,
                executor=executor,
                artifact_store_factory=artifact_store_factory,
                selected_plugin_records=selected_plugin_records,
                resource_validator_registry=resource_validator_registry,
            )
        )
        return process_id

    try:
        journal.start_once(
            assignment.assignment_id,
            process_id,
            launch_exact_worker,
        )
    except Exception:
        coordinator.advance(
            assignment.assignment_id, expected="granted", next_state="unknown"
        )
        raise
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
    worker_result = (
        result_holder[0]
        if result_holder
        else journal.read_result(assignment.assignment_id)
    )
    if worker_result is None:
        raise ManagedLocalError(
            "managed process started without a durable result; relaunch is forbidden"
        )
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
        assignment.assignment_id, expected="running", next_state="terminal"
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


def _claim_command_dict(command: ClaimCommand) -> dict[str, PlainData]:
    claim = command.claim
    return {
        "assignment_id": command.assignment.assignment_id,
        "operation_id": command.operation_id,
        "resource_kind": claim.resource_kind,
        "contract": claim.contract.to_dict(),
        "atoms": [atom.to_dict() for atom in claim.atoms],
        "provider_data_version": claim.provider_data_version,
        "provider_data": thaw_plain_data(
            claim.provider_data, path="claim.provider_data"
        ),
        "claim_fingerprint": claim.fingerprint,
    }


def _operation_command(command: ClaimCommand, operation: str) -> ClaimCommand:
    return ClaimCommand(
        assignment=command.assignment,
        operation_id=f"{command.operation_id}:{operation}",
        claim=command.claim,
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
    "MemoryResourceProvider",
    "ObserveRequest",
    "ObserveResult",
    "SQLiteAgentJournal",
    "SQLiteCoordinatorAssignments",
    "grant_and_start_managed_assignment",
    "run_managed_local_assignment",
]
