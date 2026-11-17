"""Preparation owns prerequisites through dispatch without capacity eviction."""

from collections import Counter
from concurrent.futures import Future
from threading import Event

import pytest

from loom.queue._ready_preparation import ReadyPreparationPool

pytestmark = pytest.mark.unit


class ControlledExecutor:
    """Complete one tick's work before the scheduler's next observation."""

    def __init__(self, **kwargs):
        self.jobs = []

    def submit(self, function, *args, **kwargs):
        future = Future()
        self.jobs.append((future, function, args, kwargs))
        return future

    def complete(self):
        jobs, self.jobs = self.jobs, []
        for future, function, args, kwargs in jobs:
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(function(*args, **kwargs))
                except Exception as exc:
                    future.set_exception(exc)

    def shutdown(self, **kwargs):
        self.complete()


@pytest.mark.parametrize("stages", [5, 100])
def test_prerequisites_survive_capacity_until_dispatch(monkeypatch, stages):
    monkeypatch.setattr("loom.queue._ready_preparation.ThreadPoolExecutor", ControlledExecutor)
    pool = ReadyPreparationPool(lambda: None)
    prepared = Counter()
    dispatched = set()
    capacity_observed = False

    def prepare(index, phase):
        prepared[index, phase] += 1
        return (index, phase)

    try:
        for _ in range(30):
            pool._workers.complete()
            for index in range(stages):
                if index in dispatched:
                    continue
                key = ("run", str(index))
                for phase in ("request", "input-descriptors", "recovery-predecessors"):
                    result, reason = pool.poll(
                        key, "identity-" + phase,
                        lambda index=index, phase=phase: prepare(index, phase), phase=phase,
                    )
                    capacity_observed |= reason == "stage_preparation_capacity"
                    if reason is not None:
                        break
                    assert result == (index, phase)
                else:
                    dispatched.add(index)
                    pool.discard(key)
            assert len(pool._pending) <= 32
            if len(dispatched) == stages:
                break
        assert dispatched == set(range(stages))
        assert len(prepared) == stages * 3
        assert set(prepared.values()) == {1}
        assert capacity_observed == (stages > 32)
        assert not pool._pending
    finally:
        pool.close()


@pytest.mark.parametrize("change", ["supersede", "cancel"])
def test_successor_waits_for_old_phase_writer(change):
    entered, release, woke = Event(), Event(), Event()
    writes = []
    pool = ReadyPreparationPool(woke.set, max_active_stages=1)
    key = ("run", "stage")

    def first():
        entered.set()
        assert release.wait(10)
        writes.append("old")
        return "old"

    def second():
        writes.append("new")
        return "new"

    try:
        pool.poll(key, "old-request", lambda: True)
        assert woke.wait(10)
        woke.clear()
        # Even after the request completes, its descriptor phase still owns a
        # slot/writer. Neither cancellation nor a new generation may reuse it.
        assert pool.poll(key, "old-input", first, phase="input-descriptors") == (None, "stage_preparation_pending")
        assert entered.wait(10)
        if change == "cancel":
            pool.retain_run("run", set())
            assert pool.poll(("other", "stage"), "new", second) == (None, "stage_preparation_capacity")
        assert pool.poll(key, "new", second) == (None, "stage_preparation_superseded")
        assert writes == []
        release.set()
        assert woke.wait(10)
        woke.clear()
        pool.poll(key, "new", second)
        assert woke.wait(10)
        assert pool.poll(key, "new", second) == ("new", None)
        assert writes == ["old", "new"]
    finally:
        release.set()
        pool.close()


def test_cancellation_frees_only_its_runs_slots(monkeypatch):
    monkeypatch.setattr("loom.queue._ready_preparation.ThreadPoolExecutor", ControlledExecutor)
    pool = ReadyPreparationPool(lambda: None, max_active_stages=2)
    try:
        pool.poll(("cancelled", "a"), "a", lambda: "a")
        pool.poll(("peer", "b"), "b", lambda: "b")
        pool._workers.complete()
        pool.retain_run("cancelled", set())
        pool.poll(("replacement", "c"), "c", lambda: "c")
        assert pool.poll(("peer", "b"), "b", lambda: pytest.fail("repeated preparation")) == ("b", None)
        pool._workers.complete()
        assert pool.poll(("replacement", "c"), "c", lambda: None) == ("c", None)
    finally:
        pool.close()


def test_completed_inspection_transfers_to_stage_until_dispatch(monkeypatch):
    from loom.queue import _input_validation as validation

    monkeypatch.setattr("loom.queue._ready_preparation.ThreadPoolExecutor", ControlledExecutor)
    monkeypatch.setattr(validation, "ThreadPoolExecutor", ControlledExecutor)
    inspected = Counter()

    def inspect(scope, _roots, **_kwargs):
        inspected[scope["stage"]] += 1

    monkeypatch.setattr(validation, "require_bindings", inspect)
    pool = ReadyPreparationPool(lambda: None)
    scans = validation.InputValidationPool(lambda: None)

    def poll_scan(index):
        result = scans.poll(str(index), {}, {"stage": index}, {})
        if result.reason is None:
            scans.discard(str(index))
        return result, result.reason

    try:
        for index in range(32):
            pool.poll(("run", str(index)), "request", lambda: True)
        pool._workers.complete()
        for _ in range(6):
            scans._executor.complete()
            for index in range(32):
                pool.poll_observation(
                    ("run", str(index)), "inputs", lambda index=index: poll_scan(index),
                    phase="input-inspection",
                )
        # All consumers are still waiting on a later prerequisite/GPU budget.
        assert inspected == Counter({index: 1 for index in range(32)})
        assert scans.observations("run")["inspections"] == []
        for index in range(32):
            _, reason = pool.poll_observation(
                ("run", str(index)), "inputs",
                lambda: pytest.fail("completed inputs inspected again"), phase="input-inspection",
            )
            assert reason is None
        # An identity change must not reuse that evidence.
        value, reason = pool.poll_observation(
            ("run", "0"), "changed-inputs", lambda: ("new-evidence", None), phase="input-inspection",
        )
        assert (value, reason) == ("new-evidence", None)
        pool.discard(("run", "0"))
        assert pool.poll_observation(
            ("run", "0"), "changed-inputs", lambda: pytest.fail("owner retired"), phase="input-inspection",
        )[1] == "stage_preparation_pending"
    finally:
        scans.close()
        pool.close()


@pytest.mark.parametrize("blocked_class,peer_class", [("gpu", "cpu"), ("cpu", "gpu")])
def test_completed_waiting_class_keeps_preparation_capacity_for_peer(monkeypatch, blocked_class, peer_class):
    monkeypatch.setattr("loom.queue._ready_preparation.ThreadPoolExecutor", ControlledExecutor)
    pool = ReadyPreparationPool(lambda: None)
    try:
        for index in range(32):
            pool.poll(("blocked", str(index)), "request", lambda: True, resource_class=blocked_class)
        pool._workers.complete()
        assert len(pool._pending) == 31
        # Waiting prerequisites stay retained; the peer can prepare and leave
        # repeatedly without waiting for any allocation in the blocked class.
        for index in range(100):
            key = ("peer", str(index))
            pool.poll(key, "request", lambda: True, resource_class=peer_class)
            pool._workers.complete()
            assert pool.poll(key, "request", lambda: pytest.fail("repeated preparation"), resource_class=peer_class) == (True, None)
            pool.discard(key)
        for index in range(31):
            assert pool.poll(("blocked", str(index)), "request", lambda: pytest.fail("evicted prerequisite"), resource_class=blocked_class) == (True, None)
    finally:
        pool.close()
