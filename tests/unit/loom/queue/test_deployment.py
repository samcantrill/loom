"""Protected deployment configuration and atomic publication coverage."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from loom.queue import LocalDaemon
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorError,
    AgentProcessSupervisorService,
)
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
from loom.queue.deployment import (
    _open_outbound_agent,
    load_coordinator_service_config,
    load_outbound_agent_service_config,
)
from loom.queue.errors import QueueConfigError, QueueServiceError


pytestmark = pytest.mark.unit


def test_coordinator_config_is_protected_exact_and_path_bound(tmp_path: Path) -> None:
    source = _coordinator_config(tmp_path)
    source.chmod(0o644)
    with pytest.raises(QueueConfigError, match="owner-protected"):
        load_coordinator_service_config(source)

    source.chmod(0o600)
    service = load_coordinator_service_config(source)
    assert service.daemon.deployment_root == tmp_path / "deployment"
    assert service.daemon.coordinator_root == tmp_path / "deployment/coordinator"
    assert service.daemon.agent_root == tmp_path / "deployment/agent"
    assert service.daemon.deployment_configuration_fingerprint is not None

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    source.write_text(json.dumps(payload), encoding="utf-8")
    source.chmod(0o600)
    with pytest.raises(QueueConfigError, match="must contain exactly"):
        load_coordinator_service_config(source)


def test_coordinator_publication_removes_failed_staging_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = load_coordinator_service_config(_coordinator_config(tmp_path))

    def reject_agent_root(cls: type[LocalDaemon], _root: Path) -> None:
        raise QueueServiceError("injected agent-root failure")

    monkeypatch.setattr(
        LocalDaemon, "initialize_agent_root", classmethod(reject_agent_root)
    )
    with pytest.raises(QueueServiceError, match="injected"):
        LocalDaemon.initialize_deployment(service.daemon)

    assert service.daemon.deployment_root is not None
    assert not service.daemon.deployment_root.exists()
    assert not tuple(tmp_path.glob(".deployment.staging-*"))


def test_coordinator_publication_binds_startup_to_same_config(tmp_path: Path) -> None:
    source = _coordinator_config(tmp_path)
    service = load_coordinator_service_config(source)
    LocalDaemon.initialize_deployment(service.daemon)

    daemon = LocalDaemon(service.daemon)
    daemon.start()
    assert daemon._execution is not None  # noqa: SLF001
    daemon._execution.supervisor.shutdown_for_test()  # noqa: SLF001
    daemon.stop()
    restarted = LocalDaemon(service.daemon)
    restarted.start()
    restarted.stop()

    assert service.daemon.deployment_root is not None
    binding = service.daemon.deployment_root / "deployment-binding.json"
    payload = json.loads(binding.read_text(encoding="utf-8"))
    payload["configuration_fingerprint"] = "0" * 64
    binding.write_text(json.dumps(payload), encoding="utf-8")
    binding.chmod(0o600)
    with pytest.raises(QueueServiceError, match="binding is invalid"):
        LocalDaemon(service.daemon).start()


def test_outbound_agent_publication_is_atomic_and_config_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _agent_config(tmp_path)
    service = load_outbound_agent_service_config(source)

    def reject_supervisor(
        cls: type[AgentProcessSupervisorService],
        _root: Path,
        *,
        configuration: object,
    ) -> object:
        del cls, configuration
        raise AgentProcessSupervisorError("injected supervisor failure")

    with monkeypatch.context() as context:
        context.setattr(
            AgentProcessSupervisorService,
            "initialize_process_free",
            classmethod(reject_supervisor),
        )
        with pytest.raises(QueueServiceError, match="injected"):
            LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    assert service.client.agent_root is not None
    assert not service.client.agent_root.exists()
    assert not tuple(tmp_path.glob(".remote-agent.staging-*"))

    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    client = _open_outbound_agent(service.client)
    try:
        assert client.agent_root_id
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["reconnect_seconds"] = 0.2
        source.write_text(json.dumps(payload), encoding="utf-8")
        source.chmod(0o600)
        changed = load_outbound_agent_service_config(source)
        # Reconnect timing is reloadable and preserves the immutable binding.
        with pytest.raises(QueueServiceError, match="already locked"):
            LocalDaemonAgentHttpClient(changed.client)
    finally:
        if client._supervisor is not None:  # noqa: SLF001
            client._supervisor.shutdown_for_test()  # noqa: SLF001
        client.close()
    restarted = _open_outbound_agent(service.client)
    try:
        assert restarted.agent_root_id
    finally:
        if restarted._supervisor is not None:  # noqa: SLF001
            restarted._supervisor.shutdown_for_test()  # noqa: SLF001
        restarted.close()


def _coordinator_config(tmp_path: Path) -> Path:
    return _write_protected(
        tmp_path / "coordinator.yaml",
        {
            "schema_version": 2,
            "kind": "loom.coordinator-service",
            "deployment_root": "deployment",
            "run_store_root": "runs",
            "machine_id": "local-machine",
            "poll_interval_seconds": 0.01,
            "max_accepted_time_step_seconds": 60,
            "embedded_profile": _resident_profile(tmp_path, "local-profile"),
            "remote_profiles": [],
            "agent_policy": {
                "revision": "policy-1",
                "agents": [],
                "principals": [],
            },
            "agent_server": None,
            "authority": {"kind": "embedded"},
        },
    )


def _agent_config(tmp_path: Path) -> Path:
    return _write_protected(
        tmp_path / "agent.yaml",
        {
            "schema_version": 2,
            "kind": "loom.outbound-agent-service",
            "agent_root": "remote-agent",
            "url": "https://localhost:8443",
            "server_ca_path": "ca.crt",
            "certificate_path": "agent.crt",
            "private_key_path": "agent.key",
            "resident_profiles": [_resident_profile(tmp_path, "remote-profile")],
            "registration": {
                "config_revision": "config-1",
                "inventory_revision": "inventory-1",
                "availability_revision": "availability-1",
                "pools": ["default"],
                "capabilities": ["python"],
            },
            "reconnect_seconds": 0.1,
        },
    )


def _resident_profile(tmp_path: Path, profile_id: str) -> dict[str, object]:
    return {
        "descriptor": {
            "profile_id": profile_id,
            "revision": "v1",
            "project_fingerprint": "project-1",
            "environment_fingerprint": "environment-1",
            "executor_fingerprint": "executor-1",
        },
        "project_root": str(tmp_path),
        "python_executable": sys.executable,
        "cpu_capacity": 1,
        "memory_capacity_bytes": 0,
        "gpu_devices": [],
        "environment": {},
    }


def _write_protected(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return path
