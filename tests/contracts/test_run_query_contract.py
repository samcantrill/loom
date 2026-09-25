"""Live pages retain coverage, bounded progress and native identity."""

from dataclasses import replace

import pytest

from loom.runs._query_page import QueryPage, collect_pages, search_page
from loom.runs.query import Compare, Field, InvalidCursorError, QueryRecord, RunQuery


def test_vocabulary_rereads_pending_values_and_unions_page_observations():
    from loom.runs._query_vocabulary import collect_vocabulary, vocabulary_page

    tags = [
        {"customer": "shared", "dataset.version": "v1", "region": "west"},
        {"customer": "shared", "study": "other"},
    ]
    candidates = [((f"run:{i}",), i) for i in range(2)]

    def search(query):
        return search_page(
            query,
            "owner",
            candidates,
            lambda i: QueryRecord(
                {"native": {"run_uri": f"run:{i}"}, "tags": tags[i]},
                warnings=[{"code": "partial_record"}] if i else [],
            ),
        )

    request = {"scope": {"kind": "managed"}, "limit": 1, "cursor": None}
    first = vocabulary_page(search, "tag_keys", request, "owner")
    assert first.items == ({"key": "customer"},)
    del tags[0]["dataset.version"]
    second = vocabulary_page(
        search, "tag_keys", {**request, "cursor": first.next_cursor}, "owner"
    )
    assert second.items == ({"key": "region"},)
    collected = collect_vocabulary(
        lambda cursor: vocabulary_page(
            search, "tag_keys", {**request, "cursor": cursor}, "owner"
        )
    )
    assert collected.values == ("customer", "region", "study")
    assert not collected.complete and collected.warnings
    assert sum(page.items == ({"key": "customer"},) for page in collected.pages) == 2
    with pytest.raises(InvalidCursorError):
        vocabulary_page(
            search, "tag_keys", {**request, "cursor": first.next_cursor}, "another"
        )


def test_vocabulary_empty_page_still_bounds_detailed_reads():
    from loom.runs._query_vocabulary import vocabulary_page

    candidates = [((f"run:{i:04}",), i) for i in range(502)]
    acquired = []

    def acquire(i):
        acquired.append(i)
        return QueryRecord(
            {"native": {"run_uri": f"run:{i:04}"}, "tags": {"other": "value"}}
        )

    def search(query):
        return search_page(query, "owner", candidates, acquire)

    request = {
        "scope": {"kind": "managed"},
        "limit": 50,
        "cursor": None,
        "key": "missing",
    }
    first = vocabulary_page(search, "tag_values", request, "owner")
    assert first.items == () and first.examined == len(acquired) == 500
    second = vocabulary_page(
        search, "tag_values", {**request, "cursor": first.next_cursor}, "owner"
    )
    assert second.items == () and second.examined == 2 and second.next_cursor is None
    assert len(acquired) == 502


def test_sparse_pages_bound_acquisition_and_retain_empty_page_coverage():
    query = RunQuery(where=Compare(Field("tags", ("study",)), "eq", "last")).checked()
    candidates = [((f"run:{i:04}",), i) for i in range(502)]
    acquired = []

    def acquire(i):
        acquired.append(i)
        return QueryRecord(
            {
                "native": {"run_uri": f"run:{i:04}"},
                "tags": {"study": "last" if i == 501 else "other"},
            },
            warnings=[{"code": "authority_unavailable"}] if i == 10 else [],
        )

    pages = collect_pages(
        lambda q: search_page(q, "coordinator", candidates, acquire), query
    )
    assert len(acquired) == 502
    assert pages.pages[0].items == () and pages.pages[0].examined == 500
    assert pages.pages[0].next_cursor and pages.pages[1].next_cursor is None
    assert pages.items[0]["identity"] == "run:0501"
    assert not pages.complete and pages.warnings
    assert QueryPage.from_dict(pages.pages[0].to_dict()) == pages.pages[0]


def test_vocabulary_large_unicode_annotations_and_escaped_value_byte_budget():
    from loom.runs._query_vocabulary import collect_vocabulary, vocabulary_page
    from loom.runs import SubmissionContext

    tags = {f"key{i:03}": "é" * 500 for i in range(45)}
    SubmissionContext(tags=tags)
    candidates = [(("run:unicode",), 0)]

    def search(query):
        return search_page(
            query,
            "owner",
            candidates,
            lambda _: QueryRecord({"native": {"run_uri": "run:unicode"}, "tags": tags}),
        )

    request = {"scope": {"kind": "managed"}, "limit": 10, "cursor": None}
    result = collect_vocabulary(
        lambda cursor: vocabulary_page(
            search, "tag_keys", {**request, "cursor": cursor}, "owner"
        )
    )
    assert result.complete and result.values == tuple(sorted(tags))

    candidates = [((f"run:{i:03}",), i) for i in range(200)]

    def search_values(query):
        return search_page(
            query,
            "owner",
            candidates,
            lambda i: QueryRecord(
                {
                    "native": {"run_uri": f"run:{i:03}"},
                    "tags": {"key": "\x00" * 1000 + str(i)},
                }
            ),
        )

    request = {**request, "limit": 200, "key": "key"}
    result = collect_vocabulary(
        lambda cursor: vocabulary_page(
            search_values, "tag_values", {**request, "cursor": cursor}, "owner"
        )
    )
    assert result.complete and len(result.values) == 200 and len(result.pages) == 2
    import json

    assert all(
        len(json.dumps(page.to_dict()).encode()) < 1024 * 1024 for page in result.pages
    )


def test_live_membership_and_cursor_binding():
    candidates = [((f"run:{i}",), i) for i in range(3)]
    hidden = set()
    query = RunQuery(
        limit=1, where=Compare(Field("tags", ("visible",)), "eq", "yes")
    ).checked()

    def acquire(i):
        return QueryRecord(
            {
                "native": {"run_uri": f"run:{i}"},
                "tags": {"visible": "no" if i in hidden else "yes"},
            }
        )

    page = search_page(query, "a", candidates, acquire)
    continuation = replace(query, cursor=page.next_cursor)
    hidden.add(1)
    assert (
        search_page(continuation, "a", candidates, acquire).items[0]["identity"]
        == "run:2"
    )
    for invalid, owner in [
        (continuation, "b"),
        (replace(continuation, limit=2), "a"),
        (replace(query, cursor="not-a-cursor"), "a"),
    ]:
        with pytest.raises(InvalidCursorError):
            search_page(invalid, owner, candidates, acquire)


def test_oversize_record_retains_identity_diagnostic():
    query = RunQuery().checked()
    page = search_page(
        query,
        "a",
        [(("run:1",), 1)],
        lambda _: QueryRecord(
            {"native": {"run_uri": "run:1"}, "metadata": {"huge": "x" * 100_000}}
        ),
    )
    assert page.items == (
        {
            "identity": "run:1",
            "truncated": True,
            "diagnostic": "oversize_record",
            "reference": {"run_uri": "run:1"},
        },
    )


def test_collection_time_order_enumerates_metadata_but_caps_detail_reads(
    tmp_path, monkeypatch
):
    from loom.pipeline.stores import LocalRunStore
    from loom.runs import CollectionScope, Order
    from loom.runs import _query_local

    root = tmp_path / "runs"
    root.mkdir()
    for index in range(502):
        path = root / f"run-{index:04}"
        path.mkdir()
        (path / "run.json").write_text("{}")
    metadata_reads = []
    detailed_reads = []

    def metadata(self, uri):
        metadata_reads.append(uri)
        return {"created_at": "2026-09-23T00:00:00Z"}

    def detailed(root, uri, authority, *, include_notes=False):
        detailed_reads.append(uri)
        return QueryRecord({"native": {"run_uri": uri}, "tags": {"match": "no"}})

    monkeypatch.setattr(LocalRunStore, "read_run_document", metadata)
    monkeypatch.setattr(_query_local, "acquire_run", detailed)
    query = RunQuery(
        scope=CollectionScope(),
        order_by=(Order("created_at"),),
        where=Compare(Field("tags", ("match",)), "eq", "yes"),
    )
    page = _query_local.search_collection(
        root, query, authority_factory=lambda uri: object()
    )
    assert len(metadata_reads) == 502
    assert len(detailed_reads) == page.examined == 500
    assert page.items == () and page.next_cursor is not None
    following = _query_local.search_collection(
        root,
        replace(query, cursor=page.next_cursor),
        authority_factory=lambda uri: object(),
    )
    assert following.examined == 2 and following.next_cursor is None


def test_note_excerpt_contains_late_casefolded_match():
    from loom.runs import ContainsText
    from loom.runs.query import evaluate, Truth

    query = RunQuery(where=ContainsText(Field("notes", ("text",)), "STRASSE")).checked()
    matches = []
    result = evaluate(
        query.where,
        QueryRecord(
            {
                "notes": [
                    {
                        "note_id": "note-1",
                        "text": "prefix " * 200 + "Straße observation",
                    }
                ]
            }
        ),
        matches=matches,
    )
    assert result is Truth.TRUE
    assert "Straße" in matches[0]["excerpt"] and matches[0]["truncated"]


def test_local_empty_partial_and_unavailable_are_distinct(tmp_path):
    from loom.runs import CollectionScope, RunCatalog

    missing = RunCatalog.open(tmp_path / "missing").search(
        RunQuery(scope=CollectionScope())
    )
    empty = RunCatalog.open(tmp_path).search(RunQuery(scope=CollectionScope()))
    (tmp_path / "partial").mkdir()
    partial = RunCatalog.open(tmp_path).search(RunQuery(scope=CollectionScope()))
    assert missing.items == empty.items == partial.items == ()
    assert empty.complete and not empty.warnings
    assert (
        not missing.complete and missing.warnings[0]["code"] == "collection_unavailable"
    )
    assert not partial.complete and partial.warnings[0]["code"] == "partial_run"


def test_managed_initializer_order_bounds_context_reads_and_skips_reconciled_requests(
    tmp_path, monkeypatch
):
    from contextlib import contextmanager
    import sqlite3
    from types import SimpleNamespace
    from loom.queue import _run_queries
    from loom.runs import Order

    database = tmp_path / "journal.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE preparation_operations(operation_id TEXT, principal_id TEXT, accepted_at TEXT, state TEXT, kind TEXT, queue_item_id TEXT, result_json TEXT, request_json TEXT)"
        )
        connection.execute("CREATE TABLE managed_admissions(run_uri TEXT)")
        for i in range(502):
            connection.execute(
                "INSERT INTO preparation_operations VALUES(?, 'caller', '2026-09-23T00:00:00Z', 'applied', 'run', 'queue', ?, '{}')",
                (f"op-{i:04}", '{"prepared_run":{"run_uri":"file:///same-run"}}'),
            )

    @contextmanager
    def connect():
        with sqlite3.connect(database) as connection:
            connection.row_factory = sqlite3.Row
            yield connection

    daemon = SimpleNamespace(
        _connection=connect,
        _require_started=lambda: "owner",
        config=SimpleNamespace(
            run_store_root=tmp_path, coordinator_authority_factory=lambda uri: object()
        ),
    )
    detailed = []

    def acquire(root, uri, authority, *, include_notes=False):
        detailed.append(uri)
        return QueryRecord(
            {
                "native": {
                    "run_uri": uri,
                    "operation_id": "op-0501",
                    "coordinator_id": "owner",
                }
            }
        )

    monkeypatch.setattr(_run_queries, "acquire_run", acquire)
    query = RunQuery(order_by=(Order("submitted_at"),)).checked()
    first = _run_queries.search(daemon, query)
    assert first.examined == 500 and first.items == () and first.next_cursor
    second = _run_queries.search(daemon, replace(query, cursor=first.next_cursor))
    assert second.examined == 2 and second.next_cursor is None
    assert second.items[0]["identity"] == "file:///same-run"
    assert len(detailed) == 2  # At most one detached authority context per run/page.


def test_native_provenance_is_distinct_from_annotations_and_never_opens_payloads(
    tmp_path, monkeypatch
):
    from loom.pipeline.execution import create_authority_backed_serial_run_store
    from loom.pipeline.stores import LocalRunStore
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.runs import SubmissionContext
    from loom.runs._query_acquire import acquire_run
    from loom.runs.query import evaluate, Truth

    root = tmp_path / "runs"
    authority = SQLitePerRunAuthorityStore()
    store = create_authority_backed_serial_run_store(root, authority_store=authority)
    uri = (root / "one").as_uri()
    store.create_run(uri)
    store.write_provenance_document(
        uri,
        "git",
        {
            "repository_root": "/recorded/repository",
            "commit": "native-commit",
            "is_dirty": True,
        },
    )
    authority.initialize_run_annotations(
        uri,
        SubmissionContext(
            metadata={"commit": "caller-commit", "_target_": "must.not.import"}
        ),
        "op",
        "owner",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("discovery must not read artifact indexes or payloads")

    monkeypatch.setattr(LocalRunStore, "read_artifact_index", forbidden)
    record = acquire_run(root, uri, authority)
    query = RunQuery(
        where=Compare(Field("native", ("git_commit",)), "eq", "native-commit")
    ).checked()
    assert evaluate(query.where, record) is Truth.TRUE
    assert record.sources["native"]["git_repository"] == "/recorded/repository"
    assert record.sources["native"]["git_dirty"] is True
    assert record.sources["metadata"]["commit"] == "caller-commit"
    unavailable = acquire_run(root, uri)
    assert unavailable.warnings[0]["code"] == "authority_unavailable"
