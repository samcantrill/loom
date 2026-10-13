"""Fleet waits only for native evidence and retains pending/failed outcomes."""
from types import SimpleNamespace

import pytest

from loom.fleet import upgrades


@pytest.mark.parametrize("states,timeout,expected,calls", [
    ([{"state": "applying", "acknowledged": False}, {"state": "applied", "acknowledged": True}], 2, "applied", 2),
    ([{"state": "failed", "acknowledged": True}], 2, "failed", 1),
    ([{"state": "applying", "acknowledged": False}], 0.5, "applying", 3),
    ([{"state": "applied", "acknowledged": False}], 0.25, "applied", 2),
])
def test_control_acknowledgement_retains_native_outcome(monkeypatch, states, timeout, expected, calls):
    clock = [0.0]
    observed = []
    monkeypatch.setattr(upgrades.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(upgrades.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))

    def observe(identity):
        assert identity == "retained-control"
        observed.append(identity)
        return states[min(len(observed) - 1, len(states) - 1)]

    result = upgrades._observe_control(SimpleNamespace(observe_control=observe), "retained-control", timeout)
    assert result["state"] == expected
    assert result is states[min(calls - 1, len(states) - 1)]
    assert len(observed) == calls
    assert clock[0] <= timeout


def test_control_acknowledgement_uses_selected_longer_timeout(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(upgrades.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(upgrades.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    def observe(identity):
        ready = clock[0] >= 35
        return {"state": "applied" if ready else "applying", "acknowledged": ready}
    result = upgrades._observe_control(SimpleNamespace(observe_control=observe), "slow-ready", 60)
    assert result == {"state": "applied", "acknowledged": True}
    assert clock[0] == 35
