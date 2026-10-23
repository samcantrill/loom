"""Upgrade qualification follows the retained native resource inventory."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.fleet import upgrades


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
    tmp_path, monkeypatch, device_source
):
    # NVIDIA discovery puts devices in the native offer while the authored
    # resident profile keeps an empty legacy GPU declaration.
    device = {"id": "GPU-qualified", "provider": "exclusive"}
    profile = {"gpu_devices": [device] if device_source == "profile" else []}
    agent = {"offer": {"gpu_devices": [device] if device_source == "native_inventory" else []}}
    authorized = []
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
        maintenance=lambda key, action, authorization: authorized.append(authorization),
        settled=lambda: settled.append(True),
    )

    def prepare(operation, name, check, identity):
        return {"operation_id": identity, "authorization": {"check": check}}

    def self_test(inventory, *, operation_id, timeout_seconds, _dispatch_only, _wait):
        if not _dispatch_only:
            observed.append(operation_id)
        return {"outcome": "passed"}

    monkeypatch.setattr(upgrades, "_prepare_attempt", prepare)
    monkeypatch.setattr(upgrades, "self_test", self_test)
    upgrades._run_checks(operation)
    expected = ["cpu", "storage"] + ([] if device_source == "cpu_only" else ["gpu"])
    assert [row["check"] for row in authorized] == expected
    attempts = upgrades.read(tmp_path / "checks.json")
    assert set(attempts) == {"worker:" + check for check in expected}
    assert len(observed) == len(expected)
    assert settled == [True]
    # Continuation retains each check identity instead of preparing replacements.
    monkeypatch.setattr(upgrades, "_prepare_attempt", lambda *a: pytest.fail("duplicate check"))
    upgrades._run_checks(operation)
    assert sorted(observed[len(expected):]) == sorted(observed[:len(expected)])


def test_explicit_deferred_host_retains_checks_and_native_settlement(tmp_path, monkeypatch):
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
        maintenance=lambda *args: None,
        settled=lambda: (_ for _ in ()).throw(upgrades._Waiting("retained check work")),
    )
    attempts = {"busy:cpu": [{"operation_id": "retained-busy-check"}]}
    upgrades.atomic(tmp_path / "checks.json", attempts)
    upgrades._bind_deferred_checks(operation, ["busy"], "Operator defers busy host")
    receipt = (tmp_path / "deferred-checks.json").read_bytes()
    upgrades._bind_deferred_checks(operation, ["busy"], "Operator defers busy host")
    assert (tmp_path / "deferred-checks.json").read_bytes() == receipt
    with pytest.raises(QueueConflictError, match="exception changed"):
        upgrades._bind_deferred_checks(operation, ["ready"], "Different selection")
    monkeypatch.setattr(upgrades, "_prepare_attempt", lambda operation, name, check, identity: {
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


def test_container_only_preflight_retains_selected_execution(tmp_path, monkeypatch):
    from loom.queue.preparation import PreparationSource, PrepareRunRequest
    from tests.integration.queue.test_submitted_container_agents import _fixture

    policy, execution, _ = _fixture(tmp_path)
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

    operation.call = capture
    operation.call_many = lambda batch: calls.extend(batch)
    monkeypatch.setattr(upgrades, "load_deployment", lambda path: deployment)
    upgrades._preflight_checks(operation)
    assert len(calls) == 2
    assert set(calls[0][2]["checks"]) == {"cpu", "storage"}
    for raw in calls[0][2]["checks"].values():
        request = PrepareRunRequest.from_dict(raw)
        assert request.execution == execution
        assert request.preparation_profile == "submitted"
        assert request.source == deployment.source
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


def test_resident_promotion_cannot_substitute_submitted_qualification(monkeypatch):
    from loom.queue.errors import QueueConfigError

    monkeypatch.setattr(upgrades, "_environment_files", lambda *args: {})
    with pytest.raises(QueueConfigError, match="installed-profile checks"):
        upgrades.preview(object(), workload_profile="resident", image=Path("/image.sif"),
                         check_execution=object())
