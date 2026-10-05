"""Passive status waiting and race-safe coordinator wake-ups."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import sqlite3
from threading import Event, Thread

import pytest

from loom.queue import LocalDaemon, LocalDaemonAdmissionState, QueueServiceError
from loom.queue._service_signals import _ChangeConnection
from tests.unit.loom.queue.test_local_daemon import _config


@pytest.fixture
def daemon(tmp_path):
    config = replace(
        _config(tmp_path), agent_root=None, resident_worker_launch_profile=None,
        cpu_capacity=0, agent_resource_providers=(),
    )
    LocalDaemon.initialize(config)
    owner = LocalDaemon(config)
    with owner._connection() as conn:
        conn.execute(
            "INSERT INTO managed_admissions(admission_id, queue_item_id, "
            "coordinator_id, run_uri, intent_digest, execution_owner, state, "
            "accepted_at, authority_operation_id, run_priority, enqueue_sequence, "
            "cancellation_operation_id, blocked_reason) VALUES "
            "('admission', 'item', 'coordinator', 'file:///run', 'digest', "
            "'managed-stage', 'ACTIVE', '2026-01-01T00:00:00Z', 'bind', 0, 1, NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO agent_controls(operation_id, principal_id, session_id, "
            "agent_id, request_json, state, result_code, acknowledged) VALUES "
            "('control', 'operator', 'session', 'agent', '{}', 'pending_delivery', NULL, 0)"
        )
        conn.commit()
    yield owner
    owner.stop()


def wait(owner, kind, seconds):
    if kind == "admission":
        return owner.wait_admission("admission", expected_revision=1, timeout=seconds)
    if kind == "operation":
        return owner.wait_operation("control", timeout=seconds)
    return owner._wait("item", timeout_seconds=seconds)


def finish(owner, kind):
    if kind == "operation":
        with owner._connection() as conn:
            conn.execute("UPDATE agent_controls SET state = 'applied' WHERE operation_id = 'control'")
            conn.commit()
    else:
        owner._set_state("admission", LocalDaemonAdmissionState.SUCCEEDED, reason=None)


@pytest.mark.parametrize("kind", ["admission", "operation", "legacy"])
def test_idle_wait_queries_do_not_scale_with_duration(daemon, monkeypatch, kind):
    connection = daemon._connection
    counts = []

    @contextmanager
    def observed():
        counts.append(1)
        with connection() as conn:
            yield conn

    monkeypatch.setattr(daemon, "_connection", observed)
    totals = []
    for duration in (0.12, 0.3):
        counts.clear()
        if kind == "legacy":
            with pytest.raises(TimeoutError):
                wait(daemon, kind, duration)
        else:
            assert wait(daemon, kind, duration).kind.value == "TIMEOUT"
        totals.append(len(counts))
    assert totals == [2, 2]


@pytest.mark.parametrize("kind", ["admission", "operation", "legacy"])
@pytest.mark.parametrize("before_sleep", [False, True])
def test_commit_wakes_status_before_or_during_sleep(
    daemon, monkeypatch, kind, before_sleep
):
    ready, proceed = Event(), Event()
    signal = daemon._status_changed
    original = signal.wait_for_change

    def intercepted(observed, timeout):
        if before_sleep:
            ready.set()
            assert proceed.wait(3)
        original(observed, timeout)

    condition_wait = signal._condition.wait

    def mark_sleeping(timeout=None):
        ready.set()
        return condition_wait(timeout)

    monkeypatch.setattr(signal, "wait_for_change", intercepted)
    if not before_sleep:
        monkeypatch.setattr(signal._condition, "wait", mark_sleeping)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(wait, daemon, kind, 10)
        assert ready.wait(2)
        try:
            finish(daemon, kind)
        finally:
            proceed.set()
        result = pending.result(timeout=0.8)
    if kind == "legacy":
        assert result.state is LocalDaemonAdmissionState.SUCCEEDED
    else:
        assert result.kind.value == "TERMINAL"


@pytest.mark.parametrize("kind", ["admission", "operation", "legacy"])
def test_final_state_check_recovers_suppressed_notification(daemon, monkeypatch, kind):
    original = daemon._wait_for_status_change

    def commit_without_hint(observed, deadline):
        with monkeypatch.context() as patch:
            patch.setattr(daemon._status_changed, "set", lambda: None)
            finish(daemon, kind)
        original(observed, deadline)

    monkeypatch.setattr(daemon, "_wait_for_status_change", commit_without_hint)
    result = wait(daemon, kind, 0.05)
    if kind == "legacy":
        assert result.state is LocalDaemonAdmissionState.SUCCEEDED
    else:
        assert result.kind.value == "TERMINAL"


@pytest.mark.parametrize("kind", ["admission", "operation", "legacy"])
def test_shutdown_wakes_unbounded_status_wait(daemon, monkeypatch, kind):
    ready = Event()
    original = daemon._status_changed._condition.wait

    def observed(timeout=None):
        ready.set()
        return original(timeout)

    monkeypatch.setattr(daemon._status_changed._condition, "wait", observed)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(wait, daemon, kind, None)
        assert ready.wait(2)
        daemon.stop()
        with pytest.raises(QueueServiceError, match="stopping"):
            pending.result(timeout=0.8)


def test_coordinator_preserves_notification_during_reconciliation(daemon, monkeypatch):
    calls = []
    daemon.config = replace(daemon.config, poll_interval_seconds=60)

    def reconcile():
        calls.append(1)
        if len(calls) == 1:
            daemon._wake.set()
        else:
            daemon._stop.set()
        return ()

    monkeypatch.setattr(daemon, "reconcile_once", reconcile)
    thread = Thread(target=daemon._serve)
    thread.start()
    try:
        thread.join(1)
        assert not thread.is_alive()
        assert len(calls) == 2
    finally:
        daemon._stop.set()
        daemon._wake.set()
        thread.join(2)


def test_commit_hint_requires_committed_changes():
    hints = []
    with sqlite3.connect(":memory:", factory=_ChangeConnection) as conn:
        conn.on_commit = lambda: hints.append(1)
        conn.execute("CREATE TABLE changes(value)")
        conn.commit()
        conn.execute("INSERT INTO changes VALUES (1)")
        assert hints == []
        conn.rollback()
        conn.commit()
        assert hints == []
        conn.execute("INSERT INTO changes VALUES (2)")
        conn.commit()
        assert hints == [1]
        conn.commit()
        assert hints == [1]
