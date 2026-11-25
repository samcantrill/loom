"""Upgrade qualification follows the retained native resource inventory."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.fleet import upgrades


@pytest.mark.parametrize("change", [{"state": "open"}, {"maintenance_id": "other"}, {"checks": {"running": {}}}])
def test_existing_gate_requires_exact_closed_owner_without_checks(change):
    from loom.queue.errors import QueueConflictError
    gate = {"state": "closed", "maintenance_id": "incident", "intent_digest": "digest", "checks": {}}
    assert upgrades._existing_maintenance_binding(gate, "incident") == {
        "operation_id": "incident", "target_intent_digest": "digest",
    }
    with pytest.raises(QueueConflictError, match="selected maintenance gate"):
        upgrades._existing_maintenance_binding({**gate, **change}, "incident")


@pytest.mark.parametrize("abort", [False, True])
def test_existing_gate_remains_closed_on_restore_and_abort(tmp_path, abort):
    calls = []
    operation = SimpleNamespace(
        intent={"kind": "runtime-upgrade", "agents": {}, "preserve_maintenance_gate": True},
        receipts=tmp_path, gate=lambda: {"checks": {"check-1": {}}},
        settled=lambda: calls.append("settled"),
        maintenance=lambda *args: calls.append(args),
    )
    operation.directory = tmp_path
    operation.deadline = None
    upgrades._restore(operation, abort=abort)
    assert ("revoke-check-1", "revoke", "check-1") in calls
    assert not any(isinstance(call, tuple) and "open" in call for call in calls)


def test_existing_gate_cli_selection():
    from loom.cli.main import build_parser
    selected = build_parser().parse_args([
        "fleet", "upgrade", "--fleet", "lab", "--runtime-release", "/private/release.json",
        "--maintenance-id", "incident", "--apply", "--operation-id", "upgrade",
    ])
    assert selected.maintenance_id == "incident"


@pytest.mark.parametrize("selected", ["infrastructure", "previous-generation"])
def test_check_profile_selects_resident_alias_among_submitted_container_policies(selected):
    declarations = {
        "worker": {"resident_profiles": [{"descriptor": {"profile_id": "analysis"}}]},
        "coordinator": {"preparation": {"profiles": {
            "submitted": {"container_policy_id": "submitted"},
            "infrastructure": {"resident_profile_id": "analysis"},
        }}},
    }
    assert upgrades._check_profile(
        declarations, "worker", SimpleNamespace(preparation_profile=selected)
    ) == "infrastructure"


@pytest.mark.parametrize("resident_aliases", [[], ["first", "second"]])
def test_container_policy_does_not_resolve_missing_or_ambiguous_resident_check(resident_aliases):
    from loom.queue.errors import QueueConfigError

    declarations = {
        "worker": {"resident_profiles": [{"descriptor": {"profile_id": "analysis"}}]},
        "coordinator": {"preparation": {"profiles": {
            "submitted": {"container_policy_id": "submitted"},
            **{alias: {"resident_profile_id": "analysis"} for alias in resident_aliases},
        }}},
    }
    with pytest.raises(QueueConfigError, match="ambiguous"):
        upgrades._check_profile(
            declarations, "worker", SimpleNamespace(preparation_profile="submitted")
        )


def test_runtime_workload_repair_cli_retains_parent_and_target():
    from loom.cli.main import build_parser

    selected = build_parser().parse_args([
        "fleet", "operation", "repair-workload", "runtime-window", "--fleet", "lab",
        "--workload-profile", "analysis", "--image", "/shared/compatible.sif",
        "--workload-inventory", "/private/candidate.json",
    ])
    assert selected.operation_id == "runtime-window"
    assert selected.workload_profile == "analysis"
    assert selected.image == Path("/shared/compatible.sif")
    assert selected.workload_inventory == Path("/private/candidate.json")


@pytest.mark.parametrize("device_source", ["native_inventory", "profile", "cpu_only"])
def test_upgrade_gpu_qualification_includes_native_inventory(
    tmp_path, check_gate, monkeypatch, device_source
):
    # NVIDIA discovery puts devices in the native offer while the authored
    # resident profile keeps an empty legacy GPU declaration.
    device = {"id": "GPU-qualified", "provider": "exclusive"}
    profile = {"gpu_devices": [device] if device_source == "profile" else []}
    agent = {"offer": {"gpu_devices": [device] if device_source == "native_inventory" else []}}
    observed = []
    settled = []
    operation = SimpleNamespace(
        directory=tmp_path,
        inventory=object(),
        intent={
            "operation_id": "upgrade-qualified",
            "declarations": {"worker": {"resident_profiles": [profile]}},
            "agents": {"worker": agent},
            "timeout_seconds": 30,
        },
        gate=check_gate.observe, maintenance=check_gate.authorize,
        settled=lambda **kw: settled.append(True),
    )

    def prepare(operation, name, check, identity, **kw):
        return {"operation_id": identity, "authorization": {"check": check}}

    def self_test(inventory, *, operation_id, timeout_seconds, _dispatch_only, _wait):
        if not _dispatch_only:
            observed.append(operation_id)
        return {"outcome": "passed"}

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", self_test)
    upgrades._run_checks(operation)
    expected = ["cpu", "storage"] + ([] if device_source == "cpu_only" else ["gpu"])
    assert [row["check"] for row in check_gate.checks.values()] == expected
    attempts = upgrades.read(tmp_path / "checks.json")
    assert set(attempts) == {"worker:" + check for check in expected}
    assert len(observed) == len(expected)
    assert settled == [True]
    # Continuation retains each check identity instead of preparing replacements.
    monkeypatch.setattr(upgrades, "_prepare_attempt", lambda *a: pytest.fail("duplicate check"))
    upgrades._run_checks(operation)
    assert sorted(observed[len(expected):]) == sorted(observed[:len(expected)])


def test_explicit_deferred_host_retains_checks_and_native_settlement(tmp_path, check_gate, monkeypatch):
    from loom.queue.errors import QueueConflictError

    intent = {
        "operation_id": "selected-qualification",
        "agents": {"busy": {}, "ready": {}},
        "declarations": {
            name: {"resident_profiles": [{"gpu_devices": []}]}
            for name in ("busy", "ready")
        },
        "timeout_seconds": 30,
    }
    observed = []
    operation = SimpleNamespace(
        directory=tmp_path, intent=intent, inventory=object(),
        recheck=lambda: None,
        gate=check_gate.observe, maintenance=check_gate.authorize,
        settled=lambda **kw: (_ for _ in ()).throw(upgrades._Waiting("retained check work")),
    )
    attempts = {"busy:cpu": [{"operation_id": "retained-busy-check"}]}
    upgrades.atomic(tmp_path / "checks.json", attempts)
    upgrades._bind_deferred_checks(operation, ["busy"], "Operator defers busy host")
    receipt = (tmp_path / "deferred-checks.json").read_bytes()
    upgrades._bind_deferred_checks(operation, ["busy"], "Operator defers busy host")
    assert (tmp_path / "deferred-checks.json").read_bytes() == receipt
    with pytest.raises(QueueConflictError, match="exception changed"):
        upgrades._bind_deferred_checks(operation, ["ready"], "Different selection")
    monkeypatch.setattr(upgrades, "_prepare_attempt", lambda operation, name, check, identity, **kw: {
        "operation_id": identity, "authorization": {"check": check},
    })
    monkeypatch.setattr(upgrades, "self_test", lambda inventory, *, operation_id, timeout_seconds, _dispatch_only, _wait: (
        (None if _dispatch_only else observed.append(operation_id)) or {"outcome": "passed"}
    ))
    # Deferral does not cancel the retained check or waive its effects settling.
    with pytest.raises(upgrades._Waiting, match="retained check work"):
        upgrades._run_checks(operation)
    actual = upgrades.read(tmp_path / "checks.json")
    assert actual["busy:cpu"] == attempts["busy:cpu"]
    assert set(actual) == {"busy:cpu", "ready:cpu", "ready:storage"}
    assert "retained-busy-check" not in observed
    assert len(observed) == 2
    assert upgrades._qualification_result(operation) == {
        "qualification": {"state": "partial", "deferred_agents": ["busy"],
                          "reason": "Operator defers busy host"}
    }


@pytest.mark.parametrize("agents,reason", [([], "reason"), (["missing"], "reason"), (["worker"], " ")])
def test_deferred_qualification_requires_selected_consumer_and_reason(tmp_path, agents, reason):
    from loom.queue.errors import QueueConfigError

    operation = SimpleNamespace(directory=tmp_path, intent={"agents": {"worker": {}}})
    with pytest.raises(QueueConfigError):
        upgrades._bind_deferred_checks(operation, agents, reason)
    assert not (tmp_path / "deferred-checks.json").exists()


def test_deferred_qualification_cli_names_host_and_reason():
    from loom.cli.main import build_parser

    command = build_parser().parse_args([
        "fleet", "operation", "defer-checks", "window", "--fleet", "lab",
        "--agent-id", "busy", "--reason", "Operator defers busy host",
    ])
    assert command.operation_id == "window"
    assert command.defer_agents == ["busy"]
    assert command.defer_reason == "Operator defers busy host"


def test_deferred_qualification_does_not_silently_leave_repair_checks_required(tmp_path):
    from loom.queue.errors import QueueConfigError

    repair = tmp_path / "workload-repair"
    repair.mkdir()
    (repair / "intent.json").write_text('{"kind": "workload-upgrade"}')
    operation = SimpleNamespace(directory=tmp_path)
    with pytest.raises(QueueConfigError, match="bound workload repair"):
        upgrades._bind_deferred_checks(operation, ["worker"], "Operator defers checks")
    assert not (tmp_path / "deferred-checks.json").exists()


def test_check_selection_repair_cli_retains_parent_and_explicit_deployment():
    from loom.cli.main import build_parser

    selected = build_parser().parse_args([
        "fleet", "operation", "repair-check-selection", "runtime-window",
        "--fleet", "lab", "--deployment", "/shared/current-checks.json",
    ])
    assert selected.operation_id == "runtime-window"
    assert selected.deployment == Path("/shared/current-checks.json")


@pytest.mark.parametrize("selected_inputs", [False, True])
def test_container_only_preflight_retains_selected_execution(tmp_path, monkeypatch, selected_inputs):
    from dataclasses import replace
    from loom.queue.submitted_execution import SELECTED_INPUT_WORKER_CONTRACT
    from loom.queue.preparation import PreparationSource, PrepareRunRequest
    from tests.integration.queue.test_submitted_container_agents import _fixture

    policy, execution, _ = _fixture(tmp_path)
    if selected_inputs:
        execution = replace(execution, worker_contract=SELECTED_INPUT_WORKER_CONTRACT)
    declarations = {
        "worker": {"resident_profiles": [], "container_policies": [{"policy_id": policy.policy_id}]},
        "coordinator": {"preparation": {"profiles": {
            "submitted": {"container_policy_id": policy.policy_id},
            "old": {"resident_profile_id": "legacy"},
        }}},
    }
    deployment = SimpleNamespace(preparation_profile="submitted",
        source=PreparationSource("shared", "projects", ".", ("probe.yaml",)))
    selected = {"deployment": "selected.json", "config": "probe.yaml", "execution": execution.to_dict()}
    calls = []
    operation = SimpleNamespace(directory=tmp_path, intent={
        "operation_id": "container-qualification", "check_selection": selected,
        "declarations": declarations, "agents": {"worker": {"offer": {"gpu_devices": []}}},
        "hosts": {name: {"expected_root_id": name + "-root"} for name in declarations},
    })

    def capture(name, action, **kwargs):
        calls.append((name, action, kwargs))
        return {"bindings": {"cpu": "captured-cpu", "storage": "captured-storage"}}

    def call_steps(name, action, **kwargs):
        return (yield from upgrades.sshops.rpc((name, action), lambda: capture(name, action, **kwargs)))
    operation.deadline = None
    operation.call_steps = call_steps
    monkeypatch.setattr(upgrades, "load_deployment", lambda path: deployment)
    upgrades._preflight_checks(operation)
    assert len(calls) == 2
    assert set(calls[0][2]["checks"]) == {"cpu", "storage"}
    for raw in calls[0][2]["checks"].values():
        request = PrepareRunRequest.from_dict(raw)
        assert request.execution == execution
        assert request.preparation_profile == "submitted"
        assert request.source == deployment.source
        assert request.input_locations == (() if selected_inputs else None)
    assert calls[1][2]["candidate_declaration"]["resident_profiles"] == []
    from loom.queue.errors import QueueConfigError
    with pytest.raises(QueueConfigError, match="ambiguous"):
        upgrades._check_profile(declarations, "worker", deployment)


def test_cli_accepts_explicit_submitted_check_selection():
    from loom.cli.main import build_parser

    parser = build_parser()
    check = parser.parse_args(["fleet", "self-test", "--fleet", "site", "--execution", "/private/execution.json"])
    assert check.execution == Path("/private/execution.json")
    upgrade = parser.parse_args(["fleet", "upgrade", "--fleet", "site", "--runtime-release", "/private/release.json",
                                 "--check-execution", "/private/execution.json"])
    assert upgrade.check_execution == check.execution
    setup = parser.parse_args(["fleet", "apply", "--fleet", "site", "--operation-id", "add",
                               "--deployment", "/private/deployment.json",
                               "--check-execution", "/private/execution.json",
                               "--grant-operator-access", "existing-operator"])
    assert setup.check_execution == check.execution
    assert setup.grant_operator_access == "existing-operator"


@pytest.mark.optional_dependency
def test_cli_setup_passes_exact_execution_and_explicit_operator_scope(tmp_path, monkeypatch):
    import io
    import json
    from types import SimpleNamespace
    from loom.cli.main import main
    from loom.fleet import configuration, ssh_operations
    from loom.queue.submitted_execution import SubmittedContainerExecution, SubmittedImage

    execution = SubmittedContainerExecution("apptainer", SubmittedImage(
        {"kind": "loom.shared-location", "schema_version": 1, "root_id": "images", "path": "exact.sif"},
        "d" * 64, 25), "/image/python", "resident-submitted-container-v3")
    path = tmp_path / "check.json"
    path.write_text(json.dumps(execution.to_dict()))
    path.chmod(0o600)
    inventory = SimpleNamespace(path=tmp_path / "fleet.json")
    monkeypatch.setattr(configuration, "load_inventory", lambda path: inventory)
    calls = []
    def setup(actual, **kwargs):
        assert actual is inventory
        calls.append(kwargs)
        return {"outcome": "complete"}
    monkeypatch.setattr(ssh_operations, "apply", setup)
    assert main(["fleet", "apply", "--fleet", str(inventory.path), "--operation-id", "add",
                 "--deployment", str(tmp_path / "deployment.json"), "--hosts", "worker2",
                 "--check-execution", str(path), "--grant-operator-access", "operator",
                 "--format", "json"], stdout=io.StringIO()) == 0
    assert calls[0]["hosts"] == ["worker2"]
    selected = calls[0]["check_selection"]
    assert selected["execution"] == execution.to_dict()
    assert selected["execution_file"] == str(path)
    assert selected["grant_operator_access"] == "operator"


def test_resident_promotion_cannot_substitute_submitted_qualification(monkeypatch):
    from loom.queue.errors import QueueConfigError

    monkeypatch.setattr(upgrades, "_environment_files", lambda *args: {})
    with pytest.raises(QueueConfigError, match="installed-profile checks"):
        upgrades.preview(object(), workload_profile="resident", image=Path("/image.sif"),
                         check_execution=object())


def test_workload_preview_qualifies_only_selected_consumers(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from copy import deepcopy
    import json

    from loom.coordinator import CoordinatorOperatorClient
    from loom.fleet import workload_upgrades
    from loom.queue.errors import QueueConfigError

    def write(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path

    for name in ("ca", "cert", "key"):
        write(name, "fixture")
    connection = write("connection.json", {
        "kind": "loom.coordinator-client", "schema_version": 1, "expected_coordinator_id": "coord",
        "transport": {"kind": "https", "url": "https://coordinator.invalid",
                      "server_ca_path": "ca", "certificate_path": "cert", "private_key_path": "key"},
    })
    deployment = write("deployment.json", {
        "kind": "loom.deployment", "schema_version": 1, "connection": str(connection),
        "preparation": {"profile": "prepare", "source": {
            "mode": "shared", "root": "projects", "path": ".", "include": ["."]}},
    })
    source = {"profile_id": "target", "revision": "before"}
    candidate = {**source, "revision": "after"}
    declarations = {
        "coordinator": {"remote_profiles": [source], "preparation": {
            "profiles": {"prepare": {"resident_profile_id": "target"}}}},
        "a": {"resident_profiles": [{"descriptor": source}]},
        "b": {"resident_profiles": [{"descriptor": {"profile_id": "unrelated"}}]},
        "c": {"resident_profiles": [], "container_policies": [{"policy_id": "submitted"}]},
    }
    hosts = {name: {"host": name, "source_release": "one",
                    "native_owner": {"value": {"capabilities": [workload_upgrades.CAPABILITY]}}}
             for name in declarations}
    inventory = SimpleNamespace(runtime_release="one", hosts=[
        SimpleNamespace(name=name, env_file=None) for name in hosts])
    checks = upgrades._checks(inventory, deployment, connection, "check.yaml")
    maintenance = {"hosts": hosts, "declarations": declarations, "release": "one", "checks": checks,
                   "agents": {name: {} for name in ("a", "b", "c")}, "gate": {"settled": False}}
    monkeypatch.setattr(CoordinatorOperatorClient, "from_connection_file", lambda _: nullcontext())
    monkeypatch.setattr(upgrades, "_capable", lambda _: hosts["coordinator"]["native_owner"])
    monkeypatch.setattr(upgrades, "preview", lambda *args, **kwargs: deepcopy(maintenance))
    probed = []

    def probe(requests):
        probed.extend(requests)
        return {name: {"target": {"profile": candidate},
                       "declaration": {"resident_profiles": [{"descriptor": candidate}]}}
                for name in requests}

    monkeypatch.setattr(upgrades.sshops, "_ssh_many", probe)
    options = dict(image=write("image.sif", "fixture"), deployment=deployment, connection=connection)
    with pytest.raises(QueueConfigError, match="no consuming agents"):
        workload_upgrades.preview(inventory, workload_profile="absent", **options)
    plan = workload_upgrades.preview(inventory, workload_profile="target", **options)
    intent = workload_upgrades.bind_intent(
        {"check_selection": checks, "inputs": {}, "agents": plan["agents"], "hosts": plan["hosts"]},
        plan, tmp_path,
    )
    assert probed == ["a"]
    assert set(intent["agents"]) == set(intent["candidates"]) == {"a"}
    assert set(intent["hosts"]) == set(declarations)
    assert plan["gate"] == {"settled": False}
    for name in ("b", "c"):
        assert intent["target_declarations"][name] == declarations[name]
