"""Blocked IO cannot consume unbounded slots or authorize superseded work."""

from threading import Event

import pytest

from loom.queue import _input_validation as owner

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("error,expected", [
    (None, "input_validation_complete"),
    (OSError("storage unavailable"), "input_validation_storage_unavailable"),
    (owner.QueueServiceError("invalid entry"), "input_validation_invalid"),
    (owner.CancelledError(), "input_validation_cancelled"),
])
def test_observation_reports_completion_without_another_dispatch_poll(monkeypatch, error, expected):
    started, release, woke = Event(), Event(), Event()

    def inspect(*args, **kwargs):
        started.set()
        assert release.wait(10)
        if error is not None:
            raise error

    monkeypatch.setattr(owner, "require_bindings", inspect)
    pool = owner.InputValidationPool(woke.set)
    identity = {"worker_request": {"run_uri": "file:///run", "stage_name": "prepare"}}
    try:
        pool.poll("stage", identity, {}, {})
        assert started.wait(10)
        assert pool.observations("file:///run")["inspections"][0]["reason"] == "input_validation_pending"
        release.set()
        assert woke.wait(10)
        # An unavailable execution route may prevent further dispatch polls.
        # Ordinary status must still distinguish completed IO from active IO.
        assert pool.observations("file:///run")["inspections"][0]["reason"] == expected
    finally:
        release.set()
        pool.close()


def test_bounded_validation_supersession_and_shutdown(monkeypatch):
    started, release, woke = Event(), Event(), Event()
    captured = []

    def inspect(scope, roots, *, cancelled, progress):
        captured.append((scope, roots))
        started.set()
        assert release.wait(10)
        if cancelled():
            raise owner.CancelledError()

    monkeypatch.setattr(owner, "require_bindings", inspect)
    pool = owner.InputValidationPool(woke.set, workers=1, max_pending=1)
    roots = {"data": {"host_path": "/original"}}
    try:
        assert pool.poll("first", {"attempt": "1"}, {}, roots).reason == "input_validation_pending"
        assert started.wait(10)
        roots["data"]["host_path"] = "/replacement"
        # An obsolete worker keeps its capacity until it exits, even though
        # cancellation prevents its result from authorizing commitment.
        assert pool.poll("first", {"attempt": "1"}, {}, roots).reason == "input_validation_capacity"
        assert captured[0][1]["data"]["host_path"] == "/original"
        assert pool.poll("second", {}, {}, {}).reason == "input_validation_capacity"
        pool.close()  # Must return while the worker is still blocked.
        assert not release.is_set()
        release.set()
        assert woke.wait(10)
        assert pool.poll("first", {}, {}, {}).reason == "input_validation_cancelled"
    finally:
        release.set()
        pool.close()


def test_success_is_current_request_only_and_restart_reinspects(monkeypatch):
    calls = []
    woke = Event()

    def inspect(scope, roots, **kwargs):
        calls.append((scope, roots))

    monkeypatch.setattr(owner, "require_bindings", inspect)
    for _restart in range(2):
        pool = owner.InputValidationPool(woke.set)
        try:
            woke.clear()
            pool.poll("stage", {"attempt": "one"}, {}, {})
            assert woke.wait(10)
            assert pool.poll("stage", {"attempt": "one"}, {}, {}).reason is None
            pool.retain(lambda _: False)
            woke.clear()
            pool.poll("stage", {"attempt": "two"}, {}, {})
            assert woke.wait(10)
            assert pool.poll("stage", {"attempt": "two"}, {}, {}).reason is None
        finally:
            pool.close()
    assert len(calls) == 4


def test_completed_result_does_not_starve_new_work_and_repaired_inputs_retry(monkeypatch):
    woke = Event()
    clock = [100.0]
    calls = []
    broken = [True]

    def inspect(scope, roots, **kwargs):
        calls.append(scope)
        if broken[0]:
            raise owner.QueueServiceError("shared input requires a regular file")

    monkeypatch.setattr(owner, "require_bindings", inspect)
    monkeypatch.setattr(owner, "monotonic", lambda: clock[0])
    pool = owner.InputValidationPool(woke.set, workers=1, max_pending=1)
    try:
        pool.poll("stage", {}, {}, {})
        assert woke.wait(10)
        assert pool.poll("stage", {}, {}, {}).reason == "input_validation_invalid"
        assert pool.poll("stage", {}, {}, {}).reason == "input_validation_invalid"
        assert len(calls) == 1
        clock[0] = 106.0
        broken[0] = False
        woke.clear()
        pool.poll("stage", {}, {}, {})
        assert woke.wait(10)
        assert pool.poll("stage", {}, {}, {}).reason is None
        woke.clear()
        # Completion can wait on other admission policy. It must not hold an
        # inspection slot forever or force unbounded completed-result storage.
        pool.poll("unrelated", {}, {}, {})
        assert woke.wait(10)
        assert pool.poll("unrelated", {}, {}, {}).reason is None
        assert len(calls) == 3
    finally:
        pool.close()
