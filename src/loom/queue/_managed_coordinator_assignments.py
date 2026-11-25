"""Coordinator-owned resident capacity reservations and assignment transitions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import cast

from loom._sqlite_policy import SQLitePolicy
from loom.pipeline.orchestration import SchedulingProjectionState, StageWorkRecord
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, freeze_plain_data

from ._managed_contracts import (
    ManagedAssignment,
    ManagedLocalError,
    ManagedOfferSnapshot,
    _assignment_dict,
    _assignment_from_dict,
    _capacity_atom_from_dict,
    _connect_sqlite,
    _coordinator_at_or_after,
    _json,
    _read_decline_reason,
    _require_sqlite_columns,
)


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
        sqlite_policy: SQLitePolicy | None = None,
    ) -> None:
        self.path = Path(path)
        self._allow_initialize = _allow_initialize and sqlite_policy is None
        self._sqlite_policy = sqlite_policy
        self._capacity = {atom.key: atom for atom in capacity}
        if len(self._capacity) != len(tuple(capacity)):
            raise ManagedLocalError("coordinator capacity atoms must be unique")

    def _initialize(self) -> None:
        """Create the current coordinator-assignment schema explicitly."""

        previous = self._allow_initialize
        self._allow_initialize = True
        try:
            with self._transaction():
                pass
        finally:
            self._allow_initialize = previous

    def _open_existing(self) -> None:
        """Verify the current assignment schema without creating or repairing it."""

        if not self.path.is_file():
            raise ManagedLocalError("coordinator assignment store is missing")
        with _connect_sqlite(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
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
                "SELECT offer_revision, snapshot_json, consumed, is_current "
                "FROM coordinator_offers "
                "WHERE agent_id = ? AND session_id = ? "
                "AND availability_revision = ?",
                (
                    snapshot.agent_id,
                    snapshot.session_id,
                    snapshot.availability_revision,
                ),
            ).fetchone()
            if reused_availability is not None:
                try:
                    retained = cast(
                        dict[str, object],
                        json.loads(str(reused_availability["snapshot_json"])),
                    )
                    proposed = snapshot.to_dict()
                    retained.pop("offer_revision")
                    proposed.pop("offer_revision")
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ManagedLocalError(
                        "managed offer snapshot is invalid"
                    ) from exc
                if (
                    bool(reused_availability["is_current"])
                    and not bool(reused_availability["consumed"])
                    and _json(cast(Mapping[str, PlainData], retained))
                    == _json(proposed)
                ):
                    # A no-claim assignment does not change capacity evidence.
                    # Keep the original offer bytes and let its canonical identity
                    # flow into the assignment rather than fabricating a revision.
                    return cast(str, reused_availability["offer_revision"])
                raise ManagedLocalError(
                    "managed offer requires a fresh availability revision or current unconsumed matching availability"
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
        max_parallel_stages: int | None,
        decision_receipt: Mapping[str, PlainData],
        _reservation_transaction: Callable[[], AbstractContextManager[sqlite3.Connection]] | None = None,
    ) -> str:
        if max_parallel_stages is not None and (
            type(max_parallel_stages) is not int or max_parallel_stages < 1
        ):
            raise ManagedLocalError("max_parallel_stages must be positive")
        claims = tuple(claims)
        receipt = _validate_decision_receipt(
            decision_receipt, assignment=assignment, claims=claims
        )
        receipt_value = cast(Mapping[str, object], json.loads(receipt))
        atoms = tuple(atom for claim in claims for atom in claim.atoms)
        if any(atom.key not in self._capacity for atom in atoms):
            raise ManagedLocalError("claim uses atom outside configured capacity")
        requested: dict[tuple[str, str], Fraction] = {}
        for atom in atoms:
            requested[atom.key] = (
                requested.get(atom.key, Fraction(0)) + atom.amount.fraction
            )
        identity = _json(_assignment_dict(assignment))
        with (_reservation_transaction or self._transaction)() as conn:
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
                    "WHERE stage_work_id = ? AND state != 'released'",
                    (assignment.stage_work_id,),
                ).fetchone()
                if has_slurm_assignments
                else None
            )
            if work is not None or slurm_work is not None:
                raise ManagedLocalError("stage work already has a live assignment")
            active = _run_active_assignment_count(
                conn,
                assignment.run_uri,
                has_slurm_assignments=has_slurm_assignments,
            )
            if max_parallel_stages is not None and active >= max_parallel_stages:
                raise ManagedLocalError("run active-assignment limit reached")
            offer_row = conn.execute(
                "SELECT snapshot_json, snapshot_revision, consumed, is_current "
                "FROM coordinator_offers WHERE agent_id = ? AND session_id = ? "
                "AND offer_revision = ?",
                (assignment.agent_id, assignment.session_id, assignment.offer_id),
            ).fetchone()
            if offer_row is None or not bool(offer_row["is_current"]):
                raise ManagedLocalError("assignment offer is missing or stale")
            if claims and bool(offer_row["consumed"]):
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
                    "WHERE x.agent_id = ? "
                    "AND x.state IN ('reserved','bound','accepted','granted',"
                    "'running','unknown','terminal','logical_released')",
                    (assignment.agent_id,),
                )
            )
            reflectable_claim_ids = {
                cast(str, row["claim_id"])
                for row in capacity_rows
                if row["state"]
                in {
                    "accepted",
                    "granted",
                    "running",
                    "unknown",
                    "terminal",
                    "logical_released",
                }
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
                "UPDATE stage_work SET scheduling_state = ?, record_json = ? WHERE stage_work_id = ?",
                (decided.scheduling_state.value, _json(decided.to_dict()), assignment.stage_work_id),
            )
            if claims:
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
                "UPDATE stage_work SET scheduling_state = ?, record_json = ? WHERE stage_work_id = ?",
                (reopened.scheduling_state.value, _json(reopened.to_dict()), reopened.stage_work_id),
            )
            if reopen_offer:
                conn.execute(
                    "UPDATE coordinator_offers SET consumed = 0 WHERE "
                    "agent_id = ? AND session_id = ? AND offer_revision = ? "
                    "AND is_current = 1",
                    (row["agent_id"], row["session_id"], row["offer_id"]),
                )
            return "released"

    def release_contained(self, assignment_id: str) -> str:
        """Release one claim after an accepted guarded-containment close."""

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ManagedLocalError("assignment is not reserved")
            state = cast(str, row["state"])
            if state == "released":
                return state
            if state not in self._CAPACITY_HOLDING:
                raise ManagedLocalError("contained assignment is not releasable")
            conn.execute(
                "UPDATE coordinator_assignments SET state = 'released' "
                "WHERE assignment_id = ?",
                (assignment_id,),
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

        with self._transaction(read_only=True) as conn:
            return tuple(
                (str(row["assignment_id"]), str(row["state"]))
                for row in conn.execute(
                    "SELECT assignment_id, state FROM coordinator_assignments "
                    "WHERE run_uri = ? AND state != 'released' ORDER BY assignment_id",
                    (run_uri,),
                )
            )

    def run_active_assignment_count(self, run_uri: str) -> int:
        """Return the exact assignment set counted by the reservation CAS."""

        if not isinstance(run_uri, str) or not run_uri:
            raise ManagedLocalError("run URI is required")
        with self._transaction(read_only=True) as conn:
            has_slurm_assignments = (
                conn.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                    "AND name = 'slurm_stage_assignments'"
                ).fetchone()
                is not None
            )
            return _run_active_assignment_count(
                conn,
                run_uri,
                has_slurm_assignments=has_slurm_assignments,
            )

    def child_assignments_released(self, run_uris: Sequence[str]) -> bool:
        """Read physical release across native and SLURM owners in a single snapshot."""
        with self._transaction(read_only=True) as conn:
            row = conn.execute(
                "WITH children AS (SELECT value FROM json_each(?)) "
                "SELECT NOT EXISTS (SELECT 1 FROM coordinator_assignments "
                "WHERE run_uri IN children AND state != 'released') "
                "AND NOT EXISTS (SELECT 1 FROM slurm_stage_assignments "
                "WHERE run_uri IN children AND state != 'released')", (json.dumps(run_uris),),
            ).fetchone()
        return bool(row[0])

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

    def read_decline_reason(self, assignment_id: str) -> str | None:
        """Read a durable physical refusal independently of current availability."""

        with self._transaction() as conn:
            return _read_decline_reason(conn, "coordinator_events", assignment_id)

    def retained_assignments(
        self, *, agent_id: str
    ) -> tuple[tuple[ManagedAssignment, Mapping[str, PlainData]], ...]:
        """Return exact nonreleased assignments for one local agent owner."""

        if not isinstance(agent_id, str) or not agent_id:
            raise ManagedLocalError("retained assignment agent ID is required")
        with self._transaction() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT identity_json, receipt_json FROM coordinator_assignments "
                    "WHERE agent_id = ? AND state != 'released' "
                    "ORDER BY assignment_id",
                    (agent_id,),
                )
            )
        retained: list[tuple[ManagedAssignment, Mapping[str, PlainData]]] = []
        for row in rows:
            try:
                assignment = _assignment_from_dict(
                    json.loads(cast(str, row["identity_json"]))
                )
                raw_receipt = freeze_plain_data(
                    json.loads(cast(str, row["receipt_json"])),
                    path="retained decision receipt",
                )
            except ManagedLocalError:
                raise
            except Exception as exc:
                raise ManagedLocalError(
                    "retained coordinator assignment is invalid"
                ) from exc
            if not isinstance(raw_receipt, Mapping):
                raise ManagedLocalError("retained decision receipt is invalid")
            retained.append((assignment, raw_receipt))
        return tuple(retained)

    def local_recovery_assignments(
        self, run_uri: str, *, agent_id: str, stage_name: str | None,
        limit: int | None,
    ) -> tuple[ManagedAssignment, ...]:
        with self._transaction() as conn:
            return tuple(
                _assignment_from_dict(json.loads(row[0]))
                for row in conn.execute(
                    "SELECT identity_json FROM coordinator_assignments WHERE run_uri=? AND agent_id=? "
                    "AND (? IS NULL OR json_extract(identity_json, '$.stage_name')=?) "
                    "ORDER BY assignment_id LIMIT ?",
                    (run_uri, agent_id, stage_name, stage_name, -1 if limit is None else limit + 1),
                )
            )

    def session_assignment_facts(
        self, *, session_id: str
    ) -> tuple[Mapping[str, PlainData], ...]:
        """Return a bounded, identity-checked inventory for one session.

        Replacement cannot infer that a missing agent journal is empty. This
        coordinator-owned view therefore includes released rows as well as
        capacity-holding rows and binds each assignment to its atom, event,
        decision, and offer identities without copying their payloads.
        """

        if not isinstance(session_id, str) or not session_id:
            raise ManagedLocalError("session assignment inventory requires an ID")
        with self._transaction(read_only=True) as conn:
            rows = tuple(
                conn.execute(
                    "SELECT assignment_id, identity_json, run_uri, stage_work_id, "
                    "state, receipt_json, agent_id, session_id, offer_id, claim_id "
                    "FROM coordinator_assignments WHERE session_id = ? "
                    "ORDER BY assignment_id",
                    (session_id,),
                )
            )
            facts: list[Mapping[str, PlainData]] = []
            for row in rows:
                assignment = _assignment_from_dict(
                    json.loads(cast(str, row["identity_json"]))
                )
                if (
                    assignment.assignment_id != row["assignment_id"]
                    or assignment.run_uri != row["run_uri"]
                    or assignment.stage_work_id != row["stage_work_id"]
                    or assignment.agent_id != row["agent_id"]
                    or assignment.session_id != row["session_id"]
                    or assignment.offer_id != row["offer_id"]
                    or assignment.claim_id != row["claim_id"]
                ):
                    raise ManagedLocalError(
                        "coordinator assignment inventory identity conflicts"
                    )
                state = cast(str, row["state"])
                if state not in self._CAPACITY_HOLDING | {"released"}:
                    raise ManagedLocalError(
                        "coordinator assignment inventory state is invalid"
                    )
                offer = conn.execute(
                    "SELECT 1 FROM coordinator_offers WHERE agent_id = ? "
                    "AND session_id = ? AND offer_revision = ?",
                    (
                        assignment.agent_id,
                        assignment.session_id,
                        assignment.offer_id,
                    ),
                ).fetchone()
                if offer is None:
                    raise ManagedLocalError(
                        "coordinator assignment inventory offer is missing"
                    )
                atoms = [
                    [
                        cast(str, atom["resource_kind"]),
                        cast(str, atom["capacity_key"]),
                        cast(int, atom["numerator"]),
                        cast(int, atom["denominator"]),
                    ]
                    for atom in conn.execute(
                        "SELECT resource_kind, capacity_key, numerator, denominator "
                        "FROM coordinator_atoms WHERE assignment_id = ? "
                        "ORDER BY resource_kind, capacity_key",
                        (assignment.assignment_id,),
                    )
                ]
                events = [
                    [
                        cast(int, event["sequence"]),
                        cast(str, event["event_id"]),
                        hashlib.sha256(
                            cast(str, event["payload_json"]).encode("utf-8")
                        ).hexdigest(),
                    ]
                    for event in conn.execute(
                        "SELECT sequence, event_id, payload_json "
                        "FROM coordinator_events WHERE assignment_id = ? "
                        "ORDER BY sequence",
                        (assignment.assignment_id,),
                    )
                ]
                facts.append(
                    {
                        **_assignment_dict(assignment),
                        "state": state,
                        "receipt_digest": hashlib.sha256(
                            cast(str, row["receipt_json"]).encode("utf-8")
                        ).hexdigest(),
                        "atom_count": len(atoms),
                        "atoms_digest": hashlib.sha256(
                            json.dumps(atoms, separators=(",", ":")).encode("utf-8")
                        ).hexdigest(),
                        "event_count": len(events),
                        "events_digest": hashlib.sha256(
                            json.dumps(events, separators=(",", ":")).encode("utf-8")
                        ).hexdigest(),
                    }
                )
        return tuple(facts)

    def withhold_claims(
        self,
        *,
        agent_id: str,
        atoms: Sequence[CapacityAtom],
        claim_ids: Sequence[str],
    ) -> tuple[CapacityAtom, ...]:
        """Subtract exact retained claims from a successor observation."""

        required = tuple(sorted(claim_ids))
        if (
            not isinstance(agent_id, str)
            or not agent_id
            or any(not isinstance(value, str) or not value for value in required)
            or len(set(required)) != len(required)
        ):
            raise ManagedLocalError("withheld claim identity is invalid")
        offered = {atom.key: atom for atom in atoms}
        if len(offered) != len(tuple(atoms)):
            raise ManagedLocalError("withheld offer atoms must be unique")
        if not required:
            return tuple(sorted(atoms, key=lambda item: item.key))
        placeholders = ",".join("?" for _ in required)
        with self._transaction() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT a.resource_kind, a.capacity_key, a.numerator, "
                    "a.denominator, x.claim_id FROM coordinator_atoms a "
                    "JOIN coordinator_assignments x "
                    "ON x.assignment_id = a.assignment_id "
                    f"WHERE x.agent_id = ? AND x.claim_id IN ({placeholders}) "
                    "AND x.state IN ('accepted','granted','running','unknown',"
                    "'terminal','logical_released')",
                    (agent_id, *required),
                )
            )
        if {cast(str, row["claim_id"]) for row in rows} != set(required):
            raise ManagedLocalError(
                "replacement references a claim that is not retained and live"
            )
        held: dict[tuple[str, str], Fraction] = {}
        for row in rows:
            key = (cast(str, row["resource_kind"]), cast(str, row["capacity_key"]))
            held[key] = held.get(key, Fraction(0)) + Fraction(
                cast(int, row["numerator"]), cast(int, row["denominator"])
            )
        result: list[CapacityAtom] = []
        for key, atom in offered.items():
            remaining = atom.amount.fraction - held.get(key, Fraction(0))
            if remaining <= 0:
                continue
            result.append(
                CapacityAtom(
                    atom.owner_resource_kind,
                    atom.local_capacity_key,
                    ExactQuantity(remaining.numerator, remaining.denominator),
                    atom.unit,
                    atom.granularity,
                )
            )
        return tuple(sorted(result, key=lambda item: item.key))

    def confirm_supervised_running(self, assignment_id: str) -> str:
        """Record positive supervisor start proof, including unknown recovery."""

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM coordinator_assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            if row is None:
                raise ManagedLocalError("assignment is not reserved")
            state = cast(str, row["state"])
            if state == "running" or _coordinator_at_or_after(state, "terminal"):
                return state
            if state not in {"granted", "unknown"}:
                raise ManagedLocalError(
                    "supervisor start proof conflicts with coordinator state"
                )
            conn.execute(
                "UPDATE coordinator_assignments SET state = 'running' "
                "WHERE assignment_id = ?",
                (assignment_id,),
            )
            return "running"

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
    def _transaction(self, *, read_only: bool = False):
        if not self.path.is_file():
            if not self._allow_initialize:
                raise ManagedLocalError("coordinator assignment store is missing")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with _connect_sqlite(
            self.path, sqlite_policy=self._sqlite_policy, require_existing=not self._allow_initialize
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN" if read_only and not self._allow_initialize else "BEGIN IMMEDIATE")
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


def _run_active_assignment_count(
    conn: sqlite3.Connection,
    run_uri: str,
    *,
    has_slurm_assignments: bool,
) -> int:
    active = int(
        conn.execute(
            "SELECT COUNT(*) FROM coordinator_assignments WHERE run_uri = ? "
            "AND state IN ('reserved','bound','accepted','granted','running','unknown')",
            (run_uri,),
        ).fetchone()[0]
    )
    if has_slurm_assignments:
        active += int(
            conn.execute(
                "SELECT COUNT(*) FROM slurm_stage_assignments WHERE run_uri = ? "
                "AND state != 'released'",
                (run_uri,),
            ).fetchone()[0]
        )
    return active


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
    if len({item.kind for item in parsed_components}) != len(parsed_components):
        raise ManagedLocalError("decision component descriptors must be unique")
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
    if len({item.kind for item in parsed_providers}) != len(parsed_providers):
        raise ManagedLocalError("decision provider descriptors must be unique")
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
