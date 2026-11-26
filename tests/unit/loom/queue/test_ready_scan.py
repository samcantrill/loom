"""Bounded scheduler traversal must not repeatedly inspect a blocked prefix."""

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

from loom.queue import _coordinator_run_progress as progress
from loom.queue._ready_window import ReadyWindowReader, ReadyWindowScheduler, ScanYield
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
    assert owner.select(admissions, dispatch) is ScanYield.MORE
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

    monkeypatch.setattr(_action_results, "launchable_page", lambda conn, page: page)

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
    monkeypatch.setattr(_action_results, "launchable_page", lambda conn, page: page)
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


def test_deadline_yields_after_gpu_then_resumes_each_completed_cpu_page(monkeypatch):
    from loom.queue import _ready_window
    from loom.pipeline.orchestration import READY_WINDOW_LIMIT

    n = READY_WINDOW_LIMIT
    now = [0.0]
    visits = []
    def read(*, after, gpu_heads_only=False, **kwargs):
        if gpu_heads_only:
            return ("gpu",)
        offset = 0 if after is None else after + 1
        return tuple(range(offset, min(offset + n, n + 2)))

    def offer(page):
        visits.extend(page)
        now[0] += 1
        return None

    monkeypatch.setattr(_ready_window, "monotonic", lambda: now[0])
    scheduler = ReadyWindowScheduler(cast(ReadyWindowReader, read), lambda: 1, lambda: None)
    admissions = {"run": SimpleNamespace(enqueue_sequence=1)}
    assert scheduler.select(admissions, offer, deadline=0.1) is ScanYield.MORE
    assert scheduler.select(admissions, offer, deadline=1.1) is ScanYield.MORE
    assert scheduler.select(admissions, offer, deadline=10.0) is None
    assert [v for v in visits if v != "gpu"] == list(range(n + 2))
    assert visits.count("gpu") == 2


def test_requested_read_survives_slow_turn_and_retires_only_current_interest(monkeypatch):
    from loom.queue import _run_observations as observations
    from threading import Event

    now = [1_000_000_000]
    wake = Event()
    loads = []
    spans = []
    notices = []
    monkeypatch.setattr(observations, "monotonic_ns", lambda: now[0])
    monkeypatch.setattr(observations, "milestone", lambda event, **data: spans.append(data))
    owner = observations.DispatchObservations(wake.set)
    admission = SimpleNamespace(admission_id="a", run_uri="run", revision=1)
    epochs = ("coordinator", "policy")
    def read():
        loads.append(True)
        return "snapshot"
    try:
        assert owner.poll(admission, epochs, read, work_id="one", peers={"one", "two", "gone"}) is None
        assert wake.wait(5)
        now[0] += 5_370_000_000
        owner.begin_cycle(set(), epochs, 1.0, {"a": 1}, lambda ids: ids - {"gone"}, notices.append)
        assert notices == ["one", "two"]
        assert owner.selected("a", "one") and not owner.selected("a", "two")
        assert owner.poll(admission, epochs, read, work_id="one", peers={"two"}) == "snapshot"
        owner.transferred(admission, epochs, "one")
        notices.clear()  # Simulate losing the coalesced inbox hint for the sibling.
        owner.begin_cycle(set(), epochs, 1.0, {"a": 1}, lambda ids: ids, notices.append)
        assert notices == ["two"]
        assert owner.poll(admission, epochs, read, work_id="two", peers=set()) == "snapshot"
        owner.transferred(admission, epochs, "two")
        assert len(loads) == 1 and owner.requested_runs() == set()
        assert [s["completion_wait_ns"] for s in spans] == [5_370_000_000] * 2
        for revisions, ready, next_epochs in [({"a": 2}, {"one"}, epochs), ({}, {"one"}, epochs),
                                              ({"a": 1}, set(), epochs), ({"a": 1}, {"one"}, ("new","policy"))]:
            owner.begin_cycle(set(), epochs, 1, {}, lambda ids: ids, notices.append)
            wake.clear()
            assert owner.poll(admission, epochs, read, work_id="one", peers=set()) is None
            assert wake.wait(5)
            owner.begin_cycle(set(), next_epochs, 1, revisions, lambda ids: ids & ready, notices.append)
            assert owner.requested_runs() == set()
    finally:
        owner.close()


def test_continuing_admission_contexts_outlive_the_sixteen_entry_validation_cache():
    from loom.queue.local_daemon_execution import LocalDaemonExecution

    owner = object.__new__(LocalDaemonExecution)
    epochs = ("owner", "policy")
    records = [SimpleNamespace(admission_id=str(i), run_uri=str(i), revision=1) for i in range(20)]
    validated = {r.admission_id: (SimpleNamespace(plan=SimpleNamespace(run_uri=r.run_uri)), object()) for r in records}
    owner._cycle_contexts = dict(validated)
    owner._cycle_context_epochs = {k: epochs for k in validated}
    owner._cycle_context_revisions = {k: 1 for k in validated}
    observations = set(validated)
    building = set()
    owner.run_observations = SimpleNamespace(pending_runs=set)
    owner.dispatch_observations = SimpleNamespace(requested_runs=lambda: observations)
    owner._ready_preparations = SimpleNamespace(preparing_runs=lambda: building)
    for row in records:
        building.add(row.run_uri)
        observations.remove(row.run_uri)
        owner.retain_dispatch_contexts(set(), epochs, set())
        assert owner.continuation_context(row, epochs) is validated[row.admission_id]
    records[0].revision += 1
    assert owner.continuation_context(records[0], epochs) is None
    owner.retain_dispatch_contexts({"1"}, epochs, set())
    assert owner.continuation_context(records[1], epochs) is None
    owner.retain_dispatch_contexts(set(), ("owner", "new"), set())
    assert not owner._cycle_contexts


def test_unreadable_input_leaves_the_only_host_available_to_its_peer(monkeypatch):
    from time import monotonic_ns
    from loom.pipeline.runtime import ExecutionRouteKind
    from loom.queue import _action_results, local_daemon_execution as execution
    from loom.pipeline.runtime import CpuResourcePlanner
    from loom.scheduling import FifoSchedulingPolicy, SchedulingKernel
    from tests.unit.loom.scheduling.test_kernel import _candidate, _work

    host = _candidate("only")
    profile = SimpleNamespace(project_fingerprint="p", environment_fingerprint="e", executor_fingerprint="x")
    target = SimpleNamespace(profile=profile, offer_id="offer", expires_ns=monotonic_ns() + 10**10)
    admission = SimpleNamespace(admission_id="run", run_uri="file:///run", cancellation_operation_id=None)
    records = {stage: SimpleNamespace(
        stage_name=stage, run_uri=admission.run_uri, admission_id="run", stage_work_id=stage, attempt_id=stage+"-1",
        projection_revision=1, ready_at=1, execution_requirement=profile, to_work_item=lambda name=stage: _work(name),
        placement=SimpleNamespace(route=SimpleNamespace(kind=ExecutionRouteKind.MANAGED_AGENT), target=None),
    ) for stage in ("a", "b")}
    inspected, reserved = [], []
    def inspect(record, worker):
        inspected.append(record.stage_name)
        if record.stage_name == "a":
            raise OSError("input is unreadable")
        return (), None

    intent = SimpleNamespace(max_parallel_stages=None, pipeline=SimpleNamespace(get_stage=lambda name: name),
                             plan=SimpleNamespace(ordered_stage_plans=list(records.values()), fingerprint_context=None))
    owner = SimpleNamespace(
        daemon=None, agent_id=None, _full_offer_hosts=set(), _scheduling_waits=SchedulingWaits(),
        config=SimpleNamespace(connect_database=lambda _: nullcontext(None), control_database=None,
            agent_policy=SimpleNamespace(agents=()), resident_worker_launch_profile=None),
        _daemon_owner=lambda: SimpleNamespace(_accepted_snapshot=lambda: ("decision", 1)),
        _cycle_contexts={"run": (intent, SimpleNamespace(open_run=lambda uri: object()))},
        _remote_candidates=lambda: {"only": (host, target)}, _failure_policy_allows_new_work=lambda *args: True,
        _scheduling=SimpleNamespace(kernel=lambda _: SchedulingKernel(planners={"cpu": CpuResourcePlanner()},
                                                                     policy=FifoSchedulingPolicy())),
        _ready_preparations=SimpleNamespace(request_available_ns=lambda *args: None),
        stage_work_store=SimpleNamespace(find_stage_work=records.get),
        _prepared_ready_request=lambda *args: (object(), None), _prepared_input_descriptors=inspect,
        _execute=lambda **kw: reserved.append(kw["record"].stage_name) or True,
    )
    owner._remote_preparation_wait = lambda **kw: execution.LocalDaemonExecution._remote_preparation_wait(owner, **kw)
    monkeypatch.setattr(_action_results, "launchable_page", lambda _, page: page)
    monkeypatch.setattr(execution, "bind_stage_inputs", lambda **kw: {})
    monkeypatch.setattr(execution, "build_stage_fingerprint", lambda *a, **kw: SimpleNamespace(to_dict=dict))
    monkeypatch.setattr(execution, "_worker_runtime", lambda *a: SimpleNamespace(_to_worker_metadata=dict))
    monkeypatch.setattr(execution, "_produced_outputs", lambda snapshot: {})
    monkeypatch.setattr(execution, "_validate_remote_semantic_data", lambda **kw: None)
    selected = progress._schedule_window(owner, {"run": admission}, tuple(records.values()))
    assert selected is not None and selected[0] == "run"
    assert inspected == ["a", "b"] and reserved == ["b"]


def test_new_selection_reclaims_peer_only_observation_at_capacity():
    from threading import Event
    from loom.queue._run_observations import DispatchObservations

    wake = Event()
    owner = DispatchObservations(wake.set)
    epochs = ("epoch", "policy")
    try:
        for index in range(33):
            admission = SimpleNamespace(admission_id=str(index), run_uri=str(index), revision=1)
            work = f"selected-{index}"
            wake.clear()
            assert owner.poll(admission, epochs, lambda: "result", work_id=work, peers={"blocked-sibling"}) is None
            assert wake.wait(2), index
            assert owner.poll(admission, epochs, lambda: "result", work_id=work, peers=set()) == "result"
            owner.transferred(admission, epochs, work)
        assert len(owner.requested_admissions()) == 32
        assert "0" not in owner.requested_admissions()
    finally:
        owner.close()

def test_dispatch_context_advances_when_read_is_accepted_even_if_worker_is_held():
    from threading import Event
    from loom.queue._run_observations import DispatchObservations

    gate = Event()
    reads = DispatchObservations(lambda: None)
    epochs = ("owner", "policy")
    advanced = []
    timing = SimpleNamespace(advance=advanced.append)
    def load():
        assert gate.wait(5)
        return "done"
    def poll(identity):
        job = SimpleNamespace(admission_id=identity, revision=1)
        return reads.poll(cast(Any, job), epochs, cast(Any, load), work_id=identity,
                          peers=set(), timing=cast(Any, timing))
    try:
        assert poll("one") is None and poll("two") is None
        assert advanced == ["dispatch_observation"] * 2
        assert poll("refused") is None and poll("one") is None
        assert advanced == ["dispatch_observation"] * 2
    finally:
        gate.set()
        reads.close()


def test_ready_context_advances_only_after_preparation_capacity_accepts_work(monkeypatch):
    from loom.pipeline.runtime import ExecutionRouteKind

    admission = SimpleNamespace(admission_id="admission")
    revision = SimpleNamespace(sequence=1)
    record = SimpleNamespace(placement=SimpleNamespace(route=SimpleNamespace(kind=ExecutionRouteKind.MANAGED_AGENT)),
                             run_uri="run", stage_name="stage", stage_work_id="work", authority_revision=revision)
    queued = []
    advances = []
    context = object(), SimpleNamespace(_context_timing=SimpleNamespace(advance=advances.append))
    owner = SimpleNamespace(
        config=SimpleNamespace(remote_profiles=(), container_capabilities=()),
        _ready_preparations=SimpleNamespace(request_for_descriptors=lambda *args: (False, None),
                                            request_queued_ns=lambda *args: next(iter(queued), None)),
        _observed_ready={"admission": SimpleNamespace(revision=revision)},
        _scheduling_waits=SimpleNamespace(prequeue=lambda *args: None),
        _prepared_ready_request=lambda *args: (None, "stage_preparation_capacity"),
    )
    monkeypatch.setattr(progress, "_dispatch_policy_allows", lambda *args: True)
    monkeypatch.setattr(progress, "_current_ready_attempt", lambda *args: True)
    assert progress._advance_ready_inputs(owner, record, admission, context, ("owner", "policy"), anticipated=False)
    assert not advances
    owner._prepared_ready_request = lambda *args: queued.append(123)
    assert progress._advance_ready_inputs(owner, record, admission, context, ("owner", "policy"), anticipated=False)
    assert advances == ["stage_preparation"]
