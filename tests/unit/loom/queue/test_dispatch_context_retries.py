"""Refused dispatch demand survives rediscovery until current work gets a loader."""

from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

from loom.pipeline.orchestration import SchedulingProjectionState
from loom.pipeline.runtime import ExecutionRouteKind
from loom.queue._context_preparation import ContextPreparations, PreparedAdmissionContext
from loom.queue._coordinator_run_progress import retry_dispatch_context
from loom.queue.local_daemon import LocalDaemonAdmission, LocalDaemonAdmissionState


def _row(name: str, priority: int = 0) -> LocalDaemonAdmission:
    return LocalDaemonAdmission(name, name, "owner", name, "digest", "stage", LocalDaemonAdmissionState.WAITING,
                               "2026-01-01T00:00:00Z", "bind-" + name, run_priority=priority)


def test_freed_slot_serves_current_work_by_priority_then_first_refusal(monkeypatch):
    # The ordering contract also applies on production instances with timing off.
    monkeypatch.delenv("LOOM_QUALIFICATION_TIMINGS", raising=False)
    epochs = "owner", "policy"
    pool = ContextPreparations(lambda: None)
    dispatch_gate, discovery_gate = Event(), Event()
    starts = []
    rows = {row.admission_id: row for row in (
        _row("held"), _row("discover"), _row("cancel"), _row("supersede"), _row("left-ready"),
        _row("older"), _row("hot"), _row("priority", 1), _row("new"),
    )}
    ready = set(rows)
    cancelled = set()

    def load(row, epochs):
        starts.append(row.admission_id)
        if row.admission_id == "held":
            assert dispatch_gate.wait(10)
        if row.admission_id == "discover":
            assert discovery_gate.wait(10)
        return cast(PreparedAdmissionContext, (object(), object()))

    def offer(key):
        return pool.try_submit(rows[key], epochs, load, dispatch_work_id=key)

    def finish(key):
        pool._pending[key].future.result(timeout=10)
        assert [p.admission.admission_id for p in pool.completed()] == [key]

    def work(key):
        return SimpleNamespace(scheduling_state=SchedulingProjectionState.READY,
                               placement=SimpleNamespace(route=SimpleNamespace(kind=ExecutionRouteKind.MANAGED_AGENT)),
                               run_uri=key, attempt_id=key) if key in ready else None

    daemon = SimpleNamespace(_contexts=pool, _lookup_schedulable_admissions=lambda ids: {k: rows[k] for k in ids},
                             _result_verifications=SimpleNamespace(bulk=None))
    owner: Any = SimpleNamespace(_daemon_owner=lambda: daemon, continuation_context=lambda *args: None,
                                 run_observations=SimpleNamespace(awaiting_read=lambda *args: False),
                                 stage_work_store=SimpleNamespace(find_stage_work=work),
                                 _attempt_cancel_requested=lambda run, attempt: attempt in cancelled,
                                 prepare_admission_context=load)
    try:
        assert offer("held")
        for key in ("cancel", "supersede", "left-ready", "older", "hot", "priority"):
            assert not offer(key)
        assert pool.try_submit(rows["discover"], epochs, load)
        # Both workers have real operations. Newer visits cannot move "hot".
        for _ in range(4):
            assert not offer("hot")
        cancelled.add("cancel")
        rows["supersede"] = replace(rows["supersede"], revision=2)
        ready.remove("left-ready")
        dispatch_gate.set()
        finish("held")
        assert not offer("new")  # Free worker, but an earlier refusal owns service.
        for key in ("priority", "older", "hot", "new"):
            retry_dispatch_context(owner, epochs)
            finish(key)
        assert [k for k in starts if k not in {"held", "discover"}] == ["priority", "older", "hot", "new"]
        discovery_gate.set()
        finish("discover")
    finally:
        dispatch_gate.set()
        discovery_gate.set()
        pool.close()


def test_full_retry_queue_preserves_priority_and_ready_rediscovery(monkeypatch):
    pool = ContextPreparations(lambda: None)
    monkeypatch.setattr(pool, "_retry_limit", 2)
    gate = Event()
    epochs = "owner", "policy"
    rows = {row.admission_id: row for row in (_row("held"), _row("old"), _row("peer"), _row("overflow"), _row("hi", 1))}
    starts = []

    def load(row, _epochs):
        starts.append(row.admission_id)
        assert gate.wait(10)
        return cast(PreparedAdmissionContext, (object(), object()))

    def offer(key):
        return pool.try_submit(rows[key], epochs, load, dispatch_work_id=key)

    try:
        assert offer("held")
        for key in ("old", "peer", "overflow", "hi"):
            assert not offer(key)
        gate.set()
        for key in ("held", "hi", "old"):
            pool._pending[key].future.result(timeout=10)
            pool.completed()
            pool.retry_dispatch(epochs, lambda ids: {k: rows[k] for k in ids}, lambda row, work: True, load)
        # The next ordinary READY visits can submit both displaced and overflow work.
        for key in ("peer", "overflow"):
            assert offer(key)
            pool._pending[key].future.result(timeout=10)
            pool.completed()
        assert starts == ["held", "hi", "old", "peer", "overflow"]
    finally:
        gate.set()
        pool.close()
