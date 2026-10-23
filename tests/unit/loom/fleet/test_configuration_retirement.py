"""Retirement orchestration selects native policy changes and submitted checks."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.fleet import upgrades, workload_upgrades, workload_sources
from loom.queue.errors import QueueConfigError, QueueConflictError


def test_cli_retirement_selects_no_resident_image():
    from loom.cli.main import build_parser

    selected = build_parser().parse_args([
        "fleet", "upgrade", "--fleet", "lab", "--retire-configuration",
        "--workload-inventory", "/private/candidate.json", "--check-execution", "/private/execution.json",
        "--hold-admission",
    ])
    assert selected.retire_configuration and selected.hold_admission
    assert selected.workload_profile is None and selected.image is None


@pytest.mark.parametrize("interruption", [None, "workload-stopped-retire", "upgrade-replace"])
def test_stopped_promotion_reconciles_publication_before_control_replay(tmp_path, interruption):
    from loom.fleet._host import atomic

    operation = object.__new__(workload_upgrades.WorkloadUpgrade)
    operation.receipts = tmp_path
    operation.intent = {"retire_configuration": True,
        "hosts": {"worker": {"expected_root_id": "root", "source_release": "old"}},
        "check_selection": {"coordinator_id": "coordinator"}}
    control = {"operation_id": "promotion", "candidate_source": "/candidate.json"}
    state = {"published": False, "reconciled": False, "started": False, "ack": False,
             "interrupted": False}
    calls = []

    def accept(name, candidate):
        assert not state["published"] or state["reconciled"]
        calls.append("control")
        return control, {"state": "applied" if state["ack"] else "applying",
                         "acknowledged": state["ack"]}

    def call(name, action, **values):
        calls.append(action)
        if action == "workload-stopped-retire":
            assert values == {"control": control, "expected_root_id": "root",
                              "source_release": "old", "coordinator_id": "coordinator"}
            directory = tmp_path / (name + "-" + action)
            directory.mkdir(exist_ok=True)
            atomic(directory / "intent.json", values)
            state["published"] = True
        else:
            assert state["published"] and state["reconciled"]
            assert values == {"release_options": "exact"}
            state["started"] = True
        if action == interruption and not state["interrupted"]:
            state["interrupted"] = True
            raise RuntimeError("lost host reply")
        if action == "workload-stopped-retire":
            state["reconciled"] = True
        return {}

    operation.accept_promotion = accept
    operation.call = call
    if interruption:
        with pytest.raises(RuntimeError, match="lost host reply"):
            operation.promote_stopped("worker", "/candidate.json", {"release_options": "exact"})
        calls.clear()
    with pytest.raises(upgrades._Waiting, match="acknowledgement"):
        operation.promote_stopped("worker", "/candidate.json", {"release_options": "exact"})
    assert calls == (["control"] if interruption is None else []) + [
        "workload-stopped-retire", "upgrade-replace", "control"]
    assert state["started"]
    state["ack"] = True
    calls.clear()
    assert operation.promote_stopped("worker", "/candidate.json", {"release_options": "exact"}) == "promotion"
    assert calls == ["workload-stopped-retire", "upgrade-replace", "control"]


def test_promotion_acceptance_retains_exact_control_before_acknowledgement(tmp_path):
    from loom.fleet._host import atomic

    operation = object.__new__(workload_upgrades.WorkloadUpgrade)
    operation.receipts = tmp_path
    operation.intent = {"operation_id": "upgrade", "retire_configuration": True,
        "candidates": {"worker": {"source": {"immutable": "a" * 64, "active": "b" * 64},
            "target": {"immutable": "c" * 64, "active": "d" * 64}, "declaration": {}}},
        "declarations": {"worker": {}}}
    operation.gate = lambda: {"revision": 3}
    controls = []
    state = {"state": "pending_delivery", "acknowledged": False}
    operation.operator = SimpleNamespace(
        observe_agent=lambda _: SimpleNamespace(value={"session_id": "session", "config_revision": "1", "agent_root_id": "root"}),
        control_agent=lambda control, **kwargs: controls.append((control.value(), kwargs)),
        observe_control=lambda _: dict(state),
    )

    def native(key, value, invoke):
        directory = tmp_path / key
        directory.mkdir(exist_ok=True)
        atomic(directory / "intent.json", value)
        return invoke(value)

    operation.native = native
    request, result = operation.accept_promotion("worker", "/private/candidate.json")
    assert result == state
    assert request["promotion"]["retire_configuration"]
    assert request["promotion"]["expected_gate_revision"] == 3
    with pytest.raises(upgrades._Waiting, match="acknowledgement"):
        operation.promote("worker", "/private/candidate.json")
    state.update(state="applied", acknowledged=True)
    assert operation.promote("worker", "/private/candidate.json") == request["operation_id"]
    assert all(control == request for control, _ in controls)
    assert all(condition == {"condition": {"expected_control_id": "upgrade-worker-drain"}}
               for _, condition in controls)
    state.update(state="failed", acknowledged=True)
    with pytest.raises(QueueConflictError, match="native profile promotion failed"):
        operation.accept_promotion("worker", "/private/candidate.json")


@pytest.mark.parametrize("unsupported", [None, "coordinator", "worker"])
def test_retirement_preview_uses_bound_predecessors_and_preserves_profile_alias(tmp_path, monkeypatch, unsupported):
    release = {"release_id": "current"}
    capabilities = [workload_upgrades.CAPABILITY, workload_upgrades.RETIREMENT_CAPABILITY,
                    "quiescent-coordinator-retirement-v1"]
    declarations = {
        "coordinator": {"preparation": {"profiles": {"retained": {"container_policy_id": "containers"}}}},
        "worker": {"resident_profiles": [], "container_policies": [{"policy_id": "containers"}]},
    }
    plan = {"release": release, "source": {"value": {"capabilities": list(capabilities)}},
        "hosts": {name: {"host": name, "source_release": release,
                          "native_owner": {"value": {"capabilities": list(capabilities)}}}
                  for name in declarations},
        "declarations": declarations, "checks": {"deployment": "/check.json"}, "agents": {"worker": {}}}
    if unsupported == "coordinator":
        plan["source"]["value"]["capabilities"] = []
    elif unsupported:
        plan["hosts"]["worker"]["native_owner"]["value"]["capabilities"] = []
    monkeypatch.setattr(upgrades, "preview", lambda *args, **kwargs: deepcopy(plan))
    candidates = []

    def source_candidates(*args, **kwargs):
        assert kwargs == {"retire_configuration": True}
        candidates.append(True)
        return deepcopy(declarations), {}, {"hosts": {}, "declarations": {}}

    monkeypatch.setattr(workload_sources, "candidates", source_candidates)
    monkeypatch.setattr(workload_upgrades, "load_deployment", lambda _: SimpleNamespace(preparation_profile="retained"))
    requests = []

    def probe(rows):
        requests.extend(value[1] for value in rows.values())
        return {"worker": {"source": {"immutable": "old", "active": "accepted"},
                           "target": {"profile": None}, "declaration": declarations["worker"]}}

    monkeypatch.setattr(workload_upgrades.sshops, "_ssh_many", probe)
    monkeypatch.setattr(workload_upgrades.sshops, "ssh", lambda *args: {"active": "target-coordinator"})
    kwargs = dict(workload_inventory=tmp_path / "candidate.json", deployment=None, connection=None,
                  config="check.yaml", check_execution=object(), env_file=None)
    inventory = SimpleNamespace(runtime_release=Path("/runtime.json"))
    if unsupported:
        with pytest.raises(QueueConflictError, match="retirement capability"):
            workload_upgrades.retirement_preview(inventory, **kwargs)
        assert not candidates and not requests
        return
    result = workload_upgrades.retirement_preview(inventory, **kwargs)
    assert result["retire_configuration"] and result["preparation_profile"] == "retained"
    assert result["image"] is None and result["workload_profile"] is None
    assert result["checks"] == plan["checks"]
    assert requests[0]["retire_configuration"]
    assert not {"image", "image_sha256", "workload_profile"}.intersection(requests[0])


@pytest.mark.parametrize("missing", ["workload_inventory", "check_execution"])
def test_retirement_requires_explicit_candidate_and_submitted_execution(missing):
    kwargs = dict(workload_inventory="/candidate.json", check_execution=object(), deployment=None,
                  connection=None, config="check.yaml", env_file=None)
    kwargs[missing] = None
    with pytest.raises(QueueConfigError, match="candidate inventory and submitted"):
        workload_upgrades.retirement_preview(object(), **kwargs)


def test_candidate_source_retirement_preserves_existing_logical_bindings():
    before = {"remote_profiles": [{"profile_id": "unused"}], "preparation": {
        "source_roots": {"current": {"path": "/current"}, "old": {"path": "/old"}},
        "profiles": {"selected": {"container_policy_id": "containers", "allowed_source_roots": ["current", "old"]}},
    }}
    after = deepcopy(before)
    after["remote_profiles"] = []
    del after["preparation"]["source_roots"]["old"]
    after["preparation"]["profiles"]["selected"]["allowed_source_roots"] = ["current"]
    workload_sources._retirement_coordinator(before, after)
    after["preparation"]["source_roots"]["current"]["path"] = "/different"
    with pytest.raises(QueueConflictError, match="rebind preparation sources"):
        workload_sources._retirement_coordinator(before, after)


@pytest.mark.parametrize("changed", [None, "host", "root", "env_file"])
def test_retirement_accepts_temporary_candidate_without_changing_role_ownership(tmp_path, monkeypatch, changed):
    inventory = SimpleNamespace(service_manager="tmux", runtime_release=tmp_path / "release.json")
    before = {"host": "worker", "root": "/private/native", "env_file": None,
              "config": "/private/roles/coordinator.json"}
    after = {**before, "config": str(tmp_path / "candidate.json")}
    if changed:
        after[changed] = "different"
    declaration = {"shared_roots": {}, "preparation": {"profiles": {}, "source_roots": {}}}
    plan = {"hosts": {"coordinator": before}, "declarations": {"coordinator": declaration}}
    monkeypatch.setattr(workload_sources, "load_inventory", lambda path: inventory)
    monkeypatch.setattr(workload_sources.sshops, "_selection", lambda *args: (
        {"coordinator": after}, {"coordinator": declaration}))
    monkeypatch.setattr(workload_sources.sshops, "_inputs", lambda *args: {})
    if changed:
        with pytest.raises(QueueConflictError, match="same host, root and environment"):
            workload_sources.candidates(inventory, tmp_path / "fleet.json", plan, (), None,
                                        retire_configuration=True)
    else:
        result = workload_sources.candidates(inventory, tmp_path / "fleet.json", plan, (), None,
                                             retire_configuration=True)
        assert result[2]["hosts"]["coordinator"]["config"] == after["config"]
        with pytest.raises(QueueConflictError, match="sibling file"):
            workload_sources.candidates(inventory, tmp_path / "fleet.json", plan, (), None)


@pytest.mark.parametrize("change", [None, "policy", "root", "challenge", "image", "integration"])
def test_candidate_capability_retirement_narrows_permissions(tmp_path, change):
    from dataclasses import replace
    from tests.unit.loom.queue.test_submitted_container_policy import _submitted

    policy, _, _, _ = _submitted(tmp_path)
    # A data root is available to workloads but was never an image source.
    old = replace(policy.capability, project_integration_versions=())
    current = replace(old, shared_roots={"workloads": old.shared_roots["workloads"]},
                      environment_fingerprint="sha256:" + "b" * 64)
    before = {"container_capabilities": [old.to_dict()]}
    after = {"container_capabilities": [current.to_dict()]}
    if change == "policy":
        after["container_capabilities"][0]["policy_id"] = "new-policy"
    elif change == "root":
        after["container_capabilities"][0]["shared_roots"]["new-root"] = old.to_dict()["shared_roots"]["data"]
    elif change == "challenge":
        after["container_capabilities"][0]["shared_roots"]["workloads"]["challenge"]["sha256"] = "c" * 64
    elif change == "image":
        after["container_capabilities"][0]["shared_roots"] = old.to_dict()["shared_roots"]
        after["container_capabilities"][0]["allowed_image_roots"].append("data")
    elif change == "integration":
        after["container_capabilities"][0]["project_integration_versions"] = [3]
    if change is None:
        workload_sources._retirement_coordinator(before, after)
    else:
        with pytest.raises(QueueConflictError, match="expand or rebind container capability"):
            workload_sources._retirement_coordinator(before, after)


@pytest.mark.parametrize("name", ["coordinator", "worker"])
def test_retirement_resume_rechecks_peer_support_before_staging(tmp_path, monkeypatch, name):
    operation = object.__new__(workload_upgrades.WorkloadUpgrade)
    operation.directory = tmp_path
    operation.intent = {
        "retire_configuration": True, "release": "release",
        "hosts": {name: {"host": name, "source_release": "release", "expected_root_id": "owner"}},
    }
    monkeypatch.setattr(workload_upgrades.sshops, "ssh", lambda *args: {
        "installed": "release", "native_owner": {"owner": "owner", "value": {
            "ownership": "live", "capabilities": [workload_upgrades.CAPABILITY],
        }},
    })
    with pytest.raises(QueueConflictError, match="retirement capability unavailable: " + name):
        operation.probes()
    assert not list(tmp_path.iterdir())


def test_retirement_publication_continuation_restores_without_reactivation(tmp_path, monkeypatch):
    operation = SimpleNamespace(directory=tmp_path, intent={
        "kind": "configuration-retirement-publication",
    })
    (tmp_path / "restoring.json").write_text("{}")
    calls = []
    monkeypatch.setattr(upgrades, "_restore", lambda selected: calls.append(("restore", selected)))
    monkeypatch.setattr(workload_upgrades, "_complete_workload", lambda selected: calls.append(("complete", selected)))
    workload_upgrades.continue_upgrade(operation)
    assert calls == [("restore", operation), ("complete", operation)]
