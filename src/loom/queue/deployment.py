"""Protected, versioned configuration for supported queue role processes."""

from __future__ import annotations

from .operations import OperatorObservation

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
import hashlib
from importlib import import_module
import json
import logging
import math
import os
from pathlib import Path
import re
import stat
from threading import Event
from time import monotonic
from types import MappingProxyType
from typing import Any, cast
from urllib.parse import urlsplit

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

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
from ._agent_progress import _steps, _delay, _Spawn, _set_assignment_owner
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
from .preparation import (
    PREPARATION_INPUT_CAPABILITY,
    PREPARATION_STAGED_INPUT_CAPABILITY,
)


_LOGGER = logging.getLogger(__name__)


@dataclass
class _RecoveryRetry:
    """Volatile retry pacing and redacted diagnostics for one retained owner."""

    attempts: int = 0
    state: object = None
    signature: object = None
    reported_at: float = -math.inf

    def observe_progress(self, state: object) -> None:
        if state != self.state:
            self.attempts = 0
            self.state = state

    def failed(self, error: Exception, *, assignment_id: str,
               operation_id: str | None, state: object) -> float:
        self.observe_progress(state)
        self.attempts += 1
        cause = error.__cause__ or error
        step = getattr(error, "_agent_external_step", "resume_retained_assignment")
        dispatched = getattr(error, "possibly_dispatched", None)
        signature = (step, type(cause).__name__, dispatched)
        now = monotonic()
        if signature != self.signature or now - self.reported_at >= 30:
            _LOGGER.warning("retained assignment recovery pending: %s", json.dumps({
                "assignment_id": assignment_id, "operation_id": operation_id,
                "step": step, "cause_type": type(cause).__name__,
                "possibly_dispatched": dispatched, "retry_count": self.attempts,
            }, sort_keys=True))
            self.signature = signature
            self.reported_at = now
        return min(5.0, 0.1 * 2 ** min(self.attempts - 1, 6))


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
    event_observers: Any = field(default=None, repr=False, compare=False)


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
class AgentSpec:
    """Protected outbound declarations, without execution qualification.

    ``declarations`` is a deeply immutable tree with normalized defaults and
    private path bindings. Its digest identifies declarations, not installed
    software or observed hardware. Executable paths preserve their symlink
    spelling. The source and environment filenames are provenance only.
    Obtain a spec with :func:`read_agent_spec`; pass it to
    :func:`qualify_agent_spec` when execution evidence is required.
    """

    source_path: Path
    environment_path: Path | None
    agent_root: Path
    declaration_digest: str
    declarations: Mapping[str, PlainData] = field(repr=False)
    # Preserve the published fingerprint projections' authored representation.
    _payload: Mapping[str, object] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "declarations", freeze_plain_data(self.declarations))
        object.__setattr__(self, "_payload", freeze_plain_data(self._payload))


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
    _deadline: float | None = None,
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
        {"scheduling", "slurm_profiles", "preparation", "event_sinks", "shared_roots", "assignment_payload_root_id"},
        "coordinator service config",
    )
    from ._lifecycle_observers import LifecycleObservers, parse_event_sinks

    observers = LifecycleObservers(parse_event_sinks(payload.get("event_sinks")))
    _header(payload, "loom.coordinator-service")
    payload = _normalize_coordinator_payload(payload)
    base = source.parent
    root = _path(payload, "deployment_root", base)
    local_agent = _local_agent_service(
        payload["local_agent"], base, allow_unready=_allow_unready, deadline=_deadline
    )
    remote_profiles = tuple(
        _profile_descriptor(_mapping_value(value, f"remote_profiles[{index}]"))
        for index, value in enumerate(_sequence(payload, "remote_profiles"))
    )
    preparation_policy = load_preparation_policy(
        payload.get("preparation"),
        local_agent_id=_string(payload, "machine_id"),
        local_launch_profile=None
        if local_agent is None
        else local_agent.profile.launch_profile,
        base=base,
        descriptors=(
            *remote_profiles,
            *((local_agent.profile.descriptor,) if local_agent is not None else ()),
        ),
    )
    authority_factory = _coordinator_authority_factory(
        _mapping(payload, "authority"), base, deployment_root=root
    )
    coordinator_identity = _coordinator_immutable_projection(payload)
    if "state_root" in _mapping(payload, "authority"):
        from loom.pipeline.stores.coordinator_authority import (
            coordinator_authority_identity,
        )

        coordinator_identity["authority"] = coordinator_authority_identity(
            authority_factory
        )
    fingerprint = _canonical_fingerprint(
        {
            "coordinator": coordinator_identity,
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
        shared_roots=cast(Mapping[str, PlainData], payload.get("shared_roots", {})),
        assignment_payload_root_id=cast(str | None, payload.get("assignment_payload_root_id")),
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
        event_observers=observers,
    )


def load_outbound_agent_service_config(
    path: str | Path,
    *,
    env_file: str | Path | None = None,
    _allow_unready: bool = False,
    _deadline: float | None = None,
) -> OutboundAgentServiceConfig:
    """Read protected declarations and fully qualify the selected installation."""
    return qualify_agent_spec(
        read_agent_spec(path, env_file=env_file),
        _allow_unready=_allow_unready,
        _deadline=_deadline,
    )


def read_agent_spec(
    path: str | Path, *, env_file: str | Path | None = None
) -> AgentSpec:
    """Read and normalize an outbound declaration without probing execution.

    Protected YAML/includes and the explicit environment remain mandatory.
    No worker imports, container probes, image hashing, hardware discovery or
    trusted factory construction occur. Referenced execution files need not
    exist. This snapshot alone does not authorize execution or root ownership.
    """
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
        {
            "provider_factory",
            "resources",
            "slurm_profiles",
            "max_concurrent_assignments",
        },
        "outbound agent service config",
    )
    _header(payload, "loom.outbound-agent-service")
    max_concurrent_assignments = payload.get("max_concurrent_assignments", 1)
    if (
        isinstance(max_concurrent_assignments, bool)
        or not isinstance(max_concurrent_assignments, int)
        or not 1 <= max_concurrent_assignments <= 1024
    ):
        raise QueueConfigError(
            "max_concurrent_assignments must be an integer from 1 through 1024"
        )
    if payload.get("slurm_profiles") and max_concurrent_assignments > 1:
        raise QueueConfigError(
            "max_concurrent_assignments above one is unsupported with slurm_profiles"
        )
    payload = _normalize_outbound_agent_payload(payload)
    base = source.parent
    registration = _outbound_registration(payload)
    declarations = dict(payload)
    for name in (
        "agent_root",
        "server_ca_path",
        "certificate_path",
        "private_key_path",
    ):
        declarations[name] = str(_path(payload, name, base))
    # The transport constructor is inert with no execution profiles or factory.
    AgentTlsClientConfig(
        url=_string(payload, "url"),
        server_ca_path=Path(cast(str, declarations["server_ca_path"])),
        certificate_path=Path(cast(str, declarations["certificate_path"])),
        private_key_path=Path(cast(str, declarations["private_key_path"])),
    )
    declarations["max_concurrent_assignments"] = max_concurrent_assignments
    declarations["registration"] = asdict(registration)
    declarations["resources"] = _agent_resource_declaration(payload.get("resources"))
    occupancy_policy = _gpu_occupancy_policy(payload.get("resources"))
    if occupancy_policy is not None and payload.get("provider_factory") is not None:
        raise QueueConfigError(
            "NVIDIA occupancy cannot be bypassed by a custom provider factory"
        )
    if declarations["resources"] is not None:
        resources = cast(dict[str, object], declarations["resources"])
        gpu = cast(dict[str, object], resources["gpu"])
        gpu["occupancy"] = (
            None if occupancy_policy is None else occupancy_policy.to_dict()
        )
    declarations["provider_factory"] = payload.get("provider_factory")
    if payload.get("provider_factory") is not None:
        _trusted_target_name(
            _mapping(payload, "provider_factory"), "remote provider factory"
        )
    slurm = _slurm_profile_declarations(payload.get("slurm_profiles"))
    declarations["slurm_profiles"] = slurm
    preparation_staged = (
        PREPARATION_STAGED_INPUT_CAPABILITY in registration.capabilities
    )
    preparation = (
        PREPARATION_INPUT_CAPABILITY in registration.capabilities or preparation_staged
    )
    profiles = [
        _resident_profile_declaration(
            _mapping_value(value, f"resident_profiles[{index}]"),
            base,
            f"resident_profiles[{index}]",
            preparation=preparation,
            preparation_staged=preparation_staged,
        )
        for index, value in enumerate(_sequence(payload, "resident_profiles"))
    ]
    if not profiles and not slurm:
        raise QueueConfigError(
            "resident_profiles must not be empty without external SLURM profiles"
        )
    declarations["resident_profiles"] = profiles
    if len(
        {
            cast(Mapping[str, object], profile["descriptor"])["profile_id"]
            for profile in profiles
        }
    ) != len(profiles):
        raise QueueConfigError("agent resident profile IDs must be unique")
    if declarations["resources"] is not None and not profiles:
        raise QueueConfigError("agent resource inventory requires a resident profile")
    if declarations["resources"] is None and profiles:
        capacities = [
            (
                profile["cpu_capacity"],
                profile["memory_capacity_bytes"],
                [
                    device["descriptor"]
                    for device in cast(list[dict[str, object]], profile["gpu_devices"])
                ],
            )
            for profile in profiles
        ]
        if any(capacity != capacities[0] for capacity in capacities[1:]):
            raise QueueConfigError(
                "agent resident profiles must share one capacity domain"
            )
    # Trusted constructors own their opaque arguments, including any relative
    # paths. Bind their invocation directory without interpreting those values.
    if payload.get("provider_factory") is not None or slurm:
        declarations["composition_directory"] = str(Path.cwd())
    plain = cast(Mapping[str, object], thaw_plain_data(declarations))
    return AgentSpec(
        source,
        environment_path,
        Path(cast(str, declarations["agent_root"])),
        _canonical_fingerprint(plain),
        cast(Mapping[str, PlainData], declarations),
        payload,
    )


def qualify_agent_spec(
    spec: AgentSpec, *, _allow_unready: bool = False, _deadline: float | None = None
) -> OutboundAgentServiceConfig:
    """Qualify a declaration snapshot using the normal execution checks.

    This observes software and resources and constructs trusted providers.
    Existing software, immutable and active fingerprints retain their meanings;
    declaration evidence is separate and is never inferred for programmatic
    service configurations. Protected inputs are snapshotted by the reader.
    """
    source, environment_path = spec.source_path, spec.environment_path
    payload = cast(dict[str, object], thaw_plain_data(spec._payload))
    directory = spec.declarations.get("composition_directory")
    if directory is not None and directory != str(Path.cwd()):
        raise QueueConfigError(
            "agent composition directory changed after declaration read"
        )
    for name in (
        "agent_root",
        "server_ca_path",
        "certificate_path",
        "private_key_path",
    ):
        payload[name] = spec.declarations[name]
    for authored, declared in zip(
        _sequence(payload, "resident_profiles"),
        cast(Sequence[Mapping[str, PlainData]], spec.declarations["resident_profiles"]),
        strict=True,
    ):
        profile = cast(dict[str, object], authored)
        for name in ("project_root", "python_executable"):
            profile[name] = declared[name]
        if "preparation_shared_roots" in profile:
            profile["preparation_shared_roots"] = thaw_plain_data(
                declared["preparation_shared_roots"]
            )
    base = source.parent
    max_concurrent_assignments = cast(int, payload.get("max_concurrent_assignments", 1))
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
            deadline=_deadline,
            preparation=preparation,
            preparation_staged=preparation_staged,
        )
        for index, value in enumerate(_sequence(payload, "resident_profiles"))
    )
    if not profiles and not payload.get("slurm_profiles"):
        raise QueueConfigError(
            "resident_profiles must not be empty without external SLURM profiles"
        )
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
                **({"shared_roots": dict(profile.shared_roots)} if profile.shared_roots else {}),
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
    registration = _outbound_registration(payload)
    provider_factory = None
    if payload.get("provider_factory") is not None:
        provider_factory = _trusted_target(
            _mapping(payload, "provider_factory"), "remote provider factory"
        )
        if not callable(provider_factory):
            raise QueueConfigError("remote provider factory target is invalid")
    client = AgentTlsClientConfig(
        max_concurrent_assignments=max_concurrent_assignments,
        url=_string(payload, "url"),
        server_ca_path=_path(payload, "server_ca_path", base),
        certificate_path=_path(payload, "certificate_path", base),
        private_key_path=_path(payload, "private_key_path", base),
        agent_root=_path(payload, "agent_root", base),
        slurm_profiles=cast(
            Any, _slurm_profile_composition(payload.get("slurm_profiles"))
        ),
        resident_profiles=profiles,
        resource_inventory=resource_inventory,
        gpu_occupancy_policy=occupancy_policy,
        agent_resource_provider_factory=cast(Any, provider_factory),
        deployment_configuration_fingerprint=fingerprint,
        active_configuration_fingerprint=active_fingerprint,
        declaration_digest=spec.declaration_digest,
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


def _outbound_registration(payload: Mapping[str, object]) -> OutboundAgentRegistrationConfig:
    value = _mapping(payload, "registration")
    _exact(
        value,
        {"config_revision", "inventory_revision", "availability_revision", "pools", "capabilities"},
        "outbound agent registration",
    )
    return OutboundAgentRegistrationConfig(
        config_revision=_string(value, "config_revision"),
        inventory_revision=_string(value, "inventory_revision"),
        availability_revision=_string(value, "availability_revision"),
        pools=_strings(value, "pools", non_empty=True),
        capabilities=_strings(value, "capabilities", non_empty=True),
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
    lifetime: str | None = None,
    expected_coordinator_id: str | None = None,
) -> None:
    """Progress bounded resident assignments with independent control receipts.

    The configured assignment ceiling is advertised unchanged; this service
    manages independent deliveries fairly. Application stop preserves processes and
    claims and waits for its finite external operations before closing transport.
    """
    from ._agent_progress import _run_manager

    observing: list[LocalDaemonAgentHttpClient | None] = [None]

    def controls():
        while not stop.is_set():
            client = observing[0]
            if client is not None:
                try:
                    yield from client._receive_service_controls()
                except _ManagedApplicationSuspended:
                    # A closing client also suspends during reconnect; the
                    # service's receipt owner continues with its replacement.
                    pass
                except (QueueError, AgentProcessSupervisorError):
                    pass
            yield from _delay(0.05)

    _run_manager(
        _outbound_service_steps(
            config, stop=stop, trusted_config_loader=trusted_config_loader,
            lifetime=lifetime, expected_coordinator_id=expected_coordinator_id,
            observing=observing,
        ),
        controls(),
    )


def _outbound_service_steps(
    config: OutboundAgentServiceConfig,
    *,
    stop: Event,
    trusted_config_loader: Callable[[], OutboundAgentServiceConfig] | None = None,
    lifetime: str | None = None,
    expected_coordinator_id: str | None = None,
    observing: list[LocalDaemonAgentHttpClient | None],
):
    """Run a foreground agent, preserving supervised work on service stop.

    Stop interrupts active and retained-worker observation at durable replay
    boundaries. It does not cancel jobs or release their claims. In-flight
    transport operations retain their configured timeouts before suspension.
    """

    from uuid import uuid4

    generation = str(uuid4())
    active = config
    from .retirement import require_unretired
    if active.client.agent_root is not None:
        require_unretired(active.client.agent_root)
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
    client._service_progress = True
    client._suspend_requested = stop.is_set
    observing[0] = client
    from ._service_lifetime import record_process, retained_lifetime

    if active.client.agent_root is not None:
        try:
            lifetime = retained_lifetime(active.client.agent_root, lifetime)
            record_process(active.client.agent_root, stopped=False)
        except BaseException:
            client.close()
            raise
    else:
        lifetime = lifetime or "persistent"
    while True:
        assignments = {}
        recovery = None
        suspended = Event()

        def suspending(suspended=suspended):
            return stop.is_set() or suspended.is_set()

        def recover(reference):
            assert client is not None
            _set_assignment_owner(reference[1])
            retry = _RecoveryRetry()

            def progress():
                assert client is not None
                journal = client._execution_journal
                state = None if journal is None else journal.find_state(reference[1])
                fence = None if journal is None or state is None else journal.read_grant_fence(reference[1])
                return state, fence

            while not suspending():
                delay = 0.1
                try:
                    yield from _steps(
                        client._resume_retained_assignments, (reference,),
                        suspend_requested=suspending,
                    )
                except (QueueError, AgentProcessSupervisorError) as error:
                    state, fence = progress()
                    delay = retry.failed(
                        error, assignment_id=reference[1],
                        operation_id=None if fence is None else f"{reference[1]}:launch:{fence}",
                        state=state,
                    )
                if reference not in client._require_journal().unresolved_assignment_references():
                    return
                retry.observe_progress(progress()[0])
                yield from _delay(delay)

        def delivered(reference, delivery):
            assert client is not None
            session_id, assignment_id = reference
            _set_assignment_owner(assignment_id)
            request = yield from _steps(client._resolve_delivery, session_id, delivery.get("request"))
            return (yield from _steps(client._execute_delivered_assignment,
                session_id, request, suspend_requested=suspending))

        def repair_session():
            assert client is not None
            yield from _steps(client._replay_pending_reconciliation)
            yield from _steps(client._resume_pending_poll,
                wait_timeout_ms=_OUTBOUND_POLL_WAIT_MS,
                suspend_requested=suspending)

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
            client._service_progress = True
            client._suspend_requested = suspending
            observing[0] = client
            recovery = yield _Spawn(repair_session())
            journal = client._require_journal()
            # Every known startup owner progresses independently. Poll recovery
            # closes the inventory; admission then proves ownership, not exit.
            while not stop.is_set():
                for reference in journal.unresolved_assignment_references():
                    if reference not in assignments:
                        assignments[reference] = yield _Spawn(recover(reference))
                for reference, view in tuple(assignments.items()):
                    if view.complete:
                        del assignments[reference]
                        if view.error is not None:
                            raise view.error
                if recovery.complete:
                    if recovery.error is not None:
                        raise recovery.error
                    break
                yield from _delay(0.01)
            if stop.is_set():
                return
            handshake = (yield from _steps(client.handshake))
            coordinator_epoch = cast(str, handshake["coordinator_epoch"])
            coordinator_id = cast(str, handshake["coordinator_id"])
            if (
                expected_coordinator_id is not None
                and coordinator_id != expected_coordinator_id
            ):
                raise QueueConflictError(
                    "outbound agent coordinator identity conflicts"
                )
            session = client.active_session()
            if session is None:
                operation_id = _operation_id(
                    "register",
                    client.agent_root_id,
                    active.registration.config_revision,
                    *((generation,) if lifetime == "run" else ()),
                )
                session = (yield from _steps(client.register,
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
                ))
            elif session.coordinator_epoch != coordinator_epoch:
                session = (yield from _steps(client.reconcile,
                    session.session_id,
                    coordinator_epoch,
                    idempotency_key=_operation_id(
                        "reconcile", session.session_id, coordinator_epoch
                    ),
                ))
            # External jobs retain ownership too, but use the existing serial
            # scheduler driver, not resident assignment views. Reconcile first
            # and settle them before admitting fresh work after restart.
            while client._slurm_agent is not None and client._slurm_agent.has_retained_work():
                if stop.is_set():
                    return
                yield from _steps(client.drive_slurm_jobs)
                yield from _delay(0.05)
            if lifetime != "run" and active.client.agent_root is not None:
                record_process(
                    active.client.agent_root,
                    stopped=False,
                    coordinator_id=coordinator_id,
                    session_id=session.session_id,
                )
            while not stop.is_set():
                for reference, view in tuple(assignments.items()):
                    if view.complete:
                        del assignments[reference]
                        if view.error is not None:
                            raise view.error
                if lifetime == "run":
                    retirement = {
                        "session_id": session.session_id,
                        "coordinator_epoch": coordinator_epoch,
                        "generation": generation,
                        "action": "observe",
                    }
                    decision = (yield from _steps(client._call, "service_lifetime", retirement))
                    if decision.get("state") == "authorized":
                        if decision.get("coordinator_id") != coordinator_id or any(
                            decision.get(key) != retirement[key]
                            for key in ("session_id", "coordinator_epoch", "generation")
                        ):
                            raise QueueConflictError(
                                "service retirement evidence is stale"
                            )
                        (yield from _steps(client.retire_clean,
                            session.session_id,
                            idempotency_key="service-retire-" + generation,
                        ))
                        client.shutdown_clean()
                        (yield from _steps(client._call,
                            "service_lifetime", {**retirement, "action": "closed"}
                        ))
                        if active.client.agent_root is not None:
                            record_process(
                                active.client.agent_root,
                                stopped=True,
                                coordinator_id=coordinator_id,
                                session_id=session.session_id,
                            )
                        return
                    if active.client.agent_root is not None:
                        record_process(
                            active.client.agent_root,
                            stopped=False,
                            coordinator_id=coordinator_id,
                            session_id=session.session_id,
                        )
                if client._service_control_due:
                    client._service_control_due = False
                    yield from _steps(client.poll_control, session.session_id)
                session = client.active_session()
                if session is None:
                    raise QueueServiceError("agent session ended without retirement")
                client._resource_maintenance_enabled = True  # noqa: SLF001
                if monotonic() >= client._next_resource_maintenance:
                    policy = active.client.gpu_occupancy_policy
                    interval = min(5.0, _OUTBOUND_OFFER_TTL_SECONDS / 2)
                    if policy is not None:
                        interval = min(interval, policy.poll_interval_seconds)
                    client._next_resource_maintenance = monotonic() + interval
                    yield from _steps(client.refresh_resource_offer, ttl_seconds=_OUTBOUND_OFFER_TTL_SECONDS)
                session = client.active_session()
                if session is None:
                    raise QueueServiceError("agent session ended without retirement")
                yield from _steps(client.drive_slurm_jobs)
                if client._drained or client._restart_with_retained_work or len(journal.unresolved_assignment_references()) >= active.client.max_concurrent_assignments:
                    yield from _delay(0.05)
                    continue
                sequence = client.next_poll_sequence(session.session_id)
                delivery = (yield from _steps(client.wait_for_work,
                    session.session_id,
                    session.availability_revision,
                    sequence=sequence,
                    wait_timeout_ms=_OUTBOUND_POLL_WAIT_MS,
                ))
                if delivery.get("result") == "assignment":
                    # complete_poll already owns the original request by ID.
                    for reference in journal.unresolved_assignment_references():
                        if reference not in assignments:
                            assignments[reference] = yield _Spawn(delivered(reference, delivery))
                session = client.active_session()
                if session is None:
                    raise QueueServiceError("agent session ended without retirement")
        except _ManagedApplicationSuspended:
            return
        except QueueError:
            if stop.is_set():
                return
            (yield from _delay(active.reconnect_seconds))
        finally:
            suspended.set()
            observing[0] = None
            while any(not view.complete for view in assignments.values()) or (recovery is not None and not recovery.complete):
                yield from _delay(0.01)
            if client is not None:
                observing[0] = None
                closing = client
                client = None
                try:
                    if lifetime != "run" or stop.is_set():
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
    value: object,
    base: Path,
    *,
    allow_unready: bool = False,
    deadline: float | None = None,
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
            deadline=deadline,
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

    resources = _agent_resource_declaration(value)
    if resources is None:
        return None, None
    gpu = _mapping(resources, "gpu")
    selection = _string(gpu, "devices")
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


def _agent_resource_declaration(value: object) -> dict[str, object] | None:
    """Validate declared capacity without discovering hardware or host limits."""
    if value is None:
        return None
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
    _string(gpu, "devices")
    if provider != "nvidia":
        raise QueueConfigError("agent GPU resource provider is unsupported")
    return {
        "cpu_capacity": _positive_int(resources, "cpu_capacity"),
        "memory_capacity_bytes": _non_negative_int(resources, "memory_capacity_bytes"),
        "gpu": dict(gpu),
    }


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
    *,
    deployment_root: Path,
) -> CoordinatorAuthorityFactory:
    """Construct one explicit trusted authority factory for this role.

    Embedded access is intentionally the only default.  A persistent role must
    name its already-authenticated, run-scoped adapter factory explicitly; the
    deployment loader never discovers targets or falls back to SQLite.
    """

    kind = _string(value, "kind")
    if kind == "embedded":
        _required_allowed(value, {"kind"}, {"state_root"}, "embedded authority")
        if "state_root" in value:
            from loom.pipeline.stores.coordinator_authority import (
                EmbeddedCoordinatorAuthorityFactory,
            )
            from loom.pipeline.stores.authority import AuthorityStoreError

            try:
                return cast(
                    CoordinatorAuthorityFactory,
                    EmbeddedCoordinatorAuthorityFactory(
                        state_root=_path(value, "state_root", base),
                        deployment_root=deployment_root,
                    ),
                )
            except AuthorityStoreError as exc:
                raise QueueConfigError(str(exc)) from exc
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

    module_name, attribute = _trusted_target_name(value, label)
    kwargs = {
        key: _construct_trusted_value(item, f"{label}.{key}")
        for key, item in value.items()
        if key != "_target_"
    }
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


def _trusted_target_name(value: Mapping[str, object], label: str) -> tuple[str, str]:
    target = _string(value, "_target_")
    module_name, separator, attribute = target.rpartition(".")
    if not separator or not module_name or not attribute:
        raise QueueConfigError(f"{label} target is invalid")
    return module_name, attribute


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

    declarations = _slurm_profile_declarations(value)
    if not declarations:
        return ()
    from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile

    profiles: list[SlurmReadyStageProfile] = []
    for index, mapping in enumerate(declarations):
        label = f"slurm_profiles[{index}]"
        if "_target_" in mapping:
            target = _trusted_target(mapping, label)
            if not isinstance(target, SlurmReadyStageProfile):
                raise QueueConfigError(f"{label} target is not a ready-stage profile")
            profiles.append(target)
            continue
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


def _slurm_profile_declarations(value: object) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise QueueConfigError("slurm_profiles must be a sequence")
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
        "container_options",
        "apptainer_options",
        "executor_name",
        "credential_policy_revision",
        "account",
        "qos",
        "cluster",
        "available",
        "poll_interval_seconds",
        "containment_helper",
        "result_storage",
    }
    declarations = []
    for index, item in enumerate(value):
        label = f"slurm_profiles[{index}]"
        mapping = _mapping_value(item, label)
        if "_target_" in mapping:
            _trusted_target_name(mapping, label)
        else:
            _required_allowed(mapping, required, optional, label)
        declarations.append(mapping)
    return tuple(declarations)


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
                **({"assignment_payload_root_id": payload["assignment_payload_root_id"]} if payload.get("assignment_payload_root_id") is not None else {}),
                **({"shared_roots_digest": _canonical_fingerprint(_mapping(payload, "shared_roots"))} if payload.get("shared_roots") else {}),
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
        **({"shared_roots_digest": hashlib.sha256(json.dumps(dict(profile.shared_roots), sort_keys=True).encode()).hexdigest()} if profile.shared_roots else {}),
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
            if key not in {"readiness", "preparation_shared_roots", "container", "shared_roots"}
        }
        for value in _sequence(payload, "resident_profiles")
    ]
    for profile, value in zip(
        profiles, _sequence(payload, "resident_profiles"), strict=True
    ):
        shared = _mapping_value(value, "resident profile").get("shared_roots")
        if shared:
            profile["shared_roots_digest"] = hashlib.sha256(json.dumps(shared, sort_keys=True).encode()).hexdigest()
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
                "slurm_profiles": payload.get("slurm_profiles"),
                **(
                    {
                        "max_concurrent_assignments": payload[
                            "max_concurrent_assignments"
                        ]
                    }
                    if payload.get("max_concurrent_assignments", 1) != 1
                    else {}
                ),
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
    deadline: float | None = None,
    preparation: bool = False,
    preparation_staged: bool = False,
) -> ResidentExecutionProfile:
    profile = ResidentExecutionProfile(
        **_resident_profile_arguments(
            value,
            base,
            label,
            preparation=preparation,
            preparation_staged=preparation_staged,
        )
    )
    profile = qualified_resident_profile(profile, _deadline=deadline)
    result = profile.readiness_result
    assert result is not None
    if not result.ok and not allow_unready:
        failed = next(item for item in result.checks if item.status == "FAIL")
        raise QueueConfigError(
            f"resident profile readiness failed ({failed.check_id}): {failed.message}"
        )
    return profile


def _resident_profile_arguments(
    value: Mapping[str, object],
    base: Path,
    label: str,
    *,
    preparation: bool = False,
    preparation_staged: bool = False,
) -> dict[str, Any]:
    """Parse profile fields without constructing an execution profile."""
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
        {"readiness", "preparation_shared_roots", "container", "shared_roots"},
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
    if any(not key for key in environment):
        raise QueueConfigError(f"{label}.environment names must not be empty")
    AgentResourceInventory(
        _positive_int(value, "cpu_capacity"),
        _non_negative_int(value, "memory_capacity_bytes"),
        tuple(devices),
    )
    requirements = _resident_readiness_requirements(value.get("readiness"))
    if preparation:
        requirements = replace(requirements, preparation=True)
    if preparation_staged:
        requirements = replace(requirements, preparation_staged=True)
    return dict(
        descriptor=_resident_descriptor_declaration(_mapping(value, "descriptor")),
        project_root=_path(value, "project_root", base),
        python_executable=_executable_path(value, "python_executable", base),
        cpu_capacity=_positive_int(value, "cpu_capacity"),
        memory_capacity_bytes=_non_negative_int(value, "memory_capacity_bytes"),
        gpu_devices=tuple(devices),
        environment=cast(Mapping[str, str], environment),
        readiness_requirements=requirements,
        container=cast(Mapping[str, PlainData] | None, value.get("container")),
        shared_roots=cast(Mapping[str, PlainData], value.get("shared_roots", {})),
        preparation_shared_roots={
            alias: _path({"root": path}, "root", base)
            for alias, path in _mapping_value(
                value.get("preparation_shared_roots", {}), "preparation shared roots"
            ).items()
        },
    )


def _resident_profile_declaration(
    value: Mapping[str, object],
    base: Path,
    label: str,
    *,
    preparation: bool,
    preparation_staged: bool,
) -> dict[str, object]:
    from ._agent_process_supervisor import _preparation_root_bindings
    from ._container_worker import container_binding
    from .shared_execution import root_bindings

    arguments = _resident_profile_arguments(
        value,
        base,
        label,
        preparation=preparation,
        preparation_staged=preparation_staged,
    )
    descriptor = arguments["descriptor"]
    requirements = asdict(arguments.pop("readiness_requirements"))
    project = arguments["project_root"]
    # Readiness paths use the worker's project frame, which may be a container
    # namespace. Preserve '..' since its meaning can depend on worker symlinks.
    requirements["source_roots"] = [
        str(project / root) for root in requirements["source_roots"]
    ]
    requirements["import_roots"] = {
        name: str(project / root) for name, root in requirements["import_roots"].items()
    }
    requirements["lockfile"] = str(project / requirements["lockfile"])
    return {
        **arguments,
        "descriptor": {
            "profile_id": descriptor.profile_id,
            "revision": descriptor.revision,
        },
        "project_root": str(project),
        "python_executable": str(arguments["python_executable"]),
        "gpu_devices": [
            {
                "descriptor": device.descriptor.to_dict(),
                "binding_value": device.binding_value,
            }
            for device in arguments["gpu_devices"]
        ],
        "readiness": requirements,
        "container": container_binding(arguments["container"]),
        "shared_roots": root_bindings(arguments["shared_roots"]),
        "preparation_shared_roots": {
            alias: str(path)
            for alias, path in _preparation_root_bindings(
                arguments["preparation_shared_roots"]
            ).items()
        },
    }


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
        {"project_fingerprint", "environment_fingerprint", "executor_fingerprint", "shared_roots"},
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
        agent = {"external_slurm_profiles": [], **agent}
        _exact(
            agent,
            {
                "credential_id",
                "principal_id",
                "agent_id",
                "pools",
                "capabilities",
                "gpu_devices",
                "external_slurm_profiles",
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
                external_slurm_profiles=cast(
                    tuple[tuple[str, str], ...],
                    tuple(
                        tuple(cast(Sequence[str], item))
                        for item in _sequence(agent, "external_slurm_profiles")
                    ),
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
    "AgentSpec",
    "CoordinatorServiceConfig",
    "DEPLOYMENT_CONFIG_SCHEMA_VERSION",
    "OutboundAgentRegistrationConfig",
    "OutboundAgentServiceConfig",
    "RunInspectionClientConfig",
    "load_coordinator_service_config",
    "load_outbound_agent_service_config",
    "load_run_inspection_client_config",
    "qualify_agent_spec",
    "read_agent_spec",
    "run_outbound_agent_service",
]


def inspect_role_declaration(
    path: str | Path, *, role: str, env_file: str | Path | None = None
) -> "OperatorObservation":
    """Parse protected role declarations without qualification or factory imports.

    The fingerprint identifies declarations, not installed software. Credentials,
    environment values and private paths are omitted from the public projection.
    Protected source failures are reported without echoing configuration values.
    """
    from .operations import OperatorObservation
    from loom.timestamps import utc_timestamp

    if role not in {"agent", "coordinator"}:
        raise QueueConfigError("role must be agent or coordinator")
    if role == "agent":
        spec = read_agent_spec(path, env_file=env_file)
        fingerprint = spec.declaration_digest
        profiles = cast(Sequence[Mapping[str, object]], spec.declarations["resident_profiles"])
        identities = [cast(PlainData, profile["descriptor"]) for profile in profiles]
    else:
        source, _, payload, _ = _load_protected_config(path, env_file=env_file)
        _required_allowed(payload, {"schema_version", "kind", "deployment_root", "run_store_root", "machine_id", "poll_interval_seconds", "max_accepted_time_step_seconds", "local_agent", "remote_profiles", "agent_policy", "agent_server", "authority"}, {"scheduling", "slurm_profiles", "preparation", "event_sinks", "shared_roots", "assignment_payload_root_id"}, "coordinator service config")
        _header(payload, "loom.coordinator-service")
        normalized = dict(_normalize_coordinator_payload(payload))
        if payload["agent_server"] is not None:
            _agent_server(_mapping(payload, "agent_server"), source.parent)
        for name in ("deployment_root", "run_store_root"):
            normalized[name] = str(_path(payload, name, source.parent))
        _string(payload, "machine_id")
        _agent_policy(_mapping(payload, "agent_policy"))
        authority = _mapping(payload, "authority")
        if authority.get("kind") == "embedded":
            _required_allowed(authority, {"kind"}, {"state_root"}, "embedded authority")
            if "state_root" in authority:
                _path(authority, "state_root", source.parent)
        elif authority.get("kind") == "https":
            _exact(authority, {"kind", "url", "service_id", "workspace_id", "tls"}, "HTTPS authority")
            for key in ("url", "service_id", "workspace_id"):
                _string(authority, key)
            tls = _mapping(authority, "tls")
            _exact(tls, {"ca", "certificate", "private_key"}, "HTTPS authority TLS")
            for key in tls:
                _path(tls, key, source.parent)
        else:
            raise QueueConfigError("authority kind is unsupported")
        _slurm_profile_declarations(payload.get("slurm_profiles"))
        identities = [cast(PlainData, _profile_descriptor(_mapping_value(item, "remote profile")).to_dict()) for item in _sequence(payload, "remote_profiles")]
        if payload["local_agent"] is not None:
            reference = _mapping(payload, "local_agent")
            _exact(reference, {"config", "env_file"}, "local_agent")
            local_source, _, local, _ = _load_protected_config(_path(reference, "config", source.parent), env_file=None if reference["env_file"] is None else _path(reference, "env_file", source.parent))
            _required_allowed(local, {"schema_version", "kind", "agent_root", "resident_profiles"}, {"providers", "resources"}, "local agent service config")
            _header(local, "loom.local-agent-service")
            _path(local, "agent_root", local_source.parent)
            _agent_resource_declaration(local.get("resources"))
            occupancy = _gpu_occupancy_policy(local.get("resources"))
            if occupancy is not None and local.get("providers") is not None:
                raise QueueConfigError("NVIDIA occupancy cannot be bypassed by custom providers")
            profiles = [_resident_profile_declaration(_mapping_value(item, "resident profile"), local_source.parent, "resident profile", preparation=False, preparation_staged=False) for item in _sequence(local, "resident_profiles")]
            if len(profiles) != 1:
                raise QueueConfigError("local agent service requires one resident profile")
            normalized["local_agent"] = {**local, "resident_profiles": profiles}
            identities.extend(cast(PlainData, profile["descriptor"]) for profile in profiles)
        # Opaque trusted targets are declarations here. Their actual constructors
        # own qualification; reading this document must never import them.
        def targets(value: object) -> None:
            if isinstance(value, Mapping):
                if "_target_" in value:
                    _trusted_target_name(value, "role declaration target")
                for child in value.values():
                    targets(child)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    targets(child)
        targets(normalized)
        fingerprint = _canonical_fingerprint(normalized)
    return OperatorObservation("role-declaration", utc_timestamp(), fingerprint, "current", "available", {"role": role, "declaration_fingerprint": fingerprint, "protected_paths": "validated", "profile_identities": identities, "credentials": "redacted", "qualified": False})
