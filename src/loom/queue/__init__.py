"""Public queue records and repository APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._sqlite import QUEUE_DB_SCHEMA_VERSION, SQLiteQueueRepository
from .client import QueueClient
if TYPE_CHECKING:
    from .local_daemon import (
        LocalDaemon,
        LocalDaemonAdmission,
        LocalDaemonAdmissionRequest,
        LocalDaemonAdmissionState,
        LocalDaemonConfig,
        LocalDaemonPrincipal,
        LocalDaemonRole,
        LocalDaemonStatus,
    )
    from .local_daemon_transport import (
        LocalDaemonSocketClient,
        LocalDaemonSocketServer,
    )
    from .local_daemon_runtime import prepare_managed_local_runtime_record
from .config import (
    QUEUE_CONFIG_SCHEMA_VERSION,
    QueueControllerSpec,
    QueueServiceSpec,
    compose_queue_spec,
    load_queue_spec,
    normalize_queue_spec,
    queue_spec_from_composed_config,
)
from .assignments import (
    LaunchEnvironmentBindings,
    NoOpResourceAssignmentProvider,
    ResourceAssignment,
    ResourceAssignmentDecision,
    ResourceAssignmentDisposition,
    ResourceAssignmentProvider,
    ResourceAssignmentRequest,
    StaticSlotAssignmentProvider,
)
from .controller import (
    FakeQueueDispatchAdapter,
    QueueCancellableDispatchAdapter,
    QueueController,
    QueueCycleResult,
    QueueControllerStep,
    QueueDispatchAdapter,
    QueueDispatchCancellation,
    QueueDispatchDisposition,
    QueueDispatchInspection,
    QueueDispatchNonStartCause,
    QueueDispatchResult,
    QueueDrainResult,
    QueueInspectableDispatchAdapter,
    QueuePreStartCleanupStatus,
)
from .errors import (
    QueueConfigError,
    QueueConflictError,
    QueueError,
    QueueSchemaError,
    QueueServiceError,
    QueueServiceStateError,
    QueueStorageError,
    QueueValidationError,
)
from .models import (
    QUEUE_RECORD_SCHEMA_VERSION,
    CancellationRecord,
    DispatchHandle,
    LaunchContract,
    QueueAuditEvent,
    QueueClaim,
    QueueDefinition,
    QueueItem,
    QueueItemStatus,
    QueuePool,
    QueuePoolMode,
    QueueRecoveryRecord,
    RunIntent,
    validate_one_queue_per_pool,
)
from .repository import QueuePoolSnapshot, QueueRepository
from .service import (
    QueueEnqueueRequest,
    QueueItemInspection,
    QueueService,
    QueueServiceState,
    QueueServiceStatus,
)
from .selection import (
    QueueSelectionCandidate,
    QueueSelectionContext,
    QueueSelectionDecision,
    QueueSelectionDisposition,
    QueueSelectionPolicy,
)


_LOCAL_DAEMON_EXPORTS = frozenset(
    {
        "LocalDaemon",
        "LocalDaemonAdmission",
        "LocalDaemonAdmissionRequest",
        "LocalDaemonAdmissionState",
        "LocalDaemonConfig",
        "LocalDaemonPrincipal",
        "LocalDaemonRole",
        "LocalDaemonSocketClient",
        "LocalDaemonSocketServer",
        "LocalDaemonStatus",
    }
)


def __getattr__(name: str) -> object:
    if name in _LOCAL_DAEMON_EXPORTS:
        if name in {"LocalDaemonSocketClient", "LocalDaemonSocketServer"}:
            from . import local_daemon_transport

            return getattr(local_daemon_transport, name)
        from . import local_daemon

        return getattr(local_daemon, name)
    if name == "prepare_managed_local_runtime_record":
        from .local_daemon_runtime import prepare_managed_local_runtime_record

        return prepare_managed_local_runtime_record
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "QUEUE_CONFIG_SCHEMA_VERSION",
    "QUEUE_DB_SCHEMA_VERSION",
    "QUEUE_RECORD_SCHEMA_VERSION",
    "CancellationRecord",
    "DispatchHandle",
    "FakeQueueDispatchAdapter",
    "LaunchContract",
    "LocalDaemon",
    "LocalDaemonAdmission",
    "LocalDaemonAdmissionRequest",
    "LocalDaemonAdmissionState",
    "LocalDaemonConfig",
    "LocalDaemonPrincipal",
    "LocalDaemonRole",
    "LocalDaemonSocketClient",
    "LocalDaemonSocketServer",
    "LocalDaemonStatus",
    "prepare_managed_local_runtime_record",
    "LaunchEnvironmentBindings",
    "NoOpResourceAssignmentProvider",
    "ResourceAssignment",
    "ResourceAssignmentDecision",
    "ResourceAssignmentDisposition",
    "ResourceAssignmentProvider",
    "ResourceAssignmentRequest",
    "QueueAuditEvent",
    "QueueCancellableDispatchAdapter",
    "QueueClaim",
    "QueueClient",
    "QueueConfigError",
    "QueueController",
    "QueueCycleResult",
    "QueueControllerSpec",
    "QueueControllerStep",
    "QueueDispatchAdapter",
    "QueueConflictError",
    "QueueDefinition",
    "QueueDispatchCancellation",
    "QueueDispatchDisposition",
    "QueueDispatchInspection",
    "QueueDispatchNonStartCause",
    "QueueDispatchResult",
    "QueueDrainResult",
    "QueueEnqueueRequest",
    "QueueError",
    "QueueItemInspection",
    "QueueItem",
    "QueueItemStatus",
    "QueuePool",
    "QueuePoolSnapshot",
    "QueuePoolMode",
    "QueuePreStartCleanupStatus",
    "QueueRecoveryRecord",
    "QueueRepository",
    "QueueInspectableDispatchAdapter",
    "QueueSchemaError",
    "QueueService",
    "QueueServiceError",
    "QueueServiceSpec",
    "QueueServiceState",
    "QueueServiceStateError",
    "QueueServiceStatus",
    "QueueSelectionCandidate",
    "QueueSelectionContext",
    "QueueSelectionDecision",
    "QueueSelectionDisposition",
    "QueueSelectionPolicy",
    "QueueStorageError",
    "QueueValidationError",
    "RunIntent",
    "SQLiteQueueRepository",
    "StaticSlotAssignmentProvider",
    "compose_queue_spec",
    "load_queue_spec",
    "normalize_queue_spec",
    "queue_spec_from_composed_config",
    "validate_one_queue_per_pool",
]
