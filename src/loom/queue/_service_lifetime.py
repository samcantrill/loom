"""Coordinator-owned startup attachments and accepted-work quiescence.

The extensible role metadata retains configuration and bounded, unaccepted
attachments. Accepted operations and assignments remain owned by their native
stores; this module never infers their lifetime from process presence.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING
from pathlib import Path

from .errors import QueueServiceError

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon


class ServiceRetiring(QueueServiceError):
    """Acceptance lost the serialized race to clean retirement; reconnect."""


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
        with self.daemon._cycle_lock, self.daemon._connection() as conn:
            self.require_accepting()
            if expires_at <= time.time() or expires_at > time.time() + 300:
                raise QueueServiceError("startup attachment expiry is invalid")
            conn.execute(
                "INSERT INTO daemon_metadata(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("startup-attachment:" + attachment_id, json.dumps(expires_at)),
            )
            conn.commit()
        return {"attachment_id": attachment_id, "expires_at": expires_at}

    def release(self, attachment_id: str) -> dict[str, object]:
        with self.daemon._cycle_lock, self.daemon._connection() as conn:
            conn.execute(
                "DELETE FROM daemon_metadata WHERE key = ?",
                ("startup-attachment:" + attachment_id,),
            )
            conn.commit()
        return {"attachment_id": attachment_id, "released": True}

    def retained(self) -> bool:
        """Called under the application cycle lock, including during retirement."""
        from .local_daemon_execution import local_daemon_owner_work_is_retained

        daemon = self.daemon
        daemon._require_started()
        if daemon._service_error is not None:
            raise QueueServiceError("service reconciliation is unavailable")
        with daemon._connection() as conn:
            # Terminal preparation-only history and publication pins do not retain
            # services. Run continuations stay pending until exact admission.
            queries = (
                "SELECT 1 FROM managed_admissions WHERE state NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED') LIMIT 1",
                "SELECT 1 FROM preparation_operations WHERE state NOT IN ('applied', 'failed', 'cancelled', 'conflict') LIMIT 1",
                "SELECT 1 FROM preparation_cancellations WHERE state NOT IN ('applied', 'failed', 'cancelled', 'conflict') LIMIT 1",
                "SELECT 1 FROM daemon_metadata WHERE key LIKE 'admission-retry:%' AND json_extract(value, '$.state') = 'pending' LIMIT 1",
                "SELECT 1 FROM remote_assignments WHERE state NOT IN ('RELEASED', 'FAILED', 'CANCELLED') LIMIT 1",
            )
            if any(conn.execute(query).fetchone() is not None for query in queries):
                return True
            for row in conn.execute(
                "SELECT key, value FROM daemon_metadata WHERE key LIKE 'startup-attachment:%'"
            ):
                if float(json.loads(row["value"])) > time.time():
                    return True
                conn.execute("DELETE FROM daemon_metadata WHERE key = ?", (row["key"],))
            conn.commit()
        return local_daemon_owner_work_is_retained(
            daemon.config,
            coordinator_id=daemon._require_started(),
            agent_id=daemon._agent_id,
        )

    def retire_if_idle(self) -> bool:
        with self.daemon._cycle_lock:
            if self.retiring:
                return True
            if self.retained():
                return False
            with self.daemon._connection() as conn:
                if (
                    conn.execute(
                        "SELECT 1 FROM daemon_metadata WHERE key LIKE 'service-agent:%' AND json_extract(value, '$.state') != 'closed' LIMIT 1"
                    ).fetchone()
                    is not None
                ):
                    return False
            self.retiring = True
            return True


def record_process(
    root: Path,
    *,
    stopped: bool,
    coordinator_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Record process completion evidence, never an accepted-work predicate."""
    import os
    import sqlite3

    pid = os.getpid()
    started = Path(f"/proc/{pid}/stat").read_text().split()[21]
    with sqlite3.connect(root / "control.sqlite") as conn:
        conn.execute(
            "INSERT INTO root_metadata(key,value) VALUES ('service_process',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (
                json.dumps(
                    {
                        "pid": pid,
                        "started": started,
                        "stopped": stopped,
                        "coordinator_id": coordinator_id,
                        "session_id": session_id,
                    }
                ),
            ),
        )
        conn.commit()


def retained_lifetime(root: Path, requested: str | None) -> str:
    """Resolve immutable lifetime while the caller holds the native role lock."""
    import sqlite3
    from .errors import QueueConflictError

    with sqlite3.connect(root / "control.sqlite") as conn:
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
