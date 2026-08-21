"""Foreground runtime for one safely managed local queue pool.

The facade deliberately owns only process-local lifetime and loop policy.  The
queue service remains the durable queue boundary, while the controller and
local adapter retain dispatch and lease ownership respectively.
"""

from __future__ import annotations

import os
from math import isfinite
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from loom.pipeline.stores import (
    WorkspaceCoordinationStore,
    coordination_requirement_diagnostics,
)
from loom.serialization import PlainData
from loom.timestamps import parse_timestamp, utc_timestamp

from .assignments import (
    NoOpResourceAssignmentProvider,
    ResourceAssignmentProvider,
    StaticSlotAssignmentProvider,
)
from .config import QueueServiceSpec
from .controller import QueueController, QueueCycleResult
from .errors import QueueServiceError
from .local import LocalProcessRunner, LocalQueueDispatchAdapter
from .models import (
    DispatchHandle,
    QueueItem,
    QueueItemStatus,
    QueuePool,
    QueuePoolMode,
)
from .repository import QueueRepository
from .resources import require_managed_pool_limits
from .selection import QueueSelectionPolicy
from .service import QueueService, QueueServiceState
from .status import QueuePoolStatus, build_queue_pool_status


class ManagedLocalQueueRuntimeState(StrEnum):
    """Process-local lifecycle state for a managed local pool."""

    READY = "READY"
    DEGRADED = "DEGRADED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    DRAINING = "DRAINING"
    CANCELLING = "CANCELLING"
    STOPPED = "STOPPED"


class ManagedLocalShutdownTimeoutError(QueueServiceError):
    """Raised when managed-local shutdown still owns active work at its deadline."""

    def __init__(self, remaining_item_ids: tuple[str, ...]) -> None:
        self.remaining_item_ids = remaining_item_ids
        super().__init__(
            "managed local shutdown timed out with remaining items: "
            + ", ".join(remaining_item_ids)
        )


@dataclass(frozen=True, slots=True)
class ManagedLocalQueueRuntimeStatus:
    """Plain-data, non-durable operational status for one runtime instance."""

    state: ManagedLocalQueueRuntimeState
    owner_id: str
    pool_name: str
    last_cycle_at: str | None
    next_maintenance_at: str | None
    degraded_item_ids: tuple[str, ...]
    foreign_item_ids: tuple[str, ...]
    pool_status: QueuePoolStatus | None
    observation_scope: Mapping[str, str]

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "state": self.state.value,
            "owner_id": self.owner_id,
            "pool_name": self.pool_name,
            "last_cycle_at": self.last_cycle_at,
            "next_maintenance_at": self.next_maintenance_at,
            "degraded_item_ids": list(self.degraded_item_ids),
            "foreign_item_ids": list(self.foreign_item_ids),
            "pool_status": None
            if self.pool_status is None
            else self.pool_status.to_dict(),
            "observation_scope": dict(self.observation_scope),
        }


class _StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


class ManagedLocalQueueRuntime:
    """Run one selected managed pool with local process dispatch.

    This object is intentionally in-process state.  A fresh instance never
    treats prior local handles as its own and therefore gates on recovery
    rather than attempting reattachment.
    """

    def __init__(
        self,
        *,
        spec: QueueServiceSpec,
        service: QueueService,
        pool: QueuePool,
        coordination_store: WorkspaceCoordinationStore,
        workspace_id: str,
        adapter: LocalQueueDispatchAdapter,
        controller: QueueController,
        clock: Callable[[], str],
    ) -> None:
        self.spec = spec
        self.service = service
        self.pool_name = pool.pool_name
        self.owner_id = spec.controller.owner_id
        self._pool = pool
        self._coordination_store = coordination_store
        self._workspace_id = workspace_id
        self.adapter = adapter
        self.controller = controller
        self._clock = clock
        self._state = ManagedLocalQueueRuntimeState.READY
        self._last_cycle_at: str | None = None
        self._next_maintenance_at: str | None = None
        self._degraded_item_ids: tuple[str, ...] = ()
        self._foreign_item_ids: tuple[str, ...] = ()
        self._last_pool_status: QueuePoolStatus | None = None
        self._shutdown_active = False

    @classmethod
    def from_spec(
        cls,
        spec: QueueServiceSpec,
        *,
        workspace_id: str,
        coordination_store: WorkspaceCoordinationStore,
        pool_name: str | None = None,
        repository: QueueRepository | None = None,
        process_runner: LocalProcessRunner | None = None,
        current_drift_inputs: Mapping[str, PlainData] | None = None,
        lease_ttl_seconds: int = 60,
        wait_timeout_seconds: float = 0.0,
        assignment_provider: ResourceAssignmentProvider | None = None,
        selection_policies: Mapping[str, QueueSelectionPolicy] | None = None,
        log_directory: str | Path | None = None,
        clock: Callable[[], str] = utc_timestamp,
    ) -> "ManagedLocalQueueRuntime":
        """Construct one selected local runtime with one spec-owned owner."""

        pool = _select_pool(spec, pool_name)
        authored = spec.local_assignments.get(pool.pool_name, {})
        if authored and assignment_provider is not None:
            raise QueueServiceError(
                "authored local assignments and an explicit assignment_provider are ambiguous"
            )
        if authored:
            provider: ResourceAssignmentProvider = StaticSlotAssignmentProvider(
                coordination_store,
                workspace_id=workspace_id,
                slots=tuple(
                    slot
                    for assignment in authored.values()
                    for slot in assignment.slots
                ),
                bindings={
                    resource_name: assignment.binding
                    for resource_name, assignment in authored.items()
                },
            )
        else:
            provider = assignment_provider or NoOpResourceAssignmentProvider()
        service = QueueService.from_spec(spec, repository, clock=clock)
        owner_id = spec.controller.owner_id
        adapter = LocalQueueDispatchAdapter(
            workspace_id=workspace_id,
            coordination_store=coordination_store,
            owner_id=owner_id,
            process_runner=process_runner,
            current_drift_inputs=current_drift_inputs,
            lease_ttl_seconds=lease_ttl_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            clock=clock,
            assignment_provider=provider,
            log_directory=log_directory,
        )
        controller = QueueController(
            service,
            adapters={adapter.adapter_name: adapter},
            selection_policies=selection_policies,
            owner_id=owner_id,
            clock=clock,
        )
        return cls(
            spec=spec,
            service=service,
            pool=pool,
            coordination_store=coordination_store,
            workspace_id=workspace_id,
            adapter=adapter,
            controller=controller,
            clock=clock,
        )

    @property
    def state(self) -> ManagedLocalQueueRuntimeState:
        return self._state

    def start(self) -> ManagedLocalQueueRuntimeStatus:
        """Read-only validate authority state, then start this in-process service."""

        self._shutdown_active = False
        self._validate_startup()
        if self.service.state is not QueueServiceState.RUNNING:
            self.service.start()
        try:
            _current, foreign = self._classify_recovery()
        except Exception:
            self._state = ManagedLocalQueueRuntimeState.DEGRADED
            raise
        self._foreign_item_ids = tuple(item.queue_item_id for item in foreign)
        self._degraded_item_ids = ()
        self._next_maintenance_at = None
        self._state = (
            ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
            if self._foreign_item_ids
            else ManagedLocalQueueRuntimeState.READY
        )
        return self.status()

    def resolve_recovery_unknown(
        self,
        queue_item_id: str,
        *,
        previous_processes_confirmed_stopped: bool,
        requested_by: str,
        reason: str,
    ) -> QueueItem:
        """Resolve one foreign local item after trusted process containment.

        ``previous_processes_confirmed_stopped=True`` is an explicit trusted
        operator assertion that the previous runtime's entire process
        containment group is stopped. Loom does not independently verify it.
        """

        if previous_processes_confirmed_stopped is not True:
            raise QueueServiceError(
                "recovery requires previous_processes_confirmed_stopped=True"
            )
        if not isinstance(requested_by, str) or not requested_by:
            raise QueueServiceError("requested_by must be a non-empty string")
        if not isinstance(reason, str) or not reason:
            raise QueueServiceError("reason must be a non-empty string")
        self._ensure_started()
        if self._state is not ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED:
            raise QueueServiceError("managed local runtime does not require recovery")

        _current, foreign = self._classify_recovery()
        item = next(
            (
                candidate
                for candidate in foreign
                if candidate.queue_item_id == queue_item_id
            ),
            None,
        )
        if item is None:
            raise QueueServiceError("recovery requires one foreign selected-pool item")
        if item.launch_contract.adapter != self.adapter.adapter_name:
            raise QueueServiceError("recovery requires a foreign local queue item")
        if QueueItemStatus(item.status) not in {
            QueueItemStatus.CLAIMED,
            QueueItemStatus.DISPATCHED,
        }:
            raise QueueServiceError("recovery requires an active queue item")

        previous_session_id = _managed_local_session_id(item)
        recovery_evidence: dict[str, PlainData] = {
            "action": "explicit_unknown_recovery",
            "requested_by": requested_by,
            "reason": reason,
            "previous_status": QueueItemStatus(item.status).value,
            "previous_processes_confirmed_stopped": True,
        }
        if previous_session_id is not None:
            recovery_evidence["previous_session_id"] = previous_session_id
        evidence: dict[str, PlainData] = {"managed_local_recovery": recovery_evidence}
        if QueueItemStatus(item.status) is QueueItemStatus.CLAIMED:
            item = self.service.record_dispatch_handle(
                item.queue_item_id,
                DispatchHandle(
                    adapter=self.adapter.adapter_name,
                    handle_id=(
                        f"managed-local-recovery:{item.queue_item_id}:"
                        f"{item.dispatch_attempt}"
                    ),
                    dispatched_at=self._clock(),
                    dispatch_attempt=item.dispatch_attempt,
                    evidence={"managed_local_recovery": True},
                ),
                expected=item,
            )
        completed = self.service.complete_item(
            item.queue_item_id,
            status=QueueItemStatus.UNKNOWN,
            reason="managed-local-explicit-recovery",
            expected=item,
            evidence=evidence,
        )
        self._refresh_recovery_state()
        return completed

    def run_cycle(self) -> QueueCycleResult:
        """Reconcile then fill the selected pool unless health/recovery forbids it."""

        self._ensure_started()
        try:
            _current, foreign = self._classify_recovery()
        except Exception:
            self._state = ManagedLocalQueueRuntimeState.DEGRADED
            raise
        self._foreign_item_ids = tuple(item.queue_item_id for item in foreign)
        current_item_ids = {item.queue_item_id for item in _current}
        terminal_degraded = tuple(
            item_id
            for item_id in self._degraded_item_ids
            if item_id not in current_item_ids
        )
        if terminal_degraded and not self._shutdown_active:
            raise QueueServiceError(
                "managed local runtime remains degraded after terminal dispatch uncertainty"
            )
        if self._foreign_item_ids and not self._shutdown_active:
            self._state = ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
            raise QueueServiceError(
                "managed local runtime requires recovery before running a cycle"
            )
        try:
            if self._shutdown_active:
                result = self.controller.reconcile_current_session(
                    pool_name=self.pool_name
                )
            else:
                result = self.controller.run_cycle(pool_name=self.pool_name)
        except Exception:
            self._state = ManagedLocalQueueRuntimeState.DEGRADED
            raise
        self._record_cycle(result)
        return result

    def serve(
        self,
        stop_event: _StopEvent,
        *,
        poll_interval_seconds: float = 0.1,
        wait: Callable[[float], object] | None = None,
        shutdown_mode: str = "drain",
        shutdown_timeout_seconds: float | None = None,
    ) -> ManagedLocalQueueRuntimeStatus:
        """Serve until stop, then drain or cancel current-session work safely."""

        if (
            not isinstance(poll_interval_seconds, (int, float))
            or isinstance(poll_interval_seconds, bool)
            or not isfinite(poll_interval_seconds)
            or poll_interval_seconds < 0
        ):
            raise QueueServiceError(
                "poll_interval_seconds must be a finite non-negative number"
            )
        if shutdown_mode not in {"drain", "cancel"}:
            raise QueueServiceError("shutdown_mode must be 'drain' or 'cancel'")
        if shutdown_timeout_seconds is not None and (
            not isinstance(shutdown_timeout_seconds, (int, float))
            or isinstance(shutdown_timeout_seconds, bool)
            or not isfinite(shutdown_timeout_seconds)
            or shutdown_timeout_seconds < 0
        ):
            raise QueueServiceError(
                "shutdown_timeout_seconds must be a finite non-negative number or None"
            )
        if self.service.state is not QueueServiceState.RUNNING:
            self.start()
        self._ensure_started()
        waiter = stop_event.wait if wait is None else wait
        shutdown_started_at: str | None = None
        while True:
            if (
                shutdown_started_at is None
                and stop_event.is_set()
                and self._state is not ManagedLocalQueueRuntimeState.STOPPED
            ):
                shutdown_started_at = self._clock()
                self._shutdown_active = True
                self._state = (
                    ManagedLocalQueueRuntimeState.DRAINING
                    if shutdown_mode == "drain"
                    else ManagedLocalQueueRuntimeState.CANCELLING
                )
                if self._state is ManagedLocalQueueRuntimeState.CANCELLING:
                    self._cancel_current_session_items()
            if shutdown_started_at is not None and self._shutdown_timed_out(
                shutdown_started_at, shutdown_timeout_seconds
            ):
                current, foreign = self._classify_recovery()
                self._foreign_item_ids = tuple(item.queue_item_id for item in foreign)
                if current:
                    raise ManagedLocalShutdownTimeoutError(
                        tuple(item.queue_item_id for item in current)
                    )
            try:
                self.run_cycle()
            except Exception:
                # The degraded state is the observable result; a later loop gets
                # another reconciliation attempt rather than a synthetic success.
                pass
            if (
                self._state is ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
                and shutdown_started_at is None
            ):
                return self.status()
            if shutdown_started_at is not None:
                current, foreign = self._classify_recovery()
                self._foreign_item_ids = tuple(item.queue_item_id for item in foreign)
                if not current:
                    if foreign:
                        self._state = ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
                        return self.status()
                    self._state = ManagedLocalQueueRuntimeState.STOPPED
                    self._last_pool_status = self._pool_status()
                    self.service.stop()
                    return self.status()
                if self._shutdown_timed_out(
                    shutdown_started_at, shutdown_timeout_seconds
                ):
                    raise ManagedLocalShutdownTimeoutError(
                        tuple(item.queue_item_id for item in current)
                    )
            timeout = self._next_wait_seconds(poll_interval_seconds)
            timeout = self._bounded_shutdown_wait(
                timeout, shutdown_started_at, shutdown_timeout_seconds
            )
            waiter(timeout)

    def status(self) -> ManagedLocalQueueRuntimeStatus:
        """Return safe status without representing persisted leases as hardware truth."""

        pool_status = self._pool_status()
        if pool_status is not None:
            self._last_pool_status = pool_status
        elif self._last_pool_status is not None:
            pool_status = self._last_pool_status
        return ManagedLocalQueueRuntimeStatus(
            state=self._state,
            owner_id=self.owner_id,
            pool_name=self.pool_name,
            last_cycle_at=self._last_cycle_at,
            next_maintenance_at=self._next_maintenance_at,
            degraded_item_ids=self._degraded_item_ids,
            foreign_item_ids=self._foreign_item_ids,
            pool_status=pool_status,
            observation_scope=_OBSERVATION_SCOPE,
        )

    def _validate_startup(self) -> None:
        if self._pool.mode is not QueuePoolMode.MANAGED:
            raise QueueServiceError("managed local runtime requires a managed pool")
        if os.name != "posix":
            raise QueueServiceError(
                "managed local runtime requires POSIX process groups"
            )
        diagnostics = coordination_requirement_diagnostics(
            self._coordination_store.capabilities(), require_resource_leases=True
        )
        if diagnostics:
            raise QueueServiceError(
                "managed local runtime requires resource-lease coordination: "
                + ", ".join(diagnostic.code for diagnostic in diagnostics)
            )
        require_managed_pool_limits(
            self.spec,
            self._coordination_store,
            workspace_id=self._workspace_id,
            pool_names=(self.pool_name,),
        )
        for assignment in self.spec.local_assignments.get(self.pool_name, {}).values():
            for slot in assignment.slots:
                counter = self._coordination_store.read_resource_limit(
                    self._workspace_id, slot.coordination_key
                )
                if counter is None or counter.limit != 1:
                    raise QueueServiceError(
                        "static assignment slot limits do not match authority: "
                        + slot.coordination_key
                    )

    def _record_cycle(self, result: QueueCycleResult) -> None:
        self._last_cycle_at = self._clock()
        self._next_maintenance_at = result.next_maintenance_at
        degraded = tuple(
            step.item.queue_item_id
            for step in (*result.reconciliation_steps, *result.dispatch_steps)
            if step.item is not None and step.outcome in {"degraded", "unknown"}
        )
        self._degraded_item_ids = degraded
        if self._shutdown_active:
            return
        if degraded:
            self._state = ManagedLocalQueueRuntimeState.DEGRADED
        elif not self._foreign_item_ids:
            self._state = ManagedLocalQueueRuntimeState.READY

    def _pool_status(self) -> QueuePoolStatus | None:
        if self.service.state is not QueueServiceState.RUNNING:
            return None
        return build_queue_pool_status(
            self.service,
            pool_name=self.pool_name,
            adapters={self.adapter.adapter_name: self.adapter},
        )

    def _classify_recovery(
        self,
    ) -> tuple[tuple[QueueItem, ...], tuple[QueueItem, ...]]:
        """Fence this local runtime from all non-current-local recovery work."""

        classification = self.controller.classify_recovery(pool_name=self.pool_name)
        current = tuple(
            item
            for item in classification.current_items
            if item.launch_contract.adapter == self.adapter.adapter_name
        )
        foreign = (
            *classification.foreign_items,
            *(
                item
                for item in classification.current_items
                if item.launch_contract.adapter != self.adapter.adapter_name
            ),
        )
        return current, foreign

    def _ensure_started(self) -> None:
        if self.service.state is not QueueServiceState.RUNNING:
            raise QueueServiceError("managed local runtime is not started")
        if self._state is ManagedLocalQueueRuntimeState.STOPPED:
            raise QueueServiceError("managed local runtime is stopped")

    def _refresh_recovery_state(self) -> None:
        try:
            _current, foreign = self._classify_recovery()
        except Exception:
            self._state = ManagedLocalQueueRuntimeState.DEGRADED
            raise
        self._foreign_item_ids = tuple(item.queue_item_id for item in foreign)
        self._state = (
            ManagedLocalQueueRuntimeState.RECOVERY_REQUIRED
            if self._foreign_item_ids
            else ManagedLocalQueueRuntimeState.READY
        )

    def _cancel_current_session_items(self) -> None:
        current, _foreign = self._classify_recovery()
        for item in current:
            self.controller.cancel_item(
                item.queue_item_id,
                requested_by=self.owner_id,
                reason="managed-local-shutdown",
            )

    def _shutdown_timed_out(
        self, started_at: str | None, timeout_seconds: float | None
    ) -> bool:
        if started_at is None or timeout_seconds is None:
            return False
        elapsed = (
            parse_timestamp(self._clock()) - parse_timestamp(started_at)
        ).total_seconds()
        return elapsed >= timeout_seconds

    def _bounded_shutdown_wait(
        self,
        wait_seconds: float,
        started_at: str | None,
        timeout_seconds: float | None,
    ) -> float:
        if started_at is None or timeout_seconds is None:
            return wait_seconds
        elapsed = (
            parse_timestamp(self._clock()) - parse_timestamp(started_at)
        ).total_seconds()
        return min(wait_seconds, max(0.0, timeout_seconds - elapsed))

    def _next_wait_seconds(self, poll_interval_seconds: float) -> float:
        if self._next_maintenance_at is None:
            return poll_interval_seconds
        seconds = (
            parse_timestamp(self._next_maintenance_at) - parse_timestamp(self._clock())
        ).total_seconds()
        return min(poll_interval_seconds, max(0.0, seconds))


def _select_pool(spec: QueueServiceSpec, pool_name: str | None) -> QueuePool:
    selected_name = pool_name or spec.controller.default_pool_name
    if selected_name is None:
        if len(spec.pools) != 1:
            raise QueueServiceError(
                "managed local runtime requires one selected pool_name"
            )
        return spec.pools[0]
    for pool in spec.pools:
        if pool.pool_name == selected_name:
            return pool
    raise QueueServiceError(f"unknown pool: {selected_name}")


_OBSERVATION_SCOPE: Mapping[str, str] = MappingProxyType(
    {
        "runtime_health": "same_process",
        "queue_facts": "persisted",
        "process": "same_session_or_unavailable",
        "hardware_and_lease_liveness": "not_observed",
    }
)


def _managed_local_session_id(item: QueueItem) -> str | None:
    if item.dispatch_handle is None:
        return None
    managed = item.dispatch_handle.evidence.get("managed_local")
    if not isinstance(managed, Mapping):
        return None
    session_id = managed.get("session_id")
    return session_id if isinstance(session_id, str) and session_id else None


__all__ = [
    "ManagedLocalQueueRuntime",
    "ManagedLocalShutdownTimeoutError",
    "ManagedLocalQueueRuntimeState",
    "ManagedLocalQueueRuntimeStatus",
]
