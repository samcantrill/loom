"""Explicit, irreversible role retirement before operator-owned storage disposal.

Loom proves native quiescence and fences reuse; callers own service stopping,
credential revocation, archives and deletion. No function here removes files.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import TYPE_CHECKING, cast

from loom.serialization import PlainData

from .errors import QueueConflictError, QueueServiceError

if TYPE_CHECKING:
    from ._agent_slurm import AgentSlurmJobs
    from ._managed_local import SQLiteAgentJournal
    from .deployment import AgentSpec, OutboundAgentServiceConfig


@dataclass(frozen=True, slots=True)
class AgentDeclarationBinding:
    """Accepted native declaration, not current execution-readiness evidence."""

    root_id: str
    declaration_digest: str
    immutable_fingerprint: str
    active_fingerprint: str
    active_configuration_revision: int


def read_agent_declaration_binding(
    root: Path, declaration_digest: str
) -> AgentDeclarationBinding | None:
    """Inspect one existing protected root without probes or creating state.

    Only missing legacy declaration evidence returns ``None``. Conflicting or
    malformed evidence fails. The result is a snapshot: mutating consumers must
    repeat this check while holding native ownership. A launcher still awaits
    fresh qualification and the exact native process/session after starting.
    """
    from ._agent_session_journal import _AGENT_BINDING_FILE
    from .local_daemon import _LOCAL_DAEMON_SCHEMA_VERSION

    root = Path(root).resolve()
    database = root / "control.sqlite"
    binding_path = root / _AGENT_BINDING_FILE
    try:
        for path, directory in ((root, True), (database, False), (binding_path, False)):
            details = path.stat()
            if (
                details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) & 0o077
                or (path.is_dir() if directory else path.is_file()) is not True
            ):
                raise QueueServiceError(
                    "agent declaration binding must be owner-protected"
                )
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("BEGIN")
            schema = conn.execute("PRAGMA user_version").fetchone()[0]
            metadata = dict(conn.execute("SELECT key,value FROM root_metadata"))
            if (
                schema != _LOCAL_DAEMON_SCHEMA_VERSION
                or metadata.get("role") != "local-agent"
                or not metadata.get("stable_id")
            ):
                raise QueueServiceError("agent declaration root identity is invalid")
            encoded = metadata.get("declaration_binding")
            if encoded is None:
                return None
            value = json.loads(encoded)
            if (
                not isinstance(value, dict)
                or set(value)
                != {
                    "version",
                    "declaration_digest",
                    "immutable_fingerprint",
                    "active_fingerprint",
                    "active_configuration_revision",
                }
                or type(value["version"]) is not int
                or value["version"] != 1
            ):
                raise QueueServiceError("agent declaration binding is invalid")
            for name in (
                "declaration_digest",
                "immutable_fingerprint",
                "active_fingerprint",
            ):
                digest = value[name]
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)
                ):
                    raise QueueServiceError("agent declaration binding is invalid")
            revision = value["active_configuration_revision"]
            if type(revision) is not int or revision < 1:
                raise QueueServiceError("agent declaration revision is invalid")
            if (
                value["declaration_digest"] != declaration_digest
                or value["active_fingerprint"]
                != metadata.get("active_configuration_fingerprint")
                or str(revision) != metadata.get("active_configuration_revision")
            ):
                raise QueueConflictError(
                    "agent declaration differs from accepted native configuration"
                )
            if (
                conn.execute(
                    "SELECT 1 FROM agent_controls_local WHERE effect_json IS NULL "
                    "AND replacement_fingerprint IS NOT NULL LIMIT 1"
                ).fetchone()
                is not None
            ):
                raise QueueConflictError(
                    "pending agent reload prevents lightweight control"
                )
            expected = {
                "schema_version": 2,
                "role_kind": "outbound-agent",
                "stable_id": metadata["stable_id"],
                "immutable_fingerprint": value["immutable_fingerprint"],
            }
            if json.loads(binding_path.read_text(encoding="utf-8")) != expected:
                raise QueueConflictError(
                    "agent declaration does not match the native root binding"
                )
            return AgentDeclarationBinding(
                metadata["stable_id"],
                value["declaration_digest"],
                value["immutable_fingerprint"],
                value["active_fingerprint"],
                revision,
            )
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        raise QueueServiceError(
            "agent declaration binding is unavailable or invalid"
        ) from exc


@contextmanager
def agent_declaration_guard(
    root: Path,
    declaration_digest: str,
) -> Iterator[AgentDeclarationBinding | None]:
    """Hold an existing bound agent's native owner lock without execution probes.

    The bound path rejects retired roots and conflicting declarations. ``None``
    denotes missing legacy evidence and grants no ownership proof: callers must
    use their previous fully checked path. Nothing initializes a missing root.
    Retained work is allowed for ordinary startup recovery, not silently released.
    """
    from ._agent_session_journal import _RemoteAgentJournal

    binding = read_agent_declaration_binding(root, declaration_digest)
    if binding is None:
        yield None
        return
    journal = _RemoteAgentJournal(
        root,
        expected_configuration_fingerprint=binding.immutable_fingerprint,
        expected_active_configuration_fingerprint=binding.active_fingerprint,
    )
    try:
        if read_agent_declaration_binding(root, declaration_digest) != binding:
            raise QueueConflictError("agent declaration changed during ownership check")
        require_unretired(root)
        yield binding
    finally:
        journal.close()


def _retained_agent_owners(
    spec: AgentSpec,
) -> tuple[SQLiteAgentJournal | None, AgentSlurmJobs | None]:
    from ._agent_slurm import AgentSlurmJobs
    from ._managed_local import SQLiteAgentJournal

    root = spec.agent_root
    execution = None
    if spec.declarations["resident_profiles"] or (root / "journal.sqlite").exists():
        execution = SQLiteAgentJournal(root / "journal.sqlite", _allow_initialize=False)
        execution._open_existing()
    slurm = None
    if spec.declarations["slurm_profiles"] or (root / "slurm.sqlite").exists():
        slurm = AgentSlurmJobs(root, ())
    return execution, slurm


def verify_agent_candidate(spec: AgentSpec) -> AgentDeclarationBinding:
    """Verify an initialized, process-free replacement before authorizing drain.

    Requires accepted declaration evidence and no registration/session or retained
    work. An existing empty supervisor is cleanly shut down, never started. This
    proves native initialization, not current IO/GPU/software readiness. Later
    active probes and actual service startup remain separate required boundaries.
    """
    from contextlib import nullcontext
    from .agent_session_transport import _has_retained_agent_work
    from ._agent_process_supervisor import (
        AgentProcessSupervisorError,
        retained_supervisor_guard,
    )
    from ._managed_local import ManagedLocalError

    try:
        with agent_declaration_guard(
            spec.agent_root, spec.declaration_digest
        ) as binding:
            if binding is None:
                raise QueueServiceError("candidate lacks accepted declaration binding")
            # The guard owns this journal's lock. Inspection itself stays read-only.
            with closing(
                sqlite3.connect(
                    (spec.agent_root / "control.sqlite").as_uri() + "?mode=ro", uri=True
                )
            ) as conn:
                if (
                    conn.execute(
                        "SELECT 1 FROM agent_sessions_local LIMIT 1"
                    ).fetchone()
                    or conn.execute(
                        "SELECT 1 FROM agent_registration_intents LIMIT 1"
                    ).fetchone()
                ):
                    raise QueueConflictError(
                        "candidate has already participated in a session"
                    )
            execution, slurm = _retained_agent_owners(spec)
            # Use the same retained-work owner rather than a second inventory.
            if _has_retained_agent_work(None, execution, slurm):
                raise QueueConflictError("candidate has retained work")
            guard = (
                retained_supervisor_guard(spec.agent_root, agent_id=binding.root_id)
                if spec.declarations["resident_profiles"]
                or (spec.agent_root / "supervisor").exists()
                else nullcontext()
            )
            with guard:
                return binding
    except (
        AgentProcessSupervisorError,
        ManagedLocalError,
        sqlite3.Error,
        OSError,
    ) as exc:
        raise QueueServiceError(
            "candidate native ownership is unavailable or unsettled"
        ) from exc


def retirement_receipt(root: Path) -> dict[str, PlainData] | None:
    """Read an existing role's retirement fence without creating any state."""
    database = root / "control.sqlite"
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "SELECT value FROM root_metadata WHERE key='role_retirement'"
        ).fetchone()
    return None if row is None else json.loads(row[0])


def require_unretired(root: Path) -> None:
    """Reject restarting a deployment explicitly retired for removal."""
    if retirement_receipt(root) is not None:
        raise QueueConflictError(
            "role is retired; preserve its receipt and finish removal"
        )


def _save(root: Path, receipt: Mapping[str, PlainData]) -> None:
    # The caller holds the native role lock, and for coordinators the cycle lock.
    with sqlite3.connect(root / "control.sqlite") as conn:
        conn.execute(
            "INSERT INTO root_metadata(key,value) VALUES ('role_retirement',?)",
            (json.dumps(dict(receipt), sort_keys=True),),
        )


def retire_outbound_agent(
    config: OutboundAgentServiceConfig | AgentSpec,
    *,
    operation_id: str,
    expected_coordinator_id: str,
    expected_session_id: str,
) -> dict[str, PlainData]:
    """Retire an already stopped, drained outbound service and its supervisor.

    Credentials must remain authorized until this returns. Native journals and
    the coordinator both prove references settled. Busy/unknown work refuses;
    this never cancels work, initializes roots or forces a process to exit.
    Repeating the same operation recovers a lost response without new identity.
    A protected ``AgentSpec`` uses accepted native declaration evidence without
    probing its old workload environment. Missing legacy evidence alone falls
    back to full qualification; conflicting evidence never does.
    An unanswered service poll is reconciled through authenticated outcome
    inspection, never replayed as a work request. A recovered delivery remains
    owned and refuses retirement until normal retained-work settlement completes.
    """
    from .agent_session_transport import (
        LocalDaemonAgentHttpClient,
        _has_retained_agent_work,
        _reconcile_retirement_poll,
        _retire_agent_session,
    )
    from .deployment import (
        AgentSpec,
        OutboundAgentServiceConfig,
        _OUTBOUND_POLL_WAIT_MS,
        qualify_agent_spec,
    )

    _identifiers(operation_id, expected_coordinator_id, expected_session_id)
    if isinstance(config, AgentSpec):
        binding = read_agent_declaration_binding(
            config.agent_root, config.declaration_digest
        )
        if binding is not None:
            return _retire_bound_agent(
                config,
                binding,
                operation_id=operation_id,
                expected_coordinator_id=expected_coordinator_id,
                expected_session_id=expected_session_id,
            )
        config = qualify_agent_spec(config)

    if (
        not isinstance(config, OutboundAgentServiceConfig)
        or config.client.agent_root is None
    ):
        raise QueueServiceError("outbound service configuration is required")
    root = config.client.agent_root
    expected: dict[str, PlainData] = {
        "role": "agent",
        "operation_id": operation_id,
        "coordinator_id": expected_coordinator_id,
        "session_id": expected_session_id,
        "immutable_fingerprint": config.immutable_fingerprint,
        "active_fingerprint": config.active_fingerprint,
    }
    prior = retirement_receipt(root)
    if prior is not None:
        if any(prior.get(k) != v for k, v in expected.items()):
            raise QueueConflictError("retirement operation or role binding changed")
        with retired_role_guard(root, prior):
            return prior
    # Opening takes the native exclusive journal lock. It may restart only an
    # already initialized, provably empty supervisor, never an agent service.
    client = LocalDaemonAgentHttpClient(config.client)
    try:
        journal = client._require_journal()
        with journal._connection() as conn:
            row = conn.execute(
                "SELECT value_json,state FROM agent_sessions_local WHERE session_id=?",
                (expected_session_id,),
            ).fetchone()
        if (
            row is None
            or json.loads(row["value_json"])["coordinator_id"]
            != expected_coordinator_id
        ):
            raise QueueConflictError("retirement session or coordinator changed")
        if (
            _has_retained_agent_work(
                None, client._execution_journal, client._slurm_agent
            )
            or journal.unresolved_assignment_references()
        ):
            raise QueueConflictError("agent has retained work")
        _reconcile_retirement_poll(
            journal,
            client._call,
            expected_session_id,
            wait_timeout_ms=_OUTBOUND_POLL_WAIT_MS,
        )
        # Recovery may have retained a delivery; shutdown proves all owners empty.
        client.shutdown_clean()
        receipt = {**expected, "root_id": journal.root_id, "state": "retired"}
        if row["state"] != "RETIRED_CLEAN":
            _retire_agent_session(
                journal,
                client._call,
                expected_session_id,
                idempotency_key=operation_id,
                role_receipt=receipt,
            )
        else:
            _save(root, receipt)
        return receipt
    finally:
        client.close()


def _retire_bound_agent(
    spec: AgentSpec,
    binding: AgentDeclarationBinding,
    *,
    operation_id: str,
    expected_coordinator_id: str,
    expected_session_id: str,
) -> dict[str, PlainData]:
    from ._agent_process_supervisor import (
        AgentProcessSupervisorError,
        retained_supervisor_guard,
    )
    from ._managed_local import ManagedLocalError
    from ._agent_session_journal import _RemoteAgentJournal
    from .agent_session_transport import (
        AgentTlsClientConfig,
        _exchange_agent_request,
        _has_retained_agent_work,
        _reconcile_retirement_poll,
        _retire_agent_session,
    )
    from .deployment import _OUTBOUND_POLL_WAIT_MS

    root = spec.agent_root
    expected: dict[str, PlainData] = {
        "role": "agent",
        "operation_id": operation_id,
        "coordinator_id": expected_coordinator_id,
        "session_id": expected_session_id,
        "immutable_fingerprint": binding.immutable_fingerprint,
        "active_fingerprint": binding.active_fingerprint,
    }
    prior = retirement_receipt(root)
    if prior is not None:
        if any(prior.get(key) != value for key, value in expected.items()):
            raise QueueConflictError("retirement operation or role binding changed")
        with retired_role_guard(root, prior):
            if read_agent_declaration_binding(root, spec.declaration_digest) != binding:
                raise QueueConflictError("agent declaration changed during retirement")
            return prior

    journal = _RemoteAgentJournal(
        root,
        expected_configuration_fingerprint=binding.immutable_fingerprint,
        expected_active_configuration_fingerprint=binding.active_fingerprint,
    )
    try:
        if read_agent_declaration_binding(root, spec.declaration_digest) != binding:
            raise QueueConflictError("agent declaration changed during retirement")
        with journal._connection() as conn:
            row = conn.execute(
                "SELECT value_json,state FROM agent_sessions_local WHERE session_id=?",
                (expected_session_id,),
            ).fetchone()
            other = conn.execute(
                "SELECT 1 FROM agent_sessions_local WHERE session_id!=? "
                "AND state IN ('ACTIVE','RETIRING') LIMIT 1",
                (expected_session_id,),
            ).fetchone()
        if row is None:
            raise QueueConflictError("retirement session or coordinator changed")
        session = json.loads(row["value_json"])
        if (
            not isinstance(session, dict)
            or session.get("coordinator_id") != expected_coordinator_id
            or session.get("agent_root_id") != binding.root_id
            or session.get("session_id") != expected_session_id
            or other is not None
            or row["state"] not in {"ACTIVE", "RETIRING", "RETIRED_CLEAN"}
        ):
            raise QueueConflictError("retirement session or coordinator changed")

        execution, slurm = _retained_agent_owners(spec)
        if (
            _has_retained_agent_work(None, execution, slurm)
            or journal.unresolved_assignment_references()
        ):
            raise QueueConflictError("agent has retained work")

        declarations = spec.declarations
        transport = AgentTlsClientConfig(
            cast(str, declarations["url"]),
            Path(cast(str, declarations["server_ca_path"])),
            Path(cast(str, declarations["certificate_path"])),
            Path(cast(str, declarations["private_key_path"])),
        )

        def exchange(
            operation: str, value: Mapping[str, PlainData]
        ) -> Mapping[str, PlainData]:
            body = json.dumps(
                value, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            return _exchange_agent_request(
                transport, operation, body, "agent", None, False
            ).value

        _reconcile_retirement_poll(
            journal,
            exchange,
            expected_session_id,
            wait_timeout_ms=_OUTBOUND_POLL_WAIT_MS,
        )
        if _has_retained_agent_work(journal, execution, slurm):
            raise QueueConflictError("agent has retained work")

        from contextlib import nullcontext

        guard = (
            retained_supervisor_guard(root, agent_id=binding.root_id)
            if spec.declarations["resident_profiles"] or (root / "supervisor").exists()
            else nullcontext()
        )
        with guard:
            receipt = {**expected, "root_id": journal.root_id, "state": "retired"}
            if row["state"] != "RETIRED_CLEAN":
                _retire_agent_session(
                    journal,
                    exchange,
                    expected_session_id,
                    idempotency_key=operation_id,
                    role_receipt=receipt,
                )
            else:
                _save(root, receipt)
            return receipt
    except (
        AgentProcessSupervisorError,
        ManagedLocalError,
        sqlite3.Error,
        OSError,
    ) as exc:
        raise QueueServiceError(
            "native retirement ownership is unavailable or unsettled"
        ) from exc
    finally:
        journal.close()


def _identifiers(*values: str) -> None:
    if any(not isinstance(v, str) or not v or len(v) > 512 for v in values):
        raise QueueServiceError(
            "retirement identities must be nonempty bounded strings"
        )


@contextmanager
def retired_role_guard(root: Path, receipt: Mapping[str, PlainData]) -> Iterator[None]:
    """Hold native ownership while a caller archives/deletes a retired root.

    The receipt must match the exact durable root. This is not permission to
    delete any other path. Callers must separately validate their cleanup scope.
    """
    import fcntl
    from contextlib import ExitStack
    from .local_daemon import _acquire_lock, _open_root

    with ExitStack() as stack:
        stack.enter_context(_acquire_lock(root))
        if retirement_receipt(root) != dict(receipt):
            raise QueueConflictError("retirement receipt differs from the native root")
        kind = "coordinator" if receipt.get("role") == "coordinator" else "local-agent"
        if _open_root(root, role=kind) != receipt.get("root_id"):
            raise QueueConflictError("retirement belongs to another native identity")
        supervisor = root / "supervisor"
        if supervisor.exists():
            lock = stack.enter_context((supervisor / "service.lock").open("a+"))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise QueueConflictError("retired supervisor is still owned") from exc
        yield
