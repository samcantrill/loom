"""Explicit resume successors preserve failures and conditional policy ownership."""
from types import SimpleNamespace

import pytest

from loom.coordinator import CoordinatorClientError
from loom.fleet import upgrades
from loom.fleet._host import atomic, protected_directory, read
from loom.queue.agent_sessions import AgentControl, AgentControlKind
from loom.queue.errors import QueueConflictError


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    operation = object.__new__(upgrades._Upgrade)
    operation.directory = tmp_path
    operation.receipts = tmp_path / "steps"
    operation.inventory = SimpleNamespace(path=tmp_path / "fleet.json")
    operation.intent = {"operation_id": "upgrade", "agents": {"worker": {"drained": False}}}
    key = "worker-checks-capacity"
    directory = operation.receipts / key
    protected_directory(directory)
    request = {
        **AgentControl("failed-resume", AgentControlKind.RESUME, "worker", "session", "config", None, False, "maintenance").value(),
        "condition": {"expected_control_id": "promotion"},
    }
    result = {"operation_id": "failed-resume", "state": "failed", "acknowledged": True, "code": "retained_work"}
    atomic(directory / "intent.json", request)
    atomic(directory / "receipt.json", result)
    state = SimpleNamespace(
        latest="failed-resume", controls={"failed-resume": result},
        calls=[], loss=False, settled=True, drained=True, config="config",
    )

    def observe(identity):
        if identity not in state.controls:
            raise CoordinatorClientError("not_found", boundary="local", operation="operator_operation")
        return state.controls[identity]

    def control(value, *, condition):
        state.calls.append((value.operation_id, condition))
        if value.operation_id not in state.controls:
            assert condition == {"expected_control_id": state.latest}
            state.latest = value.operation_id
            state.drained = False
            state.controls[value.operation_id] = {"state": "applied", "acknowledged": True, "code": "applied"}
            if state.loss:
                state.loss = False
                raise OSError("lost applied control reply")
        return observe(value.operation_id)

    def verify(name, expected):
        if state.latest != expected:
            raise QueueConflictError("independent native policy edit")
        return {"drained": state.drained, "session_id": "session", "config_revision": state.config}

    operation.operator = SimpleNamespace(observe_control=observe, control_agent=control)
    operation.recheck = lambda: None
    operation.gate = lambda: {"checks": {}}
    operation.settled = lambda: None
    operation.host_observe = lambda *a, **k: {"availability": "available", "value": {"settled": state.settled}}
    operation.verify_policy = verify
    operation.maintenance = lambda *a: None

    def continuation(op):
        identity = op.policy("worker", key, "resume", "promotion")
        op.verify_policy("worker", identity)
        # Restoration must verify the successor, not the original failed ID.
        upgrades._restore(op)
        return {"state": "complete"}

    monkeypatch.setattr(upgrades, "_continue", continuation)
    return operation, state, directory


def test_resume_successor_lost_reply_and_restoration_keep_failed_receipt(recovery):
    operation, state, directory = recovery
    evidence = {name: (directory / name).read_bytes() for name in ("intent.json", "receipt.json")}
    with pytest.raises(QueueConflictError, match="retry-control"):
        operation.policy("worker", "worker-checks-capacity", "resume", "promotion")
    state.loss = True
    with pytest.raises(OSError, match="lost applied"):
        upgrades._retry_control(operation, "failed-resume", "recovered-resume")
    successor_bytes = (directory / "successors.json").read_bytes()
    result = upgrades._retry_control(operation, "failed-resume", "recovered-resume")
    assert result == {"state": "complete"}
    assert state.latest == "recovered-resume"
    assert (directory / "successors.json").read_bytes() == successor_bytes
    assert all((directory / name).read_bytes() == data for name, data in evidence.items())
    assert set(state.controls) == {"failed-resume", "recovered-resume"}
    assert all(condition == {"expected_control_id": "failed-resume"} for identity, condition in state.calls if identity == "recovered-resume")
    assert read(directory / "successors.json")[0]["operation_id"] == "recovered-resume"
    with pytest.raises(QueueConflictError, match="another successor"):
        upgrades._retry_control(operation, "failed-resume", "different-resume")


@pytest.mark.parametrize("boundary", ["unknown", "unacknowledged", "independent", "unsettled", "config", "reused", "unowned"])
def test_resume_successor_refuses_without_current_native_proof(recovery, boundary):
    operation, state, directory = recovery
    failed = "failed-resume"
    if boundary == "unknown":
        state.controls[failed]["state"] = "applying"
    elif boundary == "unacknowledged":
        state.controls[failed]["acknowledged"] = False
    elif boundary == "independent":
        state.latest = "independent"
    elif boundary == "unsettled":
        state.settled = False
    elif boundary == "config":
        state.config = "new-config"
    elif boundary == "reused":
        state.controls["recovered-resume"] = {"state": "applied"}
    else:
        failed = "another-fleet"
    with pytest.raises((QueueConflictError, upgrades._Waiting)):
        upgrades._retry_control(operation, failed, "recovered-resume")
    assert not state.calls
    assert not (directory / "successors.json").exists()


def test_retry_control_cli_retains_both_operation_ids():
    from loom.cli.main import build_parser

    selected = build_parser().parse_args([
        "fleet", "operation", "retry-control", "upgrade", "--fleet", "lab",
        "--failed-control", "failed-resume", "--operation-id", "recovered-resume",
    ])
    assert selected.operation_id == "upgrade"
    assert selected.failed_control == "failed-resume"
    assert selected.new_control == "recovered-resume"
