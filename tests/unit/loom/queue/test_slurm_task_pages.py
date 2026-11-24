"""Slurm control pages honor encoded bytes and never skip an undelivered task."""

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, cast
from types import SimpleNamespace

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.local_daemon import _ensure_recovery_assignment_index
from loom.queue.local_daemon_execution import LocalDaemonExecution
from loom.queue._agent_session_codec import _MAX_BODY_BYTES, _decode


def owner_for(sizes, *, withheld=()):
    records = [SimpleNamespace(assignment=SimpleNamespace(assignment_id=f"assignment-{i:03d}")) for i in range(len(sizes))]
    constructed = []

    def page(agent, root, *, after):
        assert (agent, root) == ("agent", "root")
        return tuple(row for row in records if after is None or row.assignment.assignment_id > after)[:33]

    def task(row, facts):
        identity = row.assignment.assignment_id
        constructed.append(identity)
        return {"assignment": {"assignment_id": identity}, "recovery_request": None,
                "payload": "x" * sizes[int(identity.rsplit("-", 1)[1])]}

    return SimpleNamespace(
        slurm_assignments=SimpleNamespace(agent_page=page), _slurm_task=task,
        _slurm_recoveries=lambda ids: {key: [("{}", "pending", True)] for key in ids if key in withheld},
    ), constructed


def page(owner, cursor=None):
    return cast(dict[str, Any], LocalDaemonExecution.slurm_agent_task_page(owner, "agent", "root", cursor=cursor))


def wire(reply):
    return json.dumps({"ok": True, "result": reply}, sort_keys=True, separators=(",", ":")).encode()


def test_page_count_bounds_materialization_and_replays_lost_response():
    owner, constructed = owner_for([10] * 70)
    first = page(owner)
    assert len(first["tasks"]) == 32
    assert len(constructed) == 32
    assert page(owner) == first
    second = page(owner, first["next_cursor"])
    third = page(owner, second["next_cursor"])
    assert [len(reply["tasks"]) for reply in (first, second, third)] == [32, 32, 6]
    assert third["next_cursor"] is None
    assert len({row["assignment"]["assignment_id"] for reply in (first, second, third) for row in reply["tasks"]}) == 70
    assert len(wire(first)) <= _MAX_BODY_BYTES
    _decode(wire(first))


def test_byte_boundary_returns_last_delivered_cursor():
    owner, _ = owner_for([20000] * 5)
    first = page(owner)
    assert len(first["tasks"]) == 3
    assert len(wire(first)) <= _MAX_BODY_BYTES
    second = page(owner, first["next_cursor"])
    assert len(second["tasks"]) == 2
    assert second["tasks"][0]["assignment"]["assignment_id"] == "assignment-003"
    assert second["next_cursor"] is None


def test_oversized_task_is_an_error_not_an_advanced_cursor():
    owner, _ = owner_for([_MAX_BODY_BYTES + 1, 10])
    for _ in range(2):
        with pytest.raises(QueueServiceError, match="response budget"):
            page(owner)


def test_withheld_recovery_page_still_advances_scan_without_losing_later_work():
    owner, _ = owner_for([10] * 34, withheld={f"assignment-{i:03d}" for i in range(32)})
    first = page(owner)
    assert first == {"tasks": [], "next_cursor": "assignment-031"}
    assert len(page(owner, first["next_cursor"])["tasks"]) == 2

@pytest.mark.parametrize("page_size", [1, 32])
def test_recovery_lookup_reads_one_indexed_page(tmp_path, page_size):
    path = tmp_path / "control.sqlite"
    queries = []

    @contextmanager
    def connect(database):
        with sqlite3.connect(database) as conn:
            conn.set_trace_callback(queries.append)
            yield conn

    ids = tuple(f"page-{i}" for i in range(page_size))
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE recovery_operations (request_json TEXT, state TEXT)")
        conn.executemany(
            "INSERT INTO recovery_operations VALUES (?, ?)",
            [(json.dumps({"assignment_id": f"other-{i}"}), "pending") for i in range(4096)]
            + [(json.dumps({"assignment_id": ids[0], "target": {"kind": kind}}), state)
               for kind, state in (("slurm", "closed"), ("managed", "closed"), ("slurm", "pending"),
                                   ("slurm", "evidence_confirmed"), ("slurm", "refused"))],
        )
        _ensure_recovery_assignment_index(conn)
    owner = SimpleNamespace(config=SimpleNamespace(control_database=path, connect_database=connect))
    facts = LocalDaemonExecution._slurm_recoveries(cast(LocalDaemonExecution, owner), ids)
    assert list(facts) == [ids[0]]
    assert [(state, retains) for _, state, retains in facts[ids[0]]] == [
        ("closed", False), ("closed", True), ("pending", True), ("evidence_confirmed", True),
    ]
    assert len(queries) == 1
    with sqlite3.connect(path) as conn:
        plan = conn.execute("EXPLAIN QUERY PLAN " + queries[0]).fetchall()
    assert any("SEARCH recovery_operations USING INDEX recovery_by_assignment" in row[3] for row in plan)
