"""Coordinator-owned startup attachments and accepted-work quiescence.

The extensible role metadata retains configuration and bounded, unaccepted
attachments. Accepted operations and assignments remain owned by their native
stores; this module never infers their lifetime from process presence.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, NamedTuple
from pathlib import Path

from loom._sqlite_policy import SQLitePolicy, connect_existing

from ._coordinator_transactions import short_write
from .errors import QueueServiceError

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon


class ServiceRetiring(QueueServiceError):
    """Acceptance lost the serialized race to clean retirement; reconnect."""


class _OwnerGeneration(NamedTuple):
    coordinator_id: str
    coordinator_epoch: str | None
    scheduling_epoch: str | None
    agent_id: str | None
    reference_revision: int


class CoordinatorLifetime:
    def __init__(self, daemon: LocalDaemon) -> None:
        self.daemon = daemon
        self.retiring = False
        self.clean_shutdown_verified = False
        self.cleanup_blocked: str | None = None

    def require_accepting(self) -> None:
        if self.retiring:
            raise ServiceRetiring("coordinator is retiring; reconnect")

    def attach(self, attachment_id: str, expires_at: float) -> dict[str, object]:
        def apply(conn):
            self.require_accepting()
            if expires_at <= time.time() or expires_at > time.time() + 300:
                raise QueueServiceError("startup attachment expiry is invalid")
            conn.execute(
                "INSERT INTO daemon_metadata(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("startup-attachment:" + attachment_id, json.dumps(expires_at)),
            )
        short_write(self.daemon, apply)
        return {"attachment_id": attachment_id, "expires_at": expires_at}

    def release(self, attachment_id: str) -> dict[str, object]:
        def apply(conn):
            conn.execute(
                "DELETE FROM daemon_metadata WHERE key = ?",
                ("startup-attachment:" + attachment_id,),
            )
        short_write(self.daemon, apply)
        return {"attachment_id": attachment_id, "released": True}

    def _scope(self) -> _OwnerGeneration:
        daemon = self.daemon
        if daemon._service_error is not None:
            raise QueueServiceError("service reconciliation is unavailable")
        return _OwnerGeneration(
            daemon._require_started(), daemon._epoch, daemon._scheduling_epoch,
            daemon._agent_id, daemon._scheduling_reference_revision,
        )

    def sample_idle_owners(self) -> _OwnerGeneration | None:
        """Check the physical stores without holding a coordinator guard."""
        from .local_daemon_execution import local_daemon_owner_work_is_retained

        daemon = self.daemon
        with daemon._state_guard():
            scope = self._scope()
            config = daemon.config
        with daemon._connection() as conn:
            if _retained_coordinator_operations(conn):
                return None
        if local_daemon_owner_work_is_retained(config, coordinator_id=scope.coordinator_id, agent_id=scope.agent_id):
            return None
        return scope

    def retained_at(self, conn, idle_owners: _OwnerGeneration | None) -> bool:
        """Resolve a sample under the final coordinator transaction."""
        scope = self._scope()
        if idle_owners != scope or _retained_coordinator_operations(conn):
            return True
        conn.execute(
            "DELETE FROM daemon_metadata WHERE key LIKE 'startup-attachment:%' "
            "AND json_extract(value, '$') <= ?", (time.time(),),
        )
        return False

    def observe(self, agent_root_id=None) -> dict:
        sample = self.sample_idle_owners()

        def read(conn):
            result = {"coordinator_id": self.daemon._require_started(), "coordinator_epoch": self.daemon._epoch,
                      "retiring": self.retiring, "retained": self.retained_at(conn, sample),
                      "cleanup_blocked": self.cleanup_blocked}
            if agent_root_id is not None:
                row = conn.execute("SELECT value FROM daemon_metadata WHERE key=?",
                                   ("service-agent:" + agent_root_id,)).fetchone()
                result["agent"] = None if row is None else json.loads(row[0])
            return result

        return short_write(self.daemon, read)

    def retained(self) -> bool:
        sample = self.sample_idle_owners()
        return short_write(self.daemon, lambda conn: self.retained_at(conn, sample))

    def _can_retire(self, conn, sample) -> bool:
        return not self.retained_at(conn, sample) and not (
            conn.execute("SELECT 1 FROM daemon_metadata WHERE key LIKE 'service-agent:%' "
                         "AND json_extract(value, '$.state') != 'closed' LIMIT 1").fetchone()
            or conn.execute("SELECT 1 FROM agent_coordinator_references WHERE resolved=0 LIMIT 1").fetchone()
        )

    def _fence(self, accepted: bool) -> None:
        if accepted:
            self.retiring = True

    def retire_if_idle(self) -> bool:
        with self.daemon._state_guard():
            if self.retiring:
                return True
        sample = self.sample_idle_owners()
        return short_write(self.daemon, lambda conn: self.retiring or self._can_retire(conn, sample),
                           committed=self._fence)

    def retire_explicit(self, operation_id: str, coordinator_id: str) -> dict:
        """Atomically fence new acceptance and retain an operator removal receipt."""
        from .errors import QueueConflictError
        from .retirement import _identifiers

        _identifiers(operation_id, coordinator_id)
        daemon = self.daemon
        def prior_receipt(conn):
            if daemon._require_started() != coordinator_id:
                raise QueueConflictError("retirement coordinator identity changed")
            prior = conn.execute("SELECT value FROM root_metadata WHERE key='role_retirement'").fetchone()
            if prior is not None:
                receipt = json.loads(prior[0])
                if receipt["operation_id"] != operation_id:
                    raise QueueConflictError("another retirement operation owns this role")
                return receipt
            if daemon.config.agent_root is not None:
                raise QueueConflictError("retire a pure coordinator; embedded agents require separate recovery")
            return None

        with daemon._connection() as conn, daemon._state_guard():
            prior = prior_receipt(conn)
            if prior is not None:
                return prior
        sample = self.sample_idle_owners()

        def apply(conn):
            prior = prior_receipt(conn)
            if prior is not None:
                return prior
            if conn.execute("SELECT 1 FROM agent_sessions WHERE state NOT IN "
                            "('RETIRED_CLEAN','REPLACED') LIMIT 1").fetchone():
                raise QueueConflictError("coordinator still has unretired agents")
            if not self._can_retire(conn, sample):
                raise QueueConflictError("coordinator has retained work or startup attachments")
            receipt = {"role": "coordinator", "state": "retired", "operation_id": operation_id,
                       "coordinator_id": coordinator_id, "root_id": coordinator_id}
            conn.execute("INSERT INTO root_metadata(key,value) VALUES ('role_retirement',?)",
                         (json.dumps(receipt, sort_keys=True),))
            return receipt

        return short_write(daemon, apply, committed=lambda _: self._fence(True))


def record_process(
    root: Path,
    *,
    stopped: bool,
    coordinator_id: str | None = None,
    session_id: str | None = None,
    sqlite_policy: SQLitePolicy | None = None,
) -> None:
    """Record process completion evidence, never an accepted-work predicate."""
    import os
    import sqlite3

    pid = os.getpid()
    started = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    with (
        sqlite3.connect(root / "control.sqlite")
        if sqlite_policy is None
        else connect_existing(
            root / "control.sqlite", policy=sqlite_policy, isolation_level=""
        )
    ) as conn:
        conn.execute(
            "INSERT INTO root_metadata(key,value) VALUES ('service_process',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (
                json.dumps(
                    {
                        "pid": pid,
                        "capabilities": ["quiescent-profile-promotion-v2", "quiescent-source-promotion-v1", "quiescent-configuration-retirement-v1", "quiescent-container-policy-addition-v1", "quiescent-publication-budget-increase-v1"],
                        "started": started,
                        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                        "stopped": stopped,
                        "coordinator_id": coordinator_id,
                        "session_id": session_id,
                    }
                ),
            ),
        )
        conn.commit()


def retained_lifetime(
    root: Path, requested: str | None, *, sqlite_policy: SQLitePolicy | None = None,
) -> str:
    """Resolve immutable lifetime while the caller holds the native role lock."""
    import sqlite3
    from .errors import QueueConflictError

    with (
        sqlite3.connect(root / "control.sqlite")
        if sqlite_policy is None
        else connect_existing(
            root / "control.sqlite", policy=sqlite_policy, isolation_level=""
        )
    ) as conn:
        row = conn.execute(
            "SELECT value FROM root_metadata WHERE key = 'service_lifetime'"
        ).fetchone()
        lifetime = row[0] if row is not None else (requested or "persistent")
        if lifetime not in {"persistent", "run"} or (
            requested is not None and requested != lifetime
        ):
            raise QueueConflictError("service lifetime conflicts with retained role")
        conn.execute(
            "INSERT OR IGNORE INTO root_metadata(key,value) VALUES ('service_lifetime', ?)",
            (lifetime,),
        )
        conn.commit()
        return lifetime


def _retained_coordinator_operations(conn) -> bool:
    """One predicate for active and offline coordinator service ownership."""
    return _retained_coordinator_mutations(conn) or any(
        conn.execute(query).fetchone() is not None for query in (
            "SELECT 1 FROM managed_admissions WHERE state NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED') LIMIT 1",
            "SELECT 1 FROM remote_assignments WHERE state NOT IN ('RELEASED', 'FAILED', 'CANCELLED') LIMIT 1",
        )
    )


def _retained_coordinator_mutations(conn, *, recoverable_preparations: frozenset[str] = frozenset()) -> bool:
    """Retained mutations, excluding only preparations proved by recovery's owner."""
    queries = (
        "SELECT 1 FROM daemon_metadata WHERE key LIKE 'admission-retry:%' AND json_extract(value, '$.state') = 'pending' LIMIT 1",
    )
    return any(
        row[0] not in recoverable_preparations
        for query in (
            "SELECT operation_id FROM preparation_operations WHERE state NOT IN ('applied', 'failed', 'cancelled', 'conflict')",
            "SELECT target_operation_id FROM preparation_cancellations WHERE state NOT IN ('applied', 'failed', 'cancelled', 'conflict')",
        ) for row in conn.execute(query)
    ) or any(conn.execute(query).fetchone() is not None for query in queries) or any(
        float(json.loads(row[0])) > time.time()
        for row in conn.execute("SELECT value FROM daemon_metadata WHERE key LIKE 'startup-attachment:%'")
    )
