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
        status=QueuePreflightStatus.PASS
        if report.ok
        else QueuePreflightStatus.FAIL,
        severity=QueuePreflightSeverity.INFO
        if report.ok
        else QueuePreflightSeverity.ERROR,
        message="managed pool limits match authority"
        if report.ok
        else "managed pool limits do not match authority",
        details=report.to_dict(),
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
]
