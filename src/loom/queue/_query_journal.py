"""Bounded journal candidates before authority acquisition for native queries."""

from collections.abc import Mapping
from typing import Any

from loom.runs._query_page import after_cursor
from loom.runs.query import QUERY_LIMITS, RunQuery, QueryError, timestamp

_OPERATION_COLUMNS = (
    "operation_id, principal_id, accepted_at, state, kind, queue_item_id, "
    "json_extract(result_json, '$.prepared_run.run_uri') AS run_uri"
)


def journal_predicate(value: Any, fields: set[str]) -> tuple[str, list[Any]]:
    """Conservative necessary condition; full typed evaluation remains authoritative.

    AND can use a supported subset. OR must retain every branch; NOT is left
    to the evaluator because unknown/missing facts use three-valued semantics.
    Only journal-owned string equality is pushed down, with bound parameters.
    """
    if not isinstance(value, Mapping):
        return "1", []
    kind = value.get("kind")
    if kind in {"all", "any"}:
        parts = [journal_predicate(term, fields) for term in value["terms"]]
        if not parts:
            return ("1" if kind == "all" else "0"), []
        return "(" + (" AND " if kind == "all" else " OR ").join(p[0] for p in parts) + ")", [v for p in parts for v in p[1]]
    field = value.get("field", {})
    path = field.get("path", ())
    if (kind != "compare" or field.get("source") != "native"
            or len(path) != 1 or path[0] not in fields):
        return "1", []
    values = value["value"] if value["op"] == "in" else [value["value"]]
    if value["op"] not in {"eq", "in"} or not all(isinstance(v, str) for v in values):
        return "1", []
    return f'{path[0]} IN ({",".join("?" for _ in values)})', list(values)


def journal_candidates(daemon: Any, query: RunQuery, owner: str) -> list[dict[str, Any]]:
    """Read at most 501 rows, using the public keyset and null-last ordering."""
    submissions = query.entity == "submissions"
    table = "preparation_operations" if submissions else "managed_admissions"
    columns = _OPERATION_COLUMNS if submissions else "*"
    fields = {"operation_id", "principal_id", "state", "kind", "queue_item_id"} if submissions else {"admission_id", "queue_item_id", "state", "run_uri"}
    return _ordered_rows(daemon, query, owner, table, columns, fields)


def _ordered_rows(
    daemon: Any, query: RunQuery, owner: str, table: str, columns: str,
    fields: set[str], *, sql_prefix: str = "",
) -> list[dict[str, Any]]:
    where, args = journal_predicate(query.to_dict()["where"], fields)
    last = after_cursor(query, owner)
    expressions = []
    for order in query.order_by:
        column = "accepted_at" if query.entity == "submissions" and order.field == "submitted_at" else order.field
        expressions.append(f"query_timestamp({column}) COLLATE loom_query_timestamp" if column.endswith("_at") else column)
    ordering = []
    for expression, order in zip(expressions, query.order_by):
        ordering.extend((f"({expression}) IS NULL ASC", f"{expression} {'DESC' if order.descending else 'ASC'}"))
    if last is not None:
        alternatives = []
        cursor_args = []
        for index, (expression, order, value) in enumerate(zip(expressions, query.order_by, last)):
            if value is None:
                continue  # Null is last in both directions.
            prefix = []
            for prior, prior_value in zip(expressions[:index], last[:index]):
                prefix.append(f"({prior}) IS NULL" if prior_value is None else f"({prior}) = ?")
                if prior_value is not None:
                    cursor_args.append(prior_value)
            prefix.append(f"(({expression}) IS NULL OR ({expression}) {'<' if order.descending else '>'} ?)")
            cursor_args.append(value)
            alternatives.append("(" + " AND ".join(prefix) + ")")
        where += " AND (" + (" OR ".join(alternatives) or "0") + ")"
        args.extend(cursor_args)

    def valid_timestamp(value):
        try:
            timestamp(value)
            return value
        except QueryError:
            return None

    def compare_timestamp(a, b):
        left, right = timestamp(a), timestamp(b)
        return (left > right) - (left < right)

    # Connections and transactions never reach authority or filesystem readers.
    with daemon._connection() as conn:
        conn.create_function("query_timestamp", 1, valid_timestamp, deterministic=True)
        conn.create_collation("loom_query_timestamp", compare_timestamp)
        return [dict(row) for row in conn.execute(
            sql_prefix + f"SELECT {columns} FROM {table} WHERE {where} ORDER BY {', '.join(ordering)} LIMIT ?",
            (*args, QUERY_LIMITS["candidates"] + 1),
        )]


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
    return _ordered_rows(daemon, query, owner, "candidates", "*", {"run_uri"}, sql_prefix=prefix)
