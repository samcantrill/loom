"""Capability-narrow authority contract used by coordinator execution.

This module deliberately owns only the structural contract. Concrete embedded
and authenticated adapters live with pipeline stores, so queue execution never
constructs a database implementation or gains a generic repository view.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores.authority import (
    CancellationEpochReceipt,
    LocalDaemonAuthority,
    PreparedAttemptExecutionAuthority,
    StatusTransition,
)
from loom.pipeline.stores.read_models import (
    AuthoritativeRunSnapshot,
    BackendRevision,
    LifecycleReason,
)
from loom.pipeline.stores.run_store import RunReliabilityStore
from loom.pipeline.transition_policy import TransitionIntent


@runtime_checkable
class CoordinatorAuthorityStore(
    PreparedAttemptExecutionAuthority,
    LocalDaemonAuthority,
    RunReliabilityStore,
    Protocol,
):
    """Exact authority capabilities reached by production coordination.

    The protocol intentionally excludes discovery, schema management, leases,
    arbitrary repository access, and database construction.
    """

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot: ...

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition: ...

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition: ...

    def read_cancellation_epoch_receipt(
        self, run_uri: str, operation_id: str
    ) -> CancellationEpochReceipt | None: ...


CoordinatorAuthorityFactory = Callable[[str], CoordinatorAuthorityStore]


__all__ = [
    "CoordinatorAuthorityFactory",
    "CoordinatorAuthorityStore",
]
