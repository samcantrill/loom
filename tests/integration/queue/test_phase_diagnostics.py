"""A stalled service diagnostic stream cannot prevent a real assignment."""

from threading import Event

import pytest

from loom.queue import LocalDaemonAdmissionState
from loom.queue import _phase_diagnostics, _phase_timing
from tests.integration.queue.test_concurrent_outbound_agent import _service, _submit

pytestmark = pytest.mark.integration


def test_blocked_diagnostic_output_allows_admission_and_remote_completion(monkeypatch):
    entered, release = Event(), Event()

    def blocked(stream, value):
        entered.set()
        assert release.wait(45)

    writer = _phase_diagnostics.DiagnosticWriter(capacity=2, emit=blocked)
    monkeypatch.setattr(_phase_timing, "diagnostics", writer)
    monkeypatch.setattr(_phase_diagnostics, "diagnostics", writer)
    monkeypatch.setenv("LOOM_QUALIFICATION_TIMINGS", "all")
    try:
        with _service(monkeypatch) as case:
            assert entered.wait(5)
            _submit(case, "blocked-log")
            assert case.client.wait("blocked-log", timeout_seconds=30).state is LocalDaemonAdmissionState.SUCCEEDED
            counts = case.operator.observe_status().value["phase_diagnostics"]
            assert counts["omitted_qualification_records"] > 0
            assert counts["omitted_records"] >= counts["omitted_qualification_records"]
            assert not release.is_set()
            release.set()
    finally:
        release.set()
        assert writer.flush()


def test_idle_work_poll_reports_peer_wait_separately_from_slow_response_delivery(monkeypatch):
    from itertools import repeat
    from time import sleep

    from loom.queue.agent_session_transport import _Handler

    # Ordinary, unsampled polls must still report the deliberate active delay
    # on both ends of the real mutual-TLS exchange.
    monkeypatch.delenv("LOOM_QUALIFICATION_TIMINGS", raising=False)
    monkeypatch.setattr(_phase_timing, "_operation_samples", repeat(1))
    server_report, sender_report = Event(), Event()
    original = _Handler._reply

    def slow_reply(handler, status, value):
        if (handler.path == "/v1/agent/poll" and handler._request_timings.idle_seconds > 0
                and not server_report.is_set()):
            sleep(1.1)
        return original(handler, status, value)

    def record(value):
        if value.get("idle_nanoseconds", 0) <= 0 or value["active_nanoseconds"] < 1_000_000_000:
            return
        if value.get("related", {}).get("operation") == "poll":
            sender_report.set()
        elif any(span["action"] == "poll" for span in value["spans"]):
            server_report.set()

    monkeypatch.setattr(_Handler, "_reply", slow_reply)
    monkeypatch.setattr(_phase_timing, "log_phases", record)
    with _service(monkeypatch):
        assert server_report.wait(10)
        assert sender_report.wait(10)
