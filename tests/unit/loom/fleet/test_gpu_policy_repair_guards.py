"""Repair action routing and guards; native publication has integration coverage."""

from types import SimpleNamespace

import pytest

from loom.fleet import gpu_policy_repair, upgrades
from loom.fleet._host import atomic
from loom.fleet.configuration import protected_directory
from loom.queue.errors import QueueConfigError, QueueConflictError

pytestmark = pytest.mark.unit


@pytest.fixture
def operation(tmp_path):
    receipts = tmp_path / "steps"
    protected_directory(receipts / "coordinator-upgrade-replace")
    atomic(receipts / "coordinator-upgrade-replace/receipt.json", {"native_outcome": "applied"})
    calls = []
    return SimpleNamespace(directory=tmp_path, receipts=receipts, inventory=None, observation=None,
        intent={"kind": "runtime-upgrade", "operation_id": "upgrade", "agents": {"worker": {}},
                "hosts": {"coordinator": {"expected_root_id": "coordinator-id"}},
                "declarations": {"worker": {"resources": {"gpu": {"provider": "nvidia", "devices": "GPU-kept"}}}}},
        gate=lambda: {"settled": True, "checks": {}},
        call=lambda *args, **kwargs: calls.append((args, kwargs)) or {"reload": {"state": "applied"}},
        recheck=lambda: calls.append("recheck"), close=lambda: calls.append("close"), calls=calls)


@pytest.mark.parametrize("case", ["before_replacement", "checks", "restoring", "complete", "unknown_agent", "implicit_devices"])
def test_repair_refuses_unbound_or_late_changes(operation, case):
    if case == "before_replacement":
        (operation.receipts / "coordinator-upgrade-replace/receipt.json").unlink()
    elif case in {"checks", "restoring", "complete"}:
        atomic(operation.directory / (case + ".json"), {})
    elif case == "implicit_devices":
        operation.intent["declarations"]["worker"]["resources"]["gpu"]["devices"] = "all"
    with pytest.raises((QueueConfigError, QueueConflictError)):
        gpu_policy_repair.repair(operation, agent_id="other" if case == "unknown_agent" else "worker")
    assert operation.calls == []


def test_repair_routes_to_active_successor_and_keeps_parent_identity(operation, monkeypatch):
    parent = SimpleNamespace(directory=operation.directory / "parent", intent={"operation_id": "parent"},
        inventory=None, observation=None)
    successor = parent.directory / "runtime-candidate-repair"
    protected_directory(successor)
    binding = upgrades._maintenance_binding(parent.intent)
    operation.intent["maintenance_binding"] = binding
    atomic(successor / "intent.json", operation.intent)
    original = (successor / "intent.json").read_bytes()
    monkeypatch.setattr(upgrades, "_Upgrade", lambda inventory, directory, intent, observation: operation)
    result = gpu_policy_repair.repair(parent, agent_id="worker")
    assert result["state"] == "waiting"
    assert result["gpu_policy_repair"]["agent_id"] == "worker"
    args, values = operation.calls[0]
    assert args == ("coordinator", "repair-gpu-policy")
    assert values["gpu_uuids"] == ["GPU-kept"]
    assert values["maintenance_binding"] == binding
    assert operation.calls[1:] == ["recheck", "close"]
    assert (successor / "intent.json").read_bytes() == original
