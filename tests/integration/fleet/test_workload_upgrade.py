"""Workload control composition using real native services and a CPU image stand-in.

Only the SIF readiness probe is replaced; installed acceptance owns actual SIFs.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from loom.fleet import upgrades, workload_upgrades
from loom.fleet._host import read
from loom.fleet.ssh_operations import apply
from loom.coordinator import (
    CoordinatorClient,
    CoordinatorOperatorClient,
    RunRequest,
    CoordinatorClientError,
)
from loom.deployment import load_deployment
from loom.queue.preparation import PrepareRunRequest
from tests.integration.fleet.test_ssh_operations import bundle, endpoint, site, write, bind_environments  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_workload_upgrade_native_promotion_history_versioned_selection_and_replay(
    site,  # noqa: F811
    tmp_path, monkeypatch
):
    from loom.fleet import _workload_host
    from loom.queue.deployment import _load_protected_config

    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    for principal in authored["agent_policy"]["principals"]:
        if principal["role"] == "operator":
            principal["actions"].append("resume")
    write(inventory.hosts[0].config, authored)
    setup = apply(
        inventory,
        operation_id="setup-workload",
        issuer=base / "issuer",
        check_selection=selection,
    )
    assert setup["outcome"] == "complete", setup
    old_selection = Path(setup["deployment"])
    old_bytes = old_selection.read_bytes()
    selected = load_deployment(old_selection)
    assert selected.connection is not None
    with CoordinatorClient.from_connection_file(selected.connection) as client:
        old_request = RunRequest(
            PrepareRunRequest(
                "old-work",
                "old-work",
                selected.source,
                selection["config"],
                selected.preparation_profile,
            ),
            "old-work",
        )
        client.start_run(old_request)
        old = client.observe_run("old-work", timeout_seconds=60)
        assert old.admission is not None and old.admission.state.value == "SUCCEEDED"
    image = tmp_path / "candidate.sif"
    image.write_bytes(b"CPU fixture; installed owner qualifies two real SIFs")
    ssh = upgrades.sshops.ssh

    def qualified_cpu(host, request):
        if request["action"] != "workload-probe":
            return ssh(host, request)
        before = dict(_load_protected_config(Path(request["config"]), env_file=request["env_file"])[2])
        after = json.loads(json.dumps(before))
        after["resident_profiles"][0]["descriptor"] = {
            "profile_id": "probe",
            "revision": "image-" + request["image_sha256"][:24],
        }
        return {
            "source": _workload_host.qualify(request, before),
            "target": _workload_host.qualify(request, after),
            "image_sha256": request["image_sha256"],
            "declaration": after,
        }

    monkeypatch.setattr(upgrades.sshops, "ssh", qualified_cpu)
    options = {
        "workload_profile": "probe",
        "image": image,
        "deployment": old_selection,
        "connection": Path(setup["operator_connection"]),
        "config": selection["config"],
    }
    plan = upgrades.preview(inventory, **options)
    assert plan["gate"]["state"] == "open"
    assert old_selection.read_bytes() == old_bytes
    native = workload_upgrades.WorkloadUpgrade.native
    lost = []

    def interrupt(operation, key, request, invoke):
        result = native(operation, key, request, invoke)
        if key == "worker-promotion" and result["state"] == "applied" and not lost:
            lost.append(True)
            raise upgrades.sshops.SshUnavailable("lost applied promotion response")
        return result

    monkeypatch.setattr(workload_upgrades.WorkloadUpgrade, "native", interrupt)
    original_source = tmp_path / "projects" / "pipeline.yaml"
    original_bytes = original_source.read_bytes()
    original_source.write_text("pipeline: [invalid")
    result = upgrades.upgrade(
        inventory, operation_id="workload-window", apply=True, **options
    )
    deadline = time.monotonic() + 240
    while result["outcome"] == "waiting" and time.monotonic() < deadline:
        time.sleep(0.2)
        result = upgrades.upgrade(inventory, operation_id="workload-window")
    assert result["outcome"] == "blocked" and "explicit operation retry-check" in result["reason"], json.dumps(result)
    attempts = read(inventory.path.parent / "operations/workload-window/checks.json")
    failed = attempts["worker:cpu"][-1]["operation_id"]
    failed_path = inventory.path.parent / "checks" / failed / "result.json"
    retained_failure = failed_path.read_bytes()
    original_source.write_bytes(original_bytes)
    assert upgrades.upgrade(inventory, operation_id="workload-window")["outcome"] == "blocked"
    result = upgrades.upgrade(inventory, operation_id="workload-window", action="retry-check",
                              failed_check=failed, new_check="workload-successor")
    deadline = time.monotonic() + 180
    while result["outcome"] == "waiting" and time.monotonic() < deadline:
        time.sleep(.2)
        result = upgrades.upgrade(inventory, operation_id="workload-window")
    assert result["outcome"] == "complete", json.dumps(result)
    assert failed_path.read_bytes() == retained_failure
    assert [item["operation_id"] for item in result["checks"]["worker:cpu"]] == [failed, "workload-successor"]
    assert lost
    assert result["release"] == plan["release"]
    assert old_selection.read_bytes() == old_bytes
    new = load_deployment(result["deployment"])
    assert new.preparation_profile != selected.preparation_profile
    assert new.source == selected.source and new.connection == selected.connection
    with CoordinatorClient.from_connection_file(selected.connection) as client:
        assert client.observe_run("old-work", wait=False).admission == old.admission
        refused = RunRequest(
            PrepareRunRequest(
                "old-new-work",
                "old-new-work",
                selected.source,
                selection["config"],
                selected.preparation_profile,
            ),
            "old-new-work",
        )
        with pytest.raises(CoordinatorClientError):
            client.start_run(refused)
    with CoordinatorOperatorClient.from_connection_file(
        setup["operator_connection"]
    ) as operator:
        assert operator.observe_maintenance()["state"] == "open"
        assert (
            operator.observe_agent("worker").value["agent_root_id"]
            == plan["agents"]["worker"]["agent_root_id"]
        )
    repeated = upgrades.upgrade(inventory, operation_id="workload-window")
    assert repeated["checks"] == result["checks"]
    assert repeated["deployment"] == result["deployment"]


def test_missing_source_promotion_refuses_before_candidate_or_mutation(
    monkeypatch, tmp_path
):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from loom.queue.errors import QueueConflictError

    monkeypatch.setattr(
        upgrades, "_checks", lambda *args: {"operator_connection": "selected"}
    )
    monkeypatch.setattr(
        CoordinatorOperatorClient,
        "from_connection_file",
        lambda *a: nullcontext(object()),
    )
    monkeypatch.setattr(
        upgrades,
        "_capable",
        lambda _: {"value": {"capabilities": list(upgrades.REQUIRED_CAPABILITIES)}},
    )
    monkeypatch.setattr(
        upgrades,
        "preview",
        lambda *a, **k: pytest.fail(
            "candidate/runtime inspection must follow running source"
        ),
    )
    with pytest.raises(QueueConflictError, match="separate explicit --runtime-release"):
        workload_upgrades.preview(
            SimpleNamespace(hosts=()),
            workload_profile="selected",
            image=tmp_path / "candidate.sif",
        )
