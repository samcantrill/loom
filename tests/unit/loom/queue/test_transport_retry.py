"""Exact transport replay pacing does not consume maintenance capacity."""

from pathlib import Path

import pytest

from loom.queue._agent_progress import _Delay, _External, _steps
from loom.queue._managed_local import _ManagedApplicationSuspended
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    LocalDaemonAgentHttpClient,
    _IndeterminateAgentProtocolError,
)
from loom.queue.errors import QueueConflictError


@pytest.fixture
def client():
    # Transport steps are driven at the exchange boundary; no TLS files are read.
    client = LocalDaemonAgentHttpClient(AgentTlsClientConfig(
        "https://localhost:9443", Path("ca.pem"), Path("agent.pem"), Path("agent.key"),
    ))
    client._service_progress = True
    try:
        yield client
    finally:
        client.close()


@pytest.mark.parametrize("operation", ["poll", "started", "result", "release", "input"])
def test_indeterminate_retries_keep_exact_bytes_and_bound_work(client, monkeypatch, caplog, operation):
    clock = [100.0]
    monkeypatch.setattr("loom.queue._agent_progress.monotonic", lambda: clock[0])
    monkeypatch.setattr("loom.queue._recovery_retry.monotonic", lambda: clock[0])
    monkeypatch.setattr("loom.queue._recovery_retry.uniform", lambda low, high: high)
    request = {"assignment_id": "assignment-A", "operation_id": "operation-A"}
    progress = _steps(client._call, operation, request)
    step = next(progress)
    assert isinstance(step, _External)
    original_args = step.args
    try:
        for attempt in range(10):
            # A lost reply must never regenerate or reread this request.
            request["operation_id"] = "not-the-retained-operation"
            failure = _IndeterminateAgentProtocolError("private request contents")
            delay = progress.throw(failure)
            assert isinstance(delay, _Delay)
            assert delay.due - clock[0] == pytest.approx(min(5.0, 0.1 * 2**attempt))
            clock[0] = delay.due
            step = next(progress)
            assert isinstance(step, _External)
            assert step.args == original_args
        assert "private request contents" not in caplog.text
        assert "not-the-retained-operation" not in caplog.text
        assert "agent transport recovery pending" in caplog.text
        conflict = QueueConflictError("terminal conflict")
        with pytest.raises(QueueConflictError) as caught:
            progress.throw(conflict)
        assert caught.value is conflict
    finally:
        progress.close()


@pytest.mark.parametrize("operation", [
    "renew", "offer", "control", "assignment_control", "control_wait",
    "control_ack", "assignment_control_ack",
])
def test_maintenance_and_controls_keep_their_existing_retry_cadence(client, monkeypatch, operation):
    monkeypatch.setattr("loom.queue._agent_progress.monotonic", lambda: 100.0)
    progress = _steps(client._call, operation, {"session_id": "session-A"})
    try:
        assert isinstance(next(progress), _External)
        for _ in range(4):
            delay = progress.throw(_IndeterminateAgentProtocolError("lost reply"))
            assert isinstance(delay, _Delay)
            assert delay.due == 100.05
            assert isinstance(next(progress), _External)
    finally:
        progress.close()


def test_suspension_during_retry_does_not_dispatch_another_request(client):
    suspended = [False]
    client._suspend_requested = lambda: suspended[0]
    progress = _steps(client._call, "result", {"assignment_id": "A"})
    assert isinstance(next(progress), _External)
    assert isinstance(progress.throw(_IndeterminateAgentProtocolError("lost reply")), _Delay)
    suspended[0] = True
    with pytest.raises(_ManagedApplicationSuspended):
        next(progress)


def test_synchronous_caller_keeps_unknown_outcome_without_automatic_retry(client):
    client._service_progress = False
    progress = _steps(client._call, "result", {"assignment_id": "A"})
    assert isinstance(next(progress), _External)
    failure = _IndeterminateAgentProtocolError("lost reply")
    with pytest.raises(_IndeterminateAgentProtocolError) as caught:
        progress.throw(failure)
    assert caught.value is failure
