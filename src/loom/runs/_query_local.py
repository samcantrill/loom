"""Explicit configured or locally opened collection discovery."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from loom.pipeline.stores.errors import StoreError

from ._query_acquire import acquire_run, needs_notes
from ._query_page import after_cursor, search_page
from .query import (
    QueryError,
    QueryRecord,
    RunQuery,
    UNAVAILABLE,
)


def search_collection(
    root: Path,
    query: RunQuery,
    *,
    owner: str | None = None,
    authority_factory: Any = None,
):
    from ._scan import _authority_scan_context, _authority_store_for_candidate
    from loom.pipeline.stores import LocalRunStore

    query = query.checked()
    if (
        query.scope != {"kind": "collection", "name": "run_store"}
        or query.entity != "runs"
    ):
        raise QueryError("local catalog search requires collection scope")
    owner = owner or root.resolve().as_uri()
    after_cursor(query, owner)
    warnings: list[dict[str, Any]] = []
    store = LocalRunStore(root)
    context = _authority_scan_context() if authority_factory is None else None
    cache: dict[str, QueryRecord] = {}

    def acquire(uri: str) -> QueryRecord:
        if uri in cache:
            return cache[uri]
        try:
            if authority_factory is not None:
                authority = authority_factory(uri)
            else:
                from loom.io.uris import uri_to_path

                assert context is not None
                authority, warning = _authority_store_for_candidate(
                    uri, uri_to_path(uri), store, context
                )
                if warning is not None:
                    warnings.append({"code": str(warning.code), "run_uri": uri})
            record = acquire_run(root, uri, authority, include_notes=needs_notes(query))
        except (OSError, ValueError, LookupError, StoreError):
            record = QueryRecord(
                {"native": {"run_uri": uri}},
                warnings=[{"code": "record_unavailable", "run_uri": uri}],
            )
        record.sources["native"]["submitted_at"] = UNAVAILABLE
        cache[uri] = record
        return record

    from loom.pipeline.stores._run_discovery_index import connection
    from ._query_sql import ordered_rows

    try:
        with connection(root) as conn:
            refreshed = conn.execute("SELECT refreshed FROM discovery_metadata").fetchone()[0]
        if not refreshed:
            warnings.append({"code": "discovery_refresh_required"})
        candidates = ordered_rows(
            partial(connection, root), query, owner,
            "(SELECT run_uri, created_at, NULL AS submitted_at FROM discovery_runs)",
            "*", {"run_uri"},
        )
    except StoreError:
        candidates = []
        warnings.append({"code": "discovery_index_unavailable" if root.is_dir() else "collection_unavailable"})
    keyed = []
    for row in candidates:
        for order in query.order_by:
            if row[order.field] is None:
                warnings.append({'code': 'sort_fact_unavailable', 'run_uri': row['run_uri'],
                                 'field': order.field})
        keyed.append((tuple(row[order.field] for order in query.order_by), row['run_uri']))
    return search_page(query, owner, keyed, acquire, warnings=warnings)
