"""Scheduler and retained native owners independently constrain runtime retirement."""
from dataclasses import replace
import json
import sqlite3
from types import SimpleNamespace

import pytest

from loom.fleet import _slurm_retirement, _slurm_upgrade, upgrades
from tests.unit.loom.queue.test_agent_slurm import _task
from tests.unit.loom.queue.test_service_settlement import _agent, _snapshot


@pytest.mark.parametrize("scenario", ["settled", "active", "unresolved", "unavailable"])
def test_slurm_host_preview_is_read_only_and_marks_unknown_separately(tmp_path, monkeypatch, scenario):
    config, profile, stable_id = _agent(tmp_path / "site", rollback=True)
    assert config.agent_root is not None
    executable = tmp_path / "old/environment/bin/loom"
    helper = tmp_path / "old/containment.py"
    from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentHelper

    profile = replace(profile, bootstrap_argv=(str(executable), "slurm-bootstrap"),
                      containment_helper=SlurmContainmentHelper("containment", (str(helper),)))
    raw = {"bootstrap_executable": str(executable), "containment_helper": {"argv": [str(helper)]}}
    monkeypatch.setattr(_slurm_upgrade, "_load_protected_config", lambda *a, **kw: (None, None, {"slurm_profiles": [raw]}, None))
    monkeypatch.setattr(_slurm_upgrade, "_slurm_profile_composition", lambda _: [profile])
    task = _task(profile)["assignment"]
    if scenario in {"active", "unresolved"}:
        with sqlite3.connect(config.agent_root / "slurm.sqlite") as conn:
            conn.execute("INSERT INTO agent_slurm_operations VALUES (?, ?, 0, NULL, 1, 0)",
                         (task["operation_id"], json.dumps(task)))
    def scheduler(_):
        if scenario == "unavailable":
            raise OSError("scheduler unavailable")
        return ([{"job_id": "723", "cluster": profile.cluster, "state": "PENDING", "operation_id": task["operation_id"]}]
                if scenario == "active" else [])
    monkeypatch.setattr(_slurm_upgrade, "_live", scheduler)
    before = _snapshot(config.agent_root)
    facts = _slurm_upgrade.observe({"name": "agent-a", "root": str(config.agent_root),
                                    "config": "/protected/role", "expected_root_id": stable_id})
    assert _snapshot(config.agent_root) == before
    assert facts["status"] == scenario
    assert facts["profiles"][0]["fingerprint"] == profile.configuration_fingerprint
    if scenario == "active":
        assert facts["jobs"] == [{"job_id": "723", "cluster": profile.cluster, "state": "PENDING",
                                  "operation_id": task["operation_id"], "assignment_ids": [task["assignment_id"]],
                                  "paths": sorted([str(helper), str(executable)])}]
    if scenario == "unavailable":
        assert facts["reason"] == "scheduler_unavailable"
    if scenario == "unresolved":
        assert facts["assignments"][0]["job_id"] is None


@pytest.mark.parametrize("consumer", [
    "none", "profile", "resident_peer", "credential_helper", "intermediate_symlink", "process", "job", "recovery",
])
def test_only_verified_superseded_environment_retires(tmp_path, monkeypatch, consumer):
    from loom.fleet import _upgrade_host

    previous = {"descriptor_sha256": "a" * 64}
    target = {"descriptor_sha256": "b" * 64}
    release = tmp_path / "releases" / previous["descriptor_sha256"]
    environment = release / "environment"
    environment.mkdir(parents=True)
    (release / "bundle").mkdir()
    descriptor = release / "bundle/source.json"
    descriptor.write_text("restore")
    (release / "installed.json").write_text(json.dumps(previous))
    (tmp_path / "active.json").write_text(json.dumps(target))
    (tmp_path / "installation.lock").touch()
    (release / "installed.json").chmod(0o600)
    (tmp_path / "active.json").chmod(0o600)
    monkeypatch.setattr(_slurm_retirement, "owner", lambda _: {"owner": "agent", "value": {"ownership": "live"}})
    monkeypatch.setattr(_slurm_retirement, "verify_release", lambda path: previous if path == descriptor else None)
    monkeypatch.setattr(_slurm_retirement, "_process_consumers", lambda _: ["72"] if consumer == "process" else [])
    evidence = {"profiles": [{"paths": [str(environment / "bin/loom")] if consumer == "profile" else []}],
                "other_jobs": [{"job_id": "1"}] if consumer == "job" else []}
    monkeypatch.setattr(_upgrade_host, "_settlement", lambda *a, **k: {"availability": "available", "value": {"settled": True, "slurm": evidence}})
    args = {"admin": str(tmp_path), "source_release": previous, "release": target,
            "source_descriptor_name": descriptor.name, "expected_root_id": "agent",
            "recovery_consumers": ["pending"] if consumer == "recovery" else [],
            "role_paths": [str(environment / "bin/python")] if consumer == "resident_peer" else []}
    if consumer in {"credential_helper", "intermediate_symlink"}:
        old_bin = environment / "bin"
        old_bin.mkdir()
        interpreter = tmp_path / "system-python"
        interpreter.touch()
        (old_bin / "python").symlink_to(interpreter)
        middle = tmp_path / "python-alias"
        middle.symlink_to(old_bin / "python")
        if consumer == "intermediate_symlink":
            args["role_paths"] = [str(middle)]
        else:
            helper = tmp_path / "credentials"
            helper.write_text(f"#!{middle}\n")
            raw = {"job_private_file_provider": {"helper_argv": [str(helper)]}}
            profile = SimpleNamespace(bootstrap_argv=("loom", "slurm-bootstrap"), containment_helper=None)
            evidence["profiles"] = [{"paths": _slurm_upgrade._profile_paths(raw, profile)}]
    result = _slurm_retirement.retire(args)
    if consumer in {"credential_helper", "intermediate_symlink"}:
        assert result["reasons"] == ["installed_profile_reference"]
    assert descriptor.read_text() == "restore"
    assert environment.exists() == (consumer != "none")
    assert result["outcome"] == ("retired" if consumer == "none" else "retained")
    assert _slurm_retirement.retire(args)["outcome"] == result["outcome"]


def test_profile_selection_requires_agents_slurm_route():
    declarations = {
        "coordinator": {"preparation": {"profiles": {
            "other-agent": {"container_policy_id": "p", "execution_route": {"kind": "slurm", "profile": "other"}},
            "selected": {"container_policy_id": "p", "execution_route": {"kind": "slurm", "profile": "cpu"}},
        }}},
        "submit": {"resident_profiles": [], "slurm_profiles": [{"profile_id": "cpu", "submitted_container_policy": {"policy_id": "p"}}]},
    }
    assert upgrades._check_profile(declarations, "submit", SimpleNamespace(preparation_profile="other-agent"),
                                   execution=object()) == "selected"


def test_stopped_slurm_only_agent_replacement_uses_native_store_inventory(tmp_path):
    from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
    from loom.queue.deployment import load_outbound_agent_service_config, service_replacement_guard
    from loom.queue.operations import inspect_native_service
    from tests.unit.loom.queue.test_deployment import _agent_config, _write_protected

    source = _agent_config(tmp_path)
    declaration = json.loads(source.read_text())
    declaration["resident_profiles"] = []
    declaration["slurm_profiles"] = [{
        "profile_id": "cpu", "partition": "cpu", "max_outstanding": 2,
        "runner": {"_target_": "loom.pipeline.executors.slurm.FakeSlurmCommandRunner"},
        "command_adapter_fingerprint": "fake", "bootstrap_principal_id": "bootstrap",
        "credential_reference": "bootstrap-cert", "coordinator_endpoint": "https://localhost",
        "project_fingerprint": "project", "environment_fingerprint": "environment", "executor_fingerprint": "executor",
        "job_private_file_provider": {"_target_": "loom.pipeline.executors.slurm.ready_stage.SlurmJobPrivateFileProvider",
                                      "fixed_path": "/run/capability", "descriptor": "test", "helper_argv": ["/bin/false"]},
    }]
    _write_protected(source, declaration)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    root = service.client.agent_root
    assert root is not None
    root_id = inspect_native_service(root).owner
    assert root_id is not None
    with service_replacement_guard(service, root_id):
        assert not (root / "supervisor").exists()
    with sqlite3.connect(root / "control.sqlite") as conn:
        conn.execute("DELETE FROM root_metadata WHERE key='execution_store_requirements'")
    from loom.queue._agent_process_supervisor import AgentProcessSupervisorError

    with pytest.raises(AgentProcessSupervisorError, match="supervisor state is unavailable"):
        with service_replacement_guard(service, root_id):
            pytest.fail("missing legacy supervisor accepted")


def test_retirement_carries_idle_peer_role_paths_to_every_host(tmp_path):
    class Handoff:
        directory = tmp_path
        intent = {
            "hosts": {name: {"expected_root_id": name, "source_release": {"descriptor_sha256": "a" * 64}}
                      for name in ("coordinator", "batch", "resident")},
            "slurm_roles": ["coordinator", "batch"], "slurm_source_descriptor_name": "release.yaml",
        }

        def gate(self):
            return {"checks": []}

        def settled(self):
            return None

        def accepted_declaration(self, name):
            return {"resident_profiles": [{"python_executable": "/shared/previous/bin/python"}]} if name == "resident" else {}

        def host_observations(self, names, action, **kwargs):
            for name in names:
                yield name, {"availability": "available", "value": {"settled": True, "slurm": {
                    "profiles": [{"paths": ["/shared/bootstrap/worker"]}], "other_jobs": [],
                }}}

        def call_many(self, calls):
            return {name: values["role_paths"] for name, _, values in calls}

    evidence = upgrades._slurm_handoff(Handoff())
    assert list(evidence.values()) == [["/shared/bootstrap/worker", "/shared/previous/bin/python"]] * 3


@pytest.mark.parametrize("mismatch", [False, True])
def test_maintenance_child_binds_exact_slurm_route(tmp_path, monkeypatch, mismatch):
    from loom.pipeline.runtime.options import RunOptions
    from loom.preparation import prepare_child_run
    from loom.queue import _maintenance
    from loom.queue.local_daemon_execution import load_managed_local_intent
    from loom.queue.run import RunRequest
    from tests.integration.queue.test_maintenance_admission import _request
    from tests.integration.queue.test_submitted_preparation import _run

    selected, binding, _ = _run(tmp_path, monkeypatch, slurm=True)
    child = prepare_child_run(selected, binding, "maintenance-child", runtime_options=RunOptions(executor="local"))
    intent = load_managed_local_intent(selected.daemon, child.run_uri)
    assert binding.container_capability is not None
    placement = intent.placements["prepare"]
    profile = selected.daemon.slurm_profiles[0]
    check = {
        "request": RunRequest(replace(_request(), execution=binding.execution), "check").to_dict(),
        "profile": binding.container_capability.to_dict(), "agent_id": "authorized-submitter",
        "pool": "default", "preparation_resources": placement.resource_request.to_dict(), "max_stages": 1,
        "slurm_profile": {"profile_id": profile.profile_id,
                          "fingerprint": "different" if mismatch else profile.configuration_fingerprint},
    }
    if mismatch:
        with pytest.raises(_maintenance.MaintenanceCheckConflict, match="Slurm route conflicts"):
            _maintenance._check_target(check, intent, preparation_child=True)
    else:
        _maintenance._check_target(check, intent, preparation_child=True)
