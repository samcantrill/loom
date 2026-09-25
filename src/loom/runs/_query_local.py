"""Explicit configured or locally opened collection discovery."""

from __future__ import annotations

from functools import cmp_to_key
from pathlib import Path
from typing import Any

from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.errors import StoreError

from ._query_acquire import acquire_run, needs_notes
from ._query_page import after_cursor, search_page
from .query import (
    QueryError,
    QueryRecord,
    RunQuery,
    UNAVAILABLE,
    compare_keys,
    timestamp,
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

    try:
        candidates = []
        for path in root.iterdir():
            if path.name == ".loom_catalog":
                continue
            if not path.is_dir() or not (path / "run.json").exists():
                warnings.append({"code": "partial_run", "path": str(path)})
                continue
            candidates.append(path_to_run_uri(path))
    except OSError:
        candidates = []
        warnings.append({"code": "collection_unavailable"})
    keyed = []
    for uri in candidates:
        keys = []
        for order in query.order_by:
            value = uri if order.field == "run_uri" else UNAVAILABLE
            if order.field == "created_at":
                try:
                    value = store.read_run_document(uri).get("created_at", UNAVAILABLE)
                except (OSError, ValueError, LookupError, StoreError):
                    pass
            if order.field.endswith("_at") and value is not UNAVAILABLE:
                try:
                    timestamp(value)
                except QueryError:
                    value = UNAVAILABLE
            if value is UNAVAILABLE:
                warnings.append(
                    {
                        "code": "sort_fact_unavailable",
                        "run_uri": uri,
                        "field": order.field,
                    }
                )
                value = None
            keys.append(value)
        keyed.append((tuple(keys), uri))
    keyed.sort(key=cmp_to_key(lambda a, b: compare_keys(a[0], b[0], query.order_by)))
    return search_page(query, owner, keyed, acquire, warnings=warnings)
