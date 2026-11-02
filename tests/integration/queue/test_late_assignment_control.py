"""Cancellation delivery can outlive the assignment's execution view."""

from threading import Event, Thread

import pytest

from loom.queue import LocalDaemonAdmissionState
import loom.queue.agent_session_transport as transport

from .test_concurrent_outbound_agent import (
    _eventually,
    _release_gate,
    _rows,
    _service,
    _submit,
    _submit_gated,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("recovery", ["live", "restart", "lost_ack_reply"])
def test_control_received_after_release_is_acknowledged_and_peer_work_progresses(
    monkeypatch, recovery
):
    entered, deliver = Event(), Event()
    stopped, lost_reply = Event(), Event()
    dispatch = transport._dispatch
    prepare = transport._RemoteAgentJournal.prepare_assignment_control
    exchange = transport._exchange_agent_request

    def delayed_control(view, operation, value):
        result = dispatch(view, operation, value)
        if operation == "control_wait" and result.get("assignment_control") is not None:
            entered.set()
            assert deliver.wait(20)
        return result

    def retain(journal, control):
        result = prepare(journal, control)
        if recovery == "restart" and deliver.is_set() and not stopped.is_set():
            case.stop.set()
            stopped.set()
        return result

    def uncertain_ack(config, operation, *args):
        result = exchange(config, operation, *args)
        if recovery == "lost_ack_reply" and operation == "assignment_control_ack" and not lost_reply.is_set():
            lost_reply.set()
            raise transport._IndeterminateAgentProtocolError("acknowledgement reply lost")
        return result

    monkeypatch.setattr(transport, "_dispatch", delayed_control)
    monkeypatch.setattr(transport._RemoteAgentJournal, "prepare_assignment_control", retain)
    monkeypatch.setattr(transport, "_exchange_agent_request", uncertain_ack)
    with _service(monkeypatch, memory=2 * 1024**3) as case:
        gate, _, _ = _submit_gated(case, "cancelled")
        try:
            _eventually(lambda: (gate / "build.started").exists())
            case.client.cancel("cancelled")
            assert entered.wait(10)
            _release_gate(gate)
            _eventually(lambda: _rows(
                case.agent_root / "journal.sqlite",
                "SELECT assignment_id FROM assignments WHERE state = 'released'",
            ))
            original_results = _rows(
                case.agent_root / "journal.sqlite", "SELECT result_json FROM assignments"
            )
            deliver.set()
            if recovery == "restart":
                assert stopped.wait(10)
                case.thread.join(20)
                assert not case.thread.is_alive()
                case.stop.clear()
                case.thread = Thread(target=case.serve)
                case.thread.start()
            _eventually(lambda: _rows(
                case.agent_root / "control.sqlite",
                "SELECT operation_id FROM remote_assignment_controls_local WHERE acknowledged = 1",
            ), seconds=5)
            assert _rows(
                case.agent_root / "control.sqlite",
                "SELECT result_code FROM remote_assignment_controls_local",
            ) == [("terminal",)]
            assert _rows(
                case.database,
                "SELECT state, result_code, acknowledged FROM remote_assignment_controls",
            ) == [("applied", "terminal", 1)]
            assert _rows(
                case.agent_root / "journal.sqlite", "SELECT result_json FROM assignments"
            ) == original_results
            assert _rows(
                case.agent_root / "supervisor/supervisor.sqlite", "SELECT COUNT(*) FROM launches"
            ) == [(1,)]
            assert lost_reply.is_set() == (recovery == "lost_ack_reply")
            _submit(case, "peer")
            assert case.client.wait("peer", timeout_seconds=30).state is LocalDaemonAdmissionState.SUCCEEDED
            assert not case.failures
        finally:
            deliver.set()
            _release_gate(gate)
