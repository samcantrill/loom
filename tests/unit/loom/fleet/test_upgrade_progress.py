"""Independent clock, native gate provenance, and diagnostic boundary oracles."""
import json
import threading
import time
from types import SimpleNamespace

import pytest

from loom.fleet._upgrade_progress import Observation, encode
from loom.fleet import upgrades
from loom.fleet._host import atomic


def test_monotonic_disjoint_preparation_and_partial_gate_clocks(monkeypatch):
    now = [0.0]
    observation = Observation(None, "apply", clock=lambda: now[0])
    now[0] = 4
    assert observation.snapshot()["preparation_seconds"] == 4
    now[0] = 7
    observation.enter("closing_admission")
    assert observation.snapshot()["admission_closed_seconds"] is None
    now[0] = 10
    observation.gate(True)
    observation.enter("settling")
    now[0] = 12
    observation.gate(True)  # Repeated live observations do not reset the span.
    assert observation.snapshot()["phase_elapsed_seconds"] == 2
    monkeypatch.setattr(time, "time", lambda: -100000)
    now[0] = 18
    observation.gate(False)
    now[0] = 20
    observation.finish("complete")
    snapshot = observation.snapshot("result")
    assert snapshot["elapsed_seconds"] == 20
    assert snapshot["preparation_seconds"] == 7
    assert snapshot["admission_closed_seconds"] == 8
    assert snapshot["phase_elapsed_seconds"] == 0
    now[0] = 50
    assert observation.snapshot("result") == snapshot

    now[0] = 0
    resumed = Observation(None, "resume", clock=lambda: now[0])
    resumed.end_preparation()
    now[0] = 3
    resumed.gate(True)
    resumed.enter("preparing")
    now[0] = 5
    assert resumed.snapshot()["admission_closed_seconds"] == 2
    assert resumed.snapshot()["preparation_seconds"] == 2
    resumed.enter("replacing")
    now[0] = 6
    resumed.enter("preparing")
    now[0] = 8
    assert resumed.snapshot()["preparation_seconds"] == 4
    assert Observation(None, "resume").snapshot()["admission_closed_seconds"] is None


def test_native_gate_requires_live_matching_observation_and_fresh_open(tmp_path):
    now = [0.0]
    observer = Observation(None, "resume", clock=lambda: now[0])
    op = object.__new__(upgrades._Upgrade)
    op.observation = observer
    op.intent = {"operation_id": "window"}
    op.receipts = tmp_path
    (tmp_path / "close").mkdir()
    (tmp_path / "open").mkdir()
    binding = upgrades._maintenance_binding(op.intent)
    closed = {"state": "closed", "maintenance_id": "window",
              "intent_digest": binding["target_intent_digest"], "revision": 1}
    live = [closed]
    op.operator = SimpleNamespace(observe_maintenance=lambda: live[0])
    op.native = lambda *args: {"gate": closed}
    # The embedded mutation gate is historical even for a successful close reply.
    op.maintenance("close", "close")  # Existing pre-request observation is live.
    assert observer.snapshot()["admission_closed_seconds"] == 0
    observer.closed = None
    atomic(tmp_path / "close" / "intent.json", {
        "operation_id": "close", "action": "close", "check": None,
    })
    op.maintenance("close", "close")
    assert observer.snapshot()["admission_closed_seconds"] is None
    live[0] = {**closed, "maintenance_id": "other"}
    with pytest.raises(upgrades.QueueConflictError):
        op.gate()
    assert observer.snapshot()["admission_closed_seconds"] is None
    live[0] = closed
    now[0] = 3
    op.gate()
    atomic(tmp_path / "open" / "intent.json", {"operation_id": "open", "action": "open", "check": None})
    atomic(tmp_path / "open" / "dispatch.json", {})
    now[0] = 5
    op.maintenance("open", "open")  # Prior-invocation replay cannot stop this interval.
    now[0] = 6
    assert observer.snapshot()["admission_closed_seconds"] == 3
    live[0] = {"state": "open", "revision": 2}
    op.observe_gate()
    now[0] = 9
    assert observer.snapshot()["admission_closed_seconds"] == 3

    observer.closed, observer.opened = 10, None
    now[0] = 18
    op.maintenance("fresh-open", "open")
    now[0] = 20
    assert observer.snapshot()["admission_closed_seconds"] == 8


@pytest.mark.parametrize("mutation", [
    {"secret": "PRIVATE"}, {"phase": "PRIVATE"}, {"reason_code": "PRIVATE"},
    {"elapsed_seconds": float("nan")}, {"preparation_seconds": -1},
])
def test_stream_boundary_rejects_extra_data_and_nonfinite_clocks(mutation):
    snapshot = Observation(None, "apply").snapshot()
    line = encode(snapshot)
    assert len(line.encode()) <= 1024
    assert json.loads(line) == snapshot
    assert set(snapshot) == {"schema_version", "event", "kind", "action", "phase", "state", "reason_code",
                             "elapsed_seconds", "phase_elapsed_seconds", "preparation_seconds", "admission_closed_seconds"}
    with pytest.raises(ValueError):
        encode({**snapshot, **mutation})


def test_slow_and_broken_callback_do_not_hold_lifecycle():
    entered, release = threading.Event(), threading.Event()
    def slow(snapshot):
        entered.set()
        release.wait(10)
    observer = Observation(slow, "apply")
    assert entered.wait(2)
    started = time.monotonic()
    for _ in range(100):
        observer.enter("checking")
        observer.enter("restoring")
    observer.finish("complete")
    assert time.monotonic() - started < 1
    assert observer.worker is not None and observer.worker.daemon
    release.set()
    observer.worker.join(2)
    assert not observer.worker.is_alive()
    def broken(snapshot):
        raise BrokenPipeError("PRIVATE")
    observer = Observation(broken, "apply")
    observer.finish("complete")
    assert observer.worker is not None
    observer.worker.join(2)
    assert not observer.worker.is_alive()


@pytest.mark.parametrize("outcome,code", [("failed", "check_failed"), ("unsupported", "native_refusal")])
def test_only_confirmed_failed_checks_are_labelled_failed(tmp_path, monkeypatch, outcome, code):
    observation = Observation(None, "resume")
    operation = SimpleNamespace(
        directory=tmp_path, observation=observation, inventory=object(),
        intent={"agents": {"worker": {}}, "timeout_seconds": 1,
                "declarations": {"worker": {"resident_profiles": [{}]}}},
        maintenance=lambda *args: None,
    )
    atomic(tmp_path / "checks.json", {
        "worker:" + kind: [{"operation_id": "check-" + kind, "authorization": {}}]
        for kind in ("cpu", "storage")
    })
    monkeypatch.setattr(upgrades, "self_test", lambda *args, **kwargs: {"outcome": outcome})
    with pytest.raises(upgrades.QueueConflictError):
        upgrades._run_checks(operation)
    assert observation.snapshot()["phase"] == "checking"
    assert observation.snapshot()["reason_code"] == code
