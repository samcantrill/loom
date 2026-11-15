"""Slurm control pages honor encoded bytes and never skip an undelivered task."""

import json
from types import SimpleNamespace

import pytest

from loom.queue.errors import QueueServiceError
from loom.queue.local_daemon_execution import LocalDaemonExecution
from loom.queue._agent_session_codec import _MAX_BODY_BYTES, _decode


def owner_for(sizes, *, withheld=()):
    records = [SimpleNamespace(assignment=SimpleNamespace(assignment_id=f"assignment-{i:03d}")) for i in range(len(sizes))]
    constructed = []

    def page(agent, root, *, after):
        assert (agent, root) == ("agent", "root")
        return tuple(row for row in records if after is None or row.assignment.assignment_id > after)[:33]

    def task(row):
        identity = row.assignment.assignment_id
        constructed.append(identity)
        return {"assignment": {"assignment_id": identity}, "recovery_request": None,
                "payload": "x" * sizes[int(identity.rsplit("-", 1)[1])]}

    return SimpleNamespace(
        slurm_assignments=SimpleNamespace(agent_page=page), _slurm_task=task,
        _recovery_retains_assignment=lambda identity: identity in withheld,
    ), constructed


def page(owner, cursor=None):
    return LocalDaemonExecution.slurm_agent_task_page(owner, "agent", "root", cursor=cursor)


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
