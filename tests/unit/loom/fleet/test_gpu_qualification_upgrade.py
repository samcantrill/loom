"""Upgrade capability policy never queues an exclusive GPU assignment."""

from types import SimpleNamespace

import pytest

from loom.fleet import upgrades
from loom.queue.errors import QueueConflictError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("outcome", ["passed", "failed"])
@pytest.mark.parametrize("mode", ["resident", "submitted", "selected", "selected-retry"])
def test_upgrade_uses_host_capability_and_keeps_cpu_storage_checks(tmp_path, monkeypatch, outcome, mode):
    profile = {"profile_id": "selected"}
    execution = None
    declarations = {"worker": {"resident_profiles": [{"descriptor": profile}]}}
    offer = {"profile_identities": [profile]}
    selection = {}
    if mode != "resident":
        from tests.integration.queue.test_submitted_container_agents import _fixture

        policy, execution, _ = _fixture(tmp_path)
        if mode.startswith("selected"):
            from dataclasses import replace
            from loom.queue.submitted_execution import SELECTED_INPUT_WORKER_CONTRACT

            dataset = tmp_path / "unselected"
            dataset.mkdir()
            policy = replace(policy, worker_contracts=(SELECTED_INPUT_WORKER_CONTRACT,),
                shared_roots={**policy.shared_roots, "unselected": {
                    "host_path": str(dataset), "container_path": "/loom/unselected", "access": "ro",
                    "qualification": {"kind": "input_directory"},
                }})
            execution = replace(execution, worker_contract=SELECTED_INPUT_WORKER_CONTRACT)
        profile = policy.capability.to_dict()
        offer = {"profile_identities": [], "container_execution_capabilities": [profile]}
        declarations = {
            "worker": {"resident_profiles": [], "container_policies": [{"policy_id": policy.policy_id}]},
            "coordinator": {"preparation": {"profiles": {"submitted": {"container_policy_id": policy.policy_id}}}},
        }
        selection = {"execution": execution.to_dict(), "deployment": "selected.json"}
        monkeypatch.setattr(upgrades, "load_deployment", lambda path: SimpleNamespace(preparation_profile="submitted"))
    calls = []
    prepared = []
    settled = []
    op = SimpleNamespace(
        directory=tmp_path,
        receipts=tmp_path / "steps",
        inventory=None,
        operator=SimpleNamespace(observe_agent=lambda name: SimpleNamespace(
            availability="available", freshness="current",
            value={"offer": offer},
        )),
        intent={
            "operation_id": "upgrade-test",
            "check_selection": selection,
            "agents": {"worker": {}},
            "declarations": declarations,
            "gpu_qualification": "nonexclusive",
            "timeout_seconds": 20,
        },
        call=lambda name, action, **kw: calls.append((name, action, kw)) or {"outcome": outcome},
        maintenance=lambda *args: None,
        settled=lambda: settled.append(True),
    )
    monkeypatch.setattr(upgrades, "phase", lambda *args: None)
    monkeypatch.setattr(upgrades, "_attempts", lambda op: {})
    monkeypatch.setattr(upgrades, "_check_kinds", lambda *args: ("cpu", "storage", "gpu"))
    retry = {}
    if mode == "selected-retry":
        path = op.receipts / "worker-gpu-capability"
        path.mkdir(parents=True)
        upgrades.atomic(path / "successors.json", [{
            "operation_id": "retry", "previous_check_id": "failed",
            "step_key": "worker-gpu-capability-retry",
        }])
        retry = {"_step_key": "worker-gpu-capability-retry"}

    def prepare(op, name, check, identity):
        prepared.append(check)
        return {"operation_id": identity, "authorization": {}}

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(
        upgrades, "self_test",
        lambda *a, **kw: {"outcome": "passed", "checks": {}},
    )
    if outcome == "failed":
        with pytest.raises(QueueConflictError, match="GPU capability failed"):
            upgrades._run_checks(op)
        assert not settled
    else:
        upgrades._run_checks(op)
        assert settled == [True]
    assert prepared == ["cpu", "storage"]
    assert calls == [("worker", "gpu-capability", {"profile": profile, **retry,
        **({"execution": execution.to_dict()} if execution is not None else {})})]


@pytest.mark.parametrize("prior", ["unknown", "failed", "passed", "remote_passed", "transport_unavailable", "not_dispatched"])
def test_explicit_gpu_retry_preserves_prior_attempt_and_replays(tmp_path, monkeypatch, prior):
    original = tmp_path / "steps/worker-gpu-capability"
    original.mkdir(parents=True)
    upgrades.atomic(original / "intent.json", {"request_id": "original-probe"})
    if prior != "not_dispatched":
        upgrades.atomic(original / "dispatch.json", {"outcome": "unknown"})
    if prior in {"failed", "passed"}:
        upgrades.atomic(original / "receipt.json", {"outcome": prior})
    before = {path: path.read_bytes() for path in original.iterdir()}
    verified = []
    operation = SimpleNamespace(
        directory=tmp_path, receipts=tmp_path / "steps",
        inventory=SimpleNamespace(path=tmp_path / "fleet.json"),
        intent={"agents": {"worker": {}}, "hosts": {"worker": {"host": "fixture"}},
                "gpu_qualification": "nonexclusive"},
        recheck=lambda: verified.append("inputs"),
        gate=lambda: verified.append("gate"),
        probes=lambda: verified.append("owners"),
        settled=lambda: verified.append("settled"),
        _finish_call=lambda name, step, request, response: upgrades.atomic(step / "receipt.json", response),
    )
    monkeypatch.setattr(upgrades, "_continue", lambda op: {"outcome": "continued"})
    observations = []

    def receipt(host, request):
        assert host == "fixture" and request == {"request_id": "original-probe", "action": "receipt"}
        observations.append(request)
        if prior == "transport_unavailable":
            raise upgrades.sshops.SshUnavailable("receipt unavailable")
        return {"outcome": "passed"} if prior == "remote_passed" else None

    monkeypatch.setattr(upgrades.sshops, "ssh", receipt)
    if prior == "transport_unavailable":
        with pytest.raises(upgrades.sshops.SshUnavailable, match="receipt unavailable"):
            upgrades._retry_check(operation, "original-probe", "replacement")
        assert not (original / "successors.json").exists()
    elif prior in {"passed", "remote_passed", "not_dispatched"}:
        with pytest.raises(QueueConflictError, match="cannot be replaced|not been dispatched"):
            upgrades._retry_check(operation, "original-probe", "replacement")
        assert not (original / "successors.json").exists()
    else:
        assert upgrades._retry_check(operation, "original-probe", "replacement") == {"outcome": "continued"}
        assert verified == ["inputs", "gate", "owners", "settled"]
        retained = (original / "successors.json").read_bytes()
        assert upgrades._gpu_check_successors(operation, "worker") == [{
            "operation_id": "replacement", "previous_check_id": "original-probe",
            "step_key": "worker-gpu-capability-replacement",
        }]
        upgrades._retry_check(operation, "original-probe", "replacement")
        assert (original / "successors.json").read_bytes() == retained
        with pytest.raises(QueueConflictError, match="another successor"):
            upgrades._retry_check(operation, "original-probe", "different")
    assert all(path.read_bytes() == value for path, value in before.items())
    assert bool(observations) == (prior in {"unknown", "remote_passed", "transport_unavailable"})


def test_gpu_retry_refuses_changed_maintenance_owner(tmp_path, monkeypatch):
    original = tmp_path / "steps/worker-gpu-capability"
    original.mkdir(parents=True)
    upgrades.atomic(original / "intent.json", {"request_id": "original-probe"})
    upgrades.atomic(original / "dispatch.json", {"outcome": "unknown"})

    def changed_owner():
        raise QueueConflictError("maintenance owner changed")

    operation = SimpleNamespace(
        directory=tmp_path, receipts=tmp_path / "steps",
        inventory=SimpleNamespace(path=tmp_path / "fleet.json"),
        intent={"agents": {"worker": {}}, "hosts": {"worker": {"host": "fixture"}},
                "gpu_qualification": "nonexclusive"},
        recheck=lambda: None, gate=changed_owner,
    )
    monkeypatch.setattr(upgrades.sshops, "ssh", lambda *args: None)
    with pytest.raises(QueueConflictError, match="maintenance owner changed"):
        upgrades._retry_check(operation, "original-probe", "replacement")
    assert not (original / "successors.json").exists()


def test_scheduled_retry_still_requires_confirmed_native_failure(tmp_path, monkeypatch):
    original = tmp_path / "steps/worker-gpu-capability"
    original.mkdir(parents=True)
    upgrades.atomic(original / "intent.json", {"request_id": "gpu-probe"})
    upgrades.atomic(tmp_path / "checks.json", {"worker:cpu": [{"operation_id": "cpu-check"}]})
    operation = SimpleNamespace(
        directory=tmp_path, receipts=tmp_path / "steps",
        inventory=SimpleNamespace(path=tmp_path / "fleet.json"),
        intent={"agents": {"worker": {}}, "gpu_qualification": "nonexclusive"},
        recheck=lambda: None, gate=lambda: None, probes=lambda: None,
    )

    def refuse_unconfirmed(op, identity):
        assert op is operation and identity == "cpu-check"
        raise QueueConflictError("confirmed native terminal failure required")

    monkeypatch.setattr(upgrades, "_require_failed_check", refuse_unconfirmed)
    with pytest.raises(QueueConflictError, match="confirmed native terminal failure"):
        upgrades._retry_check(operation, "cpu-check", "replacement")
    assert not (original / "successors.json").exists()
