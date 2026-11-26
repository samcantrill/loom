"""Native discovery acquisition over coordinator journals and authority owners."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from contextvars import copy_context
from threading import Thread
from time import monotonic
from dataclasses import replace
from functools import cmp_to_key, lru_cache, partial
from typing import Any

from .errors import QueueError

from loom.runs._query_acquire import acquire_run, needs_notes
from loom.runs._query_page import QueryObservationDeadline, QueryPage, search_page
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


# Leave time within the ten-second HTTPS exchange for encoding and transfer.
_JOB_PAGE_SECONDS = 7.5
_JOB_READ_SECONDS = 4.0
_JOB_JOURNAL_BATCH = 16


def _job_read[T](daemon: Any, deadline: float, read: Callable[[], T]) -> T:
    """Stop waiting at the deadline even for a stalled filesystem or authority.

    A detached read keeps its daemon's slot until its actual I/O finishes.
    """
    end = min(deadline, monotonic() + _JOB_READ_SECONDS)
    left = end - monotonic()
    if left <= 0 or not daemon._job_read_slots.acquire(timeout=left):
        raise QueryObservationDeadline()
    future: Future[T] = Future()

    def run() -> None:
        try:
            if monotonic() >= end:
                raise QueryObservationDeadline()
            future.set_result(read())
        except BaseException as exc:
            future.set_exception(exc)
        finally:
            daemon._job_read_slots.release()

    try:
        Thread(target=copy_context().run, args=(run,), name="loom-job-read", daemon=True).start()
    except BaseException:
        daemon._job_read_slots.release()
        raise
    try:
        return future.result(timeout=max(0.0, end - monotonic()))
    except TimeoutError as exc:
        raise QueryObservationDeadline() from exc


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


def _job_warnings(admission_id: str, owners: Mapping[str, Any]) -> list[dict[str, Any]]:
    def warning(axis: str, diagnostic: str | None, **identity: Any) -> dict[str, Any]:
        return {
            "code": "job_associations_unavailable", "admission_id": admission_id,
            "axis": axis, "diagnostic": diagnostic, **identity,
        }

    warnings = [
        warning(axis, observation.get("diagnostic"))
        for axis, observation in owners.items()
        if isinstance(observation, Mapping) and observation.get("availability") == "unavailable"
    ]
    for assignment in owners["slurm"]["assignments"]:
        submission = assignment["submission"]
        if submission["dispatch_state"] == "unavailable" or (
            assignment["job_id"] is not None and submission["scheduler_state"] is None
        ):
            warnings.append(warning(
                "slurm", "scheduler_observation_unavailable", assignment_id=assignment["assignment_id"],
            ))
    return warnings


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
    job_deadline = monotonic() + _JOB_PAGE_SECONDS
    bounded_candidates = None
    discovery_warnings = []
    if query.entity == "runs" and any(order.field == "created_at" for order in query.order_by):
        from ._query_journal import run_creation_candidates
        if any(order.field == "submitted_at" for order in query.order_by):
            query = replace(query, order_by=(*query.order_by, Order("operation_id")))
        bounded_candidates, discovery_warnings = run_creation_candidates(daemon, query, owner)
        for candidate in bounded_candidates:
            for field in ("created_at", "submitted_at"):
                if field in candidate and candidate[field] is None:
                    candidate[field] = UNAVAILABLE
        operations, admissions = [], []
    elif query.entity == "runs" and any(order.field == "submitted_at" for order in query.order_by):
        from ._query_journal import run_submission_candidates
        query = replace(query, order_by=(*query.order_by, Order("operation_id")))
        bounded_candidates = run_submission_candidates(daemon, query, owner)
        for candidate in bounded_candidates:
            if candidate["submitted_at"] is None:
                candidate["submitted_at"] = UNAVAILABLE
        operations, admissions = [], []
    elif query.entity == "runs":
        if len(query.order_by) == 1 and query.order_by[0].field == "run_uri":
            from ._query_journal import run_uri_candidates
            operations, admissions = [], run_uri_candidates(daemon, query, owner)
        else:
            raise QueryError("unsupported run ordering")
    else:
        from ._query_journal import journal_candidates
        rows = (
            _job_read(daemon, job_deadline, partial(journal_candidates, daemon, query, owner))
            if query.entity == "jobs" else journal_candidates(daemon, query, owner)
        )
        operations, admissions = (rows, []) if query.entity == "submissions" else ([], rows)
    originals = {row["operation_id"]: row for row in operations}
    factory = daemon.config.coordinator_authority_factory
    read_snapshot = None
    acquire_metadata = acquire_run
    if query.entity == "jobs" and factory is not None:
        # A job's run metadata and owner report describe one authority revision.
        factory = lru_cache(maxsize=1)(factory)
        read_authority = factory

        @lru_cache(maxsize=1)
        def job_snapshot(uri: str):
            return read_authority(uri).open_run(uri)

        read_snapshot = job_snapshot
        acquire_metadata = partial(acquire_run, read_snapshot=job_snapshot)
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
        record = acquire_metadata(
            daemon.config.run_store_root,
            uri,
            authority,
            include_notes=needs_notes(query),
        )
        native = record.sources["native"]
        original = None
        if native.get("coordinator_id") == owner:
            operation_id = native.get("operation_id")
            original = originals.get(operation_id)
            if original is None and operation_id is not None:
                from ._query_journal import _OPERATION_COLUMNS
                with daemon._connection() as conn:
                    row = conn.execute(
                        f"SELECT {_OPERATION_COLUMNS} FROM preparation_operations WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                original = None if row is None else dict(row)
                if original is not None:
                    originals[operation_id] = original
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
    if bounded_candidates is not None:
        candidates = bounded_candidates
    elif query.entity == "runs":
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

    # Batch only shared journal data. Per-run authorities, stored results and
    # supplemental observations are opened as each candidate is examined.
    batch_size = min(query.limit, _JOB_JOURNAL_BATCH)
    job_indices = {row["admission_id"]: i for i, row in enumerate(admissions)} if query.entity == "jobs" else {}
    batch_start = -1
    owner_view = None

    def job_owners(candidate: dict[str, Any]):
        from .local_daemon import _admission_from_row
        from ._owner_journals import read_owner_journals

        nonlocal batch_start, owner_view
        offset = job_indices[candidate["admission_id"]] // batch_size * batch_size
        if offset != batch_start or owner_view is None:
            uris = tuple(row["run_uri"] for row in admissions[offset:offset + batch_size])
            owner_view = read_owner_journals(
                daemon.config, uris, coordinator_id=owner, agent_id=daemon._agent_id, clock=daemon._clock,
                read_snapshot=read_snapshot,
                observe_storage=daemon._slurm_storage_observer(),
            )
            batch_start = offset
        admission = _admission_from_row(candidate)
        return daemon._admission_detail(admission, owner_view(admission, admission.revision)).owners

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
                owners = job_owners(candidate)
                record.sources["job_associations"] = owners
                record.warnings.extend(_job_warnings(candidate["admission_id"], owners))
            except (OSError, ValueError, LookupError, QueueError):
                record.warnings.append(
                    {
                        "code": "job_associations_unavailable",
                        "admission_id": candidate["admission_id"],
                    }
                )
        return record

    warnings: list[dict[str, Any]] = list(discovery_warnings)
    keyed = []
    for candidate in candidates:
        keys = []
        for order in query.order_by:
            value = candidate.get(order.field, UNAVAILABLE)
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
    def bounded_acquire(candidate: dict[str, Any]) -> QueryRecord:
        try:
            return _job_read(daemon, job_deadline, partial(acquire, candidate))
        except QueryObservationDeadline as exc:
            raise QueryObservationDeadline(candidate["admission_id"]) from exc

    return search_page(
        query, owner, keyed, bounded_acquire if query.entity == "jobs" else acquire, warnings=warnings,
    )


def query_operation(daemon: Any, operation: str, value: dict[str, Any]) -> Any:
    if operation == "query_fields":
        return query_fields(value["entity"])
    if operation.startswith("search_"):
        return search(daemon, value["query"])
    from loom.runs._query_vocabulary import vocabulary_page

    return vocabulary_page(
        lambda q: search(daemon, q), operation, value, daemon._require_started()
    )
