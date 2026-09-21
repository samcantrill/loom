"""Durable action claims and graph demands in the native coordinator store.

This owner performs bounded database mutations only. Authority reads, artifact
hashing, installed verification and process control belong to its caller and are
joined through retained claim revisions and original producer identities.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, contextmanager
import json
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from loom.fingerprints import hash_mapping
from loom.serialization import PlainData, stable_json_bytes

from .errors import QueueConflictError


def initialize_action_results(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE action_claims (
        claim_id TEXT PRIMARY KEY, scope_key TEXT NOT NULL,
        execution_key TEXT NOT NULL, scope_json TEXT NOT NULL,
        identity_json TEXT NOT NULL, owner_run_uri TEXT NOT NULL,
        owner_node TEXT NOT NULL, attempt_id TEXT, assignment_id TEXT,
        fencing_token TEXT, state TEXT NOT NULL, revision INTEGER NOT NULL,
        result_json TEXT, failure_json TEXT,
        UNIQUE(scope_key, execution_key))""")
    conn.execute("""CREATE TABLE action_demands (
        run_uri TEXT NOT NULL, node TEXT NOT NULL,
        claim_id TEXT NOT NULL REFERENCES action_claims(claim_id),
        state TEXT NOT NULL, binding_json TEXT,
        PRIMARY KEY(run_uri, node))""")
    conn.execute("CREATE INDEX action_demands_claim ON action_demands(claim_id, state)")
    conn.execute("""CREATE TABLE action_graph_cancellations (
        run_uri TEXT PRIMARY KEY, operation_id TEXT NOT NULL)""")


class ActionResults:
    """One store/principal/installation-scoped native selection owner."""

    def __init__(
        self, connection: Callable[[], AbstractContextManager[sqlite3.Connection]]
    ):
        self.connection = connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def select(
        self,
        *,
        run_uri: str,
        node: str,
        scope: Mapping[str, PlainData],
        identity: Mapping[str, PlainData],
        attempt_id: str | None = None,
        retry_authorized: bool = False,
    ) -> dict[str, Any]:
        scope_key, execution_key = hash_mapping(scope), identity["digest"]
        with self.transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM action_graph_cancellations WHERE run_uri = ?", (run_uri,)
            ).fetchone():
                raise QueueConflictError("cancelled graph cannot attach action demand")
            demand = conn.execute(
                "SELECT * FROM action_demands WHERE run_uri = ? AND node = ?",
                (run_uri, node),
            ).fetchone()
            if demand is not None:
                claim = _claim(conn, demand["claim_id"])
                if (
                    claim["scope_key"] != scope_key
                    or claim["execution_key"] != execution_key
                ):
                    raise QueueConflictError(
                        "retained action demand identity conflicts"
                    )
                if (
                    retry_authorized
                    and claim["state"] == "failed"
                    and (claim["owner_run_uri"], claim["owner_node"]) == (run_uri, node)
                ):
                    if attempt_id is None or attempt_id == claim["attempt_id"]:
                        raise QueueConflictError(
                            "action retry requires a new authorized attempt"
                        )
                    conn.execute(
                        "UPDATE action_claims SET state = 'owned', attempt_id = ?, assignment_id = NULL, fencing_token = NULL, failure_json = NULL, revision = revision + 1 WHERE claim_id = ?",
                        (attempt_id, claim["claim_id"]),
                    )
                    conn.execute(
                        "UPDATE action_demands SET state = 'live' WHERE run_uri = ? AND node = ?",
                        (run_uri, node),
                    )
                    claim = _claim(conn, claim["claim_id"])
                    demand = {"state": "live", "binding_json": None}
                elif (
                    retry_authorized
                    and demand["state"] == "failed"
                    and claim["state"] in {"owned", "succeeded"}
                ):
                    conn.execute(
                        "UPDATE action_demands SET state = 'live' WHERE run_uri = ? AND node = ?",
                        (run_uri, node),
                    )
                    demand = {"state": "live", "binding_json": None}
                return _selection(claim, demand, run_uri, node)
            row = conn.execute(
                "SELECT * FROM action_claims WHERE scope_key = ? AND execution_key = ?",
                (scope_key, execution_key),
            ).fetchone()
            if row is None:
                claim_id = uuid4().hex
                conn.execute(
                    "INSERT INTO action_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'owned', 1, NULL, NULL)",
                    (
                        claim_id,
                        scope_key,
                        execution_key,
                        _json(scope),
                        _json(identity),
                        run_uri,
                        node,
                        attempt_id,
                    ),
                )
                row = _claim(conn, claim_id)
            else:
                row = dict(row)
            state = (
                "failed"
                if row["state"] in {"failed", "settling", "cancelled"}
                else "live"
            )
            conn.execute(
                "INSERT INTO action_demands VALUES (?, ?, ?, ?, NULL)",
                (run_uri, node, row["claim_id"], state),
            )
            demand = {"state": state, "binding_json": None}
            return _selection(row, demand, run_uri, node)

    def claim(self, claim_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            return _claim(conn, claim_id)

    def owner(self, run_uri: str, node: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM action_claims WHERE owner_run_uri = ? AND owner_node = ?",
                (run_uri, node),
            ).fetchone()
            return None if row is None else dict(row)

    def attach_fence(
        self,
        claim_id: str,
        *,
        run_uri: str,
        node: str,
        attempt_id: str,
        assignment_id: str,
        fencing_token: str,
    ) -> None:
        with self.transaction() as conn:
            claim = _claim(conn, claim_id)
            if (claim["owner_run_uri"], claim["owner_node"]) != (run_uri, node):
                raise QueueConflictError("action producer identity conflicts")
            fence = (attempt_id, assignment_id, fencing_token)
            retained = tuple(
                claim[key] for key in ("attempt_id", "assignment_id", "fencing_token")
            )
            if retained == fence:
                return
            if claim["state"] != "owned" or retained not in {
                (None, None, None),
                (attempt_id, None, None),
            }:
                raise QueueConflictError("action producer fence conflicts")
            conn.execute(
                "UPDATE action_claims SET attempt_id = ?, assignment_id = ?, fencing_token = ?, revision = revision + 1 WHERE claim_id = ?",
                (*fence, claim_id),
            )

    def publish(
        self,
        claim_id: str,
        *,
        result: Mapping[str, PlainData],
        attempt_id: str,
        assignment_id: str,
        fencing_token: str,
    ) -> None:
        """Retain a native verified successful commit after its authority handoff."""
        encoded = _json(result)
        with self.transaction() as conn:
            claim = _claim(conn, claim_id)
            if tuple(
                claim[key] for key in ("attempt_id", "assignment_id", "fencing_token")
            ) != (attempt_id, assignment_id, fencing_token):
                raise QueueConflictError("action result producer fence conflicts")
            if claim["result_json"] is not None:
                if claim["result_json"] != encoded:
                    raise QueueConflictError("immutable action result conflicts")
                return
            if claim["state"] not in {"owned", "settling"}:
                raise QueueConflictError("action claim cannot publish a result")
            conn.execute(
                "UPDATE action_claims SET state = 'succeeded', result_json = ?, revision = revision + 1 WHERE claim_id = ?",
                (encoded, claim_id),
            )

    def fail(
        self,
        claim_id: str,
        failure: Mapping[str, PlainData],
        *,
        expected_revision: int | None = None,
    ) -> None:
        with self.transaction() as conn:
            claim = _claim(conn, claim_id)
            if expected_revision is not None and claim["revision"] != expected_revision:
                return
            if claim["state"] in {"succeeded", "failed", "cancelled"}:
                return
            state = "cancelled" if claim["state"] == "settling" else "failed"
            conn.execute(
                "UPDATE action_claims SET state = ?, failure_json = ?, revision = revision + 1 WHERE claim_id = ?",
                (state, _json(failure), claim_id),
            )

    def bind(
        self,
        *,
        run_uri: str,
        node: str,
        claim_id: str,
        expected_revision: int,
        result: Mapping[str, PlainData],
        verification: Mapping[str, PlainData],
    ) -> dict[str, PlainData]:
        """Publish a consumer binding after external verification and rechecks."""
        with self.transaction() as conn:
            claim = _claim(conn, claim_id)
            demand = conn.execute(
                "SELECT * FROM action_demands WHERE run_uri = ? AND node = ?",
                (run_uri, node),
            ).fetchone()
            if (
                demand is None
                or demand["claim_id"] != claim_id
                or demand["state"] not in {"live", "bound"}
            ):
                raise QueueConflictError("action demand is no longer live")
            if (
                claim["state"] != "succeeded"
                or claim["revision"] != expected_revision
                or claim["result_json"] != _json(result)
            ):
                raise QueueConflictError(
                    "verified action candidate changed before binding"
                )
            binding: dict[str, PlainData] = {
                "schema_version": 1,
                "claim_id": claim_id,
                "execution_key": claim["execution_key"],
                "origin_run_uri": claim["owner_run_uri"],
                "origin_node_id": claim["owner_node"],
                "result": dict(result),
                "verification": dict(verification),
            }
            encoded = _json(binding)
            if demand["binding_json"] is not None and demand["binding_json"] != encoded:
                raise QueueConflictError("immutable consumer action binding conflicts")
            conn.execute(
                "UPDATE action_demands SET state = 'bound', binding_json = ? WHERE run_uri = ? AND node = ?",
                (encoded, run_uri, node),
            )
            return binding

    def detach_graph(
        self, run_uri: str, operation_id: str
    ) -> tuple[dict[str, Any], ...]:
        """Replay demand detachment using the native coordinator transaction."""
        with self.transaction() as conn:
            return detach_action_graph(conn, run_uri, operation_id)

    def producer_needed(self, run_uri: str, node: str) -> bool:
        with self.connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM action_claims c JOIN action_demands d ON d.claim_id = c.claim_id WHERE c.owner_run_uri = ? AND c.owner_node = ? AND c.state = 'owned' AND d.state = 'live' LIMIT 1",
                    (run_uri, node),
                ).fetchone()
                is not None
            )

    def producers(self, run_uri: str) -> tuple[dict[str, Any], ...]:
        with self.connection() as conn:
            return tuple(
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM action_claims WHERE owner_run_uri = ?", (run_uri,)
                )
            )


def detach_action_graph(
    conn: sqlite3.Connection, run_uri: str, operation_id: str
) -> tuple[dict[str, Any], ...]:
    """Atomically detach demands with acceptance of the graph cancellation."""
    previous = conn.execute(
        "SELECT operation_id FROM action_graph_cancellations WHERE run_uri = ?",
        (run_uri,),
    ).fetchone()
    if previous is not None and previous[0] != operation_id:
        raise QueueConflictError("action graph cancellation identity conflicts")
    conn.execute(
        "INSERT OR IGNORE INTO action_graph_cancellations VALUES (?, ?)",
        (run_uri, operation_id),
    )
    ids = tuple(
        row[0]
        for row in conn.execute(
            "SELECT claim_id FROM action_demands WHERE run_uri = ?", (run_uri,)
        )
    )
    conn.execute(
        "UPDATE action_demands SET state = 'detached' WHERE run_uri = ?", (run_uri,)
    )
    settling = []
    for claim_id in ids:
        claim = _claim(conn, claim_id)
        live = conn.execute(
            "SELECT 1 FROM action_demands WHERE claim_id = ? AND state = 'live' LIMIT 1",
            (claim_id,),
        ).fetchone()
        if live is None and claim["state"] == "owned":
            conn.execute(
                "UPDATE action_claims SET state = 'settling', revision = revision + 1 WHERE claim_id = ?",
                (claim_id,),
            )
            claim = _claim(conn, claim_id)
        if claim["state"] == "settling":
            settling.append(claim)
    return tuple(settling)


def cancel_action_producer(
    conn: sqlite3.Connection, run_uri: str, attempt_id: str
) -> None:
    """Administrative containment revokes shared continuation for one attempt."""
    conn.execute(
        "UPDATE action_claims SET state = 'settling', revision = revision + 1 "
        "WHERE owner_run_uri = ? AND attempt_id = ? AND state = 'owned'",
        (run_uri, attempt_id),
    )


def action_attempt_needed(
    conn: sqlite3.Connection, run_uri: str, attempt_id: str
) -> bool:
    """Read the exact live-demand decision in the caller's launch transaction."""
    return (
        conn.execute(
            "SELECT 1 FROM action_claims c JOIN action_demands d ON d.claim_id = c.claim_id WHERE c.owner_run_uri = ? AND c.attempt_id = ? AND c.state = 'owned' AND d.state = 'live' LIMIT 1",
            (run_uri, attempt_id),
        ).fetchone()
        is not None
    )


def action_attempt_cancelled(
    conn: sqlite3.Connection, run_uri: str, attempt_id: str
) -> bool:
    """A settling claim or an unexempted graph cancellation denies launch."""
    claim = conn.execute(
        "SELECT state FROM action_claims WHERE owner_run_uri = ? AND attempt_id = ?",
        (run_uri, attempt_id),
    ).fetchone()
    if claim is not None and claim[0] in {"settling", "cancelled"}:
        return True
    cancellation = conn.execute(
        "SELECT cancellation_operation_id FROM managed_admissions WHERE run_uri = ?",
        (run_uri,),
    ).fetchone()
    return (
        cancellation is not None
        and cancellation[0] is not None
        and not action_attempt_needed(conn, run_uri, attempt_id)
    )


def attach_action_fence(
    conn: sqlite3.Connection,
    run_uri: str,
    attempt_id: str,
    assignment_id: str,
    fencing_token: str,
) -> None:
    """Join a native grant without opening a nested coordinator write transaction."""
    row = conn.execute(
        "SELECT claim_id, state, assignment_id, fencing_token FROM action_claims WHERE owner_run_uri = ? AND attempt_id = ?",
        (run_uri, attempt_id),
    ).fetchone()
    if row is None:
        return
    if (row[2], row[3]) == (assignment_id, fencing_token):
        return
    if row[1] != "owned" or (row[2], row[3]) != (None, None):
        raise QueueConflictError("action producer fence conflicts")
    conn.execute(
        "UPDATE action_claims SET assignment_id = ?, fencing_token = ?, revision = revision + 1 WHERE claim_id = ?",
        (assignment_id, fencing_token, row[0]),
    )


def _claim(conn: sqlite3.Connection, claim_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM action_claims WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row is None:
        raise QueueConflictError("action claim is unavailable")
    return dict(row)


def _selection(
    claim: Mapping[str, Any], demand: Mapping[str, Any], run_uri: str, node: str
) -> dict[str, Any]:
    decision = (
        "bound"
        if demand["state"] == "bound"
        else "failed"
        if demand["state"] in {"failed", "detached"}
        or claim["state"] in {"failed", "settling", "cancelled"}
        else "candidate"
        if claim["state"] == "succeeded"
        else "owner"
        if (claim["owner_run_uri"], claim["owner_node"]) == (run_uri, node)
        else "wait"
    )
    return {
        "decision": decision,
        "claim": dict(claim),
        "binding": None
        if demand["binding_json"] is None
        else json.loads(demand["binding_json"]),
    }


def _json(value: Mapping[str, PlainData]) -> str:
    return stable_json_bytes(dict(value)).decode("utf-8")
