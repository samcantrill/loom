"""Versioned queue records for whole-run queueing."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from loom._validation import require_schema_version
from loom.fingerprints import hash_mapping, validate_digest
from loom.serialization import (
    PlainData,
    SchemaVersionError,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp

from .errors import QueueValidationError

QUEUE_RECORD_SCHEMA_VERSION = 2

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_TERMINAL_ITEM_STATUSES = frozenset(
    {
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "UNKNOWN",
    }
)


class QueuePoolMode(StrEnum):
    """Capacity ownership mode for one queue pool."""

    MANAGED = "managed"
    DELEGATED = "delegated"


class QueueItemStatus(StrEnum):
    """Queue-local lifecycle state for one whole-run item."""

    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    DISPATCHED = "DISPATCHED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class QueueEnqueueDisposition(StrEnum):
    """Durable classification of one enqueue request."""

    ENQUEUED = "enqueued"
    SUBMISSION_REPLAY = "submission_replay"
    SCIENTIFIC_DUPLICATE = "scientific_duplicate"


@dataclass(frozen=True, slots=True)
class QueuePool:
    """Versioned definition for one capacity pool."""

    pool_name: str
    mode: QueuePoolMode | str
    resources: Mapping[str, int] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pool_name", validate_queue_id(self.pool_name, "pool_name")
        )
        object.__setattr__(self, "mode", QueuePoolMode(self.mode))
        object.__setattr__(
            self,
            "resources",
            _validate_non_negative_int_mapping(self.resources, "resources"),
        )
        object.__setattr__(
            self,
            "metadata",
            _freeze_mapping(self.metadata, "metadata"),
        )
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "pool_name": self.pool_name,
            "mode": QueuePoolMode(self.mode).value,
            "resources": dict(self.resources),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "QueuePool":
        payload = _load_record(
            data,
            "QueuePool",
            required={"pool_name", "mode", "resources", "metadata"},
        )
        return cls(
            pool_name=cast(str, payload["pool_name"]),
            mode=cast(str, payload["mode"]),
            resources=cast(Mapping[str, int], payload["resources"]),
            metadata=cast(Mapping[str, PlainData], payload["metadata"]),
        )


@dataclass(frozen=True, slots=True)
class QueueDefinition:
    """Versioned definition for the FIFO queue assigned to a pool."""

    queue_name: str
    pool_name: str
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "queue_name", validate_queue_id(self.queue_name, "queue_name")
        )
        object.__setattr__(
            self, "pool_name", validate_queue_id(self.pool_name, "pool_name")
        )
        object.__setattr__(
            self,
            "metadata",
            _freeze_mapping(self.metadata, "metadata"),
        )
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "queue_name": self.queue_name,
            "pool_name": self.pool_name,
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "QueueDefinition":
        payload = _load_record(
            data,
            "QueueDefinition",
            required={"queue_name", "pool_name", "metadata"},
        )
        return cls(
            queue_name=cast(str, payload["queue_name"]),
            pool_name=cast(str, payload["pool_name"]),
            metadata=cast(Mapping[str, PlainData], payload["metadata"]),
        )


@dataclass(frozen=True, slots=True)
class RunIntent:
    """Queue-owned run identity and enqueue-time run request snapshot."""

    run_uri: str
    request: Mapping[str, PlainData] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        object.__setattr__(self, "request", _freeze_mapping(self.request, "request"))
        object.__setattr__(self, "tags", _validate_string_mapping(self.tags, "tags"))
        object.__setattr__(
            self,
            "metadata",
            _freeze_mapping(self.metadata, "metadata"),
        )
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "run_uri": self.run_uri,
            "request": thaw_plain_data(self.request, path="request"),
            "tags": dict(self.tags),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "RunIntent":
        payload = _load_record(
            data,
            "RunIntent",
            required={"run_uri", "request", "tags", "metadata"},
        )
        return cls(
            run_uri=cast(str, payload["run_uri"]),
            request=cast(Mapping[str, PlainData], payload["request"]),
            tags=cast(Mapping[str, str], payload["tags"]),
            metadata=cast(Mapping[str, PlainData], payload["metadata"]),
        )


@dataclass(frozen=True, slots=True)
class LaunchContract:
    """Normalized enqueue-time launch contract for later adapters."""

    adapter: str
    entrypoint: str
    resources: Mapping[str, int] = field(default_factory=dict)
    snapshot: Mapping[str, PlainData] = field(default_factory=dict)
    drift_inputs: Mapping[str, PlainData] = field(default_factory=dict)
    delegated_verification: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", validate_queue_id(self.adapter, "adapter"))
        object.__setattr__(
            self, "entrypoint", _non_empty_string(self.entrypoint, "entrypoint")
        )
        object.__setattr__(
            self,
            "resources",
            _validate_non_negative_int_mapping(self.resources, "resources"),
        )
        object.__setattr__(self, "snapshot", _freeze_mapping(self.snapshot, "snapshot"))
        object.__setattr__(
            self,
            "drift_inputs",
            _freeze_mapping(self.drift_inputs, "drift_inputs"),
        )
        object.__setattr__(
            self,
            "delegated_verification",
            _freeze_mapping(self.delegated_verification, "delegated_verification"),
        )
        object.__setattr__(
            self,
            "metadata",
            _freeze_mapping(self.metadata, "metadata"),
        )
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "adapter": self.adapter,
            "entrypoint": self.entrypoint,
            "resources": dict(self.resources),
            "snapshot": thaw_plain_data(self.snapshot, path="snapshot"),
            "drift_inputs": thaw_plain_data(self.drift_inputs, path="drift_inputs"),
            "delegated_verification": thaw_plain_data(
                self.delegated_verification,
                path="delegated_verification",
            ),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "LaunchContract":
        payload = _load_record(
            data,
            "LaunchContract",
            required={
                "adapter",
                "entrypoint",
                "resources",
                "snapshot",
                "drift_inputs",
                "delegated_verification",
                "metadata",
            },
        )
        return cls(
            adapter=cast(str, payload["adapter"]),
            entrypoint=cast(str, payload["entrypoint"]),
            resources=cast(Mapping[str, int], payload["resources"]),
            snapshot=cast(Mapping[str, PlainData], payload["snapshot"]),
            drift_inputs=cast(Mapping[str, PlainData], payload["drift_inputs"]),
            delegated_verification=cast(
                Mapping[str, PlainData],
                payload["delegated_verification"],
            ),
            metadata=cast(Mapping[str, PlainData], payload["metadata"]),
        )


@dataclass(frozen=True, slots=True)
class QueueClaim:
    """Queue-local claim for one dispatch attempt."""

    claim_id: str
    owner_id: str
    claimed_at: str
    dispatch_attempt: int
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "claim_id", validate_queue_id(self.claim_id, "claim_id")
        )
        object.__setattr__(
            self, "owner_id", validate_queue_id(self.owner_id, "owner_id")
        )
        object.__setattr__(
            self, "claimed_at", _timestamp(self.claimed_at, "claimed_at")
        )
        object.__setattr__(
            self,
            "dispatch_attempt",
            _positive_int(self.dispatch_attempt, "dispatch_attempt"),
        )
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "owner_id": self.owner_id,
            "claimed_at": self.claimed_at,
            "dispatch_attempt": self.dispatch_attempt,
        }

    @classmethod
    def from_dict(cls, data: object) -> "QueueClaim":
        payload = _load_record(
            data,
            "QueueClaim",
            required={"claim_id", "owner_id", "claimed_at", "dispatch_attempt"},
        )
        return cls(
            claim_id=cast(str, payload["claim_id"]),
            owner_id=cast(str, payload["owner_id"]),
            claimed_at=cast(str, payload["claimed_at"]),
            dispatch_attempt=cast(int, payload["dispatch_attempt"]),
        )


@dataclass(frozen=True, slots=True)
class DispatchHandle:
    """Adapter-visible dispatch handle persisted by the queue."""

    adapter: str
    handle_id: str
    dispatched_at: str
    dispatch_attempt: int
    evidence: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", validate_queue_id(self.adapter, "adapter"))
        object.__setattr__(
            self, "handle_id", _non_empty_string(self.handle_id, "handle_id")
        )
        object.__setattr__(
            self, "dispatched_at", _timestamp(self.dispatched_at, "dispatched_at")
        )
        object.__setattr__(
            self,
            "dispatch_attempt",
            _positive_int(self.dispatch_attempt, "dispatch_attempt"),
        )
        object.__setattr__(self, "evidence", _freeze_mapping(self.evidence, "evidence"))
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "adapter": self.adapter,
            "handle_id": self.handle_id,
            "dispatched_at": self.dispatched_at,
            "dispatch_attempt": self.dispatch_attempt,
            "evidence": thaw_plain_data(self.evidence, path="evidence"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "DispatchHandle":
        payload = _load_record(
            data,
            "DispatchHandle",
            required={
                "adapter",
                "handle_id",
                "dispatched_at",
                "dispatch_attempt",
                "evidence",
            },
        )
        return cls(
            adapter=cast(str, payload["adapter"]),
            handle_id=cast(str, payload["handle_id"]),
            dispatched_at=cast(str, payload["dispatched_at"]),
            dispatch_attempt=cast(int, payload["dispatch_attempt"]),
            evidence=cast(Mapping[str, PlainData], payload["evidence"]),
        )


@dataclass(frozen=True, slots=True)
class CancellationRecord:
    """Queue-local cancellation request and adapter evidence slots."""

    requested_at: str
    requested_by: str
    reason: str
    evidence: Mapping[str, PlainData] = field(default_factory=dict)
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "requested_at", _timestamp(self.requested_at, "requested_at")
        )
        object.__setattr__(
            self,
            "requested_by",
            validate_queue_id(self.requested_by, "requested_by"),
        )
        object.__setattr__(self, "reason", _non_empty_string(self.reason, "reason"))
        object.__setattr__(self, "evidence", _freeze_mapping(self.evidence, "evidence"))
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "requested_at": self.requested_at,
            "requested_by": self.requested_by,
            "reason": self.reason,
            "evidence": thaw_plain_data(self.evidence, path="evidence"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CancellationRecord":
        payload = _load_record(
            data,
            "CancellationRecord",
            required={"requested_at", "requested_by", "reason", "evidence"},
        )
        return cls(
            requested_at=cast(str, payload["requested_at"]),
            requested_by=cast(str, payload["requested_by"]),
            reason=cast(str, payload["reason"]),
            evidence=cast(Mapping[str, PlainData], payload["evidence"]),
        )


@dataclass(frozen=True, slots=True)
class QueueItem:
    """Durable whole-run queue item."""

    queue_item_id: str
    queue_name: str
    pool_name: str
    run_uri: str
    run_intent: RunIntent
    launch_contract: LaunchContract
    enqueued_at: str
    updated_at: str
    status: QueueItemStatus | str = QueueItemStatus.QUEUED
    dispatch_attempt: int = 1
    claim: QueueClaim | None = None
    dispatch_handle: DispatchHandle | None = None
    cancellation: CancellationRecord | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    scientific_fingerprint: str | None = None
    scientific_deduplication_bypassed: bool = False
    admission_digest: str | None = None
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "queue_item_id",
            validate_queue_id(self.queue_item_id, "queue_item_id"),
        )
        object.__setattr__(
            self,
            "queue_name",
            validate_queue_id(self.queue_name, "queue_name"),
        )
        object.__setattr__(
            self, "pool_name", validate_queue_id(self.pool_name, "pool_name")
        )
        object.__setattr__(self, "run_uri", _non_empty_string(self.run_uri, "run_uri"))
        if not isinstance(self.run_intent, RunIntent):
            raise QueueValidationError("run_intent must be a RunIntent")
        if self.run_intent.run_uri != self.run_uri:
            raise QueueValidationError(
                "run_intent.run_uri must match queue item run_uri"
            )
        if not isinstance(self.launch_contract, LaunchContract):
            raise QueueValidationError("launch_contract must be a LaunchContract")
        object.__setattr__(
            self, "enqueued_at", _timestamp(self.enqueued_at, "enqueued_at")
        )
        object.__setattr__(
            self, "updated_at", _timestamp(self.updated_at, "updated_at")
        )
        object.__setattr__(self, "status", QueueItemStatus(self.status))
        object.__setattr__(
            self,
            "dispatch_attempt",
            _positive_int(self.dispatch_attempt, "dispatch_attempt"),
        )
        if self.claim is not None and not isinstance(self.claim, QueueClaim):
            raise QueueValidationError("claim must be a QueueClaim or None")
        if self.dispatch_handle is not None and not isinstance(
            self.dispatch_handle, DispatchHandle
        ):
            raise QueueValidationError(
                "dispatch_handle must be a DispatchHandle or None"
            )
        if self.cancellation is not None and not isinstance(
            self.cancellation, CancellationRecord
        ):
            raise QueueValidationError(
                "cancellation must be a CancellationRecord or None"
            )
        object.__setattr__(
            self,
            "metadata",
            _freeze_mapping(self.metadata, "metadata"),
        )
        if self.scientific_fingerprint is not None:
            object.__setattr__(
                self,
                "scientific_fingerprint",
                _digest(self.scientific_fingerprint, "scientific_fingerprint"),
            )
        if not isinstance(self.scientific_deduplication_bypassed, bool):
            raise QueueValidationError(
                "scientific_deduplication_bypassed must be a boolean"
            )
        expected_admission_digest = _admission_digest(self)
        if self.admission_digest is None:
            object.__setattr__(self, "admission_digest", expected_admission_digest)
        else:
            admission_digest = _digest(self.admission_digest, "admission_digest")
            if admission_digest != expected_admission_digest:
                raise QueueValidationError(
                    "admission_digest must match immutable enqueue content"
                )
            object.__setattr__(self, "admission_digest", admission_digest)
        _validate_schema(self.schema_version)
        _validate_item_state(self)

    @property
    def terminal(self) -> bool:
        return QueueItemStatus(self.status).value in _TERMINAL_ITEM_STATUSES

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "queue_item_id": self.queue_item_id,
            "queue_name": self.queue_name,
            "pool_name": self.pool_name,
            "run_uri": self.run_uri,
            "status": QueueItemStatus(self.status).value,
            "dispatch_attempt": self.dispatch_attempt,
            "enqueued_at": self.enqueued_at,
            "updated_at": self.updated_at,
            "run_intent": self.run_intent.to_dict(),
            "launch_contract": self.launch_contract.to_dict(),
            "claim": None if self.claim is None else self.claim.to_dict(),
            "dispatch_handle": None
            if self.dispatch_handle is None
            else self.dispatch_handle.to_dict(),
            "cancellation": None
            if self.cancellation is None
            else self.cancellation.to_dict(),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
            "scientific_fingerprint": self.scientific_fingerprint,
            "scientific_deduplication_bypassed": self.scientific_deduplication_bypassed,
            "admission_digest": self.admission_digest,
        }

    @classmethod
    def from_dict(cls, data: object) -> "QueueItem":
        payload = _load_record(
            data,
            "QueueItem",
            required={
                "queue_item_id",
                "queue_name",
                "pool_name",
                "run_uri",
                "status",
                "dispatch_attempt",
                "enqueued_at",
                "updated_at",
                "run_intent",
                "launch_contract",
                "claim",
                "dispatch_handle",
                "cancellation",
                "metadata",
                "scientific_fingerprint",
                "scientific_deduplication_bypassed",
                "admission_digest",
            },
        )
        if payload["admission_digest"] is None:
            raise QueueValidationError(
                "QueueItem.admission_digest must be non-null and supported"
            )
        return cls(
            queue_item_id=cast(str, payload["queue_item_id"]),
            queue_name=cast(str, payload["queue_name"]),
            pool_name=cast(str, payload["pool_name"]),
            run_uri=cast(str, payload["run_uri"]),
            status=cast(str, payload["status"]),
            dispatch_attempt=cast(int, payload["dispatch_attempt"]),
            enqueued_at=cast(str, payload["enqueued_at"]),
            updated_at=cast(str, payload["updated_at"]),
            run_intent=RunIntent.from_dict(payload["run_intent"]),
            launch_contract=LaunchContract.from_dict(payload["launch_contract"]),
            claim=None
            if payload["claim"] is None
            else QueueClaim.from_dict(payload["claim"]),
            dispatch_handle=None
            if payload["dispatch_handle"] is None
            else DispatchHandle.from_dict(payload["dispatch_handle"]),
            cancellation=None
            if payload["cancellation"] is None
            else CancellationRecord.from_dict(payload["cancellation"]),
            metadata=cast(Mapping[str, PlainData], payload["metadata"]),
            scientific_fingerprint=cast(str | None, payload["scientific_fingerprint"]),
            scientific_deduplication_bypassed=cast(
                bool, payload["scientific_deduplication_bypassed"]
            ),
            admission_digest=cast(str, payload["admission_digest"]),
        )


@dataclass(frozen=True, slots=True)
class QueueEnqueueReceipt:
    """The repository-owned classification for one enqueue request."""

    disposition: QueueEnqueueDisposition | str
    requested_queue_item_id: str
    canonical_queue_item_id: str
    queue_item: QueueItem
    accepted_at: str
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "disposition", QueueEnqueueDisposition(self.disposition)
        )
        object.__setattr__(
            self,
            "requested_queue_item_id",
            validate_queue_id(self.requested_queue_item_id, "requested_queue_item_id"),
        )
        object.__setattr__(
            self,
            "canonical_queue_item_id",
            validate_queue_id(self.canonical_queue_item_id, "canonical_queue_item_id"),
        )
        if not isinstance(self.queue_item, QueueItem):
            raise QueueValidationError("queue_item must be a QueueItem")
        if self.canonical_queue_item_id != self.queue_item.queue_item_id:
            raise QueueValidationError(
                "canonical_queue_item_id must match queue_item.queue_item_id"
            )
        object.__setattr__(
            self, "accepted_at", _timestamp(self.accepted_at, "accepted_at")
        )
        if self.accepted_at != self.queue_item.enqueued_at:
            raise QueueValidationError("accepted_at must match queue_item.enqueued_at")
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "disposition": QueueEnqueueDisposition(self.disposition).value,
            "requested_queue_item_id": self.requested_queue_item_id,
            "canonical_queue_item_id": self.canonical_queue_item_id,
            "queue_item": self.queue_item.to_dict(),
            "accepted_at": self.accepted_at,
        }

    @classmethod
    def from_dict(cls, data: object) -> "QueueEnqueueReceipt":
        payload = _load_record(
            data,
            "QueueEnqueueReceipt",
            required={
                "disposition",
                "requested_queue_item_id",
                "canonical_queue_item_id",
                "queue_item",
                "accepted_at",
            },
        )
        return cls(
            disposition=cast(str, payload["disposition"]),
            requested_queue_item_id=cast(str, payload["requested_queue_item_id"]),
            canonical_queue_item_id=cast(str, payload["canonical_queue_item_id"]),
            queue_item=QueueItem.from_dict(payload["queue_item"]),
            accepted_at=cast(str, payload["accepted_at"]),
        )


@dataclass(frozen=True, slots=True)
class QueueAuditEvent:
    """Durable queue audit event."""

    event_id: str
    queue_item_id: str
    event_type: str
    timestamp: str
    detail: Mapping[str, PlainData] = field(default_factory=dict)
    sequence: int | None = None
    schema_version: int = QUEUE_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", validate_queue_id(self.event_id, "event_id")
        )
        object.__setattr__(
            self,
            "queue_item_id",
            validate_queue_id(self.queue_item_id, "queue_item_id"),
        )
        object.__setattr__(
            self,
            "event_type",
            validate_event_type(self.event_type, "event_type"),
        )
        object.__setattr__(self, "timestamp", _timestamp(self.timestamp, "timestamp"))
        object.__setattr__(self, "detail", _freeze_mapping(self.detail, "detail"))
        if self.sequence is not None:
            object.__setattr__(
                self, "sequence", _positive_int(self.sequence, "sequence")
            )
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "queue_item_id": self.queue_item_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "QueueAuditEvent":
        payload = _load_record(
            data,
            "QueueAuditEvent",
            required={
                "event_id",
                "queue_item_id",
                "event_type",
                "timestamp",
                "sequence",
                "detail",
            },
        )
        return cls(
            event_id=cast(str, payload["event_id"]),
            queue_item_id=cast(str, payload["queue_item_id"]),
            event_type=cast(str, payload["event_type"]),
            timestamp=cast(str, payload["timestamp"]),
            sequence=cast(int | None, payload["sequence"]),
            detail=cast(Mapping[str, PlainData], payload["detail"]),
        )


@dataclass(frozen=True, slots=True)
class QueueRecoveryRecord:
    """Queue item selected by repository recovery scans."""

    queue_item_id: str
    status: QueueItemStatus | str
    dispatch_attempt: int
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "queue_item_id",
            validate_queue_id(self.queue_item_id, "queue_item_id"),
        )
        object.__setattr__(self, "status", QueueItemStatus(self.status))
        object.__setattr__(
            self,
            "dispatch_attempt",
            _positive_int(self.dispatch_attempt, "dispatch_attempt"),
        )
        object.__setattr__(self, "detail", _freeze_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "queue_item_id": self.queue_item_id,
            "status": QueueItemStatus(self.status).value,
            "dispatch_attempt": self.dispatch_attempt,
            "detail": thaw_plain_data(self.detail, path="detail"),
        }


def validate_one_queue_per_pool(
    pools: Sequence[QueuePool],
    queues: Sequence[QueueDefinition],
) -> None:
    """Validate the v11 topology rule of exactly one queue per pool."""

    pool_names: set[str] = set()
    for pool in pools:
        if pool.pool_name in pool_names:
            raise QueueValidationError(f"duplicate pool: {pool.pool_name}")
        pool_names.add(pool.pool_name)
    queue_names: set[str] = set()
    queues_by_pool: dict[str, str] = {}
    for queue in queues:
        if queue.queue_name in queue_names:
            raise QueueValidationError(f"duplicate queue: {queue.queue_name}")
        queue_names.add(queue.queue_name)
        if queue.pool_name not in pool_names:
            raise QueueValidationError(f"unknown queue pool: {queue.pool_name}")
        existing = queues_by_pool.get(queue.pool_name)
        if existing is not None:
            raise QueueValidationError(
                f"pool {queue.pool_name} has multiple queues: "
                f"{existing}, {queue.queue_name}"
            )
        queues_by_pool[queue.pool_name] = queue.queue_name
    missing = pool_names - set(queues_by_pool)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise QueueValidationError(f"pool(s) missing queue: {missing_text}")


def validate_queue_id(value: object, field_name: str) -> str:
    text = _non_empty_string(value, field_name)
    if _SAFE_ID_RE.fullmatch(text) is None:
        raise QueueValidationError(
            f"{field_name} must start with an alphanumeric character and contain "
            "only alphanumerics, '_', '.', ':', or '-'"
        )
    return text


def validate_event_type(value: object, field_name: str) -> str:
    text = _non_empty_string(value, field_name)
    if not all(part for part in text.split(".")):
        raise QueueValidationError(f"{field_name} must use non-empty dotted parts")
    return text


def _validate_item_state(item: QueueItem) -> None:
    status = QueueItemStatus(item.status)
    if status is QueueItemStatus.CLAIMED and item.claim is None:
        raise QueueValidationError("CLAIMED queue items require claim")
    if status is QueueItemStatus.DISPATCHED and item.dispatch_handle is None:
        raise QueueValidationError("DISPATCHED queue items require dispatch_handle")
    if status is QueueItemStatus.CANCELLED and item.cancellation is None:
        raise QueueValidationError("CANCELLED queue items require cancellation")
    if item.claim is not None and item.claim.dispatch_attempt != item.dispatch_attempt:
        raise QueueValidationError("claim dispatch_attempt must match queue item")
    if (
        item.dispatch_handle is not None
        and item.dispatch_handle.dispatch_attempt != item.dispatch_attempt
    ):
        raise QueueValidationError(
            "dispatch_handle dispatch_attempt must match queue item"
        )


def _load_record(
    data: object,
    record_name: str,
    *,
    required: set[str],
) -> dict[str, object]:
    try:
        return load_versioned_document(
            data,
            current_version=QUEUE_RECORD_SCHEMA_VERSION,
            required=required,
            path=record_name,
        )
    except SchemaVersionError as exc:
        raise QueueValidationError(f"{record_name}.from_dict: {exc}") from exc


def _freeze_mapping(
    value: Mapping[str, PlainData], field_name: str
) -> Mapping[str, PlainData]:
    try:
        frozen = freeze_plain_data(value, path=field_name)
    except PlainDataError as exc:
        raise QueueValidationError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise QueueValidationError(f"{field_name} must be a mapping")
    return cast(Mapping[str, PlainData], frozen)


def _validate_non_negative_int_mapping(
    value: Mapping[str, int],
    field_name: str,
) -> Mapping[str, int]:
    output: dict[str, int] = {}
    if not isinstance(value, Mapping):
        raise QueueValidationError(f"{field_name} must be a mapping")
    for key, amount in value.items():
        validate_queue_id(key, f"{field_name} key")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise QueueValidationError(
                f"{field_name}.{key} must be a non-negative integer"
            )
        output[key] = amount
    return MappingProxyType(output)


def _validate_string_mapping(
    value: Mapping[str, str],
    field_name: str,
) -> Mapping[str, str]:
    output: dict[str, str] = {}
    if not isinstance(value, Mapping):
        raise QueueValidationError(f"{field_name} must be a mapping")
    for key, item in value.items():
        validate_queue_id(key, f"{field_name} key")
        output[key] = _non_empty_string(item, f"{field_name}.{key}")
    return MappingProxyType(output)


def _validate_schema(schema_version: object) -> None:
    require_schema_version(
        schema_version,
        current=QUEUE_RECORD_SCHEMA_VERSION,
        error_type=QueueValidationError,
    )


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise QueueValidationError(f"{field_name} must be a non-empty string")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise QueueValidationError(f"{field_name} must be a positive integer")
    return value


def _timestamp(value: object, field_name: str) -> str:
    text = _non_empty_string(value, field_name)
    try:
        parse_timestamp(text)
    except ValueError as exc:
        raise QueueValidationError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc
    return text


def _digest(value: object, field_name: str) -> str:
    try:
        return validate_digest(value)
    except (
        Exception
    ) as exc:  # fingerprint errors intentionally become queue validation.
        raise QueueValidationError(f"{field_name} must be a supported digest") from exc


def _admission_digest(item: QueueItem) -> str:
    """Hash the immutable normalized enqueue intent, never lifecycle facts."""

    return hash_mapping(
        {
            "queue_item_id": item.queue_item_id,
            "queue_name": item.queue_name,
            "pool_name": item.pool_name,
            "run_uri": item.run_uri,
            "run_intent": item.run_intent.to_dict(),
            "launch_contract": item.launch_contract.to_dict(),
            "metadata": thaw_plain_data(item.metadata, path="metadata"),
            "scientific_fingerprint": item.scientific_fingerprint,
            "scientific_deduplication_bypassed": item.scientific_deduplication_bypassed,
        }
    )


__all__ = [
    "QUEUE_RECORD_SCHEMA_VERSION",
    "CancellationRecord",
    "DispatchHandle",
    "LaunchContract",
    "QueueAuditEvent",
    "QueueClaim",
    "QueueDefinition",
    "QueueEnqueueDisposition",
    "QueueEnqueueReceipt",
    "QueueItem",
    "QueueItemStatus",
    "QueuePool",
    "QueuePoolMode",
    "QueueRecoveryRecord",
    "RunIntent",
    "validate_one_queue_per_pool",
    "validate_queue_id",
]
