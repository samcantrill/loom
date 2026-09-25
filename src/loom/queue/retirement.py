"""Explicit, irreversible role retirement before operator-owned storage disposal.

Loom proves native quiescence and fences reuse; callers own service stopping,
credential revocation, archives and deletion. No function here removes files.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING

from loom.serialization import PlainData

from .errors import QueueConflictError, QueueServiceError

if TYPE_CHECKING:
    from .deployment import OutboundAgentServiceConfig


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
    config: OutboundAgentServiceConfig,
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
    """
    from .agent_session_transport import LocalDaemonAgentHttpClient
    from .deployment import OutboundAgentServiceConfig

    if (
        not isinstance(config, OutboundAgentServiceConfig)
        or config.client.agent_root is None
    ):
        raise QueueServiceError("outbound service configuration is required")
    _identifiers(operation_id, expected_coordinator_id, expected_session_id)
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
        # This checks all local retained owners, not just foreground processes.
        client.shutdown_clean()
        if row["state"] != "RETIRED_CLEAN":
            client.retire_clean(expected_session_id, idempotency_key=operation_id)
        receipt = {**expected, "root_id": journal.root_id, "state": "retired"}
        _save(root, receipt)
        return receipt
    finally:
        client.close()


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
