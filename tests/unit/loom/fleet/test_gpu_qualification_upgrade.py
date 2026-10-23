"""Upgrade capability policy never queues an exclusive GPU assignment."""

from types import SimpleNamespace

import pytest

from loom.fleet import upgrades
from loom.queue.errors import QueueConflictError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("outcome", ["passed", "failed"])
@pytest.mark.parametrize("submitted", [False, True])
def test_upgrade_uses_host_capability_and_keeps_cpu_storage_checks(tmp_path, monkeypatch, outcome, submitted):
    profile = {"profile_id": "selected"}
    execution = None
    declarations = {"worker": {"resident_profiles": [{"descriptor": profile}]}}
    offer = {"profile_identities": [profile]}
    selection = {}
    if submitted:
        from tests.integration.queue.test_submitted_container_agents import _fixture

        policy, execution, _ = _fixture(tmp_path)
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
    assert calls == [("worker", "gpu-capability", {"profile": profile,
        **({"execution": execution.to_dict()} if execution is not None else {})})]
