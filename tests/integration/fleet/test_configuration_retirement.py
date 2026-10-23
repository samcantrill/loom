"""Fleet source publication retains native coordinator retirement authority."""

import hashlib
import json
import shutil

import pytest

from loom.coordinator import CoordinatorClientError, CoordinatorOperatorClient
from loom.fleet import _host, _workload_host
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.errors import QueueConflictError
from tests.unit.loom.queue.test_deployment import _coordinator_config, _write_protected

pytestmark = pytest.mark.integration


def test_coordinator_publication_replays_native_retirement_after_lost_reply(tmp_path, monkeypatch):
    source = _coordinator_config(tmp_path)
    before = json.loads(source.read_text())
    before["local_agent"] = None
    before["agent_policy"]["local_owner"] = {
        "actions": ["scheduling_reload", "maintenance"], "agent_ids": [], "pools": [],
    }
    obsolete = tmp_path / "obsolete"
    obsolete.mkdir()
    (obsolete / "challenge").write_bytes(b"obsolete")
    before["shared_roots"] = {"obsolete": {
        "host_path": str(obsolete), "container_path": "/loom/obsolete", "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"obsolete").hexdigest()},
    }}
    _write_protected(source, before)
    service = load_coordinator_service_config(source)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, trusted_scheduling_loader=lambda:
        load_coordinator_service_config(source, current=service).daemon)
    started = daemon.start()
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    server.start()
    after = {**before, "shared_roots": {}}
    request = {"name": "coordinator", "root": str(service.daemon.deployment_root),
               "config": str(source), "release": {"descriptor_sha256": "runtime"},
               "admin": str(tmp_path), "request_id": "retire", "declaration": after,
               "expected_root_id": started.coordinator_id, "retire_configuration": True,
               "retirement": {"maintenance_id": "upgrade", "maintenance_intent_digest": "selected",
                              "expected_gate_revision": 1}}
    _host.atomic(tmp_path / "service.json", {**request, "expected_root_id": started.coordinator_id})
    publication = tmp_path / "publication"
    publication.mkdir(mode=0o700)
    monkeypatch.setattr(_workload_host, "owner", lambda _: {"owner": started.coordinator_id})
    try:
        with CoordinatorOperatorClient.from_unix_socket(
            daemon.config.endpoint, expected_coordinator_id=started.coordinator_id
        ) as client:
            client.maintenance({"operation_id": "close", "maintenance_id": "upgrade",
                "maintenance_intent_digest": "selected", "action": "close", "expected_revision": 0,
                "check": None})
            (obsolete / "challenge").unlink()
            obsolete.rmdir()
            with pytest.raises(QueueConflictError, match="native root identity changed"):
                _workload_host.coordinator_probe({**request, "expected_root_id": "wrong-owner"})
            _write_protected(source, after)
            with pytest.raises(QueueConflictError, match="accepted scheduling"):
                _workload_host.coordinator_probe(request)
            _write_protected(source, before)
            target = _workload_host.coordinator_probe(request)
            assert json.loads(source.read_text()) == before and not obsolete.exists()
            lost = [True]

            class Connection:
                status = client.status
                describe_connection = client.describe_connection
                observe_maintenance = client.observe_maintenance

                def reload_scheduling(self, value):
                    result = client.reload_scheduling(value)
                    if lost[0]:
                        lost[0] = False
                        raise CoordinatorClientError("unavailable", boundary="transport",
                            operation="operator_scheduling_reload", mutation_outcome="unknown")
                    return result

            monkeypatch.setattr(_host, "coordinator_client", lambda _: (None, Connection()))
            with pytest.raises(CoordinatorClientError):
                _workload_host.publish(request, publication)
            retained = (publication / "reload.json").read_bytes()
            result = _workload_host.publish(request, publication)
            assert result["reload"]["state"] == "applied"
            assert (publication / "reload.json").read_bytes() == retained
            assert json.loads(source.read_text()) == after
            assert daemon.config.active_configuration_fingerprint == target["active"]
            assert not daemon.config.coordinator_shared_roots
            assert client.observe_maintenance()["state"] == "closed"
            assert client.status().coordinator_id == started.coordinator_id
            assert not obsolete.exists()
    finally:
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("interruption", ["before_source", "after_source"])
def test_stopped_publication_resumes_native_intent_then_startup(tmp_path, monkeypatch, interruption):
    from tests.integration.queue.test_maintenance_admission import change, operator
    from tests.integration.fleet.test_releases import bundle
    from loom.fleet import _upgrade_host
    from loom.fleet.releases import verify_release

    source = _coordinator_config(tmp_path)
    before = json.loads(source.read_text())
    before["local_agent"] = None
    before["agent_policy"]["local_owner"] = {
        "actions": ["scheduling_reload", "maintenance"], "agent_ids": [], "pools": [],
    }
    obsolete = tmp_path / "obsolete"
    obsolete.mkdir()
    (obsolete / "challenge").write_bytes(b"old")
    before["shared_roots"] = {"obsolete": {
        "host_path": str(obsolete), "container_path": "/loom/obsolete", "access": "ro",
        "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"old").hexdigest()},
    }}
    _write_protected(source, before)
    service = load_coordinator_service_config(source)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon)
    started = daemon.start()
    try:
        change(daemon, "close")
        gate = operator(daemon).observe_maintenance()
    finally:
        daemon.stop()
    (obsolete / "challenge").unlink()
    obsolete.rmdir()
    after = {**before, "shared_roots": {}}
    request = {"name": "coordinator", "root": str(service.daemon.deployment_root),
        "config": str(source), "release": {"descriptor_sha256": "staged-runtime"},
        "source_release": {"descriptor_sha256": "old-runtime"},
        "admin": str(tmp_path), "request_id": "bootstrap", "declaration": after,
        "stopped_retirement": True, "expected_scheduling_epoch": started.scheduling_epoch,
        "retirement": {"maintenance_id": gate["maintenance_id"],
            "maintenance_intent_digest": gate["intent_digest"], "expected_gate_revision": gate["revision"]}}
    _host.atomic(tmp_path / "service.json", {**request, "release": request["source_release"],
                                           "expected_root_id": started.coordinator_id})
    # The staged runtime can qualify the target before conversion while the
    # canonical source still describes the deleted predecessor input.
    descriptor = bundle(tmp_path / "candidate-runtime")
    release = verify_release(descriptor)
    shutil.copytree(descriptor.parent, tmp_path / "releases" / release["descriptor_sha256"] / "bundle")
    probe = {**request, "expected_root_id": started.coordinator_id,
             "retire_configuration": True}
    target = _workload_host.coordinator_probe(probe)
    facts = _upgrade_host.inspect({**probe, "release": release,
        "descriptor_name": descriptor.name, "required_capabilities": [],
        "retirement_declaration": after, "retirement_target": target})
    assert facts["retirement_target"] == target
    assert facts["compatibility"]["value"]["compatible"]
    assert json.loads(source.read_text()) == before and not obsolete.exists()
    publication = tmp_path / "publication"
    publication.mkdir(mode=0o700)
    atomic = _workload_host.atomic
    lost = []

    def interrupt(path, value):
        if path == source and not lost:
            lost.append(True)
            if interruption == "after_source":
                atomic(path, value)
            raise RuntimeError("publication interrupted")
        atomic(path, value)

    monkeypatch.setattr(_workload_host, "atomic", interrupt)
    with pytest.raises(RuntimeError, match="publication interrupted"):
        _workload_host.publish(request, publication)
    retained = (publication / "reload.json").read_bytes()
    assert json.loads(source.read_text()) == (before if interruption == "before_source" else after)
    with pytest.raises(QueueConflictError, match="binding changed"):
        _workload_host.publish({**request, "stopped_retirement": False,
                               "release": request["source_release"]}, publication)
    result = _workload_host.publish(request, publication)
    assert result["reload"]["state"] == "applying"
    assert result["activation"] == "startup_recovery_required"
    assert (publication / "reload.json").read_bytes() == retained
    assert json.loads(source.read_text()) == after and not obsolete.exists()
    restarted = LocalDaemon(load_coordinator_service_config(source).daemon)
    status = restarted.start()
    try:
        assert status.coordinator_id == started.coordinator_id
        assert operator(restarted).observe_maintenance()["state"] == "closed"
    finally:
        restarted.stop()
    result = _workload_host.publish(request, publication)
    assert result["reload"]["state"] == "applied" and result["activation"] == "applied"
