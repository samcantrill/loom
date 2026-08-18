"""In-process queue service boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import utc_timestamp

from .config import QueueServiceSpec
from .errors import QueueConfigError, QueueServiceError, QueueServiceStateError
from .models import (
    CancellationRecord,
    DispatchHandle,
    LaunchContract,
    QueueAuditEvent,
    QueueDefinition,
    QueueItem,
    QueueItemStatus,
    QueueRecoveryRecord,
    RunIntent,
    validate_queue_id,
)
from .repository import QueuePoolSnapshot, QueueRepository
from ._sqlite import SQLiteQueueRepository


class QueueServiceState(StrEnum):
    """Lifecycle state for an in-process queue service."""

    STOPPED = "stopped"
    RUNNING = "running"


@dataclass(frozen=True, slots=True)
class QueueEnqueueRequest:
    """Python request shape for enqueueing one whole-run queue item."""

    queue_item_id: str
    queue_name: str
    run_uri: str
    request: Mapping[str, PlainData] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    run_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    launch_contract: LaunchContract | None = None
    adapter: str = "fake"
    entrypoint: str = "fake"
    resources: Mapping[str, int] = field(default_factory=dict)
    snapshot: Mapping[str, PlainData] = field(default_factory=dict)
    drift_inputs: Mapping[str, PlainData] = field(default_factory=dict)
    delegated_verification: Mapping[str, PlainData] = field(default_factory=dict)
    launch_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "queue_item_id",
            validate_queue_id(self.queue_item_id, "queue_item_id"),
        )
        object.__setattr__(
            self, "queue_name", validate_queue_id(self.queue_name, "queue_name")
        )
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise QueueServiceError("run_uri must be a non-empty string")
        object.__setattr__(self, "request", _plain_mapping(self.request, "request"))
        object.__setattr__(self, "tags", _string_mapping(self.tags, "tags"))
        object.__setattr__(
            self,
            "run_metadata",
            _plain_mapping(self.run_metadata, "run_metadata"),
        )
        if self.launch_contract is not None and not isinstance(
            self.launch_contract, LaunchContract
        ):
            raise QueueServiceError("launch_contract must be a LaunchContract or None")
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "queue_item_id": self.queue_item_id,
            "queue_name": self.queue_name,
            "run_uri": self.run_uri,
            "request": thaw_plain_data(self.request, path="request"),
            "tags": dict(self.tags),
            "run_metadata": thaw_plain_data(self.run_metadata, path="run_metadata"),
            "launch_contract": None
            if self.launch_contract is None
            else self.launch_contract.to_dict(),
            "adapter": self.adapter,
            "entrypoint": self.entrypoint,
            "resources": dict(self.resources),
            "snapshot": thaw_plain_data(self.snapshot, path="snapshot"),
            "drift_inputs": thaw_plain_data(self.drift_inputs, path="drift_inputs"),
            "delegated_verification": thaw_plain_data(
                self.delegated_verification,
                path="delegated_verification",
            ),
            "launch_metadata": thaw_plain_data(
                self.launch_metadata, path="launch_metadata"
            ),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }


@dataclass(frozen=True, slots=True)
class QueueServiceStatus:
    """Current queue service lifecycle and recovery summary."""

    state: QueueServiceState
    pool_names: tuple[str, ...]
    queue_names: tuple[str, ...]
    recovery_records: tuple[QueueRecoveryRecord, ...]

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "state": self.state.value,
            "pool_names": list(self.pool_names),
            "queue_names": list(self.queue_names),
            "recovery_records": [record.to_dict() for record in self.recovery_records],
        }


@dataclass(frozen=True, slots=True)
class QueueItemInspection:
    """Read model returned by queue inspect operations."""

    item: QueueItem | None
    audit_events: tuple[QueueAuditEvent, ...] = ()
    recovery_records: tuple[QueueRecoveryRecord, ...] = ()


class QueueService:
    """In-process queue service over a durable queue repository."""

    def __init__(
        self,
        spec: QueueServiceSpec,
        repository: QueueRepository,
        *,
        clock: Callable[[], str] = utc_timestamp,
    ) -> None:
        self.spec = spec
        self.repository = repository
        self._clock = clock
        self._state = QueueServiceState.STOPPED

    @classmethod
    def from_spec(
        cls,
        spec: QueueServiceSpec,
        repository: QueueRepository | None = None,
        *,
        clock: Callable[[], str] = utc_timestamp,
    ) -> "QueueService":
        if repository is None:
            if spec.db_path is None:
                raise QueueConfigError(
                    "queue service spec requires db_path when no repository is provided"
                )
            repository = SQLiteQueueRepository(spec.db_path, clock=clock)
        return cls(spec, repository, clock=clock)

    @property
    def state(self) -> QueueServiceState:
        return self._state

    def start(self) -> QueueServiceStatus:
        self._state = QueueServiceState.RUNNING
        return self.status()

    def stop(self) -> QueueServiceStatus:
        self._state = QueueServiceState.STOPPED
        return self.status()

    def status(self) -> QueueServiceStatus:
        recovery_records = (
            self.repository.scan_recovery()
            if self._state is QueueServiceState.RUNNING
            else ()
        )
        return QueueServiceStatus(
            state=self._state,
            pool_names=self.spec.pool_names,
            queue_names=self.spec.queue_names,
            recovery_records=recovery_records,
        )

    def enqueue(self, request: QueueEnqueueRequest) -> QueueItem:
        self._ensure_running()
        queue = self.spec.queue_for_name(request.queue_name)
        now = self._clock()
        launch_contract = request.launch_contract or LaunchContract(
            adapter=request.adapter,
            entrypoint=request.entrypoint,
            resources=request.resources,
            snapshot=_thawed_mapping(request.snapshot, "snapshot"),
            drift_inputs=_thawed_mapping(request.drift_inputs, "drift_inputs"),
            delegated_verification=_thawed_mapping(
                request.delegated_verification,
                "delegated_verification",
            ),
            metadata=_thawed_mapping(request.launch_metadata, "launch_metadata"),
        )
        item = QueueItem(
            queue_item_id=request.queue_item_id,
            queue_name=queue.queue_name,
            pool_name=queue.pool_name,
            run_uri=request.run_uri,
            run_intent=RunIntent(
                run_uri=request.run_uri,
                request=_thawed_mapping(request.request, "request"),
                tags=request.tags,
                metadata=_thawed_mapping(request.run_metadata, "run_metadata"),
            ),
            launch_contract=launch_contract,
            enqueued_at=now,
            updated_at=now,
            metadata=_thawed_mapping(request.metadata, "metadata"),
        )
        return self.repository.enqueue(item)

    def inspect_item(self, queue_item_id: str) -> QueueItemInspection:
        self._ensure_running()
        item = self.repository.read_item(queue_item_id)
        if item is None:
            return QueueItemInspection(item=None)
        recovery = tuple(
            record
            for record in self.repository.scan_recovery()
            if record.queue_item_id == item.queue_item_id
        )
        return QueueItemInspection(
            item=item,
            audit_events=self.repository.list_audit_events(queue_item_id),
            recovery_records=recovery,
        )

    def read_item(self, queue_item_id: str) -> QueueItem | None:
        self._ensure_running()
        return self.repository.read_item(queue_item_id)

    def read_pool_snapshot(self, pool_name: str) -> QueuePoolSnapshot:
        """Return one selected-pool repository snapshot for operator status."""

        self._ensure_running()
        self._require_pool(pool_name)
        return self.repository.read_pool_snapshot(pool_name)

    def recovery_items(self) -> tuple[QueueItem, ...]:
        self._ensure_running()
        items: list[QueueItem] = []
        for record in self.repository.scan_recovery():
            item = self.repository.read_item(record.queue_item_id)
            if item is not None:
                items.append(item)
        return tuple(items)

    def cancel_item(
        self,
        queue_item_id: str,
        *,
        requested_by: str,
        reason: str,
        evidence: Mapping[str, PlainData] | None = None,
        expected: QueueItem | None = None,
    ) -> QueueItem:
        self._ensure_running()
        cancellation = CancellationRecord(
            requested_at=self._clock(),
            requested_by=requested_by,
            reason=reason,
            evidence={} if evidence is None else evidence,
        )
        return self.repository.request_cancellation(
            queue_item_id, cancellation, expected=expected
        )

    def claim_next(
        self,
        pool_name: str,
        *,
        owner_id: str,
        claim_id: str,
    ):
        self._ensure_running()
        self._require_pool(pool_name)
        return self.repository.claim_next(
            pool_name,
            owner_id=owner_id,
            claim_id=claim_id,
        )

    def record_dispatch_handle(
        self,
        queue_item_id: str,
        handle: DispatchHandle,
        *,
        expected: QueueItem,
    ) -> QueueItem:
        self._ensure_running()
        return self.repository.record_dispatch_handle(
            queue_item_id, handle, expected=expected
        )

    def complete_item(
        self,
        queue_item_id: str,
        *,
        status: QueueItemStatus,
        reason: str,
        expected: QueueItem,
    ) -> QueueItem:
        self._ensure_running()
        return self.repository.complete_item(
            queue_item_id, status=status, reason=reason, expected=expected
        )

    def defer_item(
        self,
        queue_item_id: str,
        *,
        reason_code: str,
        expected: QueueItem,
    ) -> QueueItem:
        self._ensure_running()
        return self.repository.defer_item(
            queue_item_id, reason_code=reason_code, expected=expected
        )

    def scan_recovery(self) -> tuple[QueueRecoveryRecord, ...]:
        self._ensure_running()
        return self.repository.scan_recovery()

    def list_audit_events(self, queue_item_id: str) -> tuple[QueueAuditEvent, ...]:
        self._ensure_running()
        return self.repository.list_audit_events(queue_item_id)

    def queue_for_name(self, queue_name: str) -> QueueDefinition:
        return self.spec.queue_for_name(queue_name)

    def _ensure_running(self) -> None:
        if self._state is not QueueServiceState.RUNNING:
            raise QueueServiceStateError("queue service is not running")

    def _require_pool(self, pool_name: str) -> None:
        pool_name = validate_queue_id(pool_name, "pool_name")
        if not self.spec.has_pool(pool_name):
            raise QueueServiceError(f"unknown pool: {pool_name}")


def _plain_mapping(
    value: Mapping[str, PlainData], path: str
) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=path)
    except PlainDataError as exc:
        raise QueueServiceError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise QueueServiceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


def _thawed_mapping(
    value: Mapping[str, PlainData], path: str
) -> Mapping[str, PlainData]:
    thawed = thaw_plain_data(value, path=path)
    if not isinstance(thawed, Mapping):
        raise QueueServiceError(f"{path} must be a mapping")
    return cast(Mapping[str, PlainData], thawed)


def _string_mapping(value: Mapping[str, str], path: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise QueueServiceError(f"{path} must be a mapping")
    output: dict[str, str] = {}
    for key, item in value.items():
        validate_queue_id(key, f"{path} key")
        if not isinstance(item, str) or not item:
            raise QueueServiceError(f"{path}.{key} must be a non-empty string")
        output[key] = item
    return output


__all__ = [
    "QueueEnqueueRequest",
    "QueueItemInspection",
    "QueueService",
    "QueueServiceState",
    "QueueServiceStatus",
]
