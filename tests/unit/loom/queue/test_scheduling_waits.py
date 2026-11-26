from types import SimpleNamespace
from typing import cast

import pytest

from loom.queue import _scheduling_waits as waits
from loom.pipeline.orchestration import StageWorkRecord


pytestmark = pytest.mark.unit


def _record(work, revision=1):
    return cast(StageWorkRecord, SimpleNamespace(run_uri="file:///run", stage_name=work, stage_work_id=work,
                admission_id="admission", attempt_id=work + "-attempt", ready_at=1,
                projection_revision=revision))


def test_only_confirmed_request_and_offer_overlap_counts(monkeypatch):
    now = [10]
    events = []
    monkeypatch.setattr(waits, "monotonic_ns", lambda: now[0])
    monkeypatch.setattr(waits, "milestone", lambda action, **attrs: events.append((action, attrs)))
    owner = waits.SchedulingWaits()
    work, peer = _record("a"), _record("b")
    for record in (work, peer):
        owner.ready(record)
        owner.eligible(record, "first", 25, None)
    now[0] = 30
    owner.eligible(work, "first", 40, 17)
    owner.current_offers(set(), ("epoch", "policy"))
    now[0] = 50
    for record in (work, peer):
        owner.eligible(record, "second", 100, 17)
    now[0] = 60
    owner.reserved(work, "assigned-a", "second", 17)
    now[0] = 75
    owner.reserved(peer, "assigned-b", "second", 17)
    first, second = cast(list[dict], owner.summaries(work.run_uri))
    assert first["eligible_request_ready_ns"] == 8 + 10
    assert first["saw_eligible_offer"]
    assert second["eligible_request_ready_ns"] == 0
    assert [attrs["assignment_id"] for name, attrs in events if name == "reservation_committed"] == [
        "assigned-a", "assigned-b",
    ]


def test_expired_offer_unknown_and_history_bounded(monkeypatch):
    events = []
    monkeypatch.setattr(waits, "monotonic_ns", lambda: 100)
    monkeypatch.setattr(waits, "milestone", lambda action, **attrs: events.append((action, attrs)))
    owner = waits.SchedulingWaits()
    owner._limit = 1
    a, b = _record("a"), _record("b")
    owner.ready(a)
    owner.ready(a)
    owner.eligible(a, "expired", 99, 10)
    owner.capacity(a, "assignment_slots_full")
    owner.ready(b)
    first, = cast(list[dict], owner.summaries(a.run_uri))
    assert first["result"] == "observation_evicted"
    assert not first["saw_eligible_offer"]
    assert "assignment_slots_full" in first["wait_ns"]
    owner.retain(b.run_uri, set())
    last, = cast(list[dict], owner.summaries(b.run_uri))
    assert last["result"] == "left_ready" and last["attempt_id"] == b.attempt_id
    assert sum(name == "attempt_ready" for name, _ in events) == 2
    assert all(name != "eligible_offer_observed" for name, _ in events)


def test_release_before_acceptance_reopens_the_same_attempt(monkeypatch):
    events = []
    monkeypatch.setattr(waits, "milestone", lambda action, **attrs: events.append(action))
    owner = waits.SchedulingWaits()
    first = _record("same")
    reopened = _record("same", revision=3)
    owner.ready(first)
    owner.reserved(first, "released-before-delivery", None, None)
    owner.ready(first)
    owner.ready(reopened)
    owner.reserved(reopened, "accepted", None, None)
    summaries = cast(list[dict], owner.summaries(first.run_uri))
    assert [(row["projection_revision"], row["assignment_id"]) for row in summaries] == [
        (1, "released-before-delivery"), (3, "accepted"),
    ]
    assert events.count("attempt_ready") == 2
