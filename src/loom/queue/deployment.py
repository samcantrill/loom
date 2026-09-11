"""Protected, versioned configuration for supported queue role processes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import hashlib
from importlib import import_module
import json
import math
import os
from pathlib import Path
import re
import stat
from threading import Event
from types import MappingProxyType
from typing import Any, cast
from urllib.parse import urlsplit

from loom.serialization import PlainData, thaw_plain_data

from ._remote_stage_execution import (
    AgentResourceInventory,
    GpuDeviceDescriptor,
    ResidentExecutionProfile,
    ResidentGpuDevice,
    ResidentProfileDescriptor,
)
from .agent_session_transport import (
    AgentTlsClientConfig,
    AgentTlsServerConfig,
    LocalDaemonAgentHttpClient,
    RunInspectionTlsClientConfig,
    _read_remote_agent_root_id,
)
from ._agent_process_supervisor import (
    AgentProcessSupervisorError,
    AgentProcessSupervisorService,
    SupervisorLaunchConfiguration,
)
from ._managed_local import _ManagedApplicationSuspended
from .agent_sessions import (
    AgentPolicyConfig,
    AgentPrincipalPolicy,
    AgentRegistration,
    LocalOwnerOperatorPolicy,
    TransportPrincipalPolicy,
)
from .errors import QueueConfigError, QueueConflictError, QueueError, QueueServiceError
from .local_daemon import (
    ConfiguredGpuDevice,
    LocalDaemonConfig,
    LocalDaemonSchedulingComponents,
)
from .coordinator_authority import CoordinatorAuthorityFactory
from .resources import EffectiveAgentCapacity
from .resident_readiness import (
    ResidentReadinessRequirements,
    ResidentReadinessResult,
    qualified_resident_profile,
)
from .gpu.occupancy import GpuOccupancyPolicy
from ._preparation_policy import PreparationPolicy, load_preparation_policy
from .preparation import PREPARATION_INPUT_CAPABILITY, PREPARATION_STAGED_INPUT_CAPABILITY


@dataclass(frozen=True, slots=True)
class CoordinatorConnectionFile:
    """Protected connection settings for a client with no worker identity."""

    url: str
    server_ca_path: Path
    certificate_path: Path
    private_key_path: Path
    expected_coordinator_id: str | None


def load_coordinator_connection_file(path: str | Path) -> CoordinatorConnectionFile:
    """Load the strict protected ``loom.coordinator-client`` v1 file."""
    source, _environment, payload, _fingerprint = _load_protected_config(path)
    allowed = {"schema_version", "kind", "transport", "expected_coordinator_id"}
    if (
        not {"schema_version", "kind", "transport"}.issubset(payload)
        or not set(payload).issubset(allowed)
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or payload.get("kind") != "loom.coordinator-client"
    ):
        raise QueueConfigError("coordinator client config is invalid")
    expected = payload.get("expected_coordinator_id")
    if expected is not None and (not isinstance(expected, str) or not expected):
        raise QueueConfigError("coordinator client expected coordinator ID is invalid")
    transport = payload["transport"]
    if (
        not isinstance(transport, Mapping)
        or set(transport)
        != {"kind", "url", "server_ca_path", "certificate_path", "private_key_path"}
        or transport.get("kind") != "https"
    ):
        raise QueueConfigError("coordinator client transport is invalid")
    base = source.parent
    try:
        values = {
            key: transport[key]
            for key in ("url", "server_ca_path", "certificate_path", "private_key_path")
        }
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError
        server_ca_path = Path(cast(str, values["server_ca_path"]))
        certificate_path = Path(cast(str, values["certificate_path"]))
        private_key_path = Path(cast(str, values["private_key_path"]))
        result = CoordinatorConnectionFile(
            cast(str, values["url"]),
            server_ca_path if server_ca_path.is_absolute() else base / server_ca_path,
            certificate_path
            if certificate_path.is_absolute()
            else base / certificate_path,
            private_key_path
            if private_key_path.is_absolute()
            else base / private_key_path,
            cast(str | None, expected),
        )
        parsed = urlsplit(result.url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path not in ("", "/")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        for label, candidate in (
            ("coordinator CA", result.server_ca_path),
            ("coordinator certificate", result.certificate_path),
            ("coordinator private key", result.private_key_path),
        ):
            _protected_input_path(
                candidate, label=label, require_owner_only=label.endswith("key")
            )
        return result
    except QueueConfigError:
        raise
    except (TypeError, ValueError):
        raise QueueConfigError("coordinator client transport is invalid") from None


DEPLOYMENT_CONFIG_SCHEMA_VERSION = 3
_OUTBOUND_OFFER_TTL_SECONDS = 30
_OUTBOUND_POLL_WAIT_MS = 5_000


@dataclass(frozen=True, slots=True)
class CoordinatorServiceConfig:
    daemon: LocalDaemonConfig
    agent_server: AgentTlsServerConfig | None
    source_path: Path
    immutable_fingerprint: str
    active_fingerprint: str
    environment_path: Path | None = None
    effective_capacity: EffectiveAgentCapacity | None = None
    resident_readiness: ResidentReadinessResult | None = None
    local_agent: LocalAgentServiceConfig | None = None
    _scheduling_source: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class LocalAgentServiceConfig:
    """The agent-owned portion of one embedded coordinator composition."""

    agent_root: Path
    profile: ResidentExecutionProfile
    providers: tuple[object, ...] | None
    provider_configuration: object
    source_path: Path
    environment_path: Path | None = None
    effective_capacity: EffectiveAgentCapacity | None = None
    gpu_occupancy_policy: GpuOccupancyPolicy | None = None


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
    immutable_fingerprint: str
    active_fingerprint: str
    environment_path: Path | None = None
    effective_capacity: EffectiveAgentCapacity | None = None


@dataclass(frozen=True, slots=True)
class RunInspectionClientConfig:
    """Protected configuration for the standalone read-only inspection client."""

    client: RunInspectionTlsClientConfig
    source_path: Path


def load_coordinator_service_config(
    path: str | Path,
    *,
    env_file: str | Path | None = None,
    current: CoordinatorServiceConfig | None = None,
    _allow_unready: bool = False,
) -> CoordinatorServiceConfig:
    """Load one protected coordinator role, observing its selected installation.

    During reload, pass the currently installed service snapshot as ``current``.
    An unchanged scheduling declaration from the same protected source reuses
    its existing component instances and priority resolver. Changed declarations
    are constructed normally and remain subject to the daemon's retained-identity
    checks. This does not activate the replacement or bypass the reload gate.
    """
    source, environment_path, payload, _ = _load_protected_config(
        path, env_file=env_file
    )
    _required_allowed(
        payload,
        {
            "schema_version",
            "kind",
            "deployment_root",
            "run_store_root",
            "machine_id",
            "poll_interval_seconds",
            "max_accepted_time_step_seconds",
            "local_agent",
            "remote_profiles",
            "agent_policy",
            "agent_server",
            "authority",
        },
        {"scheduling", "slurm_profiles", "preparation"},
        "coordinator service config",
    )
    _header(payload, "loom.coordinator-service")
    payload = _normalize_coordinator_payload(payload)
    base = source.parent
    root = _path(payload, "deployment_root", base)
    local_agent = _local_agent_service(
        payload["local_agent"], base, allow_unready=_allow_unready
    )
    remote_profiles = tuple(
        _profile_descriptor(_mapping_value(value, f"remote_profiles[{index}]"))
        for index, value in enumerate(_sequence(payload, "remote_profiles"))
    )
    preparation_policy = load_preparation_policy(
        payload.get("preparation"),
        base=base,
        descriptors=(
            *remote_profiles,
            *((local_agent.profile.descriptor,) if local_agent is not None else ()),
        ),
    )
    fingerprint = _canonical_fingerprint(
        {
            "coordinator": _coordinator_immutable_projection(payload),
            "local_agent": _local_agent_immutable_projection(local_agent),
        }
    )
    active_fingerprint = _canonical_fingerprint(
        {
            "coordinator": _coordinator_active_projection(
                payload, preparation=preparation_policy
            ),
            "local_agent": _local_agent_active_projection(local_agent),
        }
    )
    policy = _agent_policy(_mapping(payload, "agent_policy"))
    authority_factory = _coordinator_authority_factory(
        _mapping(payload, "authority"), base
    )
    scheduling_source = json.dumps(
        payload.get("scheduling"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if (
        current is not None
        and current.source_path == source
        and current.environment_path == environment_path
        and current.immutable_fingerprint == fingerprint
        and current._scheduling_source == scheduling_source
    ):
        scheduling = current.daemon.scheduling_components
        priority_resolver = current.daemon.admission_priority_resolver
    else:
        scheduling, priority_resolver = _scheduling_composition(
            payload.get("scheduling")
        )
    slurm_profiles = _slurm_profile_composition(payload.get("slurm_profiles"))
    server_value = payload["agent_server"]
    server = (
        None
        if server_value is None
        else _agent_server(_mapping_value(server_value, "agent_server"), base)
    )
    daemon = LocalDaemonConfig(
        coordinator_root=root / "coordinator",
        agent_root=None if local_agent is None else local_agent.agent_root,
        run_store_root=_path(payload, "run_store_root", base),
        resident_worker_launch_profile=(
            None if local_agent is None else local_agent.profile.launch_profile
        ),
        deployment_root=root,
        deployment_configuration_fingerprint=fingerprint,
        active_configuration_fingerprint=active_fingerprint,
        machine_id=_string(payload, "machine_id"),
        cpu_capacity=0 if local_agent is None else local_agent.profile.cpu_capacity,
        memory_capacity_bytes=(
            0 if local_agent is None else local_agent.profile.memory_capacity_bytes
        ),
        gpu_devices=(
            ()
            if local_agent is None
            else tuple(
                ConfiguredGpuDevice(item.descriptor, item.binding_value)
                for item in local_agent.profile.gpu_devices
            )
        ),
        poll_interval_seconds=_positive_number(payload, "poll_interval_seconds"),
        max_accepted_time_step_seconds=_positive_number(
            payload, "max_accepted_time_step_seconds"
        ),
        agent_policy=policy,
        remote_profiles=remote_profiles,
        coordinator_authority_factory=authority_factory,
        scheduling_components=scheduling,
        admission_priority_resolver=priority_resolver,
        agent_resource_providers=(
            None if local_agent is None else cast(Any, local_agent.providers)
        ),
        slurm_profiles=cast(Any, slurm_profiles),
        gpu_occupancy_policy=None
        if local_agent is None
        else local_agent.gpu_occupancy_policy,
        preparation_policy=preparation_policy,
        resident_preparation_ready=(
            local_agent is not None
            and local_agent.profile.readiness_result is not None
            and local_agent.profile.readiness_result.preparation_ready
        ),
        resident_preparation_staged_ready=(
            local_agent is not None
            and local_agent.profile.readiness_result is not None
            and local_agent.profile.readiness_result.preparation_staged_ready
        ),
    )
    return CoordinatorServiceConfig(
        daemon,
        server,
        source,
        fingerprint,
        active_fingerprint,
        environment_path,
        effective_capacity=None
        if local_agent is None
        else local_agent.effective_capacity,
        resident_readiness=None
        if local_agent is None
        else local_agent.profile.readiness_result,
        local_agent=local_agent,
        _scheduling_source=scheduling_source,
    )


def load_outbound_agent_service_config(
    path: str | Path,
    *,
    env_file: str | Path | None = None,
    _allow_unready: bool = False,
) -> OutboundAgentServiceConfig:
    source, environment_path, payload, _ = _load_protected_config(
        path, env_file=env_file
    )
    _required_allowed(
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
        {"provider_factory", "resources"},
        "outbound agent service config",
    )
    _header(payload, "loom.outbound-agent-service")
    payload = _normalize_outbound_agent_payload(payload)
    base = source.parent
    capabilities = _strings(
        _mapping(payload, "registration"), "capabilities", non_empty=True
    )
    preparation_staged = PREPARATION_STAGED_INPUT_CAPABILITY in capabilities
    preparation = PREPARATION_INPUT_CAPABILITY in capabilities or preparation_staged
    profiles = tuple(
        _resident_profile(
            _mapping_value(value, f"resident_profiles[{index}]"),
            base,
            f"resident_profiles[{index}]",
            allow_unready=_allow_unready,
            preparation=preparation,
            preparation_staged=preparation_staged,
        )
        for index, value in enumerate(_sequence(payload, "resident_profiles"))
    )
    if not profiles:
        raise QueueConfigError("resident_profiles must not be empty")
    authored_profiles = _sequence(payload, "resident_profiles")
    payload = {
        **payload,
        "resident_profiles": [
            {
                **_mapping_value(value, "resident profile"),
                "descriptor": profile.descriptor.to_dict(),
                **(
                    {
                        "preparation_shared_roots": {
                            alias: str(path)
                            for alias, path in profile.preparation_shared_roots.items()
                        }
                    }
                    if profile.preparation_shared_roots
                    else {}
                ),
            }
            for value, profile in zip(authored_profiles, profiles, strict=True)
        ],
    }
    fingerprint = _canonical_fingerprint(_outbound_immutable_projection(payload))
    resource_inventory, effective_capacity = _agent_resource_inventory(
        payload.get("resources")
    )
    occupancy_policy = _gpu_occupancy_policy(payload.get("resources"))
    if occupancy_policy is not None and payload.get("provider_factory") is not None:
        raise QueueConfigError(
            "NVIDIA occupancy cannot be bypassed by a custom provider factory"
        )
    active_fingerprint = _canonical_fingerprint(
        {
            "authored": _outbound_active_projection(payload),
            "observed_resources": _resource_inventory_projection(resource_inventory),
            **(
                {"gpu_occupancy": occupancy_policy.to_dict()}
                if occupancy_policy is not None
                and occupancy_policy != GpuOccupancyPolicy()
                else {}
            ),
        }
    )
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
    provider_factory = None
    if payload.get("provider_factory") is not None:
        provider_factory = _trusted_target(
            _mapping(payload, "provider_factory"), "remote provider factory"
        )
        if not callable(provider_factory):
            raise QueueConfigError("remote provider factory target is invalid")
    client = AgentTlsClientConfig(
        url=_string(payload, "url"),
        server_ca_path=_path(payload, "server_ca_path", base),
        certificate_path=_path(payload, "certificate_path", base),
        private_key_path=_path(payload, "private_key_path", base),
        agent_root=_path(payload, "agent_root", base),
        resident_profiles=profiles,
        resource_inventory=resource_inventory,
        gpu_occupancy_policy=occupancy_policy,
        agent_resource_provider_factory=cast(Any, provider_factory),
        deployment_configuration_fingerprint=fingerprint,
        active_configuration_fingerprint=active_fingerprint,
    )
    return OutboundAgentServiceConfig(
        client,
        registration,
        _positive_number(payload, "reconnect_seconds"),
        source,
        fingerprint,
        active_fingerprint,
        environment_path,
        effective_capacity=effective_capacity,
    )


def load_run_inspection_client_config(path: str | Path) -> RunInspectionClientConfig:
    """Load the strict protected v1 remote inspection client configuration."""

    source, _environment_path, payload, _fingerprint = _load_protected_config(path)
    _exact(
        payload,
        {
            "schema_version",
            "kind",
            "url",
            "server_ca_path",
            "certificate_path",
            "private_key_path",
        },
        "run inspection client config",
    )
    _header(payload, "loom.run-inspection-client", schema_version=1)
    base = source.parent
    return RunInspectionClientConfig(
        RunInspectionTlsClientConfig(
            url=_string(payload, "url"),
            server_ca_path=_path(payload, "server_ca_path", base),
            certificate_path=_path(payload, "certificate_path", base),
            private_key_path=_path(payload, "private_key_path", base),
        ),
        source,
    )


def run_outbound_agent_service(
    config: OutboundAgentServiceConfig,
    *,
    stop: Event,
    trusted_config_loader: Callable[[], OutboundAgentServiceConfig] | None = None,
) -> None:
    """Run a foreground agent, preserving supervised work on service stop.

    Stop interrupts active and retained-worker observation at durable replay
    boundaries. It does not cancel jobs or release their claims. In-flight
    transport operations retain their configured timeouts before suspension.
    """

    active = config
    pending: OutboundAgentServiceConfig | None = None

    def load_client() -> AgentTlsClientConfig:
        nonlocal pending
        if trusted_config_loader is None:
            raise QueueServiceError("trusted agent configuration loader is unavailable")
        pending = trusted_config_loader()
        return pending.client

    def prepare_install(
        replacement: AgentTlsClientConfig,
    ) -> Callable[[], None]:
        nonlocal pending
        if pending is None or pending.client != replacement:
            raise QueueServiceError("trusted agent role snapshot is unavailable")
        snapshot = pending

        def install() -> None:
            nonlocal active, pending
            active = snapshot
            pending = None

        return install

    client: LocalDaemonAgentHttpClient | None = _open_outbound_agent(
        active.client,
        trusted_config_loader=None if trusted_config_loader is None else load_client,
        prepare_role_reload=prepare_install,
    )
    while True:
        try:
            if stop.is_set():
                return
            if client is None:
                client = _open_outbound_agent(
                    active.client,
                    trusted_config_loader=(
                        None if trusted_config_loader is None else load_client
                    ),
                    prepare_role_reload=prepare_install,
                )
            client.resume_retained_work(suspend_requested=stop.is_set)
            handshake = client.handshake()
            coordinator_epoch = cast(str, handshake["coordinator_epoch"])
            coordinator_id = cast(str, handshake["coordinator_id"])
            session = client.active_session()
            if session is None:
                operation_id = _operation_id(
                    "register",
                    client.agent_root_id,
                    active.registration.config_revision,
                )
                session = client.register(
                    AgentRegistration(
                        operation_id,
                        coordinator_id,
                        coordinator_epoch,
                        client.agent_root_id,
                        active.registration.config_revision,
                        active.registration.inventory_revision,
                        active.registration.availability_revision,
                        active.registration.pools,
                        active.registration.capabilities,
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
                client._resource_maintenance_enabled = True  # noqa: SLF001
                client.refresh_resource_offer(ttl_seconds=_OUTBOUND_OFFER_TTL_SECONDS)
                session = client.active_session()
                if session is None:
                    raise QueueServiceError("agent session ended without retirement")
                sequence = client.next_poll_sequence(session.session_id)
                client.execute_one(
                    session.session_id,
                    session.availability_revision,
                    sequence=sequence,
                    wait_timeout_ms=_OUTBOUND_POLL_WAIT_MS,
                    suspend_requested=stop.is_set,
                )
                session = client.active_session()
                if session is None:
                    raise QueueServiceError("agent session ended without retirement")
        except _ManagedApplicationSuspended:
            return
        except QueueError:
            if stop.is_set():
                return
            stop.wait(active.reconnect_seconds)
        finally:
            if client is not None:
                closing = client
                client = None
                try:
                    closing.shutdown_clean()
                except (QueueConflictError, QueueServiceError):
                    # Retained or uncertain work deliberately keeps its process
                    # owner alive so the next service incarnation can join it.
                    pass
                closing.close()


def _operation_id(kind: str, *parts: str) -> str:
    encoded = json.dumps(parts, separators=(",", ":")).encode("utf-8")
    return f"{kind}-{hashlib.sha256(encoded).hexdigest()[:32]}"


def _open_outbound_agent(
    config: AgentTlsClientConfig,
    *,
    trusted_config_loader: Callable[[], AgentTlsClientConfig] | None = None,
    prepare_role_reload: (
        Callable[[AgentTlsClientConfig], Callable[[], None]] | None
    ) = None,
) -> LocalDaemonAgentHttpClient:
    try:
        return LocalDaemonAgentHttpClient(
            config,
            trusted_config_loader=trusted_config_loader,
            prepare_role_reload=prepare_role_reload,
        )
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
    return LocalDaemonAgentHttpClient(
        config,
        trusted_config_loader=trusted_config_loader,
        prepare_role_reload=prepare_role_reload,
    )


def _load_protected_config(
    path: str | Path, *, env_file: str | Path | None = None
) -> tuple[Path, Path | None, Mapping[str, object], str]:
    source = _protected_input_path(path, label="deployment config")
    environment_path, environment = _read_explicit_environment(env_file)
    try:
        from weave import compose_config
    except ModuleNotFoundError as exc:
        raise QueueConfigError(
            "deployment YAML loading requires Loom's weave dependency"
        ) from exc
    try:
        composed = compose_config(source, environment=environment)
    except Exception as exc:  # noqa: BLE001
        raise QueueConfigError("deployment config is invalid") from exc
    for artifact in composed.source_artifacts:
        if artifact.kind in {"base", "include"}:
            _protected_input_path(
                artifact.path,
                label="deployment config source",
                require_owner_only=artifact.kind == "base",
            )
    loaded = composed.resolved
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
        environment_path,
        cast(Mapping[str, object], plain),
        hashlib.sha256(encoded).hexdigest(),
    )


_ENVIRONMENT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _protected_input_path(
    path: str | Path, *, label: str, require_owner_only: bool = True
) -> Path:
    source = Path(path).resolve()
    if not source.is_file():
        raise QueueConfigError(f"{label} is unavailable")
    details = source.stat()
    prohibited_mode = 0o077 if require_owner_only else 0o022
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & prohibited_mode:
        raise QueueConfigError(f"{label} must be owner-protected")
    return source


def _read_explicit_environment(
    env_file: str | Path | None,
) -> tuple[Path | None, Mapping[str, str]]:
    if env_file is None:
        return None, MappingProxyType({})
    source = _protected_input_path(env_file, label="deployment environment")
    try:
        from dotenv.parser import parse_stream

        with source.open(encoding="utf-8") as stream:
            bindings = tuple(parse_stream(stream))
    except (ModuleNotFoundError, OSError, UnicodeError) as exc:
        raise QueueConfigError("deployment environment is invalid") from exc
    values: dict[str, str] = {}
    for binding in bindings:
        if binding.key is None:
            if binding.error:
                raise QueueConfigError("deployment environment is invalid")
            continue
        if (
            binding.error
            or binding.value is None
            or _ENVIRONMENT_KEY.fullmatch(binding.key) is None
            or binding.key in values
        ):
            raise QueueConfigError("deployment environment is invalid")
        values[binding.key] = binding.value
    return source, MappingProxyType(values)


def _normalize_coordinator_payload(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Normalize role-owned numeric values before identity projections."""

    normalized = dict(payload)
    normalized["poll_interval_seconds"] = _positive_number(
        payload, "poll_interval_seconds"
    )
    normalized["max_accepted_time_step_seconds"] = _positive_number(
        payload, "max_accepted_time_step_seconds"
    )
    server = payload.get("agent_server")
    if server is not None:
        normalized["agent_server"] = _normalize_agent_server(
            _mapping_value(server, "agent_server")
        )
    return normalized


def _local_agent_service(
    value: object, base: Path, *, allow_unready: bool = False
) -> LocalAgentServiceConfig | None:
    """Load the optional protected agent role used by a local coordinator."""

    if value is None:
        return None
    reference = _mapping_value(value, "local_agent")
    _exact(reference, {"config", "env_file"}, "local_agent")
    source = _path(reference, "config", base)
    environment = (
        None if reference["env_file"] is None else _path(reference, "env_file", base)
    )
    agent_source, environment_path, payload, _ = _load_protected_config(
        source, env_file=environment
    )
    _required_allowed(
        payload,
        {"schema_version", "kind", "agent_root", "resident_profiles"},
        {"providers", "resources"},
        "local agent service config",
    )
    _header(payload, "loom.local-agent-service")
    profiles = tuple(
        _resident_profile(
            _mapping_value(item, f"resident_profiles[{index}]"),
            agent_source.parent,
            f"resident_profiles[{index}]",
            allow_unready=allow_unready,
        )
        for index, item in enumerate(_sequence(payload, "resident_profiles"))
    )
    if len(profiles) != 1:
        raise QueueConfigError("local agent service requires one resident profile")
    provider_configuration = payload.get("providers")
    resource_inventory, effective_capacity = _agent_resource_inventory(
        payload.get("resources")
    )
    profile = profiles[0]
    if resource_inventory is not None:
        profile = replace(
            profile,
            cpu_capacity=resource_inventory.cpu_capacity,
            memory_capacity_bytes=resource_inventory.memory_capacity_bytes,
            gpu_devices=resource_inventory.gpu_devices,
        )
    occupancy_policy = _gpu_occupancy_policy(payload.get("resources"))
    if occupancy_policy is not None and provider_configuration is not None:
        raise QueueConfigError(
            "NVIDIA occupancy cannot be bypassed by custom providers"
        )
    providers = _embedded_provider_composition(provider_configuration)
    return LocalAgentServiceConfig(
        _path(payload, "agent_root", agent_source.parent),
        profile,
        providers,
        _without_paths(provider_configuration),
        agent_source,
        environment_path,
        effective_capacity=effective_capacity,
        gpu_occupancy_policy=occupancy_policy,
    )


def _normalize_outbound_agent_payload(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Normalize outbound role values before identity projections."""

    normalized = dict(payload)
    normalized["reconnect_seconds"] = _positive_number(payload, "reconnect_seconds")
    normalized["resident_profiles"] = [
        _normalize_resident_profile(
            _mapping_value(value, f"resident_profiles[{index}]"),
            f"resident_profiles[{index}]",
        )
        for index, value in enumerate(_sequence(payload, "resident_profiles"))
    ]
    return normalized


def _agent_resource_inventory(
    value: object,
) -> tuple[AgentResourceInventory | None, EffectiveAgentCapacity | None]:
    """Load one agent-owned capacity declaration and its selected NVIDIA cards."""

    if value is None:
        return None, None
    resources = _mapping_value(value, "agent resources")
    _exact(
        resources,
        {"cpu_capacity", "memory_capacity_bytes", "gpu"},
        "agent resources",
    )
    gpu = _mapping(resources, "gpu")
    _required_allowed(
        gpu, {"provider", "devices"}, {"occupancy"}, "agent GPU resources"
    )
    provider = _string(gpu, "provider")
    selection = _string(gpu, "devices")
    if provider != "nvidia":
        raise QueueConfigError("agent GPU resource provider is unsupported")
    devices: tuple[ResidentGpuDevice, ...] = ()
    if selection != "none":
        from .gpu.nvidia import (
            NvidiaSmiGpuInventoryProvider,
            resolve_nvidia_gpu_selection,
        )

        try:
            selected = resolve_nvidia_gpu_selection(
                selection, NvidiaSmiGpuInventoryProvider().discover()
            )
            devices = tuple(
                ResidentGpuDevice(
                    GpuDeviceDescriptor(
                        device_id=device.device_id,
                        model=cast(str, device.model),
                        vram_bytes=cast(int, device.vram_bytes),
                    ),
                    device.binding_value,
                )
                for device in selected
            )
        except (QueueServiceError, TypeError, ValueError) as exc:
            raise QueueConfigError("agent NVIDIA inventory is invalid") from exc
    inventory = AgentResourceInventory(
        _positive_int(resources, "cpu_capacity"),
        _non_negative_int(resources, "memory_capacity_bytes"),
        devices,
    )
    from .resources import require_effective_agent_capacity

    try:
        effective_capacity = require_effective_agent_capacity(
            cpu_capacity=inventory.cpu_capacity,
            memory_capacity_bytes=inventory.memory_capacity_bytes,
        )
    except QueueServiceError as exc:
        raise QueueConfigError("agent resources exceed effective capacity") from exc
    return inventory, effective_capacity


def _gpu_occupancy_policy(value: object) -> GpuOccupancyPolicy | None:
    """Normalize authored NVIDIA observation policy without querying occupancy."""
    if value is None:
        return None
    gpu = _mapping(_mapping_value(value, "agent resources"), "gpu")
    authored = _mapping_value(gpu.get("occupancy", {}), "GPU occupancy")
    fields = {
        "poll_interval_seconds",
        "max_observation_age_seconds",
        "query_timeout_seconds",
        "external_process_policy",
    }
    _required_allowed(authored, set(), fields, "GPU occupancy")
    defaults = GpuOccupancyPolicy()
    try:
        policy = GpuOccupancyPolicy(
            poll_interval_seconds=_positive_number(
                {
                    "poll_interval_seconds": authored.get(
                        "poll_interval_seconds", defaults.poll_interval_seconds
                    )
                },
                "poll_interval_seconds",
            ),
            max_observation_age_seconds=_positive_number(
                {
                    "max_observation_age_seconds": authored.get(
                        "max_observation_age_seconds",
                        defaults.max_observation_age_seconds,
                    )
                },
                "max_observation_age_seconds",
            ),
            query_timeout_seconds=_positive_number(
                {
                    "query_timeout_seconds": authored.get(
                        "query_timeout_seconds", defaults.query_timeout_seconds
                    )
                },
                "query_timeout_seconds",
            ),
            external_process_policy=cast(
                str, authored.get("external_process_policy", "block")
            ),
        )
    except (ValueError, TypeError) as exc:
        raise QueueConfigError("GPU occupancy policy is invalid") from exc
    return None if gpu.get("devices") == "none" else policy


def _resource_inventory_projection(
    inventory: AgentResourceInventory | None,
) -> object:
    if inventory is None:
        return None
    return {
        "cpu_capacity": inventory.cpu_capacity,
        "memory_capacity_bytes": inventory.memory_capacity_bytes,
        "gpu_devices": [
            {
                "descriptor": device.descriptor.to_dict(),
                "binding_digest": hashlib.sha256(
                    device.binding_value.encode()
                ).hexdigest(),
            }
            for device in inventory.gpu_devices
        ],
    }


def _normalize_resident_profile(
    profile: Mapping[str, object], label: str
) -> Mapping[str, object]:
    normalized = dict(profile)
    normalized["cpu_capacity"] = _positive_int(profile, "cpu_capacity")
    normalized["memory_capacity_bytes"] = _non_negative_int(
        profile, "memory_capacity_bytes"
    )
    return normalized


def _normalize_agent_server(server: Mapping[str, object]) -> Mapping[str, object]:
    normalized = dict(server)
    normalized["port"] = _non_negative_int(server, "port")
    return normalized


def _canonical_fingerprint(value: Mapping[str, object]) -> str:
    """Fingerprint only inert authored values, never source paths or objects."""

    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _coordinator_authority_factory(
    value: Mapping[str, object],
    base: Path,
) -> CoordinatorAuthorityFactory:
    """Construct one explicit trusted authority factory for this role.

    Embedded access is intentionally the only default.  A persistent role must
    name its already-authenticated, run-scoped adapter factory explicitly; the
    deployment loader never discovers targets or falls back to SQLite.
    """

    kind = _string(value, "kind")
    if kind == "embedded":
        _exact(value, {"kind"}, "embedded authority")
        from loom.pipeline.stores.coordinator_authority import (
            embedded_coordinator_authority,
        )

        return cast(CoordinatorAuthorityFactory, embedded_coordinator_authority)
    if kind != "https":
        raise QueueConfigError("authority kind is unsupported")
    _exact(
        value,
        {"kind", "url", "service_id", "workspace_id", "tls"},
        "HTTPS authority",
    )
    tls = _mapping(value, "tls")
    _exact(
        tls,
        {"ca", "certificate", "private_key"},
        "HTTPS authority TLS",
    )
    try:
        from loom.pipeline.stores.coordinator_authority import (
            CoordinatorAuthorityTlsConfig,
            https_coordinator_authority_factory,
        )

        return cast(
            CoordinatorAuthorityFactory,
            https_coordinator_authority_factory(
                _string(value, "url"),
                service_id=_string(value, "service_id"),
                workspace_id=_string(value, "workspace_id"),
                tls=CoordinatorAuthorityTlsConfig(
                    ca_path=_path(tls, "ca", base),
                    certificate_path=_path(tls, "certificate", base),
                    private_key_path=_path(tls, "private_key", base),
                ),
            ),
        )
    except (OSError, ValueError) as exc:
        raise QueueConfigError("HTTPS authority is unavailable or invalid") from exc


def _trusted_target(value: Mapping[str, object], label: str) -> object:
    """Instantiate one protected `_target_` eagerly and without discovery."""

    target = _string(value, "_target_")
    kwargs = {
        key: _construct_trusted_value(item, f"{label}.{key}")
        for key, item in value.items()
        if key != "_target_"
    }
    module_name, separator, attribute = target.rpartition(".")
    if not separator or not module_name or not attribute:
        raise QueueConfigError(f"{label} target is invalid")
    try:
        constructor = getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise QueueConfigError(f"{label} target is unavailable") from exc
    if not callable(constructor):
        raise QueueConfigError(f"{label} target is not callable")
    try:
        return constructor(**kwargs)
    except Exception as exc:  # trusted code, normalized at the config boundary
        raise QueueConfigError(f"{label} target is invalid") from exc


def _construct_trusted_value(value: object, label: str) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        if "_target_" in mapping:
            return _trusted_target(mapping, label)
        return {
            str(key): _construct_trusted_value(item, f"{label}.{key}")
            for key, item in mapping.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(
            _construct_trusted_value(item, f"{label}[{index}]")
            for index, item in enumerate(value)
        )
    return value


def _scheduling_composition(
    value: object,
) -> tuple[LocalDaemonSchedulingComponents, Callable[[str], int]]:
    if value is None:
        from .local_daemon import _default_scheduling_components

        return _default_scheduling_components(), lambda _run_uri: 0
    mapping = _mapping_value(value, "scheduling")
    _exact(mapping, {"priority_resolver", "components"}, "scheduling")
    components = _mapping(mapping, "components")
    _exact(
        components,
        {"planners", "hard_evaluators", "preference_scorers", "policy"},
        "scheduling components",
    )
    planners = _target_sequence(components["planners"], "scheduling planners")
    hard = _target_sequence(components["hard_evaluators"], "scheduling hard evaluators")
    preferences = _target_sequence(
        components["preference_scorers"], "scheduling preference scorers"
    )
    policy = _trusted_target(_mapping(components, "policy"), "scheduling policy")
    resolver = _trusted_target(
        _mapping(mapping, "priority_resolver"), "priority resolver"
    )
    if not callable(resolver):
        raise QueueConfigError("priority resolver target is invalid")
    try:
        composition = LocalDaemonSchedulingComponents(
            planners=cast(Any, planners),
            hard_evaluators=cast(Any, hard),
            preference_scorers=cast(Any, preferences),
            policy=cast(Any, policy),
        )
    except (TypeError, ValueError, QueueServiceError) as exc:
        raise QueueConfigError("scheduling composition is invalid") from exc
    return composition, cast(Callable[[str], int], resolver)


def _embedded_provider_composition(value: object) -> tuple[object, ...] | None:
    if value is None:
        return None
    mapping = _mapping_value(value, "embedded_agent")
    _exact(mapping, {"providers"}, "embedded agent")
    providers = _target_sequence(mapping["providers"], "embedded providers")
    if not providers:
        raise QueueConfigError("embedded provider composition is empty")
    return providers


def _target_sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise QueueConfigError(f"{label} must be a sequence")
    return tuple(
        _trusted_target(_mapping_value(item, f"{label}[{index}]"), f"{label}[{index}]")
        for index, item in enumerate(value)
    )


def _slurm_profile_composition(value: object) -> tuple[object, ...]:
    """Construct complete ready-stage profiles from one protected source."""

    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise QueueConfigError("slurm_profiles must be a sequence")
    from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile

    profiles: list[SlurmReadyStageProfile] = []
    required = {
        "profile_id",
        "partition",
        "max_outstanding",
        "runner",
        "command_adapter_fingerprint",
        "bootstrap_principal_id",
        "credential_reference",
        "coordinator_endpoint",
        "project_fingerprint",
        "environment_fingerprint",
        "executor_fingerprint",
        "job_private_file_provider",
    }
    optional = {
        "executor_name",
        "credential_policy_revision",
        "account",
        "qos",
        "cluster",
        "available",
        "containment_helper",
    }
    for index, item in enumerate(value):
        label = f"slurm_profiles[{index}]"
        mapping = _mapping_value(item, label)
        if "_target_" in mapping:
            target = _trusted_target(mapping, label)
            if not isinstance(target, SlurmReadyStageProfile):
                raise QueueConfigError(f"{label} target is not a ready-stage profile")
            profiles.append(target)
            continue
        _required_allowed(mapping, required, optional, label)
        kwargs = {
            key: _construct_trusted_value(item_value, f"{label}.{key}")
            for key, item_value in mapping.items()
        }
        kwargs["bootstrap_argv"] = ("loom", "slurm-bootstrap")
        try:
            profile = SlurmReadyStageProfile(**cast(Any, kwargs))
        except Exception as exc:
            raise QueueConfigError(f"{label} is invalid") from exc
        profiles.append(profile)
    if len({profile.profile_id for profile in profiles}) != len(profiles):
        raise QueueConfigError("slurm profile IDs must be unique")
    return cast(tuple[object, ...], tuple(profiles))


def _coordinator_immutable_projection(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Role-owned coordinator identity, deliberately excluding reloadable policy."""

    server = payload.get("agent_server")
    server_mapping = None if server is None else _mapping_value(server, "agent_server")
    server_identity = (
        None
        if server_mapping is None
        else {
            "host": server_mapping.get("host"),
            "port": server_mapping.get("port"),
        }
    )
    return {
        "schema_version": payload["schema_version"],
        "kind": payload["kind"],
        "machine_id": payload["machine_id"],
        "agent_server": server_identity,
        "authority": _without_paths(_mapping(payload, "authority")),
    }


def _outbound_immutable_projection(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Outbound role transport and executable-profile identity."""

    profiles = []
    for value in _sequence(payload, "resident_profiles"):
        profile = _mapping_value(value, "resident profile")
        profiles.append(
            {
                "descriptor": dict(_mapping(profile, "descriptor")),
            }
        )
    return {
        "schema_version": payload["schema_version"],
        "kind": payload["kind"],
        "url": payload["url"],
        "resident_profiles": profiles,
    }


def _coordinator_active_projection(
    payload: Mapping[str, object], *, preparation: PreparationPolicy | None = None
) -> dict[str, object]:
    server = payload.get("agent_server")
    server_mapping = None if server is None else _mapping_value(server, "agent_server")
    server_credentials = (
        None
        if server_mapping is None
        else server_mapping.get("credential_fingerprints")
    )
    return cast(
        dict[str, object],
        _without_paths(
            {
                "poll_interval_seconds": payload["poll_interval_seconds"],
                "max_accepted_time_step_seconds": payload[
                    "max_accepted_time_step_seconds"
                ],
                "agent_policy": payload["agent_policy"],
                "agent_server_credentials": server_credentials,
                "remote_profiles": payload["remote_profiles"],
                "scheduling": payload.get("scheduling"),
                "slurm_profiles": payload.get("slurm_profiles"),
                **(
                    {"preparation": preparation.safe_identity()}
                    if preparation is not None
                    else {}
                ),
            }
        ),
    )


def _local_agent_immutable_projection(
    local_agent: LocalAgentServiceConfig | None,
) -> object:
    if local_agent is None:
        return None
    return {"descriptor": local_agent.profile.descriptor.to_dict()}


def _local_agent_active_projection(
    local_agent: LocalAgentServiceConfig | None,
) -> object:
    if local_agent is None:
        return None
    profile = local_agent.profile
    return {
        "cpu_capacity": profile.cpu_capacity,
        "memory_capacity_bytes": profile.memory_capacity_bytes,
        "gpu_devices": [
            {
                "descriptor": item.descriptor.to_dict(),
                "binding_digest": hashlib.sha256(
                    item.binding_value.encode()
                ).hexdigest(),
            }
            for item in profile.gpu_devices
        ],
        "providers": local_agent.provider_configuration,
        **(
            {
                "preparation_shared_roots": _preparation_mapping_identity(
                    profile.preparation_shared_roots
                )
            }
            if profile.preparation_shared_roots
            else {}
        ),
        **(
            {"gpu_occupancy": local_agent.gpu_occupancy_policy.to_dict()}
            if local_agent.gpu_occupancy_policy is not None
            and local_agent.gpu_occupancy_policy != GpuOccupancyPolicy()
            else {}
        ),
    }


def _outbound_active_projection(payload: Mapping[str, object]) -> dict[str, object]:
    # Qualification controls select the observation, while the derived
    # descriptor records the software actually offered to the coordinator.
    profiles = [
        {
            key: item
            for key, item in _mapping_value(value, "resident profile").items()
            if key not in {"readiness", "preparation_shared_roots"}
        }
        for value in _sequence(payload, "resident_profiles")
    ]
    for profile, value in zip(
        profiles, _sequence(payload, "resident_profiles"), strict=True
    ):
        roots = _mapping_value(value, "resident profile").get(
            "preparation_shared_roots"
        )
        if roots:
            profile["preparation_shared_roots"] = _preparation_mapping_identity(
                cast(Mapping[str, Path], roots)
            )
    return cast(
        dict[str, object],
        _without_paths(
            {
                "registration": payload["registration"],
                "reconnect_seconds": payload["reconnect_seconds"],
                "resident_profiles": profiles,
                "provider_factory": payload.get("provider_factory"),
            }
        ),
    )


def _preparation_mapping_identity(roots: Mapping[str, Path]) -> list[dict[str, str]]:
    return [
        {
            "alias": alias,
            "binding_digest": hashlib.sha256(str(path).encode()).hexdigest(),
        }
        for alias, path in sorted(roots.items())
    ]


def _without_paths(value: object) -> object:
    """Keep canonical authored values without locations or secret-bearing values."""

    if isinstance(value, Mapping):
        return {
            str(key): _without_paths(item)
            for key, item in value.items()
            if not str(key).endswith("_path")
            and str(key)
            not in {
                "project_root",
                "python_executable",
                "environment",
                "ca",
                "certificate",
                "private_key",
            }
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_without_paths(item) for item in value]
    return value


def _header(
    payload: Mapping[str, object],
    kind: str,
    *,
    schema_version: int = DEPLOYMENT_CONFIG_SCHEMA_VERSION,
) -> None:
    version = payload.get("schema_version")
    if version != schema_version or isinstance(version, bool):
        raise QueueConfigError("deployment config schema version is unsupported")
    if payload.get("kind") != kind:
        raise QueueConfigError("deployment config kind is invalid")


def _resident_profile(
    value: Mapping[str, object],
    base: Path,
    label: str,
    *,
    allow_unready: bool = False,
    preparation: bool = False,
    preparation_staged: bool = False,
) -> ResidentExecutionProfile:
    _required_allowed(
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
        {"readiness", "preparation_shared_roots"},
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
    requirements = _resident_readiness_requirements(value.get("readiness"))
    if preparation:
        requirements = replace(requirements, preparation=True)
    if preparation_staged:
        requirements = replace(requirements, preparation_staged=True)
    profile = ResidentExecutionProfile(
        _resident_descriptor_declaration(_mapping(value, "descriptor")),
        _path(value, "project_root", base),
        _executable_path(value, "python_executable", base),
        _positive_int(value, "cpu_capacity"),
        _non_negative_int(value, "memory_capacity_bytes"),
        tuple(devices),
        cast(Mapping[str, str], environment),
        requirements,
        preparation_shared_roots={
            alias: _path({"root": path}, "root", base)
            for alias, path in _mapping_value(
                value.get("preparation_shared_roots", {}), "preparation shared roots"
            ).items()
        },
    )
    profile = qualified_resident_profile(profile)
    result = profile.readiness_result
    assert result is not None
    if not result.ok and not allow_unready:
        failed = next(item for item in result.checks if item.status == "FAIL")
        raise QueueConfigError(
            f"resident profile readiness failed ({failed.check_id}): {failed.message}"
        )
    return profile


def _resident_readiness_requirements(value: object) -> ResidentReadinessRequirements:
    if value is None:
        return ResidentReadinessRequirements()
    readiness = _mapping_value(value, "resident readiness")
    sequence_fields = {
        "imports",
        "distributions",
        "source_roots",
        "required_environment",
        "required_programs",
    }
    mapping_fields = {"import_roots", "distribution_versions"}
    string_fields = {
        "python_version",
        "python_implementation",
        "python_abi",
        "lockfile",
    }
    _required_allowed(
        readiness,
        set(),
        sequence_fields
        | mapping_fields
        | string_fields
        | {"timeout_seconds", "preparation", "preparation_staged"},
        "resident readiness",
    )
    fields: dict[str, Any] = {}
    for name in sequence_fields & readiness.keys():
        fields[name] = _strings(readiness, name)
    for name in mapping_fields & readiness.keys():
        mapping = _mapping(readiness, name)
        if any(not isinstance(item, str) or not item for item in mapping.values()):
            raise QueueConfigError(
                "resident compatibility values must be nonempty strings"
            )
        fields[name] = dict(mapping)
    for name in string_fields & readiness.keys():
        fields[name] = _string(readiness, name)
    if "timeout_seconds" in readiness:
        fields["timeout_seconds"] = _positive_number(readiness, "timeout_seconds")
    if "preparation" in readiness:
        fields["preparation"] = readiness["preparation"]
    if "preparation_staged" in readiness:
        fields["preparation_staged"] = readiness["preparation_staged"]
    try:
        return ResidentReadinessRequirements(**fields)
    except ValueError as exc:
        raise QueueConfigError("resident readiness requirements are invalid") from exc


def _resident_descriptor_declaration(
    value: Mapping[str, object],
) -> ResidentProfileDescriptor:
    _required_allowed(
        value,
        {"profile_id", "revision"},
        {"project_fingerprint", "environment_fingerprint", "executor_fingerprint"},
        "resident descriptor",
    )
    # Software fingerprints are derived from the selected installation. Existing
    # full declarations remain readable; their authored values are not evidence.
    return ResidentProfileDescriptor(
        _string(value, "profile_id"),
        _string(value, "revision"),
        "unqualified",
        "unqualified",
        "unqualified",
    )


def _profile_descriptor(value: Mapping[str, object]) -> ResidentProfileDescriptor:
    try:
        return ResidentProfileDescriptor.from_dict(value)
    except (QueueServiceError, TypeError, ValueError) as exc:
        raise QueueConfigError("resident profile descriptor is invalid") from exc


def _agent_policy(value: Mapping[str, object]) -> AgentPolicyConfig:
    _required_allowed(
        value, {"revision", "agents", "principals"}, {"local_owner"}, "agent_policy"
    )
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
    local_owner_value = value.get("local_owner")
    local_owner = None
    if local_owner_value is not None:
        scope = _mapping_value(local_owner_value, "agent_policy.local_owner")
        _exact(scope, {"actions", "agent_ids", "pools"}, "agent_policy.local_owner")
        local_owner = LocalOwnerOperatorPolicy(
            _strings(scope, "actions", non_empty=True),
            _strings(scope, "agent_ids"),
            _strings(scope, "pools"),
        )
    return AgentPolicyConfig(
        revision=_string(value, "revision"),
        agents=tuple(agents),
        principals=tuple(principals),
        local_owner=local_owner,
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


def _executable_path(data: Mapping[str, object], field: str, base: Path) -> Path:
    """Make an executable entry path absolute without resolving its leaf symlink."""
    value = Path(_string(data, field))
    return Path(os.path.abspath(value if value.is_absolute() else base / value))


def _positive_int(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise QueueConfigError(f"{field} must be a positive integer")
    return value


def _non_negative_int(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if isinstance(value, str) and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QueueConfigError(f"{field} must be a non-negative integer")
    return value


def _positive_number(data: Mapping[str, object], field: str) -> float:
    value = data.get(field)
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError as exc:
            raise QueueConfigError(f"{field} must be positive") from exc
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise QueueConfigError(f"{field} must be positive")
    return float(value)


def _exact(data: Mapping[str, object], fields: set[str], label: str) -> None:
    if set(data) != fields:
        raise QueueConfigError(
            f"{label} must contain exactly: {', '.join(sorted(fields))}"
        )


def _required_allowed(
    data: Mapping[str, object],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    if not required <= set(data) or not set(data) <= required | optional:
        raise QueueConfigError(
            f"{label} must contain exactly the required fields and supported "
            f"extensions: {', '.join(sorted(required | optional))}"
        )


__all__ = [
    "CoordinatorServiceConfig",
    "DEPLOYMENT_CONFIG_SCHEMA_VERSION",
    "OutboundAgentRegistrationConfig",
    "OutboundAgentServiceConfig",
    "RunInspectionClientConfig",
    "load_coordinator_service_config",
    "load_outbound_agent_service_config",
    "load_run_inspection_client_config",
    "run_outbound_agent_service",
]
