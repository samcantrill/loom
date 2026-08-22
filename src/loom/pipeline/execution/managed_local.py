"""Durable, assignment-scoped local admission primitives.

This module is deliberately independent of the legacy ``run_stage_job`` path.
It is the small local half of the Stage 29 saga: coordinator code owns logical
reservations, this journal owns physical claims and the worker receives one
already-granted assignment.  In particular, none of these operations allocate
an attempt or take a run lock.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Protocol

from loom.scheduling import CapacityAtom, ResourceClaim, SchedulingComponentDescriptor
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data


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
    PREPARED = "prepared"
    ACCEPTED = "accepted"
    GRANTED = "granted"
    START_INTENT = "start_intent"
    PROCESS_STARTED = "process_started"
    START_FAILED = "start_failed"
    START_UNKNOWN = "start_unknown"
    RESULT_DURABLE = "result_durable"
    RELEASED = "released"


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


class AgentResourceProvider(Protocol):
    """Versioned physical-resource lifecycle; outcomes never imply OS isolation."""

    descriptor: SchedulingComponentDescriptor

    def observe(self) -> tuple[CapacityAtom, ...]: ...
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
        self, descriptor: SchedulingComponentDescriptor, atoms: Sequence[CapacityAtom]
    ) -> None:
        self.descriptor = descriptor
        self._capacity = {atom.key: atom for atom in atoms}
        self._claims: dict[str, tuple[ClaimCommand, ClaimOutcome]] = {}

    def observe(self) -> tuple[CapacityAtom, ...]:
        used: dict[tuple[str, str], int] = {}
        for command, state in self._claims.values():
            if state not in {ClaimOutcome.PREPARED, ClaimOutcome.ACTIVE}:
                continue
            for atom in command.claim.atoms:
                used[atom.key] = used.get(atom.key, 0) + atom.amount.numerator
        result: list[CapacityAtom] = []
        for key, atom in self._capacity.items():
            # Built-in CPU/memory claims use whole quantities; retain exact type.
            available = atom.amount.numerator - used.get(key, 0)
            if available > 0:
                result.append(
                    CapacityAtom(
                        atom.owner_resource_kind,
                        atom.local_capacity_key,
                        type(atom.amount)(available, atom.amount.denominator),
                        atom.unit,
                        atom.granularity,
                    )
                )
        return tuple(sorted(result, key=lambda item: item.key))

    def prepare(self, command: ClaimCommand) -> ClaimResult:
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
        remaining = {atom.key: atom.amount.fraction for atom in self.observe()}
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
        return ClaimResult(
            ClaimOutcome.PREPARED, command.operation_id, command.claim.fingerprint
        )

    def reconcile(self, command: ClaimCommand) -> ClaimResult:
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
        return ClaimResult(
            ClaimOutcome.ACTIVE, command.operation_id, command.claim.fingerprint
        )

    def abort(self, command: ClaimCommand) -> ClaimResult:
        return self.release(command)

    def release(self, command: ClaimCommand) -> ClaimResult:
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
        self._claims[command.assignment.assignment_id] = (
            command,
            ClaimOutcome.RELEASED,
        )
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
        prepared: list[tuple[AgentResourceProvider, ClaimCommand]] = []
        for command in sorted(commands, key=lambda item: item.claim.resource_kind):
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            result = provider.prepare(command)
            if result.outcome is not ClaimOutcome.PREPARED:
                for previous, previous_command in reversed(prepared):
                    previous.abort(previous_command)
                if result.outcome is ClaimOutcome.DECLINED:
                    return self._set_state(
                        assignment.assignment_id, AssignmentState.REQUEST_DURABLE
                    )
                return self._set_state(
                    assignment.assignment_id, AssignmentState.REQUEST_DURABLE
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
            if state is AssignmentState.GRANTED:
                return state
            if state is not AssignmentState.ACCEPTED:
                raise ManagedLocalError("assignment is not accepted")
            conn.execute(
                "UPDATE assignments SET state = ?, grant_fence = ? WHERE assignment_id = ?",
                (AssignmentState.GRANTED.value, fence, assignment_id),
            )
            return AssignmentState.GRANTED

    def start_once(self, assignment_id: str, launcher: Callable[[], str]) -> str:
        """Persist intent before exactly one launcher invocation."""
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if state is AssignmentState.PROCESS_STARTED:
                return str(row["process_execution_id"])
            if state is not AssignmentState.GRANTED:
                raise ManagedLocalError("assignment is not granted for launch")
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (AssignmentState.START_INTENT.value, assignment_id),
            )
        try:
            process_id = launcher()
        except Exception:
            self._set_state(assignment_id, AssignmentState.START_UNKNOWN)
            raise
        if not isinstance(process_id, str) or not process_id:
            self._set_state(assignment_id, AssignmentState.START_FAILED)
            raise ManagedLocalError("launcher proved no process identifier")
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            conn.execute(
                "UPDATE assignments SET state = ?, process_execution_id = ? WHERE assignment_id = ?",
                (AssignmentState.PROCESS_STARTED.value, process_id, assignment_id),
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
            if AssignmentState(row["state"]) not in {
                AssignmentState.PROCESS_STARTED,
                AssignmentState.RESULT_DURABLE,
            }:
                raise ManagedLocalError("result requires a confirmed process start")
            encoded = _json(result)
            if row["result_json"] is not None and row["result_json"] != encoded:
                raise ManagedLocalError("result conflicts with durable result")
            conn.execute(
                "UPDATE assignments SET state = ?, result_json = ? WHERE assignment_id = ?",
                (AssignmentState.RESULT_DURABLE.value, encoded, assignment_id),
            )
            return AssignmentState.RESULT_DURABLE

    def release(self, assignment_id: str) -> AssignmentState:
        return self._advance(
            assignment_id, AssignmentState.RESULT_DURABLE, AssignmentState.RELEASED
        )

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS assignments (assignment_id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, request_json TEXT NOT NULL, state TEXT NOT NULL, grant_fence TEXT, process_execution_id TEXT, result_json TEXT)"
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
            if AssignmentState(row["state"]) not in {
                AssignmentState.REQUEST_DURABLE,
                AssignmentState.PREPARED,
            }:
                raise ManagedLocalError(
                    "assignment request cannot be prepared in current state"
                )

    def _advance(
        self, assignment_id: str, prior: AssignmentState, next_state: AssignmentState
    ) -> AssignmentState:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if state is next_state:
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
        receipt = _json(decision_receipt)
        if len(receipt.encode("utf-8")) > 16_384:
            raise ManagedLocalError("decision receipt exceeds its bounded limit")
        atoms = tuple(atom for claim in claims for atom in claim.atoms)
        if not atoms:
            raise ManagedLocalError("logical reservation requires capacity atoms")
        if any(atom.key not in self._capacity for atom in atoms):
            raise ManagedLocalError("claim uses atom outside configured capacity")
        identity = _json(_assignment_dict(assignment))
        with self._transaction() as conn:
            current = conn.execute(
                "SELECT identity_json, state FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment.assignment_id,),
            ).fetchone()
            if current is not None:
                if current["identity_json"] != identity:
                    raise ManagedLocalError(
                        "assignment ID conflicts with durable target"
                    )
                return str(current["state"])
            work = conn.execute(
                "SELECT assignment_id FROM coordinator_assignments WHERE stage_work_id = ? AND state IN ('reserved','bound','accepted','granted','running','unknown')",
                (assignment.stage_work_id,),
            ).fetchone()
            if work is not None:
                raise ManagedLocalError("stage work already has a live assignment")
            active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ? AND state IN ('reserved','bound','accepted','granted','running','unknown')",
                    (assignment.run_uri,),
                ).fetchone()[0]
            )
            if active >= max_parallel_stages:
                raise ManagedLocalError("run active-assignment limit reached")
            requested: dict[tuple[str, str], Fraction] = {}
            for atom in atoms:
                requested[atom.key] = (
                    requested.get(atom.key, Fraction(0)) + atom.amount.fraction
                )
            for key, amount in requested.items():
                used = sum(
                    (
                        Fraction(row["numerator"], row["denominator"])
                        for row in conn.execute(
                            "SELECT numerator, denominator FROM coordinator_atoms a JOIN coordinator_assignments x ON x.assignment_id = a.assignment_id WHERE a.resource_kind = ? AND a.capacity_key = ? AND x.state IN ('reserved','bound','accepted','granted','running','unknown')",
                            key,
                        )
                    ),
                    Fraction(0),
                )
                if used + amount > self._capacity[key]:
                    raise ManagedLocalError("logical capacity atom is unavailable")
            conn.execute(
                "INSERT INTO coordinator_assignments (assignment_id, identity_json, run_uri, stage_work_id, state, receipt_json) VALUES (?, ?, ?, ?, 'reserved', ?)",
                (
                    assignment.assignment_id,
                    identity,
                    assignment.run_uri,
                    assignment.stage_work_id,
                    receipt,
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
            return "reserved"

    def advance(self, assignment_id: str, *, expected: str, next_state: str) -> str:
        if expected not in self._LIVE or next_state not in self._LIVE | {
            "terminal",
            "released",
        }:
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
            if row["state"] != expected:
                raise ManagedLocalError("stale coordinator assignment transition")
            conn.execute(
                "UPDATE coordinator_assignments SET state = ? WHERE assignment_id = ?",
                (next_state, assignment_id),
            )
            return next_state

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS coordinator_assignments (assignment_id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, run_uri TEXT NOT NULL, stage_work_id TEXT NOT NULL, state TEXT NOT NULL, receipt_json TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS coordinator_atoms (assignment_id TEXT NOT NULL, resource_kind TEXT NOT NULL, capacity_key TEXT NOT NULL, numerator INTEGER NOT NULL, denominator INTEGER NOT NULL, PRIMARY KEY (assignment_id, resource_kind, capacity_key))"
            )
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()


def _assignment_dict(value: ManagedAssignment) -> dict[str, PlainData]:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


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
    "ManagedAssignment",
    "ManagedLocalError",
    "SQLiteAgentJournal",
    "SQLiteCoordinatorAssignments",
]
