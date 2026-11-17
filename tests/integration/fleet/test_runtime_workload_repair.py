"""A replaced runtime can qualify a new image without reopening admission."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from loom.coordinator import CoordinatorOperatorClient
from loom.fleet import _workload_host, upgrades, workload_upgrades
from loom.fleet._host import read
from loom.fleet.ssh_operations import apply
from loom.queue.deployment import _load_protected_config
from tests.integration.fleet.test_runtime_upgrade import (
    independent_policy, settle_failed_checks, target_bundle,
)
from tests.integration.fleet.test_ssh_operations import bundle, endpoint, site, write, bind_environments  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _finish(inventory, **options):
    deadline = time.monotonic() + 240
    result = upgrades.upgrade(inventory, operation_id="runtime-window", **options)
    while result["outcome"] == "waiting" and time.monotonic() < deadline:
        time.sleep(0.2)
        result = upgrades.upgrade(inventory, operation_id="runtime-window")
    return result


@pytest.mark.parametrize("initially_drained", [False, True])
def test_workload_repair_preserves_gate_failure_identity_and_replays_native_promotion(
    site, tmp_path, monkeypatch, initially_drained,  # noqa: F811
):
    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    write(inventory.hosts[0].config, authored)
    setup_deadline = time.monotonic() + 240
    setup = apply(inventory, operation_id="setup-repair", issuer=base / "issuer",
                  check_selection=selection)
    while setup["outcome"] == "waiting" and time.monotonic() < setup_deadline:
        time.sleep(0.2)
        setup = apply(inventory, operation_id="setup-repair", resume=True)
    assert setup["outcome"] == "complete", setup
    if initially_drained:
        with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
            independent_policy(operator, "worker", "prior-drain", "drain")
    selected = Path(setup["deployment"])
    target = target_bundle(inventory, tmp_path)
    source = tmp_path / "projects" / "pipeline.yaml"
    source_bytes = source.read_bytes()
    native_before_check = upgrades._Upgrade.native
    injected = []

    def break_check_input(operation, key, request, invoke):
        result = native_before_check(operation, key, request, invoke)
        if key == "close" and not injected:
            # Preflight has passed. Fail the subsequent native check preparation,
            # preserving the post-replacement failure this repair must replay.
            source.write_text("pipeline: [invalid")
            injected.append(True)
        return result

    with monkeypatch.context() as fault:
        fault.setattr(upgrades._Upgrade, "native", break_check_input)
        failed = _finish(inventory, apply=True, runtime_release=target,
                         deployment=selected, connection=Path(setup["operator_connection"]),
                         config=selection["config"])
    assert injected
    assert failed["outcome"] == "blocked" and "retry-check" in failed["reason"], failed
    # Checks advance independently: the first failure does not imply that the
    # other preparation/check has released its claims for workload promotion.
    settle_failed_checks(inventory, "runtime-window")
    parent = inventory.path.parent / "operations/runtime-window"
    original_intent = (parent / "intent.json").read_bytes()
    original_checks = (parent / "checks.json").read_bytes()
    failed_id = read(parent / "checks.json")["worker:cpu"][-1]["operation_id"]
    failure_path = inventory.path.parent / "checks" / failed_id / "result.json"
    failure_bytes = failure_path.read_bytes()
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        gate = dict(operator.observe_maintenance())
    assert gate["state"] == "closed" and gate["maintenance_id"] == "runtime-window"
    source.write_bytes(source_bytes)
    image = tmp_path / "compatible.sif"
    image.write_bytes(b"CPU stand-in; physical acceptance qualifies actual SIF")
    ssh = upgrades.sshops.ssh

    def qualified_cpu(host, request):
        if request["action"] != "workload-probe":
            return ssh(host, request)
        before = dict(_load_protected_config(Path(request["config"]), env_file=request["env_file"])[2])
        after = json.loads(json.dumps(before))
        after["resident_profiles"][0]["descriptor"] = {
            "profile_id": "probe", "revision": "image-" + request["image_sha256"][:24],
        }
        return {
            "source": _workload_host.qualify(request, before),
            "target": _workload_host.qualify(request, after, check_promotion=True),
            "image_sha256": request["image_sha256"], "declaration": after,
        }

    monkeypatch.setattr(upgrades.sshops, "ssh", qualified_cpu)
    native = workload_upgrades.WorkloadUpgrade.native
    lost = []

    def interrupt(operation, key, request, invoke):
        # Every promotion/check still belongs to the original closed gate.
        if request.get("kind") == "promote":
            assert request["promotion"]["maintenance_id"] == "runtime-window"
        result = native(operation, key, request, invoke)
        if key == "worker-promotion" and result["state"] == "applied" and not lost:
            lost.append(True)
            raise upgrades.sshops.SshUnavailable("lost repair promotion reply")
        return result

    monkeypatch.setattr(workload_upgrades.WorkloadUpgrade, "native", interrupt)
    result = upgrades.upgrade(inventory, operation_id="runtime-window",
                              action="repair-workload", workload_profile="probe", image=image)
    deadline = time.monotonic() + 240
    while result["outcome"] == "waiting" and not lost and time.monotonic() < deadline:
        time.sleep(0.2)
        result = upgrades.upgrade(inventory, operation_id="runtime-window")
    assert lost and result["outcome"] == "waiting", result
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        current = operator.observe_maintenance()
        assert current["state"] == "closed"
        assert current["maintenance_id"] == gate["maintenance_id"]
        assert current["intent_digest"] == gate["intent_digest"]
        assert not current["checks"]
    refused = upgrades.upgrade(inventory, operation_id="runtime-window",
                               action="repair-workload", workload_profile="probe",
                               image=tmp_path / "different.sif")
    assert refused["outcome"] == "blocked" and "target changed" in refused["reason"]
    completed = _finish(inventory)
    assert completed["outcome"] == "complete", completed
    assert completed["workload_repair"]
    assert completed["release"]["release_id"] == "candidate-runtime"
    assert completed["deployment"] != str(selected)
    assert set(completed["checks"]) == {"worker:cpu", "worker:storage"}
    assert failed_id not in {
        row["operation_id"] for rows in completed["checks"].values() for row in rows
    }
    assert (parent / "intent.json").read_bytes() == original_intent
    assert (parent / "checks.json").read_bytes() == original_checks
    assert failure_path.read_bytes() == failure_bytes
    with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
        assert operator.observe_maintenance()["state"] == "open"
        assert operator.observe_agent("worker").value["drained"] is initially_drained
    assert _finish(inventory)["checks"] == completed["checks"]
