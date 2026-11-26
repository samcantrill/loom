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
    refreshed = _record("same", revision=4)
    owner.ready(refreshed)
    owner.reserved(refreshed, "accepted", None, 88)
    summaries = cast(list[dict], owner.summaries(first.run_uri))
    assert [(row["projection_revision"], row["assignment_id"]) for row in summaries] == [
        (1, "released-before-delivery"), (4, "accepted"),
    ]
    assert [(s["ready_projection_revision"], s["request_available_ns"]) for s in summaries] == [(1, None), (3, 88)]
    assert events.count("attempt_ready") == 2


def test_prequeue_partitions_held_reasons_and_freezes_at_first_submission(monkeypatch):
    now = [10]
    monkeypatch.setattr(waits, "monotonic_ns", lambda: now[0])
    monkeypatch.setattr(waits, "milestone", lambda *args, **kwargs: None)
    owner, work = waits.SchedulingWaits(), _record("a")
    owner.ready(work)
    now[0] = 21
    owner.ready(work, scanned=True)
    now[0] = 24
    owner.prequeue(work, "early_retention_limit")
    now[0] = 27
    owner.prequeue(work, "early_retention_limit")
    now[0] = 40
    owner.prequeue(work, "preparation_capacity")
    owner.queued(work, 45)
    now[0] = 75
    owner.prequeue(work, "unknown")
    owner.queued(work, 81)  # a retry after the first build failed
    now[0] = 95
    owner.reserved(work, "assignment", None, 90)
    summary, = cast(list[dict], owner.summaries(work.run_uri))
    assert summary["prequeue_status"] == "observed"
    assert (summary["prequeue_ready_ns"], summary["prequeue_queued_ns"]) == (10, 45)
    assert summary["prequeue_wait_ns"] == {
        "first_scan": 11, "unknown": 3, "early_retention_limit": 16, "preparation_capacity": 5,
    }


def test_prequeue_reopen_reuse_and_stale_notifications(monkeypatch):
    now = [10]
    monkeypatch.setattr(waits, "monotonic_ns", lambda: now[0])
    monkeypatch.setattr(waits, "milestone", lambda *args, **kwargs: None)
    owner = waits.SchedulingWaits()
    first, reopened = _record("same"), _record("same", 3)
    owner.ready(first)
    owner.queued(first, 20)
    now[0] = 40
    owner.reserved(first, "previous", None, 25)
    now[0] = 50
    owner.ready(reopened, scanned=True)
    owner.queued(first, 99)
    owner.queued(reopened, 20)
    owner.reserved(reopened, "next", None, 25)
    _, carried = cast(list[dict], owner.summaries(first.run_uri))
    assert carried["ready_projection_revision"] == 3
    assert carried["prequeue_status"] == "reused"
    assert carried["prequeue_queued_ns"] == 20 and carried["prequeue_wait_ns"] is None


def test_unobserved_endpoints_do_not_report_zero_latency(monkeypatch):
    monkeypatch.setattr(waits, "milestone", lambda *args, **kwargs: None)
    owner = waits.SchedulingWaits()
    cancelled, incomplete = _record("cancelled"), _record("incomplete")
    owner.ready(cancelled)
    owner.retain(cancelled.run_uri, set())
    owner.ready(incomplete, scanned=True)
    owner.reserved(incomplete, "missing-boundary", None, None)
    summaries = cast(list[dict], owner.summaries(incomplete.run_uri))
    assert [row["prequeue_status"] for row in summaries] == ["inapplicable", "missing"]
    assert all(row["prequeue_wait_ns"] is None and row["prequeue_queued_ns"] is None for row in summaries)
