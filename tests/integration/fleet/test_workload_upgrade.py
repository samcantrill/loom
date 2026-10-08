"""Workload control composition using real native services and a CPU image stand-in.

Only the SIF readiness probe is replaced; installed acceptance owns actual SIFs.
"""

from __future__ import annotations

import json
import hashlib
import shutil
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
from loom.queue.errors import QueueConflictError
from tests.integration.fleet.test_ssh_operations import bundle, endpoint, site, write, bind_environments  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("promote_source", [False, True], ids=["image", "source-and-image"])
def test_workload_upgrade_native_promotion_history_versioned_selection_and_replay(
    site,  # noqa: F811
    tmp_path, monkeypatch, promote_source
):
    from loom.fleet import _workload_host
    from loom.queue.deployment import _load_protected_config

    inventory, base, selection = site
    inventory = bind_environments(inventory)
    authored = read(inventory.hosts[0].config)
    if promote_source:
        project = tmp_path / "projects"
        (project / "challenge").write_bytes(b"retained project namespace")
        root = {
            "host_path": str(project), "container_path": "/loom/project", "access": "ro",
            "challenge": {"path": "challenge", "sha256": hashlib.sha256((project / "challenge").read_bytes()).hexdigest()},
        }
        authored["shared_roots"]["project"] = root
        worker = read(inventory.hosts[1].config)
        worker["resident_profiles"][0]["shared_roots"]["project"] = root
        from loom.queue.shared_execution import qualifications

        portable = qualifications(authored["shared_roots"])
        authored["remote_profiles"][0]["shared_roots"] = portable
        worker["resident_profiles"][0]["descriptor"]["shared_roots"] = portable
        write(inventory.hosts[1].config, worker)
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
    assert setup["outcome"] == "complete", json.dumps(setup)
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
        after = json.loads(json.dumps(request.get("candidate_declaration", before)))
        after["resident_profiles"][0]["descriptor"] = {
            "profile_id": "probe",
            "revision": "image-" + request["image_sha256"][:24],
        }
        return {
            "source": _workload_host.qualify(request, before),
            "target": _workload_host.qualify(request, after, check_promotion=True),
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
    original_source = tmp_path / "projects" / "pipeline.yaml"
    retained = tmp_path / "retained-project"
    candidate_include = None
    candidate_top = None
    if promote_source:
        shutil.copytree(tmp_path / "projects", retained)
        repository = Path(__file__).resolve().parents[3]
        shutil.copytree(repository / "tests/support", retained / "tests/support")
        shutil.copyfile(repository / "tests/__init__.py", retained / "tests/__init__.py")
        candidate = read(inventory.path)
        for entry in inventory.hosts:
            declaration = read(entry.config)
            if entry.name == "coordinator":
                declaration["shared_roots"]["project"]["host_path"] = str(retained)
                declaration["preparation"]["source_roots"]["projects"]["path"] = str(retained)
                selected_entry = candidate["coordinator"]
            else:
                profile = declaration["resident_profiles"][0]
                profile["shared_roots"]["project"]["host_path"] = str(retained)
                profile["project_root"] = str(retained)
                selected_entry = candidate["agents"][entry.name]
            target = entry.config.with_name(entry.name + "-candidate.json")
            included = write(target.with_name(entry.name + "-included.json"), declaration)
            write(target, {"_include_": included.name})
            if entry.name == "coordinator":
                candidate_include, candidate_top = included, target
            selected_entry["config"] = str(target)
        options["workload_inventory"] = write(tmp_path / "candidate-fleet.json", candidate)
        original_source = retained / "pipeline.yaml"
        assert candidate_include is not None
        valid_candidate = candidate_include.read_bytes()
        invalid = read(candidate_include)
        invalid["shared_roots"]["project"]["host_path"] = "relative-typo"
        write(candidate_include, invalid)
        canonical = {entry.config: entry.config.read_bytes() for entry in inventory.hosts}
        with pytest.raises(QueueConflictError):
            upgrades.upgrade(
                inventory, operation_id="invalid-coordinator", apply=True, **options
            )
        assert all(path.read_bytes() == data for path, data in canonical.items())
        with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
            assert operator.observe_maintenance()["state"] == "open"
        assert not (inventory.path.parent / "operations/invalid-coordinator/intent.json").exists()
        candidate_include.write_bytes(valid_candidate)
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
    original_bytes = original_source.read_bytes()
    original_source.write_text("pipeline: [invalid")
    bind_intent = workload_upgrades.bind_intent
    if promote_source:
        def lose_candidate_storage(intent, plan, directory):
            result = bind_intent(intent, plan, directory)
            (retained / "challenge").rename(retained / "unavailable-challenge")
            return result

        monkeypatch.setattr(workload_upgrades, "bind_intent", lose_candidate_storage)
    result = upgrades.upgrade(
        inventory, operation_id="workload-window", apply=True, **options
    )
    if promote_source:
        assert result["outcome"] == "blocked", result
        assert not lost
        assert not (inventory.path.parent / "operations/workload-window/steps/close/intent.json").exists()
        with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as operator:
            assert operator.observe_maintenance()["state"] == "open"
        (retained / "unavailable-challenge").rename(retained / "challenge")
        monkeypatch.setattr(workload_upgrades, "bind_intent", bind_intent)
        result = upgrades.upgrade(inventory, operation_id="workload-window")
        deadline = time.monotonic() + 240
        while result["outcome"] == "waiting" and not lost and time.monotonic() < deadline:
            time.sleep(0.2)
            result = upgrades.upgrade(inventory, operation_id="workload-window")
        assert result["outcome"] == "waiting" and lost, json.dumps(result)
        candidate_path = options["workload_inventory"]
        retained_bytes = candidate_path.read_bytes()
        candidate_path.write_bytes(retained_bytes + b"\n")
        conflict = upgrades.upgrade(inventory, operation_id="workload-window")
        assert conflict["outcome"] == "blocked" and "input" in conflict["reason"], conflict
        candidate_path.write_bytes(retained_bytes)
        assert candidate_include is not None and candidate_top is not None
        top_bytes = candidate_top.read_bytes()
        retained_include = candidate_include.read_bytes()
        changed = read(candidate_include)
        changed["preparation"]["source_roots"]["projects"]["path"] = str(tmp_path / "edited-source")
        write(candidate_include, changed)
        conflict = upgrades.upgrade(inventory, operation_id="workload-window")
        assert conflict["outcome"] == "blocked" and "composed workload candidate" in conflict["reason"], conflict
        assert candidate_top.read_bytes() == top_bytes
        candidate_include.write_bytes(retained_include)
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
    if promote_source:
        coordinator = read(inventory.hosts[0].config)
        worker = read(inventory.hosts[1].config)["resident_profiles"][0]
        assert coordinator["preparation"]["source_roots"]["projects"]["path"] == str(retained)
        assert coordinator["shared_roots"]["project"]["host_path"] == str(retained)
        assert worker["project_root"] == worker["shared_roots"]["project"]["host_path"] == str(retained)
        assert "source-" in new.preparation_profile
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


@pytest.mark.parametrize("missing", ["profile", "source"])
def test_missing_source_promotion_refuses_before_candidate_or_mutation(
    monkeypatch, tmp_path, missing
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
        lambda _: {"value": {"capabilities": [
            *upgrades.REQUIRED_CAPABILITIES,
            *([workload_upgrades.CAPABILITY] if missing == "source" else []),
        ]}},
    )
    monkeypatch.setattr(
        upgrades,
        "preview",
        lambda *a, **k: pytest.fail(
            "candidate/runtime inspection must follow running source"
        ),
    )
    message = "capable runtime upgrade first" if missing == "source" else "separate explicit --runtime-release"
    with pytest.raises(QueueConflictError, match=message):
        workload_upgrades.preview(
            SimpleNamespace(hosts=()),
            workload_profile="selected",
            image=tmp_path / "candidate.sif",
            workload_inventory=tmp_path / "candidate.json" if missing == "source" else None,
        )
