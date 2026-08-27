"""Small mutual-TLS adapter for the restricted agent-session view.

The adapter derives a configured credential ID from the verified client
certificate's DER fingerprint.  It never accepts an actor, principal, agent,
or session selector from the HTTP path as transport identity.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import sqlite3
import ssl
import stat
from threading import RLock, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic, sleep
from typing import Any, cast
from urllib.parse import urlsplit

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.queue._managed_local import (
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ManagedAssignment,
    ObserveRequest,
    ProviderReleaseEvidence,
    SQLiteAgentJournal,
    GpuResourceProvider,
    _cancelled_worker_result,
    _configured_provider_descriptor,
)
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.runtime import CpuResourcePlanner, MemoryResourcePlanner
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.scheduling import SchedulingComponentDescriptor

from .agent_sessions import (
    AgentAssignmentControl,
    AgentOffer,
    AgentProviderReleaseProof,
    AgentControl,
    AgentControlEffect,
    AgentPollActiveError,
    AgentRegistration,
    AgentRetirementProof,
    AgentSession,
    AgentSessionState,
    SessionReplacementRequest,
    AgentTransferAuthorizationStaleError,
    PROTOCOL_VERSION,
    ScopedAuthorizer,
    _SESSION_REFERENCE_KINDS,
    _managed_containment_evidence,
    _session_from_value,
    validate_agent_session_schema,
)
from ._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY,
    REMOTE_EXECUTION_CAPABILITY,
    ResidentExecutionProfile,
    _ResidentAssignmentBundle,
    _ResidentAssignmentWorkspace,
    _RemoteExecutionReport,
    _decode_chunk,
    _encode_chunk,
)
from ._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    AgentProcessSupervisorService,
    ResidentWorkerLaunch,
    SupervisorLaunchConfiguration,
    SupervisorReceipt,
    SupervisorLaunchState,
    _launch_from_value,
    _launch_value,
)
from .errors import QueueConflictError, QueueError, QueueServiceError
from .local_daemon import (
    CoordinatorSchedulingReload,
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    RecoverUnknownAssignment,
)


_MAX_BODY_BYTES = 65_536
_MAX_JSON_DEPTH = 8
_MAX_JSON_COLLECTION = 64
_HTTP_TIMEOUT_SECONDS = 10
_ASSIGNMENT_RECONCILIATION_SECONDS = 60
_MAX_TRANSFER_AUTHORIZATION_RENEWALS = 64


def _supervisor_containment_evidence(
    receipt: SupervisorReceipt, *, agent_id: str
) -> Mapping[str, PlainData]:
    """Serialize the exact persisted process-owner receipt without paths."""

    launch = receipt.launch
    return _managed_containment_evidence(
        {
            "kind": "managed_supervisor",
            "state": "CONTAINED",
            "supervisor_id": launch.supervisor_id,
            "continuity_epoch": launch.continuity_epoch,
            "agent_id": agent_id,
            "supervisor_agent_id": launch.agent_id,
            "session_id": launch.session_id,
            "assignment_id": launch.assignment_id,
            "process_execution_id": launch.process_execution_id,
            "execution_fence": launch.execution_fence,
            "launch_operation_id": launch.launch_operation_id,
            "launch_spec_digest": launch.spec_digest,
            "supervisor_revision": receipt.supervisor_revision,
            "worker_result_digest": receipt.worker_result_digest,
        }
    )


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
    resident_profiles: tuple[ResidentExecutionProfile, ...] = ()

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
        profiles = tuple(self.resident_profiles)
        if any(not isinstance(item, ResidentExecutionProfile) for item in profiles):
            raise QueueServiceError("agent resident profiles are invalid")
        if len({item.descriptor.profile_id for item in profiles}) != len(profiles):
            raise QueueServiceError("agent resident profile IDs must be unique")
        capacity_domains = {
            (
                item.cpu_capacity,
                item.memory_capacity_bytes,
                tuple(device.descriptor for device in item.gpu_devices),
            )
            for item in profiles
        }
        if len(capacity_domains) > 1:
            raise QueueServiceError(
                "agent resident profiles must share one capacity domain"
            )
        if profiles and self.agent_root is None:
            raise QueueServiceError("resident execution requires an agent root")
        object.__setattr__(self, "resident_profiles", profiles)


def _resident_provider_descriptors(
    profile: ResidentExecutionProfile,
    agent_id: str,
    *,
    resource_kinds: set[str] | None = None,
) -> tuple[SchedulingComponentDescriptor, ...]:
    """Derive safe provider identities from one protected resident profile."""

    atoms = profile.capacity_atoms(agent_id)
    kinds = resource_kinds or {atom.owner_resource_kind for atom in atoms}
    result: list[SchedulingComponentDescriptor] = []
    for kind in sorted(kinds):
        provider_atoms = tuple(
            atom for atom in atoms if atom.owner_resource_kind == kind
        )
        bindings: Mapping[str, str] | None = None
        if kind == "gpu":
            bindings = {
                f"{agent_id}:{device.descriptor.device_id}": device.binding_value
                for device in profile.gpu_devices
                if device.descriptor.healthy
            }
            provider_atoms = tuple(
                atom for atom in provider_atoms if atom.local_capacity_key in bindings
            )
        result.append(
            _configured_provider_descriptor(kind, provider_atoms, bindings=bindings)
        )
    return tuple(result)


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
                if int(conn.execute("PRAGMA user_version").fetchone()[0]) != 7:
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
                poll_result = result.get("result")
                if poll_result == "assignment":
                    request_value = result.get("request")
                    request = _ResidentAssignmentBundle.from_dict(request_value)
                    poll_request = json.loads(str(row["request_json"]))
                    if not isinstance(poll_request, Mapping):
                        raise QueueServiceError("agent poll intent is invalid")
                    request_session = poll_request.get("session_id")
                    if not isinstance(request_session, str):
                        raise QueueServiceError("agent poll intent is invalid")
                    conn.execute(
                        "INSERT INTO agent_session_references(session_id, "
                        "reference_kind, reference_id, resolved) "
                        "VALUES (?, 'delivery', ?, 0) ON CONFLICT(session_id, "
                        "reference_kind, reference_id) DO NOTHING",
                        (request_session, request.assignment_id),
                    )
                    poll_state = "DELIVERED"
                elif poll_result == "wait":
                    poll_state = "WAIT"
                else:
                    raise QueueServiceError("agent poll result is invalid")
                conn.execute(
                    "UPDATE agent_polls_local SET state = ? WHERE poll_id = ?",
                    (poll_state, operation_id),
                )
            conn.commit()

    def fence_poll(self, poll_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE agent_polls_local SET state = 'FENCED' WHERE poll_id = ?",
                (poll_id,),
            )
            conn.commit()

    def prepare_control(self, control: AgentControl) -> AgentControlEffect | None:
        """Persist delivery and withdrawal before applying owner-local effects."""

        encoded = _canonical_json(control.value())
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json, effect_json FROM agent_controls_local "
                "WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            if row is not None:
                if str(row["request_json"]) != encoded:
                    raise QueueConflictError("agent control operation conflicts")
                if row["effect_json"] is not None:
                    conn.commit()
                    value = json.loads(str(row["effect_json"]))
                    if not isinstance(value, Mapping):
                        raise QueueServiceError("agent control effect is invalid")
                    return AgentControlEffect.from_value(value)
            else:
                conn.execute(
                    "INSERT INTO agent_controls_local(operation_id, request_json, "
                    "effect_json, acknowledged) VALUES (?, ?, NULL, 0)",
                    (control.operation_id, encoded),
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
            if control.kind.value in {"drain", "reload"}:
                conn.execute(
                    "UPDATE agent_offers_local SET state = 'DRAINED' "
                    "WHERE session_id = ?",
                    (session.session_id,),
                )
                conn.execute(
                    "UPDATE agent_polls_local SET state = 'FENCED' "
                    "WHERE session_id = ?",
                    (session.session_id,),
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

    def has_unresolved_assignment_references(self) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_session_references WHERE "
                "reference_kind = 'delivery' AND resolved = 0 LIMIT 1"
            ).fetchone()
            pending_poll = conn.execute(
                "SELECT 1 FROM agent_polls_local WHERE state = 'PENDING' LIMIT 1"
            ).fetchone()
        return row is not None or pending_poll is not None

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
                secret,
            )
            conn.execute(
                "INSERT INTO agent_retirement_proofs_local(session_id, proof_json) VALUES (?, ?) ON CONFLICT(session_id) DO UPDATE SET proof_json = excluded.proof_json",
                (session_id, _canonical_json(proof.value())),
            )
            conn.commit()
        return proof

    def persist_retired(self, session_id: str, retirement_operation_id: str) -> None:
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

    def __init__(
        self,
        config: AgentTlsClientConfig,
        *,
        trusted_config_loader: Callable[[], AgentTlsClientConfig] | None = None,
    ) -> None:
        self._config = config
        self._trusted_config_loader = trusted_config_loader
        self._connection: http.client.HTTPSConnection | None = None
        # Validate the durable supervisor binding before acquiring the exclusive
        # root lock.  A rejected opening must not strand that lock.
        self._supervisor = self._open_supervisor(config)
        self._journal = (
            _RemoteAgentJournal(config.agent_root) if config.agent_root else None
        )
        self._profiles = {
            item.descriptor.profile_id: item for item in config.resident_profiles
        }
        self._retained_profiles: dict[str, ResidentExecutionProfile] = {}
        self._execution_journal = (
            SQLiteAgentJournal(
                Path(config.agent_root) / "journal.sqlite",
                _allow_initialize=False,
            )
            if config.agent_root is not None
            else None
        )
        if self._execution_journal is not None:
            self._execution_journal._open_existing()
        self._restart_with_retained_work = bool(
            self._execution_journal.retained_claim_commands()
            if self._execution_journal is not None
            else ()
        ) or bool(
            self._journal.has_unresolved_assignment_references()
            if self._journal is not None
            else False
        )
        self._runtime_agent_id: str | None = None
        self._runtime_provider_key: str | None = None
        self._providers: dict[str, AtomResourceProvider] = {}
        self._cancelled_assignments: set[str] = set(
            self._journal.contained_assignment_ids()
            if self._journal is not None
            else ()
        )
        self._drained = False
        self._control_lock = RLock()

    @property
    def agent_root_id(self) -> str:
        return self._require_journal().root_id

    @classmethod
    def initialize_agent_root(cls, config: AgentTlsClientConfig) -> None:
        """Create the complete remote root and its continuous private owner.

        Remote configuration is trusted application configuration, so this is
        the one place where the full resident profile set becomes durable.
        Opening an existing root never fills in or upgrades that identity.
        """
        if config.agent_root is None or not config.resident_profiles:
            raise QueueServiceError(
                "remote agent initialization requires resident profiles"
            )
        LocalDaemon.initialize_agent_root(config.agent_root)
        journal = _RemoteAgentJournal(config.agent_root)
        try:
            profiles = tuple(item.launch_profile for item in config.resident_profiles)
            configuration = SupervisorLaunchConfiguration(journal.root_id, profiles)
            AgentProcessSupervisorService.initialize(
                config.agent_root, configuration=configuration
            )
        except AgentProcessSupervisorError as exc:
            raise QueueServiceError(str(exc)) from exc
        finally:
            journal.close()

    @staticmethod
    def _open_supervisor(
        config: AgentTlsClientConfig,
    ) -> AgentProcessSupervisorClient | None:
        if not config.resident_profiles:
            if (
                config.agent_root is not None
                and (Path(config.agent_root).resolve() / "supervisor").exists()
            ):
                raise QueueServiceError(
                    "managed_supervisor_state_requires_reinitialization"
                )
            return None
        if config.agent_root is None:
            raise QueueServiceError("remote resident execution requires an agent root")
        # The journal verifies the root and serializes agent application use;
        # its stable ID is the configuration's hard-bound agent identity.
        root_id = _read_remote_agent_root_id(config.agent_root)
        try:
            return AgentProcessSupervisorClient(
                config.agent_root,
                SupervisorLaunchConfiguration(
                    root_id,
                    tuple(item.launch_profile for item in config.resident_profiles),
                ),
            )
        except AgentProcessSupervisorError as exc:
            raise QueueServiceError(str(exc)) from exc

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
        if role not in {"agent", "client", "operator", "slurm_bootstrap"}:
            raise QueueServiceError("authenticated application role is invalid")
        result = self._call("handshake", {}, role=role)
        if role == "agent":
            capabilities = result.get("capabilities")
            if (
                result.get("protocol_version") != PROTOCOL_VERSION
                or not isinstance(capabilities, Sequence)
                or isinstance(capabilities, (str, bytes))
                or any(not isinstance(item, str) for item in capabilities)
                or not {
                    "agent-sessions-v7",
                    REMOTE_EXECUTION_CAPABILITY,
                    REGULAR_FILE_RELAY_CAPABILITY,
                }.issubset(set(capabilities))
            ):
                raise QueueServiceError(
                    "agent coordinator protocol is unsupported; hard cut-over "
                    f"requires version {PROTOCOL_VERSION}"
                )
        return result

    def register(self, request: AgentRegistration) -> AgentSession:
        journal = self._require_journal()
        persisted = journal.persist_registration_intent(request)
        session = _session_from_value(self._call("register", persisted.value()))
        journal.persist_session(persisted.idempotency_key, persisted.value(), session)
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
        if self._drained:
            raise QueueConflictError("drained agent cannot advertise capacity")
        if self._restart_with_retained_work:
            raise QueueConflictError(
                "restarted agent with retained remote work cannot advertise "
                "executable capacity"
            )
        if offer.resident_profiles:
            local_descriptors = {
                profile.descriptor.profile_id: profile
                for profile in self._profiles.values()
            }
            if any(
                local_descriptors.get(descriptor.profile_id) is None
                or local_descriptors[descriptor.profile_id].descriptor != descriptor
                for descriptor in offer.resident_profiles
            ):
                raise QueueConflictError("offer names an unavailable resident profile")
            capacity = next(iter(local_descriptors.values()))
            if (
                offer.cpu > capacity.cpu_capacity
                or offer.memory_bytes > capacity.memory_capacity_bytes
                or tuple(
                    sorted(
                        (device.descriptor for device in capacity.gpu_devices),
                        key=lambda item: item.device_id,
                    )
                )
                != offer.gpu_devices
            ):
                raise QueueConflictError("offer exceeds the resident capacity domain")
            configured_gpu = {
                device.descriptor.device_id: device.descriptor.capacity_atom()
                for device in capacity.gpu_devices
            }
            if any(
                atom.local_capacity_key not in configured_gpu
                or atom.unit != configured_gpu[atom.local_capacity_key].unit
                or atom.granularity
                != configured_gpu[atom.local_capacity_key].granularity
                or atom.amount.fraction
                > configured_gpu[atom.local_capacity_key].amount.fraction
                for atom in offer.gpu_atoms
            ):
                raise QueueConflictError("offer exceeds the resident GPU capacity")
            expected_provider_descriptors = _resident_provider_descriptors(
                capacity,
                self._require_journal().session(offer.session_id).agent_id,
                resource_kinds={item.kind for item in offer.provider_descriptors},
            )
            if offer.provider_descriptors != expected_provider_descriptors:
                raise QueueConflictError(
                    "offer provider identity differs from resident configuration"
                )
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
        if self._drained:
            raise QueueConflictError("drained agent cannot poll for new work")
        if self._restart_with_retained_work:
            raise QueueConflictError(
                "restarted agent with retained remote work cannot poll for new work"
            )
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

    def poll_control(self, session_id: str) -> AgentControl | None:
        journal = self._require_journal()
        pending = journal.next_unacknowledged_control()
        if pending is not None:
            control, effect = pending
            if control.expected_session_id != session_id:
                raise QueueConflictError(
                    "retained agent control belongs to another session"
                )
            self._call(
                "control_ack",
                {"session_id": session_id, "effect": effect.value()},
            )
            journal.acknowledge_control(control.operation_id)
            return control
        result = self._call("control", {"session_id": session_id})
        raw = result.get("control")
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise QueueServiceError("agent control response is invalid")
        control = AgentControl.from_value(raw)
        effect = journal.prepare_control(control)
        if effect is None:
            effect = self._apply_agent_control(control)
            journal.record_control_effect(control, effect)
        self._call(
            "control_ack",
            {"session_id": session_id, "effect": effect.value()},
        )
        journal.acknowledge_control(control.operation_id)
        return control

    def _apply_agent_control(self, control: AgentControl) -> AgentControlEffect:
        """Apply an inert command using only trusted owner-local configuration."""

        session = self._require_journal().session(control.expected_session_id)
        with self._control_lock:
            if control.kind.value in {"drain", "reload"}:
                self._drained = True
            if control.cancel_active and not self._cancel_active_assignments():
                return self._unchanged_control_effect(control, session, "unknown_work")
            if control.kind.value == "reload":
                loader = self._trusted_config_loader
                if loader is None:
                    return self._unchanged_control_effect(
                        control, session, "reload_unavailable"
                    )
                try:
                    replacement = loader()
                    self._validate_reload_config(replacement)
                except (QueueError, OSError, TypeError, ValueError):
                    return self._unchanged_control_effect(
                        control, session, "reload_rejected"
                    )
                retained = self._has_retained_agent_work()
                if retained:
                    self._retained_profiles.update(
                        {
                            _resident_profile_key(item): item
                            for item in self._profiles.values()
                        }
                    )
                self._config = replacement
                self._profiles = {
                    item.descriptor.profile_id: item
                    for item in replacement.resident_profiles
                }
                if not retained:
                    self._reset_runtime_providers()
                config_revision = _agent_config_revision(replacement)
                inventory_revision = _agent_inventory_revision(replacement)
            else:
                config_revision = session.config_revision
                inventory_revision = session.inventory_revision
            if control.kind.value == "resume":
                if self._restart_with_retained_work or self._has_retained_agent_work():
                    return self._unchanged_control_effect(
                        control, session, "retained_work"
                    )
                self._retained_profiles.clear()
                self._reset_runtime_providers()
                self._drained = False
            availability_revision = _agent_revision(
                "availability",
                {
                    "operation_id": control.operation_id,
                    "drained": self._drained,
                    "inventory_revision": inventory_revision,
                },
            )
            return AgentControlEffect(
                operation_id=control.operation_id,
                code="applied",
                config_revision=config_revision,
                inventory_revision=inventory_revision,
                availability_revision=availability_revision,
            )

    @staticmethod
    def _unchanged_control_effect(
        control: AgentControl, session: AgentSession, code: str
    ) -> AgentControlEffect:
        return AgentControlEffect(
            operation_id=control.operation_id,
            code=code,
            config_revision=session.config_revision,
            inventory_revision=session.inventory_revision,
            availability_revision=session.availability_revision,
        )

    def _validate_reload_config(self, replacement: AgentTlsClientConfig) -> None:
        if not isinstance(replacement, AgentTlsClientConfig):
            raise QueueServiceError("trusted agent configuration is invalid")
        if (
            replacement.agent_root != self._config.agent_root
            or replacement.url != self._config.url
            or replacement.server_ca_path != self._config.server_ca_path
            or replacement.certificate_path != self._config.certificate_path
            or replacement.private_key_path != self._config.private_key_path
        ):
            raise QueueServiceError(
                "agent reload cannot replace its live transport or owner root"
            )
        if _resident_launch_profile_set(replacement) != _resident_launch_profile_set(
            self._config
        ):
            raise QueueConflictError(
                "agent reload requires fresh agent-root initialization for "
                "resident profile set"
            )
        existing = (*self._profiles.values(), *self._retained_profiles.values())
        for candidate in replacement.resident_profiles:
            for retained in existing:
                if (
                    retained.descriptor == candidate.descriptor
                    and _resident_profile_key(retained)
                    != _resident_profile_key(candidate)
                ):
                    raise QueueConflictError(
                        "agent reload reuses a live profile identity for changed bindings"
                    )

    def _has_retained_agent_work(self) -> bool:
        return bool(
            self._execution_journal.retained_claim_commands()
            if self._execution_journal is not None
            else ()
        ) or bool(
            self._journal.has_unresolved_assignment_references()
            if self._journal is not None
            else False
        )

    def _reset_runtime_providers(self) -> None:
        self._runtime_agent_id = None
        self._runtime_provider_key = None
        self._providers = {}

    def _cancel_active_assignments(self) -> bool:
        journal = self._journal
        supervisor = self._supervisor
        if journal is None or supervisor is None:
            return True
        all_contained = True
        for _, assignment_id in journal.unresolved_assignment_references():
            workspace = _ResidentAssignmentWorkspace(
                cast(Path, self._config.agent_root), assignment_id
            )
            encoded_launch = workspace.supervisor_launch_json()
            if encoded_launch is None:
                continue
            try:
                launch = _launch_from_value(json.loads(encoded_launch))
                supervisor.request_stop(launch)
                receipt = supervisor.contain(launch)
            except (AgentProcessSupervisorError, QueueError, ValueError):
                all_contained = False
                continue
            if receipt.state is not SupervisorLaunchState.CONTAINED:
                all_contained = False
                continue
            self._record_contained_cancellation(workspace)
        return all_contained

    def _record_contained_cancellation(
        self, workspace: _ResidentAssignmentWorkspace
    ) -> None:
        """Make a positive supervisor containment result restart-durable."""

        result_path = workspace.root / "worker-result.json"
        if not result_path.is_file():
            result = _cancelled_worker_result(workspace.worker_request())
            atomic_write_bytes(
                result_path,
                json.dumps(
                    result.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode(),
            )
        self._cancelled_assignments.add(workspace.assignment_id)

    def control_agent(self, control: AgentControl) -> Mapping[str, PlainData]:
        """Issue the same typed operator command over authenticated HTTP."""
        return self._call(
            "agent_control", {"control": control.value()}, role="operator"
        )

    def reload_scheduling(
        self, request: CoordinatorSchedulingReload
    ) -> Mapping[str, PlainData]:
        return self._call(
            "scheduling_reload", {"request": request.to_dict()}, role="operator"
        )

    def recover_unknown(
        self, request: RecoverUnknownAssignment
    ) -> Mapping[str, PlainData]:
        return self._call(
            "recover_unknown", {"request": request.to_dict()}, role="operator"
        )

    def replace_agent_session(
        self, request: SessionReplacementRequest
    ) -> Mapping[str, PlainData]:
        return self._call(
            "replace_agent_session", {"request": request.to_dict()}, role="operator"
        )

    def authorize_transfers(
        self,
        session_id: str,
        assignment_id: str,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> Mapping[str, PlainData]:
        return self._call(
            "authorize",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "expected_revision": expected_revision,
                "operation_id": operation_id,
            },
        )

    def read_input_chunk(
        self,
        session_id: str,
        assignment_id: str,
        transfer_id: str,
        *,
        offset: int,
        authorization_id: str,
        authorization_revision: int,
    ) -> tuple[bytes, int, bool]:
        result = self._call(
            "input",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "transfer_id": transfer_id,
                "offset": offset,
                "authorization_id": authorization_id,
                "authorization_revision": authorization_revision,
            },
        )
        data = _decode_chunk(result.get("data"))
        next_offset = result.get("next_offset")
        final = result.get("final")
        if (
            isinstance(next_offset, bool)
            or not isinstance(next_offset, int)
            or not isinstance(final, bool)
            or next_offset != offset + len(data)
        ):
            raise QueueServiceError("remote input chunk response is invalid")
        return data, next_offset, final

    def accept_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        request_digest: str,
    ) -> Mapping[str, PlainData]:
        return self._call(
            "accept",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "request_digest": request_digest,
            },
        )

    def start_permit(self, session_id: str, assignment_id: str, *, fence: str) -> bool:
        result = self._call(
            "start_permit",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
            },
        )
        permitted = result.get("permitted")
        if not isinstance(permitted, bool):
            raise QueueServiceError("remote start permit response is invalid")
        return permitted

    def poll_assignment_control(self, session_id: str) -> AgentAssignmentControl | None:
        journal = self._require_journal()
        pending = journal.next_unacknowledged_assignment_control()
        if pending is not None:
            control, code, evidence = pending
            if control.session_id != session_id:
                raise QueueConflictError(
                    "retained assignment control belongs to another session"
                )
            if code == "contained":
                self._cancelled_assignments.add(control.assignment_id)
            self._acknowledge_assignment_control(session_id, control, code, evidence)
            return control
        result = self._call("assignment_control", {"session_id": session_id})
        raw = result.get("control")
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise QueueServiceError("assignment control response is invalid")
        control = AgentAssignmentControl.from_value(raw)
        prior = journal.prepare_assignment_control(control)
        if prior is not None:
            code, evidence = prior
            self._acknowledge_assignment_control(session_id, control, code, evidence)
            return control
        code, evidence = self._apply_assignment_control(control)
        journal.record_assignment_control_result(control, code, evidence)
        self._acknowledge_assignment_control(session_id, control, code, evidence)
        return control

    def _acknowledge_assignment_control(
        self,
        session_id: str,
        control: AgentAssignmentControl,
        code: str,
        evidence: Mapping[str, PlainData] | None,
    ) -> None:
        self._call(
            "assignment_control_ack",
            {
                "session_id": session_id,
                "operation_id": control.operation_id,
                "code": code,
                "evidence": None if evidence is None else dict(evidence),
            },
        )
        self._require_journal().acknowledge_assignment_control(control.operation_id)

    def _apply_assignment_control(
        self, control: AgentAssignmentControl
    ) -> tuple[str, Mapping[str, PlainData] | None]:
        with self._control_lock:
            journal = self._execution_journal
            if journal is None:
                return "unknown", None
            try:
                state = journal.read_state(control.assignment_id)
                fence = journal.read_grant_fence(control.assignment_id)
            except Exception:
                return "unknown", None
            if control.fence != fence:
                return "unknown", None
            workspace = _ResidentAssignmentWorkspace(
                cast(Path, self._config.agent_root), control.assignment_id
            )
            encoded_launch = workspace.supervisor_launch_json()
            if encoded_launch is None:
                if state in {
                    AssignmentState.RESULT_DURABLE,
                    AssignmentState.TERMINAL_ACKNOWLEDGED,
                    AssignmentState.PROVIDERS_RELEASED,
                    AssignmentState.RELEASED,
                }:
                    return "terminal", None
                if state in {
                    AssignmentState.REQUEST_DURABLE,
                    AssignmentState.PREPARED,
                    AssignmentState.ACCEPTED,
                    AssignmentState.GRANTED,
                    AssignmentState.ACTIVE,
                }:
                    return "never_started", None
                return "unknown", None
            if control.process_execution_id not in {
                None,
                f"{control.assignment_id}:root",
            }:
                return "unknown", None
            if self._supervisor is None:
                return "unknown", None
            try:
                launch = _launch_from_value(json.loads(encoded_launch))
                if (
                    launch.assignment_id != control.assignment_id
                    or launch.session_id != control.session_id
                    or (
                        control.process_execution_id is not None
                        and launch.process_execution_id != control.process_execution_id
                    )
                    or launch.execution_fence != control.fence
                ):
                    return "unknown", None
                self._supervisor.request_stop(launch)
                contained = self._supervisor.contain(launch)
            except (AgentProcessSupervisorError, QueueError, ValueError):
                return "unknown", None
            if contained.state is not SupervisorLaunchState.CONTAINED:
                return "unknown", None
            self._record_contained_cancellation(workspace)
            target_agent_id = self._runtime_agent_id
            if target_agent_id is None:
                return "unknown", None
            return "contained", _supervisor_containment_evidence(
                contained, agent_id=target_agent_id
            )

    def decline_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        availability_revision: str,
    ) -> AgentSession:
        session = _session_from_value(
            self._call(
                "decline",
                {
                    "session_id": session_id,
                    "assignment_id": assignment_id,
                    "availability_revision": availability_revision,
                },
            )
        )
        journal = self._require_journal()
        journal.persist_reconciled_session(session)
        journal.resolve_assignment_reference(session_id, assignment_id)
        return session

    def confirm_started(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        process_execution_id: str,
    ) -> Mapping[str, PlainData]:
        return self._call(
            "started",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
                "process_execution_id": process_execution_id,
            },
        )

    def report_event(
        self,
        session_id: str,
        assignment_id: str,
        *,
        sequence: int,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> Mapping[str, PlainData]:
        return self._call(
            "event",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "sequence": sequence,
                "event_id": event_id,
                "payload": thaw_plain_data(payload, path="remote event"),
            },
        )

    def declare_outputs(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        authorization_id: str,
        authorization_revision: int,
        report: _RemoteExecutionReport,
    ) -> Mapping[str, PlainData]:
        return self._call(
            "output_manifest",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
                "authorization_id": authorization_id,
                "authorization_revision": authorization_revision,
                "report": report.to_dict(),
            },
        )

    def upload_output_chunk(
        self,
        session_id: str,
        assignment_id: str,
        transfer_id: str,
        *,
        offset: int,
        data: bytes,
        final: bool,
        authorization_id: str,
        authorization_revision: int,
    ) -> Mapping[str, PlainData]:
        return self._call(
            "output",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "transfer_id": transfer_id,
                "offset": offset,
                "data": _encode_chunk(data),
                "final": final,
                "authorization_id": authorization_id,
                "authorization_revision": authorization_revision,
            },
        )

    def commit_result(
        self, session_id: str, assignment_id: str, *, fence: str
    ) -> Mapping[str, PlainData]:
        return self._call(
            "result",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
            },
        )

    def release_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        availability_revision: str,
    ) -> AgentSession:
        journal = self._require_journal()
        execution_journal = self._execution_journal
        if execution_journal is None:
            raise QueueServiceError("remote execution journal is required")
        proof = journal.provider_release_proof(
            session_id, assignment_id, execution_journal
        )
        if (
            proof.execution_fence != fence
            or proof.released_availability_revision != availability_revision
        ):
            raise QueueConflictError("remote provider release proof is stale")
        session = _session_from_value(
            self._call(
                "release",
                {
                    "session_id": session_id,
                    "assignment_id": assignment_id,
                    "fence": fence,
                    "availability_revision": availability_revision,
                    "provider_release_proof": proof.value(),
                },
            )
        )
        if session.state is AgentSessionState.ACTIVE:
            journal.persist_reconciled_session(session)
        elif session.state is not AgentSessionState.REPLACED:
            raise QueueConflictError("remote release returned an invalid session state")
        journal.resolve_assignment_reference(session_id, assignment_id)
        return session

    def release_contained_assignment(
        self, session_id: str, assignment_id: str, *, fence: str
    ) -> AgentSession:
        """Release providers from the old root after guarded containment closes."""

        journal = self._require_journal()
        session = journal.session(session_id)
        journal.contained_assignment_control(session_id, assignment_id, fence)
        workspace = _ResidentAssignmentWorkspace(
            cast(Path, self._config.agent_root), assignment_id
        )
        request = workspace.request()
        profile = self._profile_for_descriptor(request.profile)
        if profile is None:
            raise QueueConflictError(
                "contained assignment has no exact resident profile"
            )
        providers, execution_journal = self._runtime_owners(session, profile)
        commands = execution_journal.assignment_claim_commands(assignment_id)
        if not commands:
            raise QueueConflictError("contained assignment claim is unavailable")
        assignment = commands[0].assignment
        if (
            assignment.assignment_id != assignment_id
            or assignment.session_id != session_id
            or any(command.assignment != assignment for command in commands)
        ):
            raise QueueConflictError("contained assignment claim is stale")
        state = execution_journal.read_state(assignment_id)
        if state is AssignmentState.PROCESS_STARTED:
            result_path = workspace.root / "worker-result.json"
            if not result_path.is_file():
                raise QueueConflictError("contained assignment result is unavailable")
            result = StageWorkerResult.from_dict(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
            workspace.persist_worker_result(result)
            execution_journal.record_result(assignment_id, result.to_dict())
        elif state not in {
            AssignmentState.RESULT_DURABLE,
            AssignmentState.TERMINAL_ACKNOWLEDGED,
            AssignmentState.PROVIDERS_RELEASED,
            AssignmentState.RELEASED,
        }:
            raise QueueConflictError("contained assignment is not provider-releasable")
        availability_revision = self._release_provider_claims(
            session,
            assignment,
            commands,
            providers,
            execution_journal,
        )
        return self.release_assignment(
            session_id,
            assignment_id,
            fence=fence,
            availability_revision=availability_revision,
        )

    def execute_one(
        self,
        session_id: str,
        availability_revision: str,
        *,
        poll_id: str,
        wait_timeout_ms: int,
    ) -> Mapping[str, PlainData]:
        """Poll and drive at most one resident assignment to ordered release."""

        delivery = self.wait_for_work(
            session_id,
            availability_revision,
            poll_id=poll_id,
            wait_timeout_ms=wait_timeout_ms,
        )
        if delivery.get("result") != "assignment":
            return delivery
        raw_request = delivery.get("request")
        request = _ResidentAssignmentBundle.from_dict(
            thaw_plain_data(raw_request, path="remote delivered request")
        )
        profile = self._profile_for_descriptor(request.profile)
        if profile is None:
            raise QueueConflictError(
                "delivered assignment has no exact resident profile"
            )
        session = self._require_journal().session(session_id)
        workspace = _ResidentAssignmentWorkspace(
            cast(Path, self._config.agent_root), request.assignment_id
        )
        workspace.persist_request(request, profile)
        self._require_journal().retain_assignment_reference(
            session_id, request.assignment_id
        )
        providers, execution_journal = self._runtime_owners(session, profile)
        assignment = ManagedAssignment(
            assignment_id=request.assignment_id,
            run_uri=f"loom-agent:{request.assignment_id}",
            stage_work_id=request.stage_work_id,
            stage_name=request.stage_name,
            attempt=request.attempt,
            attempt_id=request.attempt_id,
            agent_id=session.agent_id,
            session_id=session.session_id,
            offer_id=request.offer_id,
            claim_id=request.claim_id,
        )
        commands = tuple(
            ClaimCommand(
                assignment,
                f"{request.assignment_id}:prepare:{index}",
                claim,
                {
                    descriptor.kind: descriptor
                    for descriptor in request.provider_descriptors
                }[claim.resource_kind],
            )
            for index, claim in enumerate(request.claims)
        )
        execution_journal.persist_request(assignment, request.to_dict())
        cancelled = self._cancel_pregrant_if_requested(
            session,
            request.assignment_id,
            assignment,
            commands,
            providers,
            execution_journal,
        )
        if cancelled is not None:
            return cancelled

        authorization = self._fresh_transfer_authorization(
            session_id=session_id,
            assignment_id=request.assignment_id,
            expected_revision=0,
        )
        authorization_id = cast(str, authorization["authorization_id"])
        authorization_revision = cast(int, authorization["revision"])
        for item in request.inputs:
            offset = 0
            while True:
                response, authorization_id, authorization_revision = (
                    self._authorized_transfer_call(
                        session_id=session_id,
                        assignment_id=request.assignment_id,
                        authorization_id=authorization_id,
                        authorization_revision=authorization_revision,
                        operation=lambda current_id, current_revision: (
                            self.read_input_chunk(
                                session_id,
                                request.assignment_id,
                                item.transfer_id,
                                offset=offset,
                                authorization_id=current_id,
                                authorization_revision=current_revision,
                            )
                        ),
                    )
                )
                data, next_offset, final = cast(tuple[bytes, int, bool], response)
                workspace.stage_input_chunk(
                    item.transfer_id,
                    offset,
                    data,
                    final=final,
                )
                offset = next_offset
                if final:
                    break
        workspace.accept()
        prepared = execution_journal.prepare_composite(assignment, commands, providers)
        if prepared is AssignmentState.DECLINED:
            next_revision = self._availability_revision(
                session, request.assignment_id, providers
            )
            execution_journal.release_declined(assignment.assignment_id, next_revision)
            released_session = cast(
                AgentSession,
                self._assignment_call(
                    session_id,
                    request.assignment_id,
                    lambda: self.decline_assignment(
                        session_id,
                        request.assignment_id,
                        availability_revision=next_revision,
                    ),
                ),
            )
            return freeze_plain_data(
                {
                    "result": "assignment",
                    "assignment_id": request.assignment_id,
                    "state": "DECLINED",
                    "session": released_session.value(),
                },
                path="remote execution decline",
            )
        if prepared not in {
            AssignmentState.PREPARED,
            AssignmentState.ACCEPTED,
            AssignmentState.GRANTED,
            AssignmentState.ACTIVE,
            AssignmentState.PROCESS_STARTED,
            AssignmentState.RESULT_DURABLE,
        }:
            raise QueueConflictError("remote physical admission is indeterminate")
        execution_journal.accept(assignment.assignment_id)
        workspace.append_event(
            f"{request.assignment_id}:request-inputs-durable",
            {"kind": "request_and_inputs_durable"},
        )
        cancelled = self._cancel_pregrant_if_requested(
            session,
            request.assignment_id,
            assignment,
            commands,
            providers,
            execution_journal,
        )
        if cancelled is not None:
            return cancelled
        request_json = json.dumps(
            request.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        try:
            grant = cast(
                Mapping[str, PlainData],
                self._assignment_call(
                    session_id,
                    request.assignment_id,
                    lambda: self.accept_assignment(
                        session_id,
                        request.assignment_id,
                        request_digest=hashlib.sha256(
                            request_json.encode()
                        ).hexdigest(),
                    ),
                ),
            )
        except QueueConflictError as conflict:
            deadline = monotonic() + 5
            while monotonic() < deadline:
                cancelled = self._cancel_pregrant_if_requested(
                    session,
                    request.assignment_id,
                    assignment,
                    commands,
                    providers,
                    execution_journal,
                )
                if cancelled is not None:
                    return cancelled
                sleep(0.05)
            raise conflict
        fence = cast(str, grant["fence"])
        execution_journal.grant(assignment.assignment_id, fence)
        workspace.grant(fence)
        activated = execution_journal.activate_composite(
            assignment.assignment_id, commands, providers
        )
        if activated not in {
            AssignmentState.ACTIVE,
            AssignmentState.PROCESS_STARTED,
            AssignmentState.RESULT_DURABLE,
        }:
            raise QueueConflictError("remote physical activation is indeterminate")

        execution_id = f"{request.assignment_id}:root"
        supervisor = self._supervisor
        if supervisor is None:
            raise QueueConflictError("remote resident execution has no supervisor")
        launch: ResidentWorkerLaunch | None = None
        result_path = workspace.root / "worker-result.json"
        cancelled_before_start = False
        if execution_journal.read_state(assignment.assignment_id) in {
            AssignmentState.ACTIVE,
        }:

            def start_supervisor_launch() -> str:
                environment = {
                    key: value
                    for key, value in os.environ.items()
                    if not any(
                        marker in key.upper()
                        for marker in (
                            "TOKEN",
                            "SECRET",
                            "CREDENTIAL",
                            "PASSWORD",
                            "KEY",
                        )
                    )
                }
                for command in commands:
                    provider = providers[command.claim.resource_kind]
                    if isinstance(provider, GpuResourceProvider):
                        environment.update(provider.worker_environment(command))
                nonlocal launch
                launch = ResidentWorkerLaunch(
                    supervisor_id=supervisor.supervisor_id,
                    continuity_epoch=supervisor.continuity_epoch,
                    agent_id=supervisor.agent_id,
                    session_id=session.session_id,
                    assignment_id=request.assignment_id,
                    process_execution_id=execution_id,
                    execution_fence=fence,
                    launch_operation_id=f"{request.assignment_id}:launch:{fence}",
                    bundle_digest=hashlib.sha256(
                        _canonical_json(request.to_dict()).encode("utf-8")
                    ).hexdigest(),
                    workspace_root=workspace.root,
                    profile=profile.launch_profile,
                    environment=environment,
                )
                workspace.persist_supervisor_launch(
                    json.dumps(
                        _launch_value(launch), sort_keys=True, separators=(",", ":")
                    )
                )
                receipt = supervisor.launch(launch)
                if (
                    receipt.state
                    not in {
                        SupervisorLaunchState.STARTING,
                        SupervisorLaunchState.RUNNING,
                    }
                    or receipt.process_id is None
                ):
                    raise QueueConflictError(
                        "remote supervisor did not create a process root"
                    )
                workspace.mark_process_started(execution_id, receipt.process_id)
                return execution_id

            with self._control_lock:
                permitted = cast(
                    bool,
                    self._assignment_call(
                        session_id,
                        request.assignment_id,
                        lambda: self.start_permit(
                            session_id, request.assignment_id, fence=fence
                        ),
                    ),
                )
                if not permitted:
                    result = _cancelled_worker_result(workspace.worker_request())
                    atomic_write_bytes(
                        result_path,
                        json.dumps(
                            result.to_dict(),
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode(),
                    )
                    workspace.persist_cancelled_before_start(result)
                    execution_journal.record_cancelled_before_start(
                        assignment.assignment_id, result.to_dict()
                    )
                    cancelled_before_start = True
                else:
                    execution_journal.start_once(
                        assignment.assignment_id, execution_id, start_supervisor_launch
                    )
                    workspace.append_event(
                        f"{request.assignment_id}:agent-process-started",
                        {"kind": "process_started"},
                    )
                    self._assignment_call(
                        session_id,
                        request.assignment_id,
                        lambda: self.confirm_started(
                            session_id,
                            request.assignment_id,
                            fence=fence,
                            process_execution_id=execution_id,
                        ),
                    )
        self._flush_workspace_events(session_id, workspace)
        if launch is None:
            retained_launch = workspace.supervisor_launch_json()
            if retained_launch is not None:
                launch = _launch_from_value(json.loads(retained_launch))
        if launch is not None:
            while True:
                receipt = supervisor.query(launch)
                if receipt.state in {
                    SupervisorLaunchState.EXITED,
                    SupervisorLaunchState.CONTAINED,
                }:
                    break
                if receipt.state is SupervisorLaunchState.UNKNOWN:
                    raise QueueConflictError("remote supervisor continuity is unknown")
                self.poll_assignment_control(session_id)
                sleep(0.05)
        elif not result_path.is_file():
            raise QueueConflictError(
                "remote process outcome is unknown and cannot be relaunched"
            )
        if (
            not result_path.is_file()
            and request.assignment_id in self._cancelled_assignments
        ):
            cancelled = _cancelled_worker_result(workspace.worker_request())
            atomic_write_bytes(
                result_path,
                json.dumps(
                    cancelled.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode(),
            )
        if not result_path.is_file():
            raise QueueConflictError(
                "remote process exited without a durable worker result"
            )
        if launch is not None:
            contained = supervisor.contain(launch)
            if contained.state is not SupervisorLaunchState.CONTAINED:
                raise QueueConflictError("remote process group containment is unknown")
            if (
                contained.worker_result_digest
                != hashlib.sha256(result_path.read_bytes()).hexdigest()
            ):
                raise QueueConflictError(
                    "remote supervisor result evidence does not match the workspace"
                )
        return self._complete_remote_result_and_release(
            session,
            request,
            workspace,
            assignment,
            commands,
            providers,
            execution_journal,
            fence=fence,
            authorization_revision=authorization_revision,
            persist_result=not cancelled_before_start,
            result_path_label="remote execution completion",
        )

    def resume_retained_work(self) -> tuple[Mapping[str, PlainData], ...]:
        """Join continuous supervisor receipts before releasing startup capacity.

        This is deliberately an explicit application-start step: no offer or
        poll can bypass it, and an unknown receipt leaves its reference and
        provider claim unavailable.
        """

        journal = self._require_journal()
        execution_journal = self._execution_journal
        supervisor = self._supervisor
        if execution_journal is None or supervisor is None:
            raise QueueConflictError("remote restart has no supervisor journal")
        completed: list[Mapping[str, PlainData]] = []
        for session_id, assignment_id in journal.unresolved_assignment_references():
            session = journal.session(session_id)
            workspace = _ResidentAssignmentWorkspace(
                cast(Path, self._config.agent_root), assignment_id
            )
            request = workspace.request()
            profile = self._profile_for_descriptor(request.profile)
            if profile is None:
                raise QueueConflictError("retained assignment has no resident profile")
            assignment = ManagedAssignment(
                assignment_id=request.assignment_id,
                run_uri=f"loom-agent:{request.assignment_id}",
                stage_work_id=request.stage_work_id,
                stage_name=request.stage_name,
                attempt=request.attempt,
                attempt_id=request.attempt_id,
                agent_id=session.agent_id,
                session_id=session.session_id,
                offer_id=request.offer_id,
                claim_id=request.claim_id,
            )
            providers, _ = self._runtime_owners(session, profile)
            commands = execution_journal.assignment_claim_commands(assignment_id)
            launch_json = workspace.supervisor_launch_json()
            if launch_json is None:
                # A pre-launch operation has no evidence allowing a new start
                # after application restart; keep it unavailable for the owner.
                continue
            launch = _launch_from_value(json.loads(launch_json))
            receipt = supervisor.query(launch)
            if receipt.state is SupervisorLaunchState.NOT_ACCEPTED:
                # The complete exact operation was journaled before the service
                # call. Submitting that operation is replay, never relaunch.
                receipt = supervisor.launch(launch)
            if receipt.state is SupervisorLaunchState.UNKNOWN:
                continue
            needs_start_join = execution_journal.read_state(assignment_id) in {
                AssignmentState.START_INTENT,
                AssignmentState.START_UNKNOWN,
                AssignmentState.PROCESS_STARTED,
            }
            if needs_start_join and receipt.process_id is not None:
                self._join_retained_supervised_start(
                    session,
                    request,
                    workspace,
                    execution_journal,
                    launch,
                    receipt.process_id,
                )
                needs_start_join = False
            while receipt.state in {
                SupervisorLaunchState.STARTING,
                SupervisorLaunchState.RUNNING,
            }:
                self.poll_assignment_control(session_id)
                sleep(0.05)
                receipt = supervisor.query(launch)
                if needs_start_join and receipt.process_id is not None:
                    self._join_retained_supervised_start(
                        session,
                        request,
                        workspace,
                        execution_journal,
                        launch,
                        receipt.process_id,
                    )
                    needs_start_join = False
                if receipt.state is SupervisorLaunchState.UNKNOWN:
                    break
            if receipt.state is SupervisorLaunchState.UNKNOWN:
                continue
            result_path = workspace.root / "worker-result.json"
            if (
                not result_path.is_file()
                and assignment_id in self._cancelled_assignments
            ):
                self._record_contained_cancellation(workspace)
            contained = supervisor.contain(launch)
            if contained.state is not SupervisorLaunchState.CONTAINED:
                continue
            if not result_path.is_file():
                continue
            digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
            if contained.worker_result_digest != digest:
                continue
            completed.append(
                self._complete_remote_result_and_release(
                    session,
                    request,
                    workspace,
                    assignment,
                    commands,
                    providers,
                    execution_journal,
                    fence=launch.execution_fence,
                    authorization_revision=0,
                    persist_result=True,
                    result_path_label="remote restart completion",
                )
            )
        self._restart_with_retained_work = self._has_retained_agent_work()
        return tuple(completed)

    def _join_retained_supervised_start(
        self,
        session: AgentSession,
        request: _ResidentAssignmentBundle,
        workspace: _ResidentAssignmentWorkspace,
        execution_journal: SQLiteAgentJournal,
        launch: ResidentWorkerLaunch,
        process_id: int,
    ) -> None:
        """Join one exact accepted launch across the application crash barrier."""

        workspace.mark_process_started(launch.process_execution_id, process_id)
        execution_journal.confirm_supervised_start(
            request.assignment_id, launch.process_execution_id
        )
        workspace.append_event(
            f"{request.assignment_id}:agent-process-started",
            {"kind": "process_started"},
        )
        self._assignment_call(
            session.session_id,
            request.assignment_id,
            lambda: self.confirm_started(
                session.session_id,
                request.assignment_id,
                fence=launch.execution_fence,
                process_execution_id=launch.process_execution_id,
            ),
        )
        self._flush_workspace_events(session.session_id, workspace)

    def _complete_remote_result_and_release(
        self,
        session: AgentSession,
        request: _ResidentAssignmentBundle,
        workspace: _ResidentAssignmentWorkspace,
        assignment: ManagedAssignment,
        commands: tuple[ClaimCommand, ...],
        providers: Mapping[str, AtomResourceProvider],
        execution_journal: SQLiteAgentJournal,
        *,
        fence: str,
        authorization_revision: int,
        persist_result: bool,
        result_path_label: str,
    ) -> Mapping[str, PlainData]:
        """Own normal and restart result/output/outbox completion ordering."""

        result_path = workspace.root / "worker-result.json"
        result = StageWorkerResult.from_dict(json.loads(result_path.read_text()))
        if persist_result:
            workspace.persist_worker_result(result)
            execution_journal.record_result(assignment.assignment_id, result.to_dict())
        report = workspace.retain_outputs()
        workspace.append_event(
            f"{request.assignment_id}:result-output-durable",
            {"kind": "result_and_output_durable", "status": report.status.value},
        )
        self._flush_workspace_events(session.session_id, workspace)
        authorization = self._fresh_transfer_authorization(
            session_id=session.session_id,
            assignment_id=request.assignment_id,
            expected_revision=authorization_revision,
        )
        authorization_id = cast(str, authorization["authorization_id"])
        authorization_revision = cast(int, authorization["revision"])
        _, authorization_id, authorization_revision = self._authorized_transfer_call(
            session_id=session.session_id,
            assignment_id=request.assignment_id,
            authorization_id=authorization_id,
            authorization_revision=authorization_revision,
            operation=lambda current_id, current_revision: self.declare_outputs(
                session.session_id,
                request.assignment_id,
                fence=fence,
                authorization_id=current_id,
                authorization_revision=current_revision,
                report=report,
            ),
        )
        for item in report.outputs:
            offset = 0
            while True:
                data, final = workspace.output_chunk(item.transfer_id, offset)
                response, authorization_id, authorization_revision = (
                    self._authorized_transfer_call(
                        session_id=session.session_id,
                        assignment_id=request.assignment_id,
                        authorization_id=authorization_id,
                        authorization_revision=authorization_revision,
                        operation=lambda current_id, current_revision: (
                            self.upload_output_chunk(
                                session.session_id,
                                request.assignment_id,
                                item.transfer_id,
                                offset=offset,
                                data=data,
                                final=final,
                                authorization_id=current_id,
                                authorization_revision=current_revision,
                            )
                        ),
                    )
                )
                offset = cast(
                    int, cast(Mapping[str, PlainData], response)["received_bytes"]
                )
                if final:
                    break
        self._assignment_call(
            session.session_id,
            request.assignment_id,
            lambda: self.commit_result(
                session.session_id, request.assignment_id, fence=fence
            ),
        )
        next_revision = self._release_provider_claims(
            session,
            assignment,
            commands,
            providers,
            execution_journal,
        )
        released_session = cast(
            AgentSession,
            self._assignment_call(
                session.session_id,
                request.assignment_id,
                lambda: self.release_assignment(
                    session.session_id,
                    request.assignment_id,
                    fence=fence,
                    availability_revision=next_revision,
                ),
            ),
        )
        self._cancelled_assignments.discard(request.assignment_id)
        return freeze_plain_data(
            {
                "result": "assignment",
                "assignment_id": request.assignment_id,
                "state": "RELEASED",
                "session": released_session.value(),
            },
            path=result_path_label,
        )

    def _cancel_pregrant_if_requested(
        self,
        session: AgentSession,
        assignment_id: str,
        assignment: ManagedAssignment,
        commands: tuple[ClaimCommand, ...],
        providers: Mapping[str, AtomResourceProvider],
        execution_journal: SQLiteAgentJournal,
    ) -> Mapping[str, PlainData] | None:
        for _ in range(32):
            control = self.poll_assignment_control(session.session_id)
            if control is None:
                return None
            if control.assignment_id != assignment_id:
                continue
            state = execution_journal.read_state(assignment_id)
            if state is AssignmentState.REQUEST_DURABLE:
                execution_journal.decline_before_prepare(assignment_id)
            elif state in {AssignmentState.PREPARED, AssignmentState.ACCEPTED}:
                execution_journal.abort_pregrant(assignment_id, commands, providers)
            else:
                return None
            next_revision = self._availability_revision(
                session, assignment_id, providers
            )
            execution_journal.release_declined(assignment_id, next_revision)
            released_session = self.decline_assignment(
                session.session_id,
                assignment.assignment_id,
                availability_revision=next_revision,
            )
            return freeze_plain_data(
                {
                    "result": "assignment",
                    "assignment_id": assignment_id,
                    "state": "CANCELLED_BEFORE_GRANT",
                    "session": released_session.value(),
                },
                path="remote pre-grant cancellation",
            )
        raise QueueConflictError("assignment control delivery exceeds its bound")

    def _release_provider_claims(
        self,
        session: AgentSession,
        assignment: ManagedAssignment,
        commands: tuple[ClaimCommand, ...],
        providers: Mapping[str, AtomResourceProvider],
        execution_journal: SQLiteAgentJournal,
    ) -> str:
        """Release the exact composite and persist fresh capacity before RPC."""

        local_state = execution_journal.acknowledge_terminal(assignment.assignment_id)
        if local_state is AssignmentState.RELEASED:
            # Re-observe the reconstructed providers, then replay only the
            # availability revision already committed by this old root.
            self._availability_revision(session, assignment.assignment_id, providers)
            retained_revision = execution_journal.read_availability_revision(
                assignment.assignment_id
            )
            if retained_revision is None:
                raise QueueConflictError(
                    "released remote availability evidence is unavailable"
                )
            return retained_revision
        if local_state is not AssignmentState.PROVIDERS_RELEASED:
            for command in commands:
                provider = providers.get(command.claim.resource_kind)
                if provider is None:
                    raise QueueConflictError(
                        "remote provider release owner is unavailable"
                    )
                released = provider.release(
                    ClaimCommand(
                        assignment,
                        f"{command.operation_id}:release",
                        command.claim,
                        command.provider_descriptor,
                    )
                )
                if released.outcome is not ClaimOutcome.RELEASED:
                    raise QueueConflictError("remote provider release is indeterminate")
            execution_journal.mark_providers_released(assignment.assignment_id)
        next_revision = self._availability_revision(
            session, assignment.assignment_id, providers
        )
        execution_journal.publish_availability(assignment.assignment_id, next_revision)
        return next_revision

    @staticmethod
    def _availability_revision(
        session: AgentSession,
        assignment_id: str,
        providers: Mapping[str, AtomResourceProvider],
    ) -> str:
        observations = {
            kind: provider.observe(
                ObserveRequest(
                    session.agent_id,
                    session.session_id,
                    f"{assignment_id}:released:{kind}",
                )
            )
            for kind, provider in providers.items()
        }
        return (
            "availability-"
            + hashlib.sha256(
                "\0".join(
                    observations[kind].availability_revision
                    for kind in sorted(observations)
                ).encode()
            ).hexdigest()
        )

    def _fresh_transfer_authorization(
        self,
        *,
        session_id: str,
        assignment_id: str,
        expected_revision: int,
    ) -> Mapping[str, PlainData]:
        """Renew until the authorization belongs to the reconciled epoch."""

        revision = expected_revision
        while True:
            operation_id = f"{assignment_id}:authorize:{revision + 1}"
            result = cast(
                Mapping[str, PlainData],
                self._assignment_call(
                    session_id,
                    assignment_id,
                    lambda: self.authorize_transfers(
                        session_id,
                        assignment_id,
                        expected_revision=revision,
                        operation_id=operation_id,
                    ),
                ),
            )
            returned_revision = result.get("revision")
            returned_epoch = result.get("coordinator_epoch")
            if (
                isinstance(returned_revision, bool)
                or not isinstance(returned_revision, int)
                or returned_revision != revision + 1
                or not isinstance(returned_epoch, str)
            ):
                raise QueueConflictError(
                    "remote transfer authorization evidence is invalid"
                )
            revision = returned_revision
            if (
                returned_epoch
                == self._require_journal().session(session_id).coordinator_epoch
            ):
                return result

    def _authorized_transfer_call(
        self,
        *,
        session_id: str,
        assignment_id: str,
        authorization_id: str,
        authorization_revision: int,
        operation: Callable[[str, int], Any],
    ) -> tuple[Any, str, int]:
        """Run one transfer operation, renewing only a proven-stale grant."""

        current_id = authorization_id
        current_revision = authorization_revision
        for _ in range(_MAX_TRANSFER_AUTHORIZATION_RENEWALS + 1):
            try:
                result = self._assignment_call(
                    session_id,
                    assignment_id,
                    lambda: operation(current_id, current_revision),
                )
                return result, current_id, current_revision
            except AgentTransferAuthorizationStaleError:
                renewed = self._fresh_transfer_authorization(
                    session_id=session_id,
                    assignment_id=assignment_id,
                    expected_revision=current_revision,
                )
                current_id = cast(str, renewed["authorization_id"])
                current_revision = cast(int, renewed["revision"])
        raise QueueConflictError(
            "remote transfer authorization renewal exceeded its bound"
        )

    def _assignment_call(
        self,
        session_id: str,
        assignment_id: str,
        operation: Callable[[], Any],
    ) -> Any:
        """Retry one exact assignment operation across coordinator restart."""

        deadline = monotonic() + _ASSIGNMENT_RECONCILIATION_SECONDS
        while True:
            try:
                return operation()
            except QueueConflictError as conflict:
                prior = self._require_journal().session(session_id)
                current = self.handshake()
                epoch = current.get("coordinator_epoch")
                if not isinstance(epoch, str) or epoch == prior.coordinator_epoch:
                    raise conflict
                self.reconcile(
                    session_id,
                    epoch,
                    idempotency_key=(f"{assignment_id}:reconcile:{epoch}"),
                )
            except _IndeterminateAgentProtocolError:
                if monotonic() >= deadline:
                    raise
                try:
                    current = self.handshake()
                    epoch = current.get("coordinator_epoch")
                    prior = self._require_journal().session(session_id)
                    if isinstance(epoch, str) and epoch != prior.coordinator_epoch:
                        self.reconcile(
                            session_id,
                            epoch,
                            idempotency_key=(f"{assignment_id}:reconcile:{epoch}"),
                        )
                except _IndeterminateAgentProtocolError:
                    pass
                sleep(0.05)

    def _runtime_owners(
        self, session: AgentSession, profile: ResidentExecutionProfile
    ) -> tuple[dict[str, AtomResourceProvider], SQLiteAgentJournal]:
        journal = self._execution_journal
        if journal is None:
            raise QueueServiceError("remote execution journal is required")
        if self._runtime_agent_id is None:
            self._runtime_agent_id = session.agent_id
            self._runtime_provider_key = _resident_provider_key(profile)
            planners = {
                "cpu": CpuResourcePlanner(),
                "memory": MemoryResourcePlanner(),
                "gpu": GpuResourcePlanner(),
            }
            atoms = profile.capacity_atoms(session.agent_id)
            self._providers = {}
            for kind in {atom.owner_resource_kind for atom in atoms}:
                if kind == "gpu":
                    continue
                provider_atoms = tuple(
                    atom for atom in atoms if atom.owner_resource_kind == kind
                )
                self._providers[kind] = AtomResourceProvider(
                    _configured_provider_descriptor(kind, provider_atoms),
                    planners[kind].claim_contracts,
                    provider_atoms,
                )
            if profile.gpu_devices:
                healthy_gpu_keys = {
                    f"{session.agent_id}:{device.descriptor.device_id}"
                    for device in profile.gpu_devices
                    if device.descriptor.healthy
                }
                gpu_atoms = tuple(
                    atom
                    for atom in atoms
                    if atom.owner_resource_kind == "gpu"
                    and atom.local_capacity_key in healthy_gpu_keys
                )
                self._providers["gpu"] = GpuResourceProvider(
                    planners["gpu"].claim_contracts,
                    gpu_atoms,
                    bindings={
                        f"{session.agent_id}:{device.descriptor.device_id}": (
                            device.binding_value
                        )
                        for device in profile.gpu_devices
                        if device.descriptor.healthy
                    },
                )
            for command in journal.retained_claim_commands():
                provider = self._providers.get(command.claim.resource_kind)
                if provider is None:
                    raise QueueConflictError(
                        "retained remote claim has no resident provider"
                    )
                provider.restore_capacity_holding(command)
        elif self._runtime_agent_id != session.agent_id:
            raise QueueConflictError("remote runtime agent identity changed")
        elif self._runtime_provider_key != _resident_provider_key(profile):
            raise QueueConflictError(
                "resident provider configuration changed while claims are retained"
            )
        if any(
            claim_kind not in self._providers
            for claim_kind in {
                atom.owner_resource_kind
                for atom in profile.capacity_atoms(session.agent_id)
            }
        ):
            raise QueueConflictError("resident provider composition changed")
        return self._providers, journal

    def _profile_for_descriptor(
        self, descriptor: object
    ) -> ResidentExecutionProfile | None:
        active = self._profiles.get(getattr(descriptor, "profile_id", ""))
        if active is not None and active.descriptor == descriptor:
            return active
        return next(
            (
                profile
                for profile in self._retained_profiles.values()
                if profile.descriptor == descriptor
            ),
            None,
        )

    def _flush_workspace_events(
        self, session_id: str, workspace: _ResidentAssignmentWorkspace
    ) -> None:
        for sequence, event_id, payload in workspace.pending_events():
            result = cast(
                Mapping[str, PlainData],
                self._assignment_call(
                    session_id,
                    workspace.assignment_id,
                    lambda: self.report_event(
                        session_id,
                        workspace.assignment_id,
                        sequence=sequence,
                        event_id=event_id,
                        payload=payload,
                    ),
                ),
            )
            acknowledged = result.get("acknowledged_sequence")
            if acknowledged != sequence:
                raise QueueConflictError("remote event acknowledgement has a gap")
            workspace.acknowledge_event(sequence)

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
        journal.persist_retired(session_id, idempotency_key)
        return result

    def _require_journal(self) -> "_RemoteAgentJournal":
        if self._journal is None:
            raise QueueServiceError("remote agent durable journal is required")
        return self._journal

    def call_application(
        self, role: str, operation: str, value: Mapping[str, PlainData]
    ) -> Mapping[str, PlainData]:
        """Call the authenticated application view selected by its certificate."""
        if role not in {"client", "operator", "slurm_bootstrap"}:
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
            if payload.get("error") == "agent_transfer_authorization_stale":
                raise AgentTransferAuthorizationStaleError(
                    "remote transfer authorization is stale"
                )
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
            execution = self._daemon_server.daemon_owner._execution
            slurm_profile = (
                None
                if execution is None
                else execution._slurm_profile_for_credential(credential)
            )
            if slurm_profile is None:
                principal_id, mapped_role = ScopedAuthorizer(
                    self._daemon_server.daemon_owner._agent_policy
                ).transport_principal(credential)
            else:
                principal_id = slurm_profile.bootstrap_principal_id
                mapped_role = LocalDaemonRole.SLURM_BOOTSTRAP.value
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
                    "authorize",
                    "input",
                    "accept",
                    "decline",
                    "started",
                    "event",
                    "output_manifest",
                    "output",
                    "result",
                    "release",
                    "control",
                    "control_ack",
                    "assignment_control",
                    "assignment_control_ack",
                    "start_permit",
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
        except AgentTransferAuthorizationStaleError:
            self._reply(
                409,
                {"ok": False, "error": "agent_transfer_authorization_stale"},
            )
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
    if operation == "authorize":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "expected_revision",
                "operation_id",
            },
        )
        return view.authorize_transfers(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            expected_revision=_integer(value, "expected_revision"),
            operation_id=_string(value, "operation_id"),
        )
    if operation == "input":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "transfer_id",
                "offset",
                "authorization_id",
                "authorization_revision",
            },
        )
        return view.read_input_chunk(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            _string(value, "transfer_id"),
            offset=_integer(value, "offset"),
            authorization_id=_string(value, "authorization_id"),
            authorization_revision=_integer(value, "authorization_revision"),
        )
    if operation == "accept":
        _exact(value, {"session_id", "assignment_id", "request_digest"})
        return view.accept_assignment(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            request_digest=_string(value, "request_digest"),
        )
    if operation == "decline":
        _exact(
            value,
            {"session_id", "assignment_id", "availability_revision"},
        )
        return view.decline_assignment(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            availability_revision=_string(value, "availability_revision"),
        ).value()
    if operation == "started":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "fence",
                "process_execution_id",
            },
        )
        return view.confirm_started(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            fence=_string(value, "fence"),
            process_execution_id=_string(value, "process_execution_id"),
        )
    if operation == "event":
        _exact(
            value,
            {"session_id", "assignment_id", "sequence", "event_id", "payload"},
        )
        payload = value["payload"]
        if not isinstance(payload, Mapping):
            raise QueueServiceError("remote event payload is invalid")
        return view.report_event(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            sequence=_integer(value, "sequence"),
            event_id=_string(value, "event_id"),
            payload=freeze_plain_data(payload, path="remote event"),
        )
    if operation == "output_manifest":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "fence",
                "authorization_id",
                "authorization_revision",
                "report",
            },
        )
        return view.declare_outputs(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            fence=_string(value, "fence"),
            authorization_id=_string(value, "authorization_id"),
            authorization_revision=_integer(value, "authorization_revision"),
            report=_RemoteExecutionReport.from_dict(value["report"]),
        )
    if operation == "output":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "transfer_id",
                "offset",
                "data",
                "final",
                "authorization_id",
                "authorization_revision",
            },
        )
        final = value["final"]
        if not isinstance(final, bool):
            raise QueueServiceError("remote output final flag is invalid")
        return view.upload_output_chunk(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            _string(value, "transfer_id"),
            offset=_integer(value, "offset"),
            data=_decode_chunk(value["data"]),
            final=final,
            authorization_id=_string(value, "authorization_id"),
            authorization_revision=_integer(value, "authorization_revision"),
        )
    if operation == "result":
        _exact(value, {"session_id", "assignment_id", "fence"})
        return view.commit_result(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            fence=_string(value, "fence"),
        )
    if operation == "release":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "fence",
                "availability_revision",
                "provider_release_proof",
            },
        )
        raw_proof = value["provider_release_proof"]
        if not isinstance(raw_proof, Mapping):
            raise QueueServiceError("agent provider release proof is invalid")
        return view.release_assignment(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            fence=_string(value, "fence"),
            availability_revision=_string(value, "availability_revision"),
            provider_release_proof=_provider_release_proof(raw_proof),
        ).value()
    if operation == "control":
        _exact(value, {"session_id"})
        control = view.next_control(_string(value, "session_id"))
        return {"control": None if control is None else control.value()}
    if operation == "control_ack":
        _exact(value, {"session_id", "effect"})
        effect = value["effect"]
        if not isinstance(effect, Mapping):
            raise QueueServiceError("agent control effect is invalid")
        return view.acknowledge_control(
            _string(value, "session_id"), AgentControlEffect.from_value(effect)
        )
    if operation == "assignment_control":
        _exact(value, {"session_id"})
        control = view.next_assignment_control(_string(value, "session_id"))
        return {"control": None if control is None else control.value()}
    if operation == "assignment_control_ack":
        _exact(value, {"session_id", "operation_id", "code", "evidence"})
        evidence = value["evidence"]
        if evidence is not None and not isinstance(evidence, Mapping):
            raise QueueServiceError("assignment control evidence is invalid")
        return view.acknowledge_assignment_control(
            _string(value, "session_id"),
            _string(value, "operation_id"),
            code=_string(value, "code"),
            evidence=evidence,
        )
    if operation == "start_permit":
        _exact(value, {"session_id", "assignment_id", "fence"})
        return {
            "permitted": view.start_permit(
                _string(value, "session_id"),
                _string(value, "assignment_id"),
                fence=_string(value, "fence"),
            )
        }
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
        if role == LocalDaemonRole.SLURM_BOOTSTRAP.value:
            return daemon.slurm_bootstrap_view(principal).handshake()
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
        if operation == "agent_control":
            _exact(value, {"control"})
            control = value["control"]
            if not isinstance(control, Mapping):
                raise QueueServiceError("agent control request is invalid")
            return view.control_agent(AgentControl.from_value(control))
        if operation == "scheduling_reload":
            _exact(value, {"request"})
            request = value["request"]
            if not isinstance(request, Mapping):
                raise QueueServiceError("scheduling reload request is invalid")
            return view.reload_scheduling(
                CoordinatorSchedulingReload.from_dict(request)
            )
        if operation == "recover_unknown":
            _exact(value, {"request"})
            request = value["request"]
            if not isinstance(request, Mapping):
                raise QueueServiceError("recovery request is invalid")
            return view.recover_unknown(RecoverUnknownAssignment.from_dict(request))
        if operation == "replace_agent_session":
            _exact(value, {"request"})
            request = value["request"]
            if not isinstance(request, Mapping):
                raise QueueServiceError("session replacement request is invalid")
            return view.replace_agent_session(
                SessionReplacementRequest.from_dict(request)
            )
    elif role == LocalDaemonRole.SLURM_BOOTSTRAP.value:
        view = daemon.slurm_bootstrap_view(principal)
        if operation == "register":
            _exact(
                value,
                {
                    "operation_id",
                    "request_digest",
                    "job_id",
                    "cluster",
                    "incarnation",
                    "capability",
                },
            )
            cluster = value["cluster"]
            if cluster is not None and not isinstance(cluster, str):
                raise QueueServiceError("SLURM bootstrap cluster is invalid")
            return view.register(
                operation_id=_string(value, "operation_id"),
                request_digest=_string(value, "request_digest"),
                job_id=_string(value, "job_id"),
                cluster=cast(str | None, cluster),
                incarnation=_string(value, "incarnation"),
                capability=_string(value, "capability"),
            )
        if operation == "input":
            _exact(
                value,
                {"assignment_id", "incarnation", "transfer_id", "offset"},
            )
            data, final = view.input_chunk(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
                _string(value, "transfer_id"),
                offset=_integer(value, "offset"),
            )
            return {"data": _encode_chunk(data), "final": final}
        if operation == "inputs_ready":
            _exact(value, {"assignment_id", "incarnation"})
            view.inputs_ready(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
            )
            return {"state": "input_ready"}
        if operation == "grant":
            _exact(value, {"assignment_id", "incarnation"})
            return {
                "fence": view.grant(
                    _string(value, "assignment_id"),
                    _string(value, "incarnation"),
                )
            }
        if operation == "start":
            _exact(value, {"assignment_id", "incarnation", "fence"})
            return {
                "permitted": view.start_permit(
                    _string(value, "assignment_id"),
                    _string(value, "incarnation"),
                    _string(value, "fence"),
                )
            }
        if operation == "started":
            _exact(
                value,
                {
                    "assignment_id",
                    "incarnation",
                    "fence",
                    "process_execution_id",
                },
            )
            view.started(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
                _string(value, "fence"),
                _string(value, "process_execution_id"),
            )
            return {"state": "running"}
        if operation == "report":
            _exact(value, {"assignment_id", "incarnation", "fence", "report"})
            report = value["report"]
            if not isinstance(report, Mapping):
                raise QueueServiceError("SLURM result report is invalid")
            view.declare_report(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
                _string(value, "fence"),
                report,
            )
            return {"state": "report_durable"}
        if operation == "output":
            _exact(
                value,
                {
                    "assignment_id",
                    "incarnation",
                    "transfer_id",
                    "offset",
                    "data",
                    "final",
                },
            )
            final = value["final"]
            if not isinstance(final, bool):
                raise QueueServiceError("SLURM output final flag is invalid")
            return {
                "received": view.output_chunk(
                    _string(value, "assignment_id"),
                    _string(value, "incarnation"),
                    _string(value, "transfer_id"),
                    offset=_integer(value, "offset"),
                    data=_decode_chunk(value["data"]),
                    final=final,
                )
            }
        if operation == "result":
            _exact(value, {"assignment_id", "incarnation", "fence"})
            view.commit_result(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
                _string(value, "fence"),
            )
            return {"state": "terminal"}
        if operation == "release":
            _exact(value, {"assignment_id", "incarnation"})
            view.release(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
            )
            return {"state": "released"}
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
            "retirement_verifier",
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
        retirement_verifier=(
            _string(value, "retirement_verifier")
            if value["retirement_verifier"] is not None
            else None
        ),
    )


def _offer(value: Mapping[str, object]) -> AgentOffer:
    try:
        return AgentOffer.from_value(value)
    except Exception as exc:
        if isinstance(exc, QueueServiceError):
            raise
        raise QueueServiceError("agent offer is invalid") from exc


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
            "retirement_secret",
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
        retirement_secret=_string(value, "retirement_secret"),
    )


def _provider_release_proof(
    value: Mapping[str, object],
) -> AgentProviderReleaseProof:
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
            "assignment_id",
            "claim_id",
            "execution_fence",
            "released_availability_revision",
            "recovery_control_operation_id",
            "retirement_secret",
        },
    )
    raw_control = value["recovery_control_operation_id"]
    if raw_control is not None and not isinstance(raw_control, str):
        raise QueueServiceError("agent recovery control proof is invalid")
    return AgentProviderReleaseProof(
        session_id=_string(value, "session_id"),
        coordinator_id=_string(value, "coordinator_id"),
        coordinator_epoch=_string(value, "coordinator_epoch"),
        agent_id=_string(value, "agent_id"),
        agent_root_id=_string(value, "agent_root_id"),
        policy_revision=_string(value, "policy_revision"),
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        assignment_id=_string(value, "assignment_id"),
        claim_id=_string(value, "claim_id"),
        execution_fence=_string(value, "execution_fence"),
        released_availability_revision=_string(value, "released_availability_revision"),
        recovery_control_operation_id=raw_control,
        retirement_secret=_string(value, "retirement_secret"),
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


def _resident_launch_profile_set(
    config: AgentTlsClientConfig,
) -> tuple[tuple[str, str], ...]:
    """Canonical executable bindings held by the initialized supervisor.

    Capacity is intentionally absent: it contributes to provider inventory, not
    the protected worker executable, descriptor, or project binding.
    """

    return tuple(
        sorted(
            (
                profile.descriptor.profile_id,
                profile.launch_profile.fingerprint,
            )
            for profile in config.resident_profiles
        )
    )


def _resident_provider_key(profile: ResidentExecutionProfile) -> str:
    return _agent_revision(
        "resident-provider",
        {
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
            ]
        },
    )


def _agent_inventory_revision(config: AgentTlsClientConfig) -> str:
    return _agent_revision(
        "inventory",
        {
            "profiles": [
                {
                    "descriptor": profile.descriptor.to_dict(),
                    "cpu_capacity": profile.cpu_capacity,
                    "memory_capacity_bytes": profile.memory_capacity_bytes,
                    "gpu_devices": [
                        device.descriptor.to_dict() for device in profile.gpu_devices
                    ],
                }
                for profile in config.resident_profiles
            ]
        },
    )


def _agent_revision(prefix: str, value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()}"


def _read_remote_agent_root_id(root: Path) -> str:
    """Read only the stable identity after protected-root validation."""
    path = Path(root).resolve() / "control.sqlite"
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT value FROM root_metadata WHERE key = 'stable_id'"
            ).fetchone()
    except sqlite3.Error as exc:
        raise QueueServiceError("remote agent control state is unavailable") from exc
    if row is None or not isinstance(row[0], str) or not row[0]:
        raise QueueServiceError("remote agent root identity is invalid")
    return row[0]


__all__ = [
    "AgentTlsClientConfig",
    "AgentTlsServerConfig",
    "LocalDaemonAgentHttpClient",
    "LocalDaemonAgentHttpServer",
]
