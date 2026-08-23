"""Authenticated, no-launch agent session protocol.

This module deliberately owns only the coordinator-facing Phase 4 protocol.
It has no dependency on the managed-local execution composition: retained
offers are protocol facts until the later delivery phase explicitly consumes
them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING
from uuid import uuid4

from loom.serialization import PlainData, freeze_plain_data
from loom.timestamps import parse_timestamp

from .errors import QueueConflictError, QueueServiceError

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon, LocalDaemonPrincipal


PROTOCOL_VERSION = "1"
_MAX_IDENTIFIER = 160
_MAX_COLLECTION = 32
_MAX_OFFER_TTL_SECONDS = 3600
_MAX_RESOURCE_ATOM = 2**63 - 1


class AgentSessionState(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED_CLEAN = "RETIRED_CLEAN"


@dataclass(frozen=True, slots=True)
class AgentPrincipalPolicy:
    """Protected mapping from a transport credential to one agent identity."""

    credential_id: str
    principal_id: str
    agent_id: str
    pools: tuple[str, ...]
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("credential_id", "principal_id", "agent_id"):
            _identifier(getattr(self, name), name)
        _identifiers(self.pools, "pools", non_empty=True)
        _identifiers(self.capabilities, "capabilities")


@dataclass(frozen=True, slots=True)
class TransportPrincipalPolicy:
    """Protected client/operator credential mapping for the HTTP adapter."""

    credential_id: str
    principal_id: str
    role: str

    def __post_init__(self) -> None:
        _identifier(self.credential_id, "credential_id")
        _identifier(self.principal_id, "principal_id")
        if self.role not in {"client", "operator"}:
            raise QueueServiceError("transport principal role is unsupported")


@dataclass(frozen=True, slots=True)
class AgentPolicyConfig:
    """Protected, replaceable current authorization policy."""

    revision: str = "policy-1"
    agents: tuple[AgentPrincipalPolicy, ...] = ()
    principals: tuple[TransportPrincipalPolicy, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.revision, "policy revision")
        credentials = [item.credential_id for item in self.agents] + [
            item.credential_id for item in self.principals
        ]
        if len(set(credentials)) != len(credentials):
            raise QueueServiceError("agent credential IDs must be unique")


@dataclass(frozen=True, slots=True)
class AgentRegistration:
    idempotency_key: str
    coordinator_id: str
    coordinator_epoch: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    declared_capabilities: tuple[str, ...] = ()
    session_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "coordinator_id",
            "coordinator_epoch",
            "config_revision",
            "inventory_revision",
            "availability_revision",
        ):
            _identifier(getattr(self, name), name)
        _identifiers(self.declared_capabilities, "declared capabilities")
        if self.session_id is not None:
            _identifier(self.session_id, "session_id")

    def value(self) -> dict[str, PlainData]:
        return {
            "idempotency_key": self.idempotency_key,
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "declared_capabilities": list(self.declared_capabilities),
            "session_id": self.session_id,
        }


@dataclass(frozen=True, slots=True)
class AgentSession:
    session_id: str
    coordinator_id: str
    coordinator_epoch: str
    agent_id: str
    policy_revision: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    capabilities: tuple[str, ...]
    pools: tuple[str, ...]
    state: AgentSessionState

    def value(self) -> dict[str, PlainData]:
        return {
            "session_id": self.session_id,
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "agent_id": self.agent_id,
            "policy_revision": self.policy_revision,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "capabilities": list(self.capabilities),
            "pools": list(self.pools),
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class AgentOffer:
    session_id: str
    coordinator_epoch: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    cpu: int
    memory_bytes: int
    ttl_seconds: int
    pools: tuple[str, ...] = ("default",)
    reflected_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "coordinator_epoch",
            "config_revision",
            "inventory_revision",
            "availability_revision",
        ):
            _identifier(getattr(self, name), name)
        for value, name in ((self.cpu, "cpu"), (self.memory_bytes, "memory_bytes")):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_RESOURCE_ATOM:
                raise QueueServiceError(f"{name} must be a bounded non-negative integer")
        if not self.cpu and not self.memory_bytes:
            raise QueueServiceError("offer capacity must not be empty")
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, int)
            or not 1 <= self.ttl_seconds <= _MAX_OFFER_TTL_SECONDS
        ):
            raise QueueServiceError("offer TTL is outside the permitted range")
        _identifiers(self.reflected_claim_ids, "reflected claim IDs")
        _identifiers(self.pools, "offer pools", non_empty=True)

    def value(self) -> dict[str, PlainData]:
        return {
            "session_id": self.session_id,
            "coordinator_epoch": self.coordinator_epoch,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "cpu": self.cpu,
            "memory_bytes": self.memory_bytes,
            "ttl_seconds": self.ttl_seconds,
            "pools": list(self.pools),
            "reflected_claim_ids": list(self.reflected_claim_ids),
        }


class ScopedAuthorizer:
    """The one current-policy check used by direct and transport adapters."""

    def __init__(self, policy: AgentPolicyConfig) -> None:
        self.policy = policy

    def agent(self, principal: "LocalDaemonPrincipal") -> AgentPrincipalPolicy:
        credential_id = principal.credential_id
        if credential_id is None:
            raise QueueServiceError("agent credential is required")
        for rule in self.policy.agents:
            if rule.credential_id == credential_id and rule.principal_id == principal.subject:
                return rule
        raise QueueServiceError("daemon principal is not authorized for this operation")

    def transport_principal(self, credential_id: str) -> tuple[str, str]:
        for rule in self.policy.agents:
            if rule.credential_id == credential_id:
                return rule.principal_id, "agent"
        for rule in self.policy.principals:
            if rule.credential_id == credential_id:
                return rule.principal_id, rule.role
        raise QueueServiceError("daemon principal is not authorized for this operation")

    def require_agent(self, principal: "LocalDaemonPrincipal", action: str) -> AgentPrincipalPolicy:
        if principal.role.value != "agent":
            raise QueueServiceError("daemon principal is not authorized for this operation")
        if action not in {"handshake", "register", "reconcile", "offer", "poll", "retire"}:
            raise QueueServiceError("agent operation is unsupported")
        return self.agent(principal)

    def require_role(self, principal: "LocalDaemonPrincipal", role: str) -> None:
        """Authorize a direct view with the same current policy as HTTP."""
        if principal.role.value != role:
            raise QueueServiceError("daemon principal is not authorized for this operation")
        # Existing owner-only Unix/direct views carry an already-trusted local
        # principal, so their legacy no-credential form remains supported.
        if principal.credential_id is None:
            return
        principal_id, mapped_role = self.transport_principal(principal.credential_id)
        if principal.subject != principal_id or mapped_role != role:
            raise QueueServiceError("daemon principal is not authorized for this operation")


class AgentSessionView:
    """A direct adapter with a trusted principal captured at construction."""

    def __init__(self, daemon: "LocalDaemon", principal: "LocalDaemonPrincipal") -> None:
        self._daemon = daemon
        self._principal = principal

    def handshake(self) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).handshake()

    def register(self, request: AgentRegistration) -> AgentSession:
        return AgentSessionService(self._daemon, self._principal).register(request)

    def reconcile(
        self, session_id: str, coordinator_epoch: str, *, expected: AgentSession | None = None
    ) -> AgentSession:
        return AgentSessionService(self._daemon, self._principal).reconcile(
            session_id, coordinator_epoch, expected=expected
        )

    def publish_offer(self, offer: AgentOffer, *, idempotency_key: str) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).publish_offer(
            offer, idempotency_key=idempotency_key
        )

    def wait_for_work(
        self, session_id: str, availability_revision: str, *, poll_id: str
    ) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).wait_for_work(
            session_id, availability_revision, poll_id=poll_id
        )

    def retire_clean(self, session_id: str, *, idempotency_key: str, agent_proof: str) -> Mapping[str, PlainData]:
        return AgentSessionService(self._daemon, self._principal).retire_clean(
            session_id, idempotency_key=idempotency_key, agent_proof=agent_proof
        )


class AgentSessionService:
    """Coordinator-owned durable transitions for the restricted agent view."""

    def __init__(self, daemon: "LocalDaemon", principal: "LocalDaemonPrincipal") -> None:
        self._daemon = daemon
        self._principal = principal

    def _rule(self, action: str) -> AgentPrincipalPolicy:
        return ScopedAuthorizer(self._daemon._agent_policy).require_agent(  # type: ignore[attr-defined]
            self._principal, action
        )

    def handshake(self) -> Mapping[str, PlainData]:
        self._rule("handshake")
        coordinator_id = self._daemon._require_started()  # type: ignore[attr-defined]
        return freeze_plain_data(
            {
                "protocol_version": PROTOCOL_VERSION,
                "capabilities": ["agent-sessions-v1", "wait-only-work-v1"],
                "coordinator_id": coordinator_id,
                "coordinator_epoch": self._daemon._epoch or "",  # type: ignore[attr-defined]
                "role": "agent",
            },
            path="agent handshake",
        )

    def register(self, request: AgentRegistration) -> AgentSession:
        rule = self._rule("register")
        coordinator_id = self._daemon._require_started()  # type: ignore[attr-defined]
        epoch = self._daemon._epoch or ""  # type: ignore[attr-defined]
        if request.coordinator_id != coordinator_id or request.coordinator_epoch != epoch:
            raise QueueConflictError("coordinator identity or epoch is stale")
        if request.session_id is not None:
            raise QueueConflictError("agent callers cannot select a session ID")
        digest = _digest(request.value())
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            replay = _receipt(conn, rule.principal_id, "register", request.idempotency_key, digest)
            if replay is not None:
                conn.commit()
                return _session_from_value(replay)
            previous = conn.execute(
                "SELECT session_id, state FROM agent_sessions WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
                (rule.agent_id,),
            ).fetchone()
            if previous is not None and str(previous["state"]) == AgentSessionState.ACTIVE.value:
                raise QueueConflictError("agent already has an active session")
            session = AgentSession(
                session_id=f"session-{uuid4()}", coordinator_id=coordinator_id,
                coordinator_epoch=epoch, agent_id=rule.agent_id,
                policy_revision=self._daemon._agent_policy.revision,  # type: ignore[attr-defined]
                config_revision=request.config_revision, inventory_revision=request.inventory_revision,
                availability_revision=request.availability_revision,
                capabilities=tuple(sorted(set(request.declared_capabilities) & set(rule.capabilities))),
                pools=rule.pools,
                state=AgentSessionState.ACTIVE,
            )
            accepted = self._daemon._accepted_time(conn)  # type: ignore[attr-defined]
            conn.execute(
                "INSERT INTO agent_sessions(session_id, agent_id, principal_id, policy_revision, config_revision, inventory_revision, availability_revision, capabilities_json, pools_json, coordinator_epoch, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session.session_id, rule.agent_id, rule.principal_id, session.policy_revision,
                 session.config_revision, session.inventory_revision, session.availability_revision,
                 json.dumps(session.capabilities), json.dumps(session.pools), epoch, session.state.value, accepted),
            )
            _write_receipt(conn, rule.principal_id, "register", request.idempotency_key, digest, session.value())
            conn.commit()
        return session

    def reconcile(self, session_id: str, coordinator_epoch: str, *, expected: AgentSession | None = None) -> AgentSession:
        rule = self._rule("reconcile")
        _identifier(session_id, "session_id")
        _identifier(coordinator_epoch, "coordinator_epoch")
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute("SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone()
        session = _session_from_row(row, self._daemon._require_started())  # type: ignore[attr-defined]
        if session.agent_id != rule.agent_id or session.state is not AgentSessionState.ACTIVE:
            raise QueueServiceError("agent session is not authorized")
        if expected is not None and (
            expected.session_id != session.session_id
            or expected.coordinator_id != session.coordinator_id
            or expected.agent_id != session.agent_id
            or expected.config_revision != session.config_revision
            or expected.inventory_revision != session.inventory_revision
            or expected.availability_revision != session.availability_revision
            or expected.capabilities != session.capabilities
            or expected.pools != session.pools
        ):
            raise QueueConflictError("agent session reconciliation facts are stale")
        if not set(session.capabilities).issubset(rule.capabilities) or not set(session.pools).issubset(rule.pools):
            raise QueueServiceError("agent session effective scope is no longer current")
        if coordinator_epoch != self._daemon._epoch:  # type: ignore[attr-defined]
            raise QueueConflictError("coordinator epoch is stale")
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE agent_sessions SET coordinator_epoch = ?, policy_revision = ? WHERE session_id = ?",
                (coordinator_epoch, self._daemon._agent_policy.revision, session_id),  # type: ignore[attr-defined]
            )
            conn.commit()
        return AgentSession(
            session.session_id, session.coordinator_id, coordinator_epoch,
            session.agent_id, self._daemon._agent_policy.revision,  # type: ignore[attr-defined]
            session.config_revision, session.inventory_revision,
            session.availability_revision, session.capabilities, session.pools, session.state,
        )

    def publish_offer(self, offer: AgentOffer, *, idempotency_key: str) -> Mapping[str, PlainData]:
        rule = self._rule("offer")
        _identifier(idempotency_key, "idempotency_key")
        digest = _digest(offer.value())
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            replay = _receipt(conn, rule.principal_id, "offer", idempotency_key, digest)
            if replay is not None:
                conn.commit()
                return replay
            session = _session_from_row(
                conn.execute("SELECT * FROM agent_sessions WHERE session_id = ?", (offer.session_id,)).fetchone(),
                self._daemon._require_started(),  # type: ignore[attr-defined]
            )
            self._check_current_session(session, rule, offer.coordinator_epoch)
            if (offer.config_revision, offer.inventory_revision, offer.availability_revision) != (
                session.config_revision, session.inventory_revision, session.availability_revision
            ):
                raise QueueConflictError("agent offer revisions do not match its session")
            if offer.pools != session.pools:
                raise QueueConflictError("agent offer pools do not match its effective scope")
            accepted = self._daemon._accepted_time(conn)  # type: ignore[attr-defined]
            expiry = _add_seconds(accepted, offer.ttl_seconds)
            offer_id = f"offer-{uuid4()}"
            conn.execute("UPDATE agent_offers SET current = 0 WHERE session_id = ?", (offer.session_id,))
            conn.execute(
                "INSERT INTO agent_offers(offer_id, session_id, coordinator_epoch, availability_revision, offer_json, accepted_at, expires_at, current) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (offer_id, offer.session_id, offer.coordinator_epoch, offer.availability_revision,
                 json.dumps(offer.value(), sort_keys=True, separators=(",", ":")), accepted, expiry),
            )
            value: dict[str, PlainData] = {"offer_id": offer_id, "accepted_at": accepted, "expires_at": expiry, "state": "retained"}
            _write_receipt(conn, rule.principal_id, "offer", idempotency_key, digest, value)
            conn.commit()
        return freeze_plain_data(value, path="agent offer receipt")

    def wait_for_work(self, session_id: str, availability_revision: str, *, poll_id: str) -> Mapping[str, PlainData]:
        rule = self._rule("poll")
        for identifier, name in ((session_id, "session_id"), (availability_revision, "availability_revision"), (poll_id, "poll_id")):
            _identifier(identifier, name)
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            session = _session_from_row(conn.execute("SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone(), self._daemon._require_started())  # type: ignore[attr-defined]
            self._check_current_session(session, rule, self._daemon._epoch or "")  # type: ignore[attr-defined]
            if session.availability_revision != availability_revision:
                raise QueueConflictError("work poll availability revision is stale")
            offer = conn.execute("SELECT expires_at FROM agent_offers WHERE session_id = ? AND coordinator_epoch = ? AND availability_revision = ? AND current = 1", (session_id, self._daemon._epoch, availability_revision)).fetchone()  # type: ignore[attr-defined]
            if offer is None or str(offer["expires_at"]) < self._daemon._accepted_time(conn):  # type: ignore[attr-defined]
                raise QueueConflictError("work poll requires a current offer")
            digest = _digest({"session_id": session_id, "availability_revision": availability_revision, "coordinator_epoch": self._daemon._epoch or ""})  # type: ignore[attr-defined]
            replay = _poll_receipt(conn, rule.principal_id, poll_id, digest)
            if replay is not None:
                conn.commit()
                return replay
            conn.execute("UPDATE agent_polls SET active = 0 WHERE session_id = ? AND availability_revision = ?", (session_id, availability_revision))
            conn.execute("INSERT INTO agent_polls(poll_id, session_id, availability_revision, coordinator_epoch, active) VALUES (?, ?, ?, ?, 1)", (poll_id, session_id, availability_revision, self._daemon._epoch))  # type: ignore[attr-defined]
            value: dict[str, PlainData] = {"result": "wait", "poll_id": poll_id, "coordinator_epoch": self._daemon._epoch or ""}  # type: ignore[attr-defined]
            _write_poll_receipt(conn, rule.principal_id, poll_id, digest, value)
            conn.commit()
        return freeze_plain_data(value, path="agent wait")

    def retire_clean(self, session_id: str, *, idempotency_key: str, agent_proof: str) -> Mapping[str, PlainData]:
        rule = self._rule("retire")
        _identifier(session_id, "session_id")
        _identifier(idempotency_key, "idempotency_key")
        _identifier(agent_proof, "agent retirement proof")
        digest = _digest({"session_id": session_id, "agent_proof": agent_proof})
        with self._daemon._connection() as conn:  # type: ignore[attr-defined]
            conn.execute("BEGIN IMMEDIATE")
            replay = _receipt(conn, rule.principal_id, "retire", idempotency_key, digest)
            if replay is not None:
                conn.commit()
                return replay
            session = _session_from_row(conn.execute("SELECT * FROM agent_sessions WHERE session_id = ?", (session_id,)).fetchone(), self._daemon._require_started())  # type: ignore[attr-defined]
            self._check_current_session(session, rule, self._daemon._epoch or "")  # type: ignore[attr-defined]
            # Fencing is durable before either owner supplies its empty-set proof.
            conn.execute("UPDATE agent_offers SET current = 0 WHERE session_id = ?", (session_id,))
            conn.execute("UPDATE agent_polls SET active = 0 WHERE session_id = ?", (session_id,))
            if not _coordinator_references_empty(conn, session_id):
                raise QueueConflictError("agent session has unresolved references")
            conn.execute("INSERT INTO agent_retirement_proofs(session_id, proof) VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET proof = excluded.proof", (session_id, agent_proof))
            conn.execute("UPDATE agent_sessions SET state = ? WHERE session_id = ?", (AgentSessionState.RETIRED_CLEAN.value, session_id))
            conn.execute("INSERT INTO agent_session_tombstones(session_id, state) VALUES (?, ?) ON CONFLICT(session_id) DO NOTHING", (session_id, AgentSessionState.RETIRED_CLEAN.value))
            value: dict[str, PlainData] = {"session_id": session_id, "state": AgentSessionState.RETIRED_CLEAN.value}
            _write_receipt(conn, rule.principal_id, "retire", idempotency_key, digest, value)
            conn.commit()
        return freeze_plain_data(value, path="agent retirement")

    def _check_current_session(self, session: AgentSession, rule: AgentPrincipalPolicy, epoch: str) -> None:
        if session.agent_id != rule.agent_id or session.state is not AgentSessionState.ACTIVE:
            raise QueueServiceError("agent session is not authorized")
        if session.policy_revision != self._daemon._agent_policy.revision:  # type: ignore[attr-defined]
            raise QueueServiceError("agent credential policy is no longer current")
        if epoch != self._daemon._epoch:  # type: ignore[attr-defined]
            raise QueueConflictError("coordinator epoch is stale")

def initialize_agent_session_schema(conn: sqlite3.Connection, *, coordinator: bool) -> None:
    """Additive V2 tables; retained Phase 3 rows are intentionally untouched."""
    if coordinator:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_sessions (session_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, principal_id TEXT NOT NULL, policy_revision TEXT NOT NULL, config_revision TEXT NOT NULL, inventory_revision TEXT NOT NULL, availability_revision TEXT NOT NULL, capabilities_json TEXT NOT NULL DEFAULT '[]', pools_json TEXT NOT NULL DEFAULT '[]', coordinator_epoch TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_receipts (principal_id TEXT NOT NULL, operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, digest TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(principal_id, operation, idempotency_key));
        CREATE TABLE IF NOT EXISTS agent_offers (offer_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, availability_revision TEXT NOT NULL, offer_json TEXT NOT NULL, accepted_at TEXT NOT NULL, expires_at TEXT NOT NULL, current INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_polls (poll_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, availability_revision TEXT NOT NULL, coordinator_epoch TEXT NOT NULL, active INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_poll_receipts (principal_id TEXT NOT NULL, poll_id TEXT NOT NULL, digest TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(principal_id, poll_id));
        CREATE TABLE IF NOT EXISTS agent_coordinator_references (session_id TEXT NOT NULL, reference_kind TEXT NOT NULL, reference_id TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id, reference_kind, reference_id));
        CREATE TABLE IF NOT EXISTS agent_retirement_proofs (session_id TEXT PRIMARY KEY, proof TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_session_tombstones (session_id TEXT PRIMARY KEY, state TEXT NOT NULL);
        """)
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(agent_sessions)")}
        if "capabilities_json" not in columns:
            conn.execute("ALTER TABLE agent_sessions ADD COLUMN capabilities_json TEXT NOT NULL DEFAULT '[]'")
        if "pools_json" not in columns:
            conn.execute("ALTER TABLE agent_sessions ADD COLUMN pools_json TEXT NOT NULL DEFAULT '[]'")


def _receipt(conn: sqlite3.Connection, principal: str, operation: str, key: str, digest: str) -> Mapping[str, PlainData] | None:
    row = conn.execute("SELECT digest, result_json FROM agent_receipts WHERE principal_id = ? AND operation = ? AND idempotency_key = ?", (principal, operation, key)).fetchone()
    if row is None:
        return None
    if str(row["digest"]) != digest:
        raise QueueConflictError("idempotency key was reused with different content")
    value = json.loads(str(row["result_json"]))
    if not isinstance(value, Mapping):
        raise QueueServiceError("agent receipt is invalid")
    return freeze_plain_data(value, path="agent receipt")


def _poll_receipt(conn: sqlite3.Connection, principal: str, poll_id: str, digest: str) -> Mapping[str, PlainData] | None:
    row = conn.execute("SELECT digest, result_json FROM agent_poll_receipts WHERE principal_id = ? AND poll_id = ?", (principal, poll_id)).fetchone()
    if row is None:
        return None
    if str(row["digest"]) != digest:
        raise QueueConflictError("poll ID was reused with different content")
    value = json.loads(str(row["result_json"]))
    if not isinstance(value, Mapping):
        raise QueueServiceError("agent poll receipt is invalid")
    return freeze_plain_data(value, path="agent poll receipt")


def _write_poll_receipt(conn: sqlite3.Connection, principal: str, poll_id: str, digest: str, result: Mapping[str, PlainData]) -> None:
    conn.execute("INSERT INTO agent_poll_receipts(principal_id, poll_id, digest, result_json) VALUES (?, ?, ?, ?)", (principal, poll_id, digest, json.dumps(result, sort_keys=True, separators=(",", ":"))))


def _coordinator_references_empty(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute("SELECT COUNT(*) AS n FROM agent_coordinator_references WHERE session_id = ? AND resolved = 0", (session_id,)).fetchone()
    return row is not None and int(row["n"]) == 0


def _write_receipt(conn: sqlite3.Connection, principal: str, operation: str, key: str, digest: str, result: Mapping[str, PlainData]) -> None:
    conn.execute("INSERT INTO agent_receipts(principal_id, operation, idempotency_key, digest, result_json) VALUES (?, ?, ?, ?, ?)", (principal, operation, key, digest, json.dumps(result, sort_keys=True, separators=(",", ":"))))


def _session_from_row(row: sqlite3.Row | None, coordinator_id: str) -> AgentSession:
    if row is None:
        raise QueueServiceError("agent session was not found")
    capabilities = _stored_identifiers(row["capabilities_json"], "session capabilities")
    pools = _stored_identifiers(row["pools_json"], "session pools")
    return AgentSession(str(row["session_id"]), coordinator_id, str(row["coordinator_epoch"]), str(row["agent_id"]), str(row["policy_revision"]), str(row["config_revision"]), str(row["inventory_revision"]), str(row["availability_revision"]), capabilities, pools, AgentSessionState(str(row["state"])))


def _session_from_value(value: Mapping[str, PlainData]) -> AgentSession:
    capabilities = value.get("capabilities")
    pools = value.get("pools")
    if not isinstance(capabilities, (list, tuple)) or any(
        not isinstance(item, str) for item in capabilities
    ) or not isinstance(pools, (list, tuple)) or any(not isinstance(item, str) for item in pools):
        raise QueueServiceError("agent session receipt capabilities are invalid")
    return AgentSession(
        str(value["session_id"]), str(value["coordinator_id"]),
        str(value["coordinator_epoch"]), str(value["agent_id"]),
        str(value["policy_revision"]), str(value["config_revision"]),
        str(value["inventory_revision"]), str(value["availability_revision"]),
        tuple(str(item) for item in capabilities), tuple(str(item) for item in pools), AgentSessionState(str(value["state"])),
    )


def _stored_identifiers(value: object, name: str) -> tuple[str, ...]:
    try:
        stored = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise QueueServiceError(f"{name} are invalid") from exc
    if not isinstance(stored, list) or any(not isinstance(item, str) for item in stored):
        raise QueueServiceError(f"{name} are invalid")
    _identifiers(stored, name)
    return tuple(stored)


def _digest(value: Mapping[str, PlainData]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER:
        raise QueueServiceError(f"{name} must be a bounded non-empty string")


def _identifiers(values: Sequence[str], name: str, *, non_empty: bool = False) -> None:
    if non_empty and not values:
        raise QueueServiceError(f"{name} must not be empty")
    if len(values) > _MAX_COLLECTION or len(set(values)) != len(values):
        raise QueueServiceError(f"{name} must be a bounded unique collection")
    for value in values:
        _identifier(value, name)


def _add_seconds(timestamp: str, seconds: int) -> str:
    from datetime import timedelta
    return (parse_timestamp(timestamp) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


__all__ = ["AgentOffer", "AgentPolicyConfig", "AgentPrincipalPolicy", "AgentRegistration", "AgentSession", "AgentSessionState", "AgentSessionView", "PROTOCOL_VERSION", "ScopedAuthorizer", "TransportPrincipalPolicy", "initialize_agent_session_schema"]
