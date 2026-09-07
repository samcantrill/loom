"""Maintenance GPU qualification through the initialized agent's claim owner."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from loom.diagnostics.models import PreflightCheckResult, PreflightCheckStatus as Status
from loom.diagnostics.models import PreflightGroup as Group
from loom.pipeline.runtime.scheduling_resources import GpuResourcePlanner
from loom.serialization import PlainData

from ._agent_process_supervisor import (
    SupervisorLaunchConfiguration,
    _service_configuration,
)
from ._managed_local import (
    AgentResourceProvider,
    ClaimCommand,
    ClaimOutcome,
    ManagedLocalError,
    ObserveRequest,
    SQLiteAgentJournal,
    _ProbeClaimOwner,
    _compose_agent_resource_providers,
    _operation_command,
    _provider_call,
)
from ._resident_probe import run_resident_probe
from .resident_readiness import readiness_check

if TYPE_CHECKING:
    from ._remote_stage_execution import ResidentExecutionProfile
    from .deployment import CoordinatorServiceConfig, OutboundAgentServiceConfig


_GPU_SCRIPT = """
import contextlib, json, sys
with contextlib.redirect_stdout(sys.stderr):
    import torch
    if torch.cuda.device_count() != 1:
        raise RuntimeError("one assigned device is required")
    value = torch.ones((8,), device="cuda")
    result = (value * 2).sum()
    torch.cuda.synchronize()
    passed = result.item() == 16
print(json.dumps({"protocol": "loom.gpu-probe.v1", "ok": passed}))
"""


class _ProbeBusy(Exception):
    pass


def _finding(
    status: Status,
    message: str,
    *,
    applicability: str = "requested active probe",
    evidence: Mapping[str, PlainData] | None = None,
) -> PreflightCheckResult:
    return readiness_check(
        "resources.gpu_compute",
        Group.RESOURCES,
        status,
        message,
        owner="agent GPU provider and journal",
        consequence="Only a completed owned kernel and cleanup qualify GPU compute; uncertain claims retain capacity.",
        repair="Initialize first, stop the owning service and settle retained work. Use the declared resident GPU runtime; preserve uncertain claims for verified recovery.",
        applicability=applicability,
        evidence=evidence,
    )


def run_role_gpu_probes(
    configuration: CoordinatorServiceConfig | OutboundAgentServiceConfig,
) -> tuple[PreflightCheckResult, ...]:
    """Qualify each profile's selected devices sequentially under its role lock."""
    from .deployment import CoordinatorServiceConfig

    if isinstance(configuration, CoordinatorServiceConfig):
        profiles = (
            ()
            if configuration.local_agent is None
            else (configuration.local_agent.profile,)
        )
    else:
        profiles = configuration.client.resident_profiles
        inventory = configuration.client.resource_inventory
        if inventory is not None:
            profiles = tuple(
                replace(profile, gpu_devices=inventory.gpu_devices)
                for profile in profiles
            )
    gpu_profiles = tuple(profile for profile in profiles if profile.gpu_devices)
    if not gpu_profiles:
        return (
            _finding(
                Status.SKIP,
                "This role has no GPU execution profile.",
                applicability="inapplicable",
            ),
        )
    unsupported = tuple(
        profile.descriptor.profile_id
        for profile in gpu_profiles
        if "torch" not in profile.readiness_requirements.distributions
        and not any(
            name.split(".")[0] == "torch"
            for name in profile.readiness_requirements.imports
        )
    )
    if unsupported:
        return (
            _finding(
                Status.FAIL,
                "Requested GPU compute qualification needs a declared Torch runtime.",
                evidence={"profile_ids": list(unsupported)},
            ),
        )
    findings: list[PreflightCheckResult] = []
    try:
        with _probe_owner(configuration, profiles) as (agent_id, journal, providers):
            for profile in gpu_profiles:
                for device in profile.gpu_devices:
                    finding = _probe_device(
                        profile,
                        device.descriptor.device_id,
                        agent_id,
                        journal,
                        providers,
                    )
                    findings.append(finding)
                    if journal.retained_claim_commands():
                        return tuple(findings)
    except _ProbeBusy:
        findings.append(
            _finding(
                Status.SKIP,
                "The agent is running or retains work; GPU probing is deferred.",
                applicability="busy/deferred",
            )
        )
    except Exception:  # noqa: BLE001 - report external owner failures without private paths.
        findings.append(
            _finding(
                Status.FAIL,
                "Initialized GPU probe ownership or retained binding is unavailable.",
            )
        )
    return tuple(findings)


@contextmanager
def _probe_owner(
    configuration: CoordinatorServiceConfig | OutboundAgentServiceConfig,
    profiles: tuple[ResidentExecutionProfile, ...],
) -> Iterator[tuple[str, SQLiteAgentJournal, dict[str, AgentResourceProvider]]]:
    from .agent_session_transport import _RemoteAgentJournal, _agent_active_fingerprint
    from .deployment import CoordinatorServiceConfig
    from .errors import QueueServiceError
    from .local_daemon import _acquire_lock, _open_root, _validate_deployment_binding
    from .local_daemon_execution import local_daemon_owner_work_is_retained

    with ExitStack() as stack:
        if isinstance(configuration, CoordinatorServiceConfig):
            config = configuration.daemon
            root = config.agent_root
            if root is None:
                raise ManagedLocalError("local GPU probe has no agent root")
            _validate_deployment_binding(config)
            try:
                lock = _acquire_lock(root)
            except QueueServiceError as exc:
                raise _ProbeBusy from exc
            stack.callback(lock.close)
            _validate_deployment_binding(config)
            root_id = _open_root(root, role="local-agent")
            coordinator_id = _open_root(config.coordinator_root, role="coordinator")
            providers = _compose_agent_resource_providers(
                tuple(config.agent_resource_providers or ())
            )
            agent_id = config.machine_id
            extra_retained = local_daemon_owner_work_is_retained(
                config, coordinator_id=coordinator_id, agent_id=root_id
            )
        else:
            client = configuration.client
            root = client.agent_root
            if root is None:
                raise ManagedLocalError("outbound GPU probe has no agent root")
            try:
                control = _RemoteAgentJournal(
                    root,
                    expected_configuration_fingerprint=client.deployment_configuration_fingerprint,
                    expected_active_configuration_fingerprint=_agent_active_fingerprint(
                        client
                    ),
                )
            except QueueServiceError as exc:
                if str(exc) == "remote agent root is already locked":
                    raise _ProbeBusy from exc
                raise
            stack.callback(control.close)
            root_id = control.root_id
            session = control.active_session()
            agent_id = root_id if session is None else session.agent_id
            factory = client.agent_resource_provider_factory
            if factory is None:
                raise ManagedLocalError("GPU provider factory is missing")
            providers = _compose_agent_resource_providers(
                tuple(factory(agent_id, client.capacity_profile))
            )
            extra_retained = control.has_unresolved_assignment_references()

        retained_configuration = _service_configuration(Path(root) / "supervisor")
        current = SupervisorLaunchConfiguration(
            root_id, tuple(profile.launch_profile for profile in profiles)
        )
        if current.fingerprint != retained_configuration.fingerprint:
            raise ManagedLocalError("GPU probe launch binding conflicts")
        journal = SQLiteAgentJournal(
            Path(root) / "journal.sqlite", _allow_initialize=False
        )
        journal._open_existing()
        retained = journal.retained_claim_commands()
        for command in retained:
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("retained GPU probe provider is missing")
            provider.restore_capacity_holding(command)
        if retained or extra_retained:
            raise _ProbeBusy
        yield agent_id, journal, providers


def _probe_device(
    profile: ResidentExecutionProfile,
    device_id: str,
    agent_id: str,
    journal: SQLiteAgentJournal,
    providers: Mapping[str, AgentResourceProvider],
) -> PreflightCheckResult:
    evidence: dict[str, PlainData] = {
        "profile_id": profile.descriptor.profile_id,
        "device_id": device_id,
    }
    provider = providers.get("gpu")
    if provider is None:
        return _finding(
            Status.FAIL,
            "The configured GPU provider is unavailable.",
            evidence=evidence,
        )
    owner = _ProbeClaimOwner(f"diagnostic-probe:{uuid4().hex}", agent_id)
    observed = provider.observe(
        ObserveRequest(agent_id, owner.session_id, f"{owner.probe_id}:observe")
    )
    if observed.live_claim_ids:
        raise _ProbeBusy
    atom = next(
        (
            item
            for item in observed.atoms
            if item.local_capacity_key == f"{agent_id}:{device_id}"
        ),
        None,
    )
    device = next(
        item for item in profile.gpu_devices if item.descriptor.device_id == device_id
    )
    if atom is None or atom != device.descriptor.capacity_atom(
        f"{agent_id}:{device_id}"
    ):
        return _finding(
            Status.FAIL,
            "The configured device has no complete available provider binding.",
            evidence=evidence,
        )
    claim = GpuResourcePlanner()._claim(
        (atom,),
        device.descriptor.allocation_mode,
        device.descriptor.provider,
        observed.availability_revision,
    )
    command = ClaimCommand(owner, owner.probe_id, claim, provider.descriptor)
    evidence["probe_id"] = owner.probe_id
    journal.reserve_probe(command)
    try:
        for operation, expected in (
            ("prepare", ClaimOutcome.PREPARED),
            ("activate", ClaimOutcome.ACTIVE),
        ):
            result = _provider_call(
                getattr(provider, operation), _operation_command(command, operation)
            )
            if result.outcome is not expected:
                if result.outcome is ClaimOutcome.DECLINED:
                    journal.mark_probe_contained(owner.probe_id)
                    released = journal.release_probe(owner.probe_id, providers)
                    evidence["claim_retained"] = not released
                    if released:
                        return _finding(
                            Status.SKIP,
                            "GPU provider capacity is busy; probing is deferred.",
                            applicability="busy/deferred",
                            evidence=evidence,
                        )
                evidence["claim_retained"] = True
                return _finding(
                    Status.FAIL,
                    "GPU probe claim activation was not established; ownership is retained.",
                    evidence=evidence,
                )
        environment = provider.worker_environment(command)
        journal.mark_probe_launch_intent(owner.probe_id)
        result = run_resident_probe(
            profile.launch_profile,
            _GPU_SCRIPT,
            {},
            timeout_seconds=profile.readiness_requirements.timeout_seconds,
            device_environment=environment,
        )
        if not result.contained:
            evidence["claim_retained"] = True
            return _finding(
                Status.FAIL,
                "GPU probe process cleanup is uncertain; ownership is retained.",
                evidence=evidence,
            )
        journal.mark_probe_contained(owner.probe_id)
        released = journal.release_probe(owner.probe_id, providers)
        evidence["claim_retained"] = not released
        if not released:
            return _finding(
                Status.FAIL,
                "GPU probe provider release is uncertain; ownership is retained.",
                evidence=evidence,
            )
        passed = result.failure is None and result.payload == {
            "protocol": "loom.gpu-probe.v1",
            "ok": True,
        }
        return _finding(
            Status.PASS if passed else Status.FAIL,
            "Assigned GPU computation and cleanup passed."
            if passed
            else "Assigned GPU computation failed; process cleanup and claim release completed.",
            evidence=evidence,
        )
    except Exception:  # noqa: BLE001 - preserve the diagnostic identity on owner failures.
        return _finding(
            Status.FAIL,
            "GPU probe completion is unconfirmed; preserve its journal claim for recovery.",
            evidence=evidence,
        )
