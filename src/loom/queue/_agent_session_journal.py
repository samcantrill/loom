"""Outbound session evidence with one owner for durable transactions."""
from __future__ import annotations
from .gpu.occupancy import GpuOccupancyPolicy

from collections.abc import Mapping

from dataclasses import replace

import fcntl

import hashlib

import json

import os

from pathlib import Path

import secrets

import sqlite3

import stat

from typing import cast

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from loom.queue._managed_local import (
    ProviderReleaseEvidence,
    SQLiteAgentJournal,
)

from .agent_sessions import (
    AgentAssignmentControl,
    AgentOffer,
    AgentOfferRenewal,
    AgentProviderReleaseProof,
    AgentControl,
    AgentControlEffect,
    AgentPollActiveError,
    AgentPollSequenceGapError,
    AgentRegistration,
    AgentRetirementProof,
    AgentSession,
    AgentSessionState,
    AgentStalePollError,
    _SESSION_REFERENCE_KINDS,
    _session_from_value,
    validate_agent_session_schema,
)

from ._remote_stage_execution import (
    ResidentExecutionProfile,
    _ResidentAssignmentBundle,
)

from .errors import QueueConflictError, QueueError, QueueServiceError

from .local_daemon import (
    _LOCAL_DAEMON_SCHEMA_VERSION,
)

from typing import TYPE_CHECKING
from ._agent_session_codec import _registration
if TYPE_CHECKING:
    from .agent_session_transport import AgentTlsClientConfig

_AGENT_BINDING_FILE = "role-binding.json"


class _RemoteAgentJournal:
    """The outbound agent's private, replayable session evidence.

    This belongs to the outbound application, never the coordinator daemon's
    configured local-agent root. Session and assignment references share the
    existing connection and transaction boundaries.
    """

    def __init__(
        self,
        root: Path,
        *,
        expected_configuration_fingerprint: str | None = None,
        expected_active_configuration_fingerprint: str | None = None,
    ) -> None:
        self._root = Path(root)
        if not self._root.is_dir():
            raise QueueServiceError("remote agent root is missing")
        details = self._root.stat()
        if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
            raise QueueServiceError("remote agent root must be owner-permissioned")
        self._path = self._root / "control.sqlite"
        if not self._path.is_file() or stat.S_IMODE(self._path.stat().st_mode) & 0o077:
            raise QueueServiceError("remote agent control state is unavailable")
        # Preserve the protected-configuration rejection point before lock
        # contention while repeating the same proof under the lock below.
        try:
            metadata = self._validated_metadata(
                expected_configuration_fingerprint,
                expected_active_configuration_fingerprint,
            )
        except QueueError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise QueueServiceError(
                "remote agent control state is unavailable"
            ) from exc
        self._lock = (self._root / "owner.lock").open("a+", encoding="utf-8")
        (self._root / "owner.lock").chmod(0o600)
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lock.close()
            raise QueueServiceError("remote agent root is already locked") from exc
        try:
            metadata = self._validated_metadata(
                expected_configuration_fingerprint,
                expected_active_configuration_fingerprint,
            )
        except QueueError:
            self._lock.close()
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            self._lock.close()
            raise QueueServiceError(
                "remote agent control state is unavailable"
            ) from exc
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_session_references)")}
            if "reference_json" not in columns:
                conn.execute("ALTER TABLE agent_session_references ADD COLUMN reference_json TEXT")
            self._backfill_delivery_requests(conn)
            conn.commit()
        self.root_id = metadata["stable_id"]

    @staticmethod
    def _backfill_delivery_requests(conn: sqlite3.Connection) -> None:
        from ._shared_assignment import reference

        # Only the surviving original inline receipt can fill a legacy row.
        # A resolved workspace is a different representation and remains owned
        # by the retained-work recovery path.
        rows = conn.execute(
            "SELECT r.session_id, r.reference_id, p.result_json "
            "FROM agent_session_references r JOIN agent_poll_state_local p "
            "ON p.session_id = r.session_id WHERE r.reference_kind = 'delivery' "
            "AND r.resolved = 0 AND r.reference_json IS NULL "
            "AND p.result_json IS NOT NULL"
        ).fetchall()
        for row in rows:
            result = json.loads(row["result_json"])
            request = result.get("request")
            if (
                result.get("result") != "assignment"
                or not isinstance(request, dict)
                or request.get("assignment_id") != row["reference_id"]
            ):
                continue
            if reference(request) is not None:
                continue
            _ResidentAssignmentBundle.from_remote_dict(request)
            conn.execute(
                "UPDATE agent_session_references SET reference_json = ? "
                "WHERE session_id = ? AND reference_kind = 'delivery' "
                "AND reference_id = ? AND resolved = 0 AND reference_json IS NULL",
                (_canonical_json(request), row["session_id"], row["reference_id"]),
            )

    def _validated_metadata(
        self,
        expected_configuration_fingerprint: str | None,
        expected_active_configuration_fingerprint: str | None,
    ) -> dict[str, str]:
        """Read and validate the immutable binding and recoverable active state."""

        with self._connection() as conn:
            if int(conn.execute("PRAGMA user_version").fetchone()[0]) != (
                _LOCAL_DAEMON_SCHEMA_VERSION
            ):
                raise QueueServiceError("remote agent root schema is unsupported")
            metadata = {
                str(row[0]): str(row[1])
                for row in conn.execute("SELECT key, value FROM root_metadata")
            }
            if metadata.get("role") != "local-agent" or not metadata.get("stable_id"):
                raise QueueServiceError("remote agent root identity is invalid")
            validate_agent_session_schema(conn, coordinator=False)
            if expected_configuration_fingerprint is None and (
                expected_active_configuration_fingerprint is None
                or "active_configuration_fingerprint" not in metadata
            ):
                return metadata
            if expected_configuration_fingerprint is not None:
                binding_path = self._root / _AGENT_BINDING_FILE
                if (
                    not binding_path.is_file()
                    or stat.S_IMODE(binding_path.stat().st_mode) & 0o077
                ):
                    raise QueueServiceError("remote agent binding is unavailable")
                binding = json.loads(binding_path.read_text(encoding="utf-8"))
                if binding != {
                    "schema_version": 2,
                    "role_kind": "outbound-agent",
                    "stable_id": metadata["stable_id"],
                    "immutable_fingerprint": expected_configuration_fingerprint,
                }:
                    raise QueueServiceError("remote agent binding is invalid")
            if metadata.get("profile_promotion_pending"):
                raise QueueConflictError("profile promotion recovery required before capacity")
            active = metadata.get("active_configuration_fingerprint")
            pending = tuple(
                conn.execute(
                    "SELECT replacement_fingerprint FROM agent_controls_local "
                    "WHERE effect_json IS NULL "
                    "AND replacement_fingerprint IS NOT NULL"
                )
            )
            if len(pending) > 1:
                raise QueueServiceError(
                    "multiple protected agent reload intents are active"
                )
            if pending and str(pending[0][0]) != (
                expected_active_configuration_fingerprint
            ):
                raise QueueServiceError(
                    "protected agent configuration conflicts with pending reload"
                )
            if active != expected_active_configuration_fingerprint and not pending:
                raise QueueServiceError(
                    "protected agent configuration changed without reload"
                )
            return metadata

    def close(self) -> None:
        self._lock.close()

    def bind_reload_intent(
        self, control: AgentControl, replacement_fingerprint: str
    ) -> None:
        """Bind one delivered reload to the exact fully prepared replacement."""

        if control.kind.value not in {"reload", "promote"} or not replacement_fingerprint:
            raise QueueConflictError("agent reload intent is invalid")
        encoded = _canonical_json(control.value())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json, replacement_fingerprint, effect_json "
                "FROM agent_controls_local WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            if row is None or str(row["request_json"]) != encoded:
                raise QueueConflictError("agent reload delivery is not durable")
            if row["effect_json"] is not None:
                raise QueueConflictError("agent reload is already complete")
            existing = row["replacement_fingerprint"]
            if existing is not None and str(existing) != replacement_fingerprint:
                raise QueueConflictError("agent reload replacement conflicts")
            conn.execute(
                "UPDATE agent_controls_local SET replacement_fingerprint = ? "
                "WHERE operation_id = ?",
                (replacement_fingerprint, control.operation_id),
            )
            conn.commit()

    def complete_reload(
        self,
        control: AgentControl,
        config: AgentTlsClientConfig,
        effect: AgentControlEffect,
    ) -> None:
        """Atomically activate the protected source and its terminal effect."""

        fingerprint = _agent_active_fingerprint(config)
        expected = AgentControlEffect(
            operation_id=control.operation_id,
            code="applied",
            config_revision=_agent_config_revision(config),
            inventory_revision=_agent_inventory_revision(config),
            availability_revision=_agent_revision(
                "availability",
                {
                    "operation_id": control.operation_id,
                    "drained": True,
                    "inventory_revision": _agent_inventory_revision(config),
                },
            ),
        )
        if effect != expected:
            raise QueueConflictError("agent reload effect conflicts with replacement")
        encoded_request = _canonical_json(control.value())
        encoded_effect = _canonical_json(effect.value())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json, replacement_fingerprint, effect_json "
                "FROM agent_controls_local WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            if (
                row is None
                or str(row["request_json"]) != encoded_request
                or str(row["replacement_fingerprint"]) != fingerprint
            ):
                raise QueueConflictError("agent reload intent is unavailable")
            if row["effect_json"] is not None:
                if str(row["effect_json"]) != encoded_effect:
                    raise QueueConflictError("agent reload effect conflicts")
                conn.commit()
                return
            session_row = conn.execute(
                "SELECT value_json FROM agent_sessions_local WHERE session_id = ?",
                (control.expected_session_id,),
            ).fetchone()
            if session_row is None:
                raise QueueConflictError("agent reload session is unavailable")
            raw_session = json.loads(str(session_row["value_json"]))
            if not isinstance(raw_session, Mapping):
                raise QueueServiceError("agent reload session is invalid")
            session = _session_from_value(raw_session)
            if session.config_revision != control.expected_config_revision:
                raise QueueConflictError("agent reload session revision is stale")
            revision = conn.execute(
                "SELECT value FROM root_metadata "
                "WHERE key = 'active_configuration_revision'"
            ).fetchone()
            availability = conn.execute(
                "SELECT value FROM root_metadata WHERE key = 'availability_state'"
            ).fetchone()
            if (
                revision is None
                or not str(revision["value"]).isdecimal()
                or availability is None
                or str(availability["value"]) != "drained"
            ):
                raise QueueServiceError("remote active configuration is unavailable")
            updated = replace(
                session,
                config_revision=effect.config_revision,
                inventory_revision=effect.inventory_revision,
                availability_revision=effect.availability_revision,
            )
            conn.execute(
                "UPDATE root_metadata SET value = ? "
                "WHERE key = 'active_configuration_revision'",
                (str(int(str(revision["value"])) + 1),),
            )
            conn.execute(
                "UPDATE root_metadata SET value = ? "
                "WHERE key = 'active_configuration_fingerprint'",
                (fingerprint,),
            )
            _record_agent_declaration_binding(
                conn, config, int(str(revision["value"])) + 1
            )
            conn.execute(
                "UPDATE agent_sessions_local SET value_json = ? WHERE session_id = ?",
                (_canonical_json(updated.value()), updated.session_id),
            )
            conn.execute(
                "UPDATE agent_controls_local SET effect_json = ? "
                "WHERE operation_id = ?",
                (encoded_effect, control.operation_id),
            )
            if control.promotion is not None:
                conn.execute("DELETE FROM root_metadata WHERE key='profile_promotion_pending'")
            conn.commit()

    def recover_pending_reload(self, config: AgentTlsClientConfig) -> None:
        """Complete the one accepted reload represented by this process source."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT request_json, replacement_fingerprint FROM "
                    "agent_controls_local WHERE effect_json IS NULL "
                    "AND replacement_fingerprint IS NOT NULL"
                )
            )
        if not rows:
            return
        if len(rows) != 1:
            raise QueueServiceError(
                "multiple protected agent reload intents are active"
            )
        row = rows[0]
        if str(row["replacement_fingerprint"]) != _agent_active_fingerprint(config):
            raise QueueConflictError(
                "protected agent configuration conflicts with pending reload"
            )
        raw_control = json.loads(str(row["request_json"]))
        if not isinstance(raw_control, Mapping):
            raise QueueServiceError("agent reload intent is invalid")
        control = AgentControl.from_value(raw_control)
        if control.kind.value not in {"reload", "promote"}:
            raise QueueServiceError("agent reload intent is invalid")
        effect = AgentControlEffect(
            operation_id=control.operation_id,
            code="applied",
            config_revision=_agent_config_revision(config),
            inventory_revision=_agent_inventory_revision(config),
            availability_revision=_agent_revision(
                "availability",
                {
                    "operation_id": control.operation_id,
                    "drained": True,
                    "inventory_revision": _agent_inventory_revision(config),
                },
            ),
        )
        self.complete_reload(control, config, effect)

    def availability_drained(self) -> bool:
        """Return the durable owner-local withdrawal state."""

        with self._connection() as conn:
            row = conn.execute(
                "SELECT value FROM root_metadata WHERE key = 'availability_state'"
            ).fetchone()
        if row is None:
            return False
        if str(row[0]) not in {"active", "drained"}:
            raise QueueServiceError("remote agent availability state is invalid")
        return str(row[0]) == "drained"

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            f"{self._path.resolve().as_uri()}?mode=rw", uri=True, timeout=30
        )
        conn.row_factory = sqlite3.Row
        return conn

    def persist_registration_intent(
        self, request: AgentRegistration
    ) -> AgentRegistration:
        if request.agent_root_id != self.root_id:
            raise QueueConflictError("registration does not match the agent root")
        if request.retirement_verifier is not None:
            raise QueueConflictError("remote registration verifier is journal-owned")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT digest, request_json FROM agent_registration_intents WHERE operation_id = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                secret = secrets.token_hex(32)
                persisted = replace(
                    request,
                    retirement_verifier=hashlib.sha256(
                        bytes.fromhex(secret)
                    ).hexdigest(),
                )
                value = persisted.value()
                digest = _canonical_digest(value)
                encoded = _canonical_json(value)
                conn.execute(
                    "INSERT INTO agent_registration_intents(operation_id, digest, request_json, retirement_secret, result_json) VALUES (?, ?, ?, ?, NULL)",
                    (request.idempotency_key, digest, encoded, secret),
                )
            else:
                stored_value = json.loads(str(row["request_json"]))
                if not isinstance(stored_value, Mapping):
                    raise QueueServiceError("agent registration intent is invalid")
                persisted = _registration(cast(Mapping[str, object], stored_value))
                if persisted.retirement_verifier is None or _canonical_digest(
                    replace(
                        request, retirement_verifier=persisted.retirement_verifier
                    ).value()
                ) != str(row["digest"]):
                    raise QueueConflictError(
                        "idempotency key was reused with different content"
                    )
            conn.commit()
        return persisted

    def persist_session(
        self, operation_id: str, request: Mapping[str, PlainData], session: AgentSession
    ) -> None:
        if (
            session.agent_root_id != self.root_id
            or session.state is not AgentSessionState.ACTIVE
        ):
            raise QueueConflictError("returned session does not match the agent root")
        digest = _canonical_digest(request)
        encoded = _canonical_json(session.value())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT digest, retirement_secret, result_json FROM agent_registration_intents WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None or str(row["digest"]) != digest:
                raise QueueConflictError("agent registration intent is not durable")
            secret = row["retirement_secret"]
            if not isinstance(secret, str) or len(secret) != 64:
                raise QueueConflictError("agent registration secret is unavailable")
            if row["result_json"] is not None and str(row["result_json"]) != encoded:
                raise QueueConflictError(
                    "registration replay returned a different session"
                )
            current = conn.execute(
                "SELECT value_json, retirement_secret, state FROM agent_sessions_local WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()
            if current is not None and (
                str(current["state"]) != AgentSessionState.ACTIVE.value
                or str(current["value_json"]) != encoded
                or str(current["retirement_secret"]) != secret
            ):
                raise QueueConflictError(
                    "registration cannot replace durable session evidence"
                )
            conn.execute(
                "UPDATE agent_registration_intents SET result_json = ? WHERE operation_id = ?",
                (encoded, operation_id),
            )
            conn.execute(
                "INSERT INTO agent_sessions_local(session_id, value_json, registration_operation_id, retirement_secret, state) VALUES (?, ?, ?, ?, ?) ON CONFLICT(session_id) DO NOTHING",
                (
                    session.session_id,
                    encoded,
                    operation_id,
                    secret,
                    session.state.value,
                ),
            )
            conn.commit()

    def session(self, session_id: str) -> AgentSession:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value_json, retirement_secret, state FROM agent_sessions_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None or str(row["state"]) != AgentSessionState.ACTIVE.value:
            raise QueueServiceError("remote agent session evidence is unavailable")
        value = json.loads(str(row["value_json"]))
        if not isinstance(value, Mapping):
            raise QueueServiceError("remote agent session evidence is invalid")
        return _session_from_value(cast(Mapping[str, PlainData], value))

    def active_session(self) -> AgentSession | None:
        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT value_json FROM agent_sessions_local WHERE state = ? "
                    "ORDER BY session_id LIMIT 2",
                    (AgentSessionState.ACTIVE.value,),
                )
            )
        if len(rows) > 1:
            raise QueueServiceError("remote agent retained several active sessions")
        if not rows:
            return None
        value = json.loads(str(rows[0]["value_json"]))
        if not isinstance(value, Mapping):
            raise QueueServiceError("remote agent session evidence is invalid")
        return _session_from_value(cast(Mapping[str, PlainData], value))

    def next_poll_sequence(self, session_id: str) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT sequence FROM agent_poll_state_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return 1 if row is None else int(row["sequence"]) + 1

    def pending_poll(self) -> tuple[str, str, int] | None:
        """Return an unresolved poll, including an active session's legacy fence."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT session_id, availability_revision, sequence "
                "FROM agent_poll_state_local p WHERE state = 'PENDING' OR "
                "(state = 'FENCED' AND result_json IS NULL AND EXISTS "
                "(SELECT 1 FROM agent_sessions_local s WHERE s.session_id = p.session_id "
                "AND s.state = 'ACTIVE')) LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return (
            str(row["session_id"]),
            str(row["availability_revision"]),
            int(row["sequence"]),
        )

    def recovery_poll(self, wait_timeout_ms: int) -> tuple[str, dict[str, PlainData]] | None:
        """Read an unresolved request, including legacy unconfirmed fences."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT p.* FROM agent_poll_state_local p "
                "JOIN agent_sessions_local s ON s.session_id = p.session_id "
                "WHERE s.state = 'ACTIVE' AND p.state IN ('PENDING', 'FENCED') "
                "AND p.result_json IS NULL LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        value: dict[str, PlainData] = {
            "session_id": str(row["session_id"]),
            "availability_revision": str(row["availability_revision"]),
            "sequence": int(row["sequence"]),
            "wait_timeout_ms": wait_timeout_ms,
        }
        if _canonical_digest(value) != row["request_digest"]:
            raise QueueConflictError("retained poll request identity conflicts")
        return str(row["state"]), value

    def discard_absent_poll(
        self, session_id: str, sequence: int, *,
        predecessor_sequence: PlainData = None,
        predecessor_delivery: PlainData = None,
    ) -> None:
        predecessor = sequence - 1 if predecessor_sequence is None else predecessor_sequence
        if isinstance(predecessor, bool) or not isinstance(predecessor, int) or not 0 <= predecessor < sequence:
            raise QueueServiceError("poll recovery predecessor is invalid")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if predecessor_delivery is not None:
                if (
                    not isinstance(predecessor_delivery, Mapping)
                    or not isinstance(predecessor_delivery.get("assignment_id"), str)
                    or not isinstance(predecessor_delivery.get("request_digest"), str)
                ):
                    raise QueueServiceError("poll recovery predecessor receipt is invalid")
                retained = conn.execute(
                    "SELECT reference_json FROM agent_session_references "
                    "WHERE session_id = ? AND reference_kind = 'delivery' AND reference_id = ?",
                    (session_id, predecessor_delivery["assignment_id"]),
                ).fetchone()
                if (
                    retained is None or retained[0] is None
                    or hashlib.sha256(str(retained[0]).encode()).hexdigest()
                    != predecessor_delivery["request_digest"]
                ):
                    raise QueueConflictError("poll recovery predecessor delivery is not retained")
            if predecessor == 0:
                conn.execute(
                    "DELETE FROM agent_poll_state_local WHERE session_id = ? "
                    "AND sequence = ? AND state IN ('PENDING', 'FENCED') "
                    "AND result_json IS NULL",
                    (session_id, sequence),
                )
            else:
                # RECONCILED is an authority-confirmed watermark, unlike the
                # old local FENCED state which did not prove consumption.
                conn.execute(
                    "UPDATE agent_poll_state_local SET sequence = ?, state = 'RECONCILED' "
                    "WHERE session_id = ? AND sequence = ? AND state IN ('PENDING', 'FENCED') "
                    "AND result_json IS NULL",
                    (predecessor, session_id, sequence),
                )
            conn.commit()

    def persist_reconciled_session(self, session: AgentSession) -> None:
        if (
            session.agent_root_id != self.root_id
            or session.state is not AgentSessionState.ACTIVE
        ):
            raise QueueConflictError("reconciled session does not match the agent root")
        with self._connection() as conn:
            updated = conn.execute(
                "UPDATE agent_sessions_local SET value_json = ?, state = ? "
                "WHERE session_id = ? AND state = ?",
                (
                    _canonical_json(session.value()),
                    session.state.value,
                    session.session_id,
                    AgentSessionState.ACTIVE.value,
                ),
            ).rowcount
            if updated != 1:
                raise QueueServiceError("remote agent session evidence is unavailable")
            conn.commit()

    def pending_mutation_inventory(self) -> tuple[tuple[str, str, str], ...]:
        with self._connection() as conn:
            return tuple(
                (row[0], row[1], row[2])
                for row in conn.execute(
                    "SELECT operation, operation_id, request_json FROM agent_mutation_intents "
                    "WHERE result_json IS NULL ORDER BY operation, operation_id"
                )
            )

    def pending_reconciliations(self) -> tuple[tuple[str, str], ...]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT operation_id, request_json FROM agent_mutation_intents "
                "WHERE operation = 'reconcile' AND result_json IS NULL ORDER BY rowid"
            ).fetchall()
        return tuple((row[0], row[1]) for row in rows)

    def discard_rejected_reconciliation(self, operation_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM agent_mutation_intents WHERE operation = 'reconcile' "
                "AND operation_id = ? AND result_json IS NULL", (operation_id,)
            )

    def discard_rejected_resource_mutation(
        self, session_id: str, operation: str, operation_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if operation == "renew":
                # A definite rejection cannot be fixed by renewing the same
                # consumed offer, even if capacity returned to identical bytes.
                self._invalidate_resource_offer(conn, session_id)
            conn.execute(
                "DELETE FROM agent_mutation_intents WHERE operation = ? "
                "AND operation_id = ? AND result_json IS NULL",
                (operation, operation_id),
            )
            conn.commit()

    def pending_resource_mutation(
        self, session_id: str
    ) -> tuple[str, str, Mapping[str, PlainData]] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT operation, operation_id, request_json FROM agent_mutation_intents "
                "WHERE operation IN ('offer', 'renew') AND result_json IS NULL "
                "AND json_extract(request_json, '$.session_id') = ? ORDER BY rowid LIMIT 1",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return (
            str(row["operation"]),
            str(row["operation_id"]),
            json.loads(str(row["request_json"])),
        )

    def current_resource_offer(self, session_id: str) -> AgentOffer | None:
        session = self.session(session_id)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT request_json FROM agent_mutation_intents WHERE operation = 'offer' "
                "AND result_json IS NOT NULL AND json_extract(request_json, '$.session_id') = ? "
                "AND json_extract(request_json, '$.availability_revision') = ? ORDER BY rowid DESC LIMIT 1",
                (session_id, session.availability_revision),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(str(row["request_json"]))
        value.pop("expected_availability_revision", None)
        return AgentOffer.from_value(value)

    def prepare_offer(
        self,
        offer: AgentOffer,
        operation_id: str,
        expected_availability_revision: str | None = None,
    ) -> None:
        session = self.session(offer.session_id)
        if (
            offer.coordinator_epoch != session.coordinator_epoch
            or offer.config_revision != session.config_revision
            or offer.inventory_revision != session.inventory_revision
            or (
                offer.availability_revision
                if expected_availability_revision is None
                else expected_availability_revision
            )
            != session.availability_revision
            or offer.pools != session.pools
        ):
            raise QueueConflictError("offer does not match the durable agent session")
        value = offer.value()
        if expected_availability_revision is not None:
            value["expected_availability_revision"] = expected_availability_revision
        self._persist_mutation("offer", operation_id, value)
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO agent_offers_local(session_id, availability_revision, state) VALUES (?, ?, 'PENDING') ON CONFLICT(session_id) DO UPDATE SET availability_revision = excluded.availability_revision, state = 'PENDING'",
                (offer.session_id, offer.availability_revision),
            )
            conn.commit()

    def prepare_offer_renewal(
        self, renewal: AgentOfferRenewal
    ) -> Mapping[str, PlainData] | None:
        """Persist one bounded renewal intent before issuing it remotely."""

        session = self.session(renewal.session_id)
        if session.availability_revision != renewal.availability_revision:
            raise QueueConflictError("offer renewal does not match the durable session")
        digest = _canonical_digest(renewal.value())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT offer_id, availability_revision, sequence, digest, result_json "
                "FROM agent_offer_renewals_local WHERE session_id = ?",
                (renewal.session_id,),
            ).fetchone()
            if (
                row is None
                or str(row["offer_id"]) != renewal.offer_id
                or str(row["availability_revision"]) != renewal.availability_revision
            ):
                raise QueueConflictError(
                    "offer renewal requires the durable current offer"
                )
            current = int(row["sequence"])
            if renewal.sequence < current:
                raise AgentStalePollError("offer renewal sequence is stale")
            if renewal.sequence == current:
                if str(row["digest"]) != digest:
                    raise QueueConflictError(
                        "offer renewal sequence was reused with different content"
                    )
                if row["result_json"] is None:
                    conn.commit()
                    return None
                value = json.loads(str(row["result_json"]))
                if not isinstance(value, Mapping):
                    raise QueueServiceError("offer renewal receipt is invalid")
                conn.commit()
                return freeze_plain_data(value, path="agent offer renewal replay")
            if renewal.sequence != current + 1:
                raise AgentPollSequenceGapError("offer renewal sequence has a gap")
            conn.execute(
                "UPDATE agent_offer_renewals_local SET sequence = ?, digest = ?, result_json = NULL WHERE session_id = ?",
                (renewal.sequence, digest, renewal.session_id),
            )
            conn.commit()
        return None

    def complete_offer_renewal(
        self, renewal: AgentOfferRenewal, result: Mapping[str, PlainData]
    ) -> None:
        with self._connection() as conn:
            updated = conn.execute(
                "UPDATE agent_offer_renewals_local SET result_json = ? WHERE session_id = ? "
                "AND offer_id = ? AND availability_revision = ? AND sequence = ?",
                (
                    _canonical_json(result),
                    renewal.session_id,
                    renewal.offer_id,
                    renewal.availability_revision,
                    renewal.sequence,
                ),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("offer renewal intent is unavailable")
            conn.commit()

    def next_offer_renewal(self, session_id: str) -> AgentOfferRenewal | None:
        session = self.session(session_id)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT r.offer_id, r.availability_revision, r.sequence, "
                "r.result_json FROM agent_offer_renewals_local r "
                "JOIN agent_offers_local o ON o.session_id = r.session_id "
                "WHERE r.session_id = ? AND o.state = 'ACTIVE'",
                (session_id,),
            ).fetchone()
        if row is None or str(row["availability_revision"]) != (
            session.availability_revision
        ):
            return None
        sequence = int(row["sequence"])
        return AgentOfferRenewal(
            session_id,
            str(row["offer_id"]),
            str(row["availability_revision"]),
            sequence if row["result_json"] is None and sequence else sequence + 1,
        )

    def prepare_poll(
        self,
        session_id: str,
        availability_revision: str,
        sequence: int,
        request: Mapping[str, PlainData],
    ) -> Mapping[str, PlainData] | None:
        session = self.session(session_id)
        if session.availability_revision != availability_revision:
            raise QueueConflictError("poll does not match the durable agent session")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise QueueServiceError("work poll sequence must be positive")
        digest = _canonical_digest(request)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT sequence, request_digest, state, result_json "
                "FROM agent_poll_state_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if current is None:
                if sequence != 1:
                    raise AgentPollSequenceGapError("work poll sequence has a gap")
                conn.execute(
                    "INSERT INTO agent_poll_state_local("
                    "session_id, availability_revision, sequence, request_digest, "
                    "state, result_json) VALUES (?, ?, ?, ?, 'PENDING', NULL)",
                    (session_id, availability_revision, sequence, digest),
                )
            else:
                stored_sequence = int(current["sequence"])
                if sequence < stored_sequence:
                    raise AgentStalePollError("work poll sequence is stale")
                if sequence > stored_sequence + 1:
                    raise AgentPollSequenceGapError("work poll sequence has a gap")
                if sequence == stored_sequence:
                    if str(current["request_digest"]) != digest:
                        raise QueueConflictError(
                            "poll sequence was reused with different content"
                        )
                    if current["result_json"] is not None:
                        value = json.loads(str(current["result_json"]))
                        if not isinstance(value, Mapping):
                            raise QueueServiceError("agent poll result is invalid")
                        conn.commit()
                        frozen = freeze_plain_data(
                            dict(value), path="agent poll replay"
                        )
                        assert isinstance(frozen, Mapping)
                        return frozen
                    if str(current["state"]) == "PENDING":
                        conn.commit()
                        return None
                    raise QueueConflictError("work poll was fenced and is not reusable")
                if str(current["state"]) == "PENDING":
                    raise AgentPollActiveError("work poll is already active")
                conn.execute(
                    "UPDATE agent_poll_state_local SET availability_revision = ?, "
                    "sequence = ?, request_digest = ?, state = 'PENDING', "
                    "result_json = NULL WHERE session_id = ?",
                    (availability_revision, sequence, digest, session_id),
                )
            conn.commit()
        return None

    def complete_mutation(
        self,
        operation: str,
        operation_id: str,
        result: Mapping[str, PlainData],
    ) -> None:
        encoded = _canonical_json(result)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT request_json, result_json FROM agent_mutation_intents "
                "WHERE operation = ? AND operation_id = ?",
                (operation, operation_id),
            ).fetchone()
            if row is None:
                raise QueueServiceError("agent mutation intent is unavailable")
            if row["result_json"] is not None:
                if str(row["result_json"]) != encoded:
                    raise QueueConflictError(
                        "mutation replay returned a different result"
                    )
                return
            conn.execute(
                "UPDATE agent_mutation_intents SET result_json = ? "
                "WHERE operation = ? AND operation_id = ?",
                (encoded, operation, operation_id),
            )
            if operation == "offer":
                request = json.loads(str(row["request_json"]))
                if not isinstance(request, Mapping):
                    raise QueueServiceError("agent offer intent is invalid")
                session_id = request.get("session_id")
                if not isinstance(session_id, str):
                    raise QueueServiceError("agent offer intent is invalid")
                returned_session = result.get("session")
                if returned_session is not None:
                    if not isinstance(returned_session, Mapping):
                        raise QueueServiceError(
                            "agent offer session receipt is invalid"
                        )
                    updated_session = _session_from_value(
                        cast(Mapping[str, PlainData], returned_session)
                    )
                    if (
                        updated_session.session_id != session_id
                        or updated_session.availability_revision
                        != request.get("availability_revision")
                    ):
                        raise QueueConflictError(
                            "agent offer session receipt conflicts"
                        )
                    conn.execute(
                        "UPDATE agent_sessions_local SET value_json = ? WHERE session_id = ?",
                        (_canonical_json(updated_session.value()), session_id),
                    )
                conn.execute(
                    "UPDATE agent_offers_local SET state = 'ACTIVE' WHERE session_id = ?",
                    (session_id,),
                )
                offer_id = result.get("offer_id")
                availability_revision = request.get("availability_revision")
                if not isinstance(offer_id, str) or not isinstance(
                    availability_revision, str
                ):
                    raise QueueServiceError("agent offer receipt is invalid")
                conn.execute(
                    "INSERT INTO agent_offer_renewals_local(session_id, offer_id, availability_revision, sequence, digest, result_json) "
                    "VALUES (?, ?, ?, 0, '', NULL) ON CONFLICT(session_id) DO UPDATE SET "
                    "offer_id = excluded.offer_id, availability_revision = excluded.availability_revision, sequence = 0, digest = '', result_json = NULL",
                    (session_id, offer_id, availability_revision),
                )
            if operation == "renew":
                # The bounded renewal row owns completed sequence replay. Keep
                # only a pending full request here to recover a lost response.
                conn.execute(
                    "DELETE FROM agent_mutation_intents WHERE operation = ? AND operation_id = ?",
                    (operation, operation_id),
                )
            conn.commit()

    def complete_poll(
        self,
        session_id: str,
        sequence: int,
        result: Mapping[str, PlainData],
        *, recovered: bool = False,
    ) -> None:
        encoded = _canonical_json(result)
        poll_result = result.get("result")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT state, result_json FROM agent_poll_state_local "
                "WHERE session_id = ? AND sequence = ?",
                (session_id, sequence),
            ).fetchone()
            if row is None:
                raise QueueServiceError("agent poll state is unavailable")
            if row["result_json"] is not None:
                if str(row["result_json"]) != encoded:
                    raise QueueConflictError("poll replay returned a different result")
                conn.commit()
                return
            previous_state = str(row["state"])
            if previous_state != "PENDING" and not (recovered and previous_state == "FENCED"):
                raise QueueConflictError("work poll was fenced")
            if poll_result == "assignment":
                request_value = result.get("request")
                from ._shared_assignment import reference
                ref = reference(request_value)
                if ref is not None:
                    if ref["session_id"] != session_id:
                        raise QueueConflictError("shared assignment reference targets another session")
                    assignment_id = str(ref["assignment_id"])
                else:
                    assignment_id = _ResidentAssignmentBundle.from_remote_dict(request_value).assignment_id
                request_json = _canonical_json(
                    cast(Mapping[str, PlainData], request_value)
                )
                retained = conn.execute(
                    "SELECT reference_json FROM agent_session_references "
                    "WHERE session_id = ? AND reference_kind = 'delivery' AND reference_id = ?",
                    (session_id, assignment_id),
                ).fetchone()
                if (
                    retained is not None
                    and retained[0] is not None
                    and retained[0] != request_json
                ):
                    raise QueueConflictError(
                        "assignment delivery replay returned a different request"
                    )
                conn.execute(
                    "INSERT INTO agent_session_references(session_id, "
                    "reference_kind, reference_id, resolved, reference_json) "
                    "VALUES (?, 'delivery', ?, 0, ?) ON CONFLICT(session_id, "
                    "reference_kind, reference_id) DO UPDATE SET "
                    "reference_json = excluded.reference_json "
                    "WHERE agent_session_references.reference_json IS NULL",
                    (session_id, assignment_id, request_json),
                )
                poll_state = "DELIVERED"
            elif poll_result == "wait":
                poll_state = "WAIT"
            else:
                raise QueueServiceError("agent poll result is invalid")
            conn.execute(
                "UPDATE agent_poll_state_local SET state = ?, result_json = ? "
                "WHERE session_id = ? AND sequence = ? AND state = ?",
                (poll_state, encoded, session_id, sequence, previous_state),
            )
            conn.commit()

    def fence_poll(self, session_id: str, sequence: int, *, confirmed: bool = False) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE agent_poll_state_local SET state = ? "
                "WHERE session_id = ? AND sequence = ?",
                ("RECONCILED" if confirmed else "FENCED", session_id, sequence),
            )
            conn.commit()

    def replayed_control_effect(
        self, control: AgentControl
    ) -> AgentControlEffect | None:
        """Return an already completed exact control without new local effects."""

        with self._connection() as conn:
            row = conn.execute(
                "SELECT request_json, effect_json FROM agent_controls_local "
                "WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
        if row is None or row["effect_json"] is None:
            return None
        if str(row["request_json"]) != _canonical_json(control.value()):
            raise QueueConflictError("agent control operation conflicts")
        value = json.loads(str(row["effect_json"]))
        if not isinstance(value, Mapping):
            raise QueueServiceError("agent control effect is invalid")
        return AgentControlEffect.from_value(value)

    def prepare_control(
        self,
        control: AgentControl,
        *,
        replacement_fingerprint: str | None = None,
    ) -> AgentControlEffect | None:
        """Persist delivery and withdrawal before applying owner-local effects."""

        if replacement_fingerprint is not None and control.kind.value not in {"reload", "promote"}:
            raise QueueConflictError(
                "only an agent reload can bind a replacement fingerprint"
            )
        encoded = _canonical_json(control.value())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json, replacement_fingerprint, effect_json "
                "FROM agent_controls_local "
                "WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            if row is not None:
                if str(row["request_json"]) != encoded:
                    raise QueueConflictError("agent control operation conflicts")
                existing_fingerprint = row["replacement_fingerprint"]
                if (
                    replacement_fingerprint is not None
                    and existing_fingerprint is not None
                    and str(existing_fingerprint) != replacement_fingerprint
                ):
                    raise QueueConflictError("agent reload replacement conflicts")
                if row["effect_json"] is not None:
                    conn.commit()
                    value = json.loads(str(row["effect_json"]))
                    if not isinstance(value, Mapping):
                        raise QueueServiceError("agent control effect is invalid")
                    return AgentControlEffect.from_value(value)
                if replacement_fingerprint is not None and existing_fingerprint is None:
                    conn.execute(
                        "UPDATE agent_controls_local SET replacement_fingerprint = ? "
                        "WHERE operation_id = ?",
                        (replacement_fingerprint, control.operation_id),
                    )
            else:
                conn.execute(
                    "INSERT INTO agent_controls_local(operation_id, request_json, "
                    "replacement_fingerprint, effect_json, acknowledged) "
                    "VALUES (?, ?, ?, NULL, 0)",
                    (control.operation_id, encoded, replacement_fingerprint),
                )
            session = self.session(control.expected_session_id)
            if session.config_revision != control.expected_config_revision:
                effect = AgentControlEffect(
                    control.operation_id,
                    "stale_revision",
                    session.config_revision,
                    session.inventory_revision,
                    session.availability_revision,
                )
                conn.execute(
                    "UPDATE agent_controls_local SET effect_json = ? "
                    "WHERE operation_id = ?",
                    (_canonical_json(effect.value()), control.operation_id),
                )
                conn.commit()
                return effect
            if control.kind.value in {"drain", "reload", "promote"}:
                conn.execute(
                    "UPDATE agent_offers_local SET state = 'DRAINED' "
                    "WHERE session_id = ?",
                    (session.session_id,),
                )
                conn.execute(
                    "DELETE FROM agent_offer_renewals_local WHERE session_id = ?",
                    (session.session_id,),
                )
                conn.execute(
                    "UPDATE agent_poll_state_local SET state = 'FENCED' "
                    "WHERE session_id = ? AND state != 'RECONCILED'",
                    (session.session_id,),
                )
                conn.execute(
                    "INSERT INTO root_metadata(key, value) VALUES "
                    "('availability_state', 'drained') ON CONFLICT(key) "
                    "DO UPDATE SET value = excluded.value"
                )
            conn.commit()
        return None

    def record_control_effect(
        self, control: AgentControl, effect: AgentControlEffect
    ) -> None:
        """Record the completed local effect and its new whole-epoch revisions."""

        if effect.operation_id != control.operation_id:
            raise QueueConflictError("agent control effect identity conflicts")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json, effect_json FROM agent_controls_local "
                "WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            if row is None or str(row["request_json"]) != _canonical_json(
                control.value()
            ):
                raise QueueConflictError("agent control delivery is not durable")
            encoded = _canonical_json(effect.value())
            if row["effect_json"] is not None and str(row["effect_json"]) != encoded:
                raise QueueConflictError("agent control effect conflicts")
            session = self.session(control.expected_session_id)
            if effect.code == "applied":
                updated = replace(
                    session,
                    config_revision=effect.config_revision,
                    inventory_revision=effect.inventory_revision,
                    availability_revision=effect.availability_revision,
                )
                conn.execute(
                    "UPDATE agent_sessions_local SET value_json = ? "
                    "WHERE session_id = ?",
                    (_canonical_json(updated.value()), updated.session_id),
                )
                if control.kind.value == "resume":
                    conn.execute(
                        "INSERT INTO root_metadata(key, value) VALUES "
                        "('availability_state', 'active') ON CONFLICT(key) "
                        "DO UPDATE SET value = excluded.value"
                    )
            elif (
                effect.config_revision != session.config_revision
                or effect.inventory_revision != session.inventory_revision
                or effect.availability_revision != session.availability_revision
            ):
                raise QueueConflictError("failed agent control changed revisions")
            conn.execute(
                "UPDATE agent_controls_local SET effect_json = ? "
                "WHERE operation_id = ?",
                (encoded, control.operation_id),
            )
            conn.commit()

    def acknowledge_control(self, operation_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE agent_controls_local SET acknowledged = 1 WHERE operation_id = ? AND effect_json IS NOT NULL",
                (operation_id,),
            )
            conn.commit()

    def next_unacknowledged_control(
        self,
    ) -> tuple[AgentControl, AgentControlEffect] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT request_json, effect_json FROM agent_controls_local "
                "WHERE acknowledged = 0 AND effect_json IS NOT NULL "
                "ORDER BY operation_id LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        request = json.loads(str(row["request_json"]))
        effect = json.loads(str(row["effect_json"]))
        if not isinstance(request, Mapping) or not isinstance(effect, Mapping):
            raise QueueServiceError("retained agent control evidence is invalid")
        return AgentControl.from_value(request), AgentControlEffect.from_value(effect)

    def prepare_assignment_control(
        self, control: AgentAssignmentControl
    ) -> tuple[str, Mapping[str, PlainData] | None] | None:
        encoded = _canonical_json(control.value())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json, result_code, evidence_json FROM "
                "remote_assignment_controls_local WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            if row is not None:
                if str(row["request_json"]) != encoded:
                    raise QueueConflictError("assignment control conflicts")
                conn.commit()
                if row["result_code"] is None:
                    return None
                raw_evidence = row["evidence_json"]
                evidence = (
                    None
                    if raw_evidence is None
                    else freeze_plain_data(
                        json.loads(str(raw_evidence)),
                        path="retained assignment control evidence",
                    )
                )
                if evidence is not None and not isinstance(evidence, Mapping):
                    raise QueueServiceError(
                        "retained assignment control evidence is invalid"
                    )
                return str(row["result_code"]), evidence
            conn.execute(
                "INSERT INTO remote_assignment_controls_local(operation_id, "
                "assignment_id, request_json, result_code, evidence_json, acknowledged) "
                "VALUES (?, ?, ?, NULL, NULL, 0)",
                (control.operation_id, control.assignment_id, encoded),
            )
            conn.commit()
        return None

    def next_received_assignment_control(self) -> AgentAssignmentControl | None:
        """Read intent retained by receipt handling before its physical effect."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT request_json FROM remote_assignment_controls_local "
                "WHERE acknowledged = 0 AND result_code IS NULL ORDER BY operation_id LIMIT 1"
            ).fetchone()
        return None if row is None else AgentAssignmentControl.from_value(json.loads(str(row[0])))

    def record_assignment_control_result(
        self,
        control: AgentAssignmentControl,
        code: str,
        evidence: Mapping[str, PlainData] | None,
    ) -> None:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json, result_code, evidence_json FROM "
                "remote_assignment_controls_local WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            if row is None or str(row["request_json"]) != _canonical_json(
                control.value()
            ):
                raise QueueConflictError("assignment control is not durable")
            if row["result_code"] is not None and str(row["result_code"]) != code:
                raise QueueConflictError("assignment control result conflicts")
            encoded_evidence = None if evidence is None else _canonical_json(evidence)
            if (
                row["evidence_json"] is not None
                and str(row["evidence_json"]) != encoded_evidence
            ):
                raise QueueConflictError("assignment control evidence conflicts")
            conn.execute(
                "UPDATE remote_assignment_controls_local SET result_code = ?, "
                "evidence_json = ? "
                "WHERE operation_id = ?",
                (code, encoded_evidence, control.operation_id),
            )
            conn.commit()

    def acknowledge_assignment_control(self, operation_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE remote_assignment_controls_local SET acknowledged = 1 "
                "WHERE operation_id = ? AND result_code IS NOT NULL",
                (operation_id,),
            )
            conn.commit()

    def next_unacknowledged_assignment_control(
        self,
    ) -> tuple[AgentAssignmentControl, str, Mapping[str, PlainData] | None] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT request_json, result_code, evidence_json FROM "
                "remote_assignment_controls_local WHERE acknowledged = 0 "
                "AND result_code IS NOT NULL ORDER BY operation_id LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        request = json.loads(str(row["request_json"]))
        if not isinstance(request, Mapping):
            raise QueueServiceError("retained assignment control evidence is invalid")
        raw_evidence = row["evidence_json"]
        evidence = (
            None
            if raw_evidence is None
            else freeze_plain_data(
                json.loads(str(raw_evidence)),
                path="retained assignment control evidence",
            )
        )
        if evidence is not None and not isinstance(evidence, Mapping):
            raise QueueServiceError("retained assignment control evidence is invalid")
        return (
            AgentAssignmentControl.from_value(request),
            str(row["result_code"]),
            evidence,
        )

    def retain_assignment_reference(self, session_id: str, assignment_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO agent_session_references(session_id, reference_kind, "
                "reference_id, resolved) VALUES (?, 'delivery', ?, 0) "
                "ON CONFLICT(session_id, reference_kind, reference_id) DO NOTHING",
                (session_id, assignment_id),
            )
            conn.commit()

    def resolve_assignment_reference(self, session_id: str, assignment_id: str) -> None:
        with self._connection() as conn:
            updated = conn.execute(
                "UPDATE agent_session_references SET resolved = 1 WHERE "
                "session_id = ? AND reference_kind = 'delivery' AND reference_id = ?",
                (session_id, assignment_id),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("remote assignment reference is unavailable")
            conn.commit()

    def complete_assignment_release(self, session: AgentSession, assignment_id: str) -> None:
        """Consume the delivery and its offer atomically after proven release."""
        if session.agent_root_id != self.root_id:
            raise QueueConflictError("released session does not match the agent root")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT resolved FROM agent_session_references WHERE session_id = ? "
                "AND reference_kind = 'delivery' AND reference_id = ?",
                (session.session_id, assignment_id),
            ).fetchone()
            if row is None:
                raise QueueConflictError("remote assignment reference is unavailable")
            if not row["resolved"]:
                if session.state is AgentSessionState.ACTIVE:
                    updated = conn.execute(
                        "UPDATE agent_sessions_local SET value_json = ?, state = ? "
                        "WHERE session_id = ? AND state = ?",
                        (_canonical_json(session.value()), session.state.value,
                         session.session_id, AgentSessionState.ACTIVE.value),
                    ).rowcount
                    if updated != 1:
                        raise QueueServiceError("remote agent session evidence is unavailable")
                self._invalidate_resource_offer(conn, session.session_id)
                conn.execute(
                    "UPDATE agent_session_references SET resolved = 1 WHERE session_id = ? "
                    "AND reference_kind = 'delivery' AND reference_id = ?",
                    (session.session_id, assignment_id),
                )
            conn.commit()

    @staticmethod
    def _invalidate_resource_offer(conn: sqlite3.Connection, session_id: str) -> None:
        conn.execute("UPDATE agent_offers_local SET state = 'FENCED' WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agent_offer_renewals_local WHERE session_id = ?", (session_id,))

    def has_unresolved_assignment_references(self) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_session_references WHERE "
                "reference_kind = 'delivery' AND resolved = 0 LIMIT 1"
            ).fetchone()
        return row is not None or self.pending_poll() is not None

    def delivery_request(self, session_id: str, assignment_id: str) -> object:
        """Read the original authenticated wire representation, including unresolved references."""
        with self._connection() as conn:
            retained = conn.execute("SELECT reference_json FROM agent_session_references WHERE session_id = ? AND reference_kind = 'delivery' AND reference_id = ?", (session_id, assignment_id)).fetchone()
            if retained is not None and retained[0] is not None:
                return json.loads(retained[0])
        return None

    def unresolved_assignment_references(self) -> tuple[tuple[str, str], ...]:
        """Return the exact durable deliveries that startup must reconcile."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT session_id, reference_id FROM agent_session_references "
                    "WHERE reference_kind = 'delivery' AND resolved = 0 "
                    "ORDER BY session_id, reference_id"
                )
            )
        return tuple((str(row["session_id"]), str(row["reference_id"])) for row in rows)

    def contained_assignment_ids(self) -> tuple[str, ...]:
        """Return assignments with a durable positive cancellation proof."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT DISTINCT assignment_id FROM "
                    "remote_assignment_controls_local WHERE result_code = 'contained' "
                    "ORDER BY assignment_id"
                )
            )
        return tuple(str(row["assignment_id"]) for row in rows)

    def contained_assignment_control(
        self, session_id: str, assignment_id: str, fence: str
    ) -> str:
        """Return the one acknowledged old-root containment operation."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT operation_id, request_json FROM "
                    "remote_assignment_controls_local WHERE assignment_id = ? "
                    "AND result_code = 'contained' AND acknowledged = 1 "
                    "ORDER BY operation_id",
                    (assignment_id,),
                )
            )
        if len(rows) != 1:
            raise QueueConflictError(
                "contained assignment has no exact acknowledged control"
            )
        raw = json.loads(str(rows[0]["request_json"]))
        if not isinstance(raw, Mapping):
            raise QueueServiceError("retained assignment control is invalid")
        control = AgentAssignmentControl.from_value(raw)
        if (
            control.session_id != session_id
            or control.assignment_id != assignment_id
            or control.fence != fence
        ):
            raise QueueConflictError("contained assignment control is stale")
        return str(rows[0]["operation_id"])

    def provider_release_proof(
        self,
        session_id: str,
        assignment_id: str,
        execution_journal: SQLiteAgentJournal,
    ) -> AgentProviderReleaseProof:
        """Join old-root possession to immutable provider-release evidence."""

        evidence: ProviderReleaseEvidence = execution_journal.provider_release_evidence(
            assignment_id
        )
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value_json, retirement_secret, state FROM "
                "agent_sessions_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            controls = tuple(
                conn.execute(
                    "SELECT operation_id FROM remote_assignment_controls_local "
                    "WHERE assignment_id = ? AND result_code = 'contained' "
                    "AND acknowledged = 1 ORDER BY operation_id",
                    (assignment_id,),
                )
            )
        if row is None or str(row["state"]) != AgentSessionState.ACTIVE.value:
            raise QueueServiceError("remote agent session evidence is unavailable")
        value = json.loads(str(row["value_json"]))
        if not isinstance(value, Mapping):
            raise QueueServiceError("remote agent session evidence is invalid")
        session = _session_from_value(cast(Mapping[str, PlainData], value))
        secret = row["retirement_secret"]
        assignment = evidence.assignment
        if (
            session.agent_root_id != self.root_id
            or assignment.session_id != session.session_id
            or assignment.agent_id != session.agent_id
        ):
            raise QueueConflictError(
                "provider release evidence does not match the old agent root"
            )
        if not isinstance(secret, str) or len(secret) != 64:
            raise QueueServiceError("remote agent retirement secret is unavailable")
        if len(controls) > 1:
            raise QueueConflictError(
                "provider release has conflicting containment controls"
            )
        recovery_control_operation_id = (
            None if not controls else str(controls[0]["operation_id"])
        )
        return AgentProviderReleaseProof(
            session_id=session.session_id,
            coordinator_id=session.coordinator_id,
            coordinator_epoch=session.coordinator_epoch,
            agent_id=session.agent_id,
            agent_root_id=session.agent_root_id,
            policy_revision=session.policy_revision,
            config_revision=session.config_revision,
            inventory_revision=session.inventory_revision,
            assignment_id=assignment.assignment_id,
            claim_id=assignment.claim_id,
            execution_fence=evidence.execution_fence,
            released_availability_revision=evidence.availability_revision,
            recovery_control_operation_id=recovery_control_operation_id,
            retirement_secret=secret,
        )

    def fence_and_prove_empty(self, session_id: str) -> AgentRetirementProof:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT value_json, retirement_secret, state FROM agent_sessions_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None or str(row["state"]) not in {
                AgentSessionState.ACTIVE.value,
                AgentSessionState.RETIRING.value,
            }:
                raise QueueServiceError("remote agent session evidence is unavailable")
            session_value = json.loads(str(row["value_json"]))
            if not isinstance(session_value, Mapping):
                raise QueueServiceError("remote agent session evidence is invalid")
            session = _session_from_value(cast(Mapping[str, PlainData], session_value))
            if session.agent_root_id != self.root_id:
                raise QueueConflictError("session does not match the agent root")
            secret = row["retirement_secret"]
            if not isinstance(secret, str) or len(secret) != 64:
                raise QueueServiceError("remote agent retirement secret is unavailable")
            conn.execute(
                "UPDATE agent_sessions_local SET state = ? WHERE session_id = ?",
                (AgentSessionState.RETIRING.value, session_id),
            )
            conn.execute(
                "UPDATE agent_offers_local SET state = 'FENCED' WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "UPDATE agent_poll_state_local SET state = 'FENCED' "
                "WHERE session_id = ? AND state != 'RECONCILED'",
                (session_id,),
            )
            unresolved = conn.execute(
                "SELECT COUNT(*) AS n FROM agent_session_references WHERE session_id = ? AND resolved = 0",
                (session_id,),
            ).fetchone()
            if unresolved is None or int(unresolved["n"]) != 0:
                conn.commit()
                raise QueueConflictError(
                    "remote agent session has unresolved references"
                )
            references: list[dict[str, PlainData]] = [
                {
                    "kind": str(item["reference_kind"]),
                    "id": str(item["reference_id"]),
                    "resolved": bool(item["resolved"]),
                }
                for item in conn.execute(
                    "SELECT reference_kind, reference_id, resolved FROM agent_session_references WHERE session_id = ? ORDER BY reference_kind, reference_id",
                    (session_id,),
                )
            ]
            if any(item["kind"] not in _SESSION_REFERENCE_KINDS for item in references):
                raise QueueServiceError("agent session reference kind is unsupported")
            revision = int(
                conn.execute(
                    "SELECT revision FROM agent_reference_revision WHERE singleton = 1"
                ).fetchone()[0]
            )
            reference_digest = _canonical_digest(
                {
                    "revision": revision,
                    "references": [cast(PlainData, item) for item in references],
                }
            )
            proof = AgentRetirementProof(
                session.session_id,
                session.coordinator_id,
                session.coordinator_epoch,
                session.agent_id,
                session.agent_root_id,
                session.policy_revision,
                session.config_revision,
                session.inventory_revision,
                session.availability_revision,
                revision,
                reference_digest,
                secret,
            )
            conn.execute(
                "INSERT INTO agent_retirement_proofs_local(session_id, proof_json) VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET proof_json = excluded.proof_json",
                (session_id, _canonical_json(proof.value())),
            )
            conn.commit()
        return proof

    def persist_retired(
        self, session_id: str, retirement_operation_id: str,
        *, role_receipt: Mapping[str, PlainData] | None = None,
    ) -> None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value_json, registration_operation_id, retirement_secret FROM agent_sessions_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise QueueServiceError("remote agent session evidence is unavailable")
            value = json.loads(str(row["value_json"]))
            if not isinstance(value, Mapping):
                raise QueueServiceError("remote agent session evidence is invalid")
            session = replace(
                _session_from_value(cast(Mapping[str, PlainData], value)),
                state=AgentSessionState.RETIRED_CLEAN,
            )
            updated = conn.execute(
                "UPDATE agent_sessions_local SET value_json = ?, retirement_secret = NULL, state = ? "
                "WHERE session_id = ? AND state = ?",
                (
                    _canonical_json(session.value()),
                    session.state.value,
                    session_id,
                    AgentSessionState.RETIRING.value,
                ),
            ).rowcount
            if updated != 1:
                raise QueueConflictError("agent session is not retiring")
            conn.execute(
                "UPDATE agent_registration_intents SET retirement_secret = NULL "
                "WHERE operation_id = ? AND retirement_secret = ?",
                (str(row["registration_operation_id"]), str(row["retirement_secret"])),
            )
            conn.execute(
                "DELETE FROM agent_retirement_proofs_local WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "DELETE FROM agent_mutation_intents WHERE operation = 'retire' AND operation_id = ?",
                (retirement_operation_id,),
            )
            if role_receipt is not None:
                conn.execute(
                    "INSERT INTO root_metadata(key,value) VALUES ('role_retirement',?)",
                    (_canonical_json(role_receipt),),
                )
            conn.commit()

    def _persist_mutation(
        self, operation: str, operation_id: str, value: Mapping[str, PlainData]
    ) -> None:
        digest = _canonical_digest(value)
        encoded = _canonical_json(value)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT digest FROM agent_mutation_intents WHERE operation = ? AND operation_id = ?",
                (operation, operation_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO agent_mutation_intents(operation, operation_id, digest, request_json, result_json) VALUES (?, ?, ?, ?, NULL)",
                    (operation, operation_id, digest, encoded),
                )
            elif str(row["digest"]) != digest:
                raise QueueConflictError(
                    "idempotency key was reused with different content"
                )
            conn.commit()


def _canonical_json(value: Mapping[str, PlainData]) -> str:
    return json.dumps(
        thaw_plain_data(value, path="agent journal value"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_digest(value: Mapping[str, PlainData]) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _resident_profile_key(profile: ResidentExecutionProfile) -> str:
    return _agent_revision(
        "resident-profile",
        {
            "descriptor": profile.descriptor.to_dict(),
            "project_root": str(profile.project_root),
            "python_executable": str(profile.python_executable),
            "cpu_capacity": profile.cpu_capacity,
            "memory_capacity_bytes": profile.memory_capacity_bytes,
            "gpu_devices": [
                {
                    "descriptor": device.descriptor.to_dict(),
                    "binding_value": device.binding_value,
                }
                for device in profile.gpu_devices
            ],
        },
    )


def _agent_config_revision(config: AgentTlsClientConfig) -> str:
    return _agent_revision(
        "config",
        {
            "profiles": [
                _resident_profile_key(profile) for profile in config.resident_profiles
            ],
            "slurm_profiles": [
                [profile.profile_id, profile.configuration_fingerprint]
                for profile in config.slurm_profiles
            ],
        },
    )


def _agent_inventory_revision(config: AgentTlsClientConfig) -> str:
    if not config.resident_profiles:
        return _agent_revision("inventory", {"capacity": None})
    capacity = config.capacity_profile
    return _agent_revision(
        "inventory",
        {
            "cpu_capacity": capacity.cpu_capacity,
            "memory_capacity_bytes": capacity.memory_capacity_bytes,
            "gpu_devices": [
                device.descriptor.to_dict() for device in capacity.gpu_devices
            ],
        },
    )


def _record_agent_declaration_binding(
    connection: sqlite3.Connection,
    config: AgentTlsClientConfig,
    revision: int,
) -> None:
    """Bind qualified declarations in the transaction activating this revision.

    Programmatic configurations carry no source evidence by default. A reload
    through such a configuration removes obsolete evidence rather than leaving
    a prior declaration apparently attached to the new active revision.
    """
    if config.declaration_digest is None:
        connection.execute(
            "DELETE FROM root_metadata WHERE key = 'declaration_binding'"
        )
        return
    if any(
        profile.readiness_result is None or not profile.readiness_result.ok
        for profile in config.resident_profiles
    ):
        raise QueueServiceError("agent declaration binding requires accepted readiness")
    value = {
        "version": 1,
        "declaration_digest": config.declaration_digest,
        "immutable_fingerprint": config.deployment_configuration_fingerprint,
        "active_fingerprint": config.active_configuration_fingerprint,
        "active_configuration_revision": revision,
    }
    connection.execute(
        "INSERT INTO root_metadata(key, value) VALUES ('declaration_binding', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (json.dumps(value, sort_keys=True, separators=(",", ":")),),
    )


def _agent_active_fingerprint(config: AgentTlsClientConfig) -> str:
    if config.active_configuration_fingerprint is not None:
        return config.active_configuration_fingerprint
    return _agent_revision(
        "active",
        {
            "config": _agent_config_revision(config),
            "inventory": _agent_inventory_revision(config),
            **(
                {"max_concurrent_assignments": config.max_concurrent_assignments}
                if config.max_concurrent_assignments != 1
                else {}
            ),
            **(
                {"gpu_occupancy": config.gpu_occupancy_policy.to_dict()}
                if config.gpu_occupancy_policy is not None
                and config.gpu_occupancy_policy != GpuOccupancyPolicy()
                else {}
            ),
        },
    )


def _agent_revision(prefix: str, value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()}"
