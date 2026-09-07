"""Managed queue-pool resource reconciliation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import resource

from loom.pipeline.execution.resource_admission import (
    ResourceLimitReconciliationResult,
    reconcile_resource_limits,
)
from loom.pipeline.stores import WorkspaceCoordinationStore
from loom.serialization import PlainData

from .config import QueueServiceSpec
from .errors import QueueServiceError
from .models import QueuePool, QueuePoolMode, validate_queue_id


@dataclass(frozen=True, slots=True)
class EffectiveAgentCapacity:
    """Process-local resource evidence; ``None`` means the limit is unavailable."""

    cpu_capacity: int | None
    memory_capacity_bytes: int | None

    def to_dict(self) -> dict[str, PlainData]:
        """Return the supported effective-limit evidence for role checks."""

        return {
            "cpu_capacity": self.cpu_capacity,
            "memory_capacity_bytes": self.memory_capacity_bytes,
        }


def observe_effective_agent_capacity() -> EffectiveAgentCapacity:
    """Observe supported process allocation and host-memory limits.

    CPU capacity is bounded by affinity and any finite cgroup-v2 CPU quota on
    the process's cgroup or its ancestors. Memory capacity is the least finite
    address-space, cgroup-v2, or host-memory limit. An unavailable source does
    not imply a limit; it remains ``None`` when no supported finite limit is
    available.
    """

    cpu_limits: list[int] = []
    try:
        affinity = len(os.sched_getaffinity(0))
        if affinity:
            cpu_limits.append(affinity)
    except (AttributeError, OSError):
        pass
    memory_limits: list[int] = []
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        for limit in (soft, hard):
            if limit not in {resource.RLIM_INFINITY, -1} and limit > 0:
                memory_limits.append(limit)
    except (ValueError, OSError):
        pass
    cgroup_cpu, cgroup_memory = _cgroup_v2_limits()
    if cgroup_cpu is not None:
        cpu_limits.append(cgroup_cpu)
    if cgroup_memory is not None:
        memory_limits.append(cgroup_memory)
    host_memory = _host_memory_limit()
    if host_memory is not None:
        memory_limits.append(host_memory)
    return EffectiveAgentCapacity(
        min(cpu_limits) if cpu_limits else None,
        min(memory_limits) if memory_limits else None,
    )


def _cgroup_v2_limits(
    *,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    membership_path: Path = Path("/proc/self/cgroup"),
) -> tuple[int | None, int | None]:
    """Return finite cgroup-v2 CPU and memory limits for this process tree."""

    try:
        membership = membership_path.read_text(encoding="ascii")
    except OSError:
        return None, None
    relative_path = _cgroup_v2_membership(membership)
    if relative_path is None:
        return None, None
    current = cgroup_root.joinpath(*relative_path.parts[1:])
    cpu_limits: list[int] = []
    memory_limits: list[int] = []
    while True:
        cpu_limit = _cpu_max_limit(current / "cpu.max")
        if cpu_limit is not None:
            cpu_limits.append(cpu_limit)
        memory_limit = _memory_max_limit(current / "memory.max")
        if memory_limit is not None:
            memory_limits.append(memory_limit)
        if current == cgroup_root:
            break
        try:
            current.relative_to(cgroup_root)
        except ValueError:
            return None, None
        current = current.parent
    return (
        min(cpu_limits) if cpu_limits else None,
        min(memory_limits) if memory_limits else None,
    )


def _cgroup_v2_membership(value: str) -> Path | None:
    for line in value.splitlines():
        hierarchy, separator, path = line.partition("::")
        if hierarchy != "0" or not separator:
            continue
        candidate = Path(path)
        if candidate.is_absolute() and ".." not in candidate.parts:
            return candidate
    return None


def _cpu_max_limit(path: Path) -> int | None:
    try:
        quota, period = path.read_text(encoding="ascii").split()
    except (OSError, ValueError):
        return None
    if quota == "max" or not quota.isdecimal() or not period.isdecimal():
        return None
    quota_value = int(quota)
    period_value = int(period)
    if quota_value <= 0 or period_value <= 0:
        return None
    return math.floor(quota_value / period_value)


def _memory_max_limit(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    if value != "max" and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


def _host_memory_limit() -> int | None:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    if (
        isinstance(page_size, int)
        and isinstance(page_count, int)
        and page_size > 0
        and page_count > 0
    ):
        return page_size * page_count
    return None


def require_effective_agent_capacity(
    *, cpu_capacity: int, memory_capacity_bytes: int
) -> EffectiveAgentCapacity:
    """Reject configured capacity that exceeds a proven process-local limit."""

    observed = observe_effective_agent_capacity()
    if observed.cpu_capacity is not None and cpu_capacity > observed.cpu_capacity:
        raise QueueServiceError("configured CPU capacity exceeds effective allocation")
    if (
        memory_capacity_bytes
        and observed.memory_capacity_bytes is not None
        and memory_capacity_bytes > observed.memory_capacity_bytes
    ):
        raise QueueServiceError("configured memory capacity exceeds effective limit")
    return observed


@dataclass(frozen=True, slots=True)
class ManagedPoolReconciliation:
    """Authority readback for one managed queue pool."""

    pool_name: str
    resources: Mapping[str, int]
    results: tuple[ResourceLimitReconciliationResult, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "pool_name": self.pool_name,
            "resources": dict(self.resources),
            "ok": self.ok,
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True, slots=True)
class ManagedPoolReconciliationReport:
    """Read-only resource-limit reconciliation report for queue pools."""

    workspace_id: str
    pools: tuple[ManagedPoolReconciliation, ...]

    @property
    def ok(self) -> bool:
        return all(pool.ok for pool in self.pools)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "workspace_id": self.workspace_id,
            "ok": self.ok,
            "pools": [pool.to_dict() for pool in self.pools],
        }


def reconcile_managed_pool_limits(
    spec: QueueServiceSpec,
    store: WorkspaceCoordinationStore,
    *,
    workspace_id: str,
    pool_names: Sequence[str] | None = None,
) -> ManagedPoolReconciliationReport:
    """Compare managed queue pool resource expectations with authority truth.

    This function intentionally never creates or updates authority limits; queue
    configuration is only validated against existing authority state.
    """

    if not isinstance(workspace_id, str) or not workspace_id:
        raise QueueServiceError("workspace_id must be a non-empty string")
    selected_names = None if pool_names is None else _pool_name_set(pool_names)
    reconciliations: list[ManagedPoolReconciliation] = []
    for pool in spec.pools:
        if pool.mode is not QueuePoolMode.MANAGED:
            continue
        if selected_names is not None and pool.pool_name not in selected_names:
            continue
        resources = _positive_resources(pool)
        reconciliations.append(
            ManagedPoolReconciliation(
                pool_name=pool.pool_name,
                resources=resources,
                results=reconcile_resource_limits(
                    store,
                    workspace_id,
                    resources,
                ),
            )
        )
    if selected_names is not None:
        missing = selected_names - {pool.pool_name for pool in spec.pools}
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise QueueServiceError(f"unknown pool(s): {missing_text}")
    return ManagedPoolReconciliationReport(
        workspace_id=workspace_id,
        pools=tuple(reconciliations),
    )


def require_managed_pool_limits(
    spec: QueueServiceSpec,
    store: WorkspaceCoordinationStore,
    *,
    workspace_id: str,
    pool_names: Sequence[str] | None = None,
) -> ManagedPoolReconciliationReport:
    """Return reconciliation evidence or raise on any mismatched managed pool."""

    report = reconcile_managed_pool_limits(
        spec,
        store,
        workspace_id=workspace_id,
        pool_names=pool_names,
    )
    if not report.ok:
        failures = [
            f"{pool.pool_name}:{result.resource_key}:{result.status.value}"
            for pool in report.pools
            for result in pool.results
            if not result.ok
        ]
        raise QueueServiceError(
            "managed queue pool resource limits do not match authority: "
            + ", ".join(failures)
        )
    return report


def _pool_name_set(pool_names: Sequence[str]) -> set[str]:
    names = {validate_queue_id(pool_name, "pool_name") for pool_name in pool_names}
    if not names:
        raise QueueServiceError("pool_names must not be empty")
    return names


def _positive_resources(pool: QueuePool) -> Mapping[str, int]:
    resources: dict[str, int] = {}
    for key, amount in pool.resources.items():
        if amount <= 0:
            raise QueueServiceError(
                f"managed pool {pool.pool_name} resource {key} must be positive"
            )
        resources[key] = amount
    return resources


__all__ = [
    "EffectiveAgentCapacity",
    "ManagedPoolReconciliation",
    "ManagedPoolReconciliationReport",
    "observe_effective_agent_capacity",
    "reconcile_managed_pool_limits",
    "require_effective_agent_capacity",
    "require_managed_pool_limits",
]
