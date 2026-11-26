"""Fence a lost agent session and qualify its successor against durable evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, Protocol, cast

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from ._service_signals import write_status
from .agent_sessions import (
    AgentAssignmentControl, AgentSession, AgentSessionState, SessionReplacementRequest,
    _REPLACEMENT_ASSIGNMENT_REFERENCE_CLASSES, _canonical_json, _digest,
    _managed_containment_evidence, _session_from_row, invalidate_current_offers,
)
from .errors import QueueConflictError, QueueServiceError, QueueStorageError

if TYPE_CHECKING:
    from .local_daemon import RecoverUnknownAssignment


@dataclass(frozen=True, slots=True)
class _ReplacementProjection:
    value: Mapping[str, PlainData]
    required_claim_ids: tuple[str, ...]
    recovery_requests: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class _ReplacementOfferAdmission:
    operation_id: str
    request: SessionReplacementRequest
    old_session_id: str
    prior_readiness: str
    decision_projection_digest: str
    projection: _ReplacementProjection
    durable_projection: Mapping[str, PlainData]


class ReplacementExecution(Protocol):
    def scheduling_reload_guard(self) -> AbstractContextManager[None]: ...

    def session_replacement_assignment_facts(
        self, session_id: str,
    ) -> tuple[Mapping[str, PlainData], ...]: ...

    def validate_session_replacement_recovery(
        self, request: RecoverUnknownAssignment,
    ) -> Mapping[str, PlainData]: ...


@dataclass(frozen=True, slots=True)
class SessionReplacement:
    """Journal, execution evidence, and transactional fence for one coordinator."""

    connection: Callable[[], AbstractContextManager[sqlite3.Connection]]
    current_execution: Callable[[], ReplacementExecution | None]
    coordinator_id: Callable[[], str]
    clock: Callable[[], str]
    accepted_time: Callable[[sqlite3.Connection], str]
    write_guarded: Callable[[
        Callable[[sqlite3.Connection], Mapping[str, PlainData]],
        Callable[[], AbstractContextManager],
    ], Mapping[str, PlainData]]
    notify: Callable[[str], None]

    def replace(
        self,
        request: SessionReplacementRequest,
        *,
        principal_id: str,
        authorize: Callable[[], None],
    ) -> Mapping[str, PlainData]:
        """Durably decide a guarded replacement from complete coordinator facts.

        This is intentionally a coordinator operation, rather than an agent RPC:
        possession of an agent credential or an empty new journal is not evidence
        that the previous session stopped.  The later ordinary registration is the
        only place that allocates the successor identity.
        """

        authorize()
        encoded = _canonical_json(request.to_dict())
        digest = _digest(request.to_dict())
        execution = self.current_execution()
        if execution is None:
            raise QueueServiceError("replacement coordinator execution is unavailable")
        with self.connection() as conn:
            prior = conn.execute(
                "SELECT principal_id, request_json, request_digest, result_json "
                "FROM session_replacements WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if prior is not None:
                return _replacement_replay(
                    prior,
                    principal_id=principal_id,
                    request_json=encoded,
                    request_digest=digest,
                )
            old = conn.execute(
                "SELECT * FROM agent_sessions WHERE agent_id = ? AND state = ?",
                (request.agent_id, AgentSessionState.ACTIVE.value),
            ).fetchone()
            if old is None:
                raise QueueConflictError("agent has no current session to replace")
            old_session = _session_from_row(
                old,
                self.coordinator_id(),
                expected_principal=str(old["principal_id"]),
            )
        execution_facts = execution.session_replacement_assignment_facts(
            old_session.session_id
        )
        with self.connection() as conn:
            candidate = _build_replacement_projection(
                conn,
                session=old_session,
                execution_facts=execution_facts,
                observed_at=self.clock(),
            )
        authority_facts = _replacement_authority_facts(execution, candidate)
        @contextmanager
        def observe_assignments():
            nonlocal execution_facts
            with execution.scheduling_reload_guard():
                execution_facts = execution.session_replacement_assignment_facts(old_session.session_id)
                yield

        def apply(conn: sqlite3.Connection) -> Mapping[str, PlainData]:
            authorize()
            if self.current_execution() is not execution:
                raise QueueConflictError("session replacement execution owner changed")
            raced = conn.execute(
                "SELECT principal_id, request_json, request_digest, result_json "
                "FROM session_replacements WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if raced is not None:
                result = _replacement_replay(
                    raced,
                    principal_id=principal_id,
                    request_json=encoded,
                    request_digest=digest,
                )
                return result
            current = conn.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?",
                (old_session.session_id,),
            ).fetchone()
            current_session = _session_from_row(
                current,
                self.coordinator_id(),
                expected_principal=str(old["principal_id"]),
            )
            if current_session != old_session:
                raise QueueConflictError("old session changed before replacement fence")
            decided_at = self.accepted_time(conn)
            write_status(
                conn, "operation",
                "UPDATE agent_controls SET state = 'superseded', "
                "result_code = 'session_replaced' WHERE session_id = ? "
                "AND state IN ('pending_delivery','applying')",
                (old_session.session_id,),
            )
            projection = _build_replacement_projection(
                conn,
                session=old_session,
                execution_facts=execution_facts,
                observed_at=self.clock(),
            )
            _require_monotonic_replacement_projection(candidate.value, projection.value)
            durable_projection = _bind_replacement_authority_facts(
                projection, authority_facts
            )
            invalidate_current_offers(conn, old_session.session_id)
            conn.execute(
                "UPDATE agent_poll_state SET active = 0 WHERE session_id = ?",
                (old_session.session_id,),
            )
            updated = conn.execute(
                "UPDATE agent_sessions SET state = ? WHERE session_id = ? AND state = ?",
                (
                    AgentSessionState.REPLACED.value,
                    old_session.session_id,
                    AgentSessionState.ACTIVE.value,
                ),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("old session changed before replacement fence")
            conn.execute(
                "INSERT INTO agent_session_tombstones(session_id, state) VALUES (?, ?)",
                (old_session.session_id, AgentSessionState.REPLACED.value),
            )
            result = _replacement_result(
                request=request,
                old_session_id=old_session.session_id,
                successor_session_id=None,
                state="decision",
                readiness="withheld",
                withholding_reason="successor_registration_required",
                projection=durable_projection,
            )
            projection_json = _canonical_json(durable_projection)
            write_status(
                conn, "operation",
                "INSERT INTO session_replacements("
                "operation_id, principal_id, request_json, request_digest, agent_id, "
                "old_session_id, successor_session_id, state, readiness, "
                "withholding_reason, decision_projection_json, "
                "decision_projection_digest, required_claim_ids_json, "
                "observed_claim_ids_json, successor_observation_digest, "
                "readiness_projection_digest, result_json, decided_at, ready_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, 'decision', 'withheld', ?, ?, ?, "
                "?, '[]', NULL, NULL, ?, ?, NULL)",
                (
                    request.operation_id,
                    principal_id,
                    encoded,
                    digest,
                    request.agent_id,
                    old_session.session_id,
                    "successor_registration_required",
                    projection_json,
                    hashlib.sha256(projection_json.encode("utf-8")).hexdigest(),
                    json.dumps(projection.required_claim_ids, separators=(",", ":")),
                    _canonical_json(result),
                    decided_at,
                ),
            )
            return freeze_plain_data(result, path="session replacement receipt")

        result = self.write_guarded(apply, observe_assignments)
        self.notify(old_session.session_id)
        return result

    def prepare_offer(
        self, successor_session_id: str
    ) -> _ReplacementOfferAdmission | None:
        execution = self.current_execution()
        if execution is None:
            raise QueueServiceError("replacement coordinator execution is unavailable")
        with self.connection() as conn:
            row = conn.execute(
                "SELECT r.*, s.principal_id AS old_principal_id "
                "FROM session_replacements r JOIN agent_sessions s "
                "ON s.session_id = r.old_session_id "
                "WHERE r.successor_session_id = ?",
                (successor_session_id,),
            ).fetchone()
            if row is None:
                return None
            if str(row["state"]) not in {"bound", "ready"} or str(row["readiness"]) not in {
                "withheld",
                "ready",
            }:
                raise QueueConflictError("replacement readiness state is invalid")
            old_row = conn.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ? AND state = ?",
                (str(row["old_session_id"]), AgentSessionState.REPLACED.value),
            ).fetchone()
            if old_row is None:
                raise QueueConflictError("replacement old-session fence is unavailable")
            tombstone = conn.execute(
                "SELECT state FROM agent_session_tombstones WHERE session_id = ?",
                (str(row["old_session_id"]),),
            ).fetchone()
            if (
                tombstone is None
                or str(tombstone["state"]) != AgentSessionState.REPLACED.value
            ):
                raise QueueConflictError("replacement old-session tombstone is unavailable")
            old_session = _session_from_row(
                old_row,
                self.coordinator_id(),
                expected_principal=str(row["old_principal_id"]),
            )
            try:
                request_value = json.loads(str(row["request_json"]))
                decision_value = json.loads(str(row["decision_projection_json"]))
                required_value = json.loads(str(row["required_claim_ids_json"]))
            except json.JSONDecodeError as exc:
                raise QueueStorageError("session replacement decision is invalid") from exc
            if not isinstance(request_value, Mapping) or not isinstance(
                decision_value, Mapping
            ):
                raise QueueStorageError("session replacement decision is invalid")
            request = SessionReplacementRequest.from_dict(request_value)
            decision = freeze_plain_data(
                decision_value, path="session replacement decision"
            )
            if not isinstance(decision, Mapping):
                raise QueueStorageError("session replacement decision is invalid")
            encoded_decision = _canonical_json(cast(Mapping[str, PlainData], decision))
            if hashlib.sha256(encoded_decision.encode("utf-8")).hexdigest() != str(
                row["decision_projection_digest"]
            ):
                raise QueueStorageError("session replacement decision digest conflicts")
            if (
                not isinstance(required_value, list)
                or any(not isinstance(item, str) for item in required_value)
                or len(set(required_value)) != len(required_value)
            ):
                raise QueueStorageError("session replacement claim inventory is invalid")
        execution_facts = execution.session_replacement_assignment_facts(
            old_session.session_id
        )
        with self.connection() as conn:
            projection = _build_replacement_projection(
                conn,
                session=old_session,
                execution_facts=execution_facts,
                observed_at=self.clock(),
            )
        _require_monotonic_replacement_projection(
            cast(Mapping[str, PlainData], decision), projection.value
        )
        decision_required = sorted(
            _projection_string(cast(Mapping[str, PlainData], item), "claim_id")
            for item in cast(Sequence[object], decision.get("assignments", ()))
            if isinstance(item, Mapping) and item.get("classification") == "contained"
        )
        if decision_required != sorted(cast(list[str], required_value)):
            raise QueueStorageError("session replacement claim inventory conflicts")
        authority_facts = _replacement_authority_facts(execution, projection)
        durable_projection = _bind_replacement_authority_facts(projection, authority_facts)
        return _ReplacementOfferAdmission(
            operation_id=str(row["operation_id"]),
            request=request,
            old_session_id=old_session.session_id,
            prior_readiness=str(row["readiness"]),
            decision_projection_digest=str(row["decision_projection_digest"]),
            projection=projection,
            durable_projection=durable_projection,
        )


def _replacement_replay(
    row: sqlite3.Row,
    *,
    principal_id: str,
    request_json: str,
    request_digest: str,
) -> Mapping[str, PlainData]:
    if (
        str(row["principal_id"]) != principal_id
        or str(row["request_json"]) != request_json
        or str(row["request_digest"]) != request_digest
    ):
        raise QueueConflictError("session replacement operation conflicts")
    try:
        result = json.loads(str(row["result_json"]))
    except json.JSONDecodeError as exc:
        raise QueueStorageError("session replacement result is invalid") from exc
    if not isinstance(result, Mapping):
        raise QueueStorageError("session replacement result is invalid")
    return freeze_plain_data(result, path="session replacement receipt")


def _build_replacement_projection(
    conn: sqlite3.Connection,
    *,
    session: AgentSession,
    execution_facts: Sequence[Mapping[str, PlainData]],
    observed_at: str,
) -> _ReplacementProjection:
    """Join every supported old-session owner or fail closed."""

    from .local_daemon import ManagedRecoveryTarget, RecoverUnknownAssignment

    execution_by_id: dict[str, Mapping[str, PlainData]] = {}
    for fact in execution_facts:
        assignment_id = _projection_string(fact, "assignment_id")
        if assignment_id in execution_by_id:
            raise QueueConflictError("old session coordinator inventory conflicts")
        if (
            _projection_string(fact, "agent_id") != session.agent_id
            or _projection_string(fact, "session_id") != session.session_id
        ):
            raise QueueConflictError("old session coordinator inventory conflicts")
        execution_by_id[assignment_id] = fact
    remote_rows = tuple(
        conn.execute(
            "SELECT * FROM remote_assignments WHERE session_id = ? "
            "ORDER BY assignment_id",
            (session.session_id,),
        )
    )
    remote_by_id = {str(row["assignment_id"]): row for row in remote_rows}
    if not set(remote_by_id).issubset(execution_by_id):
        raise QueueConflictError("old session coordinator inventory is incomplete")
    deliveries = {
        str(row["assignment_id"]): row
        for row in conn.execute(
            "SELECT assignment_id, session_id, availability_revision, "
            "coordinator_epoch, state, poll_sequence FROM agent_deliveries "
            "WHERE session_id = ? ORDER BY assignment_id",
            (session.session_id,),
        )
    }
    if set(deliveries) != set(remote_by_id):
        raise QueueConflictError("old session delivery inventory is incomplete")
    reference_rows = tuple(
        conn.execute(
            "SELECT reference_kind, reference_id, resolved "
            "FROM agent_coordinator_references WHERE session_id = ? "
            "ORDER BY reference_kind, reference_id",
            (session.session_id,),
        )
    )
    references = {
        str(row["reference_id"]): row
        for row in reference_rows
        if str(row["reference_kind"]) == "delivery"
    }
    if len(references) != len(reference_rows) or set(references) != set(remote_by_id):
        raise QueueConflictError("old session reference inventory is incomplete")
    coverage_rows = tuple(
        conn.execute(
            "SELECT assignment_id, reference_class "
            "FROM agent_replacement_coverage WHERE session_id = ? "
            "ORDER BY assignment_id, reference_class",
            (session.session_id,),
        )
    )
    expected_coverage = {
        (assignment_id, reference_class)
        for assignment_id in remote_by_id
        for reference_class in _REPLACEMENT_ASSIGNMENT_REFERENCE_CLASSES
    }
    actual_coverage = {
        (str(row["assignment_id"]), str(row["reference_class"]))
        for row in coverage_rows
    }
    if actual_coverage != expected_coverage:
        raise QueueConflictError("old session agent-owner coverage is incomplete")
    assignment_controls = {
        str(row["assignment_id"]): row
        for row in conn.execute(
            "SELECT * FROM remote_assignment_controls WHERE session_id = ? "
            "ORDER BY assignment_id",
            (session.session_id,),
        )
    }
    if not set(assignment_controls).issubset(remote_by_id):
        raise QueueConflictError("old session assignment-control parent is missing")
    recovery_rows: list[tuple[sqlite3.Row, RecoverUnknownAssignment]] = []
    for row in conn.execute(
        "SELECT recovery_id, request_json, request_digest, state, evidence_json, "
        "result_json FROM recovery_operations ORDER BY recovery_id"
    ):
        try:
            decoded = json.loads(str(row["request_json"]))
            if not isinstance(decoded, Mapping):
                raise QueueServiceError("recovery request is invalid")
            recovery = RecoverUnknownAssignment.from_dict(decoded)
        except (json.JSONDecodeError, QueueServiceError) as exc:
            raise QueueConflictError(
                "old session recovery inventory is unavailable"
            ) from exc
        target = recovery.target
        if (
            isinstance(target, ManagedRecoveryTarget)
            and target.session_id == session.session_id
        ):
            if target.agent_id != session.agent_id:
                raise QueueConflictError(
                    "old session recovery target identity conflicts"
                )
            recovery_rows.append((row, recovery))
    recovery_by_assignment: dict[
        str, list[tuple[sqlite3.Row, RecoverUnknownAssignment]]
    ] = {}
    for row, recovery in recovery_rows:
        recovery_by_assignment.setdefault(recovery.assignment_id, []).append(
            (row, recovery)
        )
    if not set(recovery_by_assignment).issubset(remote_by_id):
        raise QueueConflictError("old session recovery parent is missing")

    assignments: list[PlainData] = []
    required_claim_ids: list[str] = []
    recovery_requests: list[Mapping[str, object]] = []
    transfer_count = 0
    authorization_count = 0
    released_count = 0
    contained_count = 0
    for assignment_id, execution in sorted(execution_by_id.items()):
        remote = remote_by_id.get(assignment_id)
        coordinator_state = _projection_string(execution, "state")
        immutable: dict[str, PlainData] = {
            name: cast(PlainData, execution[name])
            for name in (
                "assignment_id",
                "run_uri",
                "stage_work_id",
                "stage_name",
                "attempt",
                "attempt_id",
                "agent_id",
                "session_id",
                "offer_id",
                "claim_id",
                "receipt_digest",
                "atom_count",
                "atoms_digest",
                "event_count",
                "events_digest",
            )
        }
        if remote is None:
            if coordinator_state != "released":
                raise QueueConflictError(
                    "old session assignment target inventory is incomplete"
                )
            assignments.append(
                {
                    **immutable,
                    "coordinator_state": coordinator_state,
                    "remote_state": None,
                    "classification": "released",
                    "release_kind": "before_delivery",
                    "delivery_state": None,
                    "reference_resolved": True,
                    "transfer_count": 0,
                    "authorization_count": 0,
                    "assignment_control_state": None,
                    "assignment_control_code": None,
                    "recovery_id": None,
                    "recovery_request_digest": None,
                    "recovery_revision": None,
                }
            )
            released_count += 1
            continue
        if (
            str(remote["run_uri"]) != immutable["run_uri"]
            or str(remote["stage_work_id"]) != immutable["stage_work_id"]
            or str(remote["stage_name"]) != immutable["stage_name"]
            or int(remote["attempt"]) != immutable["attempt"]
            or str(remote["attempt_id"]) != immutable["attempt_id"]
        ):
            raise QueueConflictError("old session assignment identity conflicts")
        delivery = deliveries[assignment_id]
        reference = references[assignment_id]
        if (
            str(delivery["session_id"]) != session.session_id
            or str(delivery["availability_revision"])
            != str(remote["availability_revision"])
            or str(delivery["coordinator_epoch"]) != str(remote["issuer_epoch"])
        ):
            raise QueueConflictError("old session delivery identity conflicts")
        transfers = tuple(
            conn.execute(
                "SELECT direction, transfer_id, size_bytes, received_bytes, "
                "finalized, descriptor_json FROM remote_transfers "
                "WHERE assignment_id = ? ORDER BY direction, transfer_id",
                (assignment_id,),
            )
        )
        if any(
            int(row["size_bytes"]) < 0
            or int(row["received_bytes"]) < 0
            or int(row["received_bytes"]) > int(row["size_bytes"])
            or (bool(row["finalized"]) and row["descriptor_json"] is None)
            for row in transfers
        ):
            raise QueueConflictError("old session transfer inventory conflicts")
        authorizations = tuple(
            conn.execute(
                "SELECT authorization_id, revision, operation_id, expires_at "
                "FROM remote_transfer_authorizations WHERE assignment_id = ? "
                "ORDER BY revision",
                (assignment_id,),
            )
        )
        transfer_count += len(transfers)
        authorization_count += len(authorizations)
        control_row = assignment_controls.get(assignment_id)
        control = (
            None
            if control_row is None
            else AgentAssignmentControl.from_value(
                json.loads(str(control_row["request_json"]))
            )
        )
        if control is not None and (
            control.session_id != session.session_id
            or control.assignment_id != assignment_id
        ):
            raise QueueConflictError(
                "old session assignment-control identity conflicts"
            )
        fully_released = (
            coordinator_state == "released"
            and str(remote["state"]) == "RELEASED"
            and bool(reference["resolved"])
            and all(bool(row["finalized"]) for row in transfers)
            and (
                control_row is None
                or (
                    bool(control_row["acknowledged"])
                    and str(control_row["state"])
                    not in {"pending_delivery", "applying", "settling"}
                )
            )
        )
        recovery_id: str | None = None
        recovery_digest: str | None = None
        recovery_revision: int | None = None
        if fully_released:
            classification = "released"
            released_count += 1
        else:
            matches = recovery_by_assignment.get(assignment_id, [])
            qualifying = [
                _qualifying_replacement_recovery(
                    row,
                    recovery,
                    session=session,
                    execution=execution,
                    remote=remote,
                    control_row=control_row,
                    control=control,
                )
                for row, recovery in matches
                if str(row["state"]) == "closed"
            ]
            qualifying = [item for item in qualifying if item is not None]
            if len(qualifying) != 1 or any(
                str(row["state"]) in {"pending", "evidence_confirmed"}
                for row, _recovery in matches
            ):
                raise QueueConflictError(
                    "old session assignment is neither released nor contained"
                )
            recovery, result = qualifying[0]
            classification = "contained"
            recovery_id = recovery.recovery_id
            recovery_digest = _digest(recovery.to_dict())
            recovery_revision = cast(int, result["revision"])
            required_claim_ids.append(_projection_string(execution, "claim_id"))
            recovery_requests.append(recovery.to_dict())
            contained_count += 1
        assignments.append(
            {
                **immutable,
                "coordinator_state": coordinator_state,
                "remote_state": str(remote["state"]),
                "classification": classification,
                "release_kind": "delivered" if fully_released else None,
                "delivery_state": str(delivery["state"]),
                "reference_resolved": bool(reference["resolved"]),
                "transfer_count": len(transfers),
                "authorization_count": len(authorizations),
                "assignment_control_state": (
                    None if control_row is None else str(control_row["state"])
                ),
                "assignment_control_code": (
                    None
                    if control_row is None or control_row["result_code"] is None
                    else str(control_row["result_code"])
                ),
                "recovery_id": recovery_id,
                "recovery_request_digest": recovery_digest,
                "recovery_revision": recovery_revision,
            }
        )
    if len(set(required_claim_ids)) != len(required_claim_ids):
        raise QueueConflictError("old session retained claim identity conflicts")
    current_offer = conn.execute(
        "SELECT expires_at FROM agent_offers WHERE session_id = ? AND current = 1",
        (session.session_id,),
    ).fetchone()
    available = (
        current_offer is not None and str(current_offer["expires_at"]) >= observed_at
    )
    if not assignments and available:
        raise QueueConflictError(
            "empty active session must use ordinary clean retirement"
        )
    controls = tuple(
        conn.execute(
            "SELECT operation_id, state, result_code, acknowledged "
            "FROM agent_controls WHERE session_id = ? ORDER BY operation_id",
            (session.session_id,),
        )
    )
    control_values: list[PlainData] = [
        {
            "operation_id": str(row["operation_id"]),
            "state": str(row["state"]),
            "code": (None if row["result_code"] is None else str(row["result_code"])),
            "acknowledged": bool(row["acknowledged"]),
        }
        for row in controls
    ]
    value: dict[str, PlainData] = {
        "projection_version": 1,
        "session": {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "agent_root_id": session.agent_root_id,
            "policy_revision": session.policy_revision,
            "config_revision": session.config_revision,
            "inventory_revision": session.inventory_revision,
            "coordinator_epoch": session.coordinator_epoch,
        },
        "assignments": assignments,
        "owner_counts": {
            "assignments": len(assignments),
            "released": released_count,
            "contained": contained_count,
            "deliveries": len(deliveries),
            "references": len(reference_rows),
            "coverage_tokens": len(coverage_rows),
            "transfers": transfer_count,
            "transfer_authorizations": authorization_count,
            "controls": len(controls),
            "assignment_controls": len(assignment_controls),
            "offers": int(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_offers WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()[0]
            ),
            "polls": int(
                conn.execute(
                    "SELECT COUNT(*) FROM agent_poll_state WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()[0]
            ),
        },
        "controls": control_values,
    }
    return _ReplacementProjection(
        value=freeze_plain_data(value, path="session replacement projection"),
        required_claim_ids=tuple(sorted(required_claim_ids)),
        recovery_requests=tuple(recovery_requests),
    )


def _qualifying_replacement_recovery(
    row: sqlite3.Row,
    recovery: "RecoverUnknownAssignment",
    *,
    session: AgentSession,
    execution: Mapping[str, PlainData],
    remote: sqlite3.Row,
    control_row: sqlite3.Row | None,
    control: AgentAssignmentControl | None,
) -> tuple["RecoverUnknownAssignment", Mapping[str, object]] | None:
    from .local_daemon import RecoverUnknownAssignment

    if not isinstance(recovery, RecoverUnknownAssignment):
        return None
    target = recovery.target
    if (
        recovery.assignment_id != remote["assignment_id"]
        or recovery.run_uri != remote["run_uri"]
        or recovery.stage_work_id != remote["stage_work_id"]
        or recovery.stage_name != remote["stage_name"]
        or recovery.attempt != remote["attempt"]
        or target.agent_id != session.agent_id  # type: ignore[union-attr]
        or target.session_id != session.session_id  # type: ignore[union-attr]
        or recovery.execution_fence != remote["fence"]
        or control_row is None
        or control is None
        or control.fence != recovery.execution_fence
        or control.process_execution_id != recovery.process_execution_id
        or not bool(control_row["acknowledged"])
        or str(control_row["result_code"]) != "contained"
    ):
        return None
    try:
        evidence = json.loads(str(row["evidence_json"]))
        result = json.loads(str(row["result_json"]))
        control_evidence = json.loads(str(control_row["evidence_json"]))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(evidence, Mapping) or not isinstance(result, Mapping):
        return None
    try:
        managed = _managed_containment_evidence(evidence)
    except QueueServiceError:
        return None
    if (
        managed.get("agent_id") != session.agent_id
        or managed.get("session_id") != session.session_id
        or managed.get("assignment_id") != remote["assignment_id"]
        or managed.get("process_execution_id") != recovery.process_execution_id
        or managed.get("execution_fence") != recovery.execution_fence
        or control_evidence != evidence
        or result.get("recovery_id") != recovery.recovery_id
        or result.get("state") != "closed"
        or result.get("evidence") != evidence
        or result.get("physical_ownership") != "retained"
        or isinstance(result.get("revision"), bool)
        or not isinstance(result.get("revision"), int)
        or _projection_string(execution, "claim_id") == ""
    ):
        return None
    return recovery, result


def _replacement_cleanup_recovery(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    assignment_id: str,
    fence: str,
) -> tuple["RecoverUnknownAssignment", str]:
    """Return the one durable recovery that permits exact late release."""

    from .local_daemon import ManagedRecoveryTarget, RecoverUnknownAssignment

    replacement = conn.execute(
        "SELECT decision_projection_json FROM session_replacements "
        "WHERE old_session_id = ?",
        (session_id,),
    ).fetchone()
    if replacement is None:
        raise QueueConflictError("replacement cleanup decision is unavailable")
    try:
        projection = json.loads(str(replacement["decision_projection_json"]))
    except json.JSONDecodeError as exc:
        raise QueueStorageError("session replacement decision is invalid") from exc
    if not isinstance(projection, Mapping) or not isinstance(
        projection.get("assignments"), list
    ):
        raise QueueStorageError("session replacement decision is invalid")
    matches = [
        item
        for item in projection["assignments"]
        if isinstance(item, Mapping) and item.get("assignment_id") == assignment_id
    ]
    if (
        len(matches) != 1
        or matches[0].get("classification") != "contained"
        or not isinstance(matches[0].get("recovery_id"), str)
        or not isinstance(matches[0].get("claim_id"), str)
    ):
        raise QueueConflictError("replacement cleanup is not containment-covered")
    recovery_id = cast(str, matches[0]["recovery_id"])
    row = conn.execute(
        "SELECT request_json, state, evidence_json, result_json "
        "FROM recovery_operations WHERE recovery_id = ?",
        (recovery_id,),
    ).fetchone()
    if row is None or str(row["state"]) != "closed" or row["evidence_json"] is None:
        raise QueueConflictError("replacement cleanup recovery is unavailable")
    try:
        value = json.loads(str(row["request_json"]))
        if not isinstance(value, Mapping):
            raise QueueServiceError("recovery request is invalid")
        recovery = RecoverUnknownAssignment.from_dict(value)
    except (json.JSONDecodeError, QueueServiceError) as exc:
        raise QueueStorageError("replacement cleanup recovery is invalid") from exc
    target = recovery.target
    if (
        not isinstance(target, ManagedRecoveryTarget)
        or target.session_id != session_id
        or recovery.assignment_id != assignment_id
        or recovery.execution_fence != fence
    ):
        raise QueueConflictError("replacement cleanup recovery identity conflicts")
    return recovery, cast(str, matches[0]["claim_id"])


def _replacement_authority_facts(
    execution: ReplacementExecution, projection: _ReplacementProjection
) -> Mapping[str, Mapping[str, PlainData]]:
    from .local_daemon import RecoverUnknownAssignment

    facts: dict[str, Mapping[str, PlainData]] = {}
    for raw in projection.recovery_requests:
        recovery = RecoverUnknownAssignment.from_dict(raw)
        fact = execution.validate_session_replacement_recovery(recovery)
        if recovery.recovery_id in facts:
            raise QueueConflictError("replacement recovery inventory conflicts")
        facts[recovery.recovery_id] = fact
    return facts


def _bind_replacement_authority_facts(
    projection: _ReplacementProjection,
    authority_facts: Mapping[str, Mapping[str, PlainData]],
) -> Mapping[str, PlainData]:
    value = thaw_plain_data(projection.value, path="session replacement projection")
    if not isinstance(value, dict):
        raise QueueStorageError("session replacement projection is invalid")
    assignments = value.get("assignments")
    if not isinstance(assignments, list):
        raise QueueStorageError("session replacement projection is invalid")
    used: set[str] = set()
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise QueueStorageError("session replacement projection is invalid")
        recovery_id = assignment.get("recovery_id")
        if recovery_id is None:
            continue
        if not isinstance(recovery_id, str):
            raise QueueStorageError("session replacement projection is invalid")
        fact = authority_facts.get(recovery_id)
        if (
            fact is None
            or fact.get("assignment_id") != assignment.get("assignment_id")
            or fact.get("authority_revision") != assignment.get("recovery_revision")
        ):
            raise QueueConflictError("replacement authority close conflicts")
        assignment["authority_revision"] = fact["authority_revision"]
        assignment["authority_status"] = fact["status"]
        used.add(recovery_id)
    if used != set(authority_facts):
        raise QueueConflictError("replacement authority inventory changed")
    return freeze_plain_data(value, path="session replacement projection")


def _require_monotonic_replacement_projection(
    previous: Mapping[str, PlainData], current: Mapping[str, PlainData]
) -> None:
    previous_session = previous.get("session")
    current_session = current.get("session")
    if previous_session != current_session:
        raise QueueConflictError("old session identity changed during replacement")
    prior_rows = previous.get("assignments")
    current_rows = current.get("assignments")
    if not isinstance(prior_rows, Sequence) or not isinstance(current_rows, Sequence):
        raise QueueStorageError("session replacement projection is invalid")
    prior = {
        _projection_string(cast(Mapping[str, PlainData], row), "assignment_id"): cast(
            Mapping[str, PlainData], row
        )
        for row in prior_rows
        if isinstance(row, Mapping)
    }
    now = {
        _projection_string(cast(Mapping[str, PlainData], row), "assignment_id"): cast(
            Mapping[str, PlainData], row
        )
        for row in current_rows
        if isinstance(row, Mapping)
    }
    if (
        len(prior) != len(prior_rows)
        or len(now) != len(current_rows)
        or set(prior) != set(now)
    ):
        raise QueueConflictError("old session assignment inventory changed")
    immutable = {
        "assignment_id",
        "run_uri",
        "stage_work_id",
        "stage_name",
        "attempt",
        "attempt_id",
        "agent_id",
        "session_id",
        "offer_id",
        "claim_id",
        "receipt_digest",
        "atom_count",
        "atoms_digest",
        "event_count",
        "events_digest",
    }
    for assignment_id, before in prior.items():
        after = now[assignment_id]
        if any(before.get(name) != after.get(name) for name in immutable):
            raise QueueConflictError("old session assignment identity changed")
        before_class = before.get("classification")
        after_class = after.get("classification")
        if before_class == "released":
            if after_class != "released":
                raise QueueConflictError("old session release state regressed")
        elif before_class == "contained":
            if after_class not in {"contained", "released"}:
                raise QueueConflictError("old session containment state regressed")
            if after_class == "contained" and any(
                before.get(name) != after.get(name)
                for name in ("recovery_id", "recovery_request_digest")
            ):
                raise QueueConflictError("old session containment identity changed")
        else:
            raise QueueStorageError("session replacement classification is invalid")


def _replacement_result(
    *,
    request: SessionReplacementRequest,
    old_session_id: str,
    successor_session_id: str | None,
    state: str,
    readiness: str,
    withholding_reason: str | None,
    projection: Mapping[str, PlainData],
) -> dict[str, PlainData]:
    counts = projection.get("owner_counts")
    if not isinstance(counts, Mapping):
        raise QueueStorageError("session replacement projection is invalid")
    frozen_counts = freeze_plain_data(counts, path="session replacement owner counts")
    if not isinstance(frozen_counts, Mapping):
        raise QueueStorageError("session replacement projection is invalid")
    return {
        "operation_id": request.operation_id,
        "agent_id": request.agent_id,
        "old_session_id": old_session_id,
        "successor_session_id": successor_session_id,
        "state": state,
        "readiness": readiness,
        "withholding_reason": withholding_reason,
        "owner_counts": dict(frozen_counts),
    }


def _replacement_cleanup_result(value: object) -> dict[str, PlainData]:
    """Advance only the current bounded counts after one exact late cleanup."""

    try:
        result = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise QueueStorageError("session replacement result is invalid") from exc
    if not isinstance(result, dict) or not isinstance(result.get("owner_counts"), dict):
        raise QueueStorageError("session replacement result is invalid")
    counts = cast(dict[str, object], result["owner_counts"])
    contained = counts.get("contained")
    released = counts.get("released")
    if (
        isinstance(contained, bool)
        or not isinstance(contained, int)
        or contained < 1
        or isinstance(released, bool)
        or not isinstance(released, int)
        or released < 0
    ):
        raise QueueStorageError("session replacement result is invalid")
    counts["contained"] = contained - 1
    counts["released"] = released + 1
    frozen = freeze_plain_data(result, path="session replacement cleanup result")
    if not isinstance(frozen, Mapping):
        raise QueueStorageError("session replacement result is invalid")
    return dict(frozen)


def _projection_string(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise QueueConflictError("replacement inventory identity is invalid")
    return item
