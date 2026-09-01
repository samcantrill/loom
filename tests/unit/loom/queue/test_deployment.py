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
    load_run_inspection_client_config,
)
from loom.queue.errors import QueueConfigError, QueueError, QueueServiceError
from loom.pipeline.executors.slurm import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.ready_stage import SlurmJobPrivateFileProvider
from tests.support.stage29_composition import (
    ConfiguredCpuProvider,
    ResidentProviderFactory,
)


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
        with pytest.raises(QueueServiceError, match="changed without reload"):
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


def test_role_fingerprints_use_path_free_immutable_and_causal_active_values(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_source = _coordinator_config(first_root)
    first = load_coordinator_service_config(first_source)
    payload = json.loads(first_source.read_text(encoding="utf-8"))
    payload["deployment_root"] = "different-deployment"
    payload["run_store_root"] = "different-runs"
    alternate_python = second_root / "python"
    alternate_python.symlink_to(sys.executable)
    payload["embedded_profile"]["project_root"] = str(second_root)
    payload["embedded_profile"]["python_executable"] = str(alternate_python)
    second_source = _write_protected(second_root / "coordinator.yaml", payload)
    second = load_coordinator_service_config(second_source)

    assert (
        second.daemon.resident_worker_launch_profile.python_executable
        == alternate_python.absolute()
    )
    assert second.immutable_fingerprint == first.immutable_fingerprint
    assert second.active_fingerprint == first.active_fingerprint

    payload["embedded_profile"]["cpu_capacity"] = 2
    capacity_source = _write_protected(
        second_root / "coordinator-capacity.yaml", payload
    )
    capacity = load_coordinator_service_config(capacity_source)
    assert capacity.immutable_fingerprint == first.immutable_fingerprint
    assert capacity.active_fingerprint != first.active_fingerprint

    payload["embedded_profile"]["descriptor"]["revision"] = "v2"
    identity_source = _write_protected(
        second_root / "coordinator-identity.yaml", payload
    )
    identity = load_coordinator_service_config(identity_source)
    assert identity.immutable_fingerprint != first.immutable_fingerprint


def test_outbound_fingerprints_exclude_paths_and_include_provider_composition(
    tmp_path: Path,
) -> None:
    source = _agent_config(tmp_path)
    first = load_outbound_agent_service_config(source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload.update(
        {
            "agent_root": "other-agent-root",
            "server_ca_path": "other-ca.crt",
            "certificate_path": "other-agent.crt",
            "private_key_path": "other-agent.key",
        }
    )
    alternate_project = tmp_path / "alternate-project"
    alternate_project.mkdir()
    alternate_python = tmp_path / "alternate-python"
    alternate_python.symlink_to(sys.executable)
    payload["resident_profiles"][0]["project_root"] = str(alternate_project)
    payload["resident_profiles"][0]["python_executable"] = str(alternate_python)
    moved = load_outbound_agent_service_config(
        _write_protected(tmp_path / "agent-moved.yaml", payload)
    )
    assert moved.client.resident_profiles[0].python_executable == (
        alternate_python.absolute()
    )
    assert moved.immutable_fingerprint == first.immutable_fingerprint
    assert moved.active_fingerprint == first.active_fingerprint

    payload["provider_factory"] = {
        "_target_": "tests.support.stage29_composition.ResidentProviderFactory",
        "capacity": 1,
    }
    composed = load_outbound_agent_service_config(
        _write_protected(tmp_path / "agent-composed.yaml", payload)
    )
    assert isinstance(
        composed.client.agent_resource_provider_factory, ResidentProviderFactory
    )
    assert composed.immutable_fingerprint == first.immutable_fingerprint
    assert composed.active_fingerprint != first.active_fingerprint


def test_agent_listener_endpoint_is_immutable_but_credentials_are_reloadable(
    tmp_path: Path,
) -> None:
    source = _coordinator_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["agent_server"] = {
        "host": "localhost",
        "port": 8443,
        "certificate_path": "server.crt",
        "private_key_path": "server.key",
        "client_ca_path": "ca.crt",
        "credential_fingerprints": {"a" * 64: "agent-credential"},
    }
    first = load_coordinator_service_config(
        _write_protected(tmp_path / "coordinator-listener.yaml", payload)
    )

    payload["agent_server"]["credential_fingerprints"]["b" * 64] = (  # type: ignore[index]
        "agent-credential"
    )
    overlap = load_coordinator_service_config(
        _write_protected(tmp_path / "coordinator-listener-overlap.yaml", payload)
    )
    assert overlap.immutable_fingerprint == first.immutable_fingerprint
    assert overlap.active_fingerprint != first.active_fingerprint

    payload["agent_server"]["port"] = 9443  # type: ignore[index]
    moved = load_coordinator_service_config(
        _write_protected(tmp_path / "coordinator-listener-moved.yaml", payload)
    )
    assert moved.immutable_fingerprint != overlap.immutable_fingerprint


def test_coordinator_config_constructs_complete_protected_composition(
    tmp_path: Path,
) -> None:
    source = _coordinator_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["scheduling"] = {
        "priority_resolver": {
            "_target_": "tests.support.stage29_composition.FixedPriorityResolver",
            "priority": 7,
        },
        "components": {
            "planners": [
                {"_target_": "loom.pipeline.runtime.CpuResourcePlanner"}
            ],
            "hard_evaluators": [
                {"_target_": "loom.scheduling.TargetConstraintEvaluator"}
            ],
            "preference_scorers": [
                {
                    "_target_": (
                        "loom.pipeline.runtime.scheduling_preferences."
                        "PackingPreferenceScorer"
                    )
                }
            ],
            "policy": {"_target_": "loom.scheduling.FifoSchedulingPolicy"},
        },
    }
    payload["embedded_agent"] = {
        "providers": [
            {
                "_target_": (
                    "tests.support.stage29_composition.ConfiguredCpuProvider"
                ),
                "capacity": 1,
                "capacity_key": "local-machine:cpu",
            }
        ]
    }
    payload["slurm_profiles"] = [
        {
            "profile_id": "training",
            "partition": "cpu",
            "max_outstanding": 2,
            "runner": {
                "_target_": (
                    "loom.pipeline.executors.slurm.FakeSlurmCommandRunner"
                ),
                "unavailable_commands": [],
            },
            "command_adapter_fingerprint": "fake-slurm-v1",
            "bootstrap_principal_id": "slurm-principal",
            "credential_reference": "slurm-credential",
            "coordinator_endpoint": "https://coordinator.example",
            "project_fingerprint": "project-1",
            "environment_fingerprint": "environment-1",
            "executor_fingerprint": "executor-1",
            "job_private_file_provider": {
                "_target_": (
                    "loom.pipeline.executors.slurm.ready_stage."
                    "SlurmJobPrivateFileProvider"
                ),
                "fixed_path": "/run/loom/capability",
                "descriptor": "test-prolog-v1",
                "helper_argv": ["/bin/true"],
            },
        }
    ]

    service = load_coordinator_service_config(
        _write_protected(tmp_path / "coordinator-complete.yaml", payload)
    )

    assert service.daemon.admission_priority_resolver("file:///run") == 7
    assert len(service.daemon.scheduling_components.planners) == 1
    providers = service.daemon.agent_resource_providers
    assert providers is not None
    assert isinstance(providers[0], ConfiguredCpuProvider)
    assert service.daemon.agent_resource_capacity[0].amount.numerator == 1
    assert len(service.daemon.slurm_profiles) == 1
    profile = service.daemon.slurm_profiles[0]
    assert isinstance(profile.runner, FakeSlurmCommandRunner)
    assert isinstance(profile.job_private_file_provider, SlurmJobPrivateFileProvider)
    assert profile.bootstrap_argv == ("loom", "slurm-bootstrap")


def test_https_authority_schema_resolves_tls_and_service_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _coordinator_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["authority"] = {
        "kind": "https",
        "url": "https://authority.example:9443",
        "service_id": "authority-service",
        "workspace_id": "workspace-1",
        "tls": {
            "ca": "tls/ca.crt",
            "certificate": "tls/coordinator.crt",
            "private_key": "tls/coordinator.key",
        },
    }
    tls_root = tmp_path / "tls"
    tls_root.mkdir()
    for name in ("ca.crt", "coordinator.crt", "coordinator.key"):
        (tls_root / name).write_text("test", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_factory(
        url: str, *, service_id: str, workspace_id: str, tls: object
    ):  # type: ignore[no-untyped-def]
        captured.update(
            {
                "url": url,
                "service_id": service_id,
                "workspace_id": workspace_id,
                "tls": tls,
            }
        )
        return lambda _run_uri: object()

    monkeypatch.setattr(
        "loom.pipeline.stores.coordinator_authority."
        "https_coordinator_authority_factory",
        fake_factory,
    )

    service = load_coordinator_service_config(
        _write_protected(tmp_path / "coordinator-https.yaml", payload)
    )

    assert captured["url"] == "https://authority.example:9443"
    assert captured["service_id"] == "authority-service"
    assert captured["workspace_id"] == "workspace-1"
    tls = captured["tls"]
    assert getattr(tls, "ca_path") == (tmp_path / "tls/ca.crt").resolve()
    assert getattr(tls, "certificate_path") == (
        tmp_path / "tls/coordinator.crt"
    ).resolve()
    assert service.daemon.coordinator_authority_factory is not None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "scheduling",
            {
                "priority_resolver": {
                    "_target_": "tests.support.stage29_composition.FixedPriorityResolver",
                    "priority": 0,
                },
                "components": {
                    "planners": [{"_target_": "builtins.object"}],
                    "hard_evaluators": [
                        {"_target_": "loom.scheduling.TargetConstraintEvaluator"}
                    ],
                    "preference_scorers": [
                        {
                            "_target_": (
                                "loom.pipeline.runtime.scheduling_preferences."
                                "PackingPreferenceScorer"
                            )
                        }
                    ],
                    "policy": {"_target_": "loom.scheduling.FifoSchedulingPolicy"},
                },
            },
            "scheduling composition is invalid",
        ),
        (
            "embedded_agent",
            {"providers": [{"_target_": "builtins.object"}]},
            "providers are invalid",
        ),
    ],
)
def test_protected_composition_rejects_targets_outside_existing_contracts(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    source = _coordinator_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload[field] = value

    with pytest.raises(QueueError, match=message):
        load_coordinator_service_config(
            _write_protected(tmp_path / f"coordinator-invalid-{field}.yaml", payload)
        )


def test_run_inspection_client_config_is_protected_exact_and_path_bound(
    tmp_path: Path,
) -> None:
    source = _write_protected(
        tmp_path / "inspection.yaml",
        {
            "schema_version": 1,
            "kind": "loom.run-inspection-client",
            "url": "https://coordinator.example.test:8443",
            "server_ca_path": "ca.pem",
            "certificate_path": "query.pem",
            "private_key_path": "query.key",
        },
    )
    config = load_run_inspection_client_config(source)
    assert config.client.url == "https://coordinator.example.test:8443"
    assert config.client.server_ca_path == tmp_path / "ca.pem"
    source.chmod(0o644)
    with pytest.raises(QueueConfigError, match="owner-protected"):
        load_run_inspection_client_config(source)


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
