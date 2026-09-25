"""Native discovery acquisition over coordinator journals and authority owners."""

from __future__ import annotations

import json
from dataclasses import replace
from functools import cmp_to_key
from typing import Any

from loom.pipeline.stores.errors import StoreError
from .errors import QueueError

from loom.runs._query_acquire import acquire_run, needs_notes
from loom.runs._query_page import QueryPage, search_page
from loom.runs.query import (
    JobQuery,
    Order,
    QueryError,
    QueryRecord,
    RunQuery,
    SubmissionQuery,
    UNAVAILABLE,
    compare_keys,
    identity_field,
    query_fields,
    timestamp,
)


QUERY_OPERATIONS = frozenset(
    {
        "search_runs",
        "search_submissions",
        "search_jobs",
        "query_fields",
        "tag_keys",
        "tag_values",
    }
)


def validate_query_request(operation: str, payload: Any) -> dict[str, Any]:
    if operation == "query_fields":
        if set(payload) != {"entity"}:
            raise QueryError("field discovery requires entity")
        query_fields(payload["entity"])
        return dict(payload)
    if operation in {"tag_keys", "tag_values"}:
        required = {"scope", "limit", "cursor"} | (
            {"key"} if operation == "tag_values" else set()
        )
        if set(payload) != required or (
            operation == "tag_values" and not isinstance(payload["key"], str)
        ):
            raise QueryError("invalid vocabulary request")
        query = RunQuery(
            scope=payload["scope"], limit=payload["limit"], cursor=payload["cursor"]
        ).checked()
        return {**payload, "scope": query.scope}
    if set(payload) != {"query"}:
        raise QueryError("search requires query")
    model = {
        "search_runs": RunQuery,
        "search_submissions": SubmissionQuery,
        "search_jobs": JobQuery,
    }[operation]
    return {"query": model.from_dict(payload["query"])}


def _journal(daemon: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Release the read transaction before any authority or filesystem access.
    with daemon._connection() as conn:
        operations = [
            dict(row)
            for row in conn.execute(
                "SELECT operation_id, principal_id, accepted_at, state, kind, queue_item_id, json_extract(result_json, '$.prepared_run.run_uri') AS run_uri FROM preparation_operations"
            )
        ]
        admissions = [
            dict(row) for row in conn.execute("SELECT * FROM managed_admissions")
        ]
    return operations, admissions


def _operation(row: dict[str, Any], owner: str) -> dict[str, Any]:
    return {
        key: row[key]
        for key in ("operation_id", "principal_id", "state", "kind", "queue_item_id")
    } | {
        "coordinator_id": owner,
        "run_uri": row["run_uri"],
        "accepted_at": row["accepted_at"]
        if row["accepted_at"] is not None
        else UNAVAILABLE,
        "submitted_at": row["accepted_at"]
        if row["accepted_at"] is not None
        else UNAVAILABLE,
    }


def search(daemon: Any, query: RunQuery) -> QueryPage:
    owner = daemon._require_started()
    if query.scope["kind"] == "collection":
        if query.entity != "runs":
            raise QueryError("collection scope has no submission or job journal")
        from loom.runs._query_local import search_collection

        return search_collection(
            daemon.config.run_store_root,
            query,
            owner=owner,
            authority_factory=daemon.config.coordinator_authority_factory,
        )
    operations, admissions = _journal(daemon)
    originals = {row["operation_id"]: row for row in operations}
    factory = daemon.config.coordinator_authority_factory
    cache: dict[str, QueryRecord] = {}

    def original_context(operation_id: str) -> dict[str, Any]:
        with daemon._connection() as conn:
            row = conn.execute(
                "SELECT request_json FROM preparation_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return json.loads(row[0]).get("context") or {
            "description": None,
            "tags": {},
            "metadata": {},
        }

    def run_record(uri: str) -> QueryRecord:
        if uri in cache:
            return cache[uri]
        try:
            authority = factory(uri) if factory is not None else None
        except (OSError, ValueError, LookupError):
            authority = None
        record = acquire_run(
            daemon.config.run_store_root,
            uri,
            authority,
            include_notes=needs_notes(query),
        )
        native = record.sources["native"]
        original = (
            originals.get(native.get("operation_id"))
            if native.get("coordinator_id") == owner
            else None
        )
        if original is not None:
            native.update(
                submitted_at=original["accepted_at"] or UNAVAILABLE,
                principal_id=original["principal_id"],
            )
            record.sources["submission.context"] = original_context(
                original["operation_id"]
            )
        else:
            native["submitted_at"] = native["principal_id"] = UNAVAILABLE
        cache[uri] = record
        return record

    candidates: list[dict[str, Any]]
    by_submission = query.entity == "runs" and any(
        order.field == "submitted_at" for order in query.order_by
    )
    if query.entity == "runs":
        uris = {row["run_uri"] for row in admissions}
        uris.update(
            native["run_uri"]
            for row in operations
            if (native := _operation(row, owner))["run_uri"]
        )
        if by_submission:
            candidates = [
                _operation(row, owner) for row in operations if row["run_uri"]
            ]
            bound = {candidate["run_uri"] for candidate in candidates}
            candidates.extend(
                {"run_uri": uri, "submitted_at": UNAVAILABLE, "operation_id": ""}
                for uri in uris - bound
            )
            # Private disambiguator advances across non-initializing submissions
            # with the same public time/run key without skipping the initializer.
            query = replace(query, order_by=(*query.order_by, Order("operation_id")))
        else:
            candidates = [{"run_uri": uri} for uri in uris]
    elif query.entity == "submissions":
        candidates = [_operation(row, owner) for row in operations]
    else:
        candidates = admissions

    def acquire(candidate: dict[str, Any]) -> QueryRecord:
        uri = candidate.get("run_uri")
        base = run_record(uri) if uri else QueryRecord({"native": {}}, stages=())
        if query.entity == "runs":
            if (
                by_submission
                and base.sources["native"].get("submitted_at", UNAVAILABLE)
                is UNAVAILABLE
            ):
                base.warnings.append(
                    {
                        "code": "sort_fact_unavailable",
                        "run_uri": uri,
                        "field": "submitted_at",
                    }
                )
            if (
                by_submission
                and candidate.get("operation_id")
                and base.sources["native"].get("operation_id")
                != candidate["operation_id"]
            ):
                return replace(base, eligible=False)
            return base
        native = {**base.sources["native"], **candidate}
        record = QueryRecord(
            {**base.sources, "native": native},
            base.stages,
            list(base.warnings),
            dict(base.observation),
        )
        if query.entity == "submissions":
            original = originals[candidate["operation_id"]]
            record.sources["submission.context"] = original_context(
                original["operation_id"]
            )
        elif query.entity == "jobs":
            try:
                detail = daemon.admission(candidate["admission_id"])
                record.sources["job_associations"] = detail.to_dict()["owners"]
            except (OSError, ValueError, LookupError, QueueError):
                record.warnings.append(
                    {
                        "code": "job_associations_unavailable",
                        "admission_id": candidate["admission_id"],
                    }
                )
        return record

    warnings: list[dict[str, Any]] = []
    keyed = []
    for candidate in candidates:
        keys = []
        for order in query.order_by:
            value = candidate.get(order.field, UNAVAILABLE)
            if (
                value is UNAVAILABLE
                and order.field == "created_at"
                and candidate.get("run_uri")
            ):
                from loom.pipeline.stores import LocalRunStore

                try:
                    value = (
                        LocalRunStore(daemon.config.run_store_root)
                        .read_run_document(candidate["run_uri"])
                        .get("created_at", UNAVAILABLE)
                    )
                except (OSError, ValueError, LookupError, StoreError):
                    pass
            if value is UNAVAILABLE and order.field == "submitted_at":
                # Submission accepted_at is the operation's own immutable time.
                value = candidate.get("accepted_at", UNAVAILABLE)
            if order.field.endswith("_at") and value is not UNAVAILABLE:
                try:
                    timestamp(value)
                except QueryError:
                    value = UNAVAILABLE
            if value is UNAVAILABLE:
                warnings.append(
                    {
                        "code": "sort_fact_unavailable",
                        "identity": candidate[identity_field(query.entity)],
                        "field": order.field,
                    }
                )
                value = None
            keys.append(value)
        keyed.append((tuple(keys), candidate))
    keyed.sort(key=cmp_to_key(lambda a, b: compare_keys(a[0], b[0], query.order_by)))
    return search_page(query, owner, keyed, acquire, warnings=warnings)


def query_operation(daemon: Any, operation: str, value: dict[str, Any]) -> Any:
    if operation == "query_fields":
        return query_fields(value["entity"])
    if operation.startswith("search_"):
        return search(daemon, value["query"])
    from loom.runs._query_vocabulary import vocabulary_page

    return vocabulary_page(
        lambda q: search(daemon, q), operation, value, daemon._require_started()
    )
