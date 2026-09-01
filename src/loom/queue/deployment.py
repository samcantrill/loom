"""Protected, versioned configuration for supported queue role processes."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import stat
from threading import Event
from typing import Any, cast

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
    RunInspectionTlsClientConfig,
    _read_remote_agent_root_id,
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


DEPLOYMENT_CONFIG_SCHEMA_VERSION = 2
_OUTBOUND_OFFER_TTL_SECONDS = 30
_OUTBOUND_POLL_WAIT_MS = 5_000


@dataclass(frozen=True, slots=True)
class CoordinatorServiceConfig:
    daemon: LocalDaemonConfig
    agent_server: AgentTlsServerConfig | None
    source_path: Path
    immutable_fingerprint: str
    active_fingerprint: str


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


@dataclass(frozen=True, slots=True)
class RunInspectionClientConfig:
    """Protected configuration for the standalone read-only inspection client."""

    client: RunInspectionTlsClientConfig
    source_path: Path


def load_coordinator_service_config(path: str | Path) -> CoordinatorServiceConfig:
    source, payload, _ = _load_protected_config(path)
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
            "embedded_profile",
            "remote_profiles",
            "agent_policy",
            "agent_server",
            "authority",
        },
        {"scheduling", "embedded_agent", "slurm_profiles"},
        "coordinator service config",
    )
    _header(payload, "loom.coordinator-service")
    fingerprint = _canonical_fingerprint(_coordinator_immutable_projection(payload))
    active_fingerprint = _canonical_fingerprint(_coordinator_active_projection(payload))
    base = source.parent
    root = _path(payload, "deployment_root", base)
    embedded = _resident_profile(
        _mapping(payload, "embedded_profile"), base, "embedded_profile"
    )
    policy = _agent_policy(_mapping(payload, "agent_policy"))
    authority_factory = _coordinator_authority_factory(
        _mapping(payload, "authority"), base
    )
    scheduling, priority_resolver = _scheduling_composition(payload.get("scheduling"))
    embedded_providers = _embedded_provider_composition(payload.get("embedded_agent"))
    slurm_profiles = _slurm_profile_composition(payload.get("slurm_profiles"))
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
        active_configuration_fingerprint=active_fingerprint,
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
        coordinator_authority_factory=authority_factory,
        scheduling_components=scheduling,
        admission_priority_resolver=priority_resolver,
        agent_resource_providers=cast(Any, embedded_providers),
        slurm_profiles=cast(Any, slurm_profiles),
    )
    return CoordinatorServiceConfig(
        daemon, server, source, fingerprint, active_fingerprint
    )


def load_outbound_agent_service_config(
    path: str | Path,
) -> OutboundAgentServiceConfig:
    source, payload, _ = _load_protected_config(path)
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
        {"provider_factory"},
        "outbound agent service config",
    )
    _header(payload, "loom.outbound-agent-service")
    fingerprint = _canonical_fingerprint(_outbound_immutable_projection(payload))
    active_fingerprint = _canonical_fingerprint(_outbound_active_projection(payload))
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
    )


def load_run_inspection_client_config(path: str | Path) -> RunInspectionClientConfig:
    """Load the strict protected v1 remote inspection client configuration."""

    source, payload, _fingerprint = _load_protected_config(path)
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
    """Run one foreground agent role with bounded reconnect and poll loops."""

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
            client.resume_retained_work()
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
                profile = active.client.resident_profiles[0]
                gpu_descriptors = tuple(item.descriptor for item in profile.gpu_devices)
                (
                    provider_descriptors,
                    capacity_atoms,
                    reflected_claim_ids,
                ) = client._offer_provider_snapshot(  # noqa: SLF001
                    session_id=session.session_id,
                    availability_revision=session.availability_revision,
                    capacity_profile=profile,
                )
                gpu_atoms = tuple(
                    atom for atom in capacity_atoms if atom.owner_resource_kind == "gpu"
                )
                offer = AgentOffer(
                    session.session_id,
                    session.coordinator_epoch,
                    session.config_revision,
                    session.inventory_revision,
                    session.availability_revision,
                    sum(
                        atom.amount.numerator
                        for atom in capacity_atoms
                        if atom.owner_resource_kind == "cpu"
                    ),
                    sum(
                        atom.amount.numerator
                        for atom in capacity_atoms
                        if atom.owner_resource_kind == "memory"
                    ),
                    _OUTBOUND_OFFER_TTL_SECONDS,
                    provider_descriptors,
                    pools=session.pools,
                    reflected_claim_ids=reflected_claim_ids,
                    resident_profiles=tuple(
                        item.descriptor for item in active.client.resident_profiles
                    ),
                    gpu_devices=gpu_descriptors,
                    gpu_atoms=gpu_atoms,
                    capacity_atoms=capacity_atoms,
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

    embedded = _mapping(payload, "embedded_profile")
    profile = _mapping(embedded, "descriptor")
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
        "embedded_profile": {
            "descriptor": dict(profile),
        },
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


def _coordinator_active_projection(payload: Mapping[str, object]) -> dict[str, object]:
    embedded = _mapping(payload, "embedded_profile")
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
                "embedded_capacity": {
                    "cpu_capacity": embedded["cpu_capacity"],
                    "memory_capacity_bytes": embedded["memory_capacity_bytes"],
                    "gpu_devices": embedded["gpu_devices"],
                },
                "agent_policy": payload["agent_policy"],
                "agent_server_credentials": server_credentials,
                "remote_profiles": payload["remote_profiles"],
                "scheduling": payload.get("scheduling"),
                "embedded_agent": payload.get("embedded_agent"),
                "slurm_profiles": payload.get("slurm_profiles"),
            }
        ),
    )


def _outbound_active_projection(payload: Mapping[str, object]) -> dict[str, object]:
    return cast(
        dict[str, object],
        _without_paths(
            {
                "registration": payload["registration"],
                "reconnect_seconds": payload["reconnect_seconds"],
                "resident_profiles": payload["resident_profiles"],
                "provider_factory": payload.get("provider_factory"),
            }
        ),
    )


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
        _executable_path(value, "python_executable", base),
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
