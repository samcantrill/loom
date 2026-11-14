"""Journal pagination bounds acquisition without changing typed query results."""

from contextlib import contextmanager
from dataclasses import replace
from functools import cmp_to_key
import sqlite3
from types import SimpleNamespace

import pytest

from loom.queue._query_journal import journal_candidates
from loom.runs import AllOf, AnyOf, Compare, Field, JobQuery, Order, SubmissionQuery
from loom.runs._query_page import collect_pages, search_page
from loom.runs.query import QueryRecord, compare_keys

pytestmark = pytest.mark.unit


@pytest.fixture
def journal():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE managed_admissions(admission_id TEXT PRIMARY KEY, queue_item_id TEXT, state TEXT, run_uri TEXT, accepted_at TEXT)")
    conn.execute("CREATE TABLE preparation_operations(operation_id TEXT PRIMARY KEY, principal_id TEXT, state TEXT, kind TEXT, queue_item_id TEXT, accepted_at TEXT, result_json TEXT)")
    for i in range(1103):
        conn.execute("INSERT INTO managed_admissions VALUES(?,?,?,?,?)", (f"a{i:04}", f"q{i}", "ACTIVE", f"file:///run/{i}", "2026-01-01T00:00:00Z"))
        conn.execute("INSERT INTO preparation_operations VALUES(?,?,?,?,?,?,?)", (f"o{i:04}", "client", "applied", "prepare", f"q{i}", "2026-01-01T00:00:00Z", '{}'))
    conn.commit()

    @contextmanager
    def connection():
        yield conn

    yield SimpleNamespace(_connection=connection), conn
    conn.close()


@pytest.mark.parametrize("model,identity", [(JobQuery, "admission_id"), (SubmissionQuery, "operation_id")])
def test_journal_pages_bound_rows_and_resume_without_duplicates(journal, model, identity):
    daemon, _ = journal
    sizes = []

    def search(query):
        rows = journal_candidates(daemon, query, "owner")
        sizes.append(len(rows))
        return search_page(query, "owner", [((row[identity],), row) for row in rows],
                           lambda row: QueryRecord({"native": row}))

    result = collect_pages(search, model(limit=137).checked())
    assert len(result.items) == len({item['identity'] for item in result.items}) == 1103
    assert result.complete
    assert max(sizes) == 501
    assert all(size <= 501 for size in sizes)


def test_predicates_narrow_only_supported_boolean_branches(journal):
    daemon, _ = journal
    exact = Compare(Field("native", ("admission_id",)), "eq", "a1102")
    external = Compare(Field("tags", ("keep",)), "eq", "yes")
    assert [r["admission_id"] for r in journal_candidates(daemon, JobQuery(where=exact).checked(), "owner")] == ["a1102"]
    assert len(journal_candidates(daemon, JobQuery(where=AllOf((exact, external))).checked(), "owner")) == 1
    assert len(journal_candidates(daemon, JobQuery(where=AnyOf((exact, external))).checked(), "owner")) == 501


@pytest.mark.parametrize("descending", [False, True])
def test_timestamp_keysets_match_normalized_public_order_including_null(journal, descending):
    daemon, conn = journal
    conn.execute("DELETE FROM preparation_operations")
    times = [None, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00+01:00", "2026-01-01T00:00:00.0000001Z", "2025-12-31T22:00:00Z"]
    for i, value in enumerate(times):
        conn.execute("INSERT INTO preparation_operations VALUES(?,?,?,?,?,?,?)", (f"o{i}", "client", "applied", "prepare", f"q{i}", value, '{}'))
    query = SubmissionQuery(order_by=(Order("accepted_at", descending),), limit=1).checked()
    observed = []
    while True:
        rows = journal_candidates(daemon, query, "owner")
        page = search_page(query, "owner", [((r["accepted_at"], r["operation_id"]), r) for r in rows], lambda row: QueryRecord({"native": row}))
        observed.extend(item["identity"] for item in page.items)
        if page.next_cursor is None:
            break
        query = replace(query, cursor=page.next_cursor)
    expected = sorted([(v, f"o{i}") for i, v in enumerate(times)], key=cmp_to_key(lambda a,b: compare_keys(a,b,query.order_by)))
    assert observed == [key[1] for key in expected]


def test_default_run_discovery_deduplicates_and_pages_before_authority_reads(journal):
    from loom.queue._query_journal import run_uri_candidates
    from loom.runs import RunQuery

    daemon, conn = journal
    conn.execute("UPDATE preparation_operations SET result_json = ?", ('{"prepared_run":{"run_uri":"file:///run/0"}}',))
    sizes = []

    def search(query):
        rows = run_uri_candidates(daemon, query, "owner")
        sizes.append(len(rows))
        return search_page(query, "owner", [((r["run_uri"],), r) for r in rows],
                           lambda row: QueryRecord({"native": row}))

    result = collect_pages(search, RunQuery(limit=200).checked())
    assert len(result.items) == len({item["identity"] for item in result.items}) == 1103
    assert max(sizes) == 501


def test_run_submission_sort_pages_noninitializers_and_unbound_runs(journal):
    from loom.queue._query_journal import run_submission_candidates
    from loom.runs import RunQuery

    daemon, conn = journal
    conn.execute("UPDATE preparation_operations SET result_json = ?", ('{"prepared_run":{"run_uri":"file:///run/0"}}',))
    query = RunQuery(order_by=(Order("submitted_at"),), limit=200).checked()
    query = replace(query, order_by=(*query.order_by, Order("operation_id")))
    counts = []

    def search(current):
        rows = run_submission_candidates(daemon, current, "owner")
        counts.append(len(rows))
        keys = [((r["submitted_at"], r["run_uri"], r["operation_id"]), r) for r in rows]
        return search_page(current, "owner", keys, lambda row: QueryRecord(
            {"native": row}, eligible=row["operation_id"] in {"", "o1102"},
        ))

    result = collect_pages(search, query)
    assert len(result.items) == len({item["identity"] for item in result.items}) == 1103
    assert max(counts) == 501
    assert result.pages[0].items == () and result.pages[0].next_cursor is not None
