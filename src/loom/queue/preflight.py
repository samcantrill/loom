"""Queue service preflight diagnostics."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError

from .config import QueueServiceSpec, load_queue_spec
from .errors import QueueServiceError
from .models import QueuePoolMode
from .resources import reconcile_managed_pool_limits
from .service import QueueService

if TYPE_CHECKING:
    from loom.diagnostics.models import PreflightResult, PreflightCheckResult
    from loom.pipeline.stores import AuthorityConfig, WorkspaceCoordinationStore


class QueuePreflightStatus(StrEnum):
    """Stable status values for queue preflight checks."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


class QueuePreflightSeverity(StrEnum):
    """Severity values for queue preflight checks."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class QueuePreflightCheck:
    """One queue preflight diagnostic."""

    check_id: str
    status: QueuePreflightStatus | str
    severity: QueuePreflightSeverity | str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", QueuePreflightStatus(self.status))
        object.__setattr__(self, "severity", QueuePreflightSeverity(self.severity))
        if not isinstance(self.check_id, str) or not self.check_id:
            raise QueueServiceError("check_id must be a non-empty string")
        if not isinstance(self.message, str) or not self.message:
            raise QueueServiceError("message must be a non-empty string")
        object.__setattr__(self, "details", _plain_mapping(self.details, "details"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "check_id": self.check_id,
            "status": QueuePreflightStatus(self.status).value,
            "severity": QueuePreflightSeverity(self.severity).value,
            "message": self.message,
            "details": thaw_plain_data(self.details, path="details"),
        }


@dataclass(frozen=True, slots=True)
class QueuePreflightResult:
    """Queue preflight result for CLI and Python callers."""

    config_path: str
    status: QueuePreflightStatus | str
    checks: tuple[QueuePreflightCheck, ...]
    summary: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", QueuePreflightStatus(self.status))
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "summary", _plain_mapping(self.summary, "summary"))

    @property
    def ok(self) -> bool:
        return QueuePreflightStatus(self.status) is not QueuePreflightStatus.FAIL

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "config_path": self.config_path,
            "status": QueuePreflightStatus(self.status).value,
            "checks": [check.to_dict() for check in self.checks],
            "summary": thaw_plain_data(self.summary, path="summary"),
        }


SlurmCommandChecker = Callable[[str], bool]


def run_queue_preflight(
    config_path: str | Path,
    *,
    authority_config: "AuthorityConfig | None" = None,
    coordination_store: "WorkspaceCoordinationStore | None" = None,
    workspace_id: str | None = None,
    slurm_command_checker: SlurmCommandChecker | None = None,
) -> QueuePreflightResult:
    """Run deterministic queue-service preflight diagnostics.

    The default checks do not submit work, mutate authority resource limits, or
    require a real SLURM cluster. Managed-pool limit reconciliation runs only
    when the caller supplies a public coordination store and workspace id.
    """

    config_text = str(config_path)
    try:
        spec = load_queue_spec(config_path)
    except Exception as exc:  # noqa: BLE001
        checks = (
            QueuePreflightCheck(
                check_id="queue.config.load",
                status=QueuePreflightStatus.FAIL,
                severity=QueuePreflightSeverity.ERROR,
                message="queue config could not be loaded",
                details={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            ),
        )
        return QueuePreflightResult(
            config_path=config_text,
            status=QueuePreflightStatus.FAIL,
            checks=checks,
        )

    checks = [
        QueuePreflightCheck(
            check_id="queue.config.load",
            status=QueuePreflightStatus.PASS,
            severity=QueuePreflightSeverity.INFO,
            message="queue config loaded",
            details=_spec_summary(spec),
        )
    ]
    checks.append(_service_repository_check(spec))
    checks.append(_resource_pool_config_check(spec))
    checks.append(_authority_connection_check(authority_config, workspace_id))
    checks.append(
        _managed_pool_limit_check(
            spec,
            coordination_store=coordination_store,
            workspace_id=workspace_id,
        )
    )
    checks.append(
        _static_assignment_authority_check(
            spec, coordination_store=coordination_store, workspace_id=workspace_id
        )
    )
    checks.append(_slurm_command_check(spec, slurm_command_checker))
    checks.append(_delegated_workspace_check(spec))
    status = _overall_status(checks)
    return QueuePreflightResult(
        config_path=config_text,
        status=status,
        checks=tuple(checks),
        summary=_spec_summary(spec),
    )


def _service_repository_check(spec: QueueServiceSpec) -> QueuePreflightCheck:
    try:
        service = QueueService.from_spec(spec)
        service.start()
        status = service.status()
    except Exception as exc:  # noqa: BLE001
        return QueuePreflightCheck(
            check_id="queue.service.repository",
            status=QueuePreflightStatus.FAIL,
            severity=QueuePreflightSeverity.ERROR,
            message="queue service repository is not reachable",
            details={
                "db_path": spec.db_path,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
    return QueuePreflightCheck(
        check_id="queue.service.repository",
        status=QueuePreflightStatus.PASS,
        severity=QueuePreflightSeverity.INFO,
        message="queue service repository is reachable",
        details={
            "db_path": spec.db_path,
            "state": status.state.value,
            "recovery_record_count": len(status.recovery_records),
        },
    )


def _resource_pool_config_check(spec: QueueServiceSpec) -> QueuePreflightCheck:
    managed_without_resources = [
        pool.pool_name
        for pool in spec.pools
        if pool.mode is QueuePoolMode.MANAGED and not pool.resources
    ]
    if managed_without_resources:
        return QueuePreflightCheck(
            check_id="queue.resource_pools",
            status=QueuePreflightStatus.WARN,
            severity=QueuePreflightSeverity.WARNING,
            message="one or more managed pools do not declare resources",
            details={
                "managed_without_resources": managed_without_resources,
                **_pool_mode_counts(spec),
            },
        )
    return QueuePreflightCheck(
        check_id="queue.resource_pools",
        status=QueuePreflightStatus.PASS,
        severity=QueuePreflightSeverity.INFO,
        message="queue pools and queues are normalized",
        details=_pool_mode_counts(spec),
    )


def _authority_connection_check(
    authority_config: "AuthorityConfig | None",
    workspace_id: str | None,
) -> QueuePreflightCheck:
    if authority_config is None:
        return QueuePreflightCheck(
            check_id="queue.authority.connection",
            status=QueuePreflightStatus.SKIP,
            severity=QueuePreflightSeverity.INFO,
            message="authority connection was not checked",
            details={"reason": "no authority config was supplied"},
        )
    configured_workspace = workspace_id or authority_config.workspace_id
    if configured_workspace is None:
        status = QueuePreflightStatus.WARN
        severity = QueuePreflightSeverity.WARNING
        message = "authority config is present but no workspace id is configured"
    else:
        status = QueuePreflightStatus.PASS
        severity = QueuePreflightSeverity.INFO
        message = "authority config is present for queue operations"
    return QueuePreflightCheck(
        check_id="queue.authority.connection",
        status=status,
        severity=severity,
        message=message,
        details={
            "workspace_id": configured_workspace,
            "authority": authority_config.redacted_dict(),
        },
    )


def _managed_pool_limit_check(
    spec: QueueServiceSpec,
    *,
    coordination_store: "WorkspaceCoordinationStore | None",
    workspace_id: str | None,
) -> QueuePreflightCheck:
    managed_pools = [
        pool.pool_name for pool in spec.pools if pool.mode is QueuePoolMode.MANAGED
    ]
    if not managed_pools:
        return QueuePreflightCheck(
            check_id="queue.managed_pool_limits",
            status=QueuePreflightStatus.SKIP,
            severity=QueuePreflightSeverity.INFO,
            message="no managed pools are configured",
            details={},
        )
    if coordination_store is None or not workspace_id:
        return QueuePreflightCheck(
            check_id="queue.managed_pool_limits",
            status=QueuePreflightStatus.SKIP,
            severity=QueuePreflightSeverity.INFO,
            message="managed pool limits were not reconciled against authority",
            details={
                "managed_pools": managed_pools,
                "reason": "coordination store and workspace id are required",
            },
        )
    try:
        report = reconcile_managed_pool_limits(
            spec,
            coordination_store,
            workspace_id=workspace_id,
        )
    except Exception as exc:  # noqa: BLE001
        return QueuePreflightCheck(
            check_id="queue.managed_pool_limits",
            status=QueuePreflightStatus.FAIL,
            severity=QueuePreflightSeverity.ERROR,
            message="managed pool limit reconciliation failed",
            details={
                "managed_pools": managed_pools,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
    return QueuePreflightCheck(
        check_id="queue.managed_pool_limits",
        status=QueuePreflightStatus.PASS if report.ok else QueuePreflightStatus.FAIL,
        severity=QueuePreflightSeverity.INFO
        if report.ok
        else QueuePreflightSeverity.ERROR,
        message="managed pool limits match authority"
        if report.ok
        else "managed pool limits do not match authority",
        details=report.to_dict(),
    )


def _static_assignment_authority_check(
    spec: QueueServiceSpec,
    *,
    coordination_store: "WorkspaceCoordinationStore | None",
    workspace_id: str | None,
) -> QueuePreflightCheck:
    """Read static-slot limits only; queues never provision authority state."""

    configured = [
        (pool_name, assignment)
        for pool_name, resources in spec.local_assignments.items()
        for assignment in resources.values()
    ]
    if not configured:
        return QueuePreflightCheck(
            check_id="queue.static_assignments",
            status=QueuePreflightStatus.SKIP,
            severity=QueuePreflightSeverity.INFO,
            message="no static local assignments are configured",
        )
    if coordination_store is None or not workspace_id:
        return QueuePreflightCheck(
            check_id="queue.static_assignments",
            status=QueuePreflightStatus.SKIP,
            severity=QueuePreflightSeverity.INFO,
            message="static assignment authority limits were not checked",
            details={"reason": "coordination store and workspace id are required"},
        )
    expected = {
        slot.coordination_key: 1
        for _pool_name, assignment in configured
        for slot in assignment.slots
    }
    try:
        from loom.pipeline.stores import coordination_requirement_diagnostics

        diagnostics = coordination_requirement_diagnostics(
            coordination_store.capabilities(), require_resource_leases=True
        )
        if diagnostics:
            return QueuePreflightCheck(
                check_id="queue.static_assignments",
                status=QueuePreflightStatus.FAIL,
                severity=QueuePreflightSeverity.ERROR,
                message="static assignments require resource-lease capabilities",
                details={
                    "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics]
                },
            )
        results = []
        for resource_key, desired_limit in expected.items():
            counter = coordination_store.read_resource_limit(workspace_id, resource_key)
            results.append(
                {
                    "resource_key": resource_key,
                    "expected_limit": desired_limit,
                    "actual_limit": None if counter is None else counter.limit,
                    "ok": counter is not None and counter.limit == desired_limit,
                }
            )
    except Exception as exc:  # noqa: BLE001
        return QueuePreflightCheck(
            check_id="queue.static_assignments",
            status=QueuePreflightStatus.FAIL,
            severity=QueuePreflightSeverity.ERROR,
            message="static assignment authority check failed",
            details={"error_type": type(exc).__name__, "error": str(exc)},
        )
    ok = all(result["ok"] for result in results)
    return QueuePreflightCheck(
        check_id="queue.static_assignments",
        status=QueuePreflightStatus.PASS if ok else QueuePreflightStatus.FAIL,
        severity=QueuePreflightSeverity.INFO if ok else QueuePreflightSeverity.ERROR,
        message="static assignment slot limits match authority"
        if ok
        else "static assignment slot limits do not match authority",
        details={"slots": results},
    )


def _slurm_command_check(
    spec: QueueServiceSpec,
    checker: SlurmCommandChecker | None,
) -> QueuePreflightCheck:
    delegated_pools = [
        pool.pool_name for pool in spec.pools if pool.mode is QueuePoolMode.DELEGATED
    ]
    if not delegated_pools:
        return QueuePreflightCheck(
            check_id="queue.slurm.commands",
            status=QueuePreflightStatus.SKIP,
            severity=QueuePreflightSeverity.INFO,
            message="no delegated pools are configured",
            details={},
        )
    command_checker = checker or _default_command_checker
    availability = {
        command: command_checker(command)
        for command in ("sbatch", "squeue", "sacct", "scancel")
    }
    missing = [command for command, available in availability.items() if not available]
    if missing:
        return QueuePreflightCheck(
            check_id="queue.slurm.commands",
            status=QueuePreflightStatus.WARN,
            severity=QueuePreflightSeverity.WARNING,
            message="one or more SLURM commands are unavailable",
            details={
                "delegated_pools": delegated_pools,
                "availability": availability,
                "missing": missing,
            },
        )
    return QueuePreflightCheck(
        check_id="queue.slurm.commands",
        status=QueuePreflightStatus.PASS,
        severity=QueuePreflightSeverity.INFO,
        message="SLURM commands are available for delegated queue checks",
        details={
            "delegated_pools": delegated_pools,
            "availability": availability,
        },
    )


def _delegated_workspace_check(spec: QueueServiceSpec) -> QueuePreflightCheck:
    delegated_pools = [
        pool for pool in spec.pools if pool.mode is QueuePoolMode.DELEGATED
    ]
    if not delegated_pools:
        return QueuePreflightCheck(
            check_id="queue.delegated_workspace_assumptions",
            status=QueuePreflightStatus.SKIP,
            severity=QueuePreflightSeverity.INFO,
            message="no delegated pools are configured",
            details={},
        )
    acknowledged = [
        pool.pool_name
        for pool in delegated_pools
        if pool.metadata.get("workspace_assumptions_acknowledged") is True
    ]
    if len(acknowledged) == len(delegated_pools):
        return QueuePreflightCheck(
            check_id="queue.delegated_workspace_assumptions",
            status=QueuePreflightStatus.PASS,
            severity=QueuePreflightSeverity.INFO,
            message="delegated workspace assumptions are acknowledged",
            details={"delegated_pools": acknowledged},
        )
    return QueuePreflightCheck(
        check_id="queue.delegated_workspace_assumptions",
        status=QueuePreflightStatus.WARN,
        severity=QueuePreflightSeverity.WARNING,
        message=(
            "delegated launch still assumes a pre-staged or shared workspace; "
            "bundle transport is not part of v11"
        ),
        details={
            "delegated_pools": [pool.pool_name for pool in delegated_pools],
            "acknowledged_pools": acknowledged,
        },
    )


def _overall_status(
    checks: Sequence[QueuePreflightCheck],
) -> QueuePreflightStatus:
    statuses = [QueuePreflightStatus(check.status) for check in checks]
    if QueuePreflightStatus.FAIL in statuses:
        return QueuePreflightStatus.FAIL
    if QueuePreflightStatus.WARN in statuses:
        return QueuePreflightStatus.WARN
    if statuses and all(status is QueuePreflightStatus.SKIP for status in statuses):
        return QueuePreflightStatus.SKIP
    return QueuePreflightStatus.PASS


def _spec_summary(spec: QueueServiceSpec) -> Mapping[str, PlainData]:
    return {
        "db_path": spec.db_path,
        "pools": [pool.to_dict() for pool in spec.pools],
        "queues": [queue.to_dict() for queue in spec.queues],
        "controller": spec.controller.to_dict(),
        **_pool_mode_counts(spec),
    }


def _pool_mode_counts(spec: QueueServiceSpec) -> Mapping[str, PlainData]:
    managed = sum(1 for pool in spec.pools if pool.mode is QueuePoolMode.MANAGED)
    delegated = sum(1 for pool in spec.pools if pool.mode is QueuePoolMode.DELEGATED)
    return {
        "pool_count": len(spec.pools),
        "queue_count": len(spec.queues),
        "managed_pool_count": managed,
        "delegated_pool_count": delegated,
    }


def _default_command_checker(command: str) -> bool:
    return shutil.which(command) is not None


def _plain_mapping(value: object, path: str) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise QueueServiceError(str(exc)) from exc
    thawed = thaw_plain_data(frozen, path=path)
    if not isinstance(thawed, Mapping):
        raise QueueServiceError(f"{path} must be a mapping")
    return thawed


__all__ = [
    "QueuePreflightCheck",
    "QueuePreflightResult",
    "QueuePreflightSeverity",
    "QueuePreflightStatus",
    "SlurmCommandChecker",
    "run_queue_preflight",
    "run_role_preflight",
]


def run_role_preflight(
    config_path: str | Path,
    *,
    role: str,
    env_file: str | Path | None = None,
    probe_io: bool = False,
    probe_gpu: bool = False,
) -> "PreflightResult":
    """Inspect one role and aggregate its applicable installation findings.

    Default inspection creates no deployment/run/claim state. Explicit IO probes
    touch only private temporary members beneath named, existing execution roots.
    Explicit GPU probes require initialized idle ownership and persist diagnostic
    claims until process containment and provider release are established.
    Connection and scientific checks remain with their actual owning operations.
    """
    import os
    import sys
    from dataclasses import replace

    from loom.diagnostics.models import (
        PreflightCheckStatus as Status,
        PreflightGroup as Group,
        PreflightResult,
    )
    from .deployment import (
        load_coordinator_service_config,
        load_outbound_agent_service_config,
    )
    from .errors import QueueError
    from .resident_readiness import readiness_check

    checks: list[PreflightCheckResult] = []

    def add(
        check_id: str,
        group: Group,
        status: Status,
        message: str,
        *,
        owner: str,
        repair: str,
        applicability: str = "required",
        evidence: Mapping[str, PlainData] | None = None,
    ) -> None:
        checks.append(
            readiness_check(
                check_id,
                group,
                status,
                message,
                owner=owner,
                consequence="Failed required checks withhold new work; retained ownership is unchanged.",
                repair=repair,
                applicability=applicability,
                evidence=evidence,
            )
        )

    try:
        if role == "coordinator":
            coordinator = load_coordinator_service_config(
                config_path, env_file=env_file, _allow_unready=True
            )
            gpu_configuration = coordinator
            agent = coordinator.local_agent
            profiles = () if agent is None else (agent.profile,)
            agent_root = None if agent is None else agent.agent_root
            assert coordinator.daemon.deployment_root is not None
            roots = (
                coordinator.daemon.deployment_root,
                coordinator.daemon.run_store_root,
            )
            capacity = coordinator.effective_capacity
        elif role == "agent":
            outbound = load_outbound_agent_service_config(
                config_path, env_file=env_file, _allow_unready=True
            )
            gpu_configuration = outbound
            profiles = outbound.client.resident_profiles
            agent_root = outbound.client.agent_root
            roots = () if agent_root is None else (agent_root,)
            capacity = outbound.effective_capacity
        else:
            raise ValueError("unknown managed role")
    except QueueError:
        add(
            "configuration.inputs",
            Group.CONFIG,
            Status.FAIL,
            "Protected role configuration or required bindings are unavailable.",
            owner="role loader",
            repair="Repair the explicit role files, required values, schema and path bindings.",
        )
        for name, group in (
            ("service.connection", Group.SERVICE),
            ("python.interpreter", Group.PYTHON),
            ("packages.required_imports", Group.PACKAGES),
            ("environment.worker", Group.ENVIRONMENT),
            ("resources.capacity", Group.RESOURCES),
            ("filesystem.role_roots", Group.FILESYSTEM),
            ("execution.identity", Group.IDENTITY),
        ):
            add(
                name,
                group,
                Status.SKIP,
                "This check requires a valid resolved role.",
                owner="role loader",
                repair="Repair configuration.inputs first.",
                applicability="blocked by configuration.inputs",
            )
        return PreflightResult(
            tuple(checks), tuple(dict.fromkeys(item.group for item in checks))
        )

    add(
        "configuration.inputs",
        Group.CONFIG,
        Status.PASS,
        "Explicit protected role inputs resolved and normalized.",
        owner="role loader",
        repair="Keep the configured files protected and use explicit reload for changed values.",
    )
    add(
        "service.connection",
        Group.SERVICE,
        Status.SKIP,
        "Live identity, authentication and connection checks run at startup/reconnect.",
        owner="coordinator/agent protocol",
        repair="Start the configured roles and inspect their connection findings.",
        applicability="startup/reconnect boundary; no connection created by this check",
    )
    if role == "coordinator":
        add(
            "python.service",
            Group.PYTHON,
            Status.PASS if sys.version_info >= (3, 12) else Status.FAIL,
            "Coordinator service interpreter observed.",
            owner="coordinator service",
            repair="Run Loom with supported Python.",
            evidence={"version": list(sys.version_info[:3])},
        )
    for profile in profiles:
        result = profile.readiness_result
        if result is None:
            add(
                "execution.identity",
                Group.IDENTITY,
                Status.FAIL,
                "Resident qualification evidence is unavailable.",
                owner="resident profile",
                repair="Qualify the selected installation before offering work.",
            )
            continue
        for check in result.checks:
            checks.append(
                replace(
                    check,
                    details={
                        **dict(check.details),
                        "profile_id": profile.descriptor.profile_id,
                    },
                )
            )
    if not profiles:
        for name, group in (
            ("packages.required_imports", Group.PACKAGES),
            ("environment.worker", Group.ENVIRONMENT),
            ("execution.identity", Group.IDENTITY),
        ):
            add(
                name,
                group,
                Status.SKIP,
                "This coordinator has no local worker profile.",
                owner="coordinator role",
                repair="Configure agents when execution capacity is required.",
                applicability="coordinator only",
            )
    add(
        "resources.capacity",
        Group.RESOURCES,
        (Status.PASS if capacity is not None else Status.WARN)
        if profiles
        else Status.SKIP,
        (
            "Agent resource selection was checked against available supported limits."
            if capacity is not None
            else "Legacy profile capacity is declared; host limits and GPU selection were not discovered."
        )
        if profiles
        else "A pure coordinator needs no execution resources.",
        owner="agent resource providers",
        repair="Select valid agent capacity; current claims are distinct from declared capacity.",
        applicability="agent resources" if profiles else "coordinator only",
        evidence={
            "effective_capacity": None if capacity is None else capacity.to_dict()
        },
    )
    roots_ok = True
    for root in roots:
        path = Path(root)
        while not path.exists() and path != path.parent:
            path = path.parent
        roots_ok = (
            roots_ok and path.is_dir() and os.access(path, os.R_OK | os.W_OK | os.X_OK)
        )
    add(
        "filesystem.role_roots",
        Group.FILESYSTEM,
        Status.PASS if roots_ok else Status.FAIL,
        "Execution roots or their existing parents are accessible."
        if roots_ok
        else "An execution root or parent is unavailable.",
        owner="role/workspace stores",
        repair="Create accessible execution roots on storage supported by the selected store; access inspection is not write proof.",
        evidence={"write_probe_requested": probe_io},
    )
    if probe_io:
        for index, root in enumerate(roots):
            checks.append(_role_io_probe(Path(root), index))
    else:
        add(
            "filesystem.io",
            Group.FILESYSTEM,
            Status.SKIP,
            "Active IO probe was not requested.",
            owner="role/workspace stores",
            repair="Use --probe-io for tiny writes in existing execution-owned roots.",
            applicability="unrequested active probe",
        )
    add(
        "scientific.inputs",
        Group.PIPELINE,
        Status.SKIP,
        "Scientific inputs, run contracts and artifact compatibility are checked by the project at check/prepare.",
        owner="project preparation",
        repair="Run the project check with its selected data, cache and run configuration.",
        applicability="project check/prepare boundary",
    )
    if agent_root is not None and Path(agent_root).exists():
        from ._agent_process_supervisor import (
            AgentProcessSupervisorError,
            SupervisorLaunchConfiguration,
            _service_configuration,
        )

        try:
            retained = _service_configuration(Path(agent_root) / "supervisor")
            current = SupervisorLaunchConfiguration(
                retained.agent_id, tuple(profile.launch_profile for profile in profiles)
            )
            matches = retained.fingerprint == current.fingerprint
        except (AgentProcessSupervisorError, OSError):
            matches = False
        add(
            "execution.retained_binding",
            Group.IDENTITY,
            Status.PASS if matches else Status.FAIL,
            "Observed profile bindings match initialized ownership."
            if matches
            else "Observed installation or private binding differs from initialized ownership.",
            owner="resident supervisor",
            repair="Preserve retained work; settle it before deliberately qualifying a new profile/deployment.",
        )
    if probe_gpu and not any(check.status is Status.FAIL for check in checks):
        from ._gpu_probe import run_role_gpu_probes

        checks.extend(run_role_gpu_probes(gpu_configuration))
    else:
        add(
            "resources.gpu_compute",
            Group.RESOURCES,
            Status.SKIP,
            "GPU enumeration does not establish compute qualification.",
            owner="agent GPU provider",
            repair="Repair failed checks, then use --probe-gpu after init and before serve.",
            applicability="blocked by failed readiness" if probe_gpu else "unrequested active probe",
        )
    return PreflightResult(
        tuple(checks), tuple(dict.fromkeys(item.group for item in checks))
    )


def _role_io_probe(root: Path, index: int) -> "PreflightCheckResult":
    import tempfile

    from loom.diagnostics.models import (
        PreflightCheckStatus as Status,
        PreflightGroup as Group,
    )
    from .resident_readiness import readiness_check

    passed = False
    try:
        if root.is_dir():
            with tempfile.TemporaryDirectory(
                prefix=".loom-io-probe-", dir=root
            ) as directory:
                source = Path(directory) / "write"
                renamed = Path(directory) / "renamed"
                source.write_bytes(b"loom-io-probe\n")
                if source.read_bytes() != b"loom-io-probe\n":
                    raise OSError("probe read did not match")
                source.replace(renamed)
                if renamed.read_bytes() != b"loom-io-probe\n":
                    raise OSError("probe rename did not preserve contents")
                renamed.unlink()
            passed = True
    except OSError:
        pass
    return readiness_check(
        "filesystem.io",
        Group.FILESYSTEM,
        Status.PASS if passed else Status.FAIL,
        "Tiny execution-root IO probe and cleanup passed."
        if passed
        else "Execution-root IO probe could not complete and clean up.",
        owner="role/workspace stores",
        consequence="Failure withholds the requested filesystem qualification.",
        repair="Use an existing writable execution-owned root; resolve storage/access/cleanup failures.",
        applicability="explicit active probe",
        evidence={"root_index": index},
    )
