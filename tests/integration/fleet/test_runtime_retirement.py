"""Combined retirement through installed runtimes, SSH and native services."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import pytest

from loom.coordinator import CoordinatorOperatorClient
from loom.fleet import upgrades
from loom.fleet._host import read
from loom.fleet.ssh_operations import apply
from examples.execution.containers.apptainer_fixture import fake_apptainer
from tests.integration.fleet.test_ssh_operations import bundle, endpoint, site, write, bind_environments  # noqa: F401
from tests.integration.fleet.test_runtime_upgrade import target_bundle, finish
from tests.unit.loom.queue.test_submitted_container_policy import _submitted

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_runtime_retirement_with_deleted_inputs_preserves_identity_and_publication_hold(site, endpoint, bundle, tmp_path, monkeypatch):  # noqa: F811
    from loom.fleet.configuration import load_inventory

    inventory, base, selection = site
    authored = read(inventory.path)
    authored["agents"]["worker2"] = {"host": "worker2", "config": "worker2.json"}
    # An explicit historical bundle qualifies the actual deployment predecessor;
    # the default exercises restart/recovery using this checkout on both sides.
    predecessor = os.environ.get("LOOM_TEST_RETIREMENT_PREDECESSOR")
    if predecessor:
        authored["runtime_release"] = str(Path(predecessor).resolve(strict=True))
    write(inventory.path, authored)
    inventory = load_inventory(inventory.path)
    inventory = bind_environments(inventory)
    # Carry the fake kernel seam into the installed host/supervisor interpreters.
    # Production SSH configuration and production containment are unchanged.
    with (endpoint / "config").open("a") as stream:
        stream.write("\n SendEnv PYTHONPATH\n")
    coordinator = read(inventory.hosts[0].config)
    obsolete = tmp_path / "obsolete-input"
    obsolete.mkdir()
    (obsolete / "challenge").write_bytes(b"obsolete")
    old_root = {"host_path": str(obsolete), "container_path": "/loom/obsolete", "access": "ro",
                "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"obsolete").hexdigest()}}
    submitted = tmp_path / "submitted"
    submitted.mkdir()
    policy, execution, _, _ = _submitted(submitted)
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir(exist_ok=True)
    (snapshots / "challenge").write_bytes(b"snapshots")
    with fake_apptainer() as runtime:
        # The fake launcher executes real workers but has no mount namespace.
        # Physical read-only and isolation checks remain separate acceptance.
        command = Path(runtime["options"]["command"])
        seam = command.parent / "sitecustomize.py"
        with seam.open("a") as stream:
            stream.write("\nfrom loom.queue import shared_execution\nfrom dataclasses import replace\n"
                "_roots = shared_execution.execution_roots\n"
                "shared_execution.execution_roots = lambda roots, *, container: _roots(roots, container=False)\n"
                "_inputs = shared_execution._preparation_input_roots\n"
                "shared_execution._preparation_input_roots = lambda profile, preparation: _inputs(replace(profile, container=None, submitted_execution=None), preparation)\n")
        command.write_text(command.read_text().replace("os.execvpe(args[0], args, os.environ)",
            f"os.environ['PYTHONPATH'] = {str(command.parent)!r}\nos.execvpe(args[0], args, os.environ)"))
        policy = replace(policy, runtime_options=runtime["options"],
            preparation_shared_roots={"projects": snapshots},
            shared_roots={**policy.shared_roots, **coordinator["shared_roots"], "obsolete": old_root,
                "snapshots": {"host_path": str(snapshots), "container_path": "/loom/snapshots", "access": "ro",
                    "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"snapshots").hexdigest()}}})
        execution = replace(execution, python_executable=sys.executable)
        coordinator["shared_roots"] = json.loads(json.dumps(policy.to_dict()["shared_roots"]))
        coordinator["container_capabilities"] = [policy.capability.to_dict()]
        coordinator["agent_policy"]["local_owner"]["actions"].append("maintenance")
        for principal in coordinator["agent_policy"]["principals"]:
            if principal["role"] == "operator":
                principal["actions"].append("resume")
        prep = dict(coordinator["preparation"]["profiles"]["existing-project"])
        prep.pop("resident_profile_id")
        prep["container_policy_id"] = policy.policy_id
        coordinator["preparation"]["profiles"]["submitted"] = prep
        write(inventory.hosts[0].config, coordinator)
        for host in inventory.hosts[1:]:
            agent = read(host.config)
            agent["container_policies"] = [policy.to_dict()]
            agent["registration"]["capabilities"].append("submitted-container-execution-v1")
            agent["resources"] = {"cpu_capacity": 2, "memory_capacity_bytes": 0,
                                  "gpu": {"provider": "nvidia", "devices": "none"}}
            write(host.config, agent)
        setup = apply(inventory, operation_id="setup-retirement", issuer=base / "issuer", check_selection=selection)
        assert setup["outcome"] == "complete", json.dumps(setup)
        from loom.deployment import load_deployment, export_connection_deployment
        submitted_deployment = tmp_path / "submitted-deployment.json"
        export_connection_deployment(replace(load_deployment(setup["deployment"]),
            preparation_profile="submitted"), submitted_deployment)
        with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as client:
            coordinator_id = client.observe_status().owner
            roots = {host.name: client.observe_agent(host.name).value["agent_root_id"] for host in inventory.hosts[1:]}
        candidate = read(inventory.path)
        for host in inventory.hosts:
            declaration = read(host.config)
            if host.name == "coordinator":
                del declaration["shared_roots"]["obsolete"]
                narrowed = replace(policy, shared_roots={key: value for key, value in policy.shared_roots.items() if key != "obsolete"})
                declaration["container_capabilities"] = [narrowed.capability.to_dict()]
                declaration["remote_profiles"] = []
                del declaration["preparation"]["profiles"]["existing-project"]
                entry = candidate["coordinator"]
            else:
                declaration["resident_profiles"] = []
                del declaration["container_policies"][0]["shared_roots"]["obsolete"]
                entry = candidate["agents"][host.name]
            path = host.config.with_name(host.name + "-retirement.json")
            write(path, declaration)
            entry["config"] = str(path)
        candidate_path = write(tmp_path / "candidate-fleet.json", candidate)
        (obsolete / "challenge").unlink()
        obsolete.rmdir()
        options = dict(runtime_release=target_bundle(replace(inventory, runtime_release=bundle), tmp_path), retire_configuration=True,
            workload_inventory=candidate_path, check_execution=execution,
            deployment=submitted_deployment, connection=Path(setup["operator_connection"]),
            config=selection["config"], hold_admission=True)
        host_call = upgrades.sshops.ssh
        interruptions = {("coordinator", "workload-publish"),
                         ("worker", "workload-stopped-retire"),
                         ("worker2", "upgrade-replace")}
        lost = set()

        def lose_applied_reply(host, request):
            result = host_call(host, request)
            boundary = (request.get("name"), request.get("action"))
            if boundary in interruptions and boundary not in lost:
                lost.add(boundary)
                raise upgrades.sshops.SshUnavailable("lost applied retirement reply")
            return result

        monkeypatch.setattr(upgrades.sshops, "ssh", lose_applied_reply)
        result = upgrades.upgrade(inventory, operation_id="retirement", apply=True, **options)
        deadline = time.monotonic() + 240
        while result["outcome"] == "waiting" and not result.get("publication_ready") and time.monotonic() < deadline:
            time.sleep(0.25)
            result = upgrades.upgrade(inventory, operation_id="retirement")
        assert result.get("publication_ready"), json.dumps(result)
        assert lost == interruptions
        with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as client:
            assert client.observe_status().owner == coordinator_id
            assert client.observe_maintenance()["state"] == "closed"
            for name, root in roots.items():
                assert client.observe_agent(name).value["agent_root_id"] == root
        assert not obsolete.exists()
        result = finish(inventory, "retirement", action="release-admission")
        assert result["outcome"] == "complete"
        assert read(inventory.path)["runtime_release"] == str(options["runtime_release"].resolve())
        with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as client:
            assert client.observe_maintenance()["state"] == "open"
        for host in inventory.hosts:
            assert "obsolete-input" not in host.config.read_text()

        # The resulting fleet has no resident profiles. Add a qualified dataset
        # policy without changing the service runtime or any retained selection.
        inventory = load_inventory(inventory.path)
        before_addition = {host.name: read(host.config) for host in inventory.hosts}
        added_root = tmp_path / "configured-dataset"
        added_root.mkdir()
        (added_root / "challenge").write_bytes(b"dataset identity")
        root_binding = {"host_path": str(added_root), "container_path": "/loom/datasets/added",
                        "access": "ro", "challenge": {"path": "challenge",
                        "sha256": hashlib.sha256(b"dataset identity").hexdigest()}}
        from loom.queue._submitted_container_policy import SubmittedContainerPolicy
        retained_policy = SubmittedContainerPolicy.from_dict(before_addition["worker"]["container_policies"][0])
        added_policy = replace(retained_policy, policy_id="added-dataset",
            shared_roots={**retained_policy.shared_roots, "formatted-added": root_binding})
        candidate = read(inventory.path)
        for host in inventory.hosts:
            declaration = read(host.config)
            if host.name == "coordinator":
                declaration["shared_roots"]["formatted-added"] = root_binding
                declaration["container_capabilities"].append(added_policy.capability.to_dict())
                declaration["preparation"]["profiles"]["added"] = {
                    **declaration["preparation"]["profiles"]["submitted"], "container_policy_id": added_policy.policy_id}
                entry = candidate["coordinator"]
            else:
                assert declaration["resident_profiles"] == []
                declaration["container_policies"].append(added_policy.to_dict())
                entry = candidate["agents"][host.name]
            entry["config"] = str(write(host.config.with_name(host.name + "-addition.json"), declaration))
        candidate_path = write(tmp_path / "add-policy-fleet.json", candidate)
        added_deployment = tmp_path / "added-deployment.json"
        export_connection_deployment(replace(load_deployment(submitted_deployment),
            preparation_profile="added"), added_deployment)
        lost.clear()
        interruptions = {("coordinator", "workload-publish"), ("worker", "workload-recover")}
        result = upgrades.upgrade(inventory, operation_id="add-policy", apply=True,
            add_container_policies=True, workload_inventory=candidate_path,
            check_execution=execution, deployment=added_deployment,
            connection=Path(setup["operator_connection"]), config=selection["config"], hold_admission=True)
        deadline = time.monotonic() + 240
        while result["outcome"] == "waiting" and not result.get("publication_ready") and time.monotonic() < deadline:
            time.sleep(0.25)
            result = upgrades.upgrade(inventory, operation_id="add-policy")
        assert result.get("publication_ready"), json.dumps(result)
        assert lost == interruptions
        with CoordinatorOperatorClient.from_connection_file(setup["operator_connection"]) as client:
            assert client.observe_maintenance()["state"] == "closed"
            for name, identity in roots.items():
                assert client.observe_agent(name).value["agent_root_id"] == identity
        assert finish(inventory, "add-policy", action="release-admission")["outcome"] == "complete"
        assert finish(inventory, "add-policy")["outcome"] == "complete"
        for host in inventory.hosts:
            after = read(host.config)
            before = before_addition[host.name]
            if host.name == "coordinator":
                assert all(after["shared_roots"][key] == value for key, value in before["shared_roots"].items())
                assert after["preparation"]["profiles"]["submitted"] == before["preparation"]["profiles"]["submitted"]
            else:
                assert after["resident_profiles"] == []
                assert after["container_policies"][:-1] == before["container_policies"]
