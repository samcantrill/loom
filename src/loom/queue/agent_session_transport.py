"""Small mutual-TLS adapter for the restricted agent-session view.

The adapter derives a configured credential ID from the verified client
certificate's DER fingerprint.  It never accepts an actor, principal, agent,
or session selector from the HTTP path as transport identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import sqlite3
import ssl
import stat
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import urlsplit

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .agent_sessions import (
    AgentOffer,
    AgentPollActiveError,
    AgentRegistration,
    AgentRetirementProof,
    AgentSession,
    AgentSessionState,
    ScopedAuthorizer,
    _SESSION_REFERENCE_KINDS,
    _session_from_value,
    validate_agent_session_schema,
)
from .errors import QueueConflictError, QueueError, QueueServiceError
from .local_daemon import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonPrincipal,
    LocalDaemonRole,
)


_MAX_BODY_BYTES = 65_536
_MAX_JSON_DEPTH = 8
_MAX_JSON_COLLECTION = 64
_HTTP_TIMEOUT_SECONDS = 10


class _IndeterminateAgentProtocolError(QueueServiceError):
    """The request may have mutated its durable owner before transport failed."""


@dataclass(frozen=True, slots=True)
class AgentTlsServerConfig:
    host: str
    port: int
    certificate_path: Path
    private_key_path: Path
    client_ca_path: Path
    credential_fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.host or not 0 <= self.port <= 65535:
            raise QueueServiceError("agent TLS server endpoint is invalid")
        if not self.credential_fingerprints:
            raise QueueServiceError("agent TLS credential map is required")
        for fingerprint, credential in self.credential_fingerprints.items():
            if len(fingerprint) != 64 or any(
                char not in "0123456789abcdef" for char in fingerprint
            ):
                raise QueueServiceError("TLS certificate fingerprint is invalid")
            if not credential:
                raise QueueServiceError("TLS credential ID is invalid")


@dataclass(frozen=True, slots=True)
class AgentTlsClientConfig:
    url: str
    server_ca_path: Path
    certificate_path: Path
    private_key_path: Path
    agent_root: Path | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise QueueServiceError("agent TLS URL is invalid") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or (port is not None and not 1 <= port <= 65535)
            or parsed.path not in ("", "/")
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
        ):
            raise QueueServiceError("agent TLS URL must be one HTTPS service identity")


class _RemoteAgentJournal:
    """The outbound agent's private, replayable session evidence.

    This intentionally lives with the HTTP caller, never under the coordinator
    daemon's configured local-agent root.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        if not self._root.is_dir():
            raise QueueServiceError("remote agent root is missing")
        details = self._root.stat()
        if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
            raise QueueServiceError("remote agent root must be owner-permissioned")
        self._path = self._root / "control.sqlite"
        if not self._path.is_file() or stat.S_IMODE(self._path.stat().st_mode) & 0o077:
            raise QueueServiceError("remote agent control state is unavailable")
        try:
            with self._connection() as conn:
                if int(conn.execute("PRAGMA user_version").fetchone()[0]) != 2:
                    raise QueueServiceError("remote agent root schema is unsupported")
                metadata = {
                    str(row[0]): str(row[1])
                    for row in conn.execute("SELECT key, value FROM root_metadata")
                }
                if metadata.get("role") != "local-agent" or not metadata.get(
                    "stable_id"
                ):
                    raise QueueServiceError("remote agent root identity is invalid")
                validate_agent_session_schema(conn, coordinator=False)
        except QueueError:
            raise
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise QueueServiceError(
                "remote agent control state is unavailable"
            ) from exc
        self.root_id = metadata["stable_id"]
        self._lock = (self._root / "owner.lock").open("a+", encoding="utf-8")
        (self._root / "owner.lock").chmod(0o600)
        try:
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lock.close()
            raise QueueServiceError("remote agent root is already locked") from exc

    def close(self) -> None:
        self._lock.close()

    def _connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            f"{self._path.resolve().as_uri()}?mode=rw", uri=True, timeout=30
        )
        conn.row_factory = sqlite3.Row
        return conn

    def persist_registration_intent(self, request: AgentRegistration) -> None:
        if request.agent_root_id != self.root_id:
            raise QueueConflictError("registration does not match the agent root")
        value = request.value()
        digest = _canonical_digest(value)
        encoded = _canonical_json(value)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT digest FROM agent_registration_intents WHERE operation_id = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO agent_registration_intents(operation_id, digest, request_json, result_json) VALUES (?, ?, ?, NULL)",
                    (request.idempotency_key, digest, encoded),
                )
            elif str(row["digest"]) != digest:
                raise QueueConflictError(
                    "idempotency key was reused with different content"
                )
            conn.commit()

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
                "SELECT digest, result_json FROM agent_registration_intents WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None or str(row["digest"]) != digest:
                raise QueueConflictError("agent registration intent is not durable")
            if row["result_json"] is not None and str(row["result_json"]) != encoded:
                raise QueueConflictError(
                    "registration replay returned a different session"
                )
            current = conn.execute(
                "SELECT value_json, state FROM agent_sessions_local WHERE session_id = ?",
                (session.session_id,),
            ).fetchone()
            if current is not None and (
                str(current["state"]) != AgentSessionState.ACTIVE.value
                or str(current["value_json"]) != encoded
            ):
                raise QueueConflictError(
                    "registration cannot replace durable session evidence"
                )
            conn.execute(
                "UPDATE agent_registration_intents SET result_json = ? WHERE operation_id = ?",
                (encoded, operation_id),
            )
            conn.execute(
                "INSERT INTO agent_sessions_local(session_id, value_json, state) VALUES (?, ?, ?) ON CONFLICT(session_id) DO NOTHING",
                (session.session_id, encoded, session.state.value),
            )
            conn.commit()

    def session(self, session_id: str) -> AgentSession:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value_json, state FROM agent_sessions_local WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None or str(row["state"]) != AgentSessionState.ACTIVE.value:
            raise QueueServiceError("remote agent session evidence is unavailable")
        value = json.loads(str(row["value_json"]))
        if not isinstance(value, Mapping):
            raise QueueServiceError("remote agent session evidence is invalid")
        return _session_from_value(cast(Mapping[str, PlainData], value))

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

    def prepare_offer(self, offer: AgentOffer, operation_id: str) -> None:
        session = self.session(offer.session_id)
        if (
            offer.coordinator_epoch != session.coordinator_epoch
            or offer.config_revision != session.config_revision
            or offer.inventory_revision != session.inventory_revision
            or offer.availability_revision != session.availability_revision
            or offer.pools != session.pools
        ):
            raise QueueConflictError("offer does not match the durable agent session")
        self._persist_mutation("offer", operation_id, offer.value())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO agent_offers_local(session_id, availability_revision, state) VALUES (?, ?, 'PENDING') ON CONFLICT(session_id) DO UPDATE SET availability_revision = excluded.availability_revision, state = 'PENDING'",
                (offer.session_id, offer.availability_revision),
            )
            conn.commit()

    def prepare_poll(
        self,
        session_id: str,
        availability_revision: str,
        poll_id: str,
        request: Mapping[str, PlainData],
    ) -> None:
        session = self.session(session_id)
        if session.availability_revision != availability_revision:
            raise QueueConflictError("poll does not match the durable agent session")
        self._persist_mutation("poll", poll_id, request)
        with self._connection() as conn:
            current = conn.execute(
                "SELECT poll_id, state FROM agent_polls_local WHERE session_id = ? AND availability_revision = ?",
                (session_id, availability_revision),
            ).fetchone()
            if (
                current is not None
                and str(current["state"]) == "PENDING"
                and str(current["poll_id"]) != poll_id
            ):
                raise QueueConflictError("agent already has a pending work poll")
            conn.execute(
                "INSERT INTO agent_polls_local(session_id, availability_revision, poll_id, state) VALUES (?, ?, ?, 'PENDING') ON CONFLICT(session_id, availability_revision) DO UPDATE SET poll_id = excluded.poll_id, state = 'PENDING'",
                (session_id, availability_revision, poll_id),
            )
            conn.commit()

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
            if row["result_json"] is not None and str(row["result_json"]) != encoded:
                raise QueueConflictError("mutation replay returned a different result")
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
                conn.execute(
                    "UPDATE agent_offers_local SET state = 'ACTIVE' WHERE session_id = ?",
                    (session_id,),
                )
            elif operation == "poll":
                conn.execute(
                    "UPDATE agent_polls_local SET state = 'WAIT' WHERE poll_id = ?",
                    (operation_id,),
                )
            conn.commit()

    def fence_poll(self, poll_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE agent_polls_local SET state = 'FENCED' WHERE poll_id = ?",
                (poll_id,),
            )
            conn.commit()

    def fence_and_prove_empty(self, session_id: str) -> AgentRetirementProof:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT value_json, state FROM agent_sessions_local WHERE session_id = ?",
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
            conn.execute(
                "UPDATE agent_sessions_local SET state = ? WHERE session_id = ?",
                (AgentSessionState.RETIRING.value, session_id),
            )
            conn.execute(
                "UPDATE agent_offers_local SET state = 'FENCED' WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "UPDATE agent_polls_local SET state = 'FENCED' WHERE session_id = ?",
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
            )
            conn.execute(
                "INSERT INTO agent_retirement_proofs_local(session_id, proof_json) VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET proof_json = excluded.proof_json",
                (session_id, _canonical_json(proof.value())),
            )
            conn.commit()
        return proof

    def persist_retired(self, session_id: str) -> None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM agent_sessions_local WHERE session_id = ?",
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
                "UPDATE agent_sessions_local SET value_json = ?, state = ? "
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


class LocalDaemonAgentHttpServer:
    """Loopback/deployment server; it exposes no inbound agent listener."""

    def __init__(self, daemon: LocalDaemon, config: AgentTlsServerConfig) -> None:
        self._daemon = daemon
        self._config = config
        self._server: _MutualTlsHttpServer | None = None
        self._thread: Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise QueueServiceError("agent TLS server is not started")
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._server is not None:
            raise QueueServiceError("agent TLS server is already started")
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(
            self._config.certificate_path, self._config.private_key_path
        )
        context.load_verify_locations(cafile=self._config.client_ca_path)
        server = _MutualTlsHttpServer(
            (self._config.host, self._config.port),
            context,
            self._daemon,
            dict(self._config.credential_fingerprints),
        )
        self._server = server
        self._thread = Thread(
            target=server.serve_forever, daemon=True, name="loom-agent-mtls"
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None


class LocalDaemonAgentHttpClient:
    """A no-redirect persistent HTTPS caller for one configured service name."""

    def __init__(self, config: AgentTlsClientConfig) -> None:
        self._config = config
        self._connection: http.client.HTTPSConnection | None = None
        self._journal = (
            _RemoteAgentJournal(config.agent_root) if config.agent_root else None
        )

    @property
    def agent_root_id(self) -> str:
        return self._require_journal().root_id

    def close(self) -> None:
        self._close_connection()
        if self._journal is not None:
            self._journal.close()
            self._journal = None

    def _close_connection(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None

    def handshake(self, *, role: str = "agent") -> Mapping[str, PlainData]:
        if role not in {"agent", "client", "operator"}:
            raise QueueServiceError("authenticated application role is invalid")
        return self._call("handshake", {}, role=role)

    def register(self, request: AgentRegistration) -> AgentSession:
        journal = self._require_journal()
        journal.persist_registration_intent(request)
        session = _session_from_value(self._call("register", request.value()))
        journal.persist_session(request.idempotency_key, request.value(), session)
        return session

    def reconcile(
        self,
        session_id: str,
        coordinator_epoch: str,
        *,
        idempotency_key: str,
    ) -> AgentSession:
        journal = self._require_journal()
        expected = journal.session(session_id)
        request: dict[str, PlainData] = {
            "expected": expected.value(),
            "coordinator_epoch": coordinator_epoch,
            "idempotency_key": idempotency_key,
        }
        journal._persist_mutation("reconcile", idempotency_key, request)
        session = _session_from_value(self._call("reconcile", request))
        journal.complete_mutation("reconcile", idempotency_key, session.value())
        journal.persist_reconciled_session(session)
        return session

    def publish_offer(
        self, offer: AgentOffer, *, idempotency_key: str
    ) -> Mapping[str, PlainData]:
        journal = self._require_journal()
        journal.prepare_offer(offer, idempotency_key)
        result = self._call(
            "offer", {"offer": offer.value(), "idempotency_key": idempotency_key}
        )
        journal.complete_mutation("offer", idempotency_key, result)
        return result

    def wait_for_work(
        self,
        session_id: str,
        availability_revision: str,
        *,
        poll_id: str,
        wait_timeout_ms: int,
    ) -> Mapping[str, PlainData]:
        value: dict[str, PlainData] = {
            "session_id": session_id,
            "availability_revision": availability_revision,
            "poll_id": poll_id,
            "wait_timeout_ms": wait_timeout_ms,
        }
        journal = self._require_journal()
        journal.prepare_poll(session_id, availability_revision, poll_id, value)
        try:
            result = self._call("poll", value)
        except AgentPollActiveError:
            # The original held request still owns this exact poll identity.
            # Preserve the local intent so the same identity can be retried.
            raise
        except QueueConflictError:
            journal.fence_poll(poll_id)
            raise
        except _IndeterminateAgentProtocolError:
            raise
        except QueueServiceError:
            journal.fence_poll(poll_id)
            raise
        journal.complete_mutation("poll", poll_id, result)
        return result

    def retire_clean(
        self, session_id: str, *, idempotency_key: str
    ) -> Mapping[str, PlainData]:
        journal = self._require_journal()
        proof = journal.fence_and_prove_empty(session_id)
        request: dict[str, PlainData] = {
            "proof": proof.value(),
            "idempotency_key": idempotency_key,
        }
        journal._persist_mutation("retire", idempotency_key, request)
        result = self._call("retire", request)
        journal.complete_mutation("retire", idempotency_key, result)
        journal.persist_retired(session_id)
        return result

    def _require_journal(self) -> "_RemoteAgentJournal":
        if self._journal is None:
            raise QueueServiceError("remote agent durable journal is required")
        return self._journal

    def call_application(
        self, role: str, operation: str, value: Mapping[str, PlainData]
    ) -> Mapping[str, PlainData]:
        """Call the authenticated client/operator view selected by its certificate."""
        if role not in {"client", "operator"}:
            raise QueueServiceError("authenticated application role is invalid")
        return self._call(operation, value, role=role)

    def _call(
        self, operation: str, value: Mapping[str, PlainData], *, role: str = "agent"
    ) -> Mapping[str, PlainData]:
        parsed = urlsplit(self._config.url)
        assert parsed.hostname is not None
        context = ssl.create_default_context(cafile=self._config.server_ca_path)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            self._config.certificate_path, self._config.private_key_path
        )
        connection = self._connection
        if connection is None:
            connection = http.client.HTTPSConnection(
                parsed.hostname,
                parsed.port or 443,
                context=context,
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            self._connection = connection
        body = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        try:
            connection.request(
                "POST",
                f"/v1/{role}/{operation}",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            raw = response.read(_MAX_BODY_BYTES + 1)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            self._close_connection()
            raise _IndeterminateAgentProtocolError(
                "agent protocol outcome is indeterminate"
            ) from exc
        if len(raw) > _MAX_BODY_BYTES:
            self._close_connection()
            raise _IndeterminateAgentProtocolError(
                "agent protocol outcome is indeterminate"
            )
        try:
            payload = _decode(raw)
        except QueueError as exc:
            self._close_connection()
            raise _IndeterminateAgentProtocolError(
                "agent protocol outcome is indeterminate"
            ) from exc
        if response.status == 409:
            self._close_connection()
            if payload.get("error") == "agent_poll_active":
                raise AgentPollActiveError("work poll is already active")
            raise QueueConflictError("agent protocol conflict")
        if response.status >= 500:
            self._close_connection()
            raise _IndeterminateAgentProtocolError(
                "agent protocol outcome is indeterminate"
            )
        if response.status != 200 or payload.get("ok") is not True:
            self._close_connection()
            code = payload.get("error")
            raise QueueServiceError(
                str(code) if isinstance(code, str) else "agent protocol request failed"
            )
        result = payload.get("result")
        if not isinstance(result, Mapping):
            self._close_connection()
            raise _IndeterminateAgentProtocolError(
                "agent protocol outcome is indeterminate"
            )
        return freeze_plain_data(result, path="agent HTTP response")


class _MutualTlsHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        context: ssl.SSLContext,
        daemon: LocalDaemon,
        credential_fingerprints: Mapping[str, str],
    ) -> None:
        self._context = context
        self.daemon_owner = daemon
        self.credential_fingerprints = credential_fingerprints
        super().__init__(address, _Handler)

    def get_request(self) -> tuple[ssl.SSLSocket, tuple[str, int]]:
        connection, address = super().get_request()
        try:
            return self._context.wrap_socket(connection, server_side=True), address
        except Exception:
            connection.close()
            raise


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def _daemon_server(self) -> _MutualTlsHttpServer:
        return cast(_MutualTlsHttpServer, self.server)

    def log_message(self, format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        try:
            certificate = cast(ssl.SSLSocket, self.connection).getpeercert(
                binary_form=True
            )
            if certificate is None:
                raise QueueServiceError("agent TLS peer is unavailable")
            fingerprint = hashlib.sha256(certificate).hexdigest()
            credential = self._daemon_server.credential_fingerprints.get(fingerprint)
            if credential is None:
                raise QueueServiceError("agent TLS credential is not accepted")
            principal_id, mapped_role = ScopedAuthorizer(
                self._daemon_server.daemon_owner._agent_policy
            ).transport_principal(credential)
            if self.headers.get("Content-Type") != "application/json":
                raise QueueServiceError("agent protocol content type is invalid")
            lengths = self.headers.get_all("Content-Length", [])
            length = lengths[0] if len(lengths) == 1 else None
            if (
                self.headers.get("Transfer-Encoding") is not None
                or length is None
                or not length.isdecimal()
                or int(length) > _MAX_BODY_BYTES
            ):
                raise QueueServiceError("agent protocol body is invalid")
            payload = _decode(self.rfile.read(int(length)))
            segments = self.path.split("/")
            if len(segments) != 4 or segments[0] or segments[1] != "v1":
                raise QueueServiceError("agent protocol operation is unsupported")
            role_name, operation = segments[2:]
            if role_name != mapped_role:
                raise QueueServiceError("agent TLS credential is not authorized")
            principal = LocalDaemonPrincipal(
                principal_id, LocalDaemonRole(mapped_role), credential
            )
            if role_name == "agent":
                if operation not in {
                    "handshake",
                    "register",
                    "reconcile",
                    "offer",
                    "poll",
                    "retire",
                }:
                    raise QueueServiceError("agent protocol operation is unsupported")
                result = _dispatch(
                    self._daemon_server.daemon_owner.agent_view(principal),
                    operation,
                    payload,
                )
            else:
                result = _dispatch_application(
                    self._daemon_server.daemon_owner,
                    principal,
                    role_name,
                    operation,
                    payload,
                )
            self._reply(200, {"ok": True, "result": result})
        except AgentPollActiveError:
            self._reply(409, {"ok": False, "error": "agent_poll_active"})
        except QueueConflictError:
            self._reply(409, {"ok": False, "error": "agent_protocol_conflict"})
        except QueueError:
            self._reply(403, {"ok": False, "error": "agent_protocol_rejected"})
        except Exception:
            self._reply(500, {"ok": False, "error": "agent_protocol_indeterminate"})

    def _reply(self, status: int, payload: Mapping[str, object]) -> None:
        body = json.dumps(
            thaw_plain_data(payload, path="agent HTTP response"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if status != 200:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)


def _dispatch(
    view: Any, operation: str, value: Mapping[str, object]
) -> Mapping[str, PlainData]:
    if operation == "handshake":
        _exact(value, set())
        return view.handshake()
    if operation == "register":
        return view.register(_registration(value)).value()
    if operation == "reconcile":
        _exact(value, {"expected", "coordinator_epoch", "idempotency_key"})
        expected = value["expected"]
        if not isinstance(expected, Mapping):
            raise QueueServiceError("agent reconciliation evidence is invalid")
        return view.reconcile(
            _session_from_value(cast(Mapping[str, PlainData], expected)),
            _string(value, "coordinator_epoch"),
            idempotency_key=_string(value, "idempotency_key"),
        ).value()
    if operation == "offer":
        _exact(value, {"offer", "idempotency_key"})
        offer = value["offer"]
        if not isinstance(offer, Mapping):
            raise QueueServiceError("agent offer is invalid")
        return view.publish_offer(
            _offer(offer), idempotency_key=_string(value, "idempotency_key")
        )
    if operation == "poll":
        _exact(
            value,
            {"session_id", "availability_revision", "poll_id", "wait_timeout_ms"},
        )
        return view.wait_for_work(
            _string(value, "session_id"),
            _string(value, "availability_revision"),
            poll_id=_string(value, "poll_id"),
            wait_timeout_ms=_integer(value, "wait_timeout_ms"),
        )
    _exact(value, {"proof", "idempotency_key"})
    proof = value["proof"]
    if not isinstance(proof, Mapping):
        raise QueueServiceError("agent retirement proof is invalid")
    return view.retire_clean(
        _retirement_proof(proof),
        idempotency_key=_string(value, "idempotency_key"),
    )


def _dispatch_application(
    daemon: LocalDaemon,
    principal: LocalDaemonPrincipal,
    role: str,
    operation: str,
    value: Mapping[str, object],
) -> Mapping[str, PlainData]:
    if operation == "handshake":
        _exact(value, set())
        daemon._require_view_role(principal, LocalDaemonRole(role))
        return freeze_plain_data(
            {
                "protocol_version": "1",
                "capabilities": ["authenticated-application-v1"],
                "coordinator_id": daemon._require_started(),
                "coordinator_epoch": daemon._epoch or "",
                "role": role,
            },
            path="authenticated application handshake",
        )
    if role == "client":
        view = daemon.client_view(principal)
        if operation == "status":
            _exact(value, set())
            return view.status().to_dict()
        if operation == "cancel":
            _exact(value, {"queue_item_id"})
            return view.cancel(_string(value, "queue_item_id")).to_dict()
        if operation == "submit":
            request = value.get("request")
            if not isinstance(request, Mapping):
                raise QueueServiceError("client admission request is invalid")
            return view.submit(LocalDaemonAdmissionRequest.from_dict(request)).to_dict()
    elif role == "operator":
        view = daemon.operator_view(principal)
        if operation == "status":
            _exact(value, set())
            return view.status().to_dict()
        if operation == "reconcile":
            _exact(value, set())
            return {
                "admissions": [
                    admission.to_dict() for admission in view.reconcile_once()
                ]
            }
    raise QueueServiceError("daemon protocol operation is unsupported")


def _registration(value: Mapping[str, object]) -> AgentRegistration:
    _exact(
        value,
        {
            "idempotency_key",
            "coordinator_id",
            "coordinator_epoch",
            "agent_root_id",
            "config_revision",
            "inventory_revision",
            "availability_revision",
            "declared_pools",
            "declared_capabilities",
            "session_id",
        },
    )
    capabilities = value["declared_capabilities"]
    pools = value["declared_pools"]
    if (
        not isinstance(capabilities, list)
        or any(not isinstance(item, str) for item in capabilities)
        or not isinstance(pools, list)
        or any(not isinstance(item, str) for item in pools)
    ):
        raise QueueServiceError("agent registration scope is invalid")
    session_id = value["session_id"]
    if session_id is not None and not isinstance(session_id, str):
        raise QueueServiceError("agent session ID is invalid")
    return AgentRegistration(
        idempotency_key=_string(value, "idempotency_key"),
        coordinator_id=_string(value, "coordinator_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        agent_root_id=_string(value, "agent_root_id"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        availability_revision=_string(value, "availability_revision"),
        declared_pools=tuple(pools),
        declared_capabilities=tuple(capabilities),
        session_id=session_id,
    )


def _offer(value: Mapping[str, object]) -> AgentOffer:
    _exact(
        value,
        {
            "session_id",
            "coordinator_epoch",
            "config_revision",
            "inventory_revision",
            "availability_revision",
            "capacity_atoms",
            "ttl_seconds",
            "pools",
            "reflected_claim_ids",
        },
    )
    claims = value["reflected_claim_ids"]
    pools = value["pools"]
    if (
        not isinstance(claims, list)
        or any(not isinstance(item, str) for item in claims)
        or not isinstance(pools, list)
        or any(not isinstance(item, str) for item in pools)
    ):
        raise QueueServiceError("agent offer scope is invalid")
    cpu, memory = _capacity_atoms(value["capacity_atoms"])
    return AgentOffer(
        session_id=_string(value, "session_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        availability_revision=_string(value, "availability_revision"),
        cpu=cpu,
        memory_bytes=memory,
        ttl_seconds=_integer(value, "ttl_seconds"),
        pools=tuple(pools),
        reflected_claim_ids=tuple(claims),
    )


def _capacity_atoms(value: object) -> tuple[int, int]:
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        raise QueueServiceError("agent capacity atoms are invalid")
    quantities: dict[str, int] = {}
    expected = {
        "cpu": ("cpu", "count"),
        "memory": ("memory", "byte"),
    }
    for item in value:
        if not isinstance(item, Mapping):
            raise QueueServiceError("agent capacity atom is invalid")
        _exact(
            item,
            {
                "owner_resource_kind",
                "local_capacity_key",
                "amount",
                "unit",
                "granularity",
            },
        )
        kind = _string(item, "owner_resource_kind")
        if kind not in expected or kind in quantities:
            raise QueueServiceError("agent capacity atom namespace is invalid")
        local_key, unit = expected[kind]
        if (
            _string(item, "local_capacity_key") != local_key
            or _string(item, "unit") != unit
        ):
            raise QueueServiceError("agent capacity atom descriptor is invalid")
        amount = _exact_integer_quantity(item["amount"], "amount")
        granularity = _exact_integer_quantity(item["granularity"], "granularity")
        if amount <= 0 or granularity != 1:
            raise QueueServiceError("agent capacity atom quantity is invalid")
        quantities[kind] = amount
    return quantities.get("cpu", 0), quantities.get("memory", 0)


def _exact_integer_quantity(value: object, name: str) -> int:
    if not isinstance(value, Mapping):
        raise QueueServiceError(f"agent capacity atom {name} is invalid")
    _exact(value, {"numerator", "denominator"})
    numerator = _integer(value, "numerator")
    denominator = _integer(value, "denominator")
    if denominator != 1:
        raise QueueServiceError(f"agent capacity atom {name} must be integral")
    return numerator


def _retirement_proof(value: Mapping[str, object]) -> AgentRetirementProof:
    _exact(
        value,
        {
            "session_id",
            "coordinator_id",
            "coordinator_epoch",
            "agent_id",
            "agent_root_id",
            "policy_revision",
            "config_revision",
            "inventory_revision",
            "availability_revision",
            "reference_revision",
            "reference_digest",
        },
    )
    return AgentRetirementProof(
        session_id=_string(value, "session_id"),
        coordinator_id=_string(value, "coordinator_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        agent_id=_string(value, "agent_id"),
        agent_root_id=_string(value, "agent_root_id"),
        policy_revision=_string(value, "policy_revision"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        availability_revision=_string(value, "availability_revision"),
        reference_revision=_integer(value, "reference_revision"),
        reference_digest=_string(value, "reference_digest"),
    )


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise QueueServiceError(f"agent protocol {key} is invalid")
    return item


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise QueueServiceError(f"agent protocol {key} is invalid")
    return item


def _exact(value: Mapping[str, object], fields: set[str]) -> None:
    if set(value) != fields:
        raise QueueServiceError("agent protocol fields are invalid")


def _decode(raw: bytes) -> Mapping[str, object]:
    if len(raw) > _MAX_BODY_BYTES:
        raise QueueServiceError("agent protocol body is too large")
    try:
        value = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise QueueServiceError("agent protocol JSON is invalid") from exc
    if not isinstance(value, Mapping):
        raise QueueServiceError("agent protocol body is not an object")
    _bounded_json(value, depth=0)
    return value


def _bounded_json(value: object, *, depth: int) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise QueueServiceError("agent protocol JSON is too deeply nested")
    if isinstance(value, Mapping):
        if len(value) > _MAX_JSON_COLLECTION:
            raise QueueServiceError("agent protocol object is too large")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 160:
                raise QueueServiceError("agent protocol object key is invalid")
            _bounded_json(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > _MAX_JSON_COLLECTION:
            raise QueueServiceError("agent protocol collection is too large")
        for item in value:
            _bounded_json(item, depth=depth + 1)
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise QueueServiceError("agent protocol JSON value is invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON key")
    return value


def _reject_constant(_value: str) -> object:
    raise ValueError("non-finite JSON value")


__all__ = [
    "AgentTlsClientConfig",
    "AgentTlsServerConfig",
    "LocalDaemonAgentHttpClient",
    "LocalDaemonAgentHttpServer",
]
