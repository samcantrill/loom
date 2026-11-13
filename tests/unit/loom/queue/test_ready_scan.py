"""Bounded scheduler traversal must not repeatedly inspect a blocked prefix."""

from threading import Lock
from types import SimpleNamespace

from loom.queue import _coordinator_run_progress as progress
from loom.queue.local_daemon import LocalDaemonAdmissionState


def test_blocked_prefix_continues_across_cycles_and_rotates_only_after_dispatch(monkeypatch):
    records = tuple(range(1030))
    visited = []
    wakes = []

    class Store:
        def ready_window(self, *, after=None, rotate_after=None, ready_through=None, enqueue_through=None):
            assert rotate_after == 7
            assert (ready_through, enqueue_through) == (10, 8)
            offset = 0 if after is None else after + 1
            return records[offset:offset + 256]

    def dispatch(owner, admissions, page, **kwargs):
        visited.extend(page)
        if 1029 in page:
            return "next-run", progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)
        return None

    monkeypatch.setattr(progress, "_schedule_window", dispatch)
    owner = SimpleNamespace(
        _launch_lock=Lock(), stage_work_store=Store(), _ready_scan_after=None,
        _last_dispatch_enqueue=7, _ready_scan_boundary=None, _prefer_gpu_dispatch=False,
        _daemon_owner=lambda: SimpleNamespace(
            _wake=SimpleNamespace(set=lambda: wakes.append(True)),
            _accepted_snapshot=lambda: ("revision", 10),
        ),
    )
    admissions = {"next-run": SimpleNamespace(enqueue_sequence=8)}
    assert progress.schedule_once(owner, admissions) is None
    assert visited == list(range(1024))
    assert wakes == [True]
    assert owner._last_dispatch_enqueue == 7
    assert owner._ready_scan_boundary == (10, 8)
    # A new admission cannot move the in-progress sweep's boundary.
    admissions["new-arrival"] = SimpleNamespace(enqueue_sequence=9)
    assert progress.schedule_once(owner, admissions)[0] == "next-run"
    assert visited == list(records)
    assert owner._ready_scan_after is None
    assert owner._ready_scan_boundary is None
    assert owner._last_dispatch_enqueue == 8


def test_ready_gpu_work_outside_reconciliation_batch_opens_exact_context():
    from loom.pipeline.runtime import ExecutionRouteKind
    from loom.scheduling import PolicyDecisionState

    admission = SimpleNamespace(admission_id="gpu-run", run_uri="file:///gpu", cancellation_operation_id=None)
    record = SimpleNamespace(
        admission_id=admission.admission_id, run_uri=admission.run_uri,
        attempt_id="fit-1", stage_work_id="fit-work",
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
        return progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)

    owner = SimpleNamespace(
        _daemon_owner=lambda: SimpleNamespace(_accepted_snapshot=lambda: ("revision", "time")),
        _attempt_cancel_requested=lambda *args: False,
        _cycle_contexts={}, _admission_context=open_context,
        cancellation_operation=lambda identity: None,
        _remote_candidates=lambda: {}, agent_id=None,
        config=SimpleNamespace(resident_worker_launch_profile=None),
        _scheduling=SimpleNamespace(kernel=lambda records: SimpleNamespace(
            decide=lambda **kwargs: SimpleNamespace(state=PolicyDecisionState.WAIT),
        )),
        _slurm_profile=lambda *args: SimpleNamespace(available=True),
        _failure_policy_allows_new_work=lambda *args: True,
        _dispatch_slurm_ready=dispatch,
    )
    assert progress._schedule_window(owner, {admission.admission_id: admission}, (record,))[0] == "gpu-run"
    assert opened == [admission] and dispatched == ["fit-work"]
    owner._cycle_contexts.clear()
    admission.cancellation_operation_id = "cancel"
    assert progress._schedule_window(owner, {admission.admission_id: admission}, (record,)) is None
    assert opened == [admission] and dispatched == ["fit-work"]


def test_gpu_opportunities_alternate_with_cpu_and_failed_reservation_falls_back(monkeypatch):
    calls = []
    gpu_available = [True]

    class Store:
        def ready_window(self, *, gpu_heads_only=False, **kwargs):
            calls.append("gpu" if gpu_heads_only else "ordinary")
            return ("fit",) if gpu_heads_only else ("score",)

    def dispatch(owner, admissions, page, **kwargs):
        if page == ("fit",) and not gpu_available[0]:
            return None
        return page[0], progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)

    monkeypatch.setattr(progress, "_schedule_window", dispatch)
    owner = SimpleNamespace(
        _launch_lock=Lock(), stage_work_store=Store(), _ready_scan_after=None,
        _ready_scan_boundary=None, _last_dispatch_enqueue=None,
        _prefer_gpu_dispatch=True, _gpu_scan_after=None, _gpu_scan_boundary=None,
        _last_gpu_dispatch_enqueue=None,
        _daemon_owner=lambda: SimpleNamespace(_accepted_snapshot=lambda: ("revision", 10)),
    )
    admissions = {"score": SimpleNamespace(enqueue_sequence=1), "fit": SimpleNamespace(enqueue_sequence=2)}
    assert progress.schedule_once(owner, admissions)[0] == "fit"
    assert progress.schedule_once(owner, admissions)[0] == "score"
    gpu_available[0] = False
    assert progress.schedule_once(owner, admissions)[0] == "score"
    assert owner._last_gpu_dispatch_enqueue == 2
    assert calls == ["gpu", "ordinary", "gpu", "ordinary"]


def test_cpu_dispatch_does_not_reset_blocked_gpu_opportunity_scan(monkeypatch):
    visited = []

    class Store:
        def ready_window(self, *, gpu_heads_only=False, after=None, rotate_after=None, **kwargs):
            if not gpu_heads_only:
                return ("score",)
            assert rotate_after is None
            offset = 0 if after is None else after + 1
            return tuple(range(offset, min(offset + 256, 257)))

    def dispatch(owner, admissions, page, **kwargs):
        if page == ("score",):
            return "score", progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)
        visited.extend(page)
        if 256 in page:
            return "fit", progress.LocalDaemonExecutionOutcome(LocalDaemonAdmissionState.ACTIVE)
        return None

    monkeypatch.setattr(progress, "_schedule_window", dispatch)
    owner = SimpleNamespace(
        _launch_lock=Lock(), stage_work_store=Store(), _ready_scan_after=None,
        _ready_scan_boundary=None, _last_dispatch_enqueue=None,
        _prefer_gpu_dispatch=True, _gpu_scan_after=None, _gpu_scan_boundary=None,
        _last_gpu_dispatch_enqueue=None,
        _daemon_owner=lambda: SimpleNamespace(_accepted_snapshot=lambda: ("revision", 10)),
    )
    admissions = {"score": SimpleNamespace(enqueue_sequence=1), "fit": SimpleNamespace(enqueue_sequence=2)}
    assert progress.schedule_once(owner, admissions)[0] == "score"
    assert owner._gpu_scan_after == 255
    assert progress.schedule_once(owner, admissions)[0] == "score"
    assert progress.schedule_once(owner, admissions)[0] == "fit"
    assert visited == list(range(257))
    assert owner._gpu_scan_after is None and owner._gpu_scan_boundary is None
    assert owner._last_gpu_dispatch_enqueue == 2
