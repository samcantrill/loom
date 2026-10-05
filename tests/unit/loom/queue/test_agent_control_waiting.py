"""Control waits retain exact delivery without periodic empty write transactions."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import json

import pytest

from loom.queue import LocalDaemonPrincipal, LocalDaemonRole
from loom.queue.agent_sessions import AgentControl, AgentControlKind
from loom.queue.agent_session_transport import _RemoteAgentJournal, _decode
from loom.queue.errors import QueueConflictError, QueueServiceError
from tests.unit.loom.queue.test_agent_sessions import (
    _delivery_journal, _prepare_delivery_poll, _view,
)
from tests.unit.loom.queue.test_agent_waiting import (
    _observe_sleep, _pause_before_wait,
)
from tests.unit.loom.queue.test_agent_waiting import waiting_owner as waiting_owner


def control_for(session):
    return AgentControl(
        "control-wait", AgentControlKind.DRAIN, session.agent_id,
        session.session_id, session.config_revision, None, False, "maintenance",
    )


def submit(daemon, session):
    control = control_for(session)
    daemon.operator_view(
        LocalDaemonPrincipal("operator", LocalDaemonRole.OPERATOR)
    ).control_agent(control)
    return control


def wait(daemon, session, *, ids=(), milliseconds=5000):
    return _view(daemon).wait_for_controls(
        session.session_id, received_operation_ids=[f"agent:{item}" for item in ids],
        wait_timeout_ms=milliseconds,
    )


def test_empty_control_wait_has_constant_reads_and_no_write_transaction(waiting_owner, monkeypatch):
    daemon, session, *_ = waiting_owner
    original = daemon._connection
    counts = Counter()

    @contextmanager
    def traced():
        with original() as conn:
            counts["connections"] += 1
            conn.set_trace_callback(lambda sql: counts.update([sql.split()[0].upper()]))
            yield conn

    monkeypatch.setattr(daemon, "_connection", traced)
    observations = []
    for duration in (150, 300):
        counts.clear()
        assert wait(daemon, session, milliseconds=duration) == {
            "control": None, "assignment_control": None,
        }
        observations.append(counts.copy())
    assert observations[0] == observations[1]
    assert observations[0]["connections"] == 4
    assert observations[0]["BEGIN"] == 0
    assert observations[0]["UPDATE"] == 0


@pytest.mark.parametrize("sleeping", [False, True])
def test_committed_control_wakes_before_or_during_wait(waiting_owner, monkeypatch, sleeping):
    daemon, session, *_ = waiting_owner
    if sleeping:
        ready, proceed = _observe_sleep(monkeypatch), None
    else:
        ready, proceed = _pause_before_wait(monkeypatch)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(wait, daemon, session)
        assert ready.wait(2)
        try:
            control = submit(daemon, session)
        finally:
            if proceed is not None:
                proceed.set()
        assert pending.result(timeout=1)["control"] == control.value()
    assert daemon._poll_waiters._subscribers == {}


def test_lost_reply_redelivers_and_receipt_suppression_never_acknowledges(waiting_owner):
    daemon, session, *_ = waiting_owner
    control = submit(daemon, session)
    first = wait(daemon, session, milliseconds=0)
    assert first["control"] == control.value()
    assert wait(daemon, session, milliseconds=0) == first
    assert wait(daemon, session, ids=[control.operation_id], milliseconds=0)["control"] is None
    with daemon._connection() as conn:
        assert tuple(conn.execute(
            "SELECT state, acknowledged FROM agent_controls WHERE operation_id = ?",
            (control.operation_id,),
        ).fetchone()) == ("applying", 0)
    assert wait(daemon, session, ids=["another-control"], milliseconds=0) == first
    assert _view(daemon).wait_for_controls(
        session.session_id, received_operation_ids=[f"assignment:{control.operation_id}"],
        wait_timeout_ms=0,
    ) == first
    with pytest.raises(QueueServiceError, match="session was not found"):
        _view(daemon).wait_for_controls(
            "another-session", received_operation_ids=[f"agent:{control.operation_id}"], wait_timeout_ms=0,
        )


def test_missed_control_notification_is_recovered_at_final_read(waiting_owner, monkeypatch):
    daemon, session, *_ = waiting_owner
    ready, proceed = _pause_before_wait(monkeypatch)
    monkeypatch.setattr(daemon._poll_waiters, "notify", lambda _: None)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(wait, daemon, session, milliseconds=100)
        assert ready.wait(2)
        try:
            control = submit(daemon, session)
        finally:
            proceed.set()
        assert pending.result(timeout=1)["control"] == control.value()


def test_shutdown_interrupts_control_wait(waiting_owner, monkeypatch):
    daemon, session, *_ = waiting_owner
    ready = _observe_sleep(monkeypatch)
    with ThreadPoolExecutor() as workers:
        pending = workers.submit(wait, daemon, session)
        assert ready.wait(2)
        daemon.stop()
        with pytest.raises(QueueServiceError, match="stopping"):
            pending.result(timeout=1)
    assert daemon._poll_waiters._subscribers == {}


@pytest.mark.parametrize("ids,timeout", [
    (["same", "same"], 0), (["bad/id"], 0), ([], -1), ([], 5001), ([], True),
    ([str(i) for i in range(1026)], 0),
])
def test_control_wait_rejects_invalid_wire_fields(waiting_owner, ids, timeout):
    daemon, session, *_ = waiting_owner
    with pytest.raises(QueueServiceError):
        wait(daemon, session, ids=ids, milliseconds=timeout)
    assert daemon._poll_waiters._subscribers == {}


def test_receipt_envelope_preserves_large_assignment_ceiling():
    request = {"session_id": "session", "wait_timeout_ms": 0,
               "received_operation_ids": [f"agent:control-{i}" for i in range(1025)]}
    encoded = json.dumps(request).encode()
    assert _decode(encoded, control_wait=True) == request
    with pytest.raises(QueueServiceError):
        _decode(encoded)
    request["received_operation_ids"] = ["x" * 160 + str(i) for i in range(1025)]
    with pytest.raises(QueueServiceError, match="too large"):
        _decode(json.dumps(request).encode(), control_wait=True)


def test_retained_drain_survives_restart_without_fencing_unanswered_poll(tmp_path):
    root = tmp_path / "agent"
    journal, session = _delivery_journal(root)
    control = control_for(session)
    try:
        _prepare_delivery_poll(journal, session, 1)
        poll = journal.pending_poll()
        journal.retain_control(control)
        assert journal.pending_poll() == poll
        assert journal.next_unacknowledged_control() is None
        assert journal.received_control_ids(session.session_id) == [f"agent:{control.operation_id}"]
        assert journal.received_control_ids("another-session") == []
        with pytest.raises(QueueConflictError, match="conflicts"):
            journal.retain_control(replace(control, reason="different request"))
    finally:
        journal.close()
    journal = _RemoteAgentJournal(root)
    try:
        assert journal.pending_poll() == poll
        assert journal.next_received_control(session.session_id) == control
        assert journal.received_control_ids(session.session_id) == [f"agent:{control.operation_id}"]
        assert journal.next_unacknowledged_control() is None
    finally:
        journal.close()
