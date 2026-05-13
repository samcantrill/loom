"""Managed queue-pool resource reconciliation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

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
    "ManagedPoolReconciliation",
    "ManagedPoolReconciliationReport",
    "reconcile_managed_pool_limits",
    "require_managed_pool_limits",
]
