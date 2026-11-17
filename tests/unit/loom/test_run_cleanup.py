"""Terminal science and this caller's physical release are separate facts."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from loom import _run


def _case(monkeypatch, *, owner="assignment", preparation=False, mode="release", lifetime="run"):
    clock = SimpleNamespace(now=0.0, polls=0, admissions=[])

    def sleep(seconds):
        clock.now += seconds

    monkeypatch.setattr(_run, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))

    def call(operation, payload, expected, *, deadline):
        assert expected == "coordinator-a" and deadline == 0.2
        if operation == "service_lifetime":
            clock.polls += 1
            return {"retained": mode != "release" or clock.polls == 1, "cleanup_blocked": None}
        assert operation == "admission"
        clock.admissions.append(payload["admission_id"])
        owners = {
            "assignment": {"availability": "available", "assignments": []},
            "slurm": {"availability": "available", "assignments": []},
            "execution": {"availability": "available", "journal": []},
        }
        selected = "preparation" if preparation else "target"
        if payload["admission_id"] == selected and mode != "other":
            key = "journal" if owner == "execution" else "assignments"
            owners[owner][key] = [{"state": "terminal_acknowledged"}]
            if mode == "unavailable":
                owners[owner]["availability"] = "unavailable"
        return SimpleNamespace(owners=owners)

    monkeypatch.setattr(_run, "_process_receipt", lambda root: (
        "persistent/borrowed" if lifetime == "persistent" else
        "stopped" if mode == "release" and clock.polls >= 2 else "running", {}
    ))
    available = SimpleNamespace(
        connection_id="coordinator-a", client=SimpleNamespace(_native_call=call),
        roles={"coordinator": {"identity": {"root": str(Path("role")), "lifetime": lifetime}}},
    )
    observation = SimpleNamespace(
        admission=SimpleNamespace(admission_id="target"),
        operation=SimpleNamespace(result={"preparation_admission_id": "preparation"}),
    )
    return clock, available, observation


@pytest.mark.parametrize("owner,preparation", [
    ("assignment", False), ("assignment", True), ("slurm", False), ("execution", False),
])
def test_cleanup_waits_for_own_release(monkeypatch, owner, preparation):
    clock, available, observation = _case(monkeypatch, owner=owner, preparation=preparation)
    result = _run._cleanup(cast(Any, available), cast(Any, observation), 0.2)
    assert result["coordinator"] == {"state": "stopped", "evidence": {}}
    assert clock.polls == 2
    assert ("preparation" if preparation else "target") in clock.admissions


def test_cleanup_returns_when_only_other_work_remains(monkeypatch):
    clock, available, observation = _case(monkeypatch, mode="other")
    result = _run._cleanup(cast(Any, available), cast(Any, observation), 0.2)
    assert result["coordinator"] == {"state": "retained-for-other-work", "evidence": {}}
    assert clock.polls == 1 and clock.now == 0


@pytest.mark.parametrize("mode", ["pending", "unavailable"])
def test_cleanup_keeps_deadline_when_own_release_is_pending(monkeypatch, mode):
    clock, available, observation = _case(monkeypatch, mode=mode)
    result = _run._cleanup(cast(Any, available), cast(Any, observation), 0.2)
    assert result["coordinator"] == {"state": "cleanup-blocked", "evidence": {}}
    assert clock.now == 0.2


@pytest.mark.parametrize("lifetime", ["persistent", "borrowed"])
def test_cleanup_skips_assignment_join_for_unowned_services(monkeypatch, lifetime):
    clock, available, observation = _case(monkeypatch, mode="other", lifetime=lifetime)
    if lifetime == "borrowed":
        available.roles = {}
    result = _run._cleanup(cast(Any, available), cast(Any, observation), 0.2)
    assert cast(dict[str, Any], result["coordinator"])["state"] == "persistent/borrowed"
    assert clock.admissions == []
