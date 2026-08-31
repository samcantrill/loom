"""Public queue records and repository APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._sqlite import QUEUE_DB_SCHEMA_VERSION, SQLiteQueueRepository
from .client import QueueClient

if TYPE_CHECKING:
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile
    from ._managed_local import (
        AgentResourceProvider,
        ClaimCommand,
        ClaimOutcome,
        ClaimResult,
        CpuResourceProvider,
        MemoryResourceProvider,
        ObserveRequest,
        ObserveResult,
    )
    from ._remote_stage_execution import GpuDeviceDescriptor
    from .coordinator_authority import (
        CoordinatorAuthorityFactory,
        CoordinatorAuthorityStore,
    )
    from .local_daemon import (
        AdmissionNotFoundError,
        AdmissionPage,
        AgentPage,
        AgentProjection,
        AdmissionWaitKind,
        AdmissionWaitResult,
        AgentControl,
        CoordinatorSchedulingReload,
        LocalDaemon,
        LocalDaemonAdmission,
        LocalDaemonAdmissionDetail,
        LocalDaemonAdmissionRequest,
        LocalDaemonAdmissionState,
        LocalDaemonConfig,
        LocalDaemonSchedulingComponents,
        ConfiguredGpuDevice,
        DaemonStatus,
        LocalDaemonPrincipal,
        LocalDaemonRole,
        LocalDaemonOperation,
        OperationWaitKind,
        OperationWaitResult,
        ManagedRecoveryTarget,
        RecoverUnknownAssignment,
        SessionReplacementRequest,
        SlurmRecoveryTarget,
        TimeRecoveryReceipt,
        TimeRecoveryRequest,
    )
    from .local_daemon_transport import (
        LocalDaemonSocketClient,
        LocalDaemonSocketServer,
    )
    from .local_daemon_runtime import prepare_managed_local_runtime_record
    from .managed_local_preparation import (
        ManagedLocalPreparationReceipt,
        prepare_managed_local_run,
    )
    from .agent_sessions import LocalOwnerOperatorPolicy
    from loom.pipeline.orchestration import ExecutionRequirement
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
    QueueForegroundDriveResult,
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
    QueueEnqueueDisposition,
    QueueEnqueueReceipt,
    QueueItem,
    QueueItemStatus,
    QueuePool,
    QueuePoolMode,
    QueueRecoveryRecord,
    RunIntent,
    validate_one_queue_per_pool,
)
from .repository import QueueItemPage, QueuePoolSnapshot, QueueRepository
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
        "AdmissionNotFoundError",
        "AgentControl",
        "CoordinatorSchedulingReload",
        "LocalDaemonAdmission",
        "LocalDaemonAdmissionDetail",
        "LocalDaemonAdmissionRequest",
        "LocalDaemonAdmissionState",
        "LocalDaemonConfig",
        "LocalDaemonSchedulingComponents",
        "ConfiguredGpuDevice",
        "LocalDaemonPrincipal",
        "LocalDaemonRole",
        "LocalDaemonSocketClient",
        "LocalDaemonSocketServer",
        "DaemonStatus",
        "AdmissionPage",
        "AgentPage",
        "AgentProjection",
        "AdmissionWaitKind",
        "AdmissionWaitResult",
        "LocalDaemonOperation",
        "OperationWaitKind",
        "OperationWaitResult",
        "ManagedRecoveryTarget",
        "RecoverUnknownAssignment",
        "SessionReplacementRequest",
        "ResidentWorkerLaunchProfile",
        "SlurmRecoveryTarget",
        "TimeRecoveryReceipt",
        "TimeRecoveryRequest",
    }
)

_MANAGED_RESOURCE_EXPORTS = frozenset(
    {
        "AgentResourceProvider",
        "ClaimCommand",
        "ClaimOutcome",
        "ClaimResult",
        "CpuResourceProvider",
        "MemoryResourceProvider",
        "ObserveRequest",
        "ObserveResult",
    }
)


def __getattr__(name: str) -> object:
    if name in {
        "CoordinatorAuthorityFactory",
        "CoordinatorAuthorityStore",
    }:
        from . import coordinator_authority

        return getattr(coordinator_authority, name)
    if name == "ResidentWorkerLaunchProfile":
        from ._agent_process_supervisor import ResidentWorkerLaunchProfile

        return ResidentWorkerLaunchProfile
    if name in _MANAGED_RESOURCE_EXPORTS:
        from . import _managed_local

        return getattr(_managed_local, name)
    if name == "LocalOwnerOperatorPolicy":
        from .agent_sessions import LocalOwnerOperatorPolicy

        return LocalOwnerOperatorPolicy
    if name in _LOCAL_DAEMON_EXPORTS:
        if name in {"LocalDaemonSocketClient", "LocalDaemonSocketServer"}:
            from . import local_daemon_transport

            return getattr(local_daemon_transport, name)
        from . import local_daemon

        return getattr(local_daemon, name)
    if name == "prepare_managed_local_runtime_record":
        from .local_daemon_runtime import prepare_managed_local_runtime_record

        return prepare_managed_local_runtime_record
    if name in {"ManagedLocalPreparationReceipt", "prepare_managed_local_run"}:
        from . import managed_local_preparation

        return getattr(managed_local_preparation, name)
    if name == "ExecutionRequirement":
        from loom.pipeline.orchestration import ExecutionRequirement

        return ExecutionRequirement
    if name == "GpuDeviceDescriptor":
        from ._remote_stage_execution import GpuDeviceDescriptor

        return GpuDeviceDescriptor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "QUEUE_CONFIG_SCHEMA_VERSION",
    "QUEUE_DB_SCHEMA_VERSION",
    "QUEUE_RECORD_SCHEMA_VERSION",
    "CancellationRecord",
    "AgentResourceProvider",
    "ClaimCommand",
    "ClaimOutcome",
    "ClaimResult",
    "CpuResourceProvider",
    "DispatchHandle",
    "ExecutionRequirement",
    "FakeQueueDispatchAdapter",
    "GpuDeviceDescriptor",
    "LaunchContract",
    "LocalDaemon",
    "AdmissionNotFoundError",
    "AgentControl",
    "CoordinatorSchedulingReload",
    "CoordinatorAuthorityFactory",
    "CoordinatorAuthorityStore",
    "LocalDaemonAdmission",
    "LocalDaemonAdmissionDetail",
    "LocalDaemonAdmissionRequest",
    "LocalDaemonAdmissionState",
    "LocalDaemonConfig",
    "LocalDaemonSchedulingComponents",
    "ConfiguredGpuDevice",
    "LocalDaemonPrincipal",
    "LocalDaemonRole",
    "LocalDaemonSocketClient",
    "LocalDaemonSocketServer",
    "DaemonStatus",
    "AdmissionPage",
    "AgentPage",
    "AgentProjection",
    "AdmissionWaitKind",
    "AdmissionWaitResult",
    "LocalDaemonOperation",
    "OperationWaitKind",
    "OperationWaitResult",
    "ManagedRecoveryTarget",
    "MemoryResourceProvider",
    "ObserveRequest",
    "ObserveResult",
    "RecoverUnknownAssignment",
    "ResidentWorkerLaunchProfile",
    "SessionReplacementRequest",
    "SlurmRecoveryTarget",
    "TimeRecoveryReceipt",
    "TimeRecoveryRequest",
    "LocalOwnerOperatorPolicy",
    "prepare_managed_local_runtime_record",
    "ManagedLocalPreparationReceipt",
    "prepare_managed_local_run",
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
    "QueueForegroundDriveResult",
    "QueueEnqueueRequest",
    "QueueEnqueueDisposition",
    "QueueEnqueueReceipt",
    "QueueError",
    "QueueItemInspection",
    "QueueItem",
    "QueueItemPage",
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
