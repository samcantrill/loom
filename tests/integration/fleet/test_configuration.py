"""Finite configuration/privacy and native observation boundaries."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from loom.cli.main import main
from loom.deployment import export_connection_deployment, load_deployment
from loom.fleet.configuration import load_inventory
from loom.queue.errors import QueueConflictError, QueueConfigError
from tests.unit.loom.queue.test_deployment import (
    _agent_config,
    _coordinator_config,
    _write_protected,
)

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def cli(*args):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["fleet", *map(str, args), "--format", "json"], stdout=stdout, stderr=stderr
    )
    return code, json.loads(stdout.getvalue())


def inventory(tmp_path):
    coordinator = _coordinator_config(tmp_path)
    payload = json.loads(coordinator.read_text())
    payload["local_agent"] = None
    payload["agent_policy"]["agents"] = [
        {
            "agent_id": "gpu01",
            "credential_id": "gpu-credential",
            "principal_id": "gpu-principal",
            "pools": ["default"],
            "capabilities": ["python"],
            "gpu_devices": [],
        }
    ]
    _write_protected(coordinator, payload)
    _agent_config(tmp_path)
    return _write_protected(
        tmp_path / "fleet.yaml",
        {
            "schema_version": 1,
            "name": "lab",
            "service_manager": "systemd-user",
            "runtime_release": "release.yaml",
            "coordinator": {"host": "control-ssh", "config": coordinator.name},
            "agents": {"gpu01": {"host": "gpu-ssh", "config": "agent.yaml"}},
        },
    )


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode)
        for p in root.rglob("*")
        if p.is_file()
    }


def forbid(*args, **kwargs):
    pytest.fail("read-only Fleet command attempted process/native-state access")


def test_init_repeat_populated_conflict_and_modes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(subprocess, "Popen", forbid)
    monkeypatch.setattr(sqlite3, "connect", forbid)
    code, created = cli("init", "lab")
    assert code == 0 and created["outcome"] == "created"
    path = Path(created["path"])
    assert all(p.stat().st_mode & 0o077 == 0 for p in path.parent.rglob("*"))
    authored = json.loads(path.read_text())
    authored["coordinator"]["host"] = "chosen-alias"
    _write_protected(path, authored)
    before = snapshot(tmp_path)
    assert cli("init", "lab")[1]["outcome"] == "unchanged"
    assert snapshot(tmp_path) == before
    assert cli("init", "lab", "--service-manager", "tmux")[0] != 0
    assert snapshot(tmp_path) == before


def test_init_capture_overlap_refuses_before_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "captured" / "private"))
    code, _ = cli("init", "lab", "--capture-root", tmp_path / "captured")
    assert code != 0 and list(tmp_path.iterdir()) == []


def test_init_world_readable_inventory_and_foreign_destination_refuse(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = Path(cli("init", "lab")[1]["path"])
    path.chmod(0o644)
    before = snapshot(tmp_path)
    assert cli("init", "lab")[0] != 0
    assert snapshot(tmp_path) == before
    path.unlink()
    assert cli("init", "lab")[0] != 0


@pytest.mark.parametrize("command", ["status", "preflight"])
def test_commands_are_inert_and_missing_evidence_is_not_readiness(
    tmp_path, monkeypatch, command
):
    path = inventory(tmp_path)
    from loom.queue import deployment

    monkeypatch.setattr(deployment, "qualify_agent_spec", forbid)
    monkeypatch.setattr(subprocess, "Popen", forbid)
    monkeypatch.setattr(sqlite3, "connect", forbid)
    before = snapshot(tmp_path)
    code, result = cli(command, "--fleet", path)
    assert code == (2 if command == "preflight" else 0)
    assert result["ready"] is False
    assert result["coordinator"]["reason"] == "operator_connection_not_selected"
    assert result["hosts"]["gpu01"]["declaration"]["value"]["qualified"] is False
    assert (
        result["hosts"]["gpu01"]["identity_binding"]["reason"]
        == "agent_certificate_unavailable"
    )
    assert result["hosts"]["gpu01"]["native_owner"]["availability"] == "unavailable"
    assert snapshot(tmp_path) == before


def test_host_selection_and_native_agent_identity_are_not_ssh_aliases(tmp_path):
    path = inventory(tmp_path)
    assert cli("status", "--fleet", path, "--hosts", "gpu-ssh")[0] != 0
    code, result = cli("status", "--fleet", path, "--hosts", "gpu01")
    assert code == 0 and set(result["hosts"]) == {"gpu01"}
    value = json.loads(path.read_text())
    value["agents"]["wrong-id"] = value["agents"].pop("gpu01")
    _write_protected(path, value)
    assert (
        cli("preflight", "--fleet", path)[1]["hosts"]["wrong-id"]["declaration"][
            "availability"
        ]
        == "unavailable"
    )


def test_world_readable_role_is_rejected_without_echoing_secret(tmp_path):
    path = inventory(tmp_path)
    role = tmp_path / "agent.yaml"
    role.chmod(0o644)
    code, result = cli("preflight", "--fleet", path)
    assert code == 2
    assert (
        result["hosts"]["gpu01"]["declaration"]["reason"]
        == "invalid_or_unavailable_native_declaration"
    )
    assert "private_key_path" not in json.dumps(result)


def connection(tmp_path):
    for name in ("ca", "cert", "key"):
        (tmp_path / name).write_text("synthetic inert credential")
        (tmp_path / name).chmod(0o600)
    return _write_protected(
        tmp_path / "connection.json",
        {
            "schema_version": 1,
            "kind": "loom.coordinator-client",
            "expected_coordinator_id": "coordinator-1",
            "transport": {
                "kind": "https",
                "url": "https://localhost:8443",
                "server_ca_path": "ca",
                "certificate_path": "cert",
                "private_key_path": "key",
            },
        },
    )


def selection(tmp_path):
    conn = connection(tmp_path)
    return _write_protected(
        tmp_path / "deployment.json",
        {
            "schema_version": 1,
            "kind": "loom.deployment",
            "connection": conn.name,
            "coordinator": {
                "service_config": "coordinator.yaml",
                "lifetime": "persistent",
                "env_file": None,
            },
            "binding_path": "binding.json",
            "preparation": {
                "source": {
                    "mode": "shared",
                    "root": "project",
                    "path": ".",
                    "include": ["pipeline.yaml"],
                },
                "profile": "remote-profile",
            },
        },
    )


def test_native_export_roundtrip_cannot_bootstrap_and_preserves_old_selection(
    tmp_path, monkeypatch
):
    path = inventory(tmp_path)
    original = selection(tmp_path)
    before = original.read_bytes()
    from loom import deployment

    monkeypatch.setattr(deployment, "_launch", forbid)
    monkeypatch.setattr(subprocess, "Popen", forbid)
    output = tmp_path / "client-v1.json"
    code, result = cli(
        "export-deployment",
        "--fleet",
        path,
        "--hosts",
        "gpu01",
        "--deployment",
        original,
        "--output",
        output,
    )
    assert code == 0, result
    exported = load_deployment(output)
    assert exported.coordinator is exported.agent is exported.binding is None
    assert exported.source == load_deployment(original).source
    assert exported.preparation_profile == "remote-profile"
    assert output.stat().st_mode & 0o777 == 0o600
    assert original.read_bytes() == before
    retained = output.read_bytes()
    with pytest.raises(QueueConflictError):
        export_connection_deployment(load_deployment(original), output)
    assert output.read_bytes() == retained
    with pytest.raises(QueueConfigError):
        load_deployment(tmp_path / "connection.json")
    assert (
        cli(
            "export-deployment",
            "--fleet",
            path,
            "--hosts",
            "gpu01",
            "--deployment",
            original,
            "--output",
            tmp_path / "blocked.json",
            "--capture-root",
            tmp_path,
        )[0]
        != 0
    )
    assert not (tmp_path / "blocked.json").exists()


def test_inventory_rejects_second_resource_policy(tmp_path):
    path = inventory(tmp_path)
    value = json.loads(path.read_text())
    value["agents"]["gpu01"]["cpu_capacity"] = 4
    _write_protected(path, value)
    with pytest.raises(QueueConfigError):
        load_inventory(path)


# Reuse the native owner fixture and the already-qualified wire boundary.
from tests.integration.queue import test_operator_observations as native_observations  # noqa: E402

owner = native_observations.owner
offer = native_observations.offer
dump = native_observations.dump


@pytest.mark.parametrize("case", ["capacity", "occupancy", "unavailable", "old_peer"])
def test_native_observations_keep_identity_freshness_and_failure_codes(
    owner, tmp_path, monkeypatch, case
):
    from loom.coordinator import CoordinatorOperatorClient
    from loom.queue import LocalDaemonSocketServer
    import loom.queue.local_daemon_transport as unix

    daemon, agent, session, _ = owner
    offer(agent, session, busy=case == "occupancy")
    path = inventory(tmp_path)
    value = json.loads(path.read_text())
    value["agents"]["agent-a"] = value["agents"].pop("gpu01")
    _write_protected(path, value)
    conn = connection(tmp_path)
    value = json.loads(conn.read_text())
    value["expected_coordinator_id"] = daemon.status().coordinator_id
    _write_protected(conn, value)
    server = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    if case != "unavailable":
        server.start()
    calls = []
    original = unix.dispatch_control

    def dispatch(daemon, principal, operation, payload, **kwargs):
        calls.append(operation)
        result = dict(original(daemon, principal, operation, payload, **kwargs))
        if case == "old_peer" and operation == "operator_handshake":
            result["capabilities"] = ["daemon-control-v1"]
        return result

    monkeypatch.setattr(unix, "dispatch_control", dispatch)
    monkeypatch.setattr(
        CoordinatorOperatorClient,
        "from_connection_file",
        classmethod(
            lambda cls, path: CoordinatorOperatorClient.from_unix_socket(
                daemon.config.endpoint,
                expected_coordinator_id=daemon.status().coordinator_id,
            )
        ),
    )
    before = dump(daemon.config.control_database)
    try:
        code, result = cli("status", "--fleet", path, "--connection", conn)
        assert code == 0 and result["ready"] is False
        native = result["hosts"]["agent-a"]["native"]
        assert native["owner"] == daemon.status().coordinator_id
        assert native["observed_at"]
        if case in {"capacity", "occupancy"}:
            assert native["availability"] == "available"
            assert native["freshness"] == "current"
            assert native["value"]["agent_root_id"] == "remote-root"
            assert native["value"]["connected"] is True
            if case == "occupancy":
                assert "external_occupancy" in json.dumps(native)
        else:
            assert native["availability"] == "unavailable"
            if case == "old_peer":
                assert (
                    native["value"]["error"]["ids"]["missing_capability"]
                    == "operator-observations-v1"
                )
        assert set(calls) <= {"operator_handshake", "operator_status", "operator_agent"}
        assert dump(daemon.config.control_database) == before
    finally:
        if case != "unavailable":
            server.stop()


@pytest.mark.parametrize("case", ["matched", "wrong_agent", "readable_key"])
def test_native_certificate_binding_and_private_key_permissions(tmp_path, case):
    from tests.support.mutual_tls import certificate_fingerprint, mutual_tls_credentials

    path = inventory(tmp_path)
    credentials = mutual_tls_credentials(tmp_path / "tls")
    agent_path = tmp_path / "agent.yaml"
    payload = json.loads(agent_path.read_text())
    payload.update(
        server_ca_path=str(credentials["ca"].with_suffix(".crt")),
        certificate_path=str(credentials["agent"].with_suffix(".crt")),
        private_key_path=str(credentials["agent"].with_suffix(".key")),
    )
    _write_protected(agent_path, payload)
    coordinator = tmp_path / "coordinator.yaml"
    payload = json.loads(coordinator.read_text())
    payload["agent_server"] = {
        "host": "localhost",
        "port": 8443,
        "certificate_path": str(credentials["server"].with_suffix(".crt")),
        "private_key_path": str(credentials["server"].with_suffix(".key")),
        "client_ca_path": str(credentials["ca"].with_suffix(".crt")),
        "credential_fingerprints": {
            certificate_fingerprint(
                credentials["agent"].with_suffix(".crt")
            ): "wrong-credential" if case == "wrong_agent" else "gpu-credential"
        },
    }
    _write_protected(coordinator, payload)
    if case == "readable_key":
        credentials["agent"].with_suffix(".key").chmod(0o644)
    code, result = cli("preflight", "--fleet", path, "--hosts", "gpu01")
    # No release has been supplied; preflight cannot pass in any case.
    assert code == 2
    row = result["hosts"]["gpu01"]
    if case == "matched":
        assert row["identity_binding"]["value"]["certificate_binding"] == "matched"
        assert row["declaration"]["availability"] == "available"
    else:
        assert row["declaration"]["availability"] == "unavailable"


def test_exported_selection_refuses_native_role_startup(tmp_path, monkeypatch):
    from loom import service_runtime
    from loom.queue.errors import QueueServiceError
    import sys

    original = selection(tmp_path)
    output = export_connection_deployment(
        load_deployment(original), tmp_path / "client.json"
    )
    monkeypatch.setattr(service_runtime, "serve_coordinator", forbid)
    for role in ("coordinator", "agent"):
        monkeypatch.setattr(sys, "argv", ["loom.service_runtime", str(output), role])
        with pytest.raises(QueueServiceError, match="not configured for local startup"):
            service_runtime.main()


def test_setup_plan_requires_complete_selection_before_ssh(tmp_path, monkeypatch):
    path = inventory(tmp_path)
    monkeypatch.setattr(subprocess, "Popen", forbid)
    before = snapshot(tmp_path)
    code, _ = cli("plan", "--fleet", path)
    assert code != 0
    assert snapshot(tmp_path) == before
