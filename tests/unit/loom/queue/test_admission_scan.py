"""A finite admission sweep advances despite cancellation and new submissions."""

from types import SimpleNamespace

from loom.queue._admission_scan import AdmissionScan


def accept(_admission):
    return True


def row(index, priority=0):
    return SimpleNamespace(admission_id=f"admission-{index}", enqueue_sequence=index, run_priority=priority)


def test_admission_batches_bound_reconciliation_and_restart_at_priority_head():
    scan = AdmissionScan()
    admissions = [row(index) for index in range(70)]
    assert scan.take(admissions, accept) == tuple(admissions[:32])
    assert scan.take(admissions, accept) == tuple(admissions[32:64])
    assert scan.take(admissions, accept) == tuple(admissions[64:])
    assert scan.after is None
    urgent = row(70, priority=5)
    assert scan.take([urgent, *admissions], accept)[0] is urgent
    assert AdmissionScan().take([urgent, *admissions], accept)[0] is urgent


def test_new_arrivals_cannot_extend_sweep_and_deleted_cursor_does_not_skip_work():
    scan = AdmissionScan()
    initial = [row(index) for index in range(5)]
    assert scan.take(initial, accept, limit=2) == tuple(initial[:2])
    urgent = row(5, priority=10)
    changed = [urgent, initial[0], *initial[2:], row(6)]
    assert scan.take(changed, accept, limit=2) == tuple(initial[2:4])
    assert scan.take(changed, accept, limit=2) == (initial[4],)
    assert scan.after is None
    assert scan.take(changed, accept, limit=2)[0] is urgent


def test_empty_scan_resets_cursor_after_all_remaining_runs_settle():
    scan = AdmissionScan()
    scan.take([row(index) for index in range(40)], accept)
    assert scan.take([], accept) == ()
    assert scan.after is None and scan.high_water is None
    assert len(scan.take([row(50)], accept)) == 1


def test_slow_cycle_diagnostics_are_bounded_and_cannot_change_lifecycle_result(monkeypatch):
    from loom.queue import local_daemon, _phase_timing

    diagnostics = []
    expected = (row(1),)
    from threading import RLock
    owner = SimpleNamespace(_reconcile_once=lambda: expected, _reconcile_guard=RLock())
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(local_daemon.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(_phase_timing, "log_phases", diagnostics.append)
    assert local_daemon.LocalDaemon.reconcile_once(owner) is expected
    assert len(diagnostics) == 1
    assert diagnostics[0]["spans"][0]["action"] == "coordinator.reconcile_cycle"
    ticks = iter([0.0, 2.0])

    def unavailable_log(value):
        raise OSError("log unavailable")

    monkeypatch.setattr(_phase_timing, "log_phases", unavailable_log)
    assert local_daemon.LocalDaemon.reconcile_once(owner) is expected


def test_scan_resumes_at_first_admission_refused_for_capacity():
    scan = AdmissionScan()
    initial = [row(index) for index in range(35)]
    first = scan.take(initial, lambda entry: entry.enqueue_sequence < 2)
    assert first == tuple(initial[:2])
    late = row(35, priority=10)
    assert scan.take([late, *initial], accept) == tuple(initial[2:34])
    assert scan.take([late, *initial], accept) == (initial[34],)
    assert scan.take([late, *initial], accept)[0] is late
