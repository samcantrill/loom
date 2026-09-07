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
from loom.queue._remote_stage_execution import GpuDeviceDescriptor
from loom.queue.deployment import (
    _open_outbound_agent,
    load_coordinator_service_config,
    load_outbound_agent_service_config,
    load_run_inspection_client_config,
)
from loom.queue.errors import (
    QueueConfigError,
    QueueConflictError,
    QueueError,
    QueueServiceError,
)
from loom.queue.gpu.local import LocalGpuDevice, LocalGpuInventory
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider
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


def test_resident_profile_requires_observed_imports_before_role_use(
    tmp_path: Path,
) -> None:
    source = _coordinator_config(tmp_path)
    payload = _local_agent_payload(source)
    profiles = payload["resident_profiles"]
    assert isinstance(profiles, list)
    profile = profiles[0]
    assert isinstance(profile, dict)
    profile["readiness"] = {"imports": ["missing_resident_package"]}
    _write_local_agent(source, payload)

    with pytest.raises(QueueConfigError, match="packages.required_imports"):
        load_coordinator_service_config(source)


@pytest.mark.optional_dependency
def test_explicit_environment_is_authoritative_and_binds_effective_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _coordinator_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    agent_payload = _local_agent_payload(source)
    profiles = agent_payload["resident_profiles"]
    assert isinstance(profiles, list)
    profile = profiles[0]
    assert isinstance(profile, dict)
    profile["project_root"] = "${oc.env:LOOM_ROLE_PROJECT}"
    profile["cpu_capacity"] = "${oc.env:LOOM_ROLE_CPU}"
    payload["agent_server"] = {
        "host": "localhost",
        "port": "${oc.env:LOOM_ROLE_PORT}",
        "certificate_path": "server.crt",
        "private_key_path": "server.key",
        "client_ca_path": "ca.crt",
        "credential_fingerprints": {"a" * 64: "test-credential"},
    }
    local_reference = payload["local_agent"]
    assert isinstance(local_reference, dict)
    local_reference["env_file"] = "coordinator.env"
    _write_protected(source, payload)
    _write_local_agent(source, agent_payload)
    environment = _write_protected_text(
        tmp_path / "coordinator.env",
        "# machine bindings\n"
        f"LOOM_ROLE_PROJECT={tmp_path}\n"
        "LOOM_ROLE_CPU=1\n"
        "LOOM_ROLE_PORT=8443\n"
        "UNUSED_ROLE_VALUE=first\n",
    )
    monkeypatch.setenv("LOOM_ROLE_PROJECT", "/ambient-project")
    monkeypatch.setenv("LOOM_ROLE_CPU", "9")

    first = load_coordinator_service_config(source, env_file=environment)
    assert first.environment_path == environment.resolve()
    assert first.daemon.resident_worker_launch_profile is not None
    assert first.daemon.resident_worker_launch_profile.project_root == tmp_path
    assert first.daemon.cpu_capacity == 1
    assert first.agent_server is not None
    assert first.agent_server.port == 8443

    _write_protected_text(
        environment,
        "# unrelated comment\n"
        f"LOOM_ROLE_PROJECT={tmp_path}\n"
        "LOOM_ROLE_CPU=1\n"
        "LOOM_ROLE_PORT=08443\n"
        "UNUSED_ROLE_VALUE=second\n",
    )
    unchanged = load_coordinator_service_config(source, env_file=environment)
    assert unchanged.immutable_fingerprint == first.immutable_fingerprint
    assert unchanged.active_fingerprint == first.active_fingerprint

    alternate_project = tmp_path / "alternate-project"
    alternate_project.mkdir()
    _write_protected_text(
        environment,
        f"LOOM_ROLE_PROJECT={alternate_project}\nLOOM_ROLE_CPU=1\nLOOM_ROLE_PORT=8443\n",
    )
    changed_project = load_coordinator_service_config(source, env_file=environment)
    assert changed_project.immutable_fingerprint == first.immutable_fingerprint
    assert changed_project.active_fingerprint == first.active_fingerprint
    assert changed_project.daemon.resident_worker_launch_profile is not None
    assert first.daemon.resident_worker_launch_profile is not None
    assert (
        changed_project.daemon.resident_worker_launch_profile.fingerprint
        != first.daemon.resident_worker_launch_profile.fingerprint
    )

    _write_protected_text(
        environment,
        f"LOOM_ROLE_PROJECT={tmp_path}\nLOOM_ROLE_CPU=2\nLOOM_ROLE_PORT=8443\n",
    )
    changed = load_coordinator_service_config(source, env_file=environment)
    assert changed.immutable_fingerprint == first.immutable_fingerprint
    assert changed.active_fingerprint != first.active_fingerprint
    assert changed.daemon.cpu_capacity == 2


@pytest.mark.optional_dependency
def test_environment_and_composed_source_fail_before_provider_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["provider_factory"] = {"_target_": "builtins.dict"}
    _write_protected(source, payload)
    environment = _write_protected_text(
        tmp_path / "agent.env", "SECRET_TOKEN=top-secret\nSECRET_TOKEN=other-secret\n"
    )
    constructed = False

    def mark_construction(*_args: object, **_kwargs: object) -> object:
        nonlocal constructed
        constructed = True
        return object()

    monkeypatch.setattr("loom.queue.deployment._trusted_target", mark_construction)
    with pytest.raises(
        QueueConfigError, match="deployment environment is invalid"
    ) as exc:
        load_outbound_agent_service_config(source, env_file=environment)

    assert not constructed
    assert "top-secret" not in str(exc.value)
    assert "other-secret" not in str(exc.value)


def test_composed_source_closure_accepts_shared_readable_templates(
    tmp_path: Path,
) -> None:
    source = _coordinator_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    agent_payload = _local_agent_payload(source)
    profiles = agent_payload["resident_profiles"]
    assert isinstance(profiles, list)
    profile = profiles[0]
    assert isinstance(profile, dict)
    included = tmp_path / "local-agent.yaml"
    included.write_text(
        json.dumps({"config": "agent.yaml", "env_file": None}), encoding="utf-8"
    )
    included.chmod(0o644)
    payload["local_agent"] = {"_include_": "local-agent.yaml"}
    _write_protected(source, payload)
    _write_local_agent(source, agent_payload)

    assert load_coordinator_service_config(source).daemon.cpu_capacity == 1

    included.chmod(0o664)
    with pytest.raises(
        QueueConfigError, match="deployment config source must be owner-protected"
    ):
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
    assert daemon._execution.supervisor is not None
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


def test_pure_coordinator_initializes_and_waits_without_local_agent(
    tmp_path: Path,
) -> None:
    source = _coordinator_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["local_agent"] = None
    _write_protected(source, payload)

    service = load_coordinator_service_config(source)
    assert service.daemon.agent_root is None
    assert service.daemon.resident_worker_launch_profile is None
    LocalDaemon.initialize_deployment(service.daemon)
    assert service.daemon.deployment_root is not None
    assert not (service.daemon.deployment_root / "agent").exists()

    daemon = LocalDaemon(service.daemon)
    status = daemon.start()
    try:
        assert status.service_health == "healthy"
        assert status.running_assignments == 0
    finally:
        daemon.stop()


def test_local_agent_rejects_old_schema_before_provider_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _coordinator_config(tmp_path)
    payload = _local_agent_payload(source)
    payload["schema_version"] = 2
    payload["providers"] = {"providers": [{"_target_": "builtins.object"}]}
    _write_local_agent(source, payload)
    constructed = False

    def construct(*_args: object, **_kwargs: object) -> object:
        nonlocal constructed
        constructed = True
        return object()

    monkeypatch.setattr("loom.queue.deployment._trusted_target", construct)
    with pytest.raises(QueueConfigError, match="schema version"):
        load_coordinator_service_config(source)
    assert not constructed
    assert not (tmp_path / "deployment").exists()


def test_local_provider_configuration_participates_in_reload_identity(
    tmp_path: Path,
) -> None:
    source = _coordinator_config(tmp_path)
    payload = _local_agent_payload(source)
    provider = {
        "_target_": "tests.support.stage29_composition.ConfiguredCpuProvider",
        "capacity": 1,
        "capacity_key": "local-machine:cpu",
    }
    payload["providers"] = {"providers": [provider]}
    _write_local_agent(source, payload)
    first = load_coordinator_service_config(source)
    provider["capacity"] = 2
    _write_local_agent(source, payload)
    changed = load_coordinator_service_config(source)
    assert changed.immutable_fingerprint == first.immutable_fingerprint
    assert changed.active_fingerprint != first.active_fingerprint
    agent_source = source.parent / "agent.yaml"
    agent_source.write_text(json.dumps(payload, indent=4, sort_keys=True))
    equivalent = load_coordinator_service_config(source)
    assert equivalent.active_fingerprint == changed.active_fingerprint


def test_local_gpu_binding_change_requires_explicit_reload(tmp_path: Path) -> None:
    source = _coordinator_config(tmp_path)
    payload = _local_agent_payload(source)
    profiles = payload["resident_profiles"]
    assert isinstance(profiles, list)
    profile = profiles[0]
    assert isinstance(profile, dict)
    device = {
        "descriptor": GpuDeviceDescriptor("gpu-a", "synthetic", 1024).to_dict(),
        "binding_value": "0",
    }
    profile["gpu_devices"] = [device]
    _write_local_agent(source, payload)
    first = load_coordinator_service_config(source)
    LocalDaemon.initialize_deployment(first.daemon)
    assert first.daemon.deployment_root is not None
    binding = first.daemon.deployment_root / "deployment-binding.json"
    retained_binding = binding.read_bytes()

    device["binding_value"] = "1"
    _write_local_agent(source, payload)
    changed = load_coordinator_service_config(source)
    assert changed.immutable_fingerprint == first.immutable_fingerprint
    assert changed.active_fingerprint != first.active_fingerprint
    with pytest.raises(QueueConflictError, match="changed without reload"):
        LocalDaemon(changed.daemon).start()
    assert binding.read_bytes() == retained_binding

    daemon = LocalDaemon(first.daemon)
    try:
        assert daemon.start().service_health == "healthy"
    finally:
        if daemon._execution is not None and daemon._execution.supervisor is not None:
            daemon._execution.supervisor.shutdown_for_test()
        daemon.stop()


def test_local_agent_rejects_incompatible_provider(tmp_path: Path) -> None:
    source = _coordinator_config(tmp_path)
    payload = _local_agent_payload(source)
    payload["providers"] = {"providers": [{"_target_": "builtins.object"}]}
    _write_local_agent(source, payload)
    with pytest.raises(QueueServiceError, match="providers are invalid"):
        load_coordinator_service_config(source)


def test_equivalent_local_agent_references_keep_effective_identity(
    tmp_path: Path,
) -> None:
    source = _coordinator_config(tmp_path)
    first = load_coordinator_service_config(source)
    payload = json.loads(source.read_text())
    for reference in ("./agent.yaml", str(tmp_path / "agent.yaml")):
        payload["local_agent"]["config"] = reference
        _write_protected(source, payload)
        equivalent = load_coordinator_service_config(source)
        assert equivalent.daemon.agent_root == first.daemon.agent_root
        assert (
            equivalent.daemon.resident_worker_launch_profile
            == first.daemon.resident_worker_launch_profile
        )
        assert equivalent.immutable_fingerprint == first.immutable_fingerprint
        assert equivalent.active_fingerprint == first.active_fingerprint


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


def test_cpu_only_agent_resources_skip_nvidia_discovery(tmp_path: Path) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["resources"] = {
        "cpu_capacity": 4,
        "memory_capacity_bytes": 0,
        "gpu": {"provider": "nvidia", "devices": "none"},
    }
    source = _write_protected(source, payload)

    service = load_outbound_agent_service_config(source)

    assert service.client.resource_inventory is not None
    assert service.client.capacity_profile.cpu_capacity == 4
    assert service.client.capacity_profile.memory_capacity_bytes == 0
    assert service.client.capacity_profile.gpu_devices == ()


def test_outbound_resource_identity_uses_effective_capacity_values(
    tmp_path: Path,
) -> None:
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["resources"] = {
        "cpu_capacity": 1,
        "memory_capacity_bytes": 0,
        "gpu": {"provider": "nvidia", "devices": "none"},
    }
    _write_protected(source, payload)
    first = load_outbound_agent_service_config(source)

    payload["resources"]["cpu_capacity"] = "01"
    payload["resources"]["memory_capacity_bytes"] = "00"
    _write_protected(source, payload)
    equivalent = load_outbound_agent_service_config(source)
    assert equivalent.client.resource_inventory == first.client.resource_inventory
    assert equivalent.immutable_fingerprint == first.immutable_fingerprint
    assert equivalent.active_fingerprint == first.active_fingerprint

    payload["resources"]["memory_capacity_bytes"] = "1"
    _write_protected(source, payload)
    changed = load_outbound_agent_service_config(source)
    assert changed.immutable_fingerprint == first.immutable_fingerprint
    assert changed.active_fingerprint != first.active_fingerprint


@pytest.mark.parametrize("selection,requires_reload", (("0", True), ("GPU-a", False)))
def test_selected_gpu_restart_distinguishes_index_from_uuid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selection: str,
    requires_reload: bool,
) -> None:
    observed = LocalGpuInventory(
        (
            LocalGpuDevice("GPU-a", "GPU-a", host_index=0, model="a", vram_bytes=1024),
            LocalGpuDevice("GPU-b", "GPU-b", host_index=1, model="b", vram_bytes=1024),
        )
    )
    monkeypatch.setattr(
        NvidiaSmiGpuInventoryProvider, "discover", lambda _self: observed
    )
    source = _agent_config(tmp_path)
    payload = json.loads(source.read_text())
    payload["resources"] = {
        "cpu_capacity": 1,
        "memory_capacity_bytes": 0,
        "gpu": {"provider": "nvidia", "devices": selection},
    }
    _write_protected(source, payload)
    first = load_outbound_agent_service_config(source)
    LocalDaemonAgentHttpClient.initialize_agent_root(first.client)
    client = _open_outbound_agent(first.client)
    try:
        root_id = client.agent_root_id
        client.shutdown_clean()
    finally:
        client.close()

    observed = LocalGpuInventory(
        (
            LocalGpuDevice("GPU-b", "GPU-b", host_index=0, model="b", vram_bytes=1024),
            LocalGpuDevice("GPU-a", "GPU-a", host_index=1, model="a", vram_bytes=1024),
        )
    )
    changed = load_outbound_agent_service_config(source)
    assert changed.immutable_fingerprint == first.immutable_fingerprint
    if requires_reload:
        assert changed.active_fingerprint != first.active_fingerprint
        with pytest.raises(QueueServiceError, match="changed without reload"):
            _open_outbound_agent(changed.client)
    else:
        assert changed.active_fingerprint == first.active_fingerprint
        restarted = _open_outbound_agent(changed.client)
        try:
            assert restarted.agent_root_id == root_id
            restarted.shutdown_clean()
        finally:
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
    agent_payload = _local_agent_payload(first_source)
    profiles = agent_payload["resident_profiles"]
    assert isinstance(profiles, list)
    profile = profiles[0]
    assert isinstance(profile, dict)
    profile["project_root"] = str(second_root)
    profile["python_executable"] = str(alternate_python)
    agent_payload["agent_root"] = "different-deployment/agent"
    _write_local_agent(first_source, agent_payload)
    second_source = _write_protected(second_root / "coordinator.yaml", payload)
    _write_local_agent(second_source, agent_payload)
    second = load_coordinator_service_config(second_source)

    assert second.daemon.resident_worker_launch_profile is not None
    assert (
        second.daemon.resident_worker_launch_profile.python_executable
        == alternate_python.absolute()
    )
    assert second.immutable_fingerprint == first.immutable_fingerprint
    assert second.active_fingerprint == first.active_fingerprint

    profile["cpu_capacity"] = 2
    _write_local_agent(second_source, agent_payload)
    capacity_source = _write_protected(
        second_root / "coordinator-capacity.yaml", payload
    )
    capacity = load_coordinator_service_config(capacity_source)
    assert capacity.immutable_fingerprint == first.immutable_fingerprint
    assert capacity.active_fingerprint != first.active_fingerprint

    descriptor = profile["descriptor"]
    assert isinstance(descriptor, dict)
    descriptor["revision"] = "v2"
    _write_local_agent(second_source, agent_payload)
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
            "planners": [{"_target_": "loom.pipeline.runtime.CpuResourcePlanner"}],
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
    agent_payload = _local_agent_payload(source)
    agent_payload["providers"] = {
        "providers": [
            {
                "_target_": ("tests.support.stage29_composition.ConfiguredCpuProvider"),
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
                "_target_": ("loom.pipeline.executors.slurm.FakeSlurmCommandRunner"),
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

    _write_local_agent(source, agent_payload)
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

    def fake_factory(url: str, *, service_id: str, workspace_id: str, tls: object):  # type: ignore[no-untyped-def]
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
    assert (
        getattr(tls, "certificate_path") == (tmp_path / "tls/coordinator.crt").resolve()
    )
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
    _write_protected(
        tmp_path / "agent.yaml",
        {
            "schema_version": 3,
            "kind": "loom.local-agent-service",
            "agent_root": "deployment/agent",
            "resident_profiles": [_resident_profile(tmp_path, "local-profile")],
        },
    )
    return _write_protected(
        tmp_path / "coordinator.yaml",
        {
            "schema_version": 3,
            "kind": "loom.coordinator-service",
            "deployment_root": "deployment",
            "run_store_root": "runs",
            "machine_id": "local-machine",
            "poll_interval_seconds": 0.01,
            "max_accepted_time_step_seconds": 60,
            "local_agent": {"config": "agent.yaml", "env_file": None},
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
            "schema_version": 3,
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


def _local_agent_payload(source: Path) -> dict[str, object]:
    payload = json.loads((source.parent / "agent.yaml").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_local_agent(source: Path, payload: object) -> Path:
    return _write_protected(source.parent / "agent.yaml", payload)


def _write_protected(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return path


def _write_protected_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path
