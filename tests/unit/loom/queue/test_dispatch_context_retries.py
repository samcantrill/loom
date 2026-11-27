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
    owner: Any = SimpleNamespace(daemon=daemon, _scheduling=SimpleNamespace(retained_slurm_profiles={}),
                                 _daemon_owner=lambda: daemon, continuation_context=lambda *args: None,
                                 run_observations=SimpleNamespace(awaiting_read=lambda *args: False),
                                 stage_work_store=SimpleNamespace(find_stage_work=work, ready_siblings=lambda *a: ((), None)),
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

def test_refused_page_head_cannot_expose_later_context_from_old_admission_revision(monkeypatch):
    from contextlib import nullcontext
    from loom.queue import _action_results, _coordinator_run_progress as progress
    from loom.scheduling import PolicyDecisionState

    rows = {key: _row(key) for key in ("head", "stale")}
    seen = []
    route = SimpleNamespace(kind=ExecutionRouteKind.MANAGED_AGENT)
    records = tuple(SimpleNamespace(admission_id=key, run_uri=key, stage_name=key, stage_work_id=key,
                                    attempt_id=key, placement=SimpleNamespace(route=route)) for key in rows)
    monkeypatch.setattr(_action_results, "launchable_page", lambda conn, page: page)
    monkeypatch.setattr(progress, "_advance_ready_inputs", lambda owner, record, *a, **kw: seen.append(record.stage_name))
    waits = SimpleNamespace(ready=lambda *a, **kw: None, prequeue=lambda *a: None, current_offers=lambda *a: None,
                            capacity=lambda *a: None, record=lambda *a: None)
    owner = SimpleNamespace(
        daemon=SimpleNamespace(_epoch="owner", _scheduling_epoch="policy", _result_verifications=SimpleNamespace(bulk=None),
                               _contexts=SimpleNamespace(try_submit=lambda *a, **kw: False)),
        _scheduling=SimpleNamespace(retained_slurm_profiles={}, kernel=lambda group: SimpleNamespace(
            decide=lambda **kw: SimpleNamespace(state=PolicyDecisionState.WAIT))),
        _daemon_owner=lambda: SimpleNamespace(_accepted_snapshot=lambda: ("decision", "utc")),
        config=SimpleNamespace(control_database=None, connect_database=lambda _: nullcontext(None),
                               agent_policy=SimpleNamespace(agents=()), resident_worker_launch_profile=None),
        _cycle_contexts={"stale": (SimpleNamespace(max_parallel_stages=None), object())},
        _cycle_context_epochs={"stale": ("owner", "policy")}, _cycle_context_revisions={"stale": 0},
        discard_dispatch_context=lambda *a, **kw: None, run_observations=SimpleNamespace(awaiting_read=lambda *a: False),
        prepare_admission_context=lambda *a: None, _scheduling_waits=waits, _remote_candidates=dict,
        agent_id=None, _full_offer_hosts=set(),
    )
    assert progress._schedule_window(cast(Any, owner), rows, cast(Any, records)) is None
    assert not seen


def test_shared_producer_keeps_admission_order_when_previous_witness_loses_demand(tmp_path):
    from loom.pipeline.orchestration import SQLiteStageWorkStore, stage_work_identity
    from loom.queue._action_results import action_attempt_cancelled
    from tests.unit.loom.queue.test_action_results import _select, _store
    from tests.unit.loom.queue.test_managed_local import _assignment, _seed_stage_work

    path = tmp_path / "execution.sqlite"
    projections = SQLiteStageWorkStore(path)
    actions = _store(tmp_path)
    original = replace(_row("admission-1"), run_uri="owner-graph", cancellation_operation_id="cancel-owner")
    # Keep 32 ineligible witnesses ahead of z so that even a cancelled graph
    # with a long projection history cannot monopolize one reconciliation turn.
    stages = ["a", *[f"m{i:02}" for i in range(31)], "z"]
    def work_id(stage):
        return stage_work_identity(original.admission_id, stage, stage + "-1", "ready-1")

    for stage in stages:
        _seed_stage_work(path, replace(_assignment(), run_uri=original.run_uri, stage_name=stage,
                                       stage_work_id=work_id(stage), attempt_id=stage + "-1"))
    for stage, consumer in (("a", "B"), ("z", "C")):
        claim = _select(actions, run=original.run_uri, node=stage, key=stage)["claim"]["claim_id"]
        _select(actions, run=consumer, node=stage, key=stage)
        actions.attach_fence(claim, run_uri=original.run_uri, node=stage, attempt_id=stage + "-1",
                             assignment_id="assignment-" + stage, fencing_token="fence-" + stage)
    actions.detach_graph(original.run_uri, "cancel-owner")
    with actions.connection() as conn:
        conn.execute("CREATE TABLE managed_admissions(admission_id TEXT PRIMARY KEY, run_uri, state, cancellation_operation_id)")
        conn.execute("INSERT INTO managed_admissions VALUES (?,?,?,?)",
                     (original.admission_id, original.run_uri, "CANCELLING", "cancel-owner"))
        conn.commit()

    def cancelled(uri, attempt):
        with actions.connection() as conn:
            return action_attempt_cancelled(conn, uri, attempt)

    pool = ContextPreparations(lambda: None)
    gate = Event()
    started = []
    epochs = "owner", "policy"
    held, younger = _row("held"), _row("younger")
    rows = {r.admission_id: r for r in (held, original, younger)}

    def load(row, _epochs):
        started.append(row.admission_id)
        assert gate.wait(10)
        return cast(PreparedAdmissionContext, (object(), object()))

    daemon = SimpleNamespace(_contexts=pool, _lookup_schedulable_admissions=lambda ids: {k: rows[k] for k in ids},
                             _result_verifications=SimpleNamespace(bulk=None))
    owner: Any = SimpleNamespace(daemon=daemon, _daemon_owner=lambda: daemon,
                                 _scheduling=SimpleNamespace(retained_slurm_profiles={}),
                                 config=SimpleNamespace(control_database=None, connect_database=lambda _: actions.connection()),
                                 continuation_context=lambda *args: None, run_observations=SimpleNamespace(awaiting_read=lambda *args: False),
                                 stage_work_store=projections, _attempt_cancel_requested=cancelled, prepare_admission_context=load)
    try:
        assert pool.try_submit(held, epochs, load, dispatch_work_id="held")
        assert not pool.try_submit(original, epochs, load, dispatch_work_id=work_id("z"))
        assert not pool.try_submit(younger, epochs, load, dispatch_work_id="younger")
        assert not pool.try_submit(original, epochs, load, dispatch_work_id=work_id("a"))
        actions.detach_graph("B", "cancel-B")
        assert cancelled(original.run_uri, "a-1") and not cancelled(original.run_uri, "z-1")
        gate.set()
        pool._pending["held"].future.result(timeout=10)
        pool.completed()
        retry_dispatch_context(owner, epochs)
        assert started == ["held"]
        retry_dispatch_context(owner, epochs)
        pool._pending[original.admission_id].future.result(timeout=10)
        assert started == ["held", original.admission_id]
        assert pool._pending[original.admission_id].dispatch_work_id == work_id("z")
    finally:
        gate.set()
        pool.close()


def test_discovery_inherits_one_dispatch_witness_without_consuming_dispatch_slot():
    epochs = "owner", "policy"
    pool = ContextPreparations(lambda: None)
    gate = Event()
    demand = []

    def load(row, epochs):
        assert gate.wait(5)
        return cast(PreparedAdmissionContext, (object(), object()))

    def observe(kind, timing):
        demand.append(kind)

    try:
        assert pool.try_submit(_row("occupied"), epochs, load, dispatch_work_id="other")
        assert not pool.try_submit(_row("run"), epochs, load, dispatch_work_id="stage-a", observe_demand=observe)
        assert not pool.try_submit(_row("run"), epochs, load, dispatch_work_id="stage-b", observe_demand=observe)
        assert pool.try_submit(_row("run"), epochs, load)  # Discovery services the refused demand.
        assert pool.try_submit(_row("run"), epochs, load, dispatch_work_id="stage-c", observe_demand=observe)
        item = pool._pending["run"]
        assert not item.for_dispatch and item.dispatch_work_id == "stage-b"
        assert demand == ["requested", "joined_waiter", "joined_pending"]
        gate.set()
        for item in pool._pending.values():
            item.future.result(5)
        pool.completed()
        assert pool.try_submit(_row("another"), epochs, load)
        assert pool.try_submit(_row("another"), epochs, load, dispatch_work_id="joined-first")
        assert pool._pending["another"].dispatch_work_id == "joined-first"
    finally:
        gate.set()
        pool.close()


def test_installed_context_hints_exact_stage_even_when_run_observation_yields():
    import pytest
    from loom.queue._completion_inbox import CompletionInbox
    from loom.queue._coordinator_run_progress import reconcile_admission
    from loom.queue._run_observations import RunObservationPending

    inbox = CompletionInbox[str](lambda: None)
    row = _row("current")
    ctx = cast(PreparedAdmissionContext, (object(), object()))

    def awaiting_read(*args, dispatch_work_id):
        retained.append(dispatch_work_id)
        assert owner._cycle_contexts[row.admission_id] == ctx
        raise RunObservationPending()

    retained = []
    observations = SimpleNamespace(snapshot_for_preparation=lambda *args: object())
    owner: Any = SimpleNamespace(
        daemon=SimpleNamespace(_epoch="coordinator", _scheduling_epoch="policy", _result_verifications=SimpleNamespace(bulk=None)),
        _cycle_contexts={}, _cycle_context_epochs={}, _cycle_context_revisions={}, _ready_continuations=inbox,
        run_observations=SimpleNamespace(advance=awaiting_read), dispatch_observations=observations,
        _ready_preparations=SimpleNamespace(owns_request=lambda key: False),
    )
    with pytest.raises(RunObservationPending):
        reconcile_admission(owner, row, prepared_context=ctx, dispatch_work_id="exact-stage")
    assert inbox.take() == ("exact-stage",)
    with pytest.raises(RunObservationPending):
        reconcile_admission(owner, row, prepared_context=ctx)
    assert not inbox.take()
    observations.snapshot_for_preparation = lambda *args: None
    with pytest.raises(RunObservationPending):
        reconcile_admission(owner, row, prepared_context=ctx, dispatch_work_id="awaiting-snapshot")
    assert not inbox.take() and retained[-1] == "awaiting-snapshot"
    owner.run_observations.advance = lambda *a, **kw: object()
    owner._observed_ready = {row.admission_id: object()}
    reconcile_admission(owner, row, prepared_context=ctx, dispatch_work_id=retained[-1])
    assert inbox.take() == ("awaiting-snapshot",)
    owner._ready_preparations.owns_request = lambda key: True
    reconcile_admission(owner, row, prepared_context=ctx, dispatch_work_id="already-queued")
    assert not inbox.take()
