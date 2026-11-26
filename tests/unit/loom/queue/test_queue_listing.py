"""Indexed admission visibility and cursors use only the queue journal."""

import json
import sqlite3
from typing import cast

import pytest

from loom.serialization import PlainData
from loom.queue._admission_scan import ACTIVE_PREDICATE, PRIORITY_ORDER, ensure_scan_index
from loom.queue._queue_listing import QueueSelection, decode_queue_page, queue_page

pytestmark = pytest.mark.unit
NOW = "2026-11-26T00:00:00Z"


@pytest.fixture
def history():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE managed_admissions (
        admission_id TEXT PRIMARY KEY, queue_item_id TEXT, admitted_by TEXT, state TEXT,
        accepted_at TEXT, blocked_reason TEXT, run_priority INTEGER, enqueue_sequence INTEGER,
        cancellation_operation_id TEXT)""")
    ensure_scan_index(conn)
    values: list[tuple[object, ...]] = [(f"a{i}", f"q{i}", "alice", "SUCCEEDED", NOW, None, 0, i, None) for i in range(2500)]
    for i, (priority, state, owner) in enumerate([
        (2, "ACTIVE", "alice"), (8, "WAITING", "bob"), (8, "CANCELLING", "alice"),
        (0, "PENDING_AUTHORITY", None), (9, "BLOCKED", "alice"),
        (1, "CANCELLATION_REQUESTED", "alice"),
    ], start=2500):
        values.append((f"a{i}", f"q{i}", owner, state, NOW, "reason", priority, i, None))
    conn.executemany("INSERT INTO managed_admissions VALUES(?,?,?,?,?,?,?,?,?)", values)
    yield conn
    conn.close()


def _admissions(page: dict[str, PlainData]) -> list[dict[str, PlainData]]:
    return cast(list[dict[str, PlainData]], page["admissions"])


def test_active_summary_filters_before_paging_and_binds_cursor(history):
    selection = QueueSelection((), False, None)
    plan = history.execute(f"EXPLAIN QUERY PLAN SELECT * FROM managed_admissions WHERE {ACTIVE_PREDICATE} "
                           f"ORDER BY {PRIORITY_ORDER} LIMIT 3").fetchall()
    assert any("managed_admissions_active_order" in row["detail"] for row in plan)
    first = queue_page(history, "one", NOW, selection, 2, None)
    assert decode_queue_page(json.loads(json.dumps(first))) == first
    assert [r["admission_id"] for r in _admissions(first)] == ["a2501", "a2502"]
    cursor = cast(str | None, first["next_cursor"])
    ids = [r["admission_id"] for r in _admissions(first)]
    while cursor:
        page = queue_page(history, "one", NOW, selection, 2, cursor)
        ids.extend(r["admission_id"] for r in _admissions(page))
        cursor = cast(str | None, page["next_cursor"])
    assert ids == ["a2501", "a2502", "a2500", "a2505", "a2503"]
    for owner, changed in [
        ("two", selection), ("one", QueueSelection((), True, None)),
        ("one", QueueSelection((), False, "bob")), ("one", QueueSelection(("ACTIVE",), False, None)),
    ]:
        with pytest.raises(ValueError, match="cursor"):
            queue_page(history, owner, NOW, changed, 2, cast(str, first["next_cursor"]))


def test_unknown_creator_and_explicit_terminal_state(history):
    def rows(states=(), principal=None, include_terminal=False):
        page = queue_page(history, "one", NOW, QueueSelection(states, include_terminal, principal), 100, None)
        return _admissions(page)
    assert [r["state"] for r in rows(("BLOCKED",), "alice")] == ["BLOCKED"]
    assert rows(("BLOCKED",), "bob") == []
    assert [r["state"] for r in rows(principal="alice")] == ["CANCELLING", "ACTIVE", "CANCELLATION_REQUESTED"]
    assert any(r["admitted_by"] is None for r in rows())
    assert rows(include_terminal=True)[0]["state"] == "BLOCKED"


@pytest.mark.parametrize("limit", [0, 101, True])
def test_invalid_page_size_is_refused_by_the_journal_reader(history, limit):
    with pytest.raises(ValueError, match="1..100"):
        queue_page(history, "one", NOW, QueueSelection((), True, None), limit, None)
