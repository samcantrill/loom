"""Controlled native lifetimes; installed cgroup qualification lives separately."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

import pytest

from loom.fleet import _services
from loom.queue.agent_session_transport import (
    AgentTlsClientConfig,
    LocalDaemonAgentHttpClient,
)
from loom.queue._remote_stage_execution import (
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
)
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    SupervisorLaunchState,
    _service_configuration,
)
from loom.queue.errors import QueueConflictError, QueueServiceError
from tests.unit.loom.queue.test_agent_process_supervisor import _named_launch

pytestmark = pytest.mark.integration


def configuration(tmp_path):
    # A real process-owning native profile, with a bounded test worker.
    executable = tmp_path / "held-worker"
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    executable.chmod(0o700)
    profile = ResidentExecutionProfile(
        ResidentProfileDescriptor(
            "fixture", "revision", "project", "environment", "executor"
        ),
        Path.cwd(),
        executable,
    )
    config = AgentTlsClientConfig(
        "https://localhost",
        tmp_path / "ca",
        tmp_path / "crt",
        tmp_path / "key",
        tmp_path / "agent",
        (profile,),
        external_supervisor=True,
    )
    LocalDaemonAgentHttpClient.initialize_agent_root(config)
    return config


def foreground(config):
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from loom.queue._agent_process_supervisor import AgentProcessSupervisorService; "
            "import sys; AgentProcessSupervisorService.serve_initialized(Path(sys.argv[1]))",
            str(config.agent_root),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def connect(config, process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(process.communicate())
        try:
            AgentProcessSupervisorClient(
                config.agent_root,
                _service_configuration(config.agent_root / "supervisor"),
            )
            return LocalDaemonAgentHttpClient(config)
        except (QueueServiceError, AgentProcessSupervisorError) as exc:
            if "endpoint is unavailable" not in str(
                exc
            ) and "already locked" not in str(exc):
                raise
            time.sleep(0.02)
    raise AssertionError("native foreground supervisor did not become ready")


def test_external_supervisor_refuses_missing_endpoint_without_creation(tmp_path):
    config = configuration(tmp_path)
    with pytest.raises(QueueServiceError, match="endpoint is unavailable"):
        LocalDaemonAgentHttpClient(config)
    assert config.agent_root is not None
    assert not (config.agent_root / "supervisor/service.lock").exists()


def test_agent_reconnect_keeps_separate_supervisor_launch_and_owned_worker(tmp_path):
    config = configuration(tmp_path)
    process = foreground(config)
    client = None
    supervisor = None
    worker_fd = None
    try:
        client = connect(config, process)
        supervisor = client._supervisor
        assert supervisor is not None
        launch = replace(
            _named_launch(
                supervisor,
                tmp_path,
                config.resident_profiles[0].launch_profile,
                "worker",
            ),
            agent_id=client.agent_root_id,
        )
        receipt = supervisor.launch(launch)
        assert receipt.state is SupervisorLaunchState.RUNNING
        assert receipt.process_id is not None
        worker_fd = os.pidfd_open(receipt.process_id)
        identity = (
            supervisor.supervisor_id,
            supervisor.continuity_epoch,
            supervisor.service_process_id,
        )
        client.close()
        client = LocalDaemonAgentHttpClient(config)
        assert client._supervisor is not None
        assert (
            client._supervisor.supervisor_id,
            client._supervisor.continuity_epoch,
            client._supervisor.service_process_id,
        ) == identity
        assert client._supervisor.query(launch).process_id == receipt.process_id
        assert not select.select([worker_fd], [], [], 0)[0]
        # Duplicate foreground startup refuses under the native service lock.
        duplicate = foreground(config)
        _, error = duplicate.communicate(timeout=10)
        assert duplicate.returncode and b"already running" in error
        assert supervisor.contain(launch).state is SupervisorLaunchState.CONTAINED
        assert select.select([worker_fd], [], [], 5)[0]
        supervisor._call("shutdown_clean", None)
        assert process.wait(timeout=10) == 0
    finally:
        if supervisor is not None and process.poll() is None:
            supervisor.shutdown_for_test()
        if client is not None:
            client.close()
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=10)
        assert process.returncode is not None
        if worker_fd is not None:
            assert select.select([worker_fd], [], [], 5)[0]
            os.close(worker_fd)


def test_same_boot_supervisor_loss_never_adopts_worker(tmp_path):
    config = configuration(tmp_path)
    process = foreground(config)
    client = connect(config, process)
    supervisor = client._supervisor
    assert supervisor is not None
    launch = replace(
        _named_launch(
            supervisor, tmp_path, config.resident_profiles[0].launch_profile, "worker"
        ),
        agent_id=client.agent_root_id,
    )
    receipt = supervisor.launch(launch)
    assert receipt.process_id is not None
    worker_fd = os.pidfd_open(receipt.process_id)
    try:
        process.kill()
        process.communicate(timeout=10)
        client.close()
        replacement = foreground(config)
        _, error = replacement.communicate(timeout=10)
        assert replacement.returncode and b"requires clean shutdown" in error
        assert not select.select([worker_fd], [], [], 0)[0]
        with pytest.raises(QueueServiceError, match="endpoint is unavailable"):
            LocalDaemonAgentHttpClient(config)
    finally:
        signal.pidfd_send_signal(worker_fd, signal.SIGKILL)
        assert select.select([worker_fd], [], [], 5)[0]
        os.close(worker_fd)
        client.close()


def test_missing_bound_database_is_not_initialized(tmp_path):
    config = configuration(tmp_path)
    assert config.agent_root is not None
    database = config.agent_root / "control.sqlite"
    database.unlink()
    process = foreground(config)
    _, error = process.communicate(timeout=10)
    assert process.returncode and error
    assert not database.exists()


def test_rendered_units_separate_ownership_and_refuse_fallback(tmp_path):
    request = {
        "root": str(tmp_path / "agent"),
        "admin": str(tmp_path / "admin"),
        "config": str(tmp_path / "role with % and $.json"),
        "coordinator_id": "coordinator",
    }
    agent = _services.render(request, "agent")
    supervisor = _services.render(request, "supervisor")
    assert "--external-supervisor" in agent
    assert "After=" + _services.unit_name(request, "supervisor") in agent
    assert "PartOf=" not in supervisor and "BindsTo=" not in supervisor
    assert "Restart=no" in supervisor and "Restart=on-failure" in agent
    assert (
        "KillMode=control-group" in agent and "KillMode=none" not in agent + supervisor
    )
    assert "ExecStartPre=" in agent and "agent-init" not in agent + supervisor
    assert "%%" in agent and "$$" in agent
    from loom.fleet._host import start

    with pytest.raises(QueueConflictError, match="unsupported service backend"):
        start({**request, "service_manager": "automatic"})


def test_runtime_binding_never_enables_linger(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "no\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(QueueConflictError, match="approved linger"):
        _services.prerequisites()
    assert calls == [
        [
            "loginctl",
            "--no-ask-password",
            "show-user",
            str(os.getuid()),
            "--property=Linger",
            "--value",
        ]
    ]


@pytest.mark.optional_dependency
def test_quiesced_migration_preserves_native_identity_and_refuses_live_owner(tmp_path):
    from tests.unit.loom.queue.test_deployment import _agent_config
    from loom.queue.deployment import (
        load_outbound_agent_service_config,
        service_backend_migration_guard,
    )

    service = load_outbound_agent_service_config(_agent_config(tmp_path))
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    client = LocalDaemonAgentHttpClient(service.client)
    root_id = client.agent_root_id
    try:
        with pytest.raises(QueueServiceError, match="already locked"):
            with service_backend_migration_guard(service, root_id):
                pytest.fail("live role was allowed to migrate")
    finally:
        client.shutdown_clean()
        client.close()
    with service_backend_migration_guard(service, root_id):
        from loom.queue.operations import inspect_native_service

        assert service.client.agent_root is not None
        assert inspect_native_service(service.client.agent_root).owner == root_id
    with pytest.raises(QueueConflictError, match="identity changed"):
        with service_backend_migration_guard(service, "wrong-root"):
            pytest.fail("migration rebound native identity")
    assert service.client.agent_root is not None
    database = service.client.agent_root / "journal.sqlite"
    database.unlink()
    with pytest.raises(Exception, match="unavailable|missing"):
        with service_backend_migration_guard(service, root_id):
            pytest.fail("missing execution database was replaced")
    assert not database.exists()


def test_backend_binding_refuses_duplicate_tmux_owner(tmp_path):
    from loom.fleet._host import atomic, start

    admin = tmp_path / "admin"
    admin.mkdir(mode=0o700)
    atomic(admin / "service.json", {"service_manager": "systemd-user"})
    with pytest.raises(QueueConflictError, match="quiesced migration"):
        start({"admin": str(admin), "service_manager": "tmux"})


def test_installed_selection_refuses_missing_config(tmp_path, monkeypatch):
    from tests.fleet_acceptance.test_managed_services import selection

    monkeypatch.setenv("LOOM_RUN_FLEET_ACCEPTANCE", "1")
    monkeypatch.delenv("LOOM_FLEET_ACCEPTANCE_CONFIG", raising=False)
    with pytest.raises(pytest.fail.Exception, match="protected"):
        selection("resident_agent_restart")


def test_foreground_notifies_only_after_native_endpoint_is_ready(tmp_path, monkeypatch):
    import socket
    import tempfile

    config = configuration(tmp_path)
    with tempfile.TemporaryDirectory(prefix="loom-notify-") as directory:
        endpoint = str(Path(directory) / "notify.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listener:
            listener.bind(endpoint)
            listener.settimeout(10)
            monkeypatch.setenv("NOTIFY_SOCKET", endpoint)
            process = foreground(config)
            client = None
            try:
                assert listener.recv(128) == b"READY=1"
                client = LocalDaemonAgentHttpClient(config)
                assert client._supervisor is not None
                client._supervisor._call("shutdown_clean", None)
                assert process.wait(timeout=10) == 0
            finally:
                if client is not None:
                    client.close()
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=10)


def test_systemd_plan_reports_retained_tmux_migration(tmp_path, monkeypatch):
    import hashlib
    from loom.fleet.configuration import Inventory
    from loom.fleet import ssh_operations

    release = tmp_path / "release"
    release.write_text("retained release")
    inventory = Inventory(
        tmp_path / "fleet.json", "selected", release, "systemd-user", ()
    )
    rows = {
        "coordinator": {
            "host": "selected-host",
            "config": str(tmp_path / "coordinator.json"),
        }
    }
    declarations = {
        "coordinator": {
            "agent_server": {
                "certificate_path": "server.crt",
                "private_key_path": "server.key",
                "client_ca_path": "ca.crt",
            }
        }
    }
    monkeypatch.setattr(
        ssh_operations, "_selection", lambda *args: (rows, declarations)
    )
    calls = []

    def inspect(host, request):
        calls.append(request["action"])
        return {
            "service_manager": "tmux",
            "bound_root": True,
            "root_exists": True,
            "installed": {
                "descriptor_sha256": hashlib.sha256(release.read_bytes()).hexdigest()
            },
        }

    monkeypatch.setattr(ssh_operations, "ssh", inspect)
    preview = ssh_operations.plan(inventory)
    assert (
        preview["hosts"]["coordinator"]["conflict"]
        == "service backend change requires explicit quiesced migration"
    )
    assert calls == ["inspect"]


@pytest.mark.optional_dependency
def test_public_foreground_command_binds_loaded_native_role(tmp_path, monkeypatch):
    import socket
    import tempfile
    from tests.unit.loom.queue.test_deployment import _agent_config
    from loom.queue.deployment import load_outbound_agent_service_config

    source = _agent_config(tmp_path)
    service = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    with tempfile.TemporaryDirectory(prefix="loom-role-notify-") as directory:
        endpoint = str(Path(directory) / "notify.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listener:
            listener.bind(endpoint)
            listener.settimeout(15)
            monkeypatch.setenv("NOTIFY_SOCKET", endpoint)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "from loom.cli.main import main; raise SystemExit(main())",
                    "queue",
                    "agent-supervisor-serve",
                    str(source),
                    "--format",
                    "json",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            client = None
            try:
                assert listener.recv(128) == b"READY=1"
                client = LocalDaemonAgentHttpClient(
                    replace(service.client, external_supervisor=True)
                )
                assert client._supervisor is not None
                assert client._supervisor.service_process_id == process.pid
                client._supervisor._call("shutdown_clean", None)
                assert process.wait(timeout=10) == 0
            finally:
                if client is not None:
                    client.close()
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=10)


def test_readiness_blocks_disappeared_profile_mount(tmp_path, monkeypatch):
    from loom.fleet import _host

    mounted = tmp_path / "shared"
    mounted.mkdir()
    declaration = {
        "resident_profiles": [{"shared_roots": {"data": {"host_path": str(mounted)}}}]
    }
    request = {"expected_root_id": "bound-root", "config": str(tmp_path / "role.json")}
    monkeypatch.setattr(_host, "owner", lambda request: {"owner": "bound-root"})
    monkeypatch.setattr(_host, "payload", lambda request: declaration)
    assert _services.readiness(request)["owner"] == "bound-root"
    mounted.rmdir()
    with pytest.raises(
        QueueConflictError, match="required shared resource unavailable"
    ):
        _services.readiness(request)
    assert not mounted.exists()


def test_agent_service_stop_leaves_empty_external_supervisor_owned(tmp_path):
    from threading import Event
    from loom.queue.deployment import (
        OutboundAgentServiceConfig,
        OutboundAgentRegistrationConfig,
        run_outbound_agent_service,
    )

    config = configuration(tmp_path)
    process = foreground(config)
    client = None
    try:
        client = connect(config, process)
        supervisor = client._supervisor
        assert supervisor is not None
        client.close()
        client = None
        stop = Event()
        stop.set()
        service = OutboundAgentServiceConfig(
            config,
            OutboundAgentRegistrationConfig(
                "config", "inventory", "availability", ("default",), ("python",)
            ),
            0.01,
            tmp_path / "agent.json",
            "0" * 64,
            "1" * 64,
        )
        run_outbound_agent_service(service, stop=stop)
        assert process.poll() is None
        status = supervisor._call("status", None)
        assert isinstance(status, dict) and status["service_process_id"] == process.pid
        supervisor._call("shutdown_clean", None)
        assert process.wait(timeout=10) == 0
    finally:
        if client is not None:
            client.close()
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=10)


def test_absent_runtime_reports_prerequisite_without_fallback(monkeypatch):
    runtime = Path('/run/user') / str(os.getuid())
    original_stat = Path.stat
    def absent(path, *args, **kwargs):
        if path == runtime:
            raise FileNotFoundError(str(path))
        return original_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', absent)
    with pytest.raises(QueueConflictError, match='ask administrator to start user@'):
        _services.manager_environment()


@pytest.mark.parametrize("backend, expected", [("systemd-user", True), ("tmux", False)])
def test_completed_setup_reports_retained_boot_capability(
    tmp_path, monkeypatch, backend, expected
):
    from types import SimpleNamespace
    from loom.coordinator import CoordinatorOperatorClient
    from loom.fleet import self_tests, ssh_operations
    from loom.fleet.configuration import Inventory, write_new

    inventory = Inventory(
        tmp_path / "fleet.json", "fixture", tmp_path / "bundle", backend, ()
    )
    intent = {
        "hosts": {
            name: {"service_manager": backend} for name in ("coordinator", "worker")
        },
        "declarations": {
            "coordinator": {},
            "worker": {"url": "https://worker", "registration": {}},
        },
        "issuer": str(tmp_path / "issuer"),
        "fresh_coordinator": False,
        "check_selection": {"config": "probe"},
    }
    operation = ssh_operations._Operation(inventory, tmp_path / "operation", intent)
    receipt = operation.receipts / "worker-initialize"
    receipt.mkdir(mode=0o700)
    write_new(receipt / "receipt.json", {"gpu_devices": []})

    def call(name, action, **values):
        if action == "prepare":
            return {"ca": "ca", "csr": None, "certificate": "certificate"}
        if action == "initialize":
            return {"owner": name + "-root", "gpu_devices": [], "profile": {}}
        return {}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def observe_agent(self, name):
            return SimpleNamespace(value={"offer": {"ready": True}})

    monkeypatch.setattr(operation, "call", call)
    monkeypatch.setattr(operation, "recheck", lambda: None)
    monkeypatch.setattr(operation, "observe", lambda name: {"owner": name + "-root"})
    monkeypatch.setattr(ssh_operations, "_bundle", lambda inventory: {})
    monkeypatch.setattr(ssh_operations, "_fingerprint", lambda certificate: "fingerprint")
    monkeypatch.setattr(
        ssh_operations, "_connections",
        lambda *args: (tmp_path / "deployment", tmp_path / "operator"),
    )
    monkeypatch.setattr(
        CoordinatorOperatorClient, "from_connection_file", lambda path: Client()
    )
    monkeypatch.setattr(
        self_tests, "self_test", lambda *args, **kwargs: {"outcome": "passed"}
    )

    result = ssh_operations._continue(operation)
    assert result["state"] == "complete"
    assert result["boot_start"] is expected
    assert result["identities"] == {
        "coordinator": "coordinator-root", "worker": "worker-root"
    }
