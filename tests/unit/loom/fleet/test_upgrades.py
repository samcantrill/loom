"""Upgrade qualification follows the retained native resource inventory."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from loom.fleet import upgrades


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

    def self_test(inventory, *, operation_id, timeout_seconds, _dispatch_only):
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
    monkeypatch.setattr(upgrades, "self_test", lambda inventory, *, operation_id, timeout_seconds, _dispatch_only: (
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
