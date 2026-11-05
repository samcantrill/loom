"""Native source publication and replay across the Fleet host receipt boundary."""

import hashlib
import io
import json
import sqlite3
from types import SimpleNamespace

import pytest

from loom.fleet import _host, gpu_policy_repair, ssh_operations, upgrades
from loom.fleet.configuration import protected_directory
from loom.fleet.releases import verify_release
from tests.integration.fleet.test_ssh_operations import bundle  # noqa: F401
from tests.integration.queue.test_gpu_policy_contraction import site, DEVICES, offer  # noqa: F401
from tests.integration.queue.test_maintenance_admission import change, operator

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("interruption", ["source_publication", "native_reload", "host_reply"])
def test_gpu_repair_reconciles_exact_native_publication(site, bundle, tmp_path, monkeypatch, interruption):  # noqa: F811
    source, daemon, agent, session = site
    change(daemon, "close")
    directory = tmp_path / "operation"
    protected_directory(directory)
    admin = tmp_path / "host"
    protected_directory(admin)
    inventory = SimpleNamespace(runtime_release=bundle)
    declaration = json.loads(source.read_text())
    intent = {"operation_id": "repair", "release": verify_release(bundle),
        "hosts": {"coordinator": {"name": "coordinator", "host": "fixture", "config": str(source),
            "root": str(daemon.config.coordinator_root.parent), "env_file": None, "env_sha256": None}},
        "declarations": {"coordinator": declaration},
        "inputs": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}}
    _host.atomic(directory / "intent.json", intent)
    retained = (directory / "intent.json").read_bytes()
    operation = ssh_operations._Operation(inventory, directory, intent)
    interrupted = []
    publish, repair_host = gpu_policy_repair.atomic, gpu_policy_repair.repair_host

    def stop_after_publish(path, value):
        publish(path, value)
        if path == source and interruption == "source_publication" and not interrupted:
            interrupted.append(interruption)
            raise ssh_operations.SshUnavailable("fixture lost publication process")

    def stop_after_reload(*args):
        result = repair_host(*args)
        if interruption == "native_reload" and not interrupted:
            interrupted.append(interruption)
            raise ssh_operations.SshUnavailable("fixture lost native reload reply")
        return result

    def transport(host, request):
        assert host == "fixture"
        with monkeypatch.context() as patch:
            patch.setattr(_host.sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps({**request, "admin": str(admin)}).encode())))
            result = _host.main()
        if interruption == "host_reply" and request["action"] != "receipt" and not interrupted:
            interrupted.append(interruption)
            raise ssh_operations.SshUnavailable("fixture lost completed host reply")
        return result

    monkeypatch.setattr(gpu_policy_repair, "atomic", stop_after_publish)
    monkeypatch.setattr(gpu_policy_repair, "repair_host", stop_after_reload)
    monkeypatch.setattr(ssh_operations, "ssh", transport)
    values = {"agent_id": "agent-a", "gpu_uuids": [DEVICES[0].device_id],
              "coordinator_id": daemon.status().coordinator_id,
              "maintenance_binding": {"operation_id": "maint-1", "target_intent_digest": "intent-maint-1"}}
    with pytest.raises(ssh_operations.SshUnavailable):
        operation.call("coordinator", "repair-gpu-policy", **values)
    result = operation.call("coordinator", "repair-gpu-policy", **values)
    assert result["reload"]["state"] == "applied"
    assert operation.call("coordinator", "repair-gpu-policy", **values) == result
    operation.recheck()
    assert upgrades._Upgrade.accepted_declaration(operation, "coordinator") == result["declaration"]
    offer(agent, session, DEVICES[:1])
    assert interrupted == [interruption]
    assert (directory / "intent.json").read_bytes() == retained
    assert json.loads(source.read_text())["agent_policy"]["agents"][0]["gpu_devices"] == [DEVICES[0].to_dict()]
    assert _host.read(directory / "accepted-inputs.json")[str(source)] == hashlib.sha256(source.read_bytes()).hexdigest()
    with sqlite3.connect(daemon.config.control_database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM scheduling_reloads WHERE state='applied'").fetchone()[0] == 1
    assert operator(daemon).observe_maintenance()["state"] == "closed"
