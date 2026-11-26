"""Persistent managed-execution coordinator with a protected local agent.

The daemon owns admission, process identity, and the production composition that
connects persisted run plans to the Stage 29 orchestrator and local assignment
saga. Clients provide only a queue identity and run URI.
"""

from __future__ import annotations

from loom._sqlite_policy import SQLitePolicy, initialize_database
from loom.pipeline.stores.atomic import atomic_write_text, _fsync_path_strict
from ._local_daemon_config import (
    _default_admission_priority as _default_admission_priority,
    LocalDaemonRole as LocalDaemonRole,
    LocalDaemonPrincipal as LocalDaemonPrincipal,
    ConfiguredGpuDevice as ConfiguredGpuDevice,
    LocalDaemonSchedulingComponents as LocalDaemonSchedulingComponents,
    _default_scheduling_components as _default_scheduling_components,
    LocalDaemonConfig as LocalDaemonConfig,
)
from ._storage_policy import StoragePolicy

from .gpu.occupancy import GpuOccupancyPolicy
from ._managed_local import (
    ResourceAvailabilityStatus,
    ObserveRequest,
    _CompositeAgentResourceProvider,
)
from .run import _public_operation_id

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, replace
from enum import StrEnum
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from threading import BoundedSemaphore, Event, RLock, Thread, current_thread
import time
from typing import TYPE_CHECKING, Any, Iterator, cast
from uuid import uuid4

from loom._sqlite_inspection import inspect_sqlite_database
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from ._queue_listing import QueueSelection, queue_page
from loom.timestamps import parse_timestamp, utc_timestamp
from .operations import OperatorObservation

from .agent_sessions import (
    AgentControl,
    AgentOffer,
    AgentPolicyConfig,
    AgentSessionView,
    SessionReplacementRequest,
    ensure_agent_lookup_indexes,
    invalidate_current_offers,
    initialize_agent_session_schema,
    replace_agent_session,
    validate_agent_session_schema,
)
from ._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
)
from ._managed_local import AgentResourceProvider
from .errors import QueueConflictError, QueueServiceError, QueueStorageError, _AcceptedTimeError
from ._admission_scan import LEGACY_CANCELLED, AdmissionScan, SchedulingAdmissions, ensure_scan_index, ensure_retry_index
from ._service_signals import _ChangeConnection, _ChangeSignal, _KeyedWaiters, _ServiceSignal, write_status
from ._recovery_retry import _RecoveryRetry
from ._context_preparation import PendingContext
from ._run_observations import RunObservation, RunObservationPending

if TYPE_CHECKING:
    from ._owner_journals import SlurmStorageFacts, StorageObserver
    from ._preparation_operations import PreparationCallbacks
    from .local_daemon_execution import (
        LocalDaemonExecution,
        LocalDaemonExecutionOutcome,
    )
    from .preparation import PrepareRunRequest
    from .run import RunRequest


_COORDINATOR_SCHEMA_VERSION = 20
_AGENT_SCHEMA_VERSION = 12
# Outbound session roots and coordinator roots independently reject old forms.
_LOCAL_DAEMON_SCHEMA_VERSION = _AGENT_SCHEMA_VERSION
_MIN_RUN_PRIORITY = -1_000_000
_MAX_RUN_PRIORITY = 1_000_000
_MAX_ADMISSION_PAGE_SIZE = 100
_DEPLOYMENT_BINDING_FILE = "deployment-binding.json"
_LOGGER = logging.getLogger(__name__)


class LocalDaemonAdmissionState(StrEnum):
    """Coordinator-owned state, kept separate from authority lifecycle truth."""

    PENDING_AUTHORITY = "PENDING_AUTHORITY"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CoordinatorSchedulingReload:
    """Inert request to read and install protected coordinator-local config.

    Policy transition modes carry the exact maintenance owner, intent digest
    and gate revision. ``gpu_policy_contraction`` permits only nonempty GPU
    inventory subsets while preserving identities and other configuration.
    ``gpu_policy_expansion`` permits strict supersets with unchanged existing
    device descriptions under the same settled maintenance guards.
    """

    operation_id: str
    expected_scheduling_epoch: str
    reason: str
    retirement: Mapping[str, PlainData] | None = None
    container_policy_addition: Mapping[str, PlainData] | None = None
    publication_budget_increase: Mapping[str, PlainData] | None = None
    gpu_policy_contraction: Mapping[str, PlainData] | None = None
    gpu_policy_expansion: Mapping[str, PlainData] | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "operation_id"),
            (self.expected_scheduling_epoch, "expected_scheduling_epoch"),
        ):
            if not isinstance(value, str) or not value or len(value) > 160:
                raise QueueServiceError(f"{name} must be a bounded non-empty string")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 512
        ):
            raise QueueServiceError(
                "scheduling reload reason must be 1..512 characters"
            )

        modes = (self.retirement, self.container_policy_addition, self.publication_budget_increase, self.gpu_policy_contraction, self.gpu_policy_expansion)
        if sum(value is not None for value in modes) > 1:
            raise QueueServiceError("coordinator policy transition modes are mutually exclusive")
        for name in ("retirement", "container_policy_addition", "publication_budget_increase", "gpu_policy_contraction", "gpu_policy_expansion"):
            value = getattr(self, name)
            if value is None:
                continue
            if (not isinstance(value, Mapping)
                or set(value) != {"maintenance_id", "maintenance_intent_digest", "expected_gate_revision"}
                or any(not isinstance(value[key], str) or not value[key] or len(value[key]) > 512
                       for key in ("maintenance_id", "maintenance_intent_digest"))
                or type(value["expected_gate_revision"]) is not int
                or value["expected_gate_revision"] < 0):
                raise QueueServiceError("coordinator retirement binding is invalid")
            object.__setattr__(self, name, freeze_plain_data(value))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "expected_scheduling_epoch": self.expected_scheduling_epoch,
            "reason": self.reason,
            **({"retirement": thaw_plain_data(self.retirement)} if self.retirement is not None else {}),
            **({"container_policy_addition": thaw_plain_data(self.container_policy_addition)}
               if self.container_policy_addition is not None else {}),
            **({"publication_budget_increase": thaw_plain_data(self.publication_budget_increase)}
               if self.publication_budget_increase is not None else {}),
            **({"gpu_policy_contraction": thaw_plain_data(self.gpu_policy_contraction)}
               if self.gpu_policy_contraction is not None else {}),
            **({"gpu_policy_expansion": thaw_plain_data(self.gpu_policy_expansion)}
               if self.gpu_policy_expansion is not None else {}),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "CoordinatorSchedulingReload":
        _exact_fields(
            data,
            {"operation_id", "expected_scheduling_epoch", "reason"} | ({"retirement"} if "retirement" in data else set())
            | ({"container_policy_addition"} if "container_policy_addition" in data else set())
            | ({"publication_budget_increase"} if "publication_budget_increase" in data else set())
            | ({"gpu_policy_contraction"} if "gpu_policy_contraction" in data else set())
            | ({"gpu_policy_expansion"} if "gpu_policy_expansion" in data else set()),
            "coordinator scheduling reload",
        )
        return cls(
            operation_id=_required_string(data, "operation_id"),
            expected_scheduling_epoch=_required_string(
                data, "expected_scheduling_epoch"
            ),
            reason=_required_string(data, "reason"),
            retirement=cast(Mapping[str, PlainData] | None, data.get("retirement")),
            container_policy_addition=cast(Mapping[str, PlainData] | None, data.get("container_policy_addition")),
            publication_budget_increase=cast(Mapping[str, PlainData] | None, data.get("publication_budget_increase")),
            gpu_policy_contraction=cast(Mapping[str, PlainData] | None, data.get("gpu_policy_contraction")),
            gpu_policy_expansion=cast(Mapping[str, PlainData] | None, data.get("gpu_policy_expansion")),
        )


@dataclass(frozen=True, slots=True)
class TimeRecoveryRequest:
    """Operator-authorized recovery of one exact degraded clock revision."""

    operation_id: str
    expected_time_revision: int
    expected_coordinator_epoch: str
    reason: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "operation_id"),
            (self.expected_coordinator_epoch, "expected_coordinator_epoch"),
        ):
            if not isinstance(value, str) or not value or len(value) > 160:
                raise QueueServiceError(f"{name} must be a bounded non-empty string")
        if (
            isinstance(self.expected_time_revision, bool)
            or not isinstance(self.expected_time_revision, int)
            or self.expected_time_revision < 1
        ):
            raise QueueServiceError("expected time revision must be positive")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 512
        ):
            raise QueueServiceError("time recovery reason must be 1..512 characters")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "expected_time_revision": self.expected_time_revision,
            "expected_coordinator_epoch": self.expected_coordinator_epoch,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TimeRecoveryRequest":
        _exact_fields(
            data,
            {
                "operation_id",
                "expected_time_revision",
                "expected_coordinator_epoch",
                "reason",
            },
            "time recovery request",
        )
        return cls(
            operation_id=_required_string(data, "operation_id"),
            expected_time_revision=_required_int(data, "expected_time_revision"),
            expected_coordinator_epoch=_required_string(
                data, "expected_coordinator_epoch"
            ),
            reason=_required_string(data, "reason"),
        )


@dataclass(frozen=True, slots=True)
class TimeRecoveryReceipt:
    operation_id: str
    request_digest: str
    recovered_at: str
    previous_coordinator_epoch: str
    coordinator_epoch: str
    time_revision: int

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "request_digest": self.request_digest,
            "recovered_at": self.recovered_at,
            "previous_coordinator_epoch": self.previous_coordinator_epoch,
            "coordinator_epoch": self.coordinator_epoch,
            "time_revision": self.time_revision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TimeRecoveryReceipt":
        _exact_fields(
            data,
            {
                "operation_id",
                "request_digest",
                "recovered_at",
                "previous_coordinator_epoch",
                "coordinator_epoch",
                "time_revision",
            },
            "time recovery receipt",
        )
        receipt = cls(
            operation_id=_required_string(data, "operation_id"),
            request_digest=_required_string(data, "request_digest"),
            recovered_at=_required_string(data, "recovered_at"),
            previous_coordinator_epoch=_required_string(
                data, "previous_coordinator_epoch"
            ),
            coordinator_epoch=_required_string(data, "coordinator_epoch"),
            time_revision=_required_int(data, "time_revision"),
        )
        parse_timestamp(receipt.recovered_at)
        return receipt


@dataclass(frozen=True, slots=True)
class ManagedRecoveryTarget:
    agent_id: str
    session_id: str

    def __post_init__(self) -> None:
        for value in (self.agent_id, self.session_id):
            _required_string({"value": value}, "value")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": "managed",
            "agent_id": self.agent_id,
            "session_id": self.session_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ManagedRecoveryTarget":
        _exact_fields(
            data, {"kind", "agent_id", "session_id"}, "managed recovery target"
        )
        if data.get("kind") != "managed":
            raise QueueServiceError("managed recovery target kind is invalid")
        return cls(
            _required_string(data, "agent_id"), _required_string(data, "session_id")
        )


@dataclass(frozen=True, slots=True)
class SlurmRecoveryTarget:
    profile_id: str
    submission_operation_id: str
    cluster_id: str
    job_id: str
    bootstrap_incarnation_id: str | None

    def __post_init__(self) -> None:
        for value in (
            self.profile_id,
            self.submission_operation_id,
            self.cluster_id,
            self.job_id,
        ):
            _required_string({"value": value}, "value")
        if self.bootstrap_incarnation_id is not None:
            _required_string({"value": self.bootstrap_incarnation_id}, "value")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": "slurm",
            "profile_id": self.profile_id,
            "submission_operation_id": self.submission_operation_id,
            "cluster_id": self.cluster_id,
            "job_id": self.job_id,
            "bootstrap_incarnation_id": self.bootstrap_incarnation_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SlurmRecoveryTarget":
        _exact_fields(
            data,
            {
                "kind",
                "profile_id",
                "submission_operation_id",
                "cluster_id",
                "job_id",
                "bootstrap_incarnation_id",
            },
            "SLURM recovery target",
        )
        if data.get("kind") != "slurm":
            raise QueueServiceError("SLURM recovery target kind is invalid")
        raw_incarnation = data.get("bootstrap_incarnation_id")
        if raw_incarnation is not None and not isinstance(raw_incarnation, str):
            raise QueueServiceError("SLURM recovery bootstrap incarnation is invalid")
        return cls(
            _required_string(data, "profile_id"),
            _required_string(data, "submission_operation_id"),
            _required_string(data, "cluster_id"),
            _required_string(data, "job_id"),
            raw_incarnation,
        )


@dataclass(frozen=True, slots=True)
class RecoverUnknownAssignment:
    """Closed, replay-safe privileged recovery request.

    Target-owned evidence is intentionally absent: a caller can request a
    close but cannot assert that a process was contained.
    """

    recovery_id: str
    run_uri: str
    stage_name: str
    attempt: int
    stage_work_id: str
    assignment_id: str
    process_execution_id: str
    execution_fence: str
    target: ManagedRecoveryTarget | SlurmRecoveryTarget
    expected_state_version: int
    requested_outcome: str
    consider_retry: bool
    reason: str

    def __post_init__(self) -> None:
        for value in (
            self.recovery_id,
            self.run_uri,
            self.stage_name,
            self.stage_work_id,
            self.assignment_id,
            self.process_execution_id,
            self.execution_fence,
        ):
            _required_string({"value": value}, "value")
        if isinstance(self.attempt, bool) or self.attempt < 1:
            raise QueueServiceError("recovery attempt is invalid")
        if not isinstance(self.target, ManagedRecoveryTarget | SlurmRecoveryTarget):
            raise QueueServiceError("recovery target is invalid")
        if (
            isinstance(self.expected_state_version, bool)
            or self.expected_state_version < 0
        ):
            raise QueueServiceError("recovery expected state version is invalid")
        if self.requested_outcome not in {"failed", "cancelled"}:
            raise QueueServiceError("recovery requested outcome is invalid")
        if not isinstance(self.consider_retry, bool):
            raise QueueServiceError("recovery retry decision is invalid")
        if (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > 512
        ):
            raise QueueServiceError("recovery reason is invalid")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "recovery_id": self.recovery_id,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "stage_work_id": self.stage_work_id,
            "assignment_id": self.assignment_id,
            "process_execution_id": self.process_execution_id,
            "execution_fence": self.execution_fence,
            "target": self.target.to_dict(),
            "expected_state_version": self.expected_state_version,
            "requested_outcome": self.requested_outcome,
            "consider_retry": self.consider_retry,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "RecoverUnknownAssignment":
        _exact_fields(
            data,
            {
                "recovery_id",
                "run_uri",
                "stage_name",
                "attempt",
                "stage_work_id",
                "assignment_id",
                "process_execution_id",
                "execution_fence",
                "target",
                "expected_state_version",
                "requested_outcome",
                "consider_retry",
                "reason",
            },
            "recovery request",
        )
        target = data.get("target")
        if not isinstance(target, Mapping):
            raise QueueServiceError("recovery target is invalid")
        kind = target.get("kind")
        if kind == "managed":
            parsed_target: ManagedRecoveryTarget | SlurmRecoveryTarget = (
                ManagedRecoveryTarget.from_dict(target)
            )
        elif kind == "slurm":
            parsed_target = SlurmRecoveryTarget.from_dict(target)
        else:
            raise QueueServiceError("recovery target kind is invalid")
        return cls(
            recovery_id=_required_string(data, "recovery_id"),
            run_uri=_required_string(data, "run_uri"),
            stage_name=_required_string(data, "stage_name"),
            attempt=_required_int(data, "attempt"),
            stage_work_id=_required_string(data, "stage_work_id"),
            assignment_id=_required_string(data, "assignment_id"),
            process_execution_id=_required_string(data, "process_execution_id"),
            execution_fence=_required_string(data, "execution_fence"),
            target=parsed_target,
            expected_state_version=_required_int(data, "expected_state_version"),
            requested_outcome=_required_string(data, "requested_outcome"),
            consider_retry=_required_bool(data, "consider_retry"),
            reason=_required_string(data, "reason"),
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonAdmissionRequest:
    """Submit prepared work, or explicitly retry an observed failed revision.

    Ordinary replay only observes the retained admission. ``retry_failed_revision``
    authorizes one continuation of that FAILED admission through its existing
    coordinator and intent; replay of the same revision cannot authorize another.
    """

    queue_item_id: str
    run_uri: str
    retry_failed_revision: int | None = None

    resume_cancelled_revision: int | None = None

    @property
    def continuation_revision(self) -> int | None:
        return self.retry_failed_revision or self.resume_cancelled_revision

    def __post_init__(self) -> None:
        for value, name in (
            (self.queue_item_id, "queue_item_id"),
            (self.run_uri, "run_uri"),
        ):
            if not isinstance(value, str) or not value:
                raise QueueServiceError(f"{name} must be a non-empty string")
        if self.retry_failed_revision is not None and (
            isinstance(self.retry_failed_revision, bool)
            or not isinstance(self.retry_failed_revision, int)
            or self.retry_failed_revision < 1
        ):
            raise QueueServiceError("retry failed revision must be a positive integer")

        if self.resume_cancelled_revision is not None and (
            type(self.resume_cancelled_revision) is not int
            or self.resume_cancelled_revision < 1
            or self.retry_failed_revision is not None
        ):
            raise QueueServiceError("resume requires one positive cancelled revision")

    def to_dict(self) -> dict[str, PlainData]:
        result: dict[str, PlainData] = {
            "queue_item_id": self.queue_item_id,
            "run_uri": self.run_uri,
        }
        if self.retry_failed_revision is not None:
            result["retry_failed_revision"] = self.retry_failed_revision
        if self.resume_cancelled_revision is not None:
            result["resume_cancelled_revision"] = self.resume_cancelled_revision
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonAdmissionRequest":
        fields = {"queue_item_id", "run_uri"}
        if "retry_failed_revision" in data:
            fields.add("retry_failed_revision")
        if "resume_cancelled_revision" in data:
            fields.add("resume_cancelled_revision")
        _exact_fields(data, fields, "admission request")
        return cls(
            queue_item_id=_required_string(data, "queue_item_id"),
            run_uri=_required_string(data, "run_uri"),
            resume_cancelled_revision=(
                _required_int(data, "resume_cancelled_revision")
                if "resume_cancelled_revision" in data else None
            ),
            retry_failed_revision=(
                _required_int(data, "retry_failed_revision")
                if "retry_failed_revision" in data
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonAdmission:
    admission_id: str
    queue_item_id: str
    coordinator_id: str
    run_uri: str
    intent_digest: str
    execution_owner: str
    state: LocalDaemonAdmissionState
    accepted_at: str
    authority_operation_id: str
    revision: int = 1
    run_priority: int = 0
    enqueue_sequence: int = 0
    cancellation_operation_id: str | None = None
    cancellation_principal_id: str | None = None
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "admission_id": self.admission_id,
            "queue_item_id": self.queue_item_id,
            "coordinator_id": self.coordinator_id,
            "run_uri": self.run_uri,
            "intent_digest": self.intent_digest,
            "execution_owner": self.execution_owner,
            "state": self.state.value,
            "accepted_at": self.accepted_at,
            "authority_operation_id": self.authority_operation_id,
            "revision": self.revision,
            "run_priority": self.run_priority,
            "enqueue_sequence": self.enqueue_sequence,
            "cancellation_operation_id": self.cancellation_operation_id,
            "cancellation_principal_id": self.cancellation_principal_id,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonAdmission":
        _exact_fields(
            data,
            {
                "admission_id",
                "queue_item_id",
                "coordinator_id",
                "run_uri",
                "intent_digest",
                "execution_owner",
                "state",
                "accepted_at",
                "authority_operation_id",
                "revision",
                "run_priority",
                "enqueue_sequence",
                "cancellation_operation_id",
                "cancellation_principal_id",
                "blocked_reason",
            },
            "local daemon admission",
        )
        return cls(
            admission_id=_required_string(data, "admission_id"),
            queue_item_id=_required_string(data, "queue_item_id"),
            coordinator_id=_required_string(data, "coordinator_id"),
            run_uri=_required_string(data, "run_uri"),
            intent_digest=_required_string(data, "intent_digest"),
            execution_owner=_required_string(data, "execution_owner"),
            state=LocalDaemonAdmissionState(_required_string(data, "state")),
            accepted_at=_required_string(data, "accepted_at"),
            authority_operation_id=_required_string(data, "authority_operation_id"),
            revision=_positive_revision(_required_int(data, "revision")),
            run_priority=_run_priority(_required_int(data, "run_priority")),
            enqueue_sequence=_required_int(data, "enqueue_sequence"),
            cancellation_operation_id=_optional_string(
                data, "cancellation_operation_id"
            ),
            cancellation_principal_id=_optional_string(
                data, "cancellation_principal_id"
            ),
            blocked_reason=_optional_string(data, "blocked_reason"),
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonAdmissionDetail:
    """One admission plus its explicit targeted owner join."""

    admission: LocalDaemonAdmission
    authority: Mapping[str, PlainData]
    owners: Mapping[str, PlainData] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "admission": self.admission.to_dict(),
            "authority": thaw_plain_data(
                self.authority, path="local daemon admission detail authority"
            ),
            "owners": thaw_plain_data(
                self.owners, path="local daemon admission detail owners"
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonAdmissionDetail":
        _exact_fields(
            data,
            {"admission", "authority", "owners"},
            "local daemon admission detail",
        )
        admission = data.get("admission")
        authority = data.get("authority")
        owners = data.get("owners")
        if (
            not isinstance(admission, Mapping)
            or not isinstance(authority, Mapping)
            or not isinstance(owners, Mapping)
        ):
            raise QueueServiceError("local daemon admission detail is invalid")
        return cls(
            admission=LocalDaemonAdmission.from_dict(admission),
            authority=freeze_plain_data(
                authority, path="local daemon admission detail authority"
            ),
            owners=freeze_plain_data(
                owners, path="local daemon admission detail owners"
            ),
        )


@dataclass(frozen=True, slots=True)
class DaemonStatus:
    """Bounded, redacted coordinator health and configured local resources.

    Detailed admissions deliberately live behind ``admissions()`` and
    ``admission()``.  Keeping the summary separate prevents a status read from
    becoming an accidental history export.
    """

    coordinator_id: str
    coordinator_epoch: str
    as_of: str
    service_health: str
    service_diagnostic: str | None
    scheduling_epoch: str
    active_admissions: int
    waiting_admissions: int
    running_assignments: int
    accepted_time_health: str
    accepted_time_diagnostic: str | None
    accepted_time_revision: int
    local_resource_status: tuple[ResourceAvailabilityStatus, ...] = ()

    @property
    def scheduling_ready(self) -> bool:
        return (
            self.service_health == "healthy" and self.accepted_time_health == "healthy"
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "as_of": self.as_of,
            "service_health": self.service_health,
            "service_diagnostic": self.service_diagnostic,
            "scheduling_epoch": self.scheduling_epoch,
            "scheduling_ready": self.scheduling_ready,
            "active_admissions": self.active_admissions,
            "waiting_admissions": self.waiting_admissions,
            "running_assignments": self.running_assignments,
            "accepted_time_health": self.accepted_time_health,
            "accepted_time_diagnostic": self.accepted_time_diagnostic,
            "accepted_time_revision": self.accepted_time_revision,
            "local_resource_status": [
                item.to_dict() for item in self.local_resource_status
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "DaemonStatus":
        _exact_fields(
            data,
            {
                "coordinator_id",
                "coordinator_epoch",
                "as_of",
                "service_health",
                "service_diagnostic",
                "scheduling_epoch",
                "scheduling_ready",
                "active_admissions",
                "waiting_admissions",
                "running_assignments",
                "accepted_time_health",
                "accepted_time_diagnostic",
                "accepted_time_revision",
                "local_resource_status",
            },
            "local daemon status",
        )
        return cls(
            local_resource_status=_resource_status_from_value(
                data["local_resource_status"]
            ),
            coordinator_id=_required_string(data, "coordinator_id"),
            coordinator_epoch=_required_string(data, "coordinator_epoch"),
            as_of=_required_string(data, "as_of"),
            service_health=_required_string(data, "service_health"),
            service_diagnostic=_optional_string(data, "service_diagnostic"),
            scheduling_epoch=_required_string(data, "scheduling_epoch"),
            active_admissions=_non_negative_int(
                _required_int(data, "active_admissions"), "active_admissions"
            ),
            waiting_admissions=_non_negative_int(
                _required_int(data, "waiting_admissions"), "waiting_admissions"
            ),
            running_assignments=_non_negative_int(
                _required_int(data, "running_assignments"), "running_assignments"
            ),
            accepted_time_health=_required_string(data, "accepted_time_health"),
            accepted_time_diagnostic=_optional_string(data, "accepted_time_diagnostic"),
            accepted_time_revision=_non_negative_int(
                _required_int(data, "accepted_time_revision"),
                "accepted_time_revision",
            ),
        )


@dataclass(frozen=True, slots=True)
class AdmissionPage:
    admissions: tuple[LocalDaemonAdmission, ...]
    next_cursor: str | None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "admissions": [item.to_dict() for item in self.admissions],
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True, slots=True)
class AgentPage:
    """Bounded current agent-session projections for guarded controls."""

    agents: tuple["AgentProjection", ...]
    next_cursor: str | None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "agents": [item.to_dict() for item in self.agents],
            "next_cursor": self.next_cursor,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AgentPage":
        _exact_fields(data, {"agents", "next_cursor"}, "agent page")
        agents = data.get("agents")
        cursor = data.get("next_cursor")
        if (
            not isinstance(agents, list)
            or not all(isinstance(item, Mapping) for item in agents)
            or (cursor is not None and not isinstance(cursor, str))
        ):
            raise QueueServiceError("agent page response is invalid")
        return cls(tuple(AgentProjection.from_dict(item) for item in agents), cursor)


@dataclass(frozen=True, slots=True)
class AgentOfferCapacity:
    """Remaining CPU count and number of offered GPU devices in a current offer."""

    cpu: int | None
    gpu_devices_offered: int | None
    observed_at: str

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "cpu": self.cpu,
            "gpu_devices_offered": self.gpu_devices_offered,
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AgentOfferCapacity":
        _exact_fields(
            data, {"cpu", "gpu_devices_offered", "observed_at"}, "agent offer capacity"
        )

        def count(key: str) -> int | None:
            if data[key] is None:
                return None
            return _non_negative_int(_required_int(data, key), key)

        observed_at = _required_string(data, "observed_at")
        parse_timestamp(observed_at)
        return cls(count("cpu"), count("gpu_devices_offered"), observed_at)


@dataclass(frozen=True, slots=True)
class AgentProjection:
    """Bounded current logical-agent state with the control freshness fences."""

    agent_id: str
    session_id: str
    state: str
    config_revision: str
    inventory_revision: str
    availability_revision: str
    coordinator_epoch: str
    pools: tuple[str, ...]
    capabilities: tuple[str, ...]
    available: bool
    resource_status: tuple[ResourceAvailabilityStatus, ...] = ()
    offered_capacity: AgentOfferCapacity | None = None

    def to_dict(self) -> dict[str, PlainData]:
        data: dict[str, PlainData] = {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "state": self.state,
            "config_revision": self.config_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "coordinator_epoch": self.coordinator_epoch,
            "pools": list(self.pools),
            "capabilities": list(self.capabilities),
            "available": self.available,
            "resource_status": [item.to_dict() for item in self.resource_status],
        }
        if self.offered_capacity is not None:
            data["offered_capacity"] = self.offered_capacity.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AgentProjection":
        _exact_fields(
            {key: value for key, value in data.items() if key != "offered_capacity"},
            {
                "agent_id",
                "session_id",
                "state",
                "config_revision",
                "inventory_revision",
                "availability_revision",
                "coordinator_epoch",
                "pools",
                "capabilities",
                "available",
                "resource_status",
            },
            "agent projection",
        )
        pools = data.get("pools")
        capabilities = data.get("capabilities")
        available = data.get("available")
        capacity = data.get("offered_capacity")
        if (
            not isinstance(pools, list)
            or not all(isinstance(item, str) and item for item in pools)
            or not isinstance(capabilities, list)
            or not all(isinstance(item, str) and item for item in capabilities)
            or not isinstance(available, bool)
            or ("offered_capacity" in data and (not available or not isinstance(capacity, Mapping)))
        ):
            raise QueueServiceError("agent projection is invalid")
        return cls(
            offered_capacity=(
                AgentOfferCapacity.from_dict(capacity) if isinstance(capacity, Mapping) else None
            ),
            resource_status=_resource_status_from_value(data["resource_status"]),
            agent_id=_required_string(data, "agent_id"),
            session_id=_required_string(data, "session_id"),
            state=_required_string(data, "state"),
            config_revision=_required_string(data, "config_revision"),
            inventory_revision=_required_string(data, "inventory_revision"),
            availability_revision=_required_string(data, "availability_revision"),
            coordinator_epoch=_required_string(data, "coordinator_epoch"),
            pools=tuple(pools),
            capabilities=tuple(capabilities),
            available=available,
        )


@dataclass(frozen=True, slots=True)
class LocalDaemonOperation:
    """One durable management operation without an unbounded history surface."""

    operation_id: str
    kind: str
    state: str
    code: str | None
    result: PlainData | None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "state": self.state,
            "code": self.code,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalDaemonOperation":
        _exact_fields(
            data, {"operation_id", "kind", "state", "code", "result"}, "operation"
        )
        code = data.get("code")
        if code is not None and not isinstance(code, str):
            raise QueueServiceError("operation response is invalid")
        return cls(
            operation_id=_required_string(data, "operation_id"),
            kind=_required_string(data, "kind"),
            state=_required_string(data, "state"),
            code=code,
            result=freeze_plain_data(data.get("result"), path="operation result"),
        )


class OperationWaitKind(StrEnum):
    TERMINAL = "TERMINAL"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class OperationWaitResult:
    kind: OperationWaitKind
    operation: LocalDaemonOperation

    def to_dict(self) -> dict[str, PlainData]:
        return {"kind": self.kind.value, "operation": self.operation.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "OperationWaitResult":
        _exact_fields(data, {"kind", "operation"}, "operation wait")
        kind = data.get("kind")
        operation = data.get("operation")
        if not isinstance(kind, str) or not isinstance(operation, Mapping):
            raise QueueServiceError("operation wait response is invalid")
        try:
            return cls(
                OperationWaitKind(kind), LocalDaemonOperation.from_dict(operation)
            )
        except ValueError as exc:
            raise QueueServiceError("operation wait response is invalid") from exc


class AdmissionWaitKind(StrEnum):
    CHANGED = "CHANGED"
    TERMINAL = "TERMINAL"
    TIMEOUT = "TIMEOUT"


class AdmissionNotFoundError(QueueServiceError):
    """The requested managed admission does not exist."""


class _RecoveryNotAccepted(QueueConflictError):
    """The guarded recovery request was refused before changing its intent."""


@dataclass(frozen=True, slots=True)
class AdmissionWaitResult:
    kind: AdmissionWaitKind
    admission: LocalDaemonAdmission
    revision: int

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind.value,
            "admission": self.admission.to_dict(),
            "revision": self.revision,
        }


class LocalDaemon:
    """One locked persistent production composition."""

    def __init__(
        self,
        config: LocalDaemonConfig,
        *,
        clock: Callable[[], str] = utc_timestamp,
        trusted_scheduling_loader: Callable[[], LocalDaemonConfig] | None = None,
        prepare_role_reload: (
            Callable[[LocalDaemonConfig], Callable[[], None]] | None
        ) = None,
        preparation: PreparationCallbacks | None = None,
        event_observers: Any = None,
    ) -> None:
        self.config = config
        from ._lifecycle_observers import LifecycleObservers

        self._event_observers = event_observers or LifecycleObservers()
        self._clock = clock
        self._trusted_scheduling_loader = trusted_scheduling_loader
        self._prepare_role_reload = prepare_role_reload
        self._coordinator_lock: object | None = None
        self._agent_lock: object | None = None
        self._coordinator_id: str | None = None
        self._agent_id: str | None = None
        self._epoch: str | None = None
        self._scheduling_epoch: str | None = None
        self._stop = Event()
        self._wake = _ServiceSignal()
        self._status_changed = _KeyedWaiters()
        self._thread: Thread | None = None
        self._execution: LocalDaemonExecution | None = None
        self._cycle_lock = RLock()
        self._job_read_slots = BoundedSemaphore(4)
        self._scheduling_reference_revision = 0
        self._reconcile_guard = RLock()
        from ._context_preparation import ContextPreparations
        from ._coordinator_gpu import CoordinatorGpuSamples

        self._gpu_samples = CoordinatorGpuSamples(self._wake.set)
        self._admission_retry_cursor: str | None = None
        self._continuation_retries: dict[str, _RecoveryRetry] = {}
        self._admission_scan = AdmissionScan()
        self._retirement_after = None
        self._contexts = ContextPreparations(self._wake.set)
        from ._result_verification import ResultVerifications

        self._result_verifications = ResultVerifications(self._wake.set)
        from ._agent_poll_waiters import _PollWaiters

        self._poll_waiters = _PollWaiters()
        from ._publication_guards import PublicationGuards

        self._publication_guards = PublicationGuards()
        self._service_error: str | None = None
        self._admission_retries: dict[str, _RecoveryRetry] = {}
        self._context_invalidations: set[str] = set()
        self._legacy_repair_after: tuple[int, str] | None = (0, "")
        self._legacy_repair_retries: deque[tuple[float, str]] = deque()
        self._recovery_cursor: str | None = None
        self._recovery_retries: dict[str, _RecoveryRetry] = {}
        self._agent_policy = config.agent_policy
        self._verified_local_owner_subject: str | None = None
        from ._preparation_operations import CoordinatorPreparations

        self._preparations = CoordinatorPreparations(self, preparation)
        from ._service_lifetime import CoordinatorLifetime

        self._lifetime = CoordinatorLifetime(self)

    def _state_guard(self):
        from ._phase_timing import state_lock

        return state_lock(self._cycle_lock)

    @property
    def preparation_available(self) -> bool:
        return self._preparations.available

    @classmethod
    def initialize_deployment(cls, config: LocalDaemonConfig) -> None:
        """Publish one complete coordinator/embedded-agent bundle atomically."""

        if config.storage is not None:
            config.storage.require_owner()
        target = config.deployment_root
        if target is None:
            raise QueueServiceError("coordinator deployment root is required")
        if target.exists():
            raise QueueServiceError("coordinator deployment requires a fresh root")
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        staging = target.parent / f".{target.name}.staging-{uuid4()}"
        staged = replace(
            config,
            coordinator_root=staging / "coordinator",
            agent_root=(None if config.agent_root is None else staging / "agent"),
            deployment_root=staging,
        )
        try:
            staging.mkdir(mode=0o700)
            cls.initialize(staged, _final_agent_root=config.agent_root)
            coordinator_id = _open_root(staged.coordinator_root, role="coordinator")
            agent_id = (
                None
                if staged.agent_root is None
                else _open_root(staged.agent_root, role="local-agent")
            )
            binding = {
                "schema_version": 3,
                "role_kind": "coordinator"
                if agent_id is None
                else "coordinator-bundle",
                "coordinator_id": coordinator_id,
                "immutable_fingerprint": (staged.deployment_configuration_fingerprint),
            }
            if agent_id is not None:
                binding["agent_id"] = agent_id
            binding_path = staging / _DEPLOYMENT_BINDING_FILE
            atomic_write_text(
                binding_path, json.dumps(
                    binding,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                encoding="utf-8", durability=config.durable_files,
            )
            binding_path.chmod(0o600)
            from .local_daemon_execution import local_daemon_owner_stores_available

            if not local_daemon_owner_stores_available(
                staged, coordinator_id=coordinator_id, agent_id=agent_id
            ):
                raise QueueServiceError(
                    "coordinator deployment owner stores are incomplete"
                )
            if target.exists():
                raise QueueServiceError("coordinator deployment requires a fresh root")
            staging.rename(target)
            if config.durable_files == "strict":
                _fsync_path_strict(target.parent)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    @classmethod
    def initialize(
        cls, config: LocalDaemonConfig, *, _final_agent_root: Path | None = None,
    ) -> None:
        """Create fresh owner-private roots; existing/legacy roots are rejected."""

        if config.coordinator_root.exists() or (
            config.agent_root is not None and config.agent_root.exists()
        ):
            raise QueueServiceError(
                "local daemon requires fresh roots; migration and compatibility "
                "with existing managed-local state are unsupported"
            )
        if config.storage is not None:
            config.storage.require_owner()
        _initialize_root(config.coordinator_root, role="coordinator", sqlite_policy=config.sqlite_policy)
        try:
            with config.connect_database(config.control_database) as conn:
                conn.execute(
                    "INSERT INTO daemon_metadata(key, value) "
                    "VALUES ('scheduling_epoch', ?)",
                    (f"scheduling-epoch-{uuid4()}",),
                )
                conn.execute(
                    "INSERT INTO daemon_metadata(key, value) "
                    "VALUES ('scheduling_fingerprint', ?)",
                    (_scheduling_fingerprint(config),),
                )
                conn.execute(
                    "INSERT INTO daemon_metadata(key, value) "
                    "VALUES ('active_configuration_revision', '1')"
                )
                conn.commit()
            agent_id: str | None = None
            if config.agent_root is not None:
                cls.initialize_agent_root(config.agent_root, storage=config.storage)
                from ._agent_process_supervisor import (
                    AgentProcessSupervisorService,
                    SupervisorLaunchConfiguration,
                )

                agent_id = _open_root(config.agent_root, role="local-agent")
                profile = config.resident_worker_launch_profile
                if profile is None:
                    raise QueueServiceError("local agent profile is unavailable")
                AgentProcessSupervisorService.initialize_process_free(
                    config.agent_root,
                    configuration=SupervisorLaunchConfiguration(agent_id, (profile,), storage=config.storage),
                    final_agent_root=_final_agent_root,
                )
            from .local_daemon_execution import initialize_local_daemon_owner_stores

            initialize_local_daemon_owner_stores(
                config,
                coordinator_id=_open_root(config.coordinator_root, role="coordinator"),
                agent_id=agent_id,
            )
        except Exception:
            raise


    @classmethod
    def initialize_agent_root(cls, root: Path, *, storage: StoragePolicy | None = None) -> None:
        """Create one fresh protected agent root for an outbound agent owner."""
        path = Path(root)
        if path.exists():
            raise QueueServiceError("remote agent requires a fresh root")
        if storage is not None:
            storage.require_owner()
        sqlite_policy = None if storage is None else storage.sqlite
        _initialize_root(path, role="local-agent", sqlite_policy=sqlite_policy)
        from loom.queue._managed_local import SQLiteAgentJournal

        SQLiteAgentJournal(path / "journal.sqlite", sqlite_policy=sqlite_policy)._initialize()
        (path / "journal.sqlite").chmod(0o600)

    def start(self, *, start_held: bool = False) -> DaemonStatus:
        from ._storage_upgrade_state import require_storage_upgrade_ready
        require_storage_upgrade_ready(self.config.coordinator_root)
        if self.config.storage is not None:
            self.config.storage.require_owner()
        if self._coordinator_lock is not None:
            raise QueueServiceError("local daemon is already started")
        if self._result_verifications.running():
            raise QueueServiceError("result verification is still stopping")
        if self._contexts.running():
            raise QueueServiceError("retained-input preparation is still stopping")
        if self.config.deployment_root is not None:
            _validate_deployment_binding(self.config)
        _validate_distinct_roots(self.config)
        coordinator_id = _open_root(self.config.coordinator_root, role="coordinator")
        agent_id = (
            None
            if self.config.agent_root is None
            else _open_root(self.config.agent_root, role="local-agent")
        )
        from .local_daemon_execution import _require_local_daemon_owner_stores

        _require_local_daemon_owner_stores(
            self.config, coordinator_id=coordinator_id, agent_id=agent_id
        )
        coordinator_lock = _acquire_lock(self.config.coordinator_root)
        agent_lock = None
        if self.config.agent_root is not None:
            try:
                agent_lock = _acquire_lock(self.config.agent_root)
            except Exception:
                coordinator_lock.close()
                raise
        created_supervisor: AgentProcessSupervisorClient | None = None
        owner_ids: tuple[str, str | None] | None = None
        try:
            coordinator_id = _open_root(
                self.config.coordinator_root, role="coordinator"
            )
            from .retirement import require_unretired
            require_unretired(self.config.coordinator_root)
            require_storage_upgrade_ready(self.config.coordinator_root, entering=True)
            from .local_daemon_execution import ensure_child_release_indexes
            from .slurm_ready_stage import ensure_slurm_page_index
            with self.config.connect_database(self.config.execution_database) as execution_conn:
                ensure_slurm_page_index(execution_conn)
                ensure_child_release_indexes(execution_conn)
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                ensure_agent_lookup_indexes(conn)
                ensure_scan_index(conn)
                ensure_retry_index(conn)
                _ensure_recovery_assignment_index(conn)
                _ensure_preparation_child_index(conn)
                retained = conn.execute("SELECT value FROM root_metadata WHERE key = 'assignment_payload_root_id'").fetchone()
                selected = self.config.assignment_payload_root_id
                if retained is not None and retained[0] != selected:
                    raise QueueConflictError("assignment payload root conflicts with durable deployment binding")
                if selected is not None and retained is None:
                    conn.execute("INSERT INTO root_metadata(key, value) VALUES ('assignment_payload_root_id', ?)", (selected,))
                conn.commit()

            agent_id = (
                None
                if self.config.agent_root is None
                else _open_root(self.config.agent_root, role="local-agent")
            )
            verified_local_owner_subject = (
                f"uid:{self.config.coordinator_root.stat().st_uid}"
            )
            owner_ids = coordinator_id, agent_id
            from .local_daemon_execution import local_daemon_owner_work_is_retained

            # Recover only a fully prepared reload intent that is bound to the
            # exact protected source used to construct this process.  This is
            # done before an empty detached owner exists at all.
            with self._connection() as conn:
                scheduling = {
                    str(row["key"]): str(row["value"])
                    for row in conn.execute(
                        "SELECT key, value FROM daemon_metadata WHERE key IN "
                        "('scheduling_epoch', 'scheduling_fingerprint', "
                        "'active_configuration_revision')"
                    )
                }
            scheduling = self._recover_scheduling_reload_intent(scheduling)
            if scheduling.get("scheduling_fingerprint") != _scheduling_fingerprint(
                self.config
            ):
                raise QueueConflictError(
                    "protected scheduling configuration changed without reload"
                )
            scheduling_epoch = scheduling.get("scheduling_epoch")
            configuration_revision = scheduling.get("active_configuration_revision")
            if (
                scheduling_epoch is None
                or configuration_revision is None
                or not configuration_revision.isdecimal()
                or int(configuration_revision) < 1
            ):
                raise QueueStorageError(
                    "active scheduling configuration is unavailable"
                )
            if start_held:
                from ._maintenance import hold_for_startup
                with self._connection() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    hold_for_startup(conn, coordinator_id, applied_at=self._clock())
                    conn.commit()
            self._event_observers.start()
            # This is the same cross-owner proof used by normal shutdown.  It
            # rejects unavailable owner state before process creation and
            # identifies retained work that must keep a newly started service
            # available for recovery if later construction fails.
            local_daemon_owner_work_is_retained(
                self.config, coordinator_id=coordinator_id, agent_id=agent_id
            )
            if agent_id is not None and self.config.agent_root is not None:
                from ._agent_process_supervisor import (
                    AgentProcessSupervisorService,
                    SupervisorLaunchConfiguration,
                )

                profile = self.config.resident_worker_launch_profile
                if profile is None:
                    raise QueueServiceError("local agent profile is unavailable")
                supervisor_configuration = SupervisorLaunchConfiguration(
                    agent_id, (profile,)
                , storage=self.config.storage)
                try:
                    AgentProcessSupervisorClient(
                        self.config.agent_root, supervisor_configuration
                    )
                except AgentProcessSupervisorError as exc:
                    if str(exc) != "managed supervisor endpoint is unavailable":
                        raise
                    created_supervisor = (
                        AgentProcessSupervisorService.start_empty_initialized(
                            self.config.agent_root,
                            configuration=supervisor_configuration,
                        )
                    )
            self._coordinator_id = coordinator_id
            self._agent_id = agent_id
            epoch = f"coordinator-epoch-{uuid4()}"
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    started_at = self._accepted_time(conn)
                except QueueServiceError:
                    high_water = conn.execute(
                        "SELECT value FROM daemon_metadata "
                        "WHERE key = 'accepted_time_high_water'"
                    ).fetchone()
                    if high_water is None:
                        raise
                    started_at = str(high_water["value"])
                conn.execute(
                    "INSERT INTO coordinator_epochs (epoch, started_at) VALUES (?, ?)",
                    (epoch, started_at),
                )
                # An active row without a result belonged to a request held by
                # the previous process epoch.  Delivery and its replay result
                # commit in one transaction, so fencing only that abandoned
                # request cannot hide accepted work.  Committed results remain
                # replayable while the reconciled agent advances from a fenced
                # request to the next sequence.
                conn.execute(
                    "UPDATE agent_poll_state SET active = 0 "
                    "WHERE active = 1 AND result_json IS NULL"
                )
                conn.commit()
        except Exception:
            if created_supervisor is not None and owner_ids is not None:
                self._shutdown_created_supervisor_if_empty(
                    created_supervisor,
                    coordinator_id=owner_ids[0],
                    agent_id=owner_ids[1],
                )
            if agent_lock is not None:
                agent_lock.close()
            coordinator_lock.close()
            self._coordinator_id = None
            self._agent_id = None
            self._scheduling_epoch = None
            raise
        from .local_daemon_execution import LocalDaemonExecution

        try:
            execution = LocalDaemonExecution(
                config=self.config,
                coordinator_id=coordinator_id,
                agent_id=agent_id,
                coordinator_epoch=epoch,
                scheduling_epoch=scheduling_epoch,
                cancellation_operation=self._cancellation_operation_id,
                admission_activated=self._activate_admission,
                daemon=self,
            )
            # A persisted recovery may already have target-owned evidence from
            # before the restart.  Replay it before ordinary retained work is
            # allowed to mutate authority again.
            self._resume_pending_recoveries(execution)
            # The daemon is not observable or schedulable until every retained
            # local launch has joined the continuous supervisor and completed
            # ordinary result/output/provider replay.
            execution.resume_retained_local_work()
        except Exception as exc:
            if created_supervisor is not None:
                self._shutdown_created_supervisor_if_empty(
                    created_supervisor,
                    coordinator_id=coordinator_id,
                    agent_id=agent_id,
                )
            if agent_lock is not None:
                agent_lock.close()
            coordinator_lock.close()
            self._coordinator_id = None
            self._agent_id = None
            raise QueueServiceError(
                "retained daemon owner state is unavailable"
            ) from exc
        thread = Thread(
            target=self._serve,
            name="loom-local-daemon-runtime",
            daemon=True,
        )
        self._coordinator_lock = coordinator_lock
        self._agent_lock = agent_lock
        self._coordinator_id = coordinator_id
        self._agent_id = agent_id
        self._epoch = epoch
        self._scheduling_epoch = scheduling_epoch
        self._service_error = None
        self._admission_retries.clear()
        self._legacy_repair_after = (0, "")
        self._legacy_repair_retries.clear()
        self._verified_local_owner_subject = verified_local_owner_subject
        self._contexts.close()
        self._gpu_samples.close()
        self._result_verifications.close()
        from ._context_preparation import ContextPreparations
        from ._coordinator_gpu import CoordinatorGpuSamples

        self._gpu_samples = CoordinatorGpuSamples(self._wake.set)
        self._admission_retry_cursor = None
        self._continuation_retries.clear()
        self._admission_scan = AdmissionScan()
        self._retirement_after = None
        self._contexts = ContextPreparations(self._wake.set)
        from ._result_verification import ResultVerifications

        self._result_verifications = ResultVerifications(self._wake.set)
        self._preparations._verification_reports.clear()
        self._preparations._reports.clear()
        self._preparations._authority_jobs.clear()
        self._resuming_runs: dict[str, None] = {}
        self._preparations._publications.clear()
        self._preparations._ready_publications.clear()
        self._preparations._children.clear()
        self._preparations._child_release_checks.clear()
        self._preparations._captures.clear()
        self._preparations._images.clear()
        self._preparations._candidates.clear()
        self._preparations._target_retries.clear()
        self._stop.clear()
        from ._agent_poll_waiters import _PollWaiters

        self._poll_waiters = _PollWaiters()
        self._status_changed = _KeyedWaiters()
        from ._publication_guards import PublicationGuards

        self._publication_guards = PublicationGuards()
        self._wake.set()
        self._execution = execution
        self._thread = thread
        self._event_observers.enable_delivery(self._wake.set)
        try:
            thread.start()
        except Exception:
            self.stop()
            raise
        return self.status()

    def _shutdown_created_supervisor_if_empty(
        self,
        supervisor: AgentProcessSupervisorClient,
        *,
        coordinator_id: str,
        agent_id: str | None,
    ) -> None:
        """Retire only the empty cross-owner service this start created."""

        from .local_daemon_execution import local_daemon_owner_work_is_retained

        if agent_id is None:
            return
        try:
            if not local_daemon_owner_work_is_retained(
                self.config, coordinator_id=coordinator_id, agent_id=agent_id
            ):
                supervisor.shutdown_clean()
        except (AgentProcessSupervisorError, QueueConflictError, QueueServiceError):
            # Unknown or retained owner state is deliberately recoverable; a
            # constructor failure must never turn it into forced termination.
            pass

    def stop(self) -> None:
        with self._state_guard():
            self._stop.set()
            self._poll_waiters.close()
            self._publication_guards.close()
            self._wake.set()
            self._status_changed.close()
        self._poll_waiters.drain()
        self._status_changed.drain()
        self._publication_guards.drain()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join()
        self._event_observers.close_delivery()
        self._contexts.close()
        self._gpu_samples.close()
        self._result_verifications.close()
        if self._execution is not None:
            self._execution.close()
            try:
                if not self._lifetime.clean_shutdown_verified:
                    self._execution.shutdown_clean()
            except (QueueConflictError, QueueServiceError):
                # A busy or unavailable cross-owner proof deliberately leaves
                # the detached process running for recovery.
                _LOGGER.warning(
                    "local daemon retained its supervisor during shutdown; "
                    "preserve the deployment and inspect the shutdown refusal",
                    exc_info=True,
                )
        self._execution = None
        for lock in (self._agent_lock, self._coordinator_lock):
            if lock is not None:
                lock.close()  # type: ignore[union-attr]
        self._coordinator_lock = None
        self._agent_lock = None
        self._coordinator_id = None
        self._agent_id = None
        self._epoch = None
        self._scheduling_epoch = None
        self._verified_local_owner_subject = None

    def client_view(self, principal: LocalDaemonPrincipal) -> "LocalDaemonClientView":
        return LocalDaemonClientView(self, principal)

    def operator_view(
        self, principal: LocalDaemonPrincipal
    ) -> "LocalDaemonOperatorView":
        return LocalDaemonOperatorView(self, principal)

    def agent_view(self, principal: LocalDaemonPrincipal) -> AgentSessionView:
        """Return the restricted authenticated agent view for a trusted principal."""
        return AgentSessionView(self, principal)

    def slurm_bootstrap_view(
        self, principal: LocalDaemonPrincipal
    ) -> "LocalDaemonSlurmBootstrapView":
        """Return the assignment-scoped fixed-bootstrap application view."""

        return LocalDaemonSlurmBootstrapView(self, principal)

    def replace_agent_policy(self, policy: AgentPolicyConfig) -> None:
        """Install a new protected policy; later operations re-authorize it."""
        if not isinstance(policy, AgentPolicyConfig):
            raise QueueServiceError("agent policy is invalid")
        slurm_credentials = {
            profile.credential_reference for profile in self.config.slurm_profiles
        }
        policy_credentials = {
            item.credential_id for item in (*policy.agents, *policy.principals)
        }
        if slurm_credentials & policy_credentials:
            raise QueueServiceError(
                "SLURM bootstrap credentials must remain role-exclusive"
            )
        with self._state_guard():
            self._agent_policy = policy
            self._poll_waiters.notify_all()

    def _require_view_role(
        self, principal: LocalDaemonPrincipal, role: LocalDaemonRole
    ) -> None:
        self._authorizer().require_role(principal, role.value)

    def _authorizer(self):  # type: ignore[no-untyped-def]
        from .agent_sessions import ScopedAuthorizer

        return ScopedAuthorizer(
            self._agent_policy,
            verified_local_owner_subject=self._verified_local_owner_subject,
        )

    def status(self) -> DaemonStatus:
        coordinator_id = self._require_started()
        # This is intentionally a small coordinator-only operation.  Do not add
        # owner joins here: detail belongs to admission() and the owner views
        # remain an internal reconciliation diagnostic.
        with self._connection() as conn:
            counts = {
                str(row["state"]): int(row["n"])
                for row in conn.execute(
                    "SELECT state, COUNT(*) AS n FROM managed_admissions GROUP BY state"
                )
            }
            failed = conn.execute(
                "SELECT 1 FROM admission_reconciliation_health "
                "WHERE health IN ('failed', 'unavailable') LIMIT 1"
            ).fetchone()
            time_state = {
                str(row["key"]): str(row["value"])
                for row in conn.execute(
                    "SELECT key, value FROM daemon_metadata WHERE key IN "
                    "('accepted_time_health', 'accepted_time_diagnostic', "
                    "'accepted_time_revision')"
                )
            }
        active = counts.get(LocalDaemonAdmissionState.ACTIVE.value, 0)
        waiting = counts.get(LocalDaemonAdmissionState.WAITING.value, 0)
        # Assignment ownership is split between local and remote stores.  The
        # coordinator's remote assignment table is the bounded public count;
        # local owner activity is included when its journal is available.
        running = 0
        assignment_counts_available = True
        try:
            with self._connection() as conn:
                running += int(
                    conn.execute(
                        "SELECT COUNT(*) FROM remote_assignments "
                        "WHERE state NOT IN ('RELEASED', 'FAILED', 'CANCELLED')"
                    ).fetchone()[0]
                )
            with inspect_sqlite_database(self.config.execution_database) as execution:
                running += int(
                    execution.execute(
                        "SELECT COUNT(*) FROM slurm_stage_assignments "
                        "WHERE state != 'released'"
                    ).fetchone()[0]
                )
            if self.config.agent_root is not None:
                with inspect_sqlite_database(self.config.agent_journal) as journal:
                    running += int(
                        journal.execute(
                            "SELECT COUNT(*) FROM assignments "
                            "WHERE state NOT IN ('RELEASED', 'FAILED', 'CANCELLED')"
                        ).fetchone()[0]
                    )
        except (sqlite3.Error, OSError):
            # The coordinator remains observable even if a private owner store
            # is temporarily unavailable; health carries that condition.
            assignment_counts_available = False
        time_health = time_state.get("accepted_time_health", "healthy")
        diagnostic = time_state.get("accepted_time_diagnostic")
        from .local_daemon_execution import local_daemon_owner_stores_available

        owners_available = local_daemon_owner_stores_available(
            self.config,
            coordinator_id=coordinator_id,
            agent_id=self._agent_id,
        )
        local_profile_ready = (
            self.config.agent_root is None
            or self._execution is None
            or self._execution.local_profile_ready
        )
        as_of = self._clock()
        parse_timestamp(as_of)
        local_status = tuple(
            status
            for provider in self._local_resource_providers()
            for status in provider.observe(
                ObserveRequest(
                    self.config.machine_id,
                    self._epoch or "status",
                    "status:cached-resources",
                )
            ).resource_status
        )
        return DaemonStatus(
            local_resource_status=local_status,
            coordinator_id=coordinator_id,
            coordinator_epoch=self._epoch or "",
            as_of=as_of,
            service_health=(
                "healthy"
                if self._service_error is None
                and failed is None
                and time_health == "healthy"
                and owners_available
                and assignment_counts_available
                and local_profile_ready
                else "degraded"
            ),
            service_diagnostic=(
                diagnostic
                if time_health != "healthy"
                else (
                    "admission_reconciliation_degraded"
                    if failed is not None
                    else (
                        "owner_status_unavailable"
                        if not owners_available or not assignment_counts_available
                        else (
                            "resident_profile_unready"
                            if not local_profile_ready
                            else self._service_error
                        )
                    )
                )
            ),
            scheduling_epoch=self._scheduling_epoch or "",
            active_admissions=active,
            waiting_admissions=waiting,
            running_assignments=running,
            accepted_time_health=time_health,
            accepted_time_diagnostic=diagnostic,
            accepted_time_revision=_non_negative_int(
                int(time_state.get("accepted_time_revision", "0")),
                "accepted_time_revision",
            ),
        )

    def _waiting_reasons(self, rows: Sequence[tuple[str, str, str | None]]) -> dict[str, str]:
        """Enrich generic WAITING rows while preserving specific durable diagnostics."""
        eligible = {identity for identity, state, reason in rows if state == "WAITING"
                    and reason in (None, "awaiting scheduling decision",
                                   "no dependency-ready stage currently has managed capacity")}
        observed = self._execution._scheduling_waits.waiting_reasons(eligible) if self._execution and eligible else {}
        return {identity: observed.get(identity, "awaiting scheduling decision") for identity in eligible}

    def admissions(
        self, *, limit: int = _MAX_ADMISSION_PAGE_SIZE, cursor: str | None = None
    ) -> AdmissionPage:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_ADMISSION_PAGE_SIZE
        ):
            raise QueueServiceError("admission list limit must be in 1..100")
        pair = _decode_admission_cursor(cursor) if cursor is not None else None
        query = "SELECT * FROM managed_admissions"
        values: tuple[object, ...] = ()
        if pair is not None:
            query += " WHERE (enqueue_sequence, admission_id) > (?, ?)"
            values = pair
        query += " ORDER BY enqueue_sequence, admission_id LIMIT ?"
        with self._connection() as conn:
            rows = tuple(conn.execute(query, (*values, limit + 1)))
        page = tuple(_admission_from_row(row) for row in rows[:limit])
        reasons = self._waiting_reasons([(item.admission_id, item.state.value, item.blocked_reason) for item in page])
        page = tuple(replace(item, blocked_reason=reasons[item.admission_id])
                     if item.admission_id in reasons else item for item in page)
        next_cursor = (
            _encode_admission_cursor(page[-1].enqueue_sequence, page[-1].admission_id)
            if len(rows) > limit and page
            else None
        )
        return AdmissionPage(page, next_cursor)

    def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
        _required_string({"admission_id": admission_id}, "admission_id")
        admission = self._admission(admission_id)
        from .local_daemon_execution import build_local_daemon_owner_views

        views = build_local_daemon_owner_views(
            self.config,
            (admission,),
            coordinator_id=self._require_started(),
            agent_id=self._agent_id,
            clock=self._clock,
            admission_revision=admission.revision,
            observe_storage=self._slurm_storage_observer(),
        )
        return self._admission_detail(admission, views[0])

    def _slurm_storage_observer(self) -> StorageObserver | None:
        from ._owner_journals import StorageObserver

        execution = self._execution
        if execution is None:
            return None

        def project(records: Sequence[SlurmStorageFacts]) -> dict[str, PlainData]:
            with self._cycle_lock:
                return execution.slurm_storage_observations(records)

        return StorageObserver(execution.slurm_assignments.path, execution.slurm_assignments.schema_version, project)

    def _admission_detail(
        self, admission: LocalDaemonAdmission, view: Mapping[str, PlainData],
    ) -> LocalDaemonAdmissionDetail:
        if not isinstance(view.get("authority"), Mapping):
            raise QueueStorageError("targeted admission owner detail is unavailable")
        if admission.state is LocalDaemonAdmissionState.WAITING:
            reasons = self._waiting_reasons([(admission.admission_id, admission.state.value, admission.blocked_reason)])
            if admission.admission_id in reasons:
                admission = replace(admission, blocked_reason=reasons[admission.admission_id])
        owners = dict(view)
        if self._execution is not None:
            owners["scheduling_waits"] = self._execution._scheduling_waits.observed(admission.run_uri)
            owners["scheduling_summaries"] = self._execution._scheduling_waits.summaries(admission.run_uri)
            owners["input_validation"] = self._execution._input_validations.observations(admission.run_uri)
        # Extend the existing loose owner detail, not the strict inspection wire.
        assignment = owners.get("assignment")
        if isinstance(assignment, Mapping):
            from ._service_lifetime import remote_release_pending
            from .operations import _agent_observation

            rows = assignment.get("assignments", ())
            remote_rows = [
                row for row in rows if isinstance(row, Mapping)
                and isinstance(row.get("agent_id"), str) and row["agent_id"] != self._agent_id
            ] if isinstance(rows, (list, tuple)) else []
            if remote_rows:
                with self._connection() as conn:
                    owners["remote_release_pending"] = remote_release_pending(
                        conn, admission.run_uri,
                        tuple(cast(str, row["assignment_id"]) for row in remote_rows),
                    )
            agent_ids = sorted({cast(str, row["agent_id"]) for row in remote_rows})
            sessions: list[PlainData] = []
            for agent_id in agent_ids[:_MAX_ADMISSION_PAGE_SIZE]:
                try:
                    observed = _agent_observation(self, agent_id)
                except Exception:
                    sessions.append({
                        "owner": f"agent-session:{agent_id}", "availability": "unavailable",
                        "state": "unavailable", "freshness": "unavailable",
                        "diagnostic": "owner_unavailable",
                    })
                else:
                    drained, connected = observed.value["drained"], observed.value["connected"]
                    sessions.append({
                        "owner": f"agent-session:{agent_id}", "availability": observed.availability,
                        "state": "drained" if drained else "connected" if connected else "disconnected",
                        "revision": observed.revision, "observed_at": observed.observed_at,
                        "freshness": observed.freshness,
                        "diagnostic": "agent_disconnected_or_drained" if drained or not connected else None,
                    })
            owners["agent_sessions"] = sessions
            owners["agent_sessions_truncated"] = len(agent_ids) > len(sessions)
        authority = cast(Mapping[str, PlainData], owners["authority"])
        return LocalDaemonAdmissionDetail(
            admission=admission,
            authority=authority,
            owners=owners,
        )

    def admission_for_queue_item(self, queue_item_id: str) -> LocalDaemonAdmission:
        _required_string({"queue_item_id": queue_item_id}, "queue_item_id")
        return self._admission_for_queue_item(queue_item_id)

    def admission_for_run_uri(self, run_uri: str) -> LocalDaemonAdmission:
        """Return the one admission indexed by its canonical run URI."""
        _required_string({"run_uri": run_uri}, "run_uri")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE coordinator_id = ? AND run_uri = ?",
                (self._require_started(), run_uri),
            ).fetchone()
        if row is None:
            raise AdmissionNotFoundError("managed admission was not found")
        return _admission_from_row(row)

    def agents(
        self, *, limit: int = _MAX_ADMISSION_PAGE_SIZE, cursor: str | None = None,
        include_capacity: bool = False,
    ) -> AgentPage:
        """Return a keyset-bounded session view with control fences intact."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise QueueServiceError("agent list limit must be in 1..100")
        agent_id = _decode_agent_cursor(cursor) if cursor is not None else None
        # A replacement may be recorded in the same accepted-time second as
        # its predecessor.  Prefer the one open session first; only when an
        # agent has no open session do reads fall back deterministically to its
        # latest terminal receipt.
        query = (
            "SELECT * FROM agent_sessions AS current WHERE NOT EXISTS ("
            "SELECT 1 FROM agent_sessions AS newer WHERE newer.agent_id = current.agent_id "
            "AND ((CASE WHEN newer.state IN ('RETIRED_CLEAN', 'REPLACED') THEN 1 ELSE 0 END) "
            "< (CASE WHEN current.state IN ('RETIRED_CLEAN', 'REPLACED') THEN 1 ELSE 0 END) OR "
            "((CASE WHEN newer.state IN ('RETIRED_CLEAN', 'REPLACED') THEN 1 ELSE 0 END) "
            "= (CASE WHEN current.state IN ('RETIRED_CLEAN', 'REPLACED') THEN 1 ELSE 0 END) "
            "AND (newer.created_at > current.created_at OR "
            "(newer.created_at = current.created_at AND newer.session_id > current.session_id))))"
            ")"
        )
        values: tuple[object, ...] = ()
        if agent_id is not None:
            query += " AND current.agent_id > ?"
            values = (agent_id,)
        query += " ORDER BY current.agent_id LIMIT ?"
        with self._connection() as conn:
            conn.execute("BEGIN")
            rows = tuple(conn.execute(query, (*values, limit + 1)))
            as_of = self._clock()
            values_out = tuple(
                _agent_projection(
                    conn, row, coordinator_epoch=self._epoch, as_of=as_of,
                    include_capacity=include_capacity,
                )
                for row in rows[:limit]
            )
        next_cursor = (
            _encode_agent_cursor(str(rows[limit - 1]["agent_id"]))
            if len(rows) > limit
            else None
        )
        return AgentPage(values_out, next_cursor)

    def agent(self, agent_id: str, *, include_capacity: bool = False) -> AgentProjection:
        _required_string({"agent_id": agent_id}, "agent_id")
        with self._connection() as conn:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE agent_id = ? ORDER BY "
                "CASE WHEN state IN ('RETIRED_CLEAN', 'REPLACED') THEN 1 ELSE 0 END, "
                "created_at DESC, session_id DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
            if row is None:
                raise QueueServiceError("managed agent was not found")
            return _agent_projection(
                conn, row, coordinator_epoch=self._epoch, as_of=self._clock(),
                include_capacity=include_capacity,
            )

    def operation(self, operation_id: str) -> LocalDaemonOperation:
        """Read the one typed durable operation receipt without a history scan."""

        _required_string({"operation_id": operation_id}, "operation_id")
        slurm_operation: LocalDaemonOperation | None = None
        execution = self._execution
        if execution is not None:
            projected = execution.operation_projection(operation_id)
            if projected is not None:
                projected_state = projected.get("state")
                projected_code = projected.get("code")
                if not isinstance(projected_state, str) or (
                    projected_code is not None and not isinstance(projected_code, str)
                ):
                    raise QueueServiceError("SLURM operation projection is invalid")
                slurm_operation = LocalDaemonOperation(
                    operation_id=operation_id,
                    kind="slurm_stage_assignment",
                    state=projected_state,
                    code=projected_code,
                    result=projected["result"],
                )
        with self._connection() as conn:
            management_operation = _operation_projection(conn, operation_id)
        if slurm_operation is not None and management_operation is not None:
            raise QueueConflictError("managed operation identity is ambiguous")
        if slurm_operation is not None:
            return slurm_operation
        if management_operation is not None:
            return management_operation
        raise QueueServiceError("managed operation was not found")

    def prepare_run(
        self, request: "PrepareRunRequest", *, principal_id: str
    ) -> LocalDaemonOperation:
        """Accept one durable intent; capture and publication reconcile separately."""
        return self._preparations.accept(request, principal_id)

    def start_run(
        self, request: "RunRequest", *, principal_id: str
    ) -> LocalDaemonOperation:
        """Retain preparation and its exact admission continuation atomically."""
        return self._preparations.accept_run(request, principal_id)

    def cancel_run_operation(
        self, operation_id: str, *, principal_id: str
    ) -> LocalDaemonOperation:
        """Retain independent cancellation, serialized against target admission."""
        return self._preparations.cancel_run(operation_id, principal_id)

    def cancel_preparation(
        self, operation_id: str, *, principal_id: str
    ) -> LocalDaemonOperation:
        """Request cancellation; terminal state requires native no-work/release proof."""
        _required_string({"operation_id": operation_id}, "operation_id")
        return self._preparations.cancel(operation_id, principal_id)

    def wait_operation(
        self, operation_id: str, *, timeout: float | None
    ) -> OperationWaitResult:
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout < 0
        ):
            raise QueueServiceError("operation wait timeout is invalid")
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        with self._status_changed.subscribe("operation:" + operation_id) as signal:
            while True:
                observed = signal.snapshot()
                self._require_wait_running()
                operation = self.operation(operation_id)
                state = operation.state
                if operation.kind == "slurm_stage_assignment":
                    if state in {"released", "conflict"}:
                        return OperationWaitResult(OperationWaitKind.TERMINAL, operation)
                    if deadline is not None and time.monotonic() >= deadline:
                        return OperationWaitResult(OperationWaitKind.TIMEOUT, operation)
                    self._wait_for_status_change(signal, observed, deadline)
                    continue
                if state not in {
                    "pending_delivery",
                    "applying",
                    "pending",
                    "evidence_confirmed",
                    "decision",
                    "bound",
                }:
                    return OperationWaitResult(OperationWaitKind.TERMINAL, operation)
                if deadline is not None and time.monotonic() >= deadline:
                    return OperationWaitResult(OperationWaitKind.TIMEOUT, operation)
                self._wait_for_status_change(signal, observed, deadline)

    def wait_admission(
        self, admission_id: str, *, expected_revision: int, timeout: float | None
    ) -> AdmissionWaitResult:
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise QueueServiceError("expected admission revision is invalid")
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout < 0
        ):
            raise QueueServiceError("admission wait timeout is invalid")
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        terminal = {
            LocalDaemonAdmissionState.SUCCEEDED,
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
            LocalDaemonAdmissionState.BLOCKED,
        }
        with self._status_changed.subscribe("admission:" + admission_id) as signal:
            while True:
                observed = signal.snapshot()
                self._require_wait_running()
                with self._connection() as conn:
                    row = conn.execute(
                        "SELECT * FROM managed_admissions WHERE admission_id = ?",
                        (admission_id,),
                    ).fetchone()
                if row is None:
                    raise AdmissionNotFoundError("managed admission was not found")
                current = _positive_revision(int(row["revision"]))
                if expected_revision > current:
                    raise QueueConflictError(
                        "expected admission revision is ahead of current revision"
                    )
                admission = _admission_from_row(row)
                if admission.state in terminal:
                    return AdmissionWaitResult(
                        AdmissionWaitKind.TERMINAL, admission, current
                    )
                if current != expected_revision:
                    return AdmissionWaitResult(
                        AdmissionWaitKind.CHANGED, admission, current
                    )
                if deadline is not None and time.monotonic() >= deadline:
                    return AdmissionWaitResult(
                        AdmissionWaitKind.TIMEOUT, admission, current
                    )
                self._wait_for_status_change(signal, observed, deadline)

    def _require_wait_running(self) -> None:
        if self._stop.is_set():
            raise QueueServiceError("coordinator is stopping")

    def _wait_for_status_change(self, signal: _ChangeSignal, observed: int, deadline: float | None) -> None:
        # Other owner databases and external processes can change without this
        # process observing their commit. Re-read at the bounded safety deadline.
        remaining = 1.0 if deadline is None else max(0.0, deadline - time.monotonic())
        signal.wait_for_change(observed, min(1.0, remaining))

    def _local_resource_providers(self) -> tuple[AgentResourceProvider, ...]:
        """Read the installed execution owners, including owners retained by reload."""
        execution = self._execution
        if execution is None:
            return tuple(self.config.agent_resource_providers or ())
        return tuple(
            member
            for owner in execution.providers.values()
            for member in (
                owner.members
                if isinstance(owner, _CompositeAgentResourceProvider)
                else (owner,)
            )
        )

    def reconcile_once(self) -> tuple[LocalDaemonAdmission, ...]:
        """Advance a finite batch and sample bounded cycle/dispatch timings."""
        from ._phase_timing import reported_phases

        with reported_phases("coordinator.reconcile_cycle"):
            checked = None
            if current_thread() is not self._thread:
                # An explicit caller observes owner loss synchronously. Its
                # filesystem wait need not own the background scheduling turn.
                with self._state_guard():
                    self._require_started()
                    owner = self._execution
                    epochs = (self._epoch, self._scheduling_epoch)
                if owner is None:
                    raise QueueServiceError("local daemon execution is absent")
                owner.open_owner_stores()
                checked = (owner, epochs)
            with self._reconcile_guard:
                try:
                    return self._reconcile_once(checked)
                finally:
                    self._contexts.finish_handoffs()


    def _reconcile_once(self, checked=None) -> tuple[LocalDaemonAdmission, ...]:
        self._require_started()
        bulk = self._result_verifications.bulk
        scopes = bulk.ready_scopes()

        priorities = tuple(scope for scope in scopes if scope[0] in {"preparation", "cancel"})
        if priorities:
            self._preparations.reconcile(priorities)
        else:
            self._preparations.reconcile()
        with self._state_guard():
            self._gpu_samples.advance(self._local_resource_providers())
        time_healthy = self._sample_clock_health(wait_for_writer=False)
        with self._state_guard():
            execution = self._execution
        if execution is None:
            raise QueueServiceError("local daemon execution is absent")
        completed_local = execution._completed_local_runs.take()
        completed_runs = (*[scope[1] for scope in scopes if scope[0] == "run"], *completed_local)
        for uri in completed_runs:
            if len(self._resuming_runs) < 256:
                self._resuming_runs.setdefault(uri, None)
        for scope in scopes:
            if scope[0] == "dispatch":
                execution._ready_continuations.offer(scope[2])
        self._event_observers.offer_audit(excluded=execution.run_observations.pending_runs())
        epochs = (self._epoch, self._scheduling_epoch)
        if checked != (execution, epochs) and not execution.owner_stores_ready(epochs):
            return ()
        self._resume_pending_admission_retries(execution)
        self._resume_pending_recoveries(execution, background=True)
        execution.begin_cycle()
        self._repair_cancelled_admissions(execution)
        with self._connection() as conn:
            enqueue_through = int(conn.execute(
                "SELECT COALESCE(MAX(enqueue_sequence), 0) FROM managed_admissions"
            ).fetchone()[0])
            admissions = tuple(_admission_from_row(row) for row in self._admission_scan.page(conn, enqueue_through))
        self._retire_inactive_scheduling_owners(execution)
        with self._state_guard():
            epochs = (self._epoch, self._scheduling_epoch)
            invalidated = set(self._context_invalidations)
            self._context_invalidations.clear()
        execution.run_observations.invalidate(invalidated, bulk)
        schedulable = SchedulingAdmissions(enqueue_through, self._lookup_schedulable_admissions)
        schedulable.include(execution.dispatch_observations.requested_admissions())
        execution.dispatch_observations.begin_cycle(
            invalidated.union(completed_local), epochs, self.config.poll_interval_seconds,
            {key: row.revision for key, row in schedulable.items()},
            execution.stage_work_store.ready_ids, execution._ready_continuations.offer,
        )
        execution.retain_dispatch_contexts(invalidated, epochs, bulk.active_runs() | self._resuming_runs.keys())
        self._contexts.begin_cycle(minimum_interval=self.config.poll_interval_seconds, invalidated=invalidated)
        prepared: dict[str, PendingContext | RunObservation] = {
            item.admission.admission_id: item for item in self._contexts.completed()
        }
        for observation in execution.run_observations.completed():
            identity = observation.admission.admission_id
            other = prepared.get(identity)
            if isinstance(other, PendingContext):
                other.discard("run_observation_preferred")
            prepared[identity] = observation
        waiting_outcomes: dict[str, LocalDaemonExecutionOutcome] = {}
        for preparation in sorted(prepared.values(), key=lambda item: AdmissionScan.key(item.admission)):
            admission = preparation.admission
            with self._state_guard():
                try:
                    current = self._admission(admission.admission_id)
                except AdmissionNotFoundError:
                    if isinstance(preparation, PendingContext):
                        preparation.discard("admission_missing")
                    execution.run_observations.discard(admission.admission_id, bulk)
                    continue
                epochs = (self._epoch, self._scheduling_epoch)
            if preparation.epochs != epochs or preparation.admission.revision != current.revision:
                if isinstance(preparation, RunObservation):
                    execution.run_observations.discard(admission.admission_id, bulk)
                else:
                    preparation.discard("epoch_changed" if preparation.epochs != epochs else "admission_revision_changed")
                self._wake.set()
                continue
            admission = current
            schedulable.pop(admission.admission_id, None)
            progress = (admission.revision, self._scheduling_epoch)
            retry = self._admission_retries.get(admission.run_uri)
            if retry is not None and not retry.ready(progress):
                if isinstance(preparation, PendingContext):
                    preparation.discard("retry_backoff")
                continue
            try:
                context = preparation.result()
                execution._cycle_context_epochs[admission.admission_id] = preparation.epochs
                outcome = execution.reconcile_admission(admission, prepared_context=context)
            except RunObservationPending:
                continue
            except QueueConflictError:
                bulk.discard(("run", admission.run_uri))
                bulk.discard(("dispatch", admission.run_uri))
                if preparation.epochs != (self._epoch, self._scheduling_epoch):
                    self._wake.set()
                    continue
                with self._state_guard():
                    self._admission_retries.pop(admission.run_uri, None)
                execution._scheduling_waits.retain(admission.run_uri, set())
                self._record_admission_health(admission.admission_id, "failed")
                self._set_state(
                    admission.admission_id,
                    LocalDaemonAdmissionState.BLOCKED,
                    reason="authority_or_intent_conflict", observed=admission,
                )
            except Exception as error:  # one unhealthy run cannot stop other admissions
                bulk.discard(("run", admission.run_uri))
                bulk.discard(("dispatch", admission.run_uri))
                self._record_admission_health(admission.admission_id, "unavailable")
                with self._state_guard():
                    retry = self._admission_retries.setdefault(admission.run_uri, _RecoveryRetry())
                retry.failed(
                    error, admission_id=admission.admission_id,
                    operation_id=admission.authority_operation_id, state=progress,
                )
            else:
                with self._state_guard():
                    self._admission_retries.pop(admission.run_uri, None)
                if outcome.state in {
                    LocalDaemonAdmissionState.SUCCEEDED,
                    LocalDaemonAdmissionState.FAILED,
                    LocalDaemonAdmissionState.CANCELLED,
                }:
                    bulk.discard(("run", admission.run_uri))
                    bulk.discard(("dispatch", admission.run_uri))
                    self._event_observers.offer_audit(admission.run_uri)
                self._record_admission_health(
                    admission.admission_id,
                    (
                        "unavailable"
                        if execution.local_assignment_reconciliation_pending(
                            admission.run_uri
                        )
                        else "healthy"
                    ),
                )
                if outcome.state is LocalDaemonAdmissionState.WAITING:
                    waiting_outcomes[admission.admission_id] = outcome
                else:
                    self._set_state(
                        admission.admission_id,
                        outcome.state,
                        reason=outcome.reason, observed=admission,
                    )
                if preparation.epochs == (self._epoch, self._scheduling_epoch) and outcome.state in {
                    LocalDaemonAdmissionState.ACTIVE,
                    LocalDaemonAdmissionState.WAITING,
                }:
                    schedulable[admission.admission_id] = admission

        # The durable ready query owns the 256-item window.  A cycle may
        # launch at most that many assignments, but a larger pipeline is
        # never rejected merely for having more stages.
        from ._coordinator_run_progress import resume_ready_inputs
        from ._ready_window import ScanYield
        resume_ready_inputs(execution, execution._ready_continuations.take(), schedulable, epochs)
        started_admissions: set[str] = set()
        with bulk.visiting(schedulable.visited_dispatch):
            if time_healthy:
                dispatch_deadline = time.monotonic() + 0.1
                for turn in range(256):
                    if turn and time.monotonic() >= dispatch_deadline:
                        self._wake.set()
                        break
                    if epochs != (self._epoch, self._scheduling_epoch):
                        self._wake.set()
                        break
                    scheduled = execution.schedule_once(schedulable, waiting_outcomes=waiting_outcomes, deadline=dispatch_deadline)
                    if scheduled is ScanYield.MORE:
                        break  # The ready cursor already owns the next wake.
                    if scheduled is None:
                        break
                    admission_id, outcome = scheduled
                    started_admissions.add(admission_id)
                    admission = schedulable[admission_id]
                    self._record_admission_health(
                        admission_id,
                        (
                            "unavailable"
                            if execution.local_assignment_reconciliation_pending(
                                admission.run_uri
                            )
                            else "healthy"
                        ),
                    )
                    # An exempt shared producer may start while its graph cancellation settles.
                    if admission.cancellation_operation_id is None:
                        self._set_state(admission_id, outcome.state, reason=outcome.reason, observed=admission)
                else:
                    # A full batch may leave runnable work. Yield the cycle lock
                    # but do not impose the safety interval on the next batch.
                    self._wake.set()
        for admission_id, outcome in waiting_outcomes.items():
            if admission_id in started_admissions:
                continue
            self._set_state(
                admission_id,
                LocalDaemonAdmissionState.WAITING,
                reason=outcome.reason, observed=(
                    prepared[admission_id].admission if admission_id in prepared
                    else schedulable[admission_id]
                ),
            )

        def visit(admission: LocalDaemonAdmission, *, resume: bool = False) -> bool:
            retry = self._admission_retries.get(admission.run_uri)
            if retry is not None and not retry.ready((admission.revision, epochs[1])):
                return True
            if execution.run_observations.awaiting_read(admission, epochs, bulk):
                return not resume
            if not execution.run_observations.can_start(admission.admission_id):
                return False
            if admission.state is LocalDaemonAdmissionState.PENDING_AUTHORITY:
                execution._scheduling_waits.record(admission.run_uri, None, "preparation")
            return self._contexts.try_submit(
                admission, epochs, execution.prepare_admission_context, resume=resume,
                continuation=execution.continuation_context(admission, epochs) if resume else None,
            )

        # Reconstruct the oldest waiting operation from current durable ownership
        # even when discovery is visiting a different admission page.
        if self._resuming_runs:
            from itertools import islice
            uris = tuple(islice(self._resuming_runs, 32))
            placeholders = ",".join("?" for _ in uris)
            with self._connection() as conn:
                active = {row["run_uri"]: _admission_from_row(row) for row in conn.execute(
                    f"SELECT * FROM managed_admissions WHERE run_uri IN ({placeholders}) "
                    "AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','BLOCKED')", uris,
                )}
            for uri in uris:
                del self._resuming_runs[uri]
                if uri in active and not visit(active[uri], resume=True):
                    self._resuming_runs[uri] = None
                elif uri not in active:
                    bulk.discard(("run", uri))

        visited = self._admission_scan.take(admissions, visit)
        if self._admission_scan.high_water is not None and self._contexts.has_capacity() and execution.run_observations.has_capacity():
            self._wake.set()
        # Reconciliation is an internal operation; retain its bounded
        # nonterminal work result without rebuilding public detail/status.
        return tuple(
            self._admission(admission.admission_id) for admission in visited
        )

    def _lookup_schedulable_admissions(self, identities: set[str]) -> dict[str, LocalDaemonAdmission]:
        placeholders = ",".join("?" for _ in identities)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM managed_admissions WHERE admission_id IN ({placeholders}) "
                "AND state IN ('ACTIVE','WAITING','CANCELLATION_REQUESTED','CANCELLING')", tuple(identities),
            ).fetchall()
        with self._state_guard():
            return {row["admission_id"]: _admission_from_row(row) for row in rows
                    if row["run_uri"] not in self._admission_retries}

    def _retire_inactive_scheduling_owners(self, execution: LocalDaemonExecution) -> None:
        """Retire bounded, positively checked owners independently of discovery pages."""
        from heapq import nsmallest

        bulk = self._result_verifications.bulk
        scopes = bulk.scopes(("run",)) | bulk.scopes(("dispatch",))
        with self._state_guard():
            scopes.update(("retry", run_uri) for run_uri in self._admission_retries)
        after = self._retirement_after
        page = nsmallest(33, (scope for scope in scopes if after is None or scope > after))
        self._retirement_after = page[31] if len(page) > 32 else None
        if not page:
            return
        page = page[:32]
        uris = {scope[1] for scope in page}
        placeholders = ",".join("?" for _ in uris)
        with self._connection() as conn:
            active = {row[0] for row in conn.execute(
                f"SELECT run_uri FROM managed_admissions WHERE coordinator_id=? AND run_uri IN ({placeholders}) "
                "AND state NOT IN ('SUCCEEDED','FAILED','CANCELLED','BLOCKED')",
                (self._coordinator_id, *uris),
            )}
        dispatch_ids = {scope[2] for scope in page if scope[0] == "dispatch" and scope[1] in active}
        ready = execution.stage_work_store.ready_ids(dispatch_ids)
        for scope in page:
            if scope[1] in active and (scope[0] != "dispatch" or scope[2] in ready):
                continue
            if scope[0] == "retry":
                with self._state_guard():
                    self._admission_retries.pop(scope[1], None)
            else:
                bulk.discard(scope)

    def _serve(self) -> None:
        from ._phase_timing import reported_phases

        while not self._stop.is_set():
            observed = self._wake.snapshot()
            try:
                with reported_phases("reconciliation"):
                    self.reconcile_once()
            except Exception:  # keep the durable owner alive and diagnosable
                self._service_error = "reconciliation_unavailable"
            else:
                self._service_error = None
            if not self._stop.is_set():
                now = time.monotonic()
                with self._state_guard():
                    delay = min(
                        (retry.retry_at - now for retry in self._admission_retries.values()
                         if retry.retry_at > now),
                        default=self.config.poll_interval_seconds,
                    )
                    if self._execution is not None:
                        local_retry = self._execution.next_local_retry_at(now)
                        if local_retry is not None:
                            delay = min(delay, local_retry - now)
                target_delay = self._preparations.next_target_delay()
                if target_delay is not None:
                    delay = min(delay, target_delay)
                context_delay = self._contexts.next_delay()
                if context_delay is not None:
                    delay = min(delay, context_delay)
                self._wake.wait_for_change(observed, min(delay, self.config.poll_interval_seconds))

    def _wake_admission(self, run_uri: str) -> None:
        """Retry this run after committed owner progress, not another run's heartbeat."""
        with self._state_guard():
            self._admission_retries.pop(run_uri, None)
            self._context_invalidations.add(run_uri)
        self._wake.set()

    def _submit(
        self,
        request: LocalDaemonAdmissionRequest,
        *,
        direct_principal: str | None = None,
        preparation_operation_id: str | None = None,
        run_operation_id: str | None = None,
        preparation_claim: tuple[object, ...] | None = None,
    ) -> LocalDaemonAdmission:
        from ._coordinator_admission import _submit

        return _submit(
            self, request, direct_principal=direct_principal, preparation_operation_id=preparation_operation_id,
            run_operation_id=run_operation_id, preparation_claim=preparation_claim,
        )


    def _resume_pending_admission_retries(
        self, execution: LocalDaemonExecution
    ) -> None:
        from ._coordinator_admission import _resume_pending_admission_retries

        _resume_pending_admission_retries(self, execution)

    def _repair_cancelled_admissions(self, execution: LocalDaemonExecution) -> None:
        from functools import partial

        workers = execution.cancelled_repair_workers
        now = time.monotonic()
        epochs = (self._epoch, self._scheduling_epoch)
        for identity, _, _, result in workers.completed(0):
            try:
                result.result()
            except Exception:
                self._record_admission_health(identity, "unavailable")
                self._legacy_repair_retries.append((now + self.config.poll_interval_seconds, identity))
            else:
                self._record_admission_health(identity, "healthy")

        def offer(identity: str) -> None:
            workers.submit(identity, identity, epochs, partial(execution.repair_cancelled_admission, identity, epochs))

        if self._legacy_repair_retries and self._legacy_repair_retries[0][0] <= now and not workers.full():
            _, identity = self._legacy_repair_retries.popleft()
            offer(identity)
        if self._legacy_repair_after is None or workers.full():
            return
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT enqueue_sequence, admission_id FROM managed_admissions WHERE {LEGACY_CANCELLED} "
                "AND (enqueue_sequence, admission_id) > (?, ?) ORDER BY enqueue_sequence, admission_id LIMIT 2",
                self._legacy_repair_after,
            ).fetchall()
        for row in rows:
            if workers.full():
                return
            identity = str(row["admission_id"])
            offer(identity)
            self._legacy_repair_after = int(row["enqueue_sequence"]), identity
        if len(rows) < 2:
            self._legacy_repair_after = None

    def _cancel(
        self,
        queue_item_id: str,
        *,
        principal_id: str,
        repair_revision: int | None = None,
    ) -> LocalDaemonAdmission:
        self._require_started()
        if not isinstance(principal_id, str) or not principal_id:
            raise QueueServiceError("cancellation principal is required")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            admission = _request_admission_cancellation(conn, queue_item_id, principal_id=principal_id, repair_revision=repair_revision)
            conn.commit()
        self._wake.set()
        return admission

    def _control_agent(
        self, principal: LocalDaemonPrincipal, control: AgentControl,
        *, condition: Mapping[str, PlainData] | None = None,
    ) -> Mapping[str, PlainData]:
        """Commit one scoped control before the outbound agent may observe it."""

        _public_operation_id(control.operation_id)
        if condition is not None:
            if set(condition) != {"expected_control_id"}:
                raise QueueServiceError("invalid conditional control")
            expected = condition["expected_control_id"]
            if expected is not None:
                if not isinstance(expected, str):
                    raise QueueServiceError("invalid conditional predecessor")
                _public_operation_id(expected)
        authorizer = self._authorizer()
        authorizer.require_operator(
            principal,
            "maintenance" if control.promotion is not None else control.kind.value,
            agent_id=control.agent_id,
            pool=control.pool,
        )
        if control.cancel_active:
            authorizer.require_operator(
                principal,
                "cancel_active",
                agent_id=control.agent_id,
                pool=control.pool,
            )
        encoded = json.dumps(control.value(), sort_keys=True, separators=(",", ":"))
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT principal_id, request_json, state, result_code FROM agent_controls "
                "WHERE operation_id = ?",
                (control.operation_id,),
            ).fetchone()
            condition_key = "agent-control-condition:" + control.operation_id
            retained_condition = conn.execute(
                "SELECT value FROM daemon_metadata WHERE key = ?", (condition_key,)
            ).fetchone()
            if prior is not None:
                if (None if retained_condition is None else json.loads(retained_condition[0])) != condition:
                    raise QueueConflictError("agent control predecessor intent conflicts")
                if (
                    str(prior["principal_id"]) != principal.subject
                    or str(prior["request_json"]) != encoded
                ):
                    raise QueueConflictError("agent control operation conflicts")
                conn.commit()
                return freeze_plain_data(
                    {
                        "operation_id": control.operation_id,
                        "state": str(prior["state"]),
                        "code": prior["result_code"],
                    },
                    path="agent control receipt",
                )
            session = conn.execute(
                "SELECT session_id, agent_id, config_revision, pools_json, state "
                "FROM agent_sessions WHERE session_id = ?",
                (control.expected_session_id,),
            ).fetchone()
            if session is None or str(session["state"]) != "ACTIVE":
                raise QueueConflictError("agent control session is stale")
            if (
                str(session["agent_id"]) != control.agent_id
                or str(session["config_revision"]) != control.expected_config_revision
            ):
                raise QueueConflictError("agent control revision is stale")
            pools = json.loads(str(session["pools_json"]))
            if control.pool is not None and control.pool not in pools:
                raise QueueServiceError("agent control pool is not authorized")
            if control.pool is not None and set(pools) != {control.pool}:
                raise QueueServiceError(
                    "pool-scoped control requires an independently controllable agent"
                )
            if condition is not None:
                current = conn.execute(
                    "SELECT operation_id FROM agent_controls WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
                    (control.expected_session_id,),
                ).fetchone()
                if (None if current is None else current[0]) != condition["expected_control_id"]:
                    raise QueueConflictError("agent control predecessor conflicts")
                conn.execute("INSERT INTO daemon_metadata(key,value) VALUES (?,?)",
                             (condition_key, json.dumps(dict(condition), sort_keys=True)))
            active = conn.execute(
                "SELECT operation_id FROM agent_controls WHERE session_id = ? "
                "AND state IN ('pending_delivery', 'applying') LIMIT 1",
                (control.expected_session_id,),
            ).fetchone()
            if active is not None:
                raise QueueConflictError("another agent control is still in progress")
            if control.promotion is not None:
                from ._profile_promotion import authorize
                authorize(self, conn, control)
            write_status(
                conn, "operation",
                "INSERT INTO agent_controls(operation_id, principal_id, session_id, agent_id, request_json, state, result_code, acknowledged) VALUES (?, ?, ?, ?, ?, 'pending_delivery', NULL, 0)",
                (
                    control.operation_id,
                    principal.subject,
                    control.expected_session_id,
                    control.agent_id,
                    encoded,
                ),
            )
            # Withdrawal is coordinator-owned and happens before delivery.  It
            # changes only future offers; it never releases a durable claim.
            if control.kind.value in {"drain", "reload", "promote"}:
                invalidate_current_offers(conn, control.expected_session_id)
                conn.execute(
                    "UPDATE agent_poll_state SET active = 0 WHERE session_id = ?",
                    (control.expected_session_id,),
                )
            if control.cancel_active:
                from ._action_results import cancel_action_producer

                # Administrative containment stops these exact physical attempts,
                # even when another graph still depends on their results.
                for assignment in conn.execute(
                    "SELECT run_uri, attempt_id FROM remote_assignments "
                    "WHERE session_id = ? AND state != 'RELEASED'",
                    (control.expected_session_id,),
                ).fetchall():
                    cancel_action_producer(conn, str(assignment[0]), str(assignment[1]))
                run_rows = tuple(
                    conn.execute(
                        "SELECT DISTINCT run_uri FROM remote_assignments "
                        "WHERE session_id = ? AND state != 'RELEASED'",
                        (control.expected_session_id,),
                    )
                )
                for run_row in run_rows:
                    run_uri = str(run_row["run_uri"])
                    cancellation_operation_id = (
                        "agent-control-cancel-"
                        + hashlib.sha256(
                            f"{control.operation_id}\0{run_uri}".encode()
                        ).hexdigest()
                    )
                    admission_row = conn.execute("SELECT queue_item_id FROM managed_admissions WHERE run_uri = ?", (run_uri,)).fetchone()
                    if admission_row is not None:
                        _request_admission_cancellation(conn, str(admission_row[0]), principal_id=principal.subject, request_operation_id=cancellation_operation_id)
            conn.commit()
        self._poll_waiters.notify(control.expected_session_id)
        self._wake.set()
        return freeze_plain_data(
            {
                "operation_id": control.operation_id,
                "state": "pending_delivery",
                "code": None,
            },
            path="agent control receipt",
        )

    def _reload_scheduling(
        self,
        principal: LocalDaemonPrincipal,
        request: CoordinatorSchedulingReload,
    ) -> Mapping[str, PlainData]:
        """Install one complete protected coordinator scheduling epoch."""

        _public_operation_id(request.operation_id)
        self._authorizer().require_operator(principal, "scheduling_reload")
        encoded = json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":"))
        execution = self._execution
        if execution is None:
            raise QueueServiceError("coordinator execution is unavailable")
        with self._publication_guards.hold("scheduling-reload"):
            replacement_fingerprint: str | None = None
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                prior = conn.execute(
                    "SELECT principal_id, request_json, state, result_code, "
                    "scheduling_epoch, configuration_revision, "
                    "replacement_fingerprint "
                    "FROM scheduling_reloads WHERE operation_id = ?",
                    (request.operation_id,),
                ).fetchone()
                if prior is not None:
                    if (
                        str(prior["principal_id"]) != principal.subject
                        or str(prior["request_json"]) != encoded
                    ):
                        raise QueueConflictError(
                            "scheduling reload operation conflicts"
                        )
                    if str(prior["state"]) != "applying":
                        conn.commit()
                        return _scheduling_reload_receipt(request.operation_id, prior)
                    if prior["replacement_fingerprint"] is None:
                        raise QueueStorageError(
                            "scheduling reload intent is incomplete"
                        )
                    replacement_fingerprint = str(prior["replacement_fingerprint"])
                if request.expected_scheduling_epoch != self._scheduling_epoch:
                    raise QueueConflictError("scheduling reload epoch is stale")
                conn.commit()

            try:
                loader = self._trusted_scheduling_loader
                if loader is None:
                    raise QueueServiceError(
                        "trusted scheduling configuration loader is unavailable"
                    )
                replacement = loader()
                self._validate_scheduling_replacement(replacement, retirement=request.retirement,
                                                      container_policy_addition=request.container_policy_addition,
                                                      publication_budget_increase=request.publication_budget_increase,
                                                      gpu_policy_contraction=request.gpu_policy_contraction,
                                                      gpu_policy_expansion=request.gpu_policy_expansion)
                candidate_fingerprint = _scheduling_fingerprint(replacement)
                if (
                    replacement_fingerprint is not None
                    and replacement_fingerprint != candidate_fingerprint
                ):
                    raise QueueConflictError(
                        "scheduling reload replacement fingerprint conflicts"
                    )

                def apply_role_reload() -> None:
                    return

                if self._prepare_role_reload is not None:
                    apply_role_reload = self._prepare_role_reload(replacement)
                    if not callable(apply_role_reload):
                        raise QueueServiceError(
                            "trusted role reload plan is unavailable"
                        )
                execution = self._execution
                if execution is None:
                    raise QueueServiceError("coordinator execution is unavailable")
                next_epoch = _scheduling_reload_epoch(
                    request.operation_id, candidate_fingerprint
                )
            except Exception:
                if self._execution is not None:
                    self._execution.local_profile_ready = False
                if replacement_fingerprint is not None:
                    return self._pending_scheduling_reload(request.operation_id)
                return self._reject_scheduling_reload(
                    operation_id=request.operation_id,
                    principal_id=principal.subject,
                    request_json=encoded,
                )
            for _attempt in range(3):
                with self._state_guard():
                    reference_revision = self._scheduling_reference_revision
                try:
                    reload_plan = execution.prepare_scheduling_reload(
                        replacement, next_epoch
                    )
                except Exception:
                    execution.local_profile_ready = False
                    if replacement_fingerprint is not None:
                        return self._pending_scheduling_reload(request.operation_id)
                    return self._reject_scheduling_reload(
                        operation_id=request.operation_id,
                        principal_id=principal.subject,
                        request_json=encoded,
                    )
                with execution.scheduling_reload_guard(), self._state_guard():
                    if reference_revision != self._scheduling_reference_revision:
                        continue
                    if self._execution is not execution or request.expected_scheduling_epoch != self._scheduling_epoch:
                        raise QueueConflictError("scheduling reload epoch changed during preparation")
                    if request.gpu_policy_expansion is not None:
                        from ._agent_gpu_policy import validate_coordinator
                        validate_coordinator(self, replacement, request.gpu_policy_expansion, expansion=True)
                    if request.gpu_policy_contraction is not None:
                        from ._agent_gpu_policy import validate_coordinator
                        validate_coordinator(self, replacement, request.gpu_policy_contraction)
                    if replacement_fingerprint is None:
                        self._record_scheduling_reload_intent(
                            operation_id=request.operation_id,
                            principal_id=principal.subject,
                            request_json=encoded,
                            replacement_fingerprint=candidate_fingerprint,
                            assignment_payload_root_id=replacement.assignment_payload_root_id,
                        )
                    with self._connection() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        revision_row = conn.execute(
                            "SELECT value FROM daemon_metadata "
                            "WHERE key = 'active_configuration_revision'"
                        ).fetchone()
                        if (
                            revision_row is None
                            or not str(revision_row["value"]).isdecimal()
                        ):
                            raise QueueStorageError(
                                "active scheduling configuration is unavailable"
                            )
                        next_revision = int(str(revision_row["value"])) + 1
                        conn.execute(
                            "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                            "VALUES ('scheduling_epoch', ?)",
                            (next_epoch,),
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                            "VALUES ('scheduling_fingerprint', ?)",
                            (candidate_fingerprint,),
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                            "VALUES ('active_configuration_revision', ?)",
                            (str(next_revision),),
                        )
                        write_status(
                            conn, "operation",
                            "UPDATE scheduling_reloads SET state = 'applied', "
                            "result_code = 'applied', scheduling_epoch = ?, "
                            "configuration_revision = ? "
                            "WHERE operation_id = ?",
                            (next_epoch, next_revision, request.operation_id),
                        )
                        conn.commit()
                    execution.apply_scheduling_reload(replacement, reload_plan)
                    # The trusted preparer performs every fallible action before
                    # persistence and returns an assignment-only installer.
                    apply_role_reload()
                    self.config = replacement
                    self._agent_policy = replacement.agent_policy
                    self._scheduling_epoch = next_epoch
                    self._poll_waiters.notify_all()
                break
            else:
                raise QueueConflictError("scheduling references kept changing during reload preparation")
        self._wake.set()
        return freeze_plain_data(
            {
                "operation_id": request.operation_id,
                "state": "applied",
                "code": "applied",
                "scheduling_epoch": next_epoch,
                "configuration_revision": next_revision,
            },
            path="scheduling reload receipt",
        )

    def _recover_unknown(
        self, principal: LocalDaemonPrincipal, request: RecoverUnknownAssignment
    ) -> Mapping[str, PlainData]:
        """Persist and advance one immutable guarded-recovery saga."""

        from ._slurm_retry import PROVIDER_RECOVERY_PREFIX

        _public_operation_id(request.recovery_id)
        self._authorizer().require_operator(principal, "recover_unknown")
        if request.recovery_id.startswith(PROVIDER_RECOVERY_PREFIX):
            raise QueueConflictError("provider recovery operation namespace is reserved")
        return self._admit_guarded_recovery(request, principal.subject)

    def _scheduled_recovery(
        self, request: RecoverUnknownAssignment, principal_id: str, admission: LocalDaemonAdmission,
        *, preparation_current: Callable[[sqlite3.Connection], bool] | None = None,
    ) -> Callable[[], Mapping[str, PlainData]]:
        """Capture scheduling ownership before a worker validates the recovery."""
        from functools import partial

        epochs = self._epoch, self._scheduling_epoch

        def current(conn: sqlite3.Connection) -> bool:
            if epochs != (self._epoch, self._scheduling_epoch):
                return False
            owner = conn.execute(
                "SELECT 1 FROM managed_admissions WHERE admission_id=? AND run_uri=? "
                "AND revision=? AND cancellation_operation_id IS ? "
                "AND (SELECT value FROM daemon_metadata WHERE key='scheduling_epoch') = ?",
                (admission.admission_id, request.run_uri, admission.revision,
                 admission.cancellation_operation_id, epochs[1]),
            ).fetchone()
            return owner is not None and (preparation_current is None or preparation_current(conn))

        return partial(self._admit_guarded_recovery, request, principal_id, current=current)

    def _admit_guarded_recovery(
        self, request: RecoverUnknownAssignment, principal_id: str,
        *, current: Callable[[sqlite3.Connection], bool] | None = None,
    ) -> Mapping[str, PlainData]:
        """Use the same intent, containment evidence and close journal for both owners."""
        encoded = json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        execution = self._execution
        if execution is None:
            raise QueueServiceError("recovery coordinator execution is unavailable")
        with self._publication_guards.hold("recovery:" + request.recovery_id):
            with self._connection() as conn:
                prior = conn.execute(
                    "SELECT principal_id, request_json, request_digest, recorded_at, "
                    "state, evidence_json, result_json FROM recovery_operations "
                    "WHERE recovery_id = ?",
                    (request.recovery_id,),
                ).fetchone()
                if prior is not None:
                    if (
                        str(prior["principal_id"]) != principal_id
                        or str(prior["request_json"]) != encoded
                        or str(prior["request_digest"]) != digest
                    ):
                        raise _RecoveryNotAccepted("recovery operation conflicts")
                    if str(prior["state"]) not in {"pending", "evidence_confirmed"}:
                        return freeze_plain_data(
                            json.loads(str(prior["result_json"])),
                            path="recovery receipt",
                        )
                    recorded_at = str(prior["recorded_at"])
                else:
                    try:
                        execution.validate_recovery_admission(request)
                    except QueueConflictError as exc:
                        raise _RecoveryNotAccepted(str(exc)) from exc
                    conn.execute("BEGIN IMMEDIATE")
                    if current is not None and not current(conn):
                        raise _RecoveryNotAccepted("scheduled recovery owner changed during validation")
                    raced = conn.execute(
                        "SELECT recovery_id FROM recovery_operations "
                        "WHERE recovery_id = ? OR (state IN ('pending', 'evidence_confirmed', 'closed') "
                        "AND json_extract(request_json, '$.assignment_id') = ?)",
                        (request.recovery_id, request.assignment_id),
                    ).fetchone()
                    if raced is not None:
                        raise _RecoveryNotAccepted("recovery operation conflicts")
                    recorded_at = self._accepted_time(conn)
                    write_status(
                        conn, "recovery",
                        "INSERT INTO recovery_operations("
                        "recovery_id, principal_id, request_json, request_digest, "
                        "recorded_at, state, evidence_json, result_json) "
                        "VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?)",
                        (
                            request.recovery_id,
                            principal_id,
                            encoded,
                            digest,
                            recorded_at,
                            json.dumps(
                                {
                                    "recovery_id": request.recovery_id,
                                    "state": "pending",
                                    "evidence": "PENDING",
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                    conn.commit()
            if current is None:
                result = self._advance_recovery(execution, request, recorded_at)
            else:
                # From this commit the existing recovery workers own containment,
                # ordinary-winner checks and close, including after restart.
                result = {"recovery_id": request.recovery_id, "state": "pending", "evidence": "PENDING"}
        self._wake.set()
        return freeze_plain_data(result, path="recovery receipt")

    def _replace_agent_session(
        self, principal: LocalDaemonPrincipal, request: SessionReplacementRequest
    ) -> Mapping[str, PlainData]:
        """Fence one completely classified old session before successor bind."""

        _public_operation_id(request.operation_id)
        execution = self._execution
        if execution is None:
            raise QueueServiceError("replacement coordinator execution is unavailable")
        with self._publication_guards.hold("replacement:" + request.agent_id):
            result = replace_agent_session(self, principal, request)
        self._wake.set()
        return result

    def _advance_recovery(
        self,
        execution: "LocalDaemonExecution",
        request: RecoverUnknownAssignment,
        recorded_at: str,
    ) -> Mapping[str, PlainData]:
        """Advance only from facts already durable at each saga boundary."""

        with self._connection() as conn:
            row = conn.execute(
                "SELECT state, evidence_json, result_json FROM recovery_operations "
                "WHERE recovery_id = ?",
                (request.recovery_id,),
            ).fetchone()
        if row is None:
            raise QueueStorageError("recovery intent is unavailable")
        state = str(row["state"])
        if state not in {"pending", "evidence_confirmed"}:
            result = json.loads(str(row["result_json"]))
            if not isinstance(result, Mapping):
                raise QueueStorageError("recovery result is invalid")
            return cast(Mapping[str, PlainData], result)

        if execution.recovery_has_ordinary_winner(request):
            return self._finish_recovery(
                request.recovery_id,
                {
                    "recovery_id": request.recovery_id,
                    "state": "superseded",
                    "evidence": "ORDINARY_TERMINAL",
                },
            )
        if not execution.recovery_target_is_still_unknown(request):
            return self._finish_recovery(
                request.recovery_id,
                {
                    "recovery_id": request.recovery_id,
                    "state": "unknown",
                    "evidence": "TARGET_STATE_CHANGED",
                },
            )

        evidence: Mapping[str, PlainData] | None = None
        if row["evidence_json"] is not None:
            decoded = freeze_plain_data(
                json.loads(str(row["evidence_json"])), path="recovery evidence"
            )
            if not isinstance(decoded, Mapping):
                raise QueueStorageError("recovery evidence is invalid")
            evidence = decoded
        else:
            evidence_state, resolved = execution.resolve_recovery_evidence(request)
            if evidence_state == "pending":
                return {
                    "recovery_id": request.recovery_id,
                    "state": "pending",
                    "evidence": "PENDING",
                }
            if evidence_state != "contained" or resolved is None:
                return self._finish_recovery(
                    request.recovery_id,
                    {
                        "recovery_id": request.recovery_id,
                        "state": "unknown",
                        "evidence": "UNKNOWN",
                    },
                )
            evidence = resolved
            encoded_evidence = json.dumps(
                thaw_plain_data(evidence, path="recovery evidence"),
                sort_keys=True,
                separators=(",", ":"),
            )
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                updated = write_status(
                    conn, "recovery",
                    "UPDATE recovery_operations SET state = 'evidence_confirmed', "
                    "evidence_json = ? WHERE recovery_id = ? AND state = 'pending'",
                    (encoded_evidence, request.recovery_id),
                ).rowcount
                if updated != 1:
                    raise QueueConflictError("recovery evidence state conflicts")
                conn.commit()

        if execution.recovery_has_ordinary_winner(request):
            return self._finish_recovery(
                request.recovery_id,
                {
                    "recovery_id": request.recovery_id,
                    "state": "superseded",
                    "evidence": "ORDINARY_TERMINAL",
                },
            )
        result = execution.close_recovered_assignment(
            request, evidence, recorded_at=recorded_at
        )
        return self._finish_recovery(request.recovery_id, result)

    def _finish_recovery(
        self, recovery_id: str, result: Mapping[str, PlainData]
    ) -> Mapping[str, PlainData]:
        state = result.get("state")
        if state not in {"closed", "superseded", "unknown"}:
            raise QueueServiceError("recovery result state is invalid")
        encoded = json.dumps(
            thaw_plain_data(result, path="recovery result"),
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            write_status(
                conn, "recovery",
                "UPDATE recovery_operations SET state = ?, result_json = ? "
                "WHERE recovery_id = ?",
                (state, encoded, recovery_id),
            )
            conn.commit()
        return result

    def _resume_pending_recoveries(self, execution: LocalDaemonExecution, *, background: bool = False) -> None:
        from functools import partial

        workers = execution.recovery_workers if background else None
        if workers is not None:
            for identity, assignment_id, state, future in workers.completed(self.config.poll_interval_seconds):
                try:
                    applied = future.result()
                except Exception as error:
                    self._pace_recovery_failure(identity, assignment_id, state, error)
                else:
                    if applied:
                        self._recovery_retries.pop(identity, None)
            if workers.full():
                return
        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT recovery_id, request_json, recorded_at, state, evidence_json FROM recovery_operations "
                    "WHERE (state IN ('pending', 'evidence_confirmed') OR "
                    "(state = 'closed' AND json_extract(request_json, '$.target.kind') = 'slurm')) "
                    "AND (? IS NULL OR recovery_id > ?) ORDER BY recovery_id LIMIT 32",
                    (self._recovery_cursor, self._recovery_cursor),
                )
            )
        deadline = time.monotonic() + 0.25
        scanned = 0
        for row in rows:
            if (workers is not None and workers.full()) or (scanned and time.monotonic() >= deadline):
                break
            scanned += 1
            self._recovery_cursor = str(row["recovery_id"])
            request = RecoverUnknownAssignment.from_dict(
                json.loads(str(row["request_json"]))
            )
            progress = (row["state"], row["evidence_json"])
            retry = self._recovery_retries.get(request.recovery_id)
            if retry is not None and not retry.ready(progress):
                continue
            apply = partial(self._resume_recovery, execution, request, row)
            if workers is not None:
                workers.submit(request.recovery_id, request.assignment_id, progress, apply)
            else:
                try:
                    if apply():
                        self._recovery_retries.pop(request.recovery_id, None)
                except Exception as error:
                    self._pace_recovery_failure(request.recovery_id, request.assignment_id, progress, error)
        if scanned == len(rows) and len(rows) < 32:
            self._recovery_cursor = None
        elif rows and (workers is None or not workers.full()):
            self._wake.set()

    def _resume_recovery(self, execution: LocalDaemonExecution, request: RecoverUnknownAssignment, row: sqlite3.Row) -> bool:
        with self._publication_guards.try_hold("recovery:" + request.recovery_id) as acquired:
            if not acquired:
                return False
            if row["state"] == "closed":
                execution.reconcile_closed_slurm_recovery(request, json.loads(str(row["evidence_json"])))
            else:
                self._advance_recovery(execution, request, str(row["recorded_at"]))
            return True

    def _pace_recovery_failure(self, identity: str, assignment_id: str, state: object, error: Exception) -> None:
        if identity not in self._recovery_retries and len(self._recovery_retries) >= 256:
            self._recovery_retries.pop(next(iter(self._recovery_retries)))
        retry = self._recovery_retries.setdefault(identity, _RecoveryRetry())
        retry.failed(error, operation_id=identity, assignment_id=assignment_id, state=state)

    def _recovery_fences_ordinary_terminal(self, assignment_id: str) -> bool:
        """A provider-driven retry lets an arriving worker result race the close."""
        from ._slurm_retry import PROVIDER_RECOVERY_PREFIX

        with self._connection() as conn:
            rows = conn.execute(
                "SELECT recovery_id, state, principal_id FROM recovery_operations "
                "WHERE state IN ('pending', 'evidence_confirmed', 'closed') "
                "AND json_extract(request_json, '$.assignment_id') = ?", (assignment_id,),
            )
            return any(
                row["state"] == "closed" or (
                    not row["recovery_id"].startswith(PROVIDER_RECOVERY_PREFIX)
                    and not (row["state"] == "pending" and row["principal_id"] == "loom:terminal-recovery")
                )
                for row in rows
            )

    def _recovery_is_settling(self, assignment_id: str) -> bool:
        """Whether close and its existing-policy retry decision are incomplete."""

        with self._connection() as conn:
            return conn.execute(
                "SELECT 1 FROM recovery_operations WHERE state IN ('pending', 'evidence_confirmed') "
                "AND json_extract(request_json, '$.assignment_id') = ? LIMIT 1", (assignment_id,),
            ).fetchone() is not None

    def _recovery_retains_assignment(self, assignment_id: str) -> bool:
        """Whether recovery intentionally keeps this physical owner retained."""

        with self._connection() as conn:
            return conn.execute(
                "SELECT 1 FROM recovery_operations WHERE state IN ('pending', 'evidence_confirmed', 'closed') "
                "AND json_extract(request_json, '$.assignment_id') = ? "
                "AND NOT (state = 'closed' AND json_extract(request_json, '$.target.kind') = 'slurm') LIMIT 1",
                (assignment_id,),
            ).fetchone() is not None

    def _record_scheduling_reload_intent(
        self,
        *,
        operation_id: str,
        principal_id: str,
        request_json: str,
        replacement_fingerprint: str,
        assignment_payload_root_id: str | None,
    ) -> None:
        """Persist the exact fully prepared replacement before activation."""

        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if assignment_payload_root_id is not None:
                retained = conn.execute("SELECT value FROM root_metadata WHERE key = 'assignment_payload_root_id'").fetchone()
                if retained is not None and retained[0] != assignment_payload_root_id:
                    raise QueueConflictError("assignment payload root conflicts with durable deployment binding")
                conn.execute("INSERT OR IGNORE INTO root_metadata(key, value) VALUES ('assignment_payload_root_id', ?)", (assignment_payload_root_id,))
            write_status(
                conn, "operation",
                "INSERT INTO scheduling_reloads(operation_id, principal_id, "
                "request_json, state, result_code, scheduling_epoch, "
                "configuration_revision, replacement_fingerprint) "
                "VALUES (?, ?, ?, 'applying', NULL, NULL, NULL, ?)",
                (
                    operation_id,
                    principal_id,
                    request_json,
                    replacement_fingerprint,
                ),
            )
            conn.commit()

    def _pending_scheduling_reload(self, operation_id: str) -> Mapping[str, PlainData]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT state, result_code, scheduling_epoch, "
                "configuration_revision FROM scheduling_reloads "
                "WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None or str(row["state"]) != "applying":
            raise QueueStorageError("scheduling reload intent is unavailable")
        return _scheduling_reload_receipt(operation_id, row)

    def _reject_scheduling_reload(
        self,
        *,
        operation_id: str,
        principal_id: str,
        request_json: str,
    ) -> Mapping[str, PlainData]:
        with self._connection() as conn:
            write_status(
                conn, "operation",
                "INSERT INTO scheduling_reloads(operation_id, principal_id, "
                "request_json, state, result_code, scheduling_epoch, "
                "configuration_revision, replacement_fingerprint) "
                "VALUES (?, ?, ?, 'failed', 'reload_rejected', ?, NULL, NULL)",
                (operation_id, principal_id, request_json, self._scheduling_epoch),
            )
            conn.commit()
        return freeze_plain_data(
            {
                "operation_id": operation_id,
                "state": "failed",
                "code": "reload_rejected",
                "scheduling_epoch": self._scheduling_epoch,
            },
            path="scheduling reload receipt",
        )

    def _recover_scheduling_reload_intent(
        self, scheduling: Mapping[str, str]
    ) -> dict[str, str]:
        """Finish the single accepted reload whose source matches this process."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT operation_id, request_json, replacement_fingerprint "
                    "FROM scheduling_reloads WHERE state = 'applying'"
                )
            )
        if not rows:
            return dict(scheduling)
        if len(rows) != 1:
            raise QueueStorageError("multiple scheduling reload intents are active")
        row = rows[0]
        configured_fingerprint = _scheduling_fingerprint(self.config)
        if str(row["replacement_fingerprint"]) != configured_fingerprint:
            raise QueueConflictError(
                "protected scheduling configuration conflicts with pending reload"
            )
        try:
            raw_request = json.loads(str(row["request_json"]))
            if not isinstance(raw_request, Mapping):
                raise TypeError
            request = CoordinatorSchedulingReload.from_dict(raw_request)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QueueStorageError("scheduling reload intent is invalid") from exc
        current_epoch = scheduling.get("scheduling_epoch")
        raw_revision = scheduling.get("active_configuration_revision")
        if (
            current_epoch is None
            or request.expected_scheduling_epoch != current_epoch
            or raw_revision is None
            or not raw_revision.isdecimal()
            or int(raw_revision) < 1
        ):
            raise QueueStorageError("scheduling reload intent is stale or invalid")
        next_epoch = _scheduling_reload_epoch(
            request.operation_id, configured_fingerprint
        )
        next_revision = int(raw_revision) + 1
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = {
                str(item["key"]): str(item["value"])
                for item in conn.execute(
                    "SELECT key, value FROM daemon_metadata WHERE key IN "
                    "('scheduling_epoch', 'active_configuration_revision')"
                )
            }
            intent = conn.execute(
                "SELECT state, request_json, replacement_fingerprint "
                "FROM scheduling_reloads WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if (
                active.get("scheduling_epoch") != current_epoch
                or active.get("active_configuration_revision") != raw_revision
                or intent is None
                or str(intent["state"]) != "applying"
                or str(intent["request_json"]) != str(row["request_json"])
                or str(intent["replacement_fingerprint"]) != configured_fingerprint
            ):
                raise QueueStorageError("scheduling reload recovery conflicts")
            conn.execute(
                "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                "VALUES ('scheduling_epoch', ?)",
                (next_epoch,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                "VALUES ('scheduling_fingerprint', ?)",
                (configured_fingerprint,),
            )
            conn.execute(
                "INSERT OR REPLACE INTO daemon_metadata(key, value) "
                "VALUES ('active_configuration_revision', ?)",
                (str(next_revision),),
            )
            write_status(
                conn, "operation",
                "UPDATE scheduling_reloads SET state = 'applied', "
                "result_code = 'applied', scheduling_epoch = ?, "
                "configuration_revision = ? WHERE operation_id = ?",
                (next_epoch, next_revision, request.operation_id),
            )
            conn.commit()
        return {
            **scheduling,
            "scheduling_epoch": next_epoch,
            "scheduling_fingerprint": configured_fingerprint,
            "active_configuration_revision": str(next_revision),
        }

    def _validate_scheduling_replacement(self, replacement: LocalDaemonConfig, *, retirement=None, container_policy_addition=None, publication_budget_increase=None, gpu_policy_contraction=None, gpu_policy_expansion=None) -> None:
        if not isinstance(replacement, LocalDaemonConfig):
            raise QueueServiceError("trusted scheduling configuration is invalid")
        if (
            replacement.deployment_configuration_fingerprint
            != self.config.deployment_configuration_fingerprint
        ):
            raise QueueConflictError(
                "scheduling reload cannot replace immutable role configuration"
            )
        immutable = (
            "coordinator_root",
            "agent_root",
            "run_store_root",
        )
        if any(
            getattr(replacement, name) != getattr(self.config, name)
            for name in immutable
        ) or (
            replacement.resident_worker_launch_profile
            != self.config.resident_worker_launch_profile
        ):
            raise QueueConflictError(
                "scheduling reload cannot replace process or agent-owned configuration"
            )
        if self.config.assignment_payload_root_id is not None and replacement.assignment_payload_root_id != self.config.assignment_payload_root_id:
            raise QueueConflictError("scheduling reload cannot replace assignment payload root")
        current_roots = self.config.coordinator_shared_roots
        replacement_roots = replacement.coordinator_shared_roots
        from .shared_execution import _readonly_root_relocations

        if gpu_policy_expansion is not None:
            from ._agent_gpu_policy import validate_coordinator
            validate_coordinator(self, replacement, gpu_policy_expansion, expansion=True)
            return
        if gpu_policy_contraction is not None:
            from ._agent_gpu_policy import validate_coordinator
            validate_coordinator(self, replacement, gpu_policy_contraction)
            return
        if publication_budget_increase is not None:
            self._validate_coordinator_retirement(replacement, publication_budget_increase, budget_increase=True)
            return
        if container_policy_addition is not None:
            self._validate_coordinator_retirement(replacement, container_policy_addition, addition=True)
            return
        if retirement is not None:
            self._validate_coordinator_retirement(replacement, retirement)
            return
        relocations = _readonly_root_relocations(current_roots, replacement_roots)
        if relocations:
            # Reload already holds the cycle lock shared with admission and
            # maintenance. Same logical read-only storage may move only at a
            # settled, closed gate; mutable output mappings remain fixed.
            from ._maintenance import observe

            gate = observe(self)
            if gate["state"] != "closed" or not gate["settled"] or gate["checks"]:
                raise QueueConflictError("read-only root relocation requires settled maintenance")
        if replacement.agent_policy != self._agent_policy:
            with self._connection() as conn:
                active = conn.execute(
                    "SELECT 1 FROM agent_sessions WHERE state = 'ACTIVE' LIMIT 1"
                ).fetchone()
            if active is not None:
                current = self._agent_policy
                candidate = replacement.agent_policy
                current_agents = {rule.agent_id for rule in current.agents}
                removed = [rule for rule in current.agents if rule not in candidate.agents]
                retired = set()
                with self._connection() as conn:
                    for rule in removed:
                        states = [row[0] for row in conn.execute(
                            "SELECT state FROM agent_sessions WHERE agent_id=?", (rule.agent_id,)
                        )]
                        if states and "RETIRED_CLEAN" in states and all(state in {"RETIRED_CLEAN", "REPLACED"} for state in states):
                            retired.add(rule.agent_id)
                # Policy revisions fence sessions and retained proofs. Enrollment
                # may add a distinct worker or revoke a cleanly retired one,
                # without changing that generation or any live worker's rule.
                additive = (
                    candidate.revision == current.revision
                    and all(rule in candidate.agents or rule.agent_id in retired for rule in current.agents)
                    and all(
                        rule in current.agents or rule.agent_id not in current_agents
                        for rule in candidate.agents
                    )
                )
                capability_addition = (
                    replace(candidate, agents=current.agents) == current
                    and len(candidate.agents) == len(current.agents)
                    and all(
                        any(
                            replace(new, capabilities=old.capabilities) == old
                            and set(old.capabilities).issubset(new.capabilities)
                            for new in candidate.agents
                        )
                        for old in current.agents
                    )
                )
                if capability_addition:
                    from ._maintenance import observe

                    gate = observe(self)
                    capability_addition = (
                        gate["state"] == "closed"
                        and gate["settled"]
                        and not gate["checks"]
                    )
                # Expanding the protected allow-list does not grant capabilities
                # to retained sessions. Native promotion owns that later change.
                if not (additive or capability_addition):
                    raise QueueConflictError(
                        "scheduling reload cannot replace credentials for a live agent session"
                    )

    def _validate_coordinator_retirement(self, replacement, binding, *, addition=False, budget_increase=False):
        from ._maintenance import observe

        gate = observe(self)
        if (gate["state"] != "closed" or not gate["settled"] or gate["checks"]
            or gate["maintenance_id"] != binding["maintenance_id"]
            or gate["intent_digest"] != binding["maintenance_intent_digest"]
            or gate["revision"] != binding["expected_gate_revision"]):
            raise QueueConflictError("coordinator retirement requires exact settled maintenance")
        if addition:
            from ._container_policy_addition import validate_coordinator
            validate_coordinator(self.config, replacement)
            return
        if budget_increase:
            from ._publication_budget_increase import validate_coordinator
            validate_coordinator(self.config, replacement)
            return
        mutable = {"shared_roots", "preparation_policy", "remote_profiles",
                   "container_capabilities", "active_configuration_fingerprint"}
        if self.config.agent_root is not None or any(
            getattr(self.config, item.name) != getattr(replacement, item.name)
            for item in fields(LocalDaemonConfig) if item.name not in mutable
        ):
            raise QueueConflictError("coordinator retirement cannot change unrelated role configuration")
        _validate_retired_coordinator_execution(self.config, replacement)

    def _wait(
        self, queue_item_id: str, *, timeout_seconds: float | None
    ) -> LocalDaemonAdmission:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise QueueServiceError("timeout_seconds must be non-negative")
        deadline = (
            None if timeout_seconds is None else time.monotonic() + timeout_seconds
        )
        terminal = {
            LocalDaemonAdmissionState.SUCCEEDED,
            LocalDaemonAdmissionState.FAILED,
            LocalDaemonAdmissionState.CANCELLED,
            LocalDaemonAdmissionState.BLOCKED,
        }
        with self._status_changed.subscribe("queue_item:" + queue_item_id) as signal:
            while True:
                observed = signal.snapshot()
                self._require_wait_running()
                admission = self._admission_for_queue_item(queue_item_id)
                if admission.state in terminal:
                    return admission
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(
                        "managed local admission did not reach terminal state"
                    )
                self._wait_for_status_change(signal, observed, deadline)

    def _cancellation_operation_id(self, admission_id: str) -> str | None:
        return self._admission(admission_id).cancellation_operation_id

    def _resolve_admission_priority(self, run_uri: str) -> int:
        """Resolve site policy before entering the durable admission transaction."""

        try:
            return _run_priority(self.config.admission_priority_resolver(run_uri))
        except Exception as exc:
            if isinstance(exc, QueueServiceError):
                raise
            raise QueueServiceError(
                "protected admission priority policy failed"
            ) from exc

    def _next_enqueue_sequence(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = 'admission_enqueue_sequence'"
        ).fetchone()
        try:
            previous = 0 if row is None else int(cast(str, row["value"]))
        except (TypeError, ValueError) as exc:
            raise QueueStorageError("admission enqueue sequence is invalid") from exc
        if previous < 0:
            raise QueueStorageError("admission enqueue sequence is invalid")
        sequence = previous + 1
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata(key, value) VALUES "
            "('admission_enqueue_sequence', ?)",
            (str(sequence),),
        )
        return sequence

    def _activate_admission(self, admission_id: str) -> bool:
        with self._connection() as conn:
            changed = write_status(
                conn, "admission",
                "UPDATE managed_admissions SET state = ?, blocked_reason = NULL, "
                "revision = revision + 1 "
                "WHERE admission_id = ? AND cancellation_operation_id IS NULL "
                "AND (state != ? OR blocked_reason IS NOT NULL) AND state IN (?, ?, ?)",
                (
                    LocalDaemonAdmissionState.ACTIVE.value,
                    admission_id,
                    LocalDaemonAdmissionState.ACTIVE.value,
                    LocalDaemonAdmissionState.PENDING_AUTHORITY.value,
                    LocalDaemonAdmissionState.WAITING.value,
                    LocalDaemonAdmissionState.ACTIVE.value,
                ),
            )
            conn.commit()
            return changed.rowcount > 0

    def _admission_for_queue_item(self, queue_item_id: str) -> LocalDaemonAdmission:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE queue_item_id = ?",
                (queue_item_id,),
            ).fetchone()
        if row is None:
            raise AdmissionNotFoundError("managed admission was not found")
        return _admission_from_row(row)

    def _admission(self, admission_id: str) -> LocalDaemonAdmission:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM managed_admissions WHERE admission_id = ?",
                (admission_id,),
            ).fetchone()
        if row is None:
            raise AdmissionNotFoundError("managed admission was not found")
        return _admission_from_row(row)

    def _set_state(
        self,
        admission_id: str,
        state: LocalDaemonAdmissionState,
        *,
        reason: str | None,
        observed: LocalDaemonAdmission | None = None,
    ) -> None:
        with self._connection() as conn:
            changed = write_status(
                conn, "admission",
                "UPDATE managed_admissions SET state = ?, blocked_reason = ?, "
                "revision = revision + 1 WHERE admission_id = ? AND "
                "(state != ? OR blocked_reason IS NOT ?) "
                "AND (? OR cancellation_operation_id IS ?)",
                (state.value, reason, admission_id, state.value, reason,
                 observed is None, None if observed is None else observed.cancellation_operation_id),
            )
            conn.commit()
        if state is LocalDaemonAdmissionState.SUCCEEDED and changed.rowcount:
            from ._phase_timing import milestone
            milestone("admission_succeeded", admission_id=admission_id)

    def _record_admission_health(self, admission_id: str, health: str) -> None:
        if health not in {"healthy", "failed", "unavailable"}:
            raise QueueServiceError("admission reconciliation health is invalid")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                observed_at = self._accepted_time(conn)
            except QueueServiceError:
                row = conn.execute(
                    "SELECT value FROM daemon_metadata "
                    "WHERE key = 'accepted_time_high_water'"
                ).fetchone()
                if row is None:
                    raise
                observed_at = str(row["value"])
            conn.execute(
                "INSERT INTO admission_reconciliation_health("
                "admission_id, health, observed_at) VALUES (?, ?, ?) "
                "ON CONFLICT(admission_id) DO UPDATE SET health = excluded.health, "
                "observed_at = excluded.observed_at",
                (admission_id, health, observed_at),
            )
            conn.commit()

    def _record_admission_health_for_run(self, run_uri: str, health: str) -> None:
        """Join retained exact assignment work to its one admission owner."""

        with self._connection() as conn:
            rows = tuple(
                conn.execute(
                    "SELECT admission_id FROM managed_admissions WHERE run_uri = ?",
                    (run_uri,),
                )
            )
        if len(rows) != 1:
            raise QueueConflictError("retained assignment admission is unavailable")
        self._record_admission_health(str(rows[0]["admission_id"]), health)

    def _sample_clock_health(self, *, wait_for_writer: bool = True) -> bool:
        from ._coordinator_transactions import short_write

        def sample(conn: sqlite3.Connection) -> bool:
            self._accepted_time(conn)
            return True

        try:
            return short_write(self, sample, wait_for_writer=wait_for_writer)
        except QueueServiceError:
            # An accepted-time regression commits its diagnostic before raising.
            return False
        except sqlite3.OperationalError as exc:
            if wait_for_writer or (getattr(exc, "sqlite_errorcode", 0) & 255) != sqlite3.SQLITE_BUSY:
                raise
            # This turn cannot establish clock health. Recheck before the next
            # dispatch instead of joining the writer or marking time degraded.
            return False

    def _recover_time(
        self, principal: LocalDaemonPrincipal, request: TimeRecoveryRequest
    ) -> TimeRecoveryReceipt:
        _public_operation_id(request.operation_id)
        self._authorizer().require_operator(principal, "recover_time")
        encoded = json.dumps(
            request.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        from ._coordinator_transactions import short_write

        def apply(conn: sqlite3.Connection) -> tuple[TimeRecoveryReceipt, bool]:
            self._authorizer().require_operator(principal, "recover_time")
            existing = conn.execute(
                "SELECT principal_id, request_digest, result_json FROM time_recoveries "
                "WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["principal_id"]) != principal.subject
                    or str(existing["request_digest"]) != digest
                ):
                    raise QueueConflictError(
                        "time recovery operation was reused with different content"
                    )
                value = json.loads(str(existing["result_json"]))
                if not isinstance(value, Mapping):
                    raise QueueStorageError("time recovery receipt is invalid")
                return TimeRecoveryReceipt.from_dict(value), False
            state = {
                str(row["key"]): str(row["value"])
                for row in conn.execute(
                    "SELECT key, value FROM daemon_metadata WHERE key IN "
                    "('accepted_time_high_water', 'accepted_time_health', "
                    "'accepted_time_revision')"
                )
            }
            current_epoch = self._epoch or ""
            revision = int(state.get("accepted_time_revision", "0"))
            if state.get("accepted_time_health") != "degraded":
                raise QueueConflictError(
                    "coordinator accepted-time is not degraded"
                )
            if request.expected_time_revision != revision:
                raise QueueConflictError("time recovery revision is stale")
            if request.expected_coordinator_epoch != current_epoch:
                raise QueueConflictError("time recovery coordinator epoch is stale")
            high_water = state.get("accepted_time_high_water")
            if high_water is None:
                raise QueueStorageError("accepted-time high-water is unavailable")
            now = self._clock()
            parse_timestamp(now)
            if parse_timestamp(now) < parse_timestamp(high_water):
                raise QueueConflictError(
                    "coordinator clock is still below accepted-time high-water"
                )
            new_epoch = f"coordinator-epoch-{uuid4()}"
            next_revision = revision + 1
            receipt = TimeRecoveryReceipt(
                operation_id=request.operation_id,
                request_digest=digest,
                recovered_at=now,
                previous_coordinator_epoch=current_epoch,
                coordinator_epoch=new_epoch,
                time_revision=next_revision,
            )
            conn.execute(
                "INSERT INTO coordinator_epochs(epoch, started_at) VALUES (?, ?)",
                (new_epoch, now),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO daemon_metadata(key, value) VALUES (?, ?)",
                (
                    ("accepted_time_high_water", now),
                    ("accepted_time_health", "healthy"),
                    ("accepted_time_revision", str(next_revision)),
                ),
            )
            conn.execute(
                "DELETE FROM daemon_metadata WHERE key = 'accepted_time_diagnostic'"
            )
            conn.execute("UPDATE agent_offers SET current = 0 WHERE current = 1")
            write_status(
                conn, "operation",
                "INSERT INTO time_recoveries(operation_id, principal_id, "
                "request_json, request_digest, result_json) VALUES (?, ?, ?, ?, ?)",
                (
                    request.operation_id,
                    principal.subject,
                    encoded,
                    digest,
                    json.dumps(
                        receipt.to_dict(),
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                ),
            )
            return receipt, True

        def committed(result: tuple[TimeRecoveryReceipt, bool]) -> None:
            receipt, applied = result
            if applied:
                self._epoch = receipt.coordinator_epoch
                if self._execution is not None:
                    self._execution.coordinator_epoch = receipt.coordinator_epoch
                self._poll_waiters.notify_all()
                self._wake.set()

        receipt, _ = short_write(self, apply, committed=committed)
        return receipt

    def _require_started(self) -> str:
        if self._coordinator_lock is None or self._coordinator_id is None:
            raise QueueServiceError("local daemon is not started")
        return self._coordinator_id

    def _require_agent_id(self) -> str:
        if self._agent_lock is None or self._agent_id is None:
            raise QueueServiceError("local daemon is not started")
        return self._agent_id

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            conn = (
                sqlite3.connect(
                    f"{self.config.control_database.resolve().as_uri()}?mode=rw",
                    uri=True, timeout=30, factory=_ChangeConnection,
                ) if self.config.storage is None else
                self.config.connect_database(self.config.control_database, factory=_ChangeConnection)
            )
            cast(_ChangeConnection, conn).on_commit = self._status_changed.notify
            conn.row_factory = sqlite3.Row
            expected = self._coordinator_id
            if expected is not None:
                row = conn.execute(
                    "SELECT value FROM root_metadata WHERE key = 'stable_id'"
                ).fetchone()
                if row is None or str(row["value"]) != expected:
                    raise QueueStorageError("coordinator control identity is invalid")
        except (OSError, sqlite3.Error):
            # A missing retained control store is unavailable.  Once a file is
            # present under a live locked root, however, an open/query failure
            # cannot prove that it is the stable coordinator store; report the
            # same fail-closed identity diagnostic as an explicit mismatch.
            diagnostic = (
                "coordinator control identity is invalid"
                if self._coordinator_id is not None
                and self.config.control_database.is_file()
                else "coordinator control state is unavailable"
            )
            raise QueueStorageError(diagnostic) from None
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _agent_connection(self) -> Iterator[sqlite3.Connection]:
        agent_root = self.config.agent_root
        if agent_root is None:
            raise QueueStorageError("coordinator has no local agent control state")
        try:
            conn = (
                sqlite3.connect(
                    f"{agent_root.joinpath('control.sqlite').resolve().as_uri()}?mode=rw",
                    uri=True, timeout=30,
                ) if self.config.storage is None else
                self.config.connect_database(agent_root / "control.sqlite")
            )
            conn.row_factory = sqlite3.Row
            expected = self._agent_id
            if expected is not None:
                row = conn.execute(
                    "SELECT value FROM root_metadata WHERE key = 'stable_id'"
                ).fetchone()
                if row is None or str(row["value"]) != expected:
                    raise QueueStorageError("agent control identity is invalid")
        except (OSError, sqlite3.Error):
            raise QueueStorageError("agent control state is unavailable") from None
        try:
            yield conn
        finally:
            conn.close()

    def _accepted_time(self, conn: sqlite3.Connection) -> str:
        """Advance accepted time inside the caller's immediate write transaction.

        Acquire the writer reservation before sampling the clock and retain it
        through commit or rollback. A genuine clock fault commits degraded health
        before raising, so caller rollback cannot erase the safety guard.
        """
        now = self._clock()
        parse_timestamp(now)
        state = {
            str(row["key"]): str(row["value"])
            for row in conn.execute(
                "SELECT key, value FROM daemon_metadata WHERE key IN "
                "('accepted_time_high_water', 'accepted_time_health', "
                "'accepted_time_diagnostic', 'accepted_time_revision')"
            )
        }
        if state.get("accepted_time_health") == "degraded":
            raise _AcceptedTimeError(
                state.get("accepted_time_diagnostic", "clock_regressed"),
                int(state.get("accepted_time_revision", "0")),
            )
        previous = state.get("accepted_time_high_water")
        if previous is not None and parse_timestamp(now) < parse_timestamp(previous):
            self._degrade_time(conn, "clock_regressed")
            conn.commit()
            self._poll_waiters.notify_all()
            _LOGGER.warning("coordinator clock guard: %s", json.dumps({
                "diagnostic": "clock_regressed", "sampled_at": now,
                "previous_high_water": previous,
                "time_revision": int(state.get("accepted_time_revision", "0")) + 1,
            }, sort_keys=True))
            raise _AcceptedTimeError(
                "clock_regressed", int(state.get("accepted_time_revision", "0")) + 1,
            )
        if (
            previous is not None
            and (parse_timestamp(now) - parse_timestamp(previous)).total_seconds()
            > self.config.max_accepted_time_step_seconds
        ):
            self._degrade_time(conn, "clock_step_exceeds_policy")
            conn.commit()
            self._poll_waiters.notify_all()
            _LOGGER.warning("coordinator clock guard: %s", json.dumps({
                "diagnostic": "clock_step_exceeds_policy", "sampled_at": now,
                "previous_high_water": previous,
                "time_revision": int(state.get("accepted_time_revision", "0")) + 1,
            }, sort_keys=True))
            raise _AcceptedTimeError(
                "clock_step_exceeds_policy", int(state.get("accepted_time_revision", "0")) + 1,
            )
        accepted = now
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) "
            "VALUES ('accepted_time_high_water', ?)",
            (accepted,),
        )
        return accepted

    @staticmethod
    def _degrade_time(conn: sqlite3.Connection, diagnostic: str) -> None:
        health = conn.execute(
            "SELECT value FROM daemon_metadata WHERE key = 'accepted_time_health'"
        ).fetchone()
        if health is not None and str(health["value"]) == "degraded":
            return
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) VALUES "
            "('accepted_time_health', 'degraded')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) VALUES "
            "('accepted_time_diagnostic', ?)",
            (diagnostic,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO daemon_metadata (key, value) VALUES "
            "('accepted_time_revision', COALESCE((SELECT CAST(value AS INTEGER) + 1 "
            "FROM daemon_metadata WHERE key = 'accepted_time_revision'), 1))"
        )

    def _accepted_snapshot(self) -> tuple[str, int]:
        """Return one monotonic accepted timestamp and whole-second snapshot time."""

        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            accepted = self._accepted_time(conn)
            conn.commit()
        return accepted, int(parse_timestamp(accepted).timestamp())


@dataclass(frozen=True, slots=True)
class LocalDaemonClientView:
    _daemon: LocalDaemon
    _principal: LocalDaemonPrincipal

    def submit(self, request: LocalDaemonAdmissionRequest) -> LocalDaemonAdmission:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._submit(request, direct_principal=self._principal.subject)

    def status(self) -> DaemonStatus:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.status()

    def list_queue(self, selection: QueueSelection, limit: int, cursor: str | None) -> dict[str, PlainData]:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        coordinator_id = self._daemon._require_started()
        with self._daemon._connection() as conn:
            page = queue_page(conn, coordinator_id, self._daemon._clock(), selection, limit, cursor)
        rows = cast(list[dict[str, PlainData]], page["admissions"])
        reasons = self._daemon._waiting_reasons([(str(row["admission_id"]), str(row["state"]), cast(str | None, row.get("blocked_reason"))) for row in rows])
        for row in rows:
            if row["admission_id"] in reasons:
                row["blocked_reason"] = reasons[str(row["admission_id"])]
        return page

    def admissions(
        self, *, limit: int = _MAX_ADMISSION_PAGE_SIZE, cursor: str | None = None
    ) -> AdmissionPage:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.admissions(limit=limit, cursor=cursor)

    def admission(self, admission_id: str) -> LocalDaemonAdmissionDetail:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.admission(admission_id)

    def admission_for_queue_item(self, queue_item_id: str) -> LocalDaemonAdmission:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.admission_for_queue_item(queue_item_id)

    def agents(
        self, *, limit: int = _MAX_ADMISSION_PAGE_SIZE, cursor: str | None = None,
        include_capacity: bool = False,
    ) -> AgentPage:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.agents(limit=limit, cursor=cursor, include_capacity=include_capacity)

    def agent(self, agent_id: str, *, include_capacity: bool = False) -> AgentProjection:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.agent(agent_id, include_capacity=include_capacity)

    def operation(self, operation_id: str) -> LocalDaemonOperation:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.operation(operation_id)

    def prepare_run(self, request: "PrepareRunRequest") -> LocalDaemonOperation:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.prepare_run(request, principal_id=self._principal.subject)

    def start_run(self, request: "RunRequest") -> LocalDaemonOperation:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.start_run(request, principal_id=self._principal.subject)

    def cancel_run_operation(self, operation_id: str) -> LocalDaemonOperation:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.cancel_run_operation(
            operation_id, principal_id=self._principal.subject
        )

    def cancel_preparation(self, operation_id: str) -> LocalDaemonOperation:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.cancel_preparation(
            operation_id, principal_id=self._principal.subject
        )

    def wait_operation(
        self, operation_id: str, *, timeout: float | None
    ) -> OperationWaitResult:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.wait_operation(operation_id, timeout=timeout)

    def wait_admission(
        self, admission_id: str, *, expected_revision: int, timeout: float | None
    ) -> AdmissionWaitResult:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon.wait_admission(
            admission_id, expected_revision=expected_revision, timeout=timeout
        )

    def wait(
        self, queue_item_id: str, *, timeout_seconds: float | None = None
    ) -> LocalDaemonAdmission:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._wait(queue_item_id, timeout_seconds=timeout_seconds)

    def cancel(self, queue_item_id: str) -> LocalDaemonAdmission:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.CLIENT)
        return self._daemon._cancel(queue_item_id, principal_id=self._principal.subject)


@dataclass(frozen=True, slots=True)
class LocalDaemonOperatorView:
    _daemon: LocalDaemon
    _principal: LocalDaemonPrincipal

    def status(self) -> DaemonStatus:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon.status()

    def observe_status(self) -> "OperatorObservation":
        """Read accepted coordinator configuration with owner-local freshness."""
        from .operations import _coordinator_observation
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return _coordinator_observation(self._daemon)

    def observe_agent(self, agent_id: str) -> "OperatorObservation":
        """Read one session, its retained offer and independent drain state."""
        from .operations import _agent_observation
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return _agent_observation(self._daemon, agent_id)

    def observe_assignment(self, assignment_id: str) -> "OperatorObservation":
        """Read one assignment's coordinator acknowledgement and release proof."""
        from .operations import _assignment_observation
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return _assignment_observation(self._daemon, assignment_id)

    def observe_maintenance(self) -> Mapping[str, PlainData]:
        """Read the durable gate, owner/revision and finite authorized checks."""
        from ._maintenance import observe
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return observe(self._daemon)

    def maintenance(self, control: Mapping[str, object], *, expected_coordinator_id: str) -> Mapping[str, PlainData]:
        """Apply/replay an exact revision-guarded maintenance owner control."""
        from ._maintenance import mutate
        return mutate(self._daemon, self._principal, control, expected_coordinator_id)

    def maintenance_operation(self, operation_id: str) -> Mapping[str, PlainData]:
        """Resolve one exact control after a lost reply, without another mutation."""
        from ._maintenance import operation
        self._daemon._authorizer().require_operator(self._principal, "maintenance")
        return operation(self._daemon, operation_id)

    def observe_control(self, operation_id: str) -> Mapping[str, PlainData]:
        """Read one authorized exact agent control, including its intent digest."""
        import hashlib
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        with self._daemon._connection() as conn:
            row = conn.execute("SELECT request_json, state, result_code, acknowledged FROM agent_controls WHERE operation_id = ?", (operation_id,)).fetchone()
        if row is None:
            raise QueueServiceError("managed operation was not found")
        control = AgentControl.from_value(json.loads(row["request_json"]))
        self._daemon._authorizer().require_operator(self._principal, "maintenance" if control.promotion is not None else control.kind.value, agent_id=control.agent_id, pool=control.pool)
        from .operations import control_intent_digest
        with self._daemon._connection() as conn:
            retained = conn.execute("SELECT value FROM daemon_metadata WHERE key = ?", ("agent-control-condition:" + operation_id,)).fetchone()
        condition = None if retained is None else json.loads(retained[0])
        intent_digest = hashlib.sha256(row["request_json"].encode()).hexdigest() if condition is None else control_intent_digest({"control": control.value(), "condition": condition})
        return {"operation_id": operation_id, "intent_digest": intent_digest, "condition": condition, "state": row["state"], "code": row["result_code"], "acknowledged": bool(row["acknowledged"]), "mutation_outcome": "applied"}

    def retire(
        self, operation_id: str, expected_coordinator_id: str
    ) -> Mapping[str, PlainData]:
        """Permanently fence an idle pure coordinator for operator removal."""
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        self._daemon._authorizer().require_operator(
            self._principal, "scheduling_reload"
        )
        return self._daemon._lifetime.retire_explicit(
            operation_id, expected_coordinator_id
        )

    def agent_retirement_ready(self, agent_id: str, session_id: str) -> bool:
        """Observe coordinator-owned references; local owners still need proof."""
        from .agent_sessions import _coordinator_references_empty

        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        self._daemon._authorizer().require_operator(
            self._principal, "drain", agent_id=agent_id
        )
        with self._daemon._cycle_lock:
            if self._daemon.agent(agent_id).session_id != session_id:
                raise QueueConflictError("agent retirement session changed")
            with self._daemon._connection() as conn:
                return _coordinator_references_empty(conn, session_id)

    def reconcile_once(self) -> tuple[LocalDaemonAdmission, ...]:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon.reconcile_once()

    def control_agent(self, control: AgentControl, *, condition: Mapping[str, PlainData] | None = None) -> Mapping[str, PlainData]:
        """Accept a control, optionally only after the exact expected predecessor.

        ``condition={"expected_control_id": None}`` expects no prior control;
        omission preserves unconditional operator behavior. Exact replay retains
        its original condition and never reapplies policy over a later control.
        """
        with self._daemon._cycle_lock:
            return self._daemon._control_agent(self._principal, control, condition=condition)

    def reload_scheduling(
        self, request: CoordinatorSchedulingReload
    ) -> Mapping[str, PlainData]:
        return self._daemon._reload_scheduling(self._principal, request)

    def recover_unknown(
        self, request: RecoverUnknownAssignment
    ) -> Mapping[str, PlainData]:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon._recover_unknown(self._principal, request)

    def recover_time(self, request: TimeRecoveryRequest) -> TimeRecoveryReceipt:
        return self._daemon._recover_time(self._principal, request)

    def replace_agent_session(
        self, request: SessionReplacementRequest
    ) -> Mapping[str, PlainData]:
        self._daemon._require_view_role(self._principal, LocalDaemonRole.OPERATOR)
        return self._daemon._replace_agent_session(self._principal, request)


@dataclass(frozen=True, slots=True)
class LocalDaemonSlurmBootstrapView:
    """Least-privilege view for one protected SLURM profile credential."""

    _daemon: LocalDaemon
    _principal: LocalDaemonPrincipal

    def _execution(self):  # type: ignore[no-untyped-def]
        _require_role(self._principal, LocalDaemonRole.SLURM_BOOTSTRAP)
        execution = self._daemon._execution
        if execution is None:
            raise QueueServiceError("SLURM coordinator execution is unavailable")
        return execution

    def handshake(self) -> Mapping[str, PlainData]:
        execution = self._execution()
        from ._slurm_start import SLURM_REPLAYABLE_START_CAPABILITY
        from .shared_execution import STAGING_CONTINUATION_CAPABILITY
        profile = execution._slurm_profile_for_principal(
            self._principal.subject, self._principal.credential_id
        )
        return freeze_plain_data(
            {
                "protocol_version": "1",
                "capabilities": ["slurm-ready-stage-bootstrap-v1", STAGING_CONTINUATION_CAPABILITY, *(
                    [SLURM_REPLAYABLE_START_CAPABILITY]
                    if execution.slurm_assignments.schema_version >= 6 else []
                )],
                "coordinator_id": self._daemon._require_started(),
                "coordinator_epoch": self._daemon._epoch or "",
                "role": LocalDaemonRole.SLURM_BOOTSTRAP.value,
                "profile_id": profile.profile_id,
                "profile_descriptor": profile.descriptor.to_dict(),
                "credential_policy_revision": profile.credential_policy_revision,
            },
            path="SLURM bootstrap handshake",
        )

    def register(
        self,
        *,
        operation_id: str,
        request_digest: str,
        job_id: str,
        cluster: str | None,
        incarnation: str,
        capability: str,
    ) -> Mapping[str, PlainData]:
        record = self._execution().slurm_register(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            operation_id=operation_id,
            request_digest=request_digest,
            job_id=job_id,
            cluster=cluster,
            incarnation=incarnation,
            capability=capability,
        )
        profile = self._execution()._slurm_profile(
            record.assignment.profile_id,
            record.assignment.profile_configuration_fingerprint,
        )
        return freeze_plain_data(
            {
                "assignment_id": record.assignment.assignment_id,
                "operation_id": record.assignment.operation_id,
                "issuer_epoch": record.issuer_epoch,
                "job_id": record.job_id,
                "cluster": record.cluster,
                "incarnation": record.bootstrap_incarnation,
                "delivery": record.delivery.to_dict(),
                "result_identity": self._execution().slurm_result_identity(record),
                "result_storage": dict(profile.result_storage or {}),
                **({"submitted_container_policy": thaw_plain_data(profile.submitted_container_policy)}
                   if record.delivery.submitted_execution is not None else {}),
            },
            path="SLURM bootstrap registration",
        )

    def input_chunk(
        self,
        assignment_id: str,
        incarnation: str,
        transfer_id: str,
        *,
        offset: int,
    ) -> tuple[bytes, bool]:
        return self._execution().slurm_input_chunk(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            transfer_id=transfer_id,
            offset=offset,
        )

    def inputs_ready(self, assignment_id: str, incarnation: str) -> bool:
        """Acknowledge durable inputs, or return false while submission is pending."""
        return self._execution().slurm_inputs_ready(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
        )

    def grant(self, assignment_id: str, incarnation: str) -> str:
        return self._execution().slurm_grant(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
        )

    def start_permit(
        self, assignment_id: str, incarnation: str, fence: str, *,
        request_id: str | None = None,
    ) -> bool:
        return self._execution().slurm_start_permit(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            fence=fence,
            request_id=request_id,
        )

    def started(
        self,
        assignment_id: str,
        incarnation: str,
        fence: str,
        process_execution_id: str,
    ) -> None:
        self._execution().slurm_started(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            fence=fence,
            process_execution_id=process_execution_id,
        )

    def declare_report(
        self,
        assignment_id: str,
        incarnation: str,
        fence: str,
        report: object,
    ) -> None:
        from ._remote_stage_execution import _RemoteExecutionReport

        parsed = (
            report
            if isinstance(report, _RemoteExecutionReport)
            else _RemoteExecutionReport.from_dict(report)
        )
        self._execution().slurm_declare_report(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            fence=fence,
            report=parsed,
        )

    def output_chunk(
        self,
        assignment_id: str,
        incarnation: str,
        transfer_id: str,
        *,
        offset: int,
        data: bytes,
        final: bool,
    ) -> int:
        return self._execution().slurm_output_chunk(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            transfer_id=transfer_id,
            offset=offset,
            data=data,
            final=final,
        )

    def commit_result(self, assignment_id: str, incarnation: str, fence: str) -> None:
        self._execution().slurm_commit_result(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
            fence=fence,
        )

    def release(self, assignment_id: str, incarnation: str) -> None:
        self._execution().slurm_release(
            principal_id=self._principal.subject,
            credential_id=self._principal.credential_id,
            assignment_id=assignment_id,
            incarnation=incarnation,
        )


def _require_role(principal: LocalDaemonPrincipal, role: LocalDaemonRole) -> None:
    if principal.role is not role:
        raise QueueServiceError("daemon principal is not authorized for this operation")


def _initialize_root(path: Path, *, role: str, sqlite_policy: SQLitePolicy | None = None) -> None:
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    database = path / "control.sqlite"
    with (sqlite3.connect(database) if sqlite_policy is None else initialize_database(database, policy=sqlite_policy, isolation_level="")) as conn:
        conn.execute(
            "CREATE TABLE root_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO root_metadata (key, value) VALUES ('role', ?)", (role,)
        )
        conn.execute(
            "INSERT INTO root_metadata (key, value) VALUES ('stable_id', ?)",
            (f"{role}-{uuid4()}",),
        )
        conn.execute(
            f"PRAGMA user_version = {_COORDINATOR_SCHEMA_VERSION if role == 'coordinator' else _AGENT_SCHEMA_VERSION}"
        )
        if role == "coordinator":
            _initialize_coordinator_schema(conn)
        initialize_agent_session_schema(conn, coordinator=role == "coordinator")
        conn.commit()
    database.chmod(0o600)


def _ensure_recovery_assignment_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS recovery_by_assignment "
        "ON recovery_operations(json_extract(request_json, '$.assignment_id'))"
    )


def _initialize_coordinator_schema(
    conn: sqlite3.Connection, *, version: int = _COORDINATOR_SCHEMA_VERSION,
) -> None:
    conn.execute(
        "CREATE TABLE daemon_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO daemon_metadata(key, value) VALUES (?, ?)",
        (
            ("accepted_time_health", "healthy"),
            ("accepted_time_revision", "0"),
        ),
    )
    conn.execute(
        "CREATE TABLE coordinator_epochs "
        "(epoch TEXT PRIMARY KEY, started_at TEXT NOT NULL)"
    )
    creator_column = "admitted_by TEXT," if version >= 20 else ""
    conn.execute(
        f"""
        CREATE TABLE managed_admissions (
            admission_id TEXT PRIMARY KEY,
            queue_item_id TEXT NOT NULL UNIQUE,
            coordinator_id TEXT NOT NULL,
            run_uri TEXT NOT NULL,
            intent_digest TEXT NOT NULL,
            execution_owner TEXT NOT NULL,
            state TEXT NOT NULL,
            accepted_at TEXT NOT NULL,
            authority_operation_id TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
            run_priority INTEGER NOT NULL,
            enqueue_sequence INTEGER NOT NULL UNIQUE,
            cancellation_operation_id TEXT,
            cancellation_principal_id TEXT,
            blocked_reason TEXT,
            {creator_column}
            UNIQUE(coordinator_id, run_uri)
        )
        """
    )
    conn.execute(
        "INSERT INTO daemon_metadata(key, value) VALUES "
        "('admission_enqueue_sequence', '0')"
    )
    conn.execute(
        "CREATE TABLE admission_reconciliation_health ("
        "admission_id TEXT PRIMARY KEY REFERENCES managed_admissions(admission_id), "
        "health TEXT NOT NULL, observed_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE scheduling_reloads ("
        "operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
        "request_json TEXT NOT NULL, state TEXT NOT NULL, "
        "result_code TEXT, scheduling_epoch TEXT, "
        "configuration_revision INTEGER, replacement_fingerprint TEXT)"
    )
    conn.execute(
        "CREATE TABLE recovery_operations ("
        "recovery_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
        "request_json TEXT NOT NULL, request_digest TEXT NOT NULL, "
        "recorded_at TEXT NOT NULL, state TEXT NOT NULL, "
        "evidence_json TEXT, result_json TEXT NOT NULL)"
    )
    ensure_scan_index(conn)
    ensure_retry_index(conn)
    _ensure_recovery_assignment_index(conn)
    conn.execute(
        "CREATE TABLE time_recoveries ("
        "operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
        "request_json TEXT NOT NULL, request_digest TEXT NOT NULL, "
        "result_json TEXT NOT NULL)"
    )
    from ._maintenance import initialize as initialize_maintenance
    initialize_maintenance(conn)
    _initialize_preparation_schema(conn)
    from ._action_results import initialize_action_results

    initialize_action_results(conn)


def _ensure_preparation_child_index(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS preparation_target_children "
                 "ON preparation_operations(target_name, principal_id, child_admission_id)")


def _initialize_preparation_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE preparation_operations ("
        "operation_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, "
        "kind TEXT NOT NULL, queue_item_id TEXT, "
        "intent_digest TEXT NOT NULL, request_json TEXT NOT NULL, "
        "selected_json TEXT NOT NULL, target_name TEXT, "
        "child_name TEXT NOT NULL UNIQUE, child_admission_id TEXT, "
        "dispatch_claimed INTEGER NOT NULL DEFAULT 0 CHECK(dispatch_claimed IN (0, 1)), "
        "state TEXT NOT NULL, result_code TEXT, result_json TEXT NOT NULL, "
        "cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancellation_requested IN (0, 1)), "
        "accepted_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE preparation_cancellations ("
        "operation_id TEXT PRIMARY KEY, target_operation_id TEXT NOT NULL UNIQUE "
        "REFERENCES preparation_operations(operation_id), state TEXT NOT NULL, "
        "result_code TEXT, result_json TEXT NOT NULL)"
    )
    _ensure_preparation_child_index(conn)


def _validate_coordinator_schema(
    conn: sqlite3.Connection, *, version: int = _COORDINATOR_SCHEMA_VERSION,
) -> None:
    """Validate durable table/identity constraints against the initialization owner."""

    def shape(database: sqlite3.Connection, table: str) -> tuple[object, ...]:
        columns = tuple(
            tuple(row) for row in database.execute(f'PRAGMA table_info("{table}")')
        )
        indexes = []
        for index in database.execute(f'PRAGMA index_list("{table}")'):
            if index[2]:
                name = str(index[1]).replace('"', '""')
                indexes.append(
                    tuple(
                        row[2]
                        for row in database.execute(f'PRAGMA index_info("{name}")')
                    )
                )
        foreign_keys = tuple(
            tuple(row)
            for row in database.execute(f'PRAGMA foreign_key_list("{table}")')
        )
        return columns, tuple(sorted(indexes)), foreign_keys

    try:
        with sqlite3.connect(":memory:") as expected:
            _initialize_coordinator_schema(expected, version=version)
            tables = tuple(
                row[0]
                for row in expected.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            )
            if any(shape(conn, table) != shape(expected, table) for table in tables):
                raise QueueStorageError(
                    "coordinator control schema is incomplete or incompatible"
                )
    except sqlite3.Error as exc:
        raise QueueStorageError("coordinator control schema is invalid") from exc


def _open_root(path: Path, *, role: str, for_storage_upgrade: bool = False) -> str:
    _validate_private_directory(path)
    database = path / "control.sqlite"
    if not database.is_file():
        raise QueueServiceError(f"{role} root is missing control state")
    mode = stat.S_IMODE(database.stat().st_mode)
    if mode & 0o077:
        raise QueueStorageError(f"{role} root must be owner-permissioned")
    with inspect_sqlite_database(database) as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        expected_version = (
            _COORDINATOR_SCHEMA_VERSION if role == "coordinator" else _AGENT_SCHEMA_VERSION
        )
        if role == "coordinator" and version == 19 and not for_storage_upgrade:
            raise QueueStorageError(
                "coordinator control schema 19 requires a stopped upgrade; "
                "use loom queue storage-upgrade admissions --help"
            )
        if version != expected_version and not (for_storage_upgrade and role == "coordinator" and version == 19):
            raise QueueStorageError(
                f"{role} daemon schema is unsupported; fresh roots are required"
            )
        validate_agent_session_schema(conn, coordinator=role == "coordinator")
        if role == "coordinator":
            _validate_coordinator_schema(conn, version=version)
        values = {
            str(row[0]): str(row[1])
            for row in conn.execute("SELECT key, value FROM root_metadata")
        }
    if values.get("role") != role or not values.get("stable_id"):
        raise QueueStorageError(f"{role} root identity is invalid")
    return values["stable_id"]


def _validate_deployment_binding(
    config: LocalDaemonConfig, *, coordinator_id: str | None = None
) -> None:
    target = config.deployment_root
    if target is None:
        raise QueueServiceError("coordinator deployment root is required")
    _validate_private_directory(target)
    binding_path = target / _DEPLOYMENT_BINDING_FILE
    if (
        not binding_path.is_file()
        or binding_path.stat().st_uid != os.getuid()
        or stat.S_IMODE(binding_path.stat().st_mode) & 0o077
    ):
        raise QueueServiceError("coordinator deployment binding is unavailable")
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueServiceError("coordinator deployment binding is invalid") from exc
    expected: dict[str, object] = {
        "schema_version": 3,
        "role_kind": "coordinator"
        if config.agent_root is None
        else "coordinator-bundle",
        "coordinator_id": coordinator_id
        if coordinator_id is not None
        else _open_root(config.coordinator_root, role="coordinator"),
        "immutable_fingerprint": config.deployment_configuration_fingerprint,
    }
    if config.agent_root is not None:
        expected["agent_id"] = _open_root(config.agent_root, role="local-agent")
    if binding != expected:
        raise QueueServiceError("coordinator deployment binding is invalid")


def _validate_private_directory(path: Path) -> None:
    if not path.is_dir():
        raise QueueServiceError(f"local daemon root is missing: {path}")
    details = path.stat()
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
        raise QueueStorageError("local daemon root must be owner-permissioned")


def _validate_distinct_roots(config: LocalDaemonConfig) -> None:
    if not config.coordinator_root.exists():
        raise QueueServiceError("local daemon initialized roots are missing")
    if config.agent_root is None:
        return
    if not config.agent_root.exists():
        raise QueueServiceError("local daemon initialized roots are missing")
    if (
        config.coordinator_root.resolve() == config.agent_root.resolve()
        or config.coordinator_root.stat().st_ino == config.agent_root.stat().st_ino
    ):
        raise QueueServiceError("coordinator and local-agent roots must not alias")


def _acquire_lock(root: Path):  # type: ignore[no-untyped-def]
    lock_path = root / "owner.lock"
    lock = lock_path.open("a+", encoding="utf-8")
    lock_path.chmod(0o600)
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock.close()
        raise QueueServiceError(f"local daemon role is already locked: {root}") from exc
    return lock


def _request_admission_cancellation(
    conn: sqlite3.Connection, queue_item_id: str, *, principal_id: str,
    repair_revision: int | None = None, request_operation_id: str | None = None,
) -> LocalDaemonAdmission:
    """One transaction owner for cancellation intent and shared-action demands."""
    from ._action_results import detach_action_graph

    row = conn.execute(
        "SELECT * FROM managed_admissions WHERE queue_item_id = ?",
        (queue_item_id,),
    ).fetchone()
    if row is None:
        raise AdmissionNotFoundError("managed admission was not found")
    admission = _admission_from_row(row)
    repairing_cancelled = (
        admission.state is LocalDaemonAdmissionState.CANCELLED
        and repair_revision == admission.revision
        and admission.cancellation_operation_id is None
    )
    if repair_revision is not None and not repairing_cancelled:
        return admission
    if not repairing_cancelled and admission.state in {
        LocalDaemonAdmissionState.SUCCEEDED,
        LocalDaemonAdmissionState.FAILED,
        LocalDaemonAdmissionState.CANCELLED,
    }:
        return admission
    if (
        admission.cancellation_operation_id and admission.cancellation_principal_id
        and admission.state in {LocalDaemonAdmissionState.CANCELLATION_REQUESTED, LocalDaemonAdmissionState.CANCELLING}
    ):
        # The intent and graph detachment committed together. Re-observing
        # that intent preserves progress and its original principal/revision.
        return admission
    operation_id = admission.cancellation_operation_id or (
        request_operation_id or f"authority-cancel-{uuid4()}"
    )
    write_status(
        conn, "admission",
        "UPDATE managed_admissions SET state = ?, "
        "cancellation_operation_id = ?, "
        "cancellation_principal_id = COALESCE("
        "cancellation_principal_id, ?), blocked_reason = NULL, "
        "revision = revision + 1 WHERE admission_id = ? AND "
        "(state != ? OR cancellation_operation_id IS NULL OR "
        "cancellation_principal_id IS NULL OR blocked_reason IS NOT NULL)",
        (
            LocalDaemonAdmissionState.CANCELLATION_REQUESTED.value,
            operation_id,
            principal_id,
            admission.admission_id,
            LocalDaemonAdmissionState.CANCELLATION_REQUESTED.value,
        ),
    )
    detach_action_graph(conn, admission.run_uri, operation_id)
    return _admission_from_row(conn.execute("SELECT * FROM managed_admissions WHERE admission_id = ?", (admission.admission_id,)).fetchone())


def _admission_from_row(row: sqlite3.Row | Mapping[str, Any]) -> LocalDaemonAdmission:
    return LocalDaemonAdmission(
        admission_id=str(row["admission_id"]),
        queue_item_id=str(row["queue_item_id"]),
        coordinator_id=str(row["coordinator_id"]),
        run_uri=str(row["run_uri"]),
        intent_digest=str(row["intent_digest"]),
        execution_owner=str(row["execution_owner"]),
        state=LocalDaemonAdmissionState(str(row["state"])),
        accepted_at=str(row["accepted_at"]),
        authority_operation_id=str(row["authority_operation_id"]),
        revision=_positive_revision(int(row["revision"])),
        run_priority=_run_priority(int(row["run_priority"])),
        enqueue_sequence=_non_negative_int(
            int(row["enqueue_sequence"]), "enqueue_sequence"
        ),
        cancellation_operation_id=(
            None
            if row["cancellation_operation_id"] is None
            else str(row["cancellation_operation_id"])
        ),
        cancellation_principal_id=(
            None
            if row["cancellation_principal_id"] is None
            else str(row["cancellation_principal_id"])
        ),
        blocked_reason=(
            None if row["blocked_reason"] is None else str(row["blocked_reason"])
        ),
    )


def _required_string(data: Mapping[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise QueueServiceError(f"{field} must be a non-empty string")
    return value


def _positive_revision(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise QueueStorageError("admission revision is invalid")
    return value


def _encode_admission_cursor(sequence: int, admission_id: str) -> str:
    """Opaque durable keyset cursor for the admission ordering contract."""
    value = json.dumps(
        [sequence, admission_id], separators=(",", ":"), ensure_ascii=True
    )
    return (
        hashlib.sha256(value.encode("ascii")).hexdigest()[:16]
        + "."
        + value.encode("ascii").hex()
    )


def _encode_agent_cursor(agent_id: str) -> str:
    value = json.dumps(agent_id, separators=(",", ":"), ensure_ascii=True)
    return (
        hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        + "."
        + value.encode("utf-8").hex()
    )


def _decode_agent_cursor(cursor: str) -> str:
    if not isinstance(cursor, str) or len(cursor) > 512 or "." not in cursor:
        raise QueueServiceError("agent cursor is invalid")
    digest, encoded = cursor.split(".", 1)
    try:
        raw = bytes.fromhex(encoded).decode("utf-8")
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QueueServiceError("agent cursor is invalid") from exc
    if hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] != digest or (
        not isinstance(value, str) or not value
    ):
        raise QueueServiceError("agent cursor is invalid")
    return value


def _resource_status_from_value(
    value: object,
) -> tuple[ResourceAvailabilityStatus, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise QueueServiceError("resource status projection is invalid")
    return tuple(ResourceAvailabilityStatus.from_dict(item) for item in value)


def _agent_projection(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    coordinator_epoch: str | None,
    as_of: str,
    include_capacity: bool,
) -> AgentProjection:
    pools = json.loads(str(row["pools_json"]))
    capabilities = json.loads(str(row["capabilities_json"]))
    if not isinstance(pools, list) or not isinstance(capabilities, list):
        raise QueueStorageError("agent session projection is invalid")
    accepted = conn.execute(
        "SELECT value FROM daemon_metadata WHERE key = 'accepted_time_high_water'"
    ).fetchone()
    accepted_at = parse_timestamp(as_of)
    if accepted is not None:
        accepted_at = max(accepted_at, parse_timestamp(accepted["value"]))
    if not all(isinstance(item, str) and item for item in pools) or not all(
        isinstance(item, str) and item for item in capabilities
    ):
        raise QueueStorageError("agent session projection is invalid")
    latest = conn.execute(
        "SELECT offer_id, offer_json, accepted_at, expires_at, current FROM agent_offers "
        "WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
        (str(row["session_id"]),),
    ).fetchone()
    statuses: tuple[ResourceAvailabilityStatus, ...] = ()
    current = False
    capacity = None
    if latest is not None:
        offer = AgentOffer.from_value(json.loads(latest["offer_json"]))
        current = (
            bool(latest["current"])
            and row["state"] == "ACTIVE"
            and offer.coordinator_epoch == row["coordinator_epoch"] == coordinator_epoch
            and offer.availability_revision == row["availability_revision"]
            and parse_timestamp(latest["expires_at"]) >= accepted_at
        )
        if current and include_capacity:
            has_cpu = any(provider.descriptor.kind == "cpu" for provider in offer.provider_composition)
            capacity = AgentOfferCapacity(
                offer.cpu if has_cpu else None,
                len(offer.gpu_atoms) if offer.gpu_devices else None,
                latest["accepted_at"],
            )
        statuses = offer.resource_status
        renewal = conn.execute(
            "SELECT result_json FROM agent_offer_renewals WHERE session_id = ?",
            (str(row["session_id"]),),
        ).fetchone()
        if renewal is not None:
            receipt = json.loads(str(renewal["result_json"]))
            if (
                receipt.get("offer_id") == str(latest["offer_id"])
                and "resource_status" in receipt
            ):
                statuses = _resource_status_from_value(receipt["resource_status"])
        if not current:
            statuses = tuple(
                replace(item, available=False, reason_code="observation_stale")
                for item in statuses
            )
    return AgentProjection(
        offered_capacity=capacity,
        resource_status=statuses,
        agent_id=str(row["agent_id"]),
        session_id=str(row["session_id"]),
        state=str(row["state"]),
        config_revision=str(row["config_revision"]),
        inventory_revision=str(row["inventory_revision"]),
        availability_revision=str(row["availability_revision"]),
        coordinator_epoch=str(row["coordinator_epoch"]),
        pools=tuple(pools),
        capabilities=tuple(capabilities),
        available=current,
    )


def _operation_projection(
    conn: sqlite3.Connection, operation_id: str
) -> LocalDaemonOperation | None:
    queries = (
        (
            "agent_control",
            "SELECT state, result_code, effect_json FROM agent_controls WHERE operation_id = ?",
        ),
        (
            "scheduling_reload",
            "SELECT state, result_code, json_object('scheduling_epoch', scheduling_epoch, "
            "'configuration_revision', configuration_revision, 'replacement_fingerprint', replacement_fingerprint) "
            "AS effect_json FROM scheduling_reloads WHERE operation_id = ?",
        ),
        (
            "time_recovery",
            "SELECT 'applied' AS state, NULL AS result_code, result_json AS effect_json FROM time_recoveries WHERE operation_id = ?",
        ),
        (
            "session_replacement",
            "SELECT state, NULL AS result_code, result_json AS effect_json FROM session_replacements WHERE operation_id = ?",
        ),
        (
            "recovery",
            "SELECT state, NULL AS result_code, result_json AS effect_json FROM recovery_operations WHERE recovery_id = ?",
        ),
        (
            "prepare_run",
            "SELECT kind, state, result_code, result_json AS effect_json FROM preparation_operations WHERE operation_id = ?",
        ),
        (
            "cancel_run",
            "SELECT state, result_code, result_json AS effect_json FROM preparation_cancellations WHERE operation_id = ?",
        ),
    )
    matches: list[LocalDaemonOperation] = []
    for kind, query in queries:
        row = conn.execute(query, (operation_id,)).fetchone()
        if row is None:
            continue
        result: PlainData | None = None
        encoded = row["effect_json"]
        if encoded is not None:
            try:
                decoded = json.loads(str(encoded))
                result = freeze_plain_data(decoded, path="operation result")
            except (json.JSONDecodeError, QueueServiceError) as exc:
                raise QueueStorageError("operation result is invalid") from exc
        matches.append(
            LocalDaemonOperation(
                operation_id=operation_id,
                kind=str(row["kind"]) if "kind" in row.keys() else kind,
                state=str(row["state"]),
                code=(None if row["result_code"] is None else str(row["result_code"])),
                result=result,
            )
        )
    if len(matches) > 1:
        raise QueueConflictError("managed operation identity is ambiguous")
    return matches[0] if matches else None


def _decode_admission_cursor(cursor: str) -> tuple[int, str]:
    if not isinstance(cursor, str) or len(cursor) > 512 or "." not in cursor:
        raise QueueServiceError("admission cursor is invalid")
    prefix, encoded = cursor.split(".", 1)
    try:
        value = bytes.fromhex(encoded).decode("ascii")
        if hashlib.sha256(value.encode("ascii")).hexdigest()[:16] != prefix:
            raise ValueError
        sequence, admission_id = json.loads(value)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise QueueServiceError("admission cursor is invalid") from None
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 0
        or not isinstance(admission_id, str)
        or not admission_id
    ):
        raise QueueServiceError("admission cursor is invalid")
    return sequence, admission_id


def _required_int(data: Mapping[str, object], field: str) -> int:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueueServiceError(f"{field} must be an integer")
    return value


def _non_negative_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QueueServiceError(f"{field} must be a non-negative integer")
    return value


def _run_priority(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not _MIN_RUN_PRIORITY <= value <= _MAX_RUN_PRIORITY
    ):
        raise QueueServiceError("run_priority is outside the protected range")
    return value


def _required_bool(data: Mapping[str, object], field: str) -> bool:
    value = data.get(field)
    if not isinstance(value, bool):
        raise QueueServiceError(f"{field} must be a boolean")
    return value


def _optional_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is not None and (not isinstance(value, str) or not value):
        raise QueueServiceError(f"{field} must be null or a non-empty string")
    return value


def _exact_fields(data: Mapping[str, object], fields: set[str], label: str) -> None:
    if set(data) != fields:
        raise QueueServiceError(
            f"{label} must contain exactly: {', '.join(sorted(fields))}"
        )


def _scheduling_fingerprint(config: LocalDaemonConfig) -> str:
    if config.active_configuration_fingerprint is not None:
        return config.active_configuration_fingerprint
    payload = {
        **({"slurm_admission": config.slurm_admission.to_dict()} if config.slurm_admission is not None else {}),
        **({"slurm_terminal_recovery": config.slurm_terminal_recovery.to_dict()} if config.slurm_terminal_recovery is not None else {}),
        **({"shared_roots": thaw_plain_data(config.shared_roots)} if config.shared_roots else {}),
        **({"assignment_payload_root_id": config.assignment_payload_root_id} if config.assignment_payload_root_id is not None else {}),
        **(
            {"resident_preparation_staged_ready": True}
            if config.resident_preparation_staged_ready
            else {}
        ),
        **(
            {"resident_preparation_ready": True}
            if config.resident_preparation_ready
            else {}
        ),
        "machine_id": config.machine_id,
        "cpu_capacity": config.cpu_capacity,
        "memory_capacity_bytes": config.memory_capacity_bytes,
        "gpu_devices": [
            {
                "descriptor": item.descriptor.to_dict(),
                "binding_digest": hashlib.sha256(
                    item.binding_value.encode()
                ).hexdigest(),
            }
            for item in config.gpu_devices
        ],
        "agent_policy": repr(config.agent_policy),
        "resident_worker_launch_profile": (
            None
            if config.resident_worker_launch_profile is None
            else {
                "project_root": str(config.resident_worker_launch_profile.project_root),
                "python_executable": str(
                    config.resident_worker_launch_profile.python_executable
                ),
                "descriptor": config.resident_worker_launch_profile.descriptor,
            }
        ),
        "remote_profiles": [item.to_dict() for item in config.remote_profiles],
        **({"container_capabilities": [item.to_dict() for item in config.container_capabilities]}
           if config.container_capabilities else {}),
        "slurm_profiles": [
            {
                "profile_id": item.profile_id,
                "configuration_fingerprint": item.configuration_fingerprint,
                "available": item.available,
            }
            for item in config.slurm_profiles
        ],
        "scheduling_components": [
            item.to_dict() for item in config.scheduling_components.descriptors
        ],
    }
    if (
        config.gpu_occupancy_policy is not None
        and config.gpu_occupancy_policy != GpuOccupancyPolicy()
    ):
        payload["gpu_occupancy"] = config.gpu_occupancy_policy.to_dict()
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return "scheduling-" + hashlib.sha256(encoded).hexdigest()


def _scheduling_reload_epoch(operation_id: str, fingerprint: str) -> str:
    return (
        "scheduling-epoch-"
        + hashlib.sha256((operation_id + "\0" + fingerprint).encode()).hexdigest()
    )


def _scheduling_reload_receipt(
    operation_id: str, row: sqlite3.Row
) -> Mapping[str, PlainData]:
    receipt: dict[str, PlainData] = {
        "operation_id": operation_id,
        "state": str(row["state"]),
        "code": row["result_code"],
        "scheduling_epoch": row["scheduling_epoch"],
    }
    if row["configuration_revision"] is not None:
        receipt["configuration_revision"] = int(row["configuration_revision"])
    return freeze_plain_data(receipt, path="scheduling reload receipt")


__all__ = [
    "CoordinatorSchedulingReload",
    "LocalDaemon",
    "LocalDaemonAdmission",
    "LocalDaemonAdmissionDetail",
    "LocalDaemonAdmissionRequest",
    "LocalDaemonAdmissionState",
    "AgentSessionView",
    "LocalDaemonClientView",
    "LocalDaemonConfig",
    "LocalDaemonSchedulingComponents",
    "LocalDaemonOperatorView",
    "LocalDaemonPrincipal",
    "LocalDaemonRole",
    "DaemonStatus",
    "AdmissionPage",
    "AdmissionNotFoundError",
    "AdmissionWaitKind",
    "AdmissionWaitResult",
    "ManagedRecoveryTarget",
    "RecoverUnknownAssignment",
    "SlurmRecoveryTarget",
    "TimeRecoveryReceipt",
    "TimeRecoveryRequest",
]


def _validate_retired_coordinator_execution(previous, replacement):
    """Share retirement execution constraints across live and stopped owners."""
    if not set(replacement.coordinator_shared_roots) <= set(previous.coordinator_shared_roots):
        raise QueueConflictError("coordinator retirement cannot add shared roots")
    for name in ("remote_profiles",):
        if any(value not in getattr(previous, name) for value in getattr(replacement, name)):
            raise QueueConflictError("coordinator retirement cannot add or change execution identities")
    from .submitted_execution import _validate_retired_capabilities
    _validate_retired_capabilities(previous.container_capabilities, replacement.container_capabilities)
    from .shared_execution import _readonly_root_relocations

    _readonly_root_relocations(
        {key: previous.coordinator_shared_roots[key] for key in replacement.coordinator_shared_roots},
        replacement.coordinator_shared_roots,
    )
    old, new = previous.preparation_policy, replacement.preparation_policy
    if new is None:
        return
    if old is None or any(old.source_roots.get(key) != value for key, value in new.source_roots.items()):
        raise QueueConflictError("coordinator retirement cannot add or rebind preparation roots")
    for key, profile in new.profiles.items():
        previous = old.profiles.get(key)
        comparable = profile
        from ._preparation_policy import SubmittedPreparationProfile
        if isinstance(profile, SubmittedPreparationProfile) and isinstance(previous, SubmittedPreparationProfile):
            if profile.capability.policy_id != previous.capability.policy_id:
                raise QueueConflictError("coordinator retirement cannot rebind preparation policy")
            _validate_retired_capabilities((previous.capability,), (profile.capability,))
            old_scope, new_scope = previous.shared_scope, profile.shared_scope
            old_roots = cast(Mapping[str, PlainData], old_scope["roots"])
            new_roots = cast(Mapping[str, PlainData], new_scope["roots"])
            if (any(old_roots.get(alias) != value for alias, value in new_roots.items())
                or {**new_scope, "roots": old_scope["roots"]} != old_scope):
                raise QueueConflictError("coordinator retirement cannot expand preparation shared scope")
            if not set(profile.image_roots) <= set(previous.image_roots):
                raise QueueConflictError("coordinator retirement cannot add preparation image roots")
            _readonly_root_relocations(
                {alias: previous.image_roots[alias] for alias in profile.image_roots}, profile.image_roots)
            comparable = replace(profile, capability=previous.capability,
                                 shared_scope=previous.shared_scope, image_roots=previous.image_roots)
        if (previous is None or not set(profile.allowed_source_roots) <= set(previous.allowed_source_roots)
            or replace(comparable, allowed_source_roots=previous.allowed_source_roots) != previous):
            raise QueueConflictError("coordinator retirement cannot add or change preparation execution")
