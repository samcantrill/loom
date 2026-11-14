"""Bounded journal candidates before authority acquisition for native queries."""

from typing import Any
from contextlib import contextmanager

from loom.runs._query_page import after_cursor
from loom.runs.query import QUERY_LIMITS, RunQuery
from loom.runs._query_sql import candidate_predicate as journal_predicate, ordered_rows

_OPERATION_COLUMNS = (
    "operation_id, principal_id, accepted_at, state, kind, queue_item_id, "
    "json_extract(result_json, '$.prepared_run.run_uri') AS run_uri"
)


def journal_candidates(daemon: Any, query: RunQuery, owner: str) -> list[dict[str, Any]]:
    """Read at most 501 rows, using the public keyset and null-last ordering."""
    submissions = query.entity == "submissions"
    table = "preparation_operations" if submissions else "managed_admissions"
    columns = _OPERATION_COLUMNS if submissions else "*"
    fields = {"operation_id", "principal_id", "state", "kind", "queue_item_id"} if submissions else {"admission_id", "queue_item_id", "state", "run_uri"}
    return ordered_rows(daemon._connection, query, owner, table, columns, fields)


def run_uri_candidates(daemon: Any, query: RunQuery, owner: str) -> list[dict[str, Any]]:
    """Page distinct managed run identities without materializing all journals."""
    where, args = journal_predicate(query.to_dict()["where"], {"run_uri"})
    last = after_cursor(query, owner)
    order = query.order_by[0]
    if last is not None:
        where += f" AND run_uri {'<' if order.descending else '>'} ?"
        args.append(last[0])
    with daemon._connection() as conn:
        return [dict(row) for row in conn.execute(
            "WITH runs AS (SELECT run_uri FROM managed_admissions UNION "
            "SELECT json_extract(result_json, '$.prepared_run.run_uri') AS run_uri FROM preparation_operations) "
            f"SELECT run_uri FROM runs WHERE run_uri IS NOT NULL AND run_uri != '' AND ({where}) "
            f"ORDER BY run_uri {'DESC' if order.descending else 'ASC'} LIMIT ?",
            (*args, QUERY_LIMITS["candidates"] + 1),
        )]


def run_submission_candidates(daemon: Any, query: RunQuery, owner: str) -> list[dict[str, Any]]:
    """Page submission sort facts; acquisition still selects the true initializer.

    Noninitializing submissions retain a private operation-ID cursor component.
    Unbound runs sort last with unavailable submission time, as before.
    """
    prefix = (
        "WITH submitted AS (SELECT operation_id, accepted_at AS submitted_at, "
        "json_extract(result_json, '$.prepared_run.run_uri') AS run_uri FROM preparation_operations), "
        "candidates AS (SELECT operation_id, submitted_at, run_uri FROM submitted WHERE run_uri IS NOT NULL AND run_uri != '' "
        "UNION ALL SELECT '', NULL, run_uri FROM managed_admissions AS a WHERE NOT EXISTS "
        "(SELECT 1 FROM submitted AS s WHERE s.run_uri = a.run_uri) GROUP BY run_uri) "
    )
    return ordered_rows(daemon._connection, query, owner, "candidates", "*", {"run_uri"}, sql_prefix=prefix)


def run_creation_candidates(daemon: Any, query: RunQuery, owner: str):
    """Join immutable creation facts before paging; never enumerate run documents."""
    from loom.pipeline.stores._run_discovery_index import connection, index_path
    from loom.pipeline.stores.errors import StoreError

    after_cursor(query, owner)
    root = daemon.config.run_store_root
    try:
        with connection(root) as conn:
            refreshed = conn.execute("SELECT refreshed FROM discovery_metadata").fetchone()[0]
    except StoreError:
        return [], [{"code": "discovery_index_unavailable"}]

    @contextmanager
    def joined_connection():
        with daemon._connection() as conn:
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("ATTACH DATABASE ? AS discovery", (index_path(root).resolve().as_uri() + "?mode=ro",))
            try:
                yield conn
            finally:
                conn.execute("DETACH DATABASE discovery")

    if any(order.field == "submitted_at" for order in query.order_by):
        prefix = (
            "WITH submitted AS (SELECT operation_id, accepted_at AS submitted_at, "
            "json_extract(result_json, '$.prepared_run.run_uri') AS run_uri FROM preparation_operations), "
            "runs AS (SELECT operation_id, submitted_at, run_uri FROM submitted WHERE run_uri IS NOT NULL AND run_uri != '' "
            "UNION ALL SELECT '', NULL, run_uri FROM managed_admissions AS a WHERE NOT EXISTS "
            "(SELECT 1 FROM submitted AS s WHERE s.run_uri = a.run_uri) GROUP BY run_uri), "
        )
    else:
        prefix = (
            "WITH runs AS (SELECT run_uri FROM managed_admissions UNION "
            "SELECT json_extract(result_json, '$.prepared_run.run_uri') AS run_uri FROM preparation_operations), "
        )
    prefix += ("candidates AS (SELECT runs.*, d.created_at FROM runs LEFT JOIN discovery.discovery_runs d "
               "ON d.run_uri=runs.run_uri WHERE runs.run_uri IS NOT NULL AND runs.run_uri != '') ")
    rows = ordered_rows(joined_connection, query, owner, "candidates", "*", {"run_uri"}, sql_prefix=prefix)
    return rows, ([] if refreshed else [{"code": "discovery_refresh_required"}])
