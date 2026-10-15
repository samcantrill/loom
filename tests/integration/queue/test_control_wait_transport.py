"""Authenticated control waits reserve independent capacity for short requests."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import BoundedSemaphore

import pytest

from loom.queue import LocalDaemonPrincipal, LocalDaemonRole
from loom.queue.agent_session_transport import AgentTlsClientConfig, LocalDaemonAgentHttpClient
from loom.queue.errors import QueueServiceError
from tests.integration.queue.test_agent_session_transport import _request
from tests.integration.queue.test_agent_session_transport import native_control_endpoint as native_control_endpoint
from tests.unit.loom.queue.test_agent_sessions import _offer, _TEST_RETIREMENT_VERIFIER
from tests.unit.loom.queue.test_agent_waiting import _observe_sleep


def test_control_wait_saturation_preserves_work_waits_and_short_requests(
    native_control_endpoint, monkeypatch,
):
    daemon, server, _, credentials = native_control_endpoint
    view = daemon.agent_view(LocalDaemonPrincipal(
        "agent-principal", LocalDaemonRole.AGENT, "agent-credential",
    ))
    session = view.register(replace(
        _request(view.handshake(), "wait-root"), retirement_verifier=_TEST_RETIREMENT_VERIFIER,
    ))
    view.publish_offer(_offer(session.session_id, session.coordinator_epoch), idempotency_key="offer")
    assert server._server is not None
    monkeypatch.setattr(server._server, "agent_control_wait_slots", BoundedSemaphore(1))
    asleep = _observe_sleep(monkeypatch)
    config = AgentTlsClientConfig(
        f"https://localhost:{server.port}", credentials["ca"].with_suffix(".crt"),
        credentials["agent"].with_suffix(".crt"), credentials["agent"].with_suffix(".key"),
    )
    waiting = LocalDaemonAgentHttpClient(config)
    other = LocalDaemonAgentHttpClient(config)
    request = {"session_id": session.session_id, "received_operation_ids": [], "wait_timeout_ms": 5000}
    try:
        with ThreadPoolExecutor() as workers:
            pending = workers.submit(waiting._call, "control_wait", request)
            assert asleep.wait(2)
            try:
                with pytest.raises(QueueServiceError):
                    other._call("control_wait", {**request, "wait_timeout_ms": 0})
                assert other.handshake()["role"] == "agent"
                result = other._call("poll", {
                    "session_id": session.session_id,
                    "availability_revision": session.availability_revision,
                    "sequence": 1, "wait_timeout_ms": 1,
                })
                assert result["result"] == "wait"
            finally:
                daemon.stop()
            with pytest.raises(QueueServiceError):
                pending.result(timeout=2)
    finally:
        waiting.close()
        other.close()
    assert server._server.agent_control_wait_slots.acquire(blocking=False)
