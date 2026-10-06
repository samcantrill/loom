"""Small mutual-TLS adapter for the restricted agent-session view.

The adapter derives a configured credential ID from the verified client
certificate's DER fingerprint.  It never accepts an actor, principal, agent,
or session selector from the HTTP path as transport identity.
"""

from __future__ import annotations

from . import _agent_session_protocol as _session_protocol
from ._agent_session_protocol import _raise_if_application_suspended
from ._agent_session_codec import (
    _IndeterminateAgentProtocolError as _IndeterminateAgentProtocolError,
    _registration,
    _offer,
    _retirement_proof,
    _provider_release_proof,
    _string,
    _integer,
    _exact,
    _decode as _decode,
    _decode_run_inspection_response as _decode_run_inspection_response,
    _MAX_BODY_BYTES,
    _MAX_QUERY_RESPONSE_BYTES,
)
from ._agent_session_journal import (
    _AGENT_BINDING_FILE,
    _RemoteAgentJournal as _RemoteAgentJournal,
    _canonical_json,
    _canonical_digest as _canonical_digest,
    _resident_profile_key,
    _agent_config_revision as _agent_config_revision,
    _agent_inventory_revision as _agent_inventory_revision,
    _record_agent_declaration_binding,
    _agent_active_fingerprint as _agent_active_fingerprint,
    _agent_revision as _agent_revision,
)

from .gpu.occupancy import GpuOccupancyPolicy, GpuOccupancyMonitor
from ._managed_local import ResourceAvailabilityStatus

from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import fcntl
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import ssl
from threading import BoundedSemaphore, RLock, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic
from typing import Any, cast
from urllib.parse import urlsplit

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.pipeline.executors.containers import ContainerOptionError
from loom.queue._managed_local import (
    AgentResourceProvider,
    AssignmentState,
    AtomResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ManagedAssignment,
    ManagedLocalError,
    ManagedProcessStartError,
    ObserveRequest,
    SQLiteAgentJournal,
    GpuResourceProvider,
    _cancelled_worker_result,
    _compose_agent_resource_providers,
    _configured_provider_descriptor,
    _managed_root_failed_worker_result,
    _managed_resource_controls,
    _start_failed_worker_result,
    _worker_environment,
)
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.status import StageStatus
from loom.pipeline.runtime import CpuResourcePlanner, MemoryResourcePlanner
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile
from ._agent_slurm import AgentSlurmJobs
from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.pipeline.stores.errors import InvalidRunURIError
from loom.pipeline.stores.run_uri import validate_run_uri
from loom.scheduling import CapacityAtom

from .agent_sessions import (
    AgentAssignmentControl,
    AgentOffer,
    AgentOfferRenewal,
    AgentProviderDescriptor,
    AgentControl,
    AgentControlEffect,
    AgentPollActiveError,
    AgentPollFencedError,
    AgentPollSequenceGapError,
    AgentRegistration,
    AgentSession,
    AgentSessionState,
    AgentStalePollError,
    SessionReplacementRequest,
    AgentTransferAuthorizationStaleError,
    ScopedAuthorizer,
    _managed_containment_evidence,
    _session_from_value,
)
from ._remote_stage_execution import (
    AgentResourceInventory,
    ResidentExecutionProfile,
    _ResidentAssignmentBundle,
    _ResidentAssignmentWorkspace,
    _RemoteExecutionReport,
    _decode_chunk,
    _encode_chunk,
)
from ._agent_process_supervisor import (
    AgentProcessSupervisor,
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    AgentProcessSupervisorService,
    ResidentWorkerLaunch,
    SupervisorLaunchConfiguration,
    SupervisorReceipt,
    SupervisorLaunchState,
    _launch_from_value,
    _launch_value,
)
from .errors import QueueConflictError, QueueError, QueueServiceError
from ._coordinator_control import (
    CONTROL_CAPABILITY,
    WAIT_OPERATIONS,
    CoordinatorClientError,
    control_error,
    decode_wire,
    dispatch_control,
    error_envelope,
)
from ._coordinator_transport import https_connection
from ._agent_progress import _Progress, _cooperative, _steps, _external, _delay, _Gate, _serialized, _owns_assignment
from .local_daemon import (
    AdmissionNotFoundError,
    CoordinatorSchedulingReload,
    LocalDaemon,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    RecoverUnknownAssignment,
    TimeRecoveryReceipt,
    TimeRecoveryRequest,
)


_FAILURE_REPORT_OPERATIONS = frozenset(
    {
        ("agent", "output_manifest"),
        ("agent", "slurm_work"),
        ("slurm_bootstrap", "report"),
    }
)
_HTTP_TIMEOUT_SECONDS = 10
_ASSIGNMENT_RECONCILIATION_SECONDS = 60
_MAX_TRANSFER_AUTHORIZATION_RENEWALS = 64


def _supervisor_containment_evidence(
    receipt: SupervisorReceipt, *, agent_id: str
) -> Mapping[str, PlainData]:
    """Serialize the exact persisted process-owner receipt without paths."""

    launch = receipt.launch
    return _managed_containment_evidence(
        {
            "kind": "managed_supervisor",
            "state": "CONTAINED",
            "supervisor_id": launch.supervisor_id,
            "continuity_epoch": launch.continuity_epoch,
            "agent_id": agent_id,
            "supervisor_agent_id": launch.agent_id,
            "session_id": launch.session_id,
            "assignment_id": launch.assignment_id,
            "process_execution_id": launch.process_execution_id,
            "execution_fence": launch.execution_fence,
            "launch_operation_id": launch.launch_operation_id,
            "launch_spec_digest": launch.spec_digest,
            "supervisor_revision": receipt.supervisor_revision,
            "worker_result_digest": receipt.worker_result_digest,
        }
    )


class _RunInspectionHttpError(QueueServiceError):
    """One safe query failure with its fixed HTTP status."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__("run inspection request was rejected")
        self.code = code
        self.status = status


@dataclass(frozen=True, slots=True)
class AgentTlsServerConfig:
    host: str
    port: int
    certificate_path: Path
    private_key_path: Path
    client_ca_path: Path
    credential_fingerprints: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.host or not 0 <= self.port <= 65535:
            raise QueueServiceError("agent TLS server endpoint is invalid")
        if not self.credential_fingerprints:
            raise QueueServiceError("agent TLS credential map is required")
        for fingerprint, credential in self.credential_fingerprints.items():
            if len(fingerprint) != 64 or any(
                char not in "0123456789abcdef" for char in fingerprint
            ):
                raise QueueServiceError("TLS certificate fingerprint is invalid")
            if not credential:
                raise QueueServiceError("TLS credential ID is invalid")


@dataclass(frozen=True, slots=True)
class AgentTlsClientConfig:
    """Protected outbound identity, execution profiles and resident ceiling.

    ``max_concurrent_assignments`` accepts integers 1..1024 (excluding bool),
    defaults to one, and bounds all unreleased resident assignments. It changes
    active configuration, requiring settlement and trusted reload to resize.
    Nonempty ``slurm_profiles`` requires one. Execution is currently serial
    even with a larger targeting ceiling.
    """

    url: str
    server_ca_path: Path
    certificate_path: Path
    private_key_path: Path
    agent_root: Path | None = None
    resident_profiles: tuple[ResidentExecutionProfile, ...] = ()
    agent_resource_provider_factory: (
        Callable[[str, ResidentExecutionProfile], Sequence[AgentResourceProvider]]
        | None
    ) = None
    deployment_configuration_fingerprint: str | None = None
    active_configuration_fingerprint: str | None = None
    resource_inventory: AgentResourceInventory | None = None
    gpu_occupancy_policy: GpuOccupancyPolicy | None = None

    slurm_profiles: tuple[SlurmReadyStageProfile, ...] = ()
    max_concurrent_assignments: int = 1
    declaration_digest: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_concurrent_assignments, bool)
            or not isinstance(self.max_concurrent_assignments, int)
            or not 1 <= self.max_concurrent_assignments <= 1024
        ):
            raise QueueServiceError(
                "max_concurrent_assignments must be an integer from 1 through 1024"
            )
        if self.slurm_profiles and self.max_concurrent_assignments > 1:
            raise QueueServiceError(
                "max_concurrent_assignments above one is unsupported with slurm_profiles"
            )
        slurm_profiles = tuple(self.slurm_profiles)
        if any(
            not isinstance(item, SlurmReadyStageProfile) for item in slurm_profiles
        ) or len({item.profile_id for item in slurm_profiles}) != len(slurm_profiles):
            raise QueueServiceError("agent SLURM profiles are invalid")
        if slurm_profiles and self.agent_root is None:
            raise QueueServiceError("SLURM submission requires an agent root")
        object.__setattr__(self, "slurm_profiles", slurm_profiles)
        parsed = urlsplit(self.url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise QueueServiceError("agent TLS URL is invalid") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or (port is not None and not 1 <= port <= 65535)
            or parsed.path not in ("", "/")
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
        ):
            raise QueueServiceError("agent TLS URL must be one HTTPS service identity")
        profiles = tuple(self.resident_profiles)
        if any(not isinstance(item, ResidentExecutionProfile) for item in profiles):
            raise QueueServiceError("agent resident profiles are invalid")
        if len({item.descriptor.profile_id for item in profiles}) != len(profiles):
            raise QueueServiceError("agent resident profile IDs must be unique")
        capacity_domains = {
            (
                item.cpu_capacity,
                item.memory_capacity_bytes,
                tuple(device.descriptor for device in item.gpu_devices),
            )
            for item in profiles
        }
        inventory = self.resource_inventory
        if inventory is not None and not isinstance(inventory, AgentResourceInventory):
            raise QueueServiceError("agent resource inventory is invalid")
        if inventory is not None and not profiles:
            raise QueueServiceError(
                "agent resource inventory requires a resident profile"
            )
        if inventory is None and len(capacity_domains) > 1:
            raise QueueServiceError(
                "agent resident profiles must share one capacity domain"
            )
        if profiles and self.agent_root is None:
            raise QueueServiceError("resident execution requires an agent root")
        factory = self.agent_resource_provider_factory or _default_remote_providers
        if not callable(factory):
            raise QueueServiceError("agent resource provider factory is invalid")
        object.__setattr__(self, "resident_profiles", profiles)
        object.__setattr__(self, "resource_inventory", inventory)
        object.__setattr__(self, "agent_resource_provider_factory", factory)
        fingerprint = self.deployment_configuration_fingerprint
        if fingerprint is not None and (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise QueueServiceError(
                "agent deployment configuration fingerprint is invalid"
            )
        active = self.active_configuration_fingerprint
        if active is not None and (
            not isinstance(active, str)
            or len(active) != 64
            or any(character not in "0123456789abcdef" for character in active)
        ):
            raise QueueServiceError("agent active configuration fingerprint is invalid")
        declaration = self.declaration_digest
        if declaration is not None and (
            not isinstance(declaration, str)
            or len(declaration) != 64
            or any(character not in "0123456789abcdef" for character in declaration)
            or fingerprint is None
            or active is None
        ):
            raise QueueServiceError("agent declaration binding is invalid")

    @property
    def capacity_profile(self) -> ResidentExecutionProfile:
        """Project the one agent capacity domain through an executable profile."""

        if not self.resident_profiles:
            raise QueueServiceError(
                "agent resource inventory requires a resident profile"
            )
        inventory = self.resource_inventory
        if inventory is None:
            return self.resident_profiles[0]
        return replace(
            self.resident_profiles[0],
            cpu_capacity=inventory.cpu_capacity,
            memory_capacity_bytes=inventory.memory_capacity_bytes,
            gpu_devices=inventory.gpu_devices,
        )


@dataclass(frozen=True, slots=True)
class _PreparedAgentReload:
    """One fully validated owner-local reload plan awaiting durable activation."""

    replacement: AgentTlsClientConfig
    profiles: Mapping[str, ResidentExecutionProfile]
    retained_profiles: Mapping[str, ResidentExecutionProfile]
    retained: bool
    install_role: Callable[[], None]
    config_revision: str
    inventory_revision: str
    active_fingerprint: str


@dataclass(frozen=True, slots=True)
class RunInspectionTlsClientConfig:
    """One protected mTLS identity for the read-only inspection operation."""

    url: str
    server_ca_path: Path
    certificate_path: Path
    private_key_path: Path

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise QueueServiceError("run inspection TLS URL is invalid") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or (port is not None and not 1 <= port <= 65535)
            or parsed.path not in ("", "/")
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
        ):
            raise QueueServiceError(
                "run inspection TLS URL must be one HTTPS service identity"
            )


def _default_remote_providers(
    agent_id: str,
    profile: ResidentExecutionProfile,
    *,
    occupancy_policy: GpuOccupancyPolicy | None = None,
) -> tuple[AgentResourceProvider, ...]:
    """Protected compatibility composition for one resident profile."""

    planners = {
        "cpu": CpuResourcePlanner(),
        "memory": MemoryResourcePlanner(),
        "gpu": GpuResourcePlanner(),
    }
    atoms = profile.capacity_atoms(agent_id)
    result: dict[str, AgentResourceProvider] = {}
    for kind in {atom.owner_resource_kind for atom in atoms}:
        if kind == "gpu":
            continue
        provider_atoms = tuple(
            atom for atom in atoms if atom.owner_resource_kind == kind
        )
        result[kind] = AtomResourceProvider(
            _configured_provider_descriptor(kind, provider_atoms),
            planners[kind].claim_contracts,
            provider_atoms,
        )
    if profile.gpu_devices:
        bindings = {
            f"{agent_id}:{device.descriptor.device_id}": device.binding_value
            for device in profile.gpu_devices
            if device.descriptor.healthy
        }
        result["gpu"] = GpuResourceProvider(
            planners["gpu"].claim_contracts,
            tuple(
                atom
                for atom in atoms
                if atom.owner_resource_kind == "gpu"
                and atom.local_capacity_key in bindings
            ),
            bindings=bindings,
            occupancy_monitor=(
                None
                if occupancy_policy is None
                else GpuOccupancyMonitor(
                    tuple(bindings.values()), policy=occupancy_policy
                )
            ),
        )
    return tuple(result[kind] for kind in sorted(result))


def _configured_remote_provider_members(
    config: AgentTlsClientConfig,
    agent_id: str,
    profile: ResidentExecutionProfile,
) -> tuple[AgentResourceProvider, ...]:
    """Construct the configured members for live execution or idle qualification."""

    factory = config.agent_resource_provider_factory
    if factory is None:
        raise QueueServiceError("remote agent provider composition is missing")
    if factory is _default_remote_providers:
        return _default_remote_providers(
            agent_id, profile, occupancy_policy=config.gpu_occupancy_policy
        )
    return tuple(factory(agent_id, profile))


def _resident_provider_descriptors(
    profile: ResidentExecutionProfile,
    agent_id: str,
    *,
    resource_kinds: set[str] | None = None,
) -> tuple[AgentProviderDescriptor, ...]:
    """Derive safe provider identities from one protected resident profile."""

    atoms = profile.capacity_atoms(agent_id)
    kinds = resource_kinds or {atom.owner_resource_kind for atom in atoms}
    result: list[AgentProviderDescriptor] = []
    planners = {
        "cpu": CpuResourcePlanner(),
        "memory": MemoryResourcePlanner(),
        "gpu": GpuResourcePlanner(),
    }
    for kind in sorted(kinds):
        provider_atoms = tuple(
            atom for atom in atoms if atom.owner_resource_kind == kind
        )
        bindings: Mapping[str, str] | None = None
        if kind == "gpu":
            bindings = {
                f"{agent_id}:{device.descriptor.device_id}": device.binding_value
                for device in profile.gpu_devices
                if device.descriptor.healthy
            }
            provider_atoms = tuple(
                atom for atom in provider_atoms if atom.local_capacity_key in bindings
            )
        result.append(
            AgentProviderDescriptor(
                _configured_provider_descriptor(
                    kind, provider_atoms, bindings=bindings
                ),
                planners[kind].claim_contracts,
            )
        )
    return tuple(result)


def _wire_capacity_atom(atom: CapacityAtom, agent_id: str) -> CapacityAtom:
    """Remove the private agent namespace and normalize the wire memory unit."""

    prefix = f"{agent_id}:"
    local_key = atom.local_capacity_key
    if local_key.startswith(prefix):
        local_key = local_key[len(prefix) :]
    return CapacityAtom(
        atom.owner_resource_kind,
        local_key,
        atom.amount,
        (
            "byte"
            if atom.owner_resource_kind == "memory" and atom.unit == "B"
            else atom.unit
        ),
        atom.granularity,
    )


class LocalDaemonAgentHttpServer:
    """Loopback/deployment server; it exposes no inbound agent listener."""

    def __init__(
        self,
        daemon: LocalDaemon,
        config: AgentTlsServerConfig,
        *,
        inspect_run: Callable[[str], Mapping[str, PlainData]] | None = None,
    ) -> None:
        self._daemon = daemon
        self._config = config
        self._inspect_run = inspect_run
        self._server: _MutualTlsHttpServer | None = None
        self._thread: Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise QueueServiceError("agent TLS server is not started")
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._server is not None:
            raise QueueServiceError("agent TLS server is already started")
        context = _agent_server_context(self._config)
        server = _MutualTlsHttpServer(
            (self._config.host, self._config.port),
            context,
            self._daemon,
            dict(self._config.credential_fingerprints),
            self._inspect_run,
        )
        self._server = server
        self._thread = Thread(
            target=server.serve_forever, daemon=True, name="loom-agent-mtls"
        )
        self._thread.start()

    def prepare_reload(self, config: AgentTlsServerConfig) -> Callable[[], None]:
        """Prepare a non-failing TLS-context swap for the resident listener."""

        server = self._server
        if server is None:
            raise QueueServiceError("agent TLS server is not started")
        if (config.host, config.port) != (self._config.host, self._config.port):
            raise QueueConflictError(
                "agent TLS reload cannot replace the resident endpoint"
            )
        context = _agent_server_context(config)
        fingerprints = dict(config.credential_fingerprints)

        def install() -> None:
            server.replace_tls(context, fingerprints)
            self._config = config

        return install

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None


class RunInspectionHttpClient:
    """No-redirect HTTPS client for one configured read-only query identity."""

    def __init__(self, config: RunInspectionTlsClientConfig) -> None:
        self._config = config

    def inspect_run(self, run_uri: str) -> Mapping[str, PlainData]:
        """Return the exact server result envelope or fail closed on transport."""

        return self._read_run("inspect_run", "run-inspection-v1", run_uri)

    def get_run_context(self, run_uri: str) -> Mapping[str, PlainData]:
        """Read context using the configured QUERY principal without write access."""
        return self._read_run("get_run_context", "run-context-v1", run_uri)

    def list_run_notes(self, run_uri: str, *, limit: int = 50, cursor: str | None = None) -> Mapping[str, PlainData]:
        """Read a bounded annotation note page using the QUERY principal."""
        return self._read_run("list_run_notes", "run-context-v1", run_uri, {"limit": limit, "cursor": cursor})

    def _read_run(self, operation: str, capability: str, run_uri: str, options: Mapping[str, PlainData] | None = None) -> Mapping[str, PlainData]:

        return self._read_query(operation, capability, {"run_uri": run_uri, **(options or {})})

    def select_outputs(self, selection) -> Mapping[str, PlainData]:
        """Select authorized exact output metadata with the QUERY role."""
        return self._read_query("select_outputs", "output-query-v1", {"selection": selection.to_dict()})

    def describe_artifact(self, locator, **options) -> Mapping[str, PlainData]:
        """Describe the exact authorized declaration with the QUERY role."""
        return self._read_query("describe_artifact", "artifact-read-v1", {"locator": locator.to_dict(), **options})

    def read_artifact_chunk(self, locator, **options) -> Mapping[str, PlainData]:
        """Read bounded declared bytes with the QUERY role."""
        return self._read_query("read_artifact_chunk", "artifact-read-v1", {"locator": locator.to_dict(), **options})

    def read_artifact(self, locator, **options) -> Mapping[str, PlainData]:
        """Preview bounded content with the QUERY role; never run codecs."""
        return self._read_query("read_artifact", "artifact-read-v1", {"locator": locator.to_dict(), **options})

    def trace_lineage(self, query) -> Mapping[str, PlainData]:
        """Trace exact lineage with the same QUERY scope as output selection."""
        return self._read_query("trace_lineage", "lineage-query-v1", {"query": query.to_dict()})

    def list_output_commits(self, selection) -> Mapping[str, PlainData]:
        """Read output history using the same QUERY scope and authority."""
        return self._read_query("list_output_commits", "output-query-v1", {"selection": selection.to_dict()})

    def search_runs(self, query) -> Mapping[str, PlainData]:
        """Search current scope with the configured read-only QUERY identity."""
        return self._read_query("search_runs", "run-query-v1", {"query": query.to_dict()})

    def search_submissions(self, query) -> Mapping[str, PlainData]:
        """Search original request records without write access."""
        return self._read_query("search_submissions", "run-query-v1", {"query": query.to_dict()})

    def search_jobs(self, query) -> Mapping[str, PlainData]:
        """Search native admission views without write access."""
        return self._read_query("search_jobs", "run-query-v1", {"query": query.to_dict()})

    def query_fields(self, entity: str = "runs") -> Mapping[str, PlainData]:
        """Discover supported query fields."""
        return self._read_query("query_fields", "run-query-v1", {"entity": entity})

    def tag_keys(self, scope, *, limit: int = 50, cursor: str | None = None) -> Mapping[str, PlainData]:
        from loom.runs.query import _plain
        return self._read_query("tag_keys", "run-query-v1", {"scope": _plain(scope), "limit": limit, "cursor": cursor})

    def tag_values(self, scope, key: str, *, limit: int = 50, cursor: str | None = None) -> Mapping[str, PlainData]:
        from loom.runs.query import _plain
        return self._read_query("tag_values", "run-query-v1", {"scope": _plain(scope), "key": key, "limit": limit, "cursor": cursor})

    def _read_query(self, operation: str, capability: str, request: Mapping[str, PlainData]) -> Mapping[str, PlainData]:

        parsed = urlsplit(self._config.url)
        assert parsed.hostname is not None
        body = json.dumps(
            request, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if len(body) > _MAX_BODY_BYTES:
            return _run_inspection_failure("invalid_request")
        connection: http.client.HTTPSConnection | None = None
        try:
            context = ssl.create_default_context(cafile=self._config.server_ca_path)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(
                self._config.certificate_path, self._config.private_key_path
            )
            connection = http.client.HTTPSConnection(
                parsed.hostname,
                parsed.port or 443,
                context=context,
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            connection.request(
                "POST",
                "/v1/query/handshake",
                body=b"{}",
                headers={"Content-Type": "application/json"},
            )
            handshake = connection.getresponse()
            handshake_raw = handshake.read(_MAX_BODY_BYTES + 1)
            if len(handshake_raw) > _MAX_BODY_BYTES:
                return _run_inspection_failure("unavailable")
            if handshake.getheader("Content-Type") != "application/json":
                return _run_inspection_failure("unavailable")
            try:
                handshake_value = _decode(handshake_raw)
                _exact(handshake_value, {"ok", "result"})
            except QueueError:
                return _run_inspection_failure("unavailable")
            handshake_result = handshake_value.get("result")
            if _is_run_inspection_failure(handshake_result):
                if handshake.status != _run_inspection_http_status(
                    cast(Mapping[str, object], handshake_result)
                ):
                    return _run_inspection_failure("unavailable")
                return freeze_plain_data(
                    handshake_result, path="run inspection handshake failure"
                )
            capabilities = (
                handshake_result.get("capabilities")
                if isinstance(handshake_result, Mapping)
                else None
            )
            if (
                handshake.status != 200
                or handshake_value.get("ok") is not True
                or not isinstance(capabilities, Sequence)
                or isinstance(capabilities, (str, bytes))
                or capability not in capabilities
            ):
                return _run_inspection_failure("unavailable")
            connection.request(
                "POST",
                f"/v1/query/{operation}",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            raw = response.read(_MAX_QUERY_RESPONSE_BYTES + 1)
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            del exc
            return _run_inspection_failure("unavailable")
        finally:
            if connection is not None:
                connection.close()
        if len(raw) > _MAX_QUERY_RESPONSE_BYTES:
            return _run_inspection_failure("unavailable")
        if response.getheader("Content-Type") != "application/json":
            return _run_inspection_failure("unavailable")
        try:
            payload = (decode_wire(raw) if operation in {"describe_artifact", "read_artifact_chunk", "read_artifact", "trace_lineage", "select_outputs", "list_output_commits"}
                       else _decode_run_inspection_response(raw))
            _exact(payload, {"ok", "result"})
        except (QueueError, ValueError, TypeError, RecursionError):
            return _run_inspection_failure("unavailable")
        if payload.get("ok") is not True:
            return _run_inspection_failure("unavailable")
        result = payload.get("result")
        if not isinstance(result, Mapping):
            return _run_inspection_failure("unavailable")
        expected_status = _run_inspection_http_status(result)
        if response.status != expected_status:
            return _run_inspection_failure("unavailable")
        return cast(
            Mapping[str, PlainData],
            thaw_plain_data(result, path="run inspection HTTP response"),
        )


def _run_inspection_failure(code: str) -> Mapping[str, PlainData]:
    """Build the closed Phase 1 error shape without importing diagnostics."""

    return freeze_plain_data(
        {"schema_version": 1, "code": code}, path="run inspection failure"
    )


def _is_run_inspection_failure(value: object) -> bool:
    code = value.get("code") if isinstance(value, Mapping) else None
    return (
        isinstance(value, Mapping)
        and value.get("schema_version") == 1
        and isinstance(code, str)
        and code
        in {"invalid_request", "invalid_cursor", "not_found", "unauthorized", "unavailable", "internal"}
        and set(value) == {"schema_version", "code"}
    )


def _run_inspection_http_status(value: Mapping[str, object]) -> int:
    code = value.get("code")
    return {
        "invalid_request": 400,
        "invalid_cursor": 400,
        "not_found": 404,
        "unauthorized": 403,
        "unavailable": 503,
        "internal": 503,
    }.get(code if isinstance(code, str) else "", 200)


class LocalDaemonAgentHttpClient:
    """A no-redirect persistent HTTPS caller for one configured service name."""

    def __init__(
        self,
        config: AgentTlsClientConfig,
        *,
        trusted_config_loader: Callable[[], AgentTlsClientConfig] | None = None,
        prepare_role_reload: (
            Callable[[AgentTlsClientConfig], Callable[[], None]] | None
        ) = None,
    ) -> None:
        self._config = config
        self._slurm_cursor: str | None = None
        self._resource_maintenance_enabled = False
        self._next_resource_maintenance = 0.0
        self._trusted_config_loader = trusted_config_loader
        self._prepare_role_reload = prepare_role_reload
        self._connection: http.client.HTTPSConnection | None = None
        self._closed = False
        self._service_progress = False
        self._service_control_due = True
        self._epoch_reconciliation_pending = False
        self._mutation_gate = _Gate()
        self._suspend_requested: Callable[[], bool] | None = None
        self._slurm_agent = (
            AgentSlurmJobs(Path(config.agent_root), config.slurm_profiles)
            if config.agent_root is not None and config.slurm_profiles
            else None
        )
        self._supervisor: AgentProcessSupervisorClient | None = None
        # The journal validates the durable deployment binding and obtains the
        # exclusive application lock before an empty supervisor can be started.
        self._journal = (
            _RemoteAgentJournal(
                config.agent_root,
                expected_configuration_fingerprint=(
                    config.deployment_configuration_fingerprint
                ),
                expected_active_configuration_fingerprint=_agent_active_fingerprint(
                    config
                ),
            )
            if config.agent_root
            else None
        )
        created_supervisor = False
        try:
            self._execution_journal = (
                SQLiteAgentJournal(
                    Path(config.agent_root) / "journal.sqlite",
                    _allow_initialize=False,
                )
                if config.agent_root is not None
                else None
            )
            if self._execution_journal is not None:
                try:
                    self._execution_journal._open_existing()
                except ManagedLocalError as exc:
                    raise QueueServiceError(
                        "remote execution journal is unavailable"
                    ) from exc
            # Reuse the normal shutdown predicate before creating a detached
            # service.  A corrupt journal therefore rejects process-free,
            # while retained work remains protected if later construction
            # fails.
            try:
                self._restart_with_retained_work = self._has_retained_agent_work()
                self._service_recovery_admission = self._restart_with_retained_work
                self._ownership_observation_generation = 0
                self._joined_starts: set[str] = set()
            except ManagedLocalError as exc:
                raise QueueServiceError(
                    "remote retained-work proof is unavailable"
                ) from exc
            self._supervisor, created_supervisor = self._open_supervisor(config)
            self._profiles = {
                item.descriptor.profile_id: item for item in config.resident_profiles
            }
            self._retained_profiles: dict[str, ResidentExecutionProfile] = {}
            self._runtime_agent_id: str | None = None
            self._runtime_provider_key: str | None = None
            self._providers: dict[str, AgentResourceProvider] = {}
            self._configured_provider_members: (
                tuple[AgentResourceProvider, ...] | None
            ) = None
            self._configured_provider_agent_id: str | None = None
            self._cancelled_assignments: set[str] = set(
                self._journal.contained_assignment_ids()
                if self._journal is not None
                else ()
            )
            self._received_cancellations: set[str] = set()
            if self._journal is not None:
                self._journal.recover_pending_reload(config)
            self._drained = (
                self._journal.availability_drained()
                if self._journal is not None
                else False
            )
            self._control_lock = RLock()
        except Exception:
            supervisor = self._supervisor
            if created_supervisor and supervisor is not None:
                try:
                    if not self._has_retained_agent_work():
                        supervisor.shutdown_clean()
                except (AgentProcessSupervisorError, ManagedLocalError, QueueError):
                    pass
            if self._journal is not None:
                self._journal.close()
                self._journal = None
            self._supervisor = None
            raise

    @property
    def agent_root_id(self) -> str:
        return self._require_journal().root_id

    def active_session(self) -> AgentSession | None:
        return self._require_journal().active_session()

    def next_poll_sequence(self, session_id: str) -> int:
        return self._require_journal().next_poll_sequence(session_id)

    @staticmethod
    def recover_reboot(
        config: AgentTlsClientConfig, operation_id: str
    ) -> Mapping[str, PlainData]:
        """Recover only an existing, exclusively owned local Linux agent root.

        This local operation never contacts the coordinator, releases claims, or
        starts a service. Retain the operation ID when replaying an uncertain reply.
        """
        if (
            config.agent_root is None
            or not config.resident_profiles
            or config.slurm_profiles
        ):
            raise QueueServiceError("reboot recovery requires native resident profiles")
        journal = _RemoteAgentJournal(
            config.agent_root,
            expected_configuration_fingerprint=config.deployment_configuration_fingerprint,
            expected_active_configuration_fingerprint=_agent_active_fingerprint(config),
        )
        try:
            execution = SQLiteAgentJournal(
                Path(config.agent_root) / "journal.sqlite", _allow_initialize=False
            )
            execution._open_existing()
            execution.retained_claim_commands()
            root = Path(config.agent_root).resolve() / "supervisor"
            if not (root / "supervisor.sqlite").is_file():
                raise QueueServiceError("supervisor journal unavailable")
            with (root / "service.lock").open("a+") as lock:
                (root / "service.lock").chmod(0o600)
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise QueueConflictError("supervisor service is still owned") from exc
                supervisor = AgentProcessSupervisor(
                    root,
                    agent_id=journal.root_id,
                    profiles=tuple(
                        item.launch_profile for item in config.resident_profiles
                    ),
                )
                return supervisor.recover_reboot(operation_id)
        except (AgentProcessSupervisorError, ManagedLocalError, sqlite3.Error) as exc:
            raise QueueServiceError(str(exc)) from exc
        finally:
            journal.close()

    @classmethod
    def initialize_agent_root(cls, config: AgentTlsClientConfig) -> None:
        """Create the complete remote root and its continuous private owner.

        Remote configuration is trusted application configuration, so this is
        the one place where the full resident profile set becomes durable.
        Opening an existing root never fills in or upgrades that identity.
        """
        if config.agent_root is None or not (
            config.resident_profiles or config.slurm_profiles
        ):
            raise QueueServiceError(
                "remote agent initialization requires resident profiles"
            )
        target = Path(config.agent_root)
        if target.exists():
            raise QueueServiceError("remote agent requires a fresh root")
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        staging = target.parent / f".{target.name}.staging-{secrets.token_hex(8)}"
        journal: _RemoteAgentJournal | None = None
        try:
            LocalDaemon.initialize_agent_root(staging)
            if config.slurm_profiles:
                AgentSlurmJobs.initialize(staging)
            with sqlite3.connect(staging / "control.sqlite") as conn:
                stable_row = conn.execute(
                    "SELECT value FROM root_metadata WHERE key = 'stable_id'"
                ).fetchone()
            if stable_row is None:
                raise QueueServiceError("remote agent root identity is invalid")
            atomic_write_bytes(
                staging / _AGENT_BINDING_FILE,
                json.dumps(
                    {
                        "schema_version": 2,
                        "role_kind": "outbound-agent",
                        "stable_id": str(stable_row[0]),
                        "immutable_fingerprint": (
                            config.deployment_configuration_fingerprint
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8"),
            )
            (staging / _AGENT_BINDING_FILE).chmod(0o600)
            with sqlite3.connect(staging / "control.sqlite") as conn:
                conn.execute(
                    "INSERT INTO root_metadata(key, value) VALUES (?, ?)",
                    ("active_configuration_revision", "1"),
                )
                conn.execute(
                    "INSERT INTO root_metadata(key, value) VALUES (?, ?)",
                    (
                        "active_configuration_fingerprint",
                        _agent_active_fingerprint(config),
                    ),
                )
                conn.execute(
                    "INSERT INTO root_metadata(key, value) VALUES "
                    "('availability_state', 'active')"
                )
                _record_agent_declaration_binding(conn, config, 1)
                conn.commit()
            journal = _RemoteAgentJournal(
                staging,
                expected_configuration_fingerprint=(
                    config.deployment_configuration_fingerprint
                ),
                expected_active_configuration_fingerprint=_agent_active_fingerprint(
                    config
                ),
            )
            if config.resident_profiles:
                profiles = tuple(
                    item.launch_profile for item in config.resident_profiles
                )
                configuration = SupervisorLaunchConfiguration(journal.root_id, profiles)
                AgentProcessSupervisorService.initialize_process_free(
                    staging, configuration=configuration, final_agent_root=target
                )
            journal.close()
            journal = None
            if target.exists():
                raise QueueServiceError("remote agent requires a fresh root")
            staging.rename(target)
        except AgentProcessSupervisorError as exc:
            raise QueueServiceError(str(exc)) from exc
        finally:
            if journal is not None:
                journal.close()
            if staging.exists():
                shutil.rmtree(staging)

    @staticmethod
    def _open_supervisor(
        config: AgentTlsClientConfig,
    ) -> tuple[AgentProcessSupervisorClient | None, bool]:
        if not config.resident_profiles:
            if (
                config.agent_root is not None
                and (Path(config.agent_root).resolve() / "supervisor").exists()
            ):
                raise QueueServiceError(
                    "managed_supervisor_state_requires_reinitialization"
                )
            return None, False
        if config.agent_root is None:
            raise QueueServiceError("remote resident execution requires an agent root")
        # The journal verifies the root and serializes agent application use;
        # its stable ID is the configuration's hard-bound agent identity.
        root_id = _read_remote_agent_root_id(config.agent_root)
        try:
            return AgentProcessSupervisorClient(
                config.agent_root,
                SupervisorLaunchConfiguration(
                    root_id,
                    tuple(item.launch_profile for item in config.resident_profiles),
                ),
            ), False
        except AgentProcessSupervisorError as exc:
            if str(exc) == "managed supervisor endpoint is unavailable":
                try:
                    return AgentProcessSupervisorService.start_empty_initialized(
                        config.agent_root,
                        configuration=SupervisorLaunchConfiguration(
                            root_id,
                            tuple(
                                item.launch_profile for item in config.resident_profiles
                            ),
                        ),
                    ), True
                except AgentProcessSupervisorError as start_exc:
                    raise QueueServiceError(str(start_exc)) from start_exc
            raise QueueServiceError(str(exc)) from exc

    def close(self) -> None:
        self._closed = True
        self._close_connection()
        if self._journal is not None:
            self._journal.close()
            self._journal = None

    def shutdown_clean(self) -> None:
        """Stop the resident supervisor only after both agent owners are empty."""

        supervisor = self._supervisor
        if self._has_retained_agent_work():
            raise QueueConflictError("agent has retained work")
        if supervisor is None:
            return
        try:
            supervisor.shutdown_clean()
        except AgentProcessSupervisorError as exc:
            raise QueueConflictError(str(exc)) from exc
        self._supervisor = None

    def _close_connection(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None

    @_cooperative
    def handshake(self, *, role: str = "agent") -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _session_protocol.handshake(self, role=role))

    @_cooperative
    @_serialized("_mutation_gate")
    def register(self, request: AgentRegistration) -> Generator[_Progress, Any, AgentSession]:
        return (yield from _session_protocol.register(self, request))

    @_cooperative
    @_serialized("_mutation_gate")
    def _replay_pending_reconciliation(self):
        return (yield from _session_protocol._replay_pending_reconciliation(self))

    @_cooperative
    @_serialized("_mutation_gate")
    def reconcile(
        self,
        session_id: str,
        coordinator_epoch: str,
        *,
        idempotency_key: str,
    ) -> Generator[_Progress, Any, AgentSession]:
        return (yield from _session_protocol.reconcile(self, session_id, coordinator_epoch, idempotency_key=idempotency_key))

    @_cooperative
    @_serialized("_mutation_gate")
    def publish_offer(
        self,
        offer: AgentOffer,
        *,
        idempotency_key: str,
        expected_availability_revision: str | None = None,
        _observed_snapshot: bool = False,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _session_protocol.publish_offer(self, offer, idempotency_key=idempotency_key, expected_availability_revision=expected_availability_revision, _observed_snapshot=_observed_snapshot))

    @_cooperative
    @_serialized("_mutation_gate")
    def renew_offer(self, renewal: AgentOfferRenewal) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _session_protocol.renew_offer(self, renewal))

    @_cooperative
    @_serialized("_mutation_gate")
    def refresh_resource_offer(
        self, *, ttl_seconds: int = 30
    ) -> Generator[_Progress, Any, Mapping[str, PlainData] | None]:
        """Refresh cached host facts and report one serial, replayable resource view."""
        return (yield from _session_protocol.refresh_resource_offer(self, ttl_seconds=ttl_seconds))

    @_cooperative
    def _replay_pending_resource_mutation(self, session_id: str) -> Generator[_Progress, Any, None]:
        return (yield from _session_protocol._replay_pending_resource_mutation(self, session_id))

    @_cooperative
    def _maintain_resource_offer(self) -> Generator[_Progress, Any, None]:
        """Keep control/supervision running when a report response is unavailable."""
        if self._service_progress or not self._resource_maintenance_enabled:
            return
        now = monotonic()
        if now < self._next_resource_maintenance:
            return
        policy = self._config.gpu_occupancy_policy
        interval = 5.0 if policy is None else policy.poll_interval_seconds
        self._next_resource_maintenance = now + interval
        try:
            session = self.active_session()
            if session is not None:
                yield from _steps(self.poll_control, session.session_id)
            (yield from _steps(self.refresh_resource_offer))
        except QueueError:
            # Its exact pending mutation is retried; no worker is released.
            pass

    @_cooperative
    def renew_current_offer(self, session_id: str) -> Generator[_Progress, Any, Mapping[str, PlainData] | None]:
        return (yield from _session_protocol.renew_current_offer(self, session_id))

    @_cooperative
    @_serialized("_mutation_gate")
    def wait_for_work(
        self,
        session_id: str,
        availability_revision: str,
        *,
        sequence: int,
        wait_timeout_ms: int,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _session_protocol.wait_for_work(self, session_id, availability_revision, sequence=sequence, wait_timeout_ms=wait_timeout_ms))

    @_cooperative
    @_serialized("_mutation_gate")
    def poll_control(self, session_id: str) -> Generator[_Progress, Any, AgentControl | None]:
        (yield from _steps(self._replay_pending_resource_mutation, session_id))
        journal = self._require_journal()
        pending = journal.next_unacknowledged_control()
        if pending is not None:
            control, effect = pending
            if control.expected_session_id != session_id:
                raise QueueConflictError(
                    "retained agent control belongs to another session"
                )
            (yield from _steps(self._call,
                "control_ack",
                {"session_id": session_id, "effect": effect.value()},
            ))
            journal.acknowledge_control(control.operation_id)
            return control
        result = (yield from _steps(self._call, "control", {"session_id": session_id}))
        raw = result.get("control")
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise QueueServiceError("agent control response is invalid")
        control = AgentControl.from_value(raw)
        effect = journal.replayed_control_effect(control)
        prepared_reload: _PreparedAgentReload | None = None
        prepared_error: str | None = None
        cancellation_prepared = False
        if effect is None and control.kind.value == "reload":
            with self._control_lock:
                if control.cancel_active:
                    cancellation_prepared = True
                    if not (yield from _steps(self._cancel_active_assignments)):
                        prepared_error = "unknown_work"
                if prepared_error is None:
                    if self._trusted_config_loader is None:
                        prepared_error = "reload_unavailable"
                    else:
                        try:
                            prepared_reload = self._prepare_agent_reload()
                        except (QueueError, OSError, TypeError, ValueError):
                            prepared_error = "reload_rejected"
        if effect is None:
            effect = journal.prepare_control(
                control,
                replacement_fingerprint=(
                    None
                    if prepared_reload is None
                    else prepared_reload.active_fingerprint
                ),
            )
        if effect is None:
            effect = (yield from _steps(self._apply_agent_control,
                control,
                prepared_reload=prepared_reload,
                prepared_error=prepared_error,
                cancellation_prepared=cancellation_prepared,
            ))
            journal.record_control_effect(control, effect)
        (yield from _steps(self._call,
            "control_ack",
            {"session_id": session_id, "effect": effect.value()},
        ))
        journal.acknowledge_control(control.operation_id)
        return control

    @_cooperative
    def _apply_agent_control(
        self,
        control: AgentControl,
        *,
        prepared_reload: _PreparedAgentReload | None = None,
        prepared_error: str | None = None,
        cancellation_prepared: bool = False,
    ) -> Generator[_Progress, Any, AgentControlEffect]:
        """Apply an inert command using only trusted owner-local configuration."""

        session = self._require_journal().session(control.expected_session_id)
        with self._control_lock:
            if control.kind.value in {"drain", "reload"}:
                self._drained = True
            if prepared_error is not None:
                return self._unchanged_control_effect(control, session, prepared_error)
            if (
                control.cancel_active
                and not cancellation_prepared
                and not (yield from _steps(self._cancel_active_assignments))
            ):
                return self._unchanged_control_effect(control, session, "unknown_work")
            if control.kind.value == "reload":
                if prepared_reload is None and self._trusted_config_loader is None:
                    return self._unchanged_control_effect(
                        control, session, "reload_unavailable"
                    )
                try:
                    plan = prepared_reload or self._prepare_agent_reload()
                except (QueueError, OSError, TypeError, ValueError):
                    return self._unchanged_control_effect(
                        control, session, "reload_rejected"
                    )
                journal = self._require_journal()
                journal.bind_reload_intent(control, plan.active_fingerprint)
                effect = AgentControlEffect(
                    operation_id=control.operation_id,
                    code="applied",
                    config_revision=plan.config_revision,
                    inventory_revision=plan.inventory_revision,
                    availability_revision=_agent_revision(
                        "availability",
                        {
                            "operation_id": control.operation_id,
                            "drained": True,
                            "inventory_revision": plan.inventory_revision,
                        },
                    ),
                )
                journal.complete_reload(control, plan.replacement, effect)
                self._config = plan.replacement
                if self._slurm_agent is not None:
                    self._slurm_agent.profiles = {
                        (item.profile_id, item.configuration_fingerprint): item
                        for item in plan.replacement.slurm_profiles
                    }
                plan.install_role()
                self._profiles = dict(plan.profiles)
                self._retained_profiles = dict(plan.retained_profiles)
                if not plan.retained:
                    self._reset_runtime_providers()
                return effect
            else:
                config_revision = session.config_revision
                inventory_revision = session.inventory_revision
            if control.kind.value == "resume":
                if self._restart_with_retained_work or self._has_retained_agent_work():
                    return self._unchanged_control_effect(
                        control, session, "retained_work"
                    )
                if self._trusted_config_loader is not None and any(
                    profile.readiness_identity is not None
                    for profile in self._config.resident_profiles
                ):
                    try:
                        replacement = self._trusted_config_loader()
                        self._validate_reload_config(replacement, retained_work=False)
                        if _agent_active_fingerprint(
                            replacement
                        ) != _agent_active_fingerprint(self._config):
                            raise QueueConflictError(
                                "changed role requires explicit reload"
                            )
                    except (QueueError, OSError, TypeError, ValueError):
                        return self._unchanged_control_effect(
                            control, session, "reload_rejected"
                        )
                self._retained_profiles.clear()
                self._reset_runtime_providers()
                self._drained = False
            availability_revision = _agent_revision(
                "availability",
                {
                    "operation_id": control.operation_id,
                    "drained": self._drained,
                    "inventory_revision": inventory_revision,
                },
            )
            return AgentControlEffect(
                operation_id=control.operation_id,
                code="applied",
                config_revision=config_revision,
                inventory_revision=inventory_revision,
                availability_revision=availability_revision,
            )

    def _prepare_agent_reload(self) -> _PreparedAgentReload:
        loader = self._trusted_config_loader
        if loader is None:
            raise QueueServiceError("trusted agent configuration loader is unavailable")
        replacement = loader()
        retained = self._has_retained_agent_work()
        self._validate_reload_config(replacement, retained_work=retained)
        next_profiles = {
            item.descriptor.profile_id: item for item in replacement.resident_profiles
        }
        next_retained_profiles = dict(self._retained_profiles)
        if retained:
            next_retained_profiles.update(
                {_resident_profile_key(item): item for item in self._profiles.values()}
            )

        def install_role() -> None:
            return

        if self._prepare_role_reload is not None:
            install_role = self._prepare_role_reload(replacement)
            if not callable(install_role):
                raise QueueServiceError("trusted agent role reload plan is unavailable")
        return _PreparedAgentReload(
            replacement=replacement,
            profiles=next_profiles,
            retained_profiles=next_retained_profiles,
            retained=retained,
            install_role=install_role,
            config_revision=_agent_config_revision(replacement),
            inventory_revision=_agent_inventory_revision(replacement),
            active_fingerprint=_agent_active_fingerprint(replacement),
        )

    @staticmethod
    def _unchanged_control_effect(
        control: AgentControl, session: AgentSession, code: str
    ) -> AgentControlEffect:
        return AgentControlEffect(
            operation_id=control.operation_id,
            code=code,
            config_revision=session.config_revision,
            inventory_revision=session.inventory_revision,
            availability_revision=session.availability_revision,
        )

    def _validate_reload_config(
        self,
        replacement: AgentTlsClientConfig,
        *,
        retained_work: bool | None = None,
    ) -> None:
        if not isinstance(replacement, AgentTlsClientConfig):
            raise QueueServiceError("trusted agent configuration is invalid")
        if (
            replacement.deployment_configuration_fingerprint
            != self._config.deployment_configuration_fingerprint
        ):
            raise QueueConflictError(
                "agent reload cannot replace immutable role configuration"
            )
        if (
            replacement.agent_root != self._config.agent_root
            or replacement.url != self._config.url
            or replacement.server_ca_path != self._config.server_ca_path
            or replacement.certificate_path != self._config.certificate_path
            or replacement.private_key_path != self._config.private_key_path
        ):
            raise QueueServiceError(
                "agent reload cannot replace its live transport or owner root"
            )
        if replacement.slurm_profiles and self._slurm_agent is None:
            raise QueueConflictError(
                "installing SLURM submission requires fresh agent-root initialization"
            )
        if _resident_launch_profile_set(replacement) != _resident_launch_profile_set(
            self._config
        ):
            raise QueueConflictError(
                "agent reload requires fresh agent-root initialization for "
                "resident profile set"
            )
        if retained_work is None:
            retained_work = self._has_retained_agent_work()
        if retained_work and _agent_active_fingerprint(
            replacement
        ) != _agent_active_fingerprint(self._config):
            raise QueueConflictError(
                "agent reload cannot replace active configuration with retained work"
            )
        existing = (*self._profiles.values(), *self._retained_profiles.values())
        for candidate in replacement.resident_profiles:
            for retained in existing:
                if (
                    retained_work
                    and retained.descriptor == candidate.descriptor
                    and _resident_profile_key(retained)
                    != _resident_profile_key(candidate)
                ):
                    raise QueueConflictError(
                        "agent reload reuses a live profile identity for changed bindings"
                    )

    def _has_retained_agent_work(self) -> bool:
        return _has_retained_agent_work(
            self._journal, self._execution_journal, self._slurm_agent
        )

    def _observe_supervisor_ownership(self, receipt: SupervisorReceipt) -> None:
        if receipt.state is SupervisorLaunchState.UNKNOWN:
            # Observation application is manager-owned, but can interleave with
            # another assignment's asynchronous admission query without a write.
            self._ownership_observation_generation += 1
            self._restart_with_retained_work = True
            self._service_recovery_admission = True

    def _admission_inventory(self):
        """Read the existing owners, including facts without a delivery view."""
        journal = self._require_journal()
        execution = self._execution_journal
        assert execution is not None
        references = journal.unresolved_assignment_references()
        with execution._transaction() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT assignment_id, identity_json, request_json, claims_json, "
                    "state, grant_fence, process_execution_id, result_json, availability_revision "
                    "FROM assignments ORDER BY assignment_id"
                )
            )
        pending = journal.pending_mutation_inventory()
        return (
            references,
            rows,
            pending,
            journal.active_session(),
            journal.pending_poll(),
            journal.next_unacknowledged_control(),
            journal.next_received_assignment_control(),
            journal.next_unacknowledged_assignment_control(),
        )

    @_cooperative
    @_serialized("_mutation_gate")
    def _qualify_service_admission(self) -> Generator[_Progress, Any, bool]:
        """Prove current recovery ownership without joining the workers' exit.

        Only the concurrent service can use this proof. The ordered mutation
        gate holds releases/session changes until the offer is prepared; local
        preparation and start completions invalidate the inventory across queries.
        No capacity snapshot or eligibility record survives this assessment.
        """
        if (
            self._service_progress
            and self._suspend_requested is not None
            and self._suspend_requested()
        ):
            return False
        if not self._service_progress or not self._service_recovery_admission:
            return not self._restart_with_retained_work
        self._restart_with_retained_work = True
        if self._drained or self._epoch_reconciliation_pending:
            return False
        if self._slurm_agent is not None and self._slurm_agent.has_retained_work():
            return False
        if not self._config.resident_profiles:
            self._restart_with_retained_work = self._has_retained_agent_work()
            return not self._restart_with_retained_work
        execution = self._execution_journal
        supervisor = self._supervisor
        if execution is None or supervisor is None:
            return False
        observation_generation = self._ownership_observation_generation
        inventory = self._admission_inventory()
        references, rows, pending, session, poll, control, received, acknowledgement = (
            inventory
        )
        if pending or poll or control or received or acknowledgement or session is None:
            return False
        ids = {assignment_id for _, assignment_id in references}
        states = {row["assignment_id"]: AssignmentState(row["state"]) for row in rows}
        if any(
            state is not AssignmentState.RELEASED and key not in ids
            for key, state in states.items()
        ):
            return False
        # A detached launch is not omitted just because its delivery disappeared.
        with sqlite3.connect(supervisor._root / "supervisor.sqlite") as conn:
            launches = tuple(conn.execute("SELECT launch_json, state FROM launches"))
        for encoded, state in launches:
            launch = _launch_from_value(json.loads(encoded))
            if launch.assignment_id not in ids and (
                state != SupervisorLaunchState.CONTAINED.value
                or states.get(launch.assignment_id) is not AssignmentState.RELEASED
            ):
                return False
        root = cast(Path, self._config.agent_root)
        for path in (root / "assignments").glob("*/resident.sqlite"):
            if (
                path.parent.name not in ids
                and states.get(path.parent.name) is not AssignmentState.RELEASED
            ):
                return False
        retained = execution.retained_claim_commands()
        if any(command.assignment.assignment_id not in ids for command in retained):
            return False
        self._runtime_owners(session)
        for session_id, assignment_id in references:
            if session_id != session.session_id:
                return False
            workspace = _ResidentAssignmentWorkspace(root, assignment_id)
            if not workspace.has_request():
                return False
            request = workspace.request()
            request.validate_remote_transport()
            if self._profile_for_descriptor(request.profile) is None:
                return False
            from ._shared_assignment import reference, verify_bundle

            ref = reference(
                self._require_journal().delivery_request(session_id, assignment_id)
            )
            if ref is not None:
                verify_bundle(ref, request, session_id=session_id)
            row = next(
                (row for row in rows if row["assignment_id"] == assignment_id), None
            )
            if row is None or json.loads(row["request_json"]) != request.to_dict():
                return False
            state = states[assignment_id]
            # Terminal acknowledgement precedes individual provider releases.
            # After interruption it cannot distinguish all-held from a partial
            # release; the existing release driver must finish that boundary.
            if state in {
                AssignmentState.PREPARE_UNKNOWN,
                AssignmentState.ACTIVATION_UNKNOWN,
                AssignmentState.TERMINAL_ACKNOWLEDGED,
                AssignmentState.PROVIDERS_RELEASED,
                AssignmentState.RELEASED,
            }:
                return False
            if (
                state is AssignmentState.REQUEST_DURABLE
                and row["claims_json"] is not None
            ):
                # A yielded partial preparation has not established its outcome.
                return False
            encoded = workspace.supervisor_launch_json()
            if encoded is None:
                if state in {
                    AssignmentState.REQUEST_DURABLE,
                    AssignmentState.PREPARED,
                    AssignmentState.ACCEPTED,
                    AssignmentState.GRANTED,
                    AssignmentState.ACTIVE,
                    AssignmentState.DECLINED,
                }:
                    continue
                if execution.definitive_start_failed(assignment_id):
                    continue
                return False
            launch = _launch_from_value(json.loads(encoded))
            if (
                launch.assignment_id != assignment_id
                or launch.session_id != session_id
                or launch.execution_fence != row["grant_fence"]
                or launch.continuity_epoch != supervisor.continuity_epoch
            ):
                return False
            try:
                receipt = yield from _external("control", supervisor.query, launch)
                self._observe_supervisor_ownership(receipt)
            except AgentProcessSupervisorError:
                return False
            if receipt.state not in {
                SupervisorLaunchState.STARTING,
                SupervisorLaunchState.RUNNING,
                SupervisorLaunchState.CONTAINED,
            }:
                return False
            if (
                receipt.started
                and receipt.state is not SupervisorLaunchState.CONTAINED
                and assignment_id not in self._joined_starts
            ):
                return False
        if (
            self._drained
            or self._epoch_reconciliation_pending
            or (self._suspend_requested is not None and self._suspend_requested())
            or inventory != self._admission_inventory()
            or observation_generation != self._ownership_observation_generation
        ):
            return False
        self._restart_with_retained_work = False
        if not references:
            self._service_recovery_admission = False
        return True

    def _reset_runtime_providers(self) -> None:
        self._configured_provider_members = None
        self._configured_provider_agent_id = None
        self._runtime_agent_id = None
        self._runtime_provider_key = None
        self._providers = {}

    @_cooperative
    def _cancel_active_assignments(self) -> Generator[_Progress, Any, bool]:
        journal = self._journal
        supervisor = self._supervisor
        if journal is None or supervisor is None:
            return True
        all_contained = True
        for _, assignment_id in journal.unresolved_assignment_references():
            workspace = _ResidentAssignmentWorkspace(
                cast(Path, self._config.agent_root), assignment_id
            )
            encoded_launch = workspace.supervisor_launch_json()
            if encoded_launch is None:
                continue
            try:
                launch = _launch_from_value(json.loads(encoded_launch))
                (yield from _external("bulk", supervisor.request_stop_wait, launch))
                receipt = (yield from _external("bulk", supervisor.contain, launch))
                self._observe_supervisor_ownership(receipt)
            except (AgentProcessSupervisorError, QueueError, ValueError):
                all_contained = False
                continue
            if receipt.state is not SupervisorLaunchState.CONTAINED:
                all_contained = False
                continue
            self._record_contained_cancellation(workspace)
        return all_contained

    def _record_contained_cancellation(
        self, workspace: _ResidentAssignmentWorkspace
    ) -> None:
        """Make a positive supervisor containment result restart-durable."""

        result_path = workspace.root / "worker-result.json"
        if not result_path.is_file():
            result = _cancelled_worker_result(workspace.worker_request())
            atomic_write_bytes(
                result_path,
                json.dumps(
                    result.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode(),
            )
        self._cancelled_assignments.add(workspace.assignment_id)

    @_cooperative
    def control_agent(self, control: AgentControl) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        """Issue the same typed operator command over authenticated HTTP."""
        return (yield from _steps(self._call,
            "agent_control", {"control": control.value()}, role="operator"
        ))

    @_cooperative
    def reload_scheduling(
        self, request: CoordinatorSchedulingReload
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "scheduling_reload", {"request": request.to_dict()}, role="operator"
        ))

    @_cooperative
    def recover_unknown(
        self, request: RecoverUnknownAssignment
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "recover_unknown", {"request": request.to_dict()}, role="operator"
        ))

    @_cooperative
    def recover_time(self, request: TimeRecoveryRequest) -> Generator[_Progress, Any, TimeRecoveryReceipt]:
        return TimeRecoveryReceipt.from_dict(
            (yield from _steps(self._call, "recover_time", {"request": request.to_dict()}, role="operator"))
        )

    @_cooperative
    def replace_agent_session(
        self, request: SessionReplacementRequest
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "replace_agent_session", {"request": request.to_dict()}, role="operator"
        ))

    @_cooperative
    def authorize_transfers(
        self,
        session_id: str,
        assignment_id: str,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "authorize",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "expected_revision": expected_revision,
                "operation_id": operation_id,
            },
        ))

    @_cooperative
    def read_input_chunk(
        self,
        session_id: str,
        assignment_id: str,
        transfer_id: str,
        *,
        offset: int,
        authorization_id: str,
        authorization_revision: int,
    ) -> Generator[_Progress, Any, tuple[bytes, int, bool]]:
        result = (yield from _steps(self._call,
            "input",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "transfer_id": transfer_id,
                "offset": offset,
                "authorization_id": authorization_id,
                "authorization_revision": authorization_revision,
            },
        ))
        data = _decode_chunk(result.get("data"))
        next_offset = result.get("next_offset")
        final = result.get("final")
        if (
            isinstance(next_offset, bool)
            or not isinstance(next_offset, int)
            or not isinstance(final, bool)
            or next_offset != offset + len(data)
        ):
            raise QueueServiceError("remote input chunk response is invalid")
        return data, next_offset, final

    @_cooperative
    def accept_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        request_digest: str,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "accept",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "request_digest": request_digest,
            },
        ))

    @_cooperative
    def start_permit(self, session_id: str, assignment_id: str, *, fence: str) -> Generator[_Progress, Any, bool]:
        result = (yield from _steps(self._call,
            "start_permit",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
            },
        ))
        permitted = result.get("permitted")
        if not isinstance(permitted, bool):
            raise QueueServiceError("remote start permit response is invalid")
        return permitted

    @_cooperative
    def poll_assignment_control(self, session_id: str) -> Generator[_Progress, Any, AgentAssignmentControl | None]:
        journal = self._require_journal()
        pending = journal.next_unacknowledged_assignment_control()
        if pending is not None:
            control, code, evidence = pending
            if self._service_progress and not _owns_assignment(control.assignment_id):
                return None
            if control.session_id != session_id:
                raise QueueConflictError(
                    "retained assignment control belongs to another session"
                )
            if code == "contained":
                self._cancelled_assignments.add(control.assignment_id)
            (yield from _steps(self._acknowledge_assignment_control, session_id, control, code, evidence))
            return control
        received = journal.next_received_assignment_control()
        if received is None:
            if self._service_progress:
                return None
            result = (yield from _steps(self._call, "assignment_control", {"session_id": session_id}))
            raw = result.get("control")
        else:
            raw = received.value()
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise QueueServiceError("assignment control response is invalid")
        control = AgentAssignmentControl.from_value(raw)
        if control.session_id != session_id:
            raise QueueConflictError("retained assignment control belongs to another session")
        self._received_cancellations.add(control.assignment_id)
        if self._service_progress and not _owns_assignment(control.assignment_id):
            journal.prepare_assignment_control(control)
            return None
        prior = journal.prepare_assignment_control(control)
        if prior is not None:
            code, evidence = prior
            (yield from _steps(self._acknowledge_assignment_control, session_id, control, code, evidence))
            return control
        code, evidence = (yield from _steps(self._apply_assignment_control, control))
        journal.record_assignment_control_result(control, code, evidence)
        (yield from _steps(self._acknowledge_assignment_control, session_id, control, code, evidence))
        return control

    @_cooperative
    def _acknowledge_assignment_control(
        self,
        session_id: str,
        control: AgentAssignmentControl,
        code: str,
        evidence: Mapping[str, PlainData] | None,
    ) -> Generator[_Progress, Any, None]:
        (yield from _steps(self._call,
            "assignment_control_ack",
            {
                "session_id": session_id,
                "operation_id": control.operation_id,
                "code": code,
                "evidence": None if evidence is None else dict(evidence),
            },
        ))
        workspace = _ResidentAssignmentWorkspace(cast(Path, self._config.agent_root), control.assignment_id)
        if (code == "never_started" and not workspace.has_request()
            and self._execution_journal is not None
            and self._execution_journal.find_state(control.assignment_id) is None):
            session = self._require_journal().session(session_id)
            providers, _ = self._runtime_owners(session)
            (yield from _steps(self.decline_assignment, session_id, control.assignment_id,
                availability_revision=self._availability_revision(session, control.assignment_id, providers)))
        self._require_journal().acknowledge_assignment_control(control.operation_id)

    @_cooperative
    def _apply_assignment_control(
        self, control: AgentAssignmentControl
    ) -> Generator[_Progress, Any, tuple[str, Mapping[str, PlainData] | None]]:
        with self._control_lock:
            journal = self._execution_journal
            if journal is None:
                return "unknown", None
            workspace = _ResidentAssignmentWorkspace(cast(Path, self._config.agent_root), control.assignment_id)
            raw = self._require_journal().delivery_request(control.session_id, control.assignment_id)
            from ._shared_assignment import reference
            if (not workspace.has_request() and reference(raw) is not None
                and control.fence is None and journal.find_state(control.assignment_id) is None):
                return "never_started", None
            try:
                state = journal.read_state(control.assignment_id)
                fence = journal.read_grant_fence(control.assignment_id)
            except Exception:
                return "unknown", None
            if control.fence != fence:
                return "unknown", None
            workspace = _ResidentAssignmentWorkspace(
                cast(Path, self._config.agent_root), control.assignment_id
            )
            encoded_launch = workspace.supervisor_launch_json()
            if encoded_launch is None:
                if state in {
                    AssignmentState.RESULT_DURABLE,
                    AssignmentState.TERMINAL_ACKNOWLEDGED,
                    AssignmentState.PROVIDERS_RELEASED,
                    AssignmentState.RELEASED,
                }:
                    result = journal.read_result(control.assignment_id)
                    if result is not None and result.status is StageStatus.CANCELLED:
                        # With no persisted launch, this result can only come
                        # from the native ACTIVE/no-start cancellation transition.
                        return "never_started", None
                    return "terminal", None
                if state in {
                    AssignmentState.REQUEST_DURABLE,
                    AssignmentState.PREPARED,
                    AssignmentState.ACCEPTED,
                    AssignmentState.GRANTED,
                    AssignmentState.ACTIVE,
                }:
                    return "never_started", None
                return "unknown", None
            if control.process_execution_id not in {
                None,
                f"{control.assignment_id}:root",
            }:
                return "unknown", None
            if self._supervisor is None:
                return "unknown", None
            try:
                launch = _launch_from_value(json.loads(encoded_launch))
                if (
                    launch.assignment_id != control.assignment_id
                    or launch.session_id != control.session_id
                    or (
                        control.process_execution_id is not None
                        and launch.process_execution_id != control.process_execution_id
                    )
                    or launch.execution_fence != control.fence
                ):
                    return "unknown", None
                (yield from _external("bulk", self._supervisor.request_stop_wait, launch))
                contained = (yield from _external("bulk", self._supervisor.contain, launch))
                self._observe_supervisor_ownership(contained)
            except (AgentProcessSupervisorError, QueueError, ValueError):
                return "unknown", None
            if contained.state is not SupervisorLaunchState.CONTAINED:
                return "unknown", None
            self._record_contained_cancellation(workspace)
            target_agent_id = self._runtime_agent_id
            if target_agent_id is None:
                return "unknown", None
            return "contained", _supervisor_containment_evidence(
                contained, agent_id=target_agent_id
            )

    @_cooperative
    @_serialized("_mutation_gate")
    def decline_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        availability_revision: str,
        reason_code: str | None = None,
    ) -> Generator[_Progress, Any, AgentSession]:
        (yield from _steps(self._replay_pending_resource_mutation, session_id))
        session = _session_from_value(
            (yield from _steps(self._call,
                "decline",
                {
                    "session_id": session_id,
                    "assignment_id": assignment_id,
                    "availability_revision": availability_revision,
                    "reason_code": reason_code,
                },
            ))
        )
        journal = self._require_journal()
        journal.persist_reconciled_session(session)
        journal.resolve_assignment_reference(session_id, assignment_id)
        self._next_resource_maintenance = 0
        return session

    @_cooperative
    def confirm_started(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        process_execution_id: str,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        result = (yield from _steps(self._call,
            "started",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
                "process_execution_id": process_execution_id,
            },
        ))
        self._joined_starts.add(assignment_id)
        return result

    @_cooperative
    def report_event(
        self,
        session_id: str,
        assignment_id: str,
        *,
        sequence: int,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "event",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "sequence": sequence,
                "event_id": event_id,
                "payload": thaw_plain_data(payload, path="remote event"),
            },
        ))

    @_cooperative
    def declare_outputs(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        authorization_id: str,
        authorization_revision: int,
        report: _RemoteExecutionReport,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "output_manifest",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
                "authorization_id": authorization_id,
                "authorization_revision": authorization_revision,
                "report": report.to_dict(),
            },
        ))

    @_cooperative
    def upload_output_chunk(
        self,
        session_id: str,
        assignment_id: str,
        transfer_id: str,
        *,
        offset: int,
        data: bytes,
        final: bool,
        authorization_id: str,
        authorization_revision: int,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "output",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "transfer_id": transfer_id,
                "offset": offset,
                "data": _encode_chunk(data),
                "final": final,
                "authorization_id": authorization_id,
                "authorization_revision": authorization_revision,
            },
        ))

    @_cooperative
    def commit_result(
        self, session_id: str, assignment_id: str, *, fence: str
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        return (yield from _steps(self._call,
            "result",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
            },
        ))

    @_cooperative
    @_serialized("_mutation_gate")
    def release_assignment(
        self,
        session_id: str,
        assignment_id: str,
        *,
        fence: str,
        availability_revision: str,
    ) -> Generator[_Progress, Any, AgentSession]:
        (yield from _steps(self._replay_pending_resource_mutation, session_id))
        journal = self._require_journal()
        execution_journal = self._execution_journal
        if execution_journal is None:
            raise QueueServiceError("remote execution journal is required")
        proof = journal.provider_release_proof(
            session_id, assignment_id, execution_journal
        )
        if (
            proof.execution_fence != fence
            or proof.released_availability_revision != availability_revision
        ):
            raise QueueConflictError("remote provider release proof is stale")
        session = _session_from_value(
            (yield from _steps(self._call,
                "release",
                {
                    "session_id": session_id,
                    "assignment_id": assignment_id,
                    "fence": fence,
                    "availability_revision": availability_revision,
                    "provider_release_proof": proof.value(),
                },
            ))
        )
        if session.state not in {AgentSessionState.ACTIVE, AgentSessionState.REPLACED}:
            raise QueueConflictError("remote release returned an invalid session state")
        journal.complete_assignment_release(session, assignment_id)
        self._next_resource_maintenance = 0
        return session

    @_cooperative
    @_serialized("_mutation_gate")
    def release_contained_assignment(
        self, session_id: str, assignment_id: str, *, fence: str
    ) -> Generator[_Progress, Any, AgentSession]:
        """Release providers from the old root after guarded containment closes."""

        journal = self._require_journal()
        session = journal.session(session_id)
        journal.contained_assignment_control(session_id, assignment_id, fence)
        readiness = (yield from _steps(self._call,
            "recovery_release_ready",
            {
                "session_id": session_id,
                "assignment_id": assignment_id,
                "fence": fence,
            },
        ))
        if readiness.get("ready") is not True:
            raise QueueConflictError("contained assignment authority close is pending")
        workspace = _ResidentAssignmentWorkspace(
            cast(Path, self._config.agent_root), assignment_id
        )
        request = workspace.request()
        request.validate_remote_transport()
        profile = self._profile_for_descriptor(request.profile)
        if profile is None:
            raise QueueConflictError("contained assignment has no exact resident profile")
        providers, execution_journal = self._runtime_owners(session)
        commands = execution_journal.assignment_claim_commands(assignment_id)
        assignment = ManagedAssignment(
            assignment_id=request.assignment_id,
            run_uri=f"loom-agent:{request.assignment_id}",
            stage_work_id=request.stage_work_id,
            stage_name=request.stage_name,
            attempt=request.attempt,
            attempt_id=request.attempt_id,
            agent_id=session.agent_id,
            session_id=session.session_id,
            offer_id=request.offer_id,
            claim_id=request.claim_id,
        )
        if (
            assignment.assignment_id != assignment_id
            or assignment.session_id != session_id
            or any(command.assignment != assignment for command in commands)
        ):
            raise QueueConflictError("contained assignment claim is stale")
        state = execution_journal.read_state(assignment_id)
        if state in {AssignmentState.START_INTENT, AssignmentState.START_UNKNOWN}:
            result = _cancelled_worker_result(workspace.worker_request())
            execution_journal.record_recovered_start_result(
                assignment_id,
                fence=fence,
                result=result.to_dict(),
            )
        elif state is AssignmentState.PROCESS_STARTED:
            result_path = workspace.root / "worker-result.json"
            if not result_path.is_file():
                raise QueueConflictError("contained assignment result is unavailable")
            result = StageWorkerResult.from_dict(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
            if result.status is StageStatus.SUCCEEDED:
                encoded = workspace.supervisor_launch_json()
                if encoded is None or self._supervisor is None:
                    raise QueueConflictError("contained result has no supervisor evidence")
                receipt = (yield from _external("bulk", self._supervisor.query_wait, _launch_from_value(json.loads(encoded))))
                self._observe_supervisor_ownership(receipt)
                if not receipt.qualified_success:
                    result = _managed_root_failed_worker_result(
                        workspace.worker_request(),
                        ManagedLocalError("worker backend success is unqualified"),
                        process_exit_code=receipt.exit_code,
                    )
            (yield from _external("bulk", workspace.persist_worker_result, result))
            execution_journal.record_result(assignment_id, result.to_dict())
        elif state not in {
            AssignmentState.RESULT_DURABLE,
            AssignmentState.TERMINAL_ACKNOWLEDGED,
            AssignmentState.PROVIDERS_RELEASED,
            AssignmentState.RELEASED,
        }:
            raise QueueConflictError("contained assignment is not provider-releasable")
        availability_revision = self._release_provider_claims(
            session,
            assignment,
            commands,
            providers,
            execution_journal,
        )
        return (yield from _steps(self.release_assignment,
            session_id,
            assignment_id,
            fence=fence,
            availability_revision=availability_revision,
        ))

    @_cooperative
    def drive_slurm_jobs(self) -> Generator[_Progress, Any, None]:
        if self._slurm_agent is None:
            return
        session = self.active_session()
        if session is None:
            return
        binding = {
            "session_id": session.session_id,
            "coordinator_epoch": session.coordinator_epoch,
            "cursor": self._slurm_cursor,
        }
        self._slurm_agent.replay_pending(
            lambda evidence: self._call(
                "slurm_work", {**binding, "evidence": dict(evidence)}
            )
        )
        response = (yield from _steps(self._call, "slurm_work", {**binding, "evidence": None}))
        cursor = response.get("next_cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise QueueServiceError("SLURM task cursor is invalid")
        self._slurm_cursor = cursor
        tasks = response.get("tasks")
        if not isinstance(tasks, (list, tuple)):
            raise QueueServiceError("SLURM task response is invalid")
        for task in tasks:
            if not isinstance(task, Mapping):
                raise QueueServiceError("SLURM task is invalid")
            self._slurm_agent.step(
                task,
                lambda evidence: self._call(
                    "slurm_work", {**binding, "evidence": dict(evidence)}
                ),
            )

    @_cooperative
    def execute_one(
        self,
        session_id: str,
        availability_revision: str,
        *,
        sequence: int,
        wait_timeout_ms: int,
        suspend_requested: Callable[[], bool] | None = None,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        """Poll and drive one resident assignment to ordered release.

        A suspension callback stops application observation at a durable replay
        boundary. It preserves the supervised worker, fence, and provider claims;
        an assignment already delivered is journalled and handed to its process
        owner before suspension. Poll/network calls retain their bounded waits.
        """

        (yield from _steps(self.drive_slurm_jobs))
        _raise_if_application_suspended(suspend_requested)
        delivery = (yield from _steps(self.wait_for_work,
            session_id,
            availability_revision,
            sequence=sequence,
            wait_timeout_ms=wait_timeout_ms,
        ))
        if delivery.get("result") != "assignment":
            return delivery
        try:
            request = (yield from _steps(self._resolve_delivery, session_id, delivery.get("request")))
        except (QueueError, OSError):
            # No provider claim exists yet to subtract this unresolved delivery
            # from an offer. Reuse the native retained-work startup barrier.
            self._restart_with_retained_work = True
            raise
        _raise_if_application_suspended(suspend_requested)
        return (yield from _steps(self._execute_delivered_assignment,
            session_id, request, suspend_requested=suspend_requested
        ))

    def _receive_service_controls(self) -> Generator[_Progress, Any, None]:
        """Retain control intent without joining containment or changing sessions.

        Each assignment view applies/acknowledges effects at its next boundary.
        This separate receipt path can request an exact stop while that view
        owns an input/publication operation. It never writes that workspace.
        """
        journal = self._journal
        if journal is None:
            return
        session = journal.active_session()
        if session is None:
            return
        response = yield from _steps(self._call, "assignment_control", {"session_id": session.session_id})
        if self._closed or journal is not self._journal:
            return
        raw = response.get("control")
        if raw is not None:
            control = AgentAssignmentControl.from_value(raw)
            journal.prepare_assignment_control(control)
            self._received_cancellations.add(control.assignment_id)
            encoded = _ResidentAssignmentWorkspace.read_supervisor_launch_json(
                cast(Path, self._config.agent_root), control.assignment_id)
            if encoded is not None and self._supervisor is not None:
                launch = _launch_from_value(json.loads(encoded))
                if (launch.session_id == control.session_id
                    and launch.assignment_id == control.assignment_id
                    and launch.execution_fence == control.fence
                    and control.process_execution_id in {None, launch.process_execution_id}):
                    yield from _external("control", self._supervisor.request_stop, launch)
        # Native drain preparation fences polls, so it must wait for exact poll
        # settlement. Receipt of a late delivery is never replaced by withdrawal.
        if self._closed or journal.pending_poll() is not None:
            return
        response = yield from _steps(self._call, "control", {"session_id": session.session_id})
        if self._closed or journal is not self._journal or journal.pending_poll() is not None:
            return
        raw = response.get("control")
        if raw is not None:
            control = AgentControl.from_value(raw)
            self._service_control_due = True
            journal.prepare_control(control)
            if control.kind.value in {"drain", "reload"}:
                self._drained = True
            if control.cancel_active:
                for _, assignment_id in journal.unresolved_assignment_references():
                    self._received_cancellations.add(assignment_id)
                    encoded = _ResidentAssignmentWorkspace.read_supervisor_launch_json(
                        cast(Path, self._config.agent_root), assignment_id)
                    if encoded is not None and self._supervisor is not None:
                        yield from _external("control", self._supervisor.request_stop, _launch_from_value(json.loads(encoded)))

    @_cooperative
    def _resolve_delivery(self, session_id: str, raw: object) -> Generator[_Progress, Any, _ResidentAssignmentBundle]:
        from ._shared_assignment import reference, resolve, verify_bundle
        ref = reference(raw)
        if ref is None:
            return _ResidentAssignmentBundle.from_remote_dict(thaw_plain_data(raw))
        profile = next((item for item in (*self._profiles.values(), *self._retained_profiles.values())
            if item.descriptor.profile_id == ref["profile_id"]
            and item.descriptor.fingerprint == ref["profile_fingerprint"]), None)
        if profile is None:
            raise QueueConflictError("shared assignment reference has no exact protected profile")
        workspace = _ResidentAssignmentWorkspace(cast(Path, self._config.agent_root), str(ref["assignment_id"]))
        if workspace.has_request():
            request = workspace.request()
            verify_bundle(ref, request, session_id=session_id)
            return request
        request = (yield from _external("bulk", resolve, ref, profile, session_id=session_id))
        (yield from _external("bulk", workspace.persist_request, request, profile))
        return request

    @_cooperative
    def _execute_delivered_assignment(
        self,
        session_id: str,
        request: _ResidentAssignmentBundle,
        *,
        suspend_requested: Callable[[], bool] | None = None,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        """Drive one already durable delivery through the native input/grant path."""
        profile = self._profile_for_descriptor(request.profile)
        if profile is None:
            raise QueueConflictError(
                "delivered assignment has no exact resident profile"
            )
        session = self._require_journal().session(session_id)
        workspace = _ResidentAssignmentWorkspace(
            cast(Path, self._config.agent_root), request.assignment_id
        )
        (yield from _external("bulk", workspace.persist_request, request, profile))
        self._require_journal().retain_assignment_reference(
            session_id, request.assignment_id
        )
        providers, execution_journal = self._runtime_owners(session)
        assignment = ManagedAssignment(
            assignment_id=request.assignment_id,
            run_uri=f"loom-agent:{request.assignment_id}",
            stage_work_id=request.stage_work_id,
            stage_name=request.stage_name,
            attempt=request.attempt,
            attempt_id=request.attempt_id,
            agent_id=session.agent_id,
            session_id=session.session_id,
            offer_id=request.offer_id,
            claim_id=request.claim_id,
        )
        commands = tuple(
            ClaimCommand(
                assignment,
                f"{request.assignment_id}:prepare:{index}",
                claim,
                {
                    descriptor.kind: descriptor
                    for descriptor in request.provider_descriptors
                }[claim.resource_kind],
            )
            for index, claim in enumerate(request.claims)
        )
        execution_journal.persist_request(assignment, request.to_dict())
        cancelled = (yield from _steps(self._cancel_pregrant_if_requested,
            session,
            request.assignment_id,
            assignment,
            commands,
            providers,
            execution_journal,
        ))
        if cancelled is not None:
            return cancelled

        authorization = (yield from _steps(self._fresh_transfer_authorization,
            session_id=session_id,
            assignment_id=request.assignment_id,
            expected_revision=0,
        ))
        authorization_id = cast(str, authorization["authorization_id"])
        authorization_revision = cast(int, authorization["revision"])
        for item in request.inputs:
            from loom.pipeline.stores.shared_artifacts import binding
            if binding(item.metadata) is not None:
                continue
            offset = 0
            while True:
                response, authorization_id, authorization_revision = (
                    (yield from _steps(self._authorized_transfer_call,
                        session_id=session_id,
                        assignment_id=request.assignment_id,
                        authorization_id=authorization_id,
                        authorization_revision=authorization_revision,
                        operation=lambda current_id, current_revision: (
                            _steps(self.read_input_chunk,
                                session_id,
                                request.assignment_id,
                                item.transfer_id,
                                offset=offset,
                                authorization_id=current_id,
                                authorization_revision=current_revision,
                            )
                        ),
                    ))
                )
                data, next_offset, final = cast(tuple[bytes, int, bool], response)
                (yield from _external("bulk", workspace.stage_input_chunk,
                    item.transfer_id,
                    offset,
                    data,
                    final=final,
                ))
                _raise_if_application_suspended(suspend_requested)
                offset = next_offset
                (yield from _steps(self._maintain_resource_offer))
                if final:
                    break
        if execution_journal.read_grant_fence(assignment.assignment_id) is None:
            (yield from _external("bulk", workspace.accept))
        prepared = yield from _steps(
            execution_journal.prepare_composite, assignment, commands, providers
        )
        self._next_resource_maintenance = 0
        if prepared is AssignmentState.DECLINED:
            return (yield from _steps(self._decline_pregrant_assignment,
                session, assignment, commands, providers, execution_journal))
        if prepared not in {
            AssignmentState.PREPARED,
            AssignmentState.ACCEPTED,
            AssignmentState.GRANTED,
            AssignmentState.ACTIVE,
            AssignmentState.PROCESS_STARTED,
            AssignmentState.RESULT_DURABLE,
        }:
            raise QueueConflictError("remote physical admission is indeterminate")
        execution_journal.accept(assignment.assignment_id)
        workspace.append_event(
            f"{request.assignment_id}:request-inputs-durable",
            {"kind": "request_and_inputs_durable"},
        )
        cancelled = (yield from _steps(self._cancel_pregrant_if_requested,
            session,
            request.assignment_id,
            assignment,
            commands,
            providers,
            execution_journal,
        ))
        if cancelled is not None:
            return cancelled
        request_json = json.dumps(
            request.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        try:
            grant = cast(
                Mapping[str, PlainData],
                (yield from _steps(self._assignment_call,
                    session_id,
                    request.assignment_id,
                    lambda: _steps(self.accept_assignment,
                        session_id,
                        request.assignment_id,
                        request_digest=hashlib.sha256(
                            request_json.encode()
                        ).hexdigest(),
                    ),
                )),
            )
        except QueueConflictError as conflict:
            deadline = monotonic() + 5
            while monotonic() < deadline:
                cancelled = (yield from _steps(self._cancel_pregrant_if_requested,
                    session,
                    request.assignment_id,
                    assignment,
                    commands,
                    providers,
                    execution_journal,
                ))
                if cancelled is not None:
                    return cancelled
                (yield from _delay(0.05))
            raise conflict
        fence = cast(str, grant["fence"])
        execution_journal.grant(assignment.assignment_id, fence)
        workspace.grant(fence)
        activated = execution_journal.activate_composite(
            assignment.assignment_id, commands, providers
        )
        if activated not in {
            AssignmentState.ACTIVE,
            AssignmentState.PROCESS_STARTED,
            AssignmentState.RESULT_DURABLE,
        }:
            raise QueueConflictError("remote physical activation is indeterminate")

        execution_id = f"{request.assignment_id}:root"
        supervisor = self._supervisor
        if supervisor is None:
            raise QueueConflictError("remote resident execution has no supervisor")
        launch: ResidentWorkerLaunch | None = None
        result_path = workspace.root / "worker-result.json"
        completed_before_start = False
        if execution_journal.read_state(assignment.assignment_id) in {
            AssignmentState.ACTIVE,
        }:

            def start_supervisor_launch() -> Generator[_Progress, Any, str]:
                nonlocal launch
                while self._epoch_reconciliation_pending:
                    _raise_if_application_suspended(suspend_requested)
                    yield from _delay(0.01)
                try:
                    launch = build_supervisor_launch()
                except (ValueError, QueueError, OSError, ContainerOptionError) as exc:
                    # No supervisor call has occurred: construction failure is
                    # definite no-start evidence, not an uncertain process.
                    raise ManagedProcessStartError(str(exc)) from exc
                workspace.persist_supervisor_launch(
                    json.dumps(
                        _launch_value(launch), sort_keys=True, separators=(",", ":")
                    )
                )
                from ._agent_process_supervisor import _SupervisorNoStartError

                try:
                    receipt = (yield from _external("bulk", supervisor.launch, launch))
                except _SupervisorNoStartError as exc:
                    if not (yield from _external("control", supervisor.reject_unstarted_assignment,
                                                request.assignment_id)):
                        raise QueueConflictError("rejected launch ownership is unresolved") from exc
                    raise ManagedProcessStartError(str(exc)) from exc
                self._observe_supervisor_ownership(receipt)
                if (
                    receipt.state
                    in {
                        SupervisorLaunchState.NOT_ACCEPTED,
                        SupervisorLaunchState.UNKNOWN,
                    }
                    or not receipt.started
                ):
                    raise QueueConflictError(
                        "remote supervisor has not established whether a process root was created"
                    )
                workspace.mark_process_started(execution_id, receipt.process_id)
                return execution_id

            def build_supervisor_launch() -> ResidentWorkerLaunch:
                environment = _worker_environment(
                    profile.launch_profile,
                    workspace.root,
                    commands,
                    providers,
                    cast(
                        Mapping[str, object],
                        request.resolved_runtime.get("resource_selection"),
                    ),
                )
                candidate = ResidentWorkerLaunch(
                    supervisor_id=supervisor.supervisor_id,
                    continuity_epoch=supervisor.continuity_epoch,
                    agent_id=supervisor.agent_id,
                    session_id=session.session_id,
                    assignment_id=request.assignment_id,
                    process_execution_id=execution_id,
                    execution_fence=fence,
                    launch_operation_id=f"{request.assignment_id}:launch:{fence}",
                    bundle_digest=hashlib.sha256(
                        _canonical_json(request.to_dict()).encode("utf-8")
                    ).hexdigest(),
                    workspace_root=workspace.root,
                    profile=profile.launch_profile,
                    environment=environment,
                    resource_controls=_managed_resource_controls(
                        request.resolved_runtime, bindings_prepared=True
                    ),
                )
                if candidate.profile.container is not None:
                    from loom.pipeline.runtime._resource_controls import _validated_resource_controls

                    candidate = replace(candidate, resource_controls=_validated_resource_controls(
                        candidate.container_command.metadata.get("resource_controls")
                    ))
                return candidate

            with self._control_lock:
                _raise_if_application_suspended(suspend_requested)
                permitted = cast(
                    bool,
                    (yield from _steps(self._assignment_call,
                        session_id,
                        request.assignment_id,
                        lambda: _steps(self.start_permit,
                            session_id, request.assignment_id, fence=fence
                        ),
                    )),
                )
                if permitted and request.assignment_id in self._received_cancellations:
                    rejected = yield from _external("control", supervisor.reject_unstarted_assignment, request.assignment_id)
                    if not rejected:
                        raise QueueConflictError("cancelled assignment start ownership is unresolved")
                    permitted = False
                if not permitted:
                    result = _cancelled_worker_result(workspace.worker_request())
                    atomic_write_bytes(
                        result_path,
                        json.dumps(
                            result.to_dict(),
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode(),
                    )
                    workspace.persist_cancelled_before_start(result)
                    execution_journal.record_cancelled_before_start(
                        assignment.assignment_id, result.to_dict()
                    )
                    completed_before_start = True
                else:
                    try:
                        yield from _start_once_steps(
                            execution_journal,
                            assignment.assignment_id,
                            execution_id,
                            start_supervisor_launch,
                            start_failure=lambda error: _start_failed_worker_result(
                                workspace.worker_request(), error
                            ),
                        )
                    except ManagedProcessStartError:
                        result = cast(
                            StageWorkerResult,
                            execution_journal.read_result(assignment.assignment_id),
                        )
                        atomic_write_bytes(
                            result_path,
                            json.dumps(
                                result.to_dict(),
                                sort_keys=True,
                                separators=(",", ":"),
                                allow_nan=False,
                            ).encode(),
                        )
                        execution_journal.require_failed_before_start(
                            assignment.assignment_id, fence=fence
                        )
                        workspace.persist_failed_before_start(
                            result, fence=fence, supervisor_rejected=launch is not None
                        )
                        execution_journal.record_result(
                            assignment.assignment_id, result.to_dict()
                        )
                        completed_before_start = True
                    else:
                        workspace.append_event(
                            f"{request.assignment_id}:agent-process-started",
                            {"kind": "process_started"},
                        )
                        (yield from _steps(self._assignment_call,
                            session_id,
                            request.assignment_id,
                            lambda: _steps(self.confirm_started,
                                session_id,
                                request.assignment_id,
                                fence=fence,
                                process_execution_id=execution_id,
                            ),
                        ))
        if not completed_before_start:
            (yield from _steps(self._flush_workspace_events, session_id, workspace))
        if launch is None:
            retained_launch = workspace.supervisor_launch_json()
            if retained_launch is not None:
                launch = _launch_from_value(json.loads(retained_launch))
        if launch is not None and not completed_before_start:
            while True:
                _raise_if_application_suspended(suspend_requested)
                receipt = (yield from _external("control", supervisor.query, launch))
                self._observe_supervisor_ownership(receipt)
                if receipt.state in {
                    SupervisorLaunchState.EXITED,
                    SupervisorLaunchState.CONTAINED,
                }:
                    break
                if receipt.state is SupervisorLaunchState.UNKNOWN:
                    raise QueueConflictError("remote supervisor continuity is unknown")
                (yield from _steps(self.poll_assignment_control, session_id))
                (yield from _steps(self._maintain_resource_offer))
                (yield from _delay(0.05))
            if not (yield from _steps(self._settle_supervised_worker_result, workspace, launch, receipt)):
                raise QueueConflictError("remote process group containment is unknown")
        elif not result_path.is_file():
            raise QueueConflictError(
                "remote process outcome is unknown and cannot be relaunched"
            )
        return (yield from _steps(self._complete_remote_result_and_release,
            session,
            request,
            workspace,
            assignment,
            commands,
            providers,
            execution_journal,
            fence=fence,
            authorization_revision=authorization_revision,
            persist_result=not completed_before_start,
            result_path_label="remote execution completion",
            # A proven no-start outcome completes without a supervisor to join.
            suspend_requested=suspend_requested if launch is not None else None,
        ))

    @_cooperative
    @_serialized("_mutation_gate")
    def _resume_pending_poll(
        self,
        *,
        wait_timeout_ms: int,
        suspend_requested: Callable[[], bool] | None = None,
    ) -> Generator[_Progress, Any, None]:
        return (yield from _session_protocol._resume_pending_poll(self, wait_timeout_ms=wait_timeout_ms, suspend_requested=suspend_requested))

    @_cooperative
    def resume_retained_work(
        self, *, suspend_requested: Callable[[], bool] | None = None
    ) -> Generator[_Progress, Any, tuple[Mapping[str, PlainData], ...]]:
        """Join continuous supervisor receipts before releasing startup capacity.

        This is deliberately an explicit application-start step: no offer or
        poll can bypass it, and an unknown receipt leaves its reference and
        provider claim unavailable.

        Suspension preserves the same retained references for the next service
        incarnation and never releases capacity or cancels its supervised work.
        """

        return (yield from _steps(
            self._resume_retained_assignments,
            self._require_journal().unresolved_assignment_references(),
            suspend_requested=suspend_requested,
        ))

    @_cooperative
    def _resume_retained_assignments(
        self, references, *, suspend_requested=None
    ):
        """Shared exact recovery transitions; the service gives each ID a view."""
        _raise_if_application_suspended(suspend_requested)
        journal = self._require_journal()
        execution_journal = self._execution_journal
        supervisor = self._supervisor
        if (
            not self._config.resident_profiles
            and not journal.unresolved_assignment_references()
        ):
            self._restart_with_retained_work = False
            return ()
        if execution_journal is None or supervisor is None:
            raise QueueConflictError("remote restart has no supervisor journal")
        completed: list[Mapping[str, PlainData]] = []
        for session_id, assignment_id in references:
            _raise_if_application_suspended(suspend_requested)
            session = journal.session(session_id)
            workspace = _ResidentAssignmentWorkspace(
                cast(Path, self._config.agent_root), assignment_id
            )
            raw_delivery = journal.delivery_request(session_id, assignment_id)
            if not workspace.has_request():
                if raw_delivery is None:
                    raise QueueConflictError("retained assignment delivery is unavailable")
                (yield from _steps(self._assignment_call, session_id, assignment_id, lambda: _steps(self.poll_assignment_control, session_id)))
                if (session_id, assignment_id) not in journal.unresolved_assignment_references():
                    continue
                request = (yield from _steps(self._resolve_delivery, session_id, raw_delivery))
                completed.append((yield from _steps(self._execute_delivered_assignment, session_id, request, suspend_requested=suspend_requested)))
                continue
            request = workspace.request()
            if raw_delivery is not None:
                from ._shared_assignment import reference, verify_bundle
                ref = reference(raw_delivery)
                if ref is not None:
                    verify_bundle(ref, request, session_id=session_id)
            request.validate_remote_transport()
            profile = self._profile_for_descriptor(request.profile)
            if profile is None:
                raise QueueConflictError("retained assignment has no resident profile")
            assignment = ManagedAssignment(
                assignment_id=request.assignment_id,
                run_uri=f"loom-agent:{request.assignment_id}",
                stage_work_id=request.stage_work_id,
                stage_name=request.stage_name,
                attempt=request.attempt,
                attempt_id=request.attempt_id,
                agent_id=session.agent_id,
                session_id=session.session_id,
                offer_id=request.offer_id,
                claim_id=request.claim_id,
            )
            # Workspace publication may have committed immediately before the
            # application stopped, before the execution journal saw the bundle.
            execution_journal.persist_request(assignment, request.to_dict())
            providers, _ = self._runtime_owners(session)
            if execution_journal.read_state(assignment_id) is AssignmentState.RELEASED:
                # The release reply may be lost after coordinator acceptance.
                # Replay its retained proof, not an already committed output manifest.
                retained_fence = execution_journal.read_grant_fence(assignment_id)
                revision = cast(str, execution_journal.read_availability_revision(assignment_id))
                if retained_fence is None:
                    released = yield from _steps(
                        self.decline_assignment, session_id, assignment_id,
                        availability_revision=revision,
                        reason_code=execution_journal.read_decline_reason(assignment_id),
                    )
                else:
                    released = yield from _steps(
                        self.release_assignment, session_id, assignment_id,
                        fence=retained_fence, availability_revision=revision,
                    )
                completed.append(freeze_plain_data({
                    "result": "assignment", "assignment_id": assignment_id,
                    "state": "RELEASED", "session": released.value(),
                }, path="remote release restart completion"))
                continue
            launch_json = workspace.supervisor_launch_json()
            if (
                launch_json is None
                and execution_journal.read_state(assignment_id)
                in {
                    AssignmentState.REQUEST_DURABLE,
                    AssignmentState.PREPARED,
                    AssignmentState.ACCEPTED,
                    AssignmentState.GRANTED,
                    AssignmentState.ACTIVE,
                }
            ):
                # Continue this exact delivery. The service separately proves
                # the whole inventory before admission; commands may not yet
                # exist when the interruption was during input.
                completed.append(
                    (yield from _steps(self._execute_delivered_assignment,
                        session_id, request, suspend_requested=suspend_requested
                    ))
                )
                continue
            commands = execution_journal.assignment_claim_commands(assignment_id)
            if launch_json is None or execution_journal.definitive_start_failed(assignment_id):
                retained_fence = execution_journal.read_grant_fence(assignment_id)
                if launch_json is not None and not (yield from _external(
                    "control", supervisor.reject_unstarted_assignment, assignment_id
                )):
                    raise QueueConflictError("failed launch ownership is unresolved")
                with self._control_lock:
                    if (
                        retained_fence is not None
                        and workspace.supervisor_launch_json() is None
                        and execution_journal.read_state(assignment_id) in {
                            AssignmentState.START_INTENT, AssignmentState.START_UNKNOWN
                        }
                    ):
                        # The supervisor atomically checks historical acceptance
                        # and fences all future launches. Absence alone is not proof.
                        if not (yield from _external("bulk", supervisor.reject_unstarted_assignment, assignment_id)):
                            continue
                        execution_journal.record_supervisor_rejected_start(
                            assignment_id, fence=retained_fence,
                            result=_start_failed_worker_result(
                                workspace.worker_request(),
                                ManagedProcessStartError(
                                    "supervisor durably rejected unstarted assignment during recovery"
                                ),
                            ),
                        )
                retained_result = (
                    execution_journal.read_result(assignment_id)
                    if execution_journal.definitive_start_failed(assignment_id)
                    else workspace.worker_result()
                )
                if retained_fence is None:
                    continue
                if (
                    retained_result is None
                    and execution_journal.read_state(assignment_id)
                    is AssignmentState.START_FAILED
                ):
                    result_path = workspace.root / "worker-result.json"
                    if result_path.is_file():
                        retained_result = StageWorkerResult.from_dict(
                            json.loads(result_path.read_text())
                        )
                if (
                    retained_result is not None
                    and retained_result.status is StageStatus.FAILED
                ):
                    execution_journal.require_failed_before_start(
                        assignment_id, fence=retained_fence
                    )
                    result_path = workspace.root / "worker-result.json"
                    if not result_path.is_file():
                        atomic_write_bytes(
                            result_path,
                            _canonical_json(retained_result.to_dict()).encode(),
                        )
                    workspace.persist_failed_before_start(
                        retained_result, fence=retained_fence,
                        supervisor_rejected=launch_json is not None,
                    )
                    execution_journal.record_result(
                        assignment_id, retained_result.to_dict()
                    )
                elif (
                    retained_result is not None
                    and retained_result.status is StageStatus.CANCELLED
                ):
                    if execution_journal.read_result(assignment_id) != retained_result:
                        continue
                else:
                    # Absence of a launch alone cannot establish safe release.
                    continue
                completed.append(
                    (yield from _steps(self._complete_remote_result_and_release,
                        session,
                        request,
                        workspace,
                        assignment,
                        commands,
                        providers,
                        execution_journal,
                        fence=retained_fence,
                        authorization_revision=0,
                        persist_result=False,
                        result_path_label="remote no-start restart completion",
                        suspend_requested=suspend_requested,
                    ))
                )
                continue
            launch = _launch_from_value(json.loads(launch_json))
            receipt = (yield from _external("bulk", supervisor.query_wait, launch))
            self._observe_supervisor_ownership(receipt)
            if (
                launch.continuity_epoch in supervisor.reboot_generations
                and receipt.exit_code is None
            ):
                # A reboot proves containment, never a scientific terminal result.
                # Keep capacity withheld until the operator's guarded close wins.
                (yield from _steps(self._assignment_call,
                    session_id,
                    assignment_id,
                    lambda: _steps(self.poll_assignment_control, session_id),
                ))
                ready = (yield from _steps(self._assignment_call,
                    session_id,
                    assignment_id,
                    lambda: _steps(self._call,
                        "recovery_release_ready",
                        {
                            "session_id": session_id,
                            "assignment_id": assignment_id,
                            "fence": launch.execution_fence,
                        },
                    ),
                ))
                if ready.get("ready") is True:
                    (yield from _steps(self._assignment_call,
                        session_id,
                        assignment_id,
                        lambda: _steps(self.release_contained_assignment,
                            session_id,
                            assignment_id,
                            fence=launch.execution_fence,
                        ),
                    ))
                continue
            if receipt.state is SupervisorLaunchState.NOT_ACCEPTED:
                # The complete exact operation was journaled before the service
                # call. Submitting that operation is replay, never relaunch.
                while self._epoch_reconciliation_pending:
                    _raise_if_application_suspended(suspend_requested)
                    yield from _delay(0.01)
                from ._agent_process_supervisor import _SupervisorNoStartError

                try:
                    receipt = (yield from _external("bulk", supervisor.launch, launch))
                except _SupervisorNoStartError as exc:
                    if not (yield from _external("control", supervisor.reject_unstarted_assignment,
                                                assignment_id)):
                        raise QueueConflictError("rejected launch ownership is unresolved") from exc
                    execution_journal.record_supervisor_rejected_start(
                        assignment_id, fence=launch.execution_fence,
                        result=_start_failed_worker_result(
                            workspace.worker_request(), ManagedProcessStartError(str(exc))
                        ),
                    )
                    completed.extend((yield from _steps(
                        self._resume_retained_assignments, ((session_id, assignment_id),),
                        suspend_requested=suspend_requested,
                    )))
                    continue
                self._observe_supervisor_ownership(receipt)
            if receipt.state is SupervisorLaunchState.UNKNOWN:
                continue
            needs_start_join = execution_journal.read_state(assignment_id) in {
                AssignmentState.START_INTENT,
                AssignmentState.START_UNKNOWN,
                AssignmentState.PROCESS_STARTED,
            }
            if needs_start_join and receipt.started:
                (yield from _steps(self._join_retained_supervised_start,
                    session,
                    request,
                    workspace,
                    execution_journal,
                    launch,
                    receipt.process_id,
                ))
                needs_start_join = False
            while receipt.state in {
                SupervisorLaunchState.STARTING,
                SupervisorLaunchState.RUNNING,
            }:
                _raise_if_application_suspended(suspend_requested)
                (yield from _steps(self.poll_assignment_control, session_id))
                (yield from _delay(0.05))
                receipt = (yield from _external("control", supervisor.query, launch))
                self._observe_supervisor_ownership(receipt)
                if needs_start_join and receipt.started:
                    (yield from _steps(self._join_retained_supervised_start,
                        session,
                        request,
                        workspace,
                        execution_journal,
                        launch,
                        receipt.process_id,
                    ))
                    needs_start_join = False
                if receipt.state is SupervisorLaunchState.UNKNOWN:
                    break
            if receipt.state is SupervisorLaunchState.UNKNOWN:
                continue
            if not (yield from _steps(self._settle_supervised_worker_result, workspace, launch, receipt)):
                continue
            completed.append(
                (yield from _steps(self._complete_remote_result_and_release,
                    session,
                    request,
                    workspace,
                    assignment,
                    commands,
                    providers,
                    execution_journal,
                    fence=launch.execution_fence,
                    authorization_revision=0,
                    persist_result=True,
                    result_path_label="remote restart completion",
                    suspend_requested=suspend_requested,
                ))
            )
        if not self._service_progress:
            self._restart_with_retained_work = self._has_retained_agent_work()
        return tuple(completed)

    @_cooperative
    def _settle_supervised_worker_result(
        self,
        workspace: _ResidentAssignmentWorkspace,
        launch: ResidentWorkerLaunch,
        receipt: SupervisorReceipt,
    ) -> Generator[_Progress, Any, bool]:
        """Close a known root exit only with continuous group/result evidence."""

        if receipt.state not in {
            SupervisorLaunchState.EXITED,
            SupervisorLaunchState.CONTAINED,
        }:
            return False
        supervisor = self._supervisor
        if supervisor is None:
            raise QueueConflictError("remote completion has no process owner")
        if workspace.assignment_id in self._received_cancellations:
            yield from _steps(self.poll_assignment_control, launch.session_id)
        result_path = workspace.root / "worker-result.json"
        if not result_path.is_file():
            if workspace.assignment_id in self._cancelled_assignments:
                self._record_contained_cancellation(workspace)
            else:
                result = _managed_root_failed_worker_result(
                    workspace.worker_request(),
                    ManagedLocalError(
                        "resident worker exited without a durable worker result"
                    ),
                    process_exit_code=receipt.exit_code,
                )
                atomic_write_bytes(
                    result_path,
                    json.dumps(
                        result.to_dict(),
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode(),
                )
        contained = (yield from _external("bulk", supervisor.contain, launch))
        self._observe_supervisor_ownership(contained)
        if contained.state is not SupervisorLaunchState.CONTAINED:
            return False
        if (
            contained.worker_result_digest
            != hashlib.sha256(result_path.read_bytes()).hexdigest()
        ):
            raise QueueConflictError(
                "remote supervisor result evidence does not match the workspace"
            )
        return True

    @_cooperative
    def _join_retained_supervised_start(
        self,
        session: AgentSession,
        request: _ResidentAssignmentBundle,
        workspace: _ResidentAssignmentWorkspace,
        execution_journal: SQLiteAgentJournal,
        launch: ResidentWorkerLaunch,
        process_id: int | None,
    ) -> Generator[_Progress, Any, None]:
        """Join one exact accepted launch across the application crash barrier."""

        workspace.mark_process_started(launch.process_execution_id, process_id)
        execution_journal.confirm_supervised_start(
            request.assignment_id, launch.process_execution_id
        )
        workspace.append_event(
            f"{request.assignment_id}:agent-process-started",
            {"kind": "process_started"},
        )
        (yield from _steps(self._assignment_call,
            session.session_id,
            request.assignment_id,
            lambda: _steps(self.confirm_started,
                session.session_id,
                request.assignment_id,
                fence=launch.execution_fence,
                process_execution_id=launch.process_execution_id,
            ),
        ))
        (yield from _steps(self._flush_workspace_events, session.session_id, workspace))

    @_cooperative
    def _complete_remote_result_and_release(
        self,
        session: AgentSession,
        request: _ResidentAssignmentBundle,
        workspace: _ResidentAssignmentWorkspace,
        assignment: ManagedAssignment,
        commands: tuple[ClaimCommand, ...],
        providers: Mapping[str, AgentResourceProvider],
        execution_journal: SQLiteAgentJournal,
        *,
        fence: str,
        authorization_revision: int,
        persist_result: bool,
        result_path_label: str,
        suspend_requested: Callable[[], bool] | None = None,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        """Own normal and restart result/output/outbox completion ordering."""

        yield from _steps(self._assignment_call, session.session_id, request.assignment_id,
                          lambda: _steps(self.poll_assignment_control, session.session_id))
        result_path = workspace.root / "worker-result.json"
        result = (
            StageWorkerResult.from_dict(json.loads(result_path.read_text()))
            if persist_result
            else workspace.worker_result()
        )
        if result is None:
            raise QueueConflictError("remote completion has no durable result")
        completed_before_start = (
            result.status in {StageStatus.CANCELLED, StageStatus.FAILED}
            and (workspace.supervisor_launch_json() is None
                 or execution_journal.definitive_start_failed(request.assignment_id))
        )
        if completed_before_start and result.status is StageStatus.FAILED:
            execution_journal.require_failed_before_start(
                request.assignment_id, fence=fence
            )
            retained_launch = workspace.supervisor_launch_json() is not None
            if retained_launch and (
                self._supervisor is None or not (yield from _external(
                    "control", self._supervisor.reject_unstarted_assignment, request.assignment_id
                ))
            ):
                raise QueueConflictError("failed launch ownership is unresolved")
            workspace.persist_failed_before_start(
                result, fence=fence, supervisor_rejected=retained_launch
            )
        if persist_result:
            retained = workspace.worker_result()
            if retained is not None:
                result = retained
            elif workspace.supervisor_launch_json() is not None:
                launch = _launch_from_value(
                    json.loads(cast(str, workspace.supervisor_launch_json()))
                )
                if self._supervisor is None:
                    raise QueueConflictError("remote completion lost its supervisor")
                evidence = (yield from _external("bulk", self._supervisor.query_wait, launch))
                self._observe_supervisor_ownership(evidence)
                if evidence.state is not SupervisorLaunchState.CONTAINED:
                    raise QueueConflictError("remote completion lacks containment")
                if (
                    result.status is StageStatus.SUCCEEDED
                    and not evidence.qualified_success
                ):
                    result = _managed_root_failed_worker_result(
                        workspace.worker_request(),
                        ManagedLocalError("worker backend success is unqualified"),
                        process_exit_code=evidence.exit_code,
                    )
                metadata = dict(result.executor_metadata)
                metadata.pop("managed_successful_exit", None)
                metadata.pop("managed_backend_success", None)
                if result.status is StageStatus.SUCCEEDED:
                    metadata[
                        "managed_backend_success"
                        if launch.backend_kind == "docker"
                        else "managed_successful_exit"
                    ] = evidence.qualified_success
                result = replace(result, executor_metadata=metadata)
            (yield from _external("bulk", workspace.persist_worker_result, result))
            result = cast(StageWorkerResult, workspace.worker_result())
            execution_journal.record_result(assignment.assignment_id, result.to_dict())
        report = (yield from _external("bulk", workspace.retain_outputs))
        workspace.append_event(
            f"{request.assignment_id}:result-output-durable",
            {"kind": "result_and_output_durable", "status": report.status.value},
        )
        if not completed_before_start:
            (yield from _steps(self._flush_workspace_events, session.session_id, workspace))
        authorization = (yield from _steps(self._fresh_transfer_authorization,
            session_id=session.session_id,
            assignment_id=request.assignment_id,
            expected_revision=authorization_revision,
        ))
        authorization_id = cast(str, authorization["authorization_id"])
        authorization_revision = cast(int, authorization["revision"])
        _, authorization_id, authorization_revision = (yield from _steps(self._authorized_transfer_call,
            session_id=session.session_id,
            assignment_id=request.assignment_id,
            authorization_id=authorization_id,
            authorization_revision=authorization_revision,
            operation=lambda current_id, current_revision: _steps(self.declare_outputs,
                session.session_id,
                request.assignment_id,
                fence=fence,
                authorization_id=current_id,
                authorization_revision=current_revision,
                report=report,
            ),
        ))
        for item in report.outputs:
            from loom.pipeline.stores.shared_artifacts import binding
            if binding(item.metadata) is not None:
                continue
            offset = 0
            while True:
                _raise_if_application_suspended(suspend_requested)
                data, final = (yield from _external("bulk", workspace.output_chunk, item.transfer_id, offset))
                response, authorization_id, authorization_revision = (
                    (yield from _steps(self._authorized_transfer_call,
                        session_id=session.session_id,
                        assignment_id=request.assignment_id,
                        authorization_id=authorization_id,
                        authorization_revision=authorization_revision,
                        operation=lambda current_id, current_revision: (
                            _steps(self.upload_output_chunk,
                                session.session_id,
                                request.assignment_id,
                                item.transfer_id,
                                offset=offset,
                                data=data,
                                final=final,
                                authorization_id=current_id,
                                authorization_revision=current_revision,
                            )
                        ),
                    ))
                )
                offset = cast(
                    int, cast(Mapping[str, PlainData], response)["received_bytes"]
                )
                (yield from _steps(self._maintain_resource_offer))
                if final:
                    break
        _raise_if_application_suspended(suspend_requested)
        yield from _steps(self.poll_assignment_control, session.session_id)
        (yield from _steps(self._assignment_call,
            session.session_id,
            request.assignment_id,
            lambda: _steps(self.commit_result,
                session.session_id, request.assignment_id, fence=fence
            ),
        ))
        if completed_before_start:
            (yield from _steps(self._flush_workspace_events, session.session_id, workspace))
        released_session = yield from _steps(
            self._release_completed_assignment, session, assignment, commands,
            providers, execution_journal, fence=fence,
        )
        self._next_resource_maintenance = 0
        self._cancelled_assignments.discard(request.assignment_id)
        self._received_cancellations.discard(request.assignment_id)
        self._joined_starts.discard(request.assignment_id)
        return freeze_plain_data(
            {
                "result": "assignment",
                "assignment_id": request.assignment_id,
                "state": "RELEASED",
                "session": released_session.value(),
            },
            path=result_path_label,
        )

    @_cooperative
    @_serialized("_mutation_gate")
    def _release_completed_assignment(
        self, session, assignment, commands, providers, execution_journal, *, fence
    ):
        next_revision = self._release_provider_claims(
            session,
            assignment,
            commands,
            providers,
            execution_journal,
        )
        released_session = cast(
            AgentSession,
            (yield from _steps(self._assignment_call,
                session.session_id,
                assignment.assignment_id,
                lambda: _steps(self.release_assignment,
                    session.session_id,
                    assignment.assignment_id,
                    fence=fence,
                    availability_revision=next_revision,
                ),
            )),
        )
        return released_session

    @_cooperative
    def _cancel_pregrant_if_requested(
        self,
        session: AgentSession,
        assignment_id: str,
        assignment: ManagedAssignment,
        commands: tuple[ClaimCommand, ...],
        providers: Mapping[str, AgentResourceProvider],
        execution_journal: SQLiteAgentJournal,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData] | None]:
        for _ in range(32):
            control = (yield from _steps(self._assignment_call,
                session.session_id,
                assignment_id,
                lambda: _steps(self.poll_assignment_control, session.session_id),
            ))
            if control is None:
                return None
            if control.assignment_id != assignment_id:
                continue
            if execution_journal.read_state(assignment_id) not in {
                AssignmentState.REQUEST_DURABLE, AssignmentState.PREPARED, AssignmentState.ACCEPTED,
            }:
                return None
            return (yield from _steps(self._decline_pregrant_assignment,
                session, assignment, commands, providers, execution_journal, cancelled=True))
        raise QueueConflictError("assignment control delivery exceeds its bound")

    @_cooperative
    @_serialized("_mutation_gate")
    def _decline_pregrant_assignment(
        self, session, assignment, commands, providers, execution_journal, *, cancelled=False
    ):
        assignment_id = assignment.assignment_id
        if cancelled:
            if execution_journal.read_state(assignment_id) is AssignmentState.REQUEST_DURABLE:
                execution_journal.decline_before_prepare(assignment_id)
            else:
                execution_journal.abort_pregrant(assignment_id, commands, providers)
        reason_code = execution_journal.read_decline_reason(assignment_id)
        revision = self._availability_revision(session, assignment_id, providers)
        execution_journal.release_declined(assignment_id, revision)
        released = yield from _steps(self._assignment_call, session.session_id, assignment_id,
            lambda: _steps(self.decline_assignment, session.session_id, assignment_id,
                          availability_revision=revision, reason_code=reason_code))
        return freeze_plain_data({
            "result": "assignment", "assignment_id": assignment_id,
            "state": "CANCELLED_BEFORE_GRANT" if cancelled else "DECLINED",
            **({} if cancelled else {"reason_code": reason_code}),
            "session": released.value(),
        }, path="remote pre-grant completion")

    def _release_provider_claims(
        self,
        session: AgentSession,
        assignment: ManagedAssignment,
        commands: tuple[ClaimCommand, ...],
        providers: Mapping[str, AgentResourceProvider],
        execution_journal: SQLiteAgentJournal,
    ) -> str:
        """Release the exact composite and persist fresh capacity before RPC."""

        local_state = execution_journal.acknowledge_terminal(assignment.assignment_id)
        if local_state is AssignmentState.RELEASED:
            # Re-observe the reconstructed providers, then replay only the
            # availability revision already committed by this old root.
            self._availability_revision(session, assignment.assignment_id, providers)
            retained_revision = execution_journal.read_availability_revision(
                assignment.assignment_id
            )
            if retained_revision is None:
                raise QueueConflictError(
                    "released remote availability evidence is unavailable"
                )
            return retained_revision
        if local_state is not AssignmentState.PROVIDERS_RELEASED:
            for command in commands:
                provider = providers.get(command.claim.resource_kind)
                if provider is None:
                    raise QueueConflictError(
                        "remote provider release owner is unavailable"
                    )
                released = provider.release(
                    ClaimCommand(
                        assignment,
                        f"{command.operation_id}:release",
                        command.claim,
                        command.provider_descriptor,
                    )
                )
                if released.outcome is not ClaimOutcome.RELEASED:
                    raise QueueConflictError("remote provider release is indeterminate")
            execution_journal.mark_providers_released(assignment.assignment_id)
        next_revision = self._availability_revision(
            session, assignment.assignment_id, providers
        )
        execution_journal.publish_availability(assignment.assignment_id, next_revision)
        return next_revision

    @staticmethod
    def _availability_revision(
        session: AgentSession,
        assignment_id: str,
        providers: Mapping[str, AgentResourceProvider],
    ) -> str:
        observations = {
            kind: provider.observe(
                ObserveRequest(
                    session.agent_id,
                    session.session_id,
                    f"{assignment_id}:released:{kind}",
                )
            )
            for kind, provider in providers.items()
        }
        return (
            "availability-"
            + hashlib.sha256(
                "\0".join(
                    observations[kind].availability_revision
                    for kind in sorted(observations)
                ).encode()
            ).hexdigest()
        )

    @_cooperative
    def _fresh_transfer_authorization(
        self,
        *,
        session_id: str,
        assignment_id: str,
        expected_revision: int,
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        """Renew until the authorization belongs to the reconciled epoch."""

        revision = expected_revision
        while True:
            operation_id = f"{assignment_id}:authorize:{revision + 1}"
            result = cast(
                Mapping[str, PlainData],
                (yield from _steps(self._assignment_call,
                    session_id,
                    assignment_id,
                    lambda: _steps(self.authorize_transfers,
                        session_id,
                        assignment_id,
                        expected_revision=revision,
                        operation_id=operation_id,
                    ),
                )),
            )
            returned_revision = result.get("revision")
            returned_epoch = result.get("coordinator_epoch")
            if (
                isinstance(returned_revision, bool)
                or not isinstance(returned_revision, int)
                or returned_revision != revision + 1
                or not isinstance(returned_epoch, str)
            ):
                raise QueueConflictError(
                    "remote transfer authorization evidence is invalid"
                )
            revision = returned_revision
            if (
                returned_epoch
                == self._require_journal().session(session_id).coordinator_epoch
            ):
                return result

    @_cooperative
    def _authorized_transfer_call(
        self,
        *,
        session_id: str,
        assignment_id: str,
        authorization_id: str,
        authorization_revision: int,
        operation: Callable[[str, int], Any],
    ) -> Generator[_Progress, Any, tuple[Any, str, int]]:
        """Run one transfer operation, renewing only a proven-stale grant."""

        current_id = authorization_id
        current_revision = authorization_revision
        for _ in range(_MAX_TRANSFER_AUTHORIZATION_RENEWALS + 1):
            try:
                result = (yield from _steps(self._assignment_call,
                    session_id,
                    assignment_id,
                    lambda: _steps(operation, current_id, current_revision),
                ))
                return result, current_id, current_revision
            except AgentTransferAuthorizationStaleError:
                renewed = (yield from _steps(self._fresh_transfer_authorization,
                    session_id=session_id,
                    assignment_id=assignment_id,
                    expected_revision=current_revision,
                ))
                current_id = cast(str, renewed["authorization_id"])
                current_revision = cast(int, renewed["revision"])
        raise QueueConflictError(
            "remote transfer authorization renewal exceeded its bound"
        )

    @_cooperative
    def _assignment_call(
        self,
        session_id: str,
        assignment_id: str,
        operation: Callable[[], Any],
    ) -> Generator[_Progress, Any, Any]:
        """Retry one exact assignment operation across coordinator restart."""

        deadline = monotonic() + _ASSIGNMENT_RECONCILIATION_SECONDS
        while True:
            try:
                return (yield from _steps(operation))
            except QueueConflictError as conflict:
                prior = self._require_journal().session(session_id)
                current = (yield from _steps(self.handshake))
                epoch = current.get("coordinator_epoch")
                if not isinstance(epoch, str) or epoch == prior.coordinator_epoch:
                    raise conflict
                self._epoch_reconciliation_pending = True
                (yield from _steps(self.reconcile,
                    session_id,
                    epoch,
                    idempotency_key=(f"{assignment_id}:reconcile:{epoch}"),
                ))
            except _IndeterminateAgentProtocolError:
                _raise_if_application_suspended(getattr(self, "_suspend_requested", None))
                if monotonic() >= deadline:
                    raise
                try:
                    current = (yield from _steps(self.handshake))
                    epoch = current.get("coordinator_epoch")
                    prior = self._require_journal().session(session_id)
                    if isinstance(epoch, str) and epoch != prior.coordinator_epoch:
                        self._epoch_reconciliation_pending = True
                        (yield from _steps(self.reconcile,
                            session_id,
                            epoch,
                            idempotency_key=(f"{assignment_id}:reconcile:{epoch}"),
                        ))
                except _IndeterminateAgentProtocolError:
                    pass
                (yield from _delay(0.05))

    def _runtime_owners(
        self, session: AgentSession
    ) -> tuple[dict[str, AgentResourceProvider], SQLiteAgentJournal]:
        profile = self._config.capacity_profile
        journal = self._execution_journal
        if journal is None:
            raise QueueServiceError("remote execution journal is required")
        if self._runtime_agent_id is None:
            self._runtime_agent_id = session.agent_id
            self._providers = self._provider_composition(session.agent_id, profile)
            self._runtime_provider_key = _agent_provider_composition_key(
                self._providers.values()
            )
            for command in journal.retained_claim_commands():
                provider = self._providers.get(command.claim.resource_kind)
                if provider is None:
                    raise QueueConflictError(
                        "retained remote claim has no resident provider"
                    )
                provider.restore_capacity_holding(command)
        elif self._runtime_agent_id != session.agent_id:
            raise QueueConflictError("remote runtime agent identity changed")
        elif self._runtime_provider_key != _agent_provider_composition_key(
            self._providers.values()
        ):
            raise QueueConflictError(
                "resident provider configuration changed while claims are retained"
            )
        if any(
            claim_kind not in self._providers
            for claim_kind in {
                atom.owner_resource_kind
                for atom in profile.capacity_atoms(session.agent_id)
            }
        ):
            raise QueueConflictError("resident provider composition changed")
        return self._providers, journal

    def _provider_composition(
        self, agent_id: str, capacity_profile: ResidentExecutionProfile
    ) -> dict[str, AgentResourceProvider]:
        if self._configured_provider_members is None:
            members = _configured_remote_provider_members(
                self._config, agent_id, capacity_profile
            )
            try:
                providers = _compose_agent_resource_providers(members)
            except Exception as exc:
                raise QueueConflictError(
                    "remote agent provider composition is invalid"
                ) from exc
            self._configured_provider_members = members
            self._configured_provider_agent_id = agent_id
            self._providers = providers
        elif self._configured_provider_agent_id != agent_id:
            raise QueueConflictError("remote agent provider identity changed")
        return dict(self._providers)

    def _offer_provider_snapshot(
        self,
        *,
        session_id: str,
        availability_revision: str,
        capacity_profile: ResidentExecutionProfile,
    ) -> tuple[
        tuple[AgentProviderDescriptor, ...],
        tuple[CapacityAtom, ...],
        tuple[str, ...],
        tuple[ResourceAvailabilityStatus, ...],
    ]:
        """Observe the configured factory once and project its safe wire facts."""

        session = self._require_journal().session(session_id)
        providers = self._provider_composition(session.agent_id, capacity_profile)
        atoms: list[CapacityAtom] = []
        live_claim_ids: set[str] = set()
        statuses: list[ResourceAvailabilityStatus] = []
        for kind, provider in sorted(providers.items()):
            observed = provider.observe(
                ObserveRequest(
                    session.agent_id,
                    session_id,
                    f"offer:{availability_revision}:observe:{kind}",
                )
            )
            atoms.extend(
                _wire_capacity_atom(atom, session.agent_id) for atom in observed.atoms
            )
            live_claim_ids.update(observed.live_claim_ids)
            prefix = f"{session.agent_id}:"
            statuses.extend(
                replace(
                    item,
                    local_capacity_key=item.local_capacity_key.removeprefix(prefix),
                )
                for item in observed.resource_status
            )
        members = self._configured_provider_members
        if members is None:
            raise QueueConflictError("remote agent provider composition is missing")
        return (
            tuple(
                sorted(
                    (
                        AgentProviderDescriptor(
                            provider.descriptor, provider.claim_contracts
                        )
                        for provider in members
                    ),
                    key=lambda item: item.descriptor.key,
                )
            ),
            tuple(sorted(atoms, key=lambda item: item.key)),
            tuple(sorted(live_claim_ids)),
            tuple(
                sorted(
                    statuses,
                    key=lambda item: (item.resource_kind, item.local_capacity_key),
                )
            ),
        )

    def _validate_offer_provider_capacity(
        self, offer: AgentOffer, agent_id: str
    ) -> None:
        observed: list[CapacityAtom] = []
        for kind, provider in sorted(self._providers.items()):
            result = provider.observe(
                ObserveRequest(
                    agent_id,
                    offer.session_id,
                    f"offer:{offer.availability_revision}:observe:{kind}",
                )
            )
            for atom in result.atoms:
                observed.append(_wire_capacity_atom(atom, agent_id))
        if tuple(sorted(observed, key=lambda item: item.key)) != offer.capacity_atoms:
            raise QueueConflictError(
                "offer capacity differs from configured provider observations"
            )

    def _profile_for_descriptor(
        self, descriptor: object
    ) -> ResidentExecutionProfile | None:
        active = self._profiles.get(getattr(descriptor, "profile_id", ""))
        if active is not None and active.descriptor == descriptor:
            return active
        return next(
            (
                profile
                for profile in self._retained_profiles.values()
                if profile.descriptor == descriptor
            ),
            None,
        )

    @_cooperative
    def _flush_workspace_events(
        self, session_id: str, workspace: _ResidentAssignmentWorkspace
    ) -> Generator[_Progress, Any, None]:
        for sequence, event_id, payload in workspace.pending_events():
            result = cast(
                Mapping[str, PlainData],
                (yield from _steps(self._assignment_call,
                    session_id,
                    workspace.assignment_id,
                    lambda: _steps(self.report_event,
                        session_id,
                        workspace.assignment_id,
                        sequence=sequence,
                        event_id=event_id,
                        payload=payload,
                    ),
                )),
            )
            acknowledged = result.get("acknowledged_sequence")
            if acknowledged != sequence:
                raise QueueConflictError("remote event acknowledgement has a gap")
            workspace.acknowledge_event(sequence)

    @_cooperative
    def retire_clean(
        self, session_id: str, *, idempotency_key: str
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        if self._slurm_agent is not None and self._slurm_agent.has_retained_work():
            raise QueueConflictError("agent has retained SLURM work")
        return (yield from _steps(
            _retire_agent_session, self._require_journal(), self._call,
            session_id, idempotency_key=idempotency_key,
        ))

    def _require_journal(self) -> "_RemoteAgentJournal":
        if self._journal is None:
            raise QueueServiceError("remote agent durable journal is required")
        return self._journal

    @_cooperative
    def call_application(
        self, role: str, operation: str, value: Mapping[str, PlainData]
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        """Call the authenticated application view selected by its certificate."""
        if role not in {"client", "operator", "slurm_bootstrap"}:
            raise QueueServiceError("authenticated application role is invalid")
        return (yield from _steps(self._call, operation, value, role=role))

    @_cooperative
    def _call(
        self, operation: str, value: Mapping[str, PlainData], *, role: str = "agent"
    ) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
        while self._service_progress and self._epoch_reconciliation_pending and operation in {
            "accept", "start_permit", "started", "event", "authorize", "input",
            "output_manifest", "output", "result", "assignment_control_ack",
        }:
            _raise_if_application_suspended(self._suspend_requested)
            yield from _delay(0.01)
        body = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if (role, operation) in _FAILURE_REPORT_OPERATIONS:
            _decode(body, failure_report=True)
        connection, self._connection = self._connection, None
        while True:
            try:
                reply = yield from _external(
                    "poll" if operation == "poll" else "bulk" if operation in {"input", "output"} else "control",
                    _exchange_agent_request, self._config, operation, body, role, connection,
                    not self._service_progress,
                )
                break
            except _IndeterminateAgentProtocolError:
                if not self._service_progress:
                    raise
                connection = None
                _raise_if_application_suspended(self._suspend_requested)
                yield from _delay(0.05)
        if self._connection is None and not self._closed and not self._service_progress:
            self._connection = reply.connection
        else:
            reply.connection.close()
        return reply.value


def _has_retained_agent_work(
    journal: _RemoteAgentJournal | None,
    execution: SQLiteAgentJournal | None,
    slurm: AgentSlurmJobs | None,
) -> bool:
    """One settlement predicate for execution and control-only native owners."""
    return (
        bool(slurm is not None and slurm.has_retained_work())
        or bool(execution is not None and execution.retained_claim_commands())
        or bool(journal is not None and journal.has_unresolved_assignment_references())
    )


@_cooperative
def _reconcile_retirement_poll(
    journal: _RemoteAgentJournal,
    exchange: Callable[[str, Mapping[str, PlainData]], Mapping[str, PlainData]],
    session_id: str,
    *,
    wait_timeout_ms: int,
) -> Generator[_Progress, Any, None]:
    """Read the stopped service's exact poll outcome without requesting work.

    A committed delivery is retained by the ordinary journal transition; the
    caller's empty-owner check must then refuse retirement. Unknown outcomes
    preserve the request and cannot authorize a retirement proof.
    """
    pending = journal.recovery_poll(wait_timeout_ms)
    if pending is None:
        return
    _, request = pending
    if request["session_id"] != session_id:
        raise QueueConflictError("retirement poll targets another agent session")
    session = journal.session(session_id)
    try:
        outcome = yield from _steps(
            exchange,
            "recover_poll",
            {**request, "coordinator_epoch": session.coordinator_epoch},
        )
    except QueueError as exc:
        raise QueueConflictError(
            "retirement cannot confirm unanswered poll; preserve agent state "
            "and retry with an available compatible coordinator"
        ) from exc
    sequence = cast(int, request["sequence"])
    if outcome.get("state") == "absent":
        journal.discard_absent_poll(
            session_id,
            sequence,
            predecessor_sequence=outcome.get("predecessor_sequence"),
            predecessor_delivery=outcome.get("predecessor_delivery"),
        )
    elif outcome.get("state") == "fenced":
        journal.fence_poll(session_id, sequence, confirmed=True)
    elif outcome.get("state") == "committed":
        journal.complete_poll(
            session_id,
            sequence,
            {key: value for key, value in outcome.items() if key != "state"},
            recovered=True,
        )
    else:
        raise QueueServiceError("retained poll recovery result is invalid")


@_cooperative
def _retire_agent_session(
    journal: _RemoteAgentJournal,
    exchange: Callable[[str, Mapping[str, PlainData]], Mapping[str, PlainData]],
    session_id: str,
    *,
    idempotency_key: str,
    role_receipt: Mapping[str, PlainData] | None = None,
) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
    """Fence, persist and replay the same native retirement protocol everywhere."""
    proof = journal.fence_and_prove_empty(session_id)
    request: dict[str, PlainData] = {
        "proof": proof.value(), "idempotency_key": idempotency_key,
    }
    journal._persist_mutation("retire", idempotency_key, request)
    result = yield from _steps(exchange, "retire", request)
    journal.complete_mutation("retire", idempotency_key, result)
    journal.persist_retired(session_id, idempotency_key, role_receipt=role_receipt)
    return result


def _start_once_steps(journal, assignment_id, execution_id, launcher, *, start_failure):
    existing = journal._prepare_process_start(assignment_id, execution_id)
    if existing is not None:
        return existing
    try:
        process_id = yield from launcher()
    except ManagedProcessStartError as error:
        journal._set_start_failed(assignment_id, execution_id, start_failure(error))
        raise
    except Exception:
        journal._set_state(assignment_id, AssignmentState.START_UNKNOWN)
        raise
    return journal._complete_process_start(assignment_id, execution_id, process_id, start_failure)


@dataclass(frozen=True)
class _AgentHttpReply:
    connection: http.client.HTTPSConnection
    value: Mapping[str, PlainData]


def _exchange_agent_request(
    config: AgentTlsClientConfig, operation: str, body: bytes, role: str,
    connection: http.client.HTTPSConnection | None,
    keep_alive: bool,
) -> _AgentHttpReply:
    """Exchange exact prepared bytes using one exclusively owned connection."""
    connection = connection or https_connection(
        config.url, config.server_ca_path, config.certificate_path,
        config.private_key_path, timeout=_HTTP_TIMEOUT_SECONDS,
    )
    try:
        return _AgentHttpReply(connection, _read_agent_reply(connection, operation, body, role))
    except BaseException:
        connection.close()
        raise
    finally:
        if not keep_alive:
            connection.close()


def _read_agent_reply(
    connection: http.client.HTTPSConnection, operation: str, body: bytes, role: str
) -> Mapping[str, PlainData]:
    try:
        connection.request(
            "POST",
            f"/v1/{role}/{operation}",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read(_MAX_BODY_BYTES + 1)
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise _IndeterminateAgentProtocolError(
            "agent protocol outcome is indeterminate"
        ) from exc
    if len(raw) > _MAX_BODY_BYTES:
        raise _IndeterminateAgentProtocolError(
            "agent protocol outcome is indeterminate"
        )
    try:
        payload = _decode(raw)
    except QueueError as exc:
        raise _IndeterminateAgentProtocolError(
            "agent protocol outcome is indeterminate"
        ) from exc
    if response.status == 409:
        if payload.get("error") == "agent_poll_active":
            raise AgentPollActiveError("work poll is already active")
        if payload.get("error") == "agent_poll_fenced":
            raise AgentPollFencedError("work poll was fenced and is not reusable")
        if payload.get("error") == "agent_poll_stale":
            raise AgentStalePollError("work poll sequence is stale")
        if payload.get("error") == "agent_poll_sequence_gap":
            raise AgentPollSequenceGapError("work poll sequence has a gap")
        if payload.get("error") == "agent_transfer_authorization_stale":
            raise AgentTransferAuthorizationStaleError(
                "remote transfer authorization is stale"
            )
        raise QueueConflictError("agent protocol conflict")
    if response.status >= 500:
        raise _IndeterminateAgentProtocolError(
            "agent protocol outcome is indeterminate"
        )
    if response.status != 200 or payload.get("ok") is not True:
        code = payload.get("error")
        raise QueueServiceError(
            str(code) if isinstance(code, str) else "agent protocol request failed"
        )
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise _IndeterminateAgentProtocolError(
            "agent protocol outcome is indeterminate"
        )
    return freeze_plain_data(result, path="agent HTTP response")


class _MutualTlsHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        context: ssl.SSLContext,
        daemon: LocalDaemon,
        credential_fingerprints: Mapping[str, str],
        inspect_run: Callable[[str], Mapping[str, PlainData]] | None,
    ) -> None:
        self._context = context
        self.daemon_owner = daemon
        self.credential_fingerprints = credential_fingerprints
        self.inspect_run = inspect_run
        self.client_slots = BoundedSemaphore(8)
        self.client_wait_slots = BoundedSemaphore(6)
        super().__init__(address, _Handler)

    def get_request(self) -> tuple[ssl.SSLSocket, tuple[str, int]]:
        connection, address = super().get_request()
        try:
            connection.settimeout(_HTTP_TIMEOUT_SECONDS)
            authenticated = self._context.wrap_socket(connection, server_side=True)
            # The accept deadline bounds TLS negotiation, not the established
            # worker protocol's idle keepalive interval. Native control I/O has
            # its own cumulative client deadline.
            authenticated.settimeout(None)
            return authenticated, address
        except Exception:
            connection.close()
            raise

    def replace_tls(
        self,
        context: ssl.SSLContext,
        credential_fingerprints: Mapping[str, str],
    ) -> None:
        """Install a fully prepared context for subsequent requests."""

        self._context = context
        self.credential_fingerprints = credential_fingerprints


def _agent_server_context(config: AgentTlsServerConfig) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(config.certificate_path, config.private_key_path)
    context.load_verify_locations(cafile=config.client_ca_path)
    return context


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def _daemon_server(self) -> _MutualTlsHttpServer:
        return cast(_MutualTlsHttpServer, self.server)

    def log_message(self, format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        query_path = self.path.startswith("/v1/query/")
        query_credential = False
        payload: dict[str, object] = {}
        new_client = (
            self.path.startswith(("/v1/client/", "/v1/operator/"))
            and self.headers.get("X-Loom-Client") == CONTROL_CAPABILITY
        )
        operation = self.path.rsplit("/", 1)[-1] or "unknown"
        authenticated = dispatched = False
        client_acquired = wait_acquired = False
        try:
            certificate = cast(ssl.SSLSocket, self.connection).getpeercert(
                binary_form=True
            )
            if certificate is None:
                raise QueueServiceError("agent TLS peer is unavailable")
            fingerprint = hashlib.sha256(certificate).hexdigest()
            credential = self._daemon_server.credential_fingerprints.get(fingerprint)
            if credential is None:
                raise QueueServiceError("agent TLS credential is not accepted")
            execution = self._daemon_server.daemon_owner._execution
            slurm_profile = (
                None
                if execution is None
                else execution._slurm_profile_for_credential(credential)
            )
            if slurm_profile is None:
                principal_id, mapped_role = ScopedAuthorizer(
                    self._daemon_server.daemon_owner._agent_policy
                ).transport_principal(credential)
            else:
                principal_id = slurm_profile.bootstrap_principal_id
                mapped_role = LocalDaemonRole.SLURM_BOOTSTRAP.value
            query_credential = mapped_role == LocalDaemonRole.QUERY.value
            segments = self.path.split("/")
            if len(segments) != 4 or segments[0] or segments[1] != "v1":
                raise QueueServiceError("agent protocol operation is unsupported")
            role_name, operation = segments[2:]
            if role_name != mapped_role:
                raise QueueServiceError("agent TLS credential is not authorized")
            authenticated = True
            if role_name == "client":
                if operation in WAIT_OPERATIONS:
                    wait_acquired = self._daemon_server.client_wait_slots.acquire(
                        blocking=False
                    )
                    if not wait_acquired:
                        raise control_error(
                            "capacity_exhausted",
                            operation,
                            payload,
                            boundary="coordinator",
                        )
                client_acquired = self._daemon_server.client_slots.acquire(
                    blocking=False
                )
                if not client_acquired:
                    raise control_error(
                        "capacity_exhausted", operation, payload, boundary="coordinator"
                    )
            if self.headers.get("Content-Type") != "application/json":
                raise QueueServiceError("agent protocol content type is invalid")
            lengths = self.headers.get_all("Content-Length", [])
            length = lengths[0] if len(lengths) == 1 else None
            if (
                self.headers.get("Transfer-Encoding") is not None
                or length is None
                or not length.isdecimal()
                or int(length) > _MAX_BODY_BYTES
            ):
                raise QueueServiceError("agent protocol body is invalid")
            raw = self.rfile.read(int(length))
            if role_name == "client":
                try:
                    payload = dict(decode_wire(raw))
                except (ValueError, TypeError, RecursionError) as exc:
                    raise control_error(
                        "invalid_request", operation, {}, boundary="client_protocol"
                    ) from exc
            elif role_name == "query" and operation in {"describe_artifact", "read_artifact_chunk", "read_artifact", "trace_lineage", "select_outputs", "list_output_commits"}:
                try:
                    payload = dict(decode_wire(raw))
                except (ValueError, TypeError, RecursionError) as exc:
                    raise _RunInspectionHttpError("invalid_request", 400) from exc
            else:
                payload = dict(
                    _decode(raw, failure_report=True)
                    if (role_name, operation) in _FAILURE_REPORT_OPERATIONS
                    else _decode(raw)
                )
            principal = LocalDaemonPrincipal(
                principal_id, LocalDaemonRole(mapped_role), credential
            )
            if role_name == "agent":
                if operation not in {
                    "slurm_work",
                    "service_lifetime",
                    "handshake",
                    "register",
                    "reconcile",
                    "offer",
                    "renew",
                    "poll",
                    "recover_poll",
                    "authorize",
                    "input",
                    "accept",
                    "decline",
                    "started",
                    "event",
                    "output_manifest",
                    "output",
                    "result",
                    "release",
                    "recovery_release_ready",
                    "control",
                    "control_ack",
                    "assignment_control",
                    "assignment_control_ack",
                    "start_permit",
                    "retire",
                }:
                    raise QueueServiceError("agent protocol operation is unsupported")
                result = _dispatch(
                    self._daemon_server.daemon_owner.agent_view(principal),
                    operation,
                    payload,
                )
            else:
                dispatched = True
                result = _dispatch_application(
                    self._daemon_server.daemon_owner,
                    principal,
                    role_name,
                    operation,
                    payload,
                    inspect_run=self._daemon_server.inspect_run,
                    daemon_control=new_client,
                )
            if role_name == LocalDaemonRole.QUERY.value:
                self._reply_query_result(result)
            else:
                self._reply(200, {"ok": True, "result": result})
        except _RunInspectionHttpError as exc:
            self._reply_query_failure(exc.code, exc.status)
        except AgentPollActiveError:
            self._reply(409, {"ok": False, "error": "agent_poll_active"})
        except AgentPollFencedError:
            self._reply(409, {"ok": False, "error": "agent_poll_fenced"})
        except AgentStalePollError:
            self._reply(409, {"ok": False, "error": "agent_poll_stale"})
        except AgentPollSequenceGapError:
            self._reply(409, {"ok": False, "error": "agent_poll_sequence_gap"})
        except AgentTransferAuthorizationStaleError:
            self._reply(
                409,
                {"ok": False, "error": "agent_transfer_authorization_stale"},
            )
        except CoordinatorClientError as exc:
            if new_client:
                status = {
                    "unauthorized": 403,
                    "conflict": 409,
                    "capacity_exhausted": 429,
                    "not_found": 404,
                    "unavailable": 503,
                    "internal_error": 500,
                }.get(exc.code, 400)
                self._reply(status, error_envelope(exc))
            else:
                self._reply(
                    409 if exc.code == "conflict" else 403,
                    {"ok": False, "error": "agent_protocol_rejected"},
                )
        except QueueConflictError:
            self._reply(409, {"ok": False, "error": "agent_protocol_conflict"})
        except QueueError:
            if new_client:
                code = "invalid_request" if authenticated else "unauthorized"
                error = control_error(
                    code,
                    operation,
                    payload,
                    boundary="client_protocol" if authenticated else "authentication",
                    dispatched=dispatched,
                )
                self._reply(400 if authenticated else 403, error_envelope(error))
            elif query_path or query_credential:
                code = "invalid_request" if query_credential else "unauthorized"
                self._reply_query_failure(code, 400 if query_credential else 403)
            else:
                self._reply(403, {"ok": False, "error": "agent_protocol_rejected"})
        except Exception:
            if new_client:
                self._reply(
                    500,
                    error_envelope(
                        control_error(
                            "internal_error",
                            operation,
                            payload,
                            boundary="coordinator",
                            dispatched=dispatched,
                        )
                    ),
                )
            elif query_path:
                self._reply_query_failure("unavailable", 503)
            else:
                self._reply(500, {"ok": False, "error": "agent_protocol_indeterminate"})
        finally:
            if client_acquired:
                self._daemon_server.client_slots.release()
            if wait_acquired:
                self._daemon_server.client_wait_slots.release()

    def _reply_query_result(self, result: Mapping[str, PlainData]) -> None:
        status = _run_inspection_http_status(result)
        payload = {"ok": True, "result": result}
        encoded = json.dumps(
            thaw_plain_data(payload, path="run inspection HTTP response"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > _MAX_QUERY_RESPONSE_BYTES:
            self._reply_query_failure("unavailable", 503)
            return
        self._reply(status, payload)

    def _reply_query_failure(self, code: str, status: int) -> None:
        self._reply(
            status,
            {"ok": True, "result": {"schema_version": 1, "code": code}},
        )

    def _reply(self, status: int, payload: Mapping[str, object]) -> None:
        body = json.dumps(
            thaw_plain_data(payload, path="agent HTTP response"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if status != 200:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)


def _dispatch(
    view: Any, operation: str, value: Mapping[str, object]
) -> Mapping[str, PlainData]:
    if operation == "slurm_work":
        _exact(value, {"session_id", "coordinator_epoch", "evidence", "cursor"})
        evidence = value["evidence"]
        if evidence is not None and not isinstance(evidence, Mapping):
            raise QueueServiceError("SLURM evidence is invalid")
        cursor = value["cursor"]
        if cursor is not None and not isinstance(cursor, str):
            raise QueueServiceError("SLURM task cursor is invalid")
        return view.slurm_work(
            _string(value, "session_id"),
            _string(value, "coordinator_epoch"),
            evidence,
            cursor,
        )
    if operation == "handshake":
        _exact(value, set())
        return view.handshake()
    if operation == "service_lifetime":
        _exact(value, {"session_id", "coordinator_epoch", "generation", "action"})
        return view.service_lifetime(
            _string(value, "session_id"),
            _string(value, "coordinator_epoch"),
            _string(value, "generation"),
            _string(value, "action"),
        )
    if operation == "register":
        return view.register(_registration(value)).value()
    if operation == "reconcile":
        _exact(value, {"expected", "coordinator_epoch", "idempotency_key"})
        expected = value["expected"]
        if not isinstance(expected, Mapping):
            raise QueueServiceError("agent reconciliation evidence is invalid")
        return view.reconcile(
            _session_from_value(cast(Mapping[str, PlainData], expected)),
            _string(value, "coordinator_epoch"),
            idempotency_key=_string(value, "idempotency_key"),
        ).value()
    if operation == "offer":
        value = {"expected_availability_revision": None, **value}
        _exact(value, {"offer", "idempotency_key", "expected_availability_revision"})
        expected = value["expected_availability_revision"]
        if expected is not None and not isinstance(expected, str):
            raise QueueServiceError("offer expected availability revision is invalid")
        offer = value["offer"]
        if not isinstance(offer, Mapping):
            raise QueueServiceError("agent offer is invalid")
        return view.publish_offer(
            _offer(offer),
            idempotency_key=_string(value, "idempotency_key"),
            expected_availability_revision=expected,
        )
    if operation == "renew":
        _exact(value, {"renewal"})
        renewal = value["renewal"]
        if not isinstance(renewal, Mapping):
            raise QueueServiceError("agent offer renewal is invalid")
        return view.renew_offer(AgentOfferRenewal.from_value(renewal))
    if operation == "recover_poll":
        _exact(
            value,
            {
                "session_id",
                "availability_revision",
                "sequence",
                "wait_timeout_ms",
                "coordinator_epoch",
            },
        )
        return view.recover_poll(
            _string(value, "session_id"),
            _string(value, "availability_revision"),
            sequence=_integer(value, "sequence"),
            wait_timeout_ms=_integer(value, "wait_timeout_ms"),
            coordinator_epoch=_string(value, "coordinator_epoch"),
        )
    if operation == "poll":
        _exact(
            value,
            {"session_id", "availability_revision", "sequence", "wait_timeout_ms"},
        )
        return view.wait_for_work(
            _string(value, "session_id"),
            _string(value, "availability_revision"),
            sequence=_integer(value, "sequence"),
            wait_timeout_ms=_integer(value, "wait_timeout_ms"),
        )
    if operation == "authorize":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "expected_revision",
                "operation_id",
            },
        )
        return view.authorize_transfers(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            expected_revision=_integer(value, "expected_revision"),
            operation_id=_string(value, "operation_id"),
        )
    if operation == "input":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "transfer_id",
                "offset",
                "authorization_id",
                "authorization_revision",
            },
        )
        return view.read_input_chunk(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            _string(value, "transfer_id"),
            offset=_integer(value, "offset"),
            authorization_id=_string(value, "authorization_id"),
            authorization_revision=_integer(value, "authorization_revision"),
        )
    if operation == "accept":
        _exact(value, {"session_id", "assignment_id", "request_digest"})
        return view.accept_assignment(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            request_digest=_string(value, "request_digest"),
        )
    if operation == "decline":
        value = {"reason_code": None, **value}
        _exact(
            value,
            {"session_id", "assignment_id", "availability_revision", "reason_code"},
        )
        return view.decline_assignment(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            availability_revision=_string(value, "availability_revision"),
            reason_code=cast(str | None, value["reason_code"]),
        ).value()
    if operation == "started":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "fence",
                "process_execution_id",
            },
        )
        return view.confirm_started(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            fence=_string(value, "fence"),
            process_execution_id=_string(value, "process_execution_id"),
        )
    if operation == "event":
        _exact(
            value,
            {"session_id", "assignment_id", "sequence", "event_id", "payload"},
        )
        payload = value["payload"]
        if not isinstance(payload, Mapping):
            raise QueueServiceError("remote event payload is invalid")
        return view.report_event(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            sequence=_integer(value, "sequence"),
            event_id=_string(value, "event_id"),
            payload=freeze_plain_data(payload, path="remote event"),
        )
    if operation == "output_manifest":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "fence",
                "authorization_id",
                "authorization_revision",
                "report",
            },
        )
        return view.declare_outputs(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            fence=_string(value, "fence"),
            authorization_id=_string(value, "authorization_id"),
            authorization_revision=_integer(value, "authorization_revision"),
            report=_RemoteExecutionReport.from_dict(value["report"]),
        )
    if operation == "output":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "transfer_id",
                "offset",
                "data",
                "final",
                "authorization_id",
                "authorization_revision",
            },
        )
        final = value["final"]
        if not isinstance(final, bool):
            raise QueueServiceError("remote output final flag is invalid")
        return view.upload_output_chunk(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            _string(value, "transfer_id"),
            offset=_integer(value, "offset"),
            data=_decode_chunk(value["data"]),
            final=final,
            authorization_id=_string(value, "authorization_id"),
            authorization_revision=_integer(value, "authorization_revision"),
        )
    if operation == "result":
        _exact(value, {"session_id", "assignment_id", "fence"})
        return view.commit_result(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            fence=_string(value, "fence"),
        )
    if operation == "recovery_release_ready":
        _exact(value, {"session_id", "assignment_id", "fence"})
        return view.recovery_release_ready(
            _string(value, "session_id"), _string(value, "assignment_id"),
            fence=_string(value, "fence"),
        )
    if operation == "release":
        _exact(
            value,
            {
                "session_id",
                "assignment_id",
                "fence",
                "availability_revision",
                "provider_release_proof",
            },
        )
        raw_proof = value["provider_release_proof"]
        if not isinstance(raw_proof, Mapping):
            raise QueueServiceError("agent provider release proof is invalid")
        return view.release_assignment(
            _string(value, "session_id"),
            _string(value, "assignment_id"),
            fence=_string(value, "fence"),
            availability_revision=_string(value, "availability_revision"),
            provider_release_proof=_provider_release_proof(raw_proof),
        ).value()
    if operation == "control":
        _exact(value, {"session_id"})
        control = view.next_control(_string(value, "session_id"))
        return {"control": None if control is None else control.value()}
    if operation == "control_ack":
        _exact(value, {"session_id", "effect"})
        effect = value["effect"]
        if not isinstance(effect, Mapping):
            raise QueueServiceError("agent control effect is invalid")
        return view.acknowledge_control(
            _string(value, "session_id"), AgentControlEffect.from_value(effect)
        )
    if operation == "assignment_control":
        _exact(value, {"session_id"})
        control = view.next_assignment_control(_string(value, "session_id"))
        return {"control": None if control is None else control.value()}
    if operation == "assignment_control_ack":
        _exact(value, {"session_id", "operation_id", "code", "evidence"})
        evidence = value["evidence"]
        if evidence is not None and not isinstance(evidence, Mapping):
            raise QueueServiceError("assignment control evidence is invalid")
        return view.acknowledge_assignment_control(
            _string(value, "session_id"),
            _string(value, "operation_id"),
            code=_string(value, "code"),
            evidence=evidence,
        )
    if operation == "start_permit":
        _exact(value, {"session_id", "assignment_id", "fence"})
        return {
            "permitted": view.start_permit(
                _string(value, "session_id"),
                _string(value, "assignment_id"),
                fence=_string(value, "fence"),
            )
        }
    _exact(value, {"proof", "idempotency_key"})
    proof = value["proof"]
    if not isinstance(proof, Mapping):
        raise QueueServiceError("agent retirement proof is invalid")
    return view.retire_clean(
        _retirement_proof(proof),
        idempotency_key=_string(value, "idempotency_key"),
    )


def _dispatch_application(
    daemon: LocalDaemon,
    principal: LocalDaemonPrincipal,
    role: str,
    operation: str,
    value: Mapping[str, object],
    *,
    inspect_run: Callable[[str], Mapping[str, PlainData]] | None = None,
    daemon_control: bool = False,
) -> Mapping[str, PlainData]:
    if role == "operator" and daemon_control:
        from ._coordinator_control import OPERATOR_OPERATIONS
        if operation not in OPERATOR_OPERATIONS:
            raise control_error("unauthorized", operation, value, boundary="authentication")
    if role == "client" or (role == "operator" and daemon_control):
        result = dict(
            dispatch_control(
                daemon,
                principal,
                operation,
                value,
                transport="https",
                wait_slice=5.0,
                inspect_run=inspect_run,
                legacy=not daemon_control,
            )
        )
        if operation == "handshake":
            result["role"] = role
            result["capabilities"] = [
                "authenticated-application-v1",
                *cast(list[PlainData], result["capabilities"]),
            ]
        return result
    if operation == "handshake":
        _exact(value, set())
        if role == LocalDaemonRole.SLURM_BOOTSTRAP.value:
            return daemon.slurm_bootstrap_view(principal).handshake()
        daemon._require_view_role(principal, LocalDaemonRole(role))
        capabilities: list[PlainData] = ["authenticated-application-v1"]
        if role == LocalDaemonRole.QUERY.value and inspect_run is not None:
            capabilities.append("run-inspection-v1")
        if role == LocalDaemonRole.QUERY.value:
            capabilities.append("run-context-v1")
            capabilities.append("run-query-v1")
            capabilities.append("output-query-v1")
            capabilities.append("lineage-query-v1")
            capabilities.append("artifact-read-v1")
        result: dict[str, PlainData] = {
            "protocol_version": "1",
            "capabilities": capabilities,
            "coordinator_id": daemon._require_started(),
            "coordinator_epoch": daemon._epoch or "",
        }
        result["role"] = role
        return freeze_plain_data(
            result,
            path="authenticated application handshake",
        )
    if role == LocalDaemonRole.QUERY.value:
        from ._run_queries import QUERY_OPERATIONS, query_operation, validate_query_request
        from ._output_selection import OUTPUT_OPERATIONS, output_operation, validate_output_request
        from ._artifact_access import ARTIFACT_OPERATIONS, artifact_operation, validate_artifact_request

        if operation in ARTIFACT_OPERATIONS:
            daemon._require_view_role(principal, LocalDaemonRole.QUERY)
            try:
                return artifact_operation(daemon, operation, validate_artifact_request(operation, value))
            except (ValueError, TypeError):
                return {"schema_version": 1, "code": "invalid_request"}

        if operation == "trace_lineage":
            from ._lineage import lineage_operation, validate_lineage_request
            from loom.runs.query import InvalidCursorError
            daemon._require_view_role(principal, LocalDaemonRole.QUERY)
            try:
                return lineage_operation(daemon, validate_lineage_request(value)["query"]).to_dict()
            except InvalidCursorError:
                return {"schema_version": 1, "code": "invalid_cursor"}
            except (ValueError, TypeError):
                return {"schema_version": 1, "code": "invalid_request"}

        if operation in OUTPUT_OPERATIONS:
            daemon._require_view_role(principal, LocalDaemonRole.QUERY)
            from loom.runs.query import InvalidCursorError
            try:
                return output_operation(daemon, operation, validate_output_request(operation, value)).to_dict()
            except InvalidCursorError:
                return {"schema_version": 1, "code": "invalid_cursor"}
            except (ValueError, TypeError):
                return {"schema_version": 1, "code": "invalid_request"}

        if operation in QUERY_OPERATIONS:
            daemon._require_view_role(principal, LocalDaemonRole.QUERY)
            from loom.runs.query import InvalidCursorError
            try:
                query_result = query_operation(daemon, operation, validate_query_request(operation, value))
                return query_result.to_dict() if hasattr(query_result, "to_dict") else query_result
            except InvalidCursorError:
                return {"schema_version": 1, "code": "invalid_cursor"}
            except (ValueError, TypeError):
                return {"schema_version": 1, "code": "invalid_request"}
        if operation not in {"inspect_run", "get_run_context", "list_run_notes"} or (operation == "inspect_run" and inspect_run is None):
            raise _RunInspectionHttpError("invalid_request", 400)
        try:
            _exact(value, {"run_uri", "limit", "cursor"} if operation == "list_run_notes" else {"run_uri"})
            run_uri = _string(value, "run_uri")
        except QueueError as exc:
            raise _RunInspectionHttpError("invalid_request", 400) from exc
        try:
            run_uri_bytes = run_uri.encode("utf-8")
        except UnicodeEncodeError:
            return {"schema_version": 1, "code": "invalid_request"}
        if len(run_uri_bytes) > 4 * 1024:
            return {"schema_version": 1, "code": "invalid_request"}
        try:
            run_uri = validate_run_uri(run_uri)
        except (InvalidRunURIError, OSError, ValueError):
            return {"schema_version": 1, "code": "invalid_request"}
        try:
            daemon._require_view_role(principal, LocalDaemonRole.QUERY)
        except QueueError as exc:
            raise _RunInspectionHttpError("unauthorized", 403) from exc
        try:
            if operation == "list_run_notes":
                from ._run_context import annotation_operation
                from ._coordinator_control import validate_request

                validated = validate_request(operation, value)
                page = annotation_operation(daemon, operation, validated, principal.subject)
                return cast(Any, page).to_dict()
            if operation == "get_run_context":
                from ._run_context import get_run_context

                return get_run_context(daemon, run_uri, inspect_run).to_dict()
            daemon.admission_for_run_uri(run_uri)
        except (AdmissionNotFoundError, FileNotFoundError, LookupError):
            return {"schema_version": 1, "code": "not_found"}
        except Exception:
            return {"schema_version": 1, "code": "unavailable"}
        try:
            assert inspect_run is not None
            return inspect_run(run_uri)
        except Exception:
            return {"schema_version": 1, "code": "unavailable"}
    elif role == "operator":
        view = daemon.operator_view(principal)
        if operation == "status":
            _exact(value, set())
            return view.status().to_dict()
        if operation == "reconcile":
            _exact(value, set())
            return {
                "admissions": [
                    admission.to_dict() for admission in view.reconcile_once()
                ]
            }
        if operation == "agent_control":
            _exact(value, {"control"})
            control = value["control"]
            if not isinstance(control, Mapping):
                raise QueueServiceError("agent control request is invalid")
            return view.control_agent(AgentControl.from_value(control))
        if operation == "scheduling_reload":
            _exact(value, {"request"})
            request = value["request"]
            if not isinstance(request, Mapping):
                raise QueueServiceError("scheduling reload request is invalid")
            return view.reload_scheduling(
                CoordinatorSchedulingReload.from_dict(request)
            )
        if operation == "recover_unknown":
            _exact(value, {"request"})
            request = value["request"]
            if not isinstance(request, Mapping):
                raise QueueServiceError("recovery request is invalid")
            return view.recover_unknown(RecoverUnknownAssignment.from_dict(request))
        if operation == "recover_time":
            _exact(value, {"request"})
            request = value["request"]
            if not isinstance(request, Mapping):
                raise QueueServiceError("time recovery request is invalid")
            return view.recover_time(TimeRecoveryRequest.from_dict(request)).to_dict()
        if operation == "replace_agent_session":
            _exact(value, {"request"})
            request = value["request"]
            if not isinstance(request, Mapping):
                raise QueueServiceError("session replacement request is invalid")
            return view.replace_agent_session(
                SessionReplacementRequest.from_dict(request)
            )
    elif role == LocalDaemonRole.SLURM_BOOTSTRAP.value:
        view = daemon.slurm_bootstrap_view(principal)
        if operation == "register":
            _exact(
                value,
                {
                    "operation_id",
                    "request_digest",
                    "job_id",
                    "cluster",
                    "incarnation",
                    "capability",
                },
            )
            cluster = value["cluster"]
            if cluster is not None and not isinstance(cluster, str):
                raise QueueServiceError("SLURM bootstrap cluster is invalid")
            return view.register(
                operation_id=_string(value, "operation_id"),
                request_digest=_string(value, "request_digest"),
                job_id=_string(value, "job_id"),
                cluster=cast(str | None, cluster),
                incarnation=_string(value, "incarnation"),
                capability=_string(value, "capability"),
            )
        if operation == "input":
            _exact(
                value,
                {"assignment_id", "incarnation", "transfer_id", "offset"},
            )
            data, final = view.input_chunk(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
                _string(value, "transfer_id"),
                offset=_integer(value, "offset"),
            )
            return {"data": _encode_chunk(data), "final": final}
        if operation == "inputs_ready":
            _exact(value, {"assignment_id", "incarnation"})
            ready = view.inputs_ready(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
            )
            return {"state": "input_ready" if ready else "awaiting_submission_ack"}
        if operation == "grant":
            _exact(value, {"assignment_id", "incarnation"})
            return {
                "fence": view.grant(
                    _string(value, "assignment_id"),
                    _string(value, "incarnation"),
                )
            }
        if operation == "start":
            _exact(value, {"assignment_id", "incarnation", "fence"})
            return {
                "permitted": view.start_permit(
                    _string(value, "assignment_id"),
                    _string(value, "incarnation"),
                    _string(value, "fence"),
                )
            }
        if operation == "started":
            _exact(
                value,
                {
                    "assignment_id",
                    "incarnation",
                    "fence",
                    "process_execution_id",
                },
            )
            view.started(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
                _string(value, "fence"),
                _string(value, "process_execution_id"),
            )
            return {"state": "running"}
        if operation == "report":
            _exact(value, {"assignment_id", "incarnation", "fence", "report"})
            report = value["report"]
            if not isinstance(report, Mapping):
                raise QueueServiceError("SLURM result report is invalid")
            view.declare_report(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
                _string(value, "fence"),
                report,
            )
            return {"state": "report_durable"}
        if operation == "output":
            _exact(
                value,
                {
                    "assignment_id",
                    "incarnation",
                    "transfer_id",
                    "offset",
                    "data",
                    "final",
                },
            )
            final = value["final"]
            if not isinstance(final, bool):
                raise QueueServiceError("SLURM output final flag is invalid")
            return {
                "received": view.output_chunk(
                    _string(value, "assignment_id"),
                    _string(value, "incarnation"),
                    _string(value, "transfer_id"),
                    offset=_integer(value, "offset"),
                    data=_decode_chunk(value["data"]),
                    final=final,
                )
            }
        if operation == "result":
            _exact(value, {"assignment_id", "incarnation", "fence"})
            view.commit_result(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
                _string(value, "fence"),
            )
            return {"state": "terminal"}
        if operation == "release":
            _exact(value, {"assignment_id", "incarnation"})
            view.release(
                _string(value, "assignment_id"),
                _string(value, "incarnation"),
            )
            return {"state": "released"}
    raise QueueServiceError("daemon protocol operation is unsupported")


def _resident_launch_profile_set(
    config: AgentTlsClientConfig,
) -> tuple[tuple[str, str], ...]:
    """Canonical executable bindings held by the initialized supervisor.

    Capacity is intentionally absent: it contributes to provider inventory, not
    the protected worker executable, descriptor, or project binding.
    """

    return tuple(
        sorted(
            (
                profile.descriptor.profile_id,
                profile.launch_profile.fingerprint,
            )
            for profile in config.resident_profiles
        )
    )


def _agent_provider_composition_key(
    providers: Iterable[AgentResourceProvider],
) -> str:
    return _agent_revision(
        "resident-provider",
        {
            "providers": [
                {
                    "descriptor": provider.descriptor.to_dict(),
                    "claim_contracts": [
                        contract.to_dict()
                        for contract in sorted(
                            provider.claim_contracts, key=lambda item: item.key
                        )
                    ],
                }
                for provider in sorted(providers, key=lambda item: item.descriptor.key)
            ],
        },
    )


def _read_remote_agent_root_id(root: Path) -> str:
    """Read only the stable identity after protected-root validation."""
    path = Path(root).resolve() / "control.sqlite"
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT value FROM root_metadata WHERE key = 'stable_id'"
            ).fetchone()
    except sqlite3.Error as exc:
        raise QueueServiceError("remote agent control state is unavailable") from exc
    if row is None or not isinstance(row[0], str) or not row[0]:
        raise QueueServiceError("remote agent root identity is invalid")
    return row[0]


__all__ = [
    "AgentTlsClientConfig",
    "AgentTlsServerConfig",
    "LocalDaemonAgentHttpClient",
    "LocalDaemonAgentHttpServer",
    "RunInspectionHttpClient",
    "RunInspectionTlsClientConfig",
]
