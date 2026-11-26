"""Bounded scheduler traversal must not repeatedly inspect a blocked prefix."""

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

from loom.queue import _coordinator_run_progress as progress
from loom.queue._ready_window import ReadyWindowReader, ReadyWindowScheduler
from loom.queue._scheduling_waits import SchedulingWaits
from loom.queue.local_daemon import LocalDaemonAdmissionState


def test_blocked_prefix_continues_across_cycles_and_rotates_only_after_dispatch():
    records = tuple(range(1030))
    visited = []
    wakes = []

    class Store:
        def ready_window(self, *, after=None, rotate_after=None, ready_through=None, enqueue_through=None, gpu_heads_only=False):
            assert not gpu_heads_only
            assert rotate_after == 7
            assert (ready_through, enqueue_through) == (10, 8)
            offset = 0 if after is None else after + 1
            return records[offset:offset + 256]

    def dispatch(page):
        visited.extend(page)
        if 1029 in page:
            return "next-run", progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)
        return None

    owner = ReadyWindowScheduler(cast(ReadyWindowReader, Store().ready_window), lambda: 10, lambda: wakes.append(True))
    owner._prefer_gpu_dispatch = False
    owner._last_dispatch_enqueue = 7
    admissions: dict[str, Any] = {"next-run": SimpleNamespace(enqueue_sequence=8)}
    assert owner.select(admissions, dispatch) is None
    assert visited == list(range(1024))
    assert wakes == [True]
    assert owner._last_dispatch_enqueue == 7
    assert owner._ready_scan_boundary == (10, 8)
    # A new admission cannot move the in-progress sweep's boundary.
    admissions["new-arrival"] = SimpleNamespace(enqueue_sequence=9)
    selected = owner.select(admissions, dispatch)
    assert selected is not None and selected[0] == "next-run"
    assert visited == list(records)
    assert owner._ready_scan_after is None
    assert owner._ready_scan_boundary is None
    assert owner._last_dispatch_enqueue == 8


def test_ready_gpu_work_waits_for_its_prepared_context_then_dispatches(monkeypatch):
    from loom.pipeline.runtime import ExecutionRouteKind
    from loom.scheduling import PolicyDecisionState
    from loom.queue import _action_results
    from time import monotonic_ns

    monkeypatch.setattr(_action_results, "action_attempt_cancelled", lambda *args: False)

    admission: Any = SimpleNamespace(admission_id="gpu-run", run_uri="file:///gpu", cancellation_operation_id=None)
    record: Any = SimpleNamespace(
        admission_id=admission.admission_id, run_uri=admission.run_uri,
        attempt_id="fit-1", stage_work_id="fit-work", stage_name="fit",
        projection_revision=1, ready_at="2026-11-26T00:00:00Z",
        placement=SimpleNamespace(route=SimpleNamespace(
            kind=ExecutionRouteKind.SLURM, profile_id="gpu", profile_configuration_fingerprint="profile",
        )),
    )
    opened, dispatched = [], []
    snapshot = object()
    context = (SimpleNamespace(max_parallel_stages=None), SimpleNamespace(open_run=lambda uri: snapshot))

    def open_context(selected):
        opened.append(selected)
        return context

    def dispatch(**selection):
        assert selection["snapshot"] is snapshot
        dispatched.append(selection["stage_work_id"])
        owner._scheduling_waits.queued(record, monotonic_ns())
        owner._scheduling_waits.reserved(record, "fit-assignment", None, None)
        return progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)

    owner: Any = SimpleNamespace(
        daemon=None,
        _daemon_owner=lambda: SimpleNamespace(_accepted_snapshot=lambda: ("revision", "time")),
        _attempt_cancel_requested=lambda *args: False,
        _cycle_contexts={}, _admission_context=open_context,
        _scheduling_waits=SchedulingWaits(),
        cancellation_operation=lambda identity: None,
        _remote_candidates=lambda: {}, agent_id=None, _full_offer_hosts=set(),
        config=SimpleNamespace(agent_policy=SimpleNamespace(agents=()),
                               resident_worker_launch_profile=None, control_database=None,
                               connect_database=lambda _: nullcontext(None)),
        _scheduling=SimpleNamespace(kernel=lambda records: SimpleNamespace(
            decide=lambda **kwargs: SimpleNamespace(state=PolicyDecisionState.WAIT),
        )),
        _slurm_profile=lambda *args: SimpleNamespace(available=True),
        _failure_policy_allows_new_work=lambda *args: True,
        _dispatch_slurm_ready=dispatch,
    )
    assert progress._schedule_window(owner, {admission.admission_id: admission}, (record,)) is None
    assert opened == [] and dispatched == []
    owner._cycle_contexts[admission.admission_id] = context
    selected = progress._schedule_window(owner, {admission.admission_id: admission}, (record,))
    assert selected is not None and selected[0] == "gpu-run"
    assert opened == [] and dispatched == ["fit-work"]
    summary, = owner._scheduling_waits.summaries(admission.run_uri)
    assert summary["prequeue_wait_ns"]["context_unavailable"] > 0
    owner._cycle_contexts.clear()
    admission.cancellation_operation_id = "cancel"
    assert progress._schedule_window(owner, {admission.admission_id: admission}, (record,)) is None
    assert opened == [] and dispatched == ["fit-work"]


def test_full_slot_observation_only_explains_prequeue_wait_on_demand_only_route(monkeypatch):
    from loom.pipeline.runtime import ExecutionRouteKind
    from loom.queue import _action_results, _scheduling_waits
    from loom.scheduling import PolicyDecisionState

    now = [10]
    monkeypatch.setattr(_action_results, "action_attempt_cancelled", lambda *args: False)
    monkeypatch.setattr(_scheduling_waits, "monotonic_ns", lambda: now[0])
    monkeypatch.setattr(_scheduling_waits, "milestone", lambda *args, **kwargs: None)
    admission = SimpleNamespace(admission_id="run", revision=1)
    profile = SimpleNamespace(project_fingerprint="project", environment_fingerprint="env", executor_fingerprint="exec")
    local_profile = SimpleNamespace(project_fingerprint="local", environment_fingerprint="env", executor_fingerprint="exec")
    records = [SimpleNamespace(
        admission_id="run", run_uri="file:///run", attempt_id=name, stage_work_id=name, stage_name=name,
        ready_at=1, projection_revision=1, to_work_item=lambda: None, execution_requirement=required,
        placement=SimpleNamespace(route=SimpleNamespace(kind=ExecutionRouteKind.MANAGED_AGENT), target="host"),
    ) for name, required in [("early", profile), ("local", local_profile)]]
    waits = _scheduling_waits.SchedulingWaits()
    owner: Any = SimpleNamespace(
        daemon=SimpleNamespace(_epoch="e", _scheduling_epoch="s"),
        _scheduling=SimpleNamespace(retained_slurm_profiles={}, kernel=lambda group: SimpleNamespace(
            decide=lambda **kwargs: SimpleNamespace(state=PolicyDecisionState.WAIT))),
        config=SimpleNamespace(control_database=None, connect_database=lambda _: nullcontext(None),
            agent_policy=SimpleNamespace(agents=[SimpleNamespace(agent_id="host")]), resident_worker_launch_profile=None,
            remote_profiles=(profile,), container_capabilities=()),
        _daemon_owner=lambda: SimpleNamespace(_accepted_snapshot=lambda: ("decision", "utc")),
        _cycle_contexts={"run": (SimpleNamespace(max_parallel_stages=None), None)},
        _cycle_context_revisions={"run": 1}, _cycle_context_epochs={"run": ("e", "s")},
        _ready_preparations=SimpleNamespace(anticipation_wait=lambda key: "early_retention_limit",
                                            request_queued_ns=lambda key, work: None),
        _scheduling_waits=waits, _remote_candidates=lambda: {}, _full_offer_hosts={"host"}, agent_id=None,
    )
    for record in records:
        waits.ready(record)
    now[0] = 20
    assert progress._schedule_window(owner, {"run": admission}, tuple(records)) is None
    now[0] = 50
    for record in records:
        waits.queued(record, 40)
        waits.reserved(record, record.stage_name + "-assignment", None, None)
    early, local = waits.summaries("file:///run")
    assert early["prequeue_wait_ns"] == {"first_scan": 10, "unknown": 0, "early_retention_limit": 20}
    assert local["prequeue_wait_ns"] == {"first_scan": 10, "unknown": 0, "assignment_slots_full": 20}


def test_gpu_opportunities_alternate_with_cpu_and_failed_reservation_falls_back():
    calls = []
    gpu_available = [True]

    class Store:
        def ready_window(self, *, gpu_heads_only=False, **kwargs):
            calls.append("gpu" if gpu_heads_only else "ordinary")
            return ("fit",) if gpu_heads_only else ("score",)

    def dispatch(page):
        if page == ("fit",) and not gpu_available[0]:
            return None
        return page[0], progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)

    owner = ReadyWindowScheduler(cast(ReadyWindowReader, Store().ready_window), lambda: 10, lambda: None)
    admissions: dict[str, Any] = {"score": SimpleNamespace(enqueue_sequence=1), "fit": SimpleNamespace(enqueue_sequence=2)}
    selected = owner.select(admissions, dispatch)
    assert selected is not None and selected[0] == "fit"
    selected = owner.select(admissions, dispatch)
    assert selected is not None and selected[0] == "score"
    gpu_available[0] = False
    selected = owner.select(admissions, dispatch)
    assert selected is not None and selected[0] == "score"
    assert owner._last_gpu_dispatch_enqueue == 2
    assert calls == ["gpu", "ordinary", "gpu", "ordinary"]


def test_cpu_dispatch_does_not_reset_blocked_gpu_opportunity_scan():
    visited = []

    class Store:
        def ready_window(self, *, gpu_heads_only=False, after=None, rotate_after=None, **kwargs):
            if not gpu_heads_only:
                return ("score",)
            assert rotate_after is None
            offset = 0 if after is None else after + 1
            return tuple(range(offset, min(offset + 256, 257)))

    def dispatch(page):
        if page == ("score",):
            return "score", progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)
        visited.extend(page)
        if 256 in page:
            return "fit", progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)
        return None

    owner = ReadyWindowScheduler(cast(ReadyWindowReader, Store().ready_window), lambda: 10, lambda: None)
    admissions: dict[str, Any] = {"score": SimpleNamespace(enqueue_sequence=1), "fit": SimpleNamespace(enqueue_sequence=2)}
    selected = owner.select(admissions, dispatch)
    assert selected is not None and selected[0] == "score"
    assert owner._gpu_scan_after == 255
    selected = owner.select(admissions, dispatch)
    assert selected is not None and selected[0] == "score"
    selected = owner.select(admissions, dispatch)
    assert selected is not None and selected[0] == "fit"
    assert visited == list(range(257))
    assert owner._gpu_scan_after is None and owner._gpu_scan_boundary is None
    assert owner._last_gpu_dispatch_enqueue == 2
