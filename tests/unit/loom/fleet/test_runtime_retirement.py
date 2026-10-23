"""Runtime retirement stages qualification before closing the existing gate."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.fleet import runtime_retirement as retirement, upgrades, workload_sources
from loom.fleet._host import atomic


def test_combined_retirement_preview_does_not_require_old_runtime_retirement_support(tmp_path, monkeypatch):
    from loom.cli.main import build_parser

    args = build_parser().parse_args(["fleet", "upgrade", "--fleet", "lab",
        "--runtime-release", "/new.json", "--retire-configuration",
        "--workload-inventory", "/candidate.json", "--check-execution", "/execution.json"])
    assert args.runtime_release == Path("/new.json") and args.retire_configuration
    declarations = {"coordinator": {"preparation": {"profiles": {
        "selected": {"container_policy_id": "containers"}}}},
        "worker": {"resident_profiles": [], "container_policies": [{"policy_id": "containers"}]}}
    plan = {"agents": {"worker": {}}, "checks": {"deployment": "/check.json"},
            "source": {"value": {"capabilities": []}}}
    seen = []

    def preview(*args, **kwargs):
        seen.append(kwargs)
        return deepcopy(plan)

    monkeypatch.setattr(upgrades, "preview", preview)
    monkeypatch.setattr(workload_sources, "candidates", lambda *args, **kwargs:
                        (declarations, {"candidate": "hash"}, {"hosts": {}, "declarations": declarations}))
    monkeypatch.setattr(retirement, "load_deployment", lambda _: SimpleNamespace(preparation_profile="selected"))
    result = retirement.preview(SimpleNamespace(), runtime_release=Path("/new.json"),
        workload_inventory=tmp_path / "candidate.json", deployment=None, connection=None,
        config="check.yaml", check_execution=object(), env_file=None)
    assert result["runtime_retirement"] and result["retire_configuration"]
    assert result["candidates"] == {} and result["coordinator_target"] is None
    assert result["target_declarations"] == declarations
    assert seen[0]["runtime_release"] == Path("/new.json")
    assert "retire_configuration" not in seen[0]


@pytest.mark.parametrize("interrupted", [False, True])
def test_bootstrap_restarts_coordinator_before_serial_agent_conversion(tmp_path, monkeypatch, interrupted):
    events = []
    hosts = {name: {"host": name, "expected_root_id": name, "source_release": "old"}
             for name in ("coordinator", "one", "two")}
    intent = {"hosts": hosts, "agents": {"one": {}, "two": {}}, "release": "new",
              "operation_id": "migration", "target_declarations": {name: {} for name in hosts}}
    receipts = tmp_path / "steps"
    receipts.mkdir()
    for name in intent["agents"]:
        directory = receipts / (name + "-workload-stage")
        directory.mkdir()
        atomic(directory / "receipt.json", {"candidate_source": "/" + name + ".json"})
    state = {"coordinator": False, "interrupted": False}

    def call(name, action, **values):
        events.append((name, action))
        if action == "workload-publish":
            assert all((host, "upgrade-stop") in events for host in hosts)
            assert values["expected_scheduling_epoch"] == "epoch"
        if action == "upgrade-replace":
            assert ("coordinator", "workload-publish") in events
            state["coordinator"] = True
        return {}

    def promote(name, candidate, replacement):
        assert state["coordinator"]
        events.append((name, "promote"))
        if interrupted and name == "one" and not state["interrupted"]:
            state["interrupted"] = True
            raise upgrades._Waiting("agent acknowledgement")

    operation = SimpleNamespace(directory=tmp_path, intent=intent, receipts=receipts,
        inventory=object(), operator=SimpleNamespace(observe_status=lambda: SimpleNamespace(value={"scheduling_epoch": "epoch"})),
        reconcile_publications=lambda: events.append("reconcile"), recheck=lambda: events.append("recheck"),
        probes=lambda: events.append("qualify"), call=call, call_many=lambda values: events.append("stage"),
        maintenance=lambda *args: events.append("close"), settled=lambda: None,
        gate=lambda: {"maintenance_id": "migration", "intent_digest": "digest", "revision": 2},
        host_observe=lambda *args: {"availability": "available", "value": {"settled": True}},
        qualification=lambda name: {"retirement_target": {"active": name}},
        runtime_arguments=lambda name: {}, promote_stopped=promote)
    monkeypatch.setattr(retirement.sshops, "_bundle", lambda _: {})
    monkeypatch.setattr(retirement.sshops, "_ssh_many", lambda _: {"ok": {}})
    monkeypatch.setattr(upgrades, "phase", lambda *args: None)
    monkeypatch.setattr(upgrades, "_capable", lambda *args: {})
    monkeypatch.setattr(upgrades, "_preflight_checks", lambda _: events.append("preflight"))
    monkeypatch.setattr(upgrades, "_independent_policies", lambda *args: None)
    monkeypatch.setattr(upgrades._Upgrade, "probes", lambda _: events.append("running"))
    monkeypatch.setattr(upgrades, "_run_checks", lambda _: events.append("checks"))
    monkeypatch.setattr(upgrades, "_restore", lambda _: events.append("restore"))
    monkeypatch.setattr(upgrades, "_complete_runtime", lambda _: {"state": "complete"})
    if interrupted:
        with pytest.raises(upgrades._Waiting):
            retirement.continue_upgrade(operation)
        assert ("two", "promote") not in events and "checks" not in events and "restore" not in events
        events.clear()
    assert retirement.continue_upgrade(operation) == {"state": "complete"}
    assert events[:2] == ["reconcile", "recheck"]
    assert events.index(("coordinator", "upgrade-replace")) < events.index(("one", "promote")) < events.index(("two", "promote"))
    assert events[-3:] == ["running", "checks", "restore"]
    if not interrupted:
        assert events.index("qualify") < events.index("preflight") < events.index("close")
