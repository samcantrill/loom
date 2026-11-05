"""Slow retained-input IO must not own the coordinator control path."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from loom.queue import (
    LocalDaemon, LocalDaemonAdmissionRequest, LocalDaemonAdmissionState,
    LocalDaemonConfig, LocalDaemonPrincipal, LocalDaemonRole,
)
from loom.queue.agent_sessions import AgentOfferRenewal
from loom.queue import local_daemon_execution
from tests.integration.queue.test_local_daemon_production import _persist_sleep_run
from tests.unit.loom.queue.test_agent_sessions import _offer, _policy, _register, _view


@pytest.mark.parametrize("operation", ["renew", "poll", "cancel"])
def test_blocked_context_loading_keeps_control_responsive(tmp_path, monkeypatch, operation):
    # Keep the production coordinator and stores, but drive its cycles explicitly.
    monkeypatch.setattr(LocalDaemon, "_serve", lambda self: self._stop.wait())
    root = tmp_path / "runs"
    run_uri = _persist_sleep_run(root, run_name="slow", stage_name="stage")
    config = LocalDaemonConfig(tmp_path / "coordinator", None, root, None,
                               cpu_capacity=0, agent_policy=_policy())
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    entered, release = Event(), Event()
    executor = ThreadPoolExecutor(max_workers=2)
    reconciliation = None
    try:
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        client.submit(LocalDaemonAdmissionRequest("slow", run_uri))
        session = _register(daemon)
        offer = _view(daemon).publish_offer(
            _offer(session.session_id, session.coordinator_epoch), idempotency_key="offer"
        )
        original = local_daemon_execution.load_managed_local_intent

        def blocked_load(*args, **kwargs):
            entered.set()
            assert release.wait(10), "test did not release retained-input IO"
            return original(*args, **kwargs)

        monkeypatch.setattr(local_daemon_execution, "load_managed_local_intent", blocked_load)
        reconciliation = executor.submit(daemon.reconcile_once)
        assert entered.wait(2)
        if operation == "renew":
            renewal = AgentOfferRenewal(session.session_id, str(offer["offer_id"]), "availability-1", 1)
            result = executor.submit(_view(daemon).renew_offer, renewal).result(2)
            assert result["offer_id"] == offer["offer_id"]
        elif operation == "poll":
            result = executor.submit(_view(daemon).wait_for_work, session.session_id,
                                     "availability-1", sequence=1, wait_timeout_ms=1).result(2)
            assert result["result"] == "wait"
        else:
            result = executor.submit(client.cancel, "slow").result(2)
            assert result.state is LocalDaemonAdmissionState.CANCELLATION_REQUESTED
            assert result.cancellation_operation_id
        assert not release.is_set()
    finally:
        release.set()
        if reconciliation is not None:
            reconciliation.result(10)
        executor.shutdown()
        daemon.stop()


def test_state_lock_diagnostics_report_after_release_and_cannot_change_outcome():
    from threading import Lock
    from loom.queue._phase_timing import observe_phases, phase, state_lock

    lock = Lock()
    payloads = []

    def report(payload):
        assert lock.acquire(blocking=False), "diagnostics ran inside critical section"
        lock.release()
        payloads.append(payload)
        raise OSError("diagnostic sink unavailable")

    with observe_phases(report), state_lock(lock):
        with phase("short_transition"):
            assert payloads == []
    assert len(payloads) == 1
    assert {span["action"] for span in payloads[0]["spans"]} == {
        "coordinator_state_lock_wait", "coordinator_state_lock_hold", "short_transition"
    }


def _drive_until(daemon, predicate):
    from time import monotonic

    deadline = monotonic() + 5
    while not predicate():
        observed = daemon._wake.snapshot()
        daemon.reconcile_once()
        if predicate():
            return
        remaining = deadline - monotonic()
        assert remaining > 0, "reconciliation made no progress"
        daemon._wake.wait_for_change(observed, remaining)


@pytest.mark.parametrize("saturated", [False, True])
def test_blocked_admissions_preserve_bounded_capacity_and_peer_progress(tmp_path, monkeypatch, saturated):
    monkeypatch.setattr(LocalDaemon, "_serve", lambda self: self._stop.wait())
    root = tmp_path / "runs"
    uris = [_persist_sleep_run(root, run_name=f"run-{i}", stage_name="stage") for i in range(3)]
    config = LocalDaemonConfig(tmp_path / "coordinator", None, root, None, cpu_capacity=0)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    releases = [Event(), Event()]
    entered = [Event(), Event(), Event()]
    try:
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        admissions = [client.submit(LocalDaemonAdmissionRequest(str(i), uri)) for i, uri in enumerate(uris)]
        original = local_daemon_execution.load_managed_local_intent

        def blocked_load(config, uri, **kwargs):
            index = uris.index(uri)
            entered[index].set()
            if index == 0 or (saturated and index == 1):
                assert releases[index].wait(10)
            return original(config, uri, **kwargs)

        monkeypatch.setattr(local_daemon_execution, "load_managed_local_intent", blocked_load)
        daemon.reconcile_once()
        assert entered[0].wait(2) and entered[1].wait(2)
        execution = daemon._execution
        assert execution is not None
        if saturated:
            client.cancel("0")
            # Repeated callers and cancellation cannot create an executor backlog
            # or reclaim a slot still occupied by the underlying storage call.
            for _ in range(10):
                daemon.reconcile_once()
            assert not entered[2].is_set()
            assert len(daemon._contexts._pending) == 2
            assert daemon.status().coordinator_id
            releases[1].set()
        _drive_until(daemon, lambda: bool(execution.stage_work_store.list_stage_work(
            admission_id=admissions[2].admission_id)))
        assert not releases[0].is_set()
        assert len(daemon._contexts._pending) <= 2
        assert execution.stage_work_store.list_stage_work(admission_id=admissions[0].admission_id) == ()
    finally:
        for release in releases:
            release.set()
        daemon.stop()


@pytest.mark.parametrize("change", ["cancel", "scheduling"])
def test_preparation_is_discarded_when_its_authorization_changes(tmp_path, monkeypatch, change):
    from loom.queue import CoordinatorSchedulingReload

    monkeypatch.setattr(LocalDaemon, "_serve", lambda self: self._stop.wait())
    root = tmp_path / "runs"
    uri = _persist_sleep_run(root, run_name="stale", stage_name="stage")
    config = LocalDaemonConfig(tmp_path / "coordinator", None, root, None,
                               cpu_capacity=0, agent_policy=_policy())
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config, trusted_scheduling_loader=lambda: config)
    status = daemon.start()
    entered, release = Event(), Event()
    try:
        client = daemon.client_view(LocalDaemonPrincipal("client", LocalDaemonRole.CLIENT))
        admission = client.submit(LocalDaemonAdmissionRequest("stale", uri))
        original = local_daemon_execution.load_managed_local_intent

        def blocked_load(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return original(*args, **kwargs)

        monkeypatch.setattr(local_daemon_execution, "load_managed_local_intent", blocked_load)
        daemon.reconcile_once()
        assert entered.wait(2)
        pending = daemon._contexts._pending[admission.admission_id].future
        if change == "cancel":
            client.cancel("stale")
        else:
            receipt = daemon.operator_view(LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)).reload_scheduling(
                CoordinatorSchedulingReload("reload", status.scheduling_epoch, "test stale preparation"))
            assert receipt["state"] == "applied"
        release.set()
        pending.result(2)
        daemon.reconcile_once()
        execution = daemon._execution
        assert execution is not None
        assert not execution.stage_work_store.list_stage_work()
        assert not execution.coordinator.list_run_live_states(uri)
    finally:
        release.set()
        daemon.stop()
