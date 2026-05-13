"""Public queue records and repository APIs."""

from __future__ import annotations

from ._sqlite import QUEUE_DB_SCHEMA_VERSION, SQLiteQueueRepository
from .errors import (
    QueueConflictError,
    QueueError,
    QueueSchemaError,
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
from .repository import QueueClaimResult, QueueRepository

__all__ = [
    "QUEUE_DB_SCHEMA_VERSION",
    "QUEUE_RECORD_SCHEMA_VERSION",
    "CancellationRecord",
    "DispatchHandle",
    "LaunchContract",
    "QueueAuditEvent",
    "QueueClaim",
    "QueueClaimResult",
    "QueueConflictError",
    "QueueDefinition",
    "QueueError",
    "QueueItem",
    "QueueItemStatus",
    "QueuePool",
    "QueuePoolMode",
    "QueueRecoveryRecord",
    "QueueRepository",
    "QueueSchemaError",
    "QueueStorageError",
    "QueueValidationError",
    "RunIntent",
    "SQLiteQueueRepository",
    "validate_one_queue_per_pool",
]
