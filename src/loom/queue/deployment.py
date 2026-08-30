"""Protected, versioned configuration for supported queue role processes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from threading import Event
from typing import cast

from loom.serialization import PlainData, thaw_plain_data

from ._remote_stage_execution import (
    GpuDeviceDescriptor,
    ResidentExecutionProfile,
    ResidentGpuDevice,
    ResidentProfileDescriptor,
)
from .agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    _read_remote_agent_root_id,
    _resident_provider_descriptors,
)
from ._agent_process_supervisor import (
    AgentProcessSupervisorError,
    AgentProcessSupervisorService,
    SupervisorLaunchConfiguration,
)
from .agent_sessions import (
    AgentOffer,
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    TransportPrincipalPolicy,
)
from .errors import QueueConfigError, QueueConflictError, QueueError, QueueServiceError
from .local_daemon import ConfiguredGpuDevice, LocalDaemonConfig


DEPLOYMENT_CONFIG_SCHEMA_VERSION = 1
_OUTBOUND_OFFER_TTL_SECONDS = 30
_OUTBOUND_POLL_WAIT_MS = 5_000


@dataclass(frozen=True, slots=True)
class CoordinatorServiceConfig:
    daemon: LocalDaemonConfig
    agent_server: AgentTlsServerConfig | None
    source_path: Path


@dataclass(frozen=True, slots=True)
class OutboundAgentRegistrationConfig:
    config_revision: str
    inventory_revision: str
    availability_revision: str
    pools: tuple[str, ...]
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutboundAgentServiceConfig:
    client: AgentTlsClientConfig
    registration: OutboundAgentRegistrationConfig
    reconnect_seconds: float
    source_path: Path


def load_coordinator_service_config(path: str | Path) -> CoordinatorServiceConfig:
    source, payload, fingerprint = _load_protected_config(path)
    _exact(
        payload,
        {
            "schema_version",
            "kind",
            "deployment_root",
            "run_store_root",
            "machine_id",
            "poll_interval_seconds",
            "max_accepted_time_step_seconds",
            "embedded_profile",
            "remote_profiles",
            "agent_policy",
            "agent_server",
        },
        "coordinator service config",
    )
    _header(payload, "loom.coordinator-service")
    base = source.parent
    root = _path(payload, "deployment_root", base)
    embedded = _resident_profile(
        _mapping(payload, "embedded_profile"), base, "embedded_profile"
    )
    policy = _agent_policy(_mapping(payload, "agent_policy"))
    server_value = payload["agent_server"]
    server = (
        None
        if server_value is None
        else _agent_server(_mapping_value(server_value, "agent_server"), base)
    )
    remote_values = _sequence(payload, "remote_profiles")
    remote_profiles = tuple(
        _profile_descriptor(_mapping_value(value, f"remote_profiles[{index}]"))
        for index, value in enumerate(remote_values)
    )
    daemon = LocalDaemonConfig(
        coordinator_root=root / "coordinator",
        agent_root=root / "agent",
        run_store_root=_path(payload, "run_store_root", base),
        resident_worker_launch_profile=embedded.launch_profile,
        deployment_root=root,
        deployment_configuration_fingerprint=fingerprint,
        machine_id=_string(payload, "machine_id"),
        cpu_capacity=embedded.cpu_capacity,
        memory_capacity_bytes=embedded.memory_capacity_bytes,
        gpu_devices=tuple(
            ConfiguredGpuDevice(item.descriptor, item.binding_value)
            for item in embedded.gpu_devices
        ),
        poll_interval_seconds=_positive_number(payload, "poll_interval_seconds"),
        max_accepted_time_step_seconds=_positive_number(
            payload, "max_accepted_time_step_seconds"
        ),
        agent_policy=policy,
        remote_profiles=remote_profiles,
    )
    return CoordinatorServiceConfig(daemon, server, source)


def load_outbound_agent_service_config(
    path: str | Path,
) -> OutboundAgentServiceConfig:
    source, payload, fingerprint = _load_protected_config(path)
    _exact(
        payload,
        {
            "schema_version",
            "kind",
            "agent_root",
            "url",
            "server_ca_path",
            "certificate_path",
            "private_key_path",
            "resident_profiles",
            "registration",
            "reconnect_seconds",
        },
        "outbound agent service config",
    )
    _header(payload, "loom.outbound-agent-service")
    base = source.parent
    profiles = tuple(
        _resident_profile(
            _mapping_value(value, f"resident_profiles[{index}]"),
            base,
            f"resident_profiles[{index}]",
        )
        for index, value in enumerate(_sequence(payload, "resident_profiles"))
    )
    if not profiles:
        raise QueueConfigError("resident_profiles must not be empty")
    registration_value = _mapping(payload, "registration")
    _exact(
        registration_value,
        {
            "config_revision",
            "inventory_revision",
            "availability_revision",
            "pools",
            "capabilities",
        },
        "outbound agent registration",
    )
    registration = OutboundAgentRegistrationConfig(
        config_revision=_string(registration_value, "config_revision"),
        inventory_revision=_string(registration_value, "inventory_revision"),
        availability_revision=_string(registration_value, "availability_revision"),
        pools=_strings(registration_value, "pools", non_empty=True),
        capabilities=_strings(registration_value, "capabilities", non_empty=True),
    )
    client = AgentTlsClientConfig(
        url=_string(payload, "url"),
        server_ca_path=_path(payload, "server_ca_path", base),
        certificate_path=_path(payload, "certificate_path", base),
        private_key_path=_path(payload, "private_key_path", base),
        agent_root=_path(payload, "agent_root", base),
        resident_profiles=profiles,
        deployment_configuration_fingerprint=fingerprint,
    )
    return OutboundAgentServiceConfig(
        client,
        registration,
        _positive_number(payload, "reconnect_seconds"),
        source,
    )


def run_outbound_agent_service(
    config: OutboundAgentServiceConfig, *, stop: Event
) -> None:
    """Run one foreground agent role with bounded reconnect and poll loops."""

    probe = _open_outbound_agent(config.client)
    try:
        if stop.is_set():
            try:
                probe.shutdown_clean()
            except (QueueConflictError, QueueServiceError):
                pass
    finally:
        probe.close()
    while not stop.is_set():
        client: LocalDaemonAgentHttpClient | None = None
        try:
            client = _open_outbound_agent(config.client)
            client.resume_retained_work()
            handshake = client.handshake()
            coordinator_epoch = cast(str, handshake["coordinator_epoch"])
            coordinator_id = cast(str, handshake["coordinator_id"])
            session = client.active_session()
            if session is None:
                operation_id = _operation_id(
                    "register",
                    client.agent_root_id,
                    config.registration.config_revision,
                )
                session = client.register(
                    AgentRegistration(
                        operation_id,
                        coordinator_id,
                        coordinator_epoch,
                        client.agent_root_id,
                        config.registration.config_revision,
                        config.registration.inventory_revision,
                        config.registration.availability_revision,
                        config.registration.pools,
                        config.registration.capabilities,
                    )
                )
            elif session.coordinator_epoch != coordinator_epoch:
                session = client.reconcile(
                    session.session_id,
                    coordinator_epoch,
                    idempotency_key=_operation_id(
                        "reconcile", session.session_id, coordinator_epoch
                    ),
                )
            while not stop.is_set():
                client.poll_control(session.session_id)
                session = client.active_session()
                if session is None:
                    raise QueueServiceError("agent session ended without retirement")
                profile = config.client.resident_profiles[0]
                gpu_descriptors = tuple(item.descriptor for item in profile.gpu_devices)
                gpu_atoms = tuple(
                    item.descriptor.capacity_atom()
                    for item in profile.gpu_devices
                    if item.descriptor.healthy
                )
                offer = AgentOffer(
                    session.session_id,
                    session.coordinator_epoch,
                    session.config_revision,
                    session.inventory_revision,
                    session.availability_revision,
                    profile.cpu_capacity,
                    profile.memory_capacity_bytes,
                    _OUTBOUND_OFFER_TTL_SECONDS,
                    _resident_provider_descriptors(profile, session.agent_id),
                    pools=session.pools,
                    resident_profiles=tuple(
                        item.descriptor for item in config.client.resident_profiles
                    ),
                    gpu_devices=gpu_descriptors,
                    gpu_atoms=gpu_atoms,
                )
                # Availability revisions publish a new offer.  An unchanged
                # revision retains that offer identity and only renews its TTL.
                if client.renew_current_offer(session.session_id) is None:
                    client.publish_offer(
                        offer,
                        idempotency_key=_operation_id(
                            "offer",
                            session.session_id,
                            session.coordinator_epoch,
                            session.availability_revision,
                        ),
                    )
                sequence = client.next_poll_sequence(session.session_id)
                client.execute_one(
                    session.session_id,
                    session.availability_revision,
                    sequence=sequence,
                    wait_timeout_ms=_OUTBOUND_POLL_WAIT_MS,
                )
                session = client.active_session()
                if session is None:
                    raise QueueServiceError("agent session ended without retirement")
        except QueueError:
            if stop.is_set():
                return
            stop.wait(config.reconnect_seconds)
        finally:
            if client is not None:
                try:
                    client.shutdown_clean()
                except (QueueConflictError, QueueServiceError):
                    # Retained or uncertain work deliberately keeps its process
                    # owner alive so the next service incarnation can join it.
                    pass
                client.close()


def _operation_id(kind: str, *parts: str) -> str:
    encoded = json.dumps(parts, separators=(",", ":")).encode("utf-8")
    return f"{kind}-{hashlib.sha256(encoded).hexdigest()[:32]}"


def _open_outbound_agent(config: AgentTlsClientConfig) -> LocalDaemonAgentHttpClient:
    try:
        return LocalDaemonAgentHttpClient(config)
    except QueueServiceError as exc:
        if str(exc) != "managed supervisor endpoint is unavailable":
            raise
    if config.agent_root is None:
        raise QueueServiceError("outbound agent root is unavailable")
    configuration = SupervisorLaunchConfiguration(
        _read_remote_agent_root_id(config.agent_root),
        tuple(item.launch_profile for item in config.resident_profiles),
    )
    try:
        AgentProcessSupervisorService.start_empty_initialized(
            config.agent_root, configuration=configuration
        )
    except AgentProcessSupervisorError as exc:
        raise QueueServiceError(str(exc)) from exc
    return LocalDaemonAgentHttpClient(config)


def _load_protected_config(
    path: str | Path,
) -> tuple[Path, Mapping[str, object], str]:
    source = Path(path).resolve()
    if not source.is_file():
        raise QueueConfigError("deployment config is unavailable")
    details = source.stat()
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
        raise QueueConfigError("deployment config must be owner-protected")
    try:
        from weave.load import load_config
    except ModuleNotFoundError as exc:
        raise QueueConfigError(
            "deployment YAML loading requires Loom's weave dependency"
        ) from exc
    try:
        loaded, _source = load_config(source, kind="base", order=0)
    except Exception as exc:  # noqa: BLE001
        raise QueueConfigError("deployment config is invalid") from exc
    if not isinstance(loaded, Mapping):
        raise QueueConfigError("deployment config must be a mapping")
    plain = thaw_plain_data(cast(Mapping[str, PlainData], loaded), path="deployment")
    if not isinstance(plain, dict):
        raise QueueConfigError("deployment config must be a mapping")
    encoded = json.dumps(
        plain, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return (
        source,
        cast(Mapping[str, object], plain),
        hashlib.sha256(encoded).hexdigest(),
    )


def _header(payload: Mapping[str, object], kind: str) -> None:
    version = payload.get("schema_version")
    if version != DEPLOYMENT_CONFIG_SCHEMA_VERSION or isinstance(version, bool):
        raise QueueConfigError("deployment config schema version is unsupported")
    if payload.get("kind") != kind:
        raise QueueConfigError("deployment config kind is invalid")


def _resident_profile(
    value: Mapping[str, object], base: Path, label: str
) -> ResidentExecutionProfile:
    _exact(
        value,
        {
            "descriptor",
            "project_root",
            "python_executable",
            "cpu_capacity",
            "memory_capacity_bytes",
            "gpu_devices",
            "environment",
        },
        label,
    )
    devices: list[ResidentGpuDevice] = []
    for index, item in enumerate(_sequence(value, "gpu_devices")):
        device = _mapping_value(item, f"{label}.gpu_devices[{index}]")
        _exact(
            device,
            {"descriptor", "binding_value"},
            f"{label}.gpu_devices[{index}]",
        )
        devices.append(
            ResidentGpuDevice(
                GpuDeviceDescriptor.from_dict(_mapping(device, "descriptor")),
                _string(device, "binding_value"),
            )
        )
    environment = _mapping(value, "environment")
    if any(not isinstance(item, str) for item in environment.values()):
        raise QueueConfigError(f"{label}.environment values must be strings")
    return ResidentExecutionProfile(
        _profile_descriptor(_mapping(value, "descriptor")),
        _path(value, "project_root", base),
        _path(value, "python_executable", base),
        _positive_int(value, "cpu_capacity"),
        _non_negative_int(value, "memory_capacity_bytes"),
        tuple(devices),
        cast(Mapping[str, str], environment),
    )


def _profile_descriptor(value: Mapping[str, object]) -> ResidentProfileDescriptor:
    try:
        return ResidentProfileDescriptor.from_dict(value)
    except (QueueServiceError, TypeError, ValueError) as exc:
        raise QueueConfigError("resident profile descriptor is invalid") from exc


def _agent_policy(value: Mapping[str, object]) -> AgentPolicyConfig:
    _exact(value, {"revision", "agents", "principals"}, "agent_policy")
    agents: list[AgentPrincipalPolicy] = []
    for index, item in enumerate(_sequence(value, "agents")):
        agent = _mapping_value(item, f"agent_policy.agents[{index}]")
        _exact(
            agent,
            {
                "credential_id",
                "principal_id",
                "agent_id",
                "pools",
                "capabilities",
                "gpu_devices",
            },
            f"agent_policy.agents[{index}]",
        )
        agents.append(
            AgentPrincipalPolicy(
                _string(agent, "credential_id"),
                _string(agent, "principal_id"),
                _string(agent, "agent_id"),
                _strings(agent, "pools", non_empty=True),
                _strings(agent, "capabilities"),
                tuple(
                    GpuDeviceDescriptor.from_dict(
                        _mapping_value(device, "agent GPU descriptor")
                    )
                    for device in _sequence(agent, "gpu_devices")
                ),
            )
        )
    principals: list[TransportPrincipalPolicy] = []
    for index, item in enumerate(_sequence(value, "principals")):
        principal = _mapping_value(item, f"agent_policy.principals[{index}]")
        _exact(
            principal,
            {"credential_id", "principal_id", "role", "actions", "agent_ids", "pools"},
            f"agent_policy.principals[{index}]",
        )
        principals.append(
            TransportPrincipalPolicy(
                _string(principal, "credential_id"),
                _string(principal, "principal_id"),
                _string(principal, "role"),
                _strings(principal, "actions"),
                _strings(principal, "agent_ids"),
                _strings(principal, "pools"),
            )
        )
    return AgentPolicyConfig(
        revision=_string(value, "revision"),
        agents=tuple(agents),
        principals=tuple(principals),
    )


def _agent_server(value: Mapping[str, object], base: Path) -> AgentTlsServerConfig:
    _exact(
        value,
        {
            "host",
            "port",
            "certificate_path",
            "private_key_path",
            "client_ca_path",
            "credential_fingerprints",
        },
        "agent_server",
    )
    fingerprints = _mapping(value, "credential_fingerprints")
    if any(not isinstance(item, str) for item in fingerprints.values()):
        raise QueueConfigError("agent_server credential IDs must be strings")
    port = _non_negative_int(value, "port")
    return AgentTlsServerConfig(
        _string(value, "host"),
        port,
        _path(value, "certificate_path", base),
        _path(value, "private_key_path", base),
        _path(value, "client_ca_path", base),
        cast(Mapping[str, str], fingerprints),
    )


def _mapping(data: Mapping[str, object], field: str) -> Mapping[str, object]:
    return _mapping_value(data.get(field), field)


def _mapping_value(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise QueueConfigError(f"{label} must be a mapping")
    return cast(Mapping[str, object], value)


def _sequence(data: Mapping[str, object], field: str) -> Sequence[object]:
    value = data.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise QueueConfigError(f"{field} must be a sequence")
    return value


def _string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise QueueConfigError(f"{field} must be a non-empty string")
    return value


def _strings(
    data: Mapping[str, object], field: str, *, non_empty: bool = False
) -> tuple[str, ...]:
    values = tuple(_sequence(data, field))
    if non_empty and not values:
        raise QueueConfigError(f"{field} must not be empty")
    if any(not isinstance(value, str) or not value for value in values):
        raise QueueConfigError(f"{field} must contain non-empty strings")
    return cast(tuple[str, ...], values)


def _path(data: Mapping[str, object], field: str, base: Path) -> Path:
    value = Path(_string(data, field))
    return value.resolve() if value.is_absolute() else (base / value).resolve()


def _positive_int(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise QueueConfigError(f"{field} must be a positive integer")
    return value


def _non_negative_int(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QueueConfigError(f"{field} must be a non-negative integer")
    return value


def _positive_number(data: Mapping[str, object], field: str) -> float:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise QueueConfigError(f"{field} must be positive")
    return float(value)


def _exact(data: Mapping[str, object], fields: set[str], label: str) -> None:
    if set(data) != fields:
        raise QueueConfigError(
            f"{label} must contain exactly: {', '.join(sorted(fields))}"
        )


__all__ = [
    "CoordinatorServiceConfig",
    "DEPLOYMENT_CONFIG_SCHEMA_VERSION",
    "OutboundAgentRegistrationConfig",
    "OutboundAgentServiceConfig",
    "load_coordinator_service_config",
    "load_outbound_agent_service_config",
    "run_outbound_agent_service",
]
