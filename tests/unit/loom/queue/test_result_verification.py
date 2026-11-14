"""Actual IO capacity and diagnostic ownership of background result audits."""

from threading import Barrier, Event

import pytest

from loom.queue._phase_timing import observe_phases, phase
from loom.queue._result_verification import ResultVerifications


pytestmark = pytest.mark.unit


def test_audits_have_no_backlog_and_close_retains_running_capacity():
    entered = Barrier(3)
    release = Event()
    woke = Event()
    pool = ResultVerifications(woke.set)
    calls = []

    def verify(outputs):
        calls.append(outputs)
        entered.wait(timeout=10)
        assert release.wait(timeout=10)

    try:
        for identity in ("first", "second", "excess", "first"):
            pool.submit({"claim_id": identity}, ("epoch", "schedule"), {}, {}, verify)
        entered.wait(timeout=10)
        assert len(calls) == 2
        assert pool.completed() == ()
        pool.close()
        assert pool.running()
        pool.submit({"claim_id": "after-close"}, (None, None), {}, {}, verify)
        release.set()
        # Wait for both actual workers, without manufacturing capacity on close.
        for item in tuple(pool._pending.values()):
            item.future.result(timeout=10)
        assert woke.wait(timeout=10)
        assert not pool.running()
        assert {item.claim["claim_id"] for item in pool.completed()} == {"first", "second"}
        assert pool.completed() == ()
        assert len(calls) == 2
    finally:
        release.set()
        pool.close()


def test_worker_failure_is_returned_to_owner_without_mutating_parent_timings():
    woke = Event()
    parent_spans = []
    pool = ResultVerifications(woke.set)

    def verify(outputs):
        with phase("publication_inventory_hash"):
            raise OSError("unreadable companion")

    try:
        with observe_phases(parent_spans.append):
            pool.submit({"claim_id": "failed"}, ("epoch", "schedule"), {}, {}, verify)
        assert woke.wait(timeout=10)
        completed, = pool.completed()
        with pytest.raises(OSError, match="unreadable companion"):
            completed.future.result()
        assert parent_spans == []
        assert not pool.running()
    finally:
        pool.close()


@pytest.mark.parametrize("cancel", [False, True])
def test_terminal_admission_waits_for_its_unsettled_action_claim(tmp_path, cancel):
    from types import SimpleNamespace

    from loom.queue._coordinator_run_progress import (
        LocalDaemonExecutionOutcome,
        _settled_terminal_outcome,
    )
    from loom.queue.local_daemon import LocalDaemonAdmissionState
    from tests.unit.loom.queue.test_action_results import _select, _store

    store = _store(tmp_path)
    claim = _select(store)["claim"]
    terminal = LocalDaemonExecutionOutcome(
        LocalDaemonAdmissionState.CANCELLED if cancel
        else LocalDaemonAdmissionState.SUCCEEDED
    )
    execution = SimpleNamespace(
        _action_resolution=SimpleNamespace(store=store),
        coordinator=SimpleNamespace(list_run_live_states=lambda uri: ()),
    )
    if cancel:
        store.detach_graph("run-a", "cancel-a")
    outcome = _settled_terminal_outcome(
        execution, "run-a", terminal,
        slurm_in_flight=False, slurm_diagnostic=None,
    )
    assert outcome.state is LocalDaemonAdmissionState.ACTIVE
    assert outcome.reason == "action result settlement remains in flight"
    store.fail(claim["claim_id"], {"code": "candidate_unavailable"})
    assert _settled_terminal_outcome(
        execution, "run-a", terminal,
        slurm_in_flight=False, slurm_diagnostic=None,
    ) == terminal


@pytest.mark.parametrize(
    "change", ["none", "cancel", "shared_cancel", "epoch", "scheduling_epoch", "authority", "retry", "corrupt"]
)
def test_delayed_proof_rechecks_demand_epochs_and_authority(tmp_path, monkeypatch, change):
    from types import SimpleNamespace

    from loom.queue._action_result_resolution import ActionResultResolution
    from loom.queue.errors import QueueConflictError
    from tests.unit.loom.queue.test_action_results import _select, _store

    store = _store(tmp_path)
    identity = _select(store)["claim"]["claim_id"]
    store.attach_fence(
        identity, run_uri="run-a", node="generate", attempt_id="attempt-a",
        assignment_id="assignment-a", fencing_token="fence-a",
    )
    if change == "shared_cancel":
        _select(store, "run-b")
    captured = store.claim(identity)
    entered, release, woke = Event(), Event(), Event()
    pool = ResultVerifications(woke.set)
    daemon = SimpleNamespace(
        _result_verifications=pool, _epoch="epoch", _scheduling_epoch="schedule"
    )
    resolver = object.__new__(ActionResultResolution)
    resolver.daemon, resolver.store = daemon, store
    checked = []

    def check_authority(claim, result):
        checked.append(claim["claim_id"])
        if change == "authority":
            raise QueueConflictError("action candidate original authority changed")
        return {}

    monkeypatch.setattr(resolver, "_checked_result_outputs", check_authority)

    def verify(outputs):
        entered.set()
        assert release.wait(timeout=10)
        if change == "corrupt":
            raise OSError("companion became unreadable")

    try:
        pool.submit(captured, ("epoch", "schedule"), {"commit": "original"}, {}, verify)
        assert entered.wait(timeout=10)
        if change in {"cancel", "shared_cancel"}:
            store.detach_graph("run-a", "cancel-a")
        elif change == "epoch":
            daemon._epoch = "successor"
        elif change == "scheduling_epoch":
            daemon._scheduling_epoch = "successor"
        elif change == "retry":
            store.fail(identity, {"code": "producer_failed"})
            retry = store.select(
                run_uri="run-a", node="generate", scope={"principal": "one"},
                identity={"digest": "a" * 64}, attempt_id="attempt-b",
                retry_authorized=True,
            )
            assert retry["decision"] == "owner"
            store.attach_fence(
                identity, run_uri="run-a", node="generate", attempt_id="attempt-b",
                assignment_id="assignment-b", fencing_token="fence-b",
            )
        release.set()
        assert woke.wait(timeout=10)
        diagnostics = []
        with observe_phases(diagnostics.append):
            resolver.complete_verifications()
        assert len(diagnostics) == 1
        assert diagnostics[0]["operation_id"] == identity
        completion, = diagnostics[0]["spans"]
        assert completion["action"] == "action_result_completion_apply"
        assert completion["outcome"] == "complete"
        assert completion["elapsed_nanoseconds"] >= 0
        current = store.claim(identity)
        if change in {"none", "shared_cancel"}:
            assert current["state"] == "succeeded"
            assert current["result_json"] is not None
            assert checked == [identity]
        else:
            assert current["result_json"] is None
            assert current["state"] == {
                "cancel": "settling", "epoch": "owned",
                "scheduling_epoch": "owned", "authority": "failed",
                "retry": "owned", "corrupt": "failed",
            }[change]
            assert checked == ([identity] if change == "authority" else [])
        # Completion consumption cannot publish a second time.
        with observe_phases(diagnostics.append):
            resolver.complete_verifications()
        assert len(diagnostics) == 1
        assert store.claim(identity) == current
    finally:
        release.set()
        pool.close()


def test_report_and_result_consumers_share_actual_io_capacity():
    entered = Barrier(3)
    release = Event()
    pool = ResultVerifications(lambda: None)

    def blocked(*args):
        entered.wait(timeout=10)
        assert release.wait(timeout=10)
        return "hydrated"

    try:
        report = pool.bulk.submit("preparation", "report_hydration", blocked)
        assert report is not None
        pool.submit({"claim_id": "producer"}, (None, None), {}, {}, blocked)
        entered.wait(timeout=10)
        assert pool.bulk.submit("excess-report", "report_hydration", blocked) is None
        pool.submit({"claim_id": "excess-producer"}, (None, None), {}, {}, blocked)
        release.set()
        assert report.result(timeout=10) == "hydrated"
        for item in tuple(pool._pending.values()):
            item.future.result(timeout=10)
        assert [item.claim["claim_id"] for item in pool.completed()] == ["producer"]
        assert not pool.running()
    finally:
        release.set()
        pool.close()



def test_fair_waiter_survives_skipped_owner_visits_and_new_work_cannot_overtake():
    from loom.queue._bulk_operations import BulkOperations

    pool = BulkOperations(lambda: None)
    entered = Barrier(3)
    release = Event()

    def occupy():
        entered.wait(timeout=10)
        assert release.wait(timeout=10)

    def offer(name):
        with pool.offering(("owner", name)):
            return pool.submit(name, "audit", lambda: name)

    try:
        running = [pool.submit(str(index), "occupied", occupy) for index in range(2)]
        entered.wait(timeout=10)
        assert offer("older") is None
        assert offer("later") is None
        release.set()
        for future in running:
            future.result(timeout=10)
        # Later work is revisited repeatedly while the older owner's scan is elsewhere.
        for _ in range(8):
            assert offer("later") is None
            with pool.offering(("owner", "unrelated")):
                pass
        older = offer("older")
        assert older is not None and older.result(timeout=10) == "older"
        assert offer("older") is None  # A new operation cannot jump the later waiter.
        later = offer("later")
        assert later is not None and later.result(timeout=10) == "later"
    finally:
        release.set()
        pool.close()


def test_owner_withdrawal_removes_waiter_without_retaining_payload_or_running_it():
    import gc
    import weakref
    from loom.queue._bulk_operations import BulkOperations

    class Payload:
        pass

    pool = BulkOperations(lambda: None)
    entered = Barrier(3)
    release = Event()
    calls = []

    def occupy():
        entered.wait(timeout=10)
        assert release.wait(timeout=10)

    try:
        running = [pool.submit(str(index), "occupied", occupy) for index in range(2)]
        entered.wait(timeout=10)
        payload = Payload()
        reference = weakref.ref(payload)
        with pool.offering(("preparation", "cancelled")):
            assert pool.submit("cancelled", "capture", calls.append, payload) is None
        del payload
        gc.collect()
        assert reference() is None
        # Visiting the cancelled owner offers no IO and withdraws its old ticket.
        with pool.offering(("preparation", "cancelled")):
            pass
        release.set()
        for future in running:
            future.result(timeout=10)
        with pool.offering(("preparation", "live")):
            live = pool.submit("live", "capture", calls.append, "live")
        assert live is not None
        live.result(timeout=10)
        assert calls == ["live"]
    finally:
        release.set()
        pool.close()


def test_retired_run_waiter_does_not_block_other_owner_or_free_running_io():
    from loom.queue._bulk_operations import BulkOperations

    pool = BulkOperations(lambda: None)
    entered = Barrier(3)
    release = Event()
    calls = []

    def occupy():
        entered.wait(timeout=10)
        assert release.wait(timeout=10)

    try:
        running = [pool.submit(str(index), "occupied", occupy) for index in range(2)]
        entered.wait(timeout=10)
        with pool.offering(("run", "retired")):
            assert pool.submit("retired", "reuse", calls.append, "retired") is None
        with pool.offering(("preparation", "live")):
            assert pool.submit("live", "capture", calls.append, "live") is None
        pool.retain(("run",), set())
        assert pool.running()
        with pool.offering(("preparation", "live")):
            assert pool.submit("live", "capture", calls.append, "live") is None
        release.set()
        for future in running:
            future.result(timeout=10)
        with pool.offering(("preparation", "live")):
            future = pool.submit("live", "capture", calls.append, "live")
        assert future is not None
        future.result(timeout=10)
        assert calls == ["live"]
    finally:
        release.set()
        pool.close()


def test_dispatch_scan_withdraws_unselected_work_but_preserves_unvisited_run():
    from loom.queue._bulk_operations import BulkOperations

    pool = BulkOperations(lambda: None)
    entered = Barrier(3)
    release = Event()
    unavailable = ("dispatch", "run-a", "stage-a", "execution")
    waiting_context = ("dispatch", "run-b", "stage-b", "execution")

    def occupy():
        entered.wait(timeout=10)
        assert release.wait(timeout=10)

    try:
        running = [pool.submit(str(index), "occupied", occupy) for index in range(2)]
        entered.wait(timeout=10)
        for scope in (unavailable, waiting_context):
            with pool.offering(scope):
                assert pool.submit(scope[2], "request", lambda: None) is None
        # Only run-a has a prepared context. Its current capacity scan selects
        # no candidate; run-b has not had an opportunity to refresh its waiter.
        with pool.visiting({("dispatch", "run-a")}):
            pass
        assert pool.scopes(("dispatch",)) == {waiting_context}
        release.set()
        for future in running:
            future.result(timeout=10)
        with pool.visiting({("dispatch", "run-b")}):
            with pool.offering(waiting_context):
                future = pool.submit("stage-b", "request", lambda: "prepared")
        assert future is not None and future.result(timeout=10) == "prepared"
        assert pool.scopes(("dispatch",)) == set()
    finally:
        release.set()
        pool.close()


@pytest.mark.parametrize("work_seconds", [0.0, 4.0])
def test_bulk_timing_separates_original_capacity_wait_from_worker_execution(monkeypatch, work_seconds):
    from loom.queue import _bulk_operations as bulk_module, _phase_timing as timing

    clock = [0.0]
    records = []
    monkeypatch.setattr(bulk_module, "monotonic", lambda: clock[0])
    monkeypatch.setattr(timing, "monotonic", lambda: clock[0])
    monkeypatch.setattr(timing, "log_phases", records.append)
    monkeypatch.setattr(timing, "_operation_samples", iter([1] * 10))
    pool = bulk_module.BulkOperations(lambda: None)
    entered = Barrier(3)
    release = Event()
    parent = []

    def occupy():
        entered.wait(timeout=10)
        assert release.wait(timeout=10)

    def work():
        clock[0] = 3.0 + work_seconds
        return "verified"

    try:
        running = [pool.submit(str(index), "occupied", occupy) for index in range(2)]
        entered.wait(timeout=10)
        with pool.offering(("run", "measured")):
            assert pool.submit("measured", "audit", work) is None
        clock[0] = 3.0
        release.set()
        for future in running:
            future.result(timeout=10)
        with observe_phases(parent.append), pool.offering(("run", "measured")):
            future = pool.submit("measured", "audit", work)
        assert future is not None and future.result(timeout=10) == "verified"
        report, = [record for record in records if record["operation_id"] == "measured"]
        spans = {span["action"]: span for span in report["spans"]}
        assert spans["bulk_capacity_wait"]["elapsed_nanoseconds"] == 3_000_000_000
        assert spans["audit"]["elapsed_nanoseconds"] == round(work_seconds * 1_000_000_000)
        assert parent == []
    finally:
        release.set()
        pool.close()
