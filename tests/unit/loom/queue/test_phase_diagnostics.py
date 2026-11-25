"""Active delivery work and intentional long-poll sleeps have different costs."""

from itertools import count
import json
from threading import Event
from unittest.mock import Mock

import pytest

from loom.queue import _phase_timing as timing
from loom.queue._phase_diagnostics import DiagnosticWriter
from loom.queue._service_signals import _ChangeSignal


def test_long_polls_sample_idle_and_report_slow_delivery_after_idle(monkeypatch):
    now = 0.0
    records = []
    signal = _ChangeSignal()

    def wait_for_change(predicate, timeout):
        nonlocal now
        now += timeout

    monkeypatch.delenv("LOOM_QUALIFICATION_TIMINGS", raising=False)
    monkeypatch.setattr(signal._condition, "wait_for", wait_for_change)
    monkeypatch.setattr(timing, "monotonic", lambda: now)
    monkeypatch.setattr(timing, "_operation_samples", count())
    monkeypatch.setattr(timing, "log_phases", records.append)
    for _ in range(128):
        with timing.request_phases():
            signal.wait_for_change(0, 5)
    assert len(records) == 2
    assert all(item["idle_nanoseconds"] == 5_000_000_000 for item in records)
    assert all(item["active_nanoseconds"] == 0 for item in records)

    with timing.request_phases():
        signal.wait_for_change(0, 5)
        now += 2
    assert records[-1]["idle_nanoseconds"] == 5_000_000_000
    assert records[-1]["active_nanoseconds"] == 2_000_000_000
    with timing.request_phases() as request:
        request.failed = True
    assert records[-1]["outcome"] == "error"


def test_sender_uses_only_reported_idle_and_retains_slow_reply_processing(monkeypatch):
    now = 0.0
    records = []
    monkeypatch.setattr(timing, "monotonic", lambda: now)
    monkeypatch.setattr(timing, "log_phases", records.append)
    monkeypatch.setattr(timing, "_operation_samples", count(1))
    monkeypatch.delenv("LOOM_QUALIFICATION_TIMINGS", raising=False)
    for header, processing in (("5000000000", 0), ("5000000000", 2), (None, 0)):
        with timing.reported_phases("agent_exchange"):
            now += 5
            timing.received_idle_duration(header, 5.0)
            now += processing
    assert [(r["active_nanoseconds"], r["idle_nanoseconds"]) for r in records] == [
        (2_000_000_000, 5_000_000_000), (5_000_000_000, 0),
    ]


def test_saturation_and_failed_writes_report_cumulative_qualification_loss():
    started = Event()
    release = Event()
    lines = []

    def emit(stream, value):
        if not started.is_set():
            started.set()
            assert release.wait(5)
            raise OSError("diagnostic destination unavailable")
        lines.append(json.dumps(value))

    writer = DiagnosticWriter(capacity=1, emit=emit)
    try:
        writer.submit({"sequence": 1}, qualification=True)
        assert started.wait(2)
        writer.submit({"sequence": 2}, qualification=True)
        writer.submit({"sequence": 3}, qualification=True)
        writer.submit({"sequence": 4}, qualification=False)
        assert not writer.flush(timeout=0)
        assert writer.counts() == {"omitted_records": 2, "omitted_qualification_records": 1}
    finally:
        release.set()
    assert writer.flush()
    assert [json.loads(line) for line in lines] == [
        {"sequence": 2, "omitted_records": 3, "omitted_qualification_records": 2}
    ]


def test_pending_lifecycle_retries_are_sampled_and_fast_failures_reported(monkeypatch):
    from loom.queue._agent_lifecycle import LifecyclePending
    from loom.queue import agent_session_transport as transport

    records = []
    monkeypatch.setattr(timing, "log_phases", records.append)
    monkeypatch.setattr(timing, "_operation_samples", count(1))
    monkeypatch.delenv("LOOM_QUALIFICATION_TIMINGS", raising=False)
    for error, qualify in ((LifecyclePending(), False), (LifecyclePending(), True), (OSError(), False)):
        def exchange(*args, **kwargs):
            raise error

        monkeypatch.setattr(transport, "_exchange_agent_request", exchange)
        monkeypatch.setenv("LOOM_QUALIFICATION_TIMINGS", "all" if qualify else "")
        with pytest.raises(type(error)):
            transport._timed_agent_exchange(transport.monotonic(), "", "id", Mock(), "accept")
    assert [record["outcome"] for record in records] == ["pending", "error"]
    assert [record["spans"][-1]["outcome"] for record in records] == ["pending", "error"]
