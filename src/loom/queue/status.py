"""Read models for queue dispatch status joins."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError

from .controller import QueueDispatchInspection, QueueInspectableDispatchAdapter
from .errors import QueueServiceError
from .models import QueueAuditEvent, QueueItem, QueueItemStatus, QueueRecoveryRecord
from .repository import QueuePoolSnapshot
from .service import QueueItemInspection, QueueService, QueueServiceStatus


@dataclass(frozen=True, slots=True)
class QueueManagedItemStatus:
    """Queue item status with adapter recovery evidence when available."""

    item: QueueItem
    recovery_record: QueueRecoveryRecord | None = None
    adapter_inspection: QueueDispatchInspection | None = None
    authority_evidence: Mapping[str, PlainData] = field(default_factory=dict)

    @property
    def status(self) -> QueueItemStatus:
        if self.adapter_inspection is not None:
            return self.adapter_inspection.status
        return QueueItemStatus(self.item.status)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "item": self.item.to_dict(),
            "status": self.status.value,
            "recovery_record": None
            if self.recovery_record is None
            else self.recovery_record.to_dict(),
            "adapter_inspection": None
            if self.adapter_inspection is None
            else {
                "status": self.adapter_inspection.status.value,
                "reason": self.adapter_inspection.reason,
                "terminal": self.adapter_inspection.terminal,
                "handoff_complete": self.adapter_inspection.handoff_complete,
                "evidence": thaw_plain_data(
                    self.adapter_inspection.evidence,
                    path="adapter_inspection.evidence",
                ),
            },
            "authority_evidence": thaw_plain_data(
                self.authority_evidence,
                path="authority_evidence",
            ),
        }


@dataclass(frozen=True, slots=True)
class QueuePoolCounts:
    """Fixed lifecycle counts for one selected pool snapshot."""

    queued: int = 0
    claimed: int = 0
    dispatched: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    unknown: int = 0

    @property
    def active(self) -> int:
        return self.claimed + self.dispatched

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "queued": self.queued,
            "claimed": self.claimed,
            "dispatched": self.dispatched,
            "active": self.active,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "unknown": self.unknown,
        }


@dataclass(frozen=True, slots=True)
class QueueActiveAttemptStatus:
    """Allowlisted active-attempt facts for the pool status read model."""

    queue_item_id: str
    status: QueueItemStatus
    owner_id: str | None
    session_id: str | None
    evidence_source: str
    live_observation: str
    process: Mapping[str, PlainData] | None
    assignment: Mapping[str, PlainData] | None
    logs: Mapping[str, PlainData] | None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "queue_item_id": self.queue_item_id,
            "status": self.status.value,
            "owner_id": self.owner_id,
            "session_id": self.session_id,
            "evidence_source": self.evidence_source,
            "live_observation": self.live_observation,
            "process": None if self.process is None else dict(self.process),
            "assignment": None if self.assignment is None else _plain_dict(self.assignment),
            "logs": None if self.logs is None else dict(self.logs),
        }


@dataclass(frozen=True, slots=True)
class QueuePoolStatus:
    """Safe, selected-pool operational status derived from one snapshot."""

    pool_name: str
    controller_max_active_items: int
    counts: QueuePoolCounts
    active_attempts: tuple[QueueActiveAttemptStatus, ...]

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "pool_name": self.pool_name,
            "controller_max_active_items": self.controller_max_active_items,
            "counts": self.counts.to_dict(),
            "active_attempts": [attempt.to_dict() for attempt in self.active_attempts],
        }


@dataclass(frozen=True, slots=True)
class QueueOperationalStatus:
    """Operator-facing queue status read model."""

    service_status: QueueServiceStatus
    item_inspection: QueueItemInspection | None = None
    active_items: tuple[QueueManagedItemStatus, ...] = ()
    pool_status: QueuePoolStatus | None = None
    service_scope: str = "in_process_command"

    def to_dict(self) -> dict[str, PlainData]:
        result: dict[str, PlainData] = {
            "service_scope": self.service_scope,
            "service": self.service_status.to_dict(),
            "item": None
            if self.item_inspection is None
            else _item_inspection_dict(self.item_inspection),
            "active_items": [status.to_dict() for status in self.active_items],
            "ownership": queue_ownership_summary(),
        }
        if self.pool_status is not None:
            result["pool"] = self.pool_status.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class QueueCancellationStatus:
    """Operator-facing cancellation result."""

    item: QueueItem

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "item": self.item.to_dict(),
            "ownership": queue_ownership_summary(),
        }


def build_queue_operational_status(
    service: QueueService,
    *,
    queue_item_id: str | None = None,
    pool_name: str | None = None,
    adapters: Mapping[str, QueueInspectableDispatchAdapter] | None = None,
) -> QueueOperationalStatus:
    """Build a queue status report without changing queue state."""

    if queue_item_id is not None and pool_name is not None:
        raise QueueServiceError("queue status accepts either an item or a pool")
    item_inspection = (
        None if queue_item_id is None else service.inspect_item(queue_item_id)
    )
    active_items = (
        ()
        if adapters is None or pool_name is not None
        else inspect_managed_queue_status(service, adapters=adapters)
    )
    pool_status = (
        None
        if pool_name is None
        else build_queue_pool_status(service, pool_name=pool_name, adapters=adapters)
    )
    return QueueOperationalStatus(
        service_status=service.status(),
        item_inspection=item_inspection,
        active_items=active_items,
        pool_status=pool_status,
    )


def build_queue_pool_status(
    service: QueueService,
    *,
    pool_name: str,
    adapters: Mapping[str, QueueInspectableDispatchAdapter] | None = None,
) -> QueuePoolStatus:
    """Build a redacted selected-pool status from one durable snapshot."""

    snapshot = service.read_pool_snapshot(pool_name)
    return _pool_status_from_snapshot(
        snapshot,
        controller_max_active_items=service.spec.controller.max_active_items,
        adapters={} if adapters is None else dict(adapters),
    )


def queue_ownership_summary() -> dict[str, PlainData]:
    """Return stable operator wording for queue/status ownership."""

    return {
        "queue_state": "queue service owns scheduling intent, dispatch handles, and queue-local item status",
        "authority_state": "authority remains the source of run lifecycle and coordination truth",
        "delegated_scheduler_state": (
            "delegated adapters report external scheduler evidence; SLURM-pending "
            "work does not hold Loom resource leases by default"
        ),
    }


def inspect_managed_queue_status(
    service: QueueService,
    *,
    adapters: Mapping[str, QueueInspectableDispatchAdapter] | None = None,
) -> tuple[QueueManagedItemStatus, ...]:
    """Join active queue records with local/delegated adapter observations."""

    adapters = {} if adapters is None else dict(adapters)
    recovery_records = {
        record.queue_item_id: record for record in service.scan_recovery()
    }
    statuses: list[QueueManagedItemStatus] = []
    for item in service.recovery_items():
        adapter = adapters.get(item.launch_contract.adapter)
        inspection = None
        if adapter is not None and QueueItemStatus(item.status) is QueueItemStatus.DISPATCHED:
            inspection = adapter.inspect(item)
        statuses.append(
            QueueManagedItemStatus(
                item=item,
                recovery_record=recovery_records.get(item.queue_item_id),
                adapter_inspection=inspection,
                authority_evidence=_authority_evidence(item),
            )
        )
    return tuple(statuses)


def _pool_status_from_snapshot(
    snapshot: QueuePoolSnapshot,
    *,
    controller_max_active_items: int,
    adapters: Mapping[str, QueueInspectableDispatchAdapter],
) -> QueuePoolStatus:
    counts = QueuePoolCounts(
        **{
            status.value.lower(): sum(
                1 for item in snapshot.items if QueueItemStatus(item.status) is status
            )
            for status in QueueItemStatus
        }
    )
    attempts = tuple(
        _active_attempt_status(item, adapters=adapters)
        for item in snapshot.items
        if QueueItemStatus(item.status)
        in {QueueItemStatus.CLAIMED, QueueItemStatus.DISPATCHED}
    )
    return QueuePoolStatus(
        pool_name=snapshot.pool_name,
        controller_max_active_items=controller_max_active_items,
        counts=counts,
        active_attempts=attempts,
    )


def _active_attempt_status(
    item: QueueItem,
    *,
    adapters: Mapping[str, QueueInspectableDispatchAdapter],
) -> QueueActiveAttemptStatus:
    status = QueueItemStatus(item.status)
    owner_id = None if item.claim is None else item.claim.owner_id
    if status is QueueItemStatus.CLAIMED:
        return QueueActiveAttemptStatus(
            queue_item_id=item.queue_item_id,
            status=status,
            owner_id=owner_id,
            session_id=None,
            evidence_source="unavailable",
            live_observation="not_requested",
            process=None,
            assignment=None,
            logs=None,
        )
    projection = _managed_local_projection(item)
    if projection is None:
        return QueueActiveAttemptStatus(
            queue_item_id=item.queue_item_id,
            status=status,
            owner_id=owner_id,
            session_id=None,
            evidence_source="unavailable",
            live_observation="not_requested",
            process=None,
            assignment=None,
            logs=None,
        )
    live_observation = "not_requested"
    evidence_source = "persisted"
    handle = item.dispatch_handle
    assert handle is not None
    adapter = adapters.get(item.launch_contract.adapter)
    if adapter is not None:
        if _same_session_adapter(adapter, item, projection):
            try:
                inspection = adapter.inspect(item)
            except Exception:  # observation is optional and never changes durable facts
                live_observation = "unavailable"
            else:
                if inspection.evidence.get("handle_id") == handle.handle_id:
                    live_observation = "same_session"
                    evidence_source = "same_session_live"
                else:
                    live_observation = "unavailable"
        else:
            live_observation = "unavailable"
    return QueueActiveAttemptStatus(
        queue_item_id=item.queue_item_id,
        status=status,
        owner_id=owner_id,
        session_id=_string(projection["session_id"]),
        evidence_source=evidence_source,
        live_observation=live_observation,
        process=_mapping_or_none(projection["process"]),
        assignment=_mapping_or_none(projection["assignment"]),
        logs=_mapping_or_none(projection["logs"]),
    )


def _managed_local_projection(item: QueueItem) -> Mapping[str, PlainData] | None:
    """Copy the Phase 2 projection field-by-field; never traverse raw evidence."""

    handle = item.dispatch_handle
    if handle is None:
        return None
    raw = handle.evidence.get("managed_local")
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        return None
    owner_id = raw.get("owner_id")
    session_id = raw.get("session_id")
    pid, pgid = raw.get("pid"), raw.get("pgid")
    assignment, logs = raw.get("assignment"), raw.get("logs")
    if not (
        isinstance(owner_id, str)
        and isinstance(session_id, str)
        and isinstance(pid, int)
        and not isinstance(pid, bool)
        and isinstance(pgid, int)
        and not isinstance(pgid, bool)
        and isinstance(assignment, Mapping)
        and isinstance(logs, Mapping)
    ):
        return None
    provider_name, slots = assignment.get("provider_name"), assignment.get("slots")
    stdout_path, stderr_path = logs.get("stdout_path"), logs.get("stderr_path")
    if not (
        isinstance(provider_name, str)
        and isinstance(slots, Sequence)
        and not isinstance(slots, str)
        and _queue_relative_path(stdout_path)
        and _queue_relative_path(stderr_path)
    ):
        return None
    safe_slots: list[PlainData] = []
    for raw_slot in slots:
        if not isinstance(raw_slot, Mapping):
            return None
        required = ("resource_name", "slot_id", "lease_id", "expires_at")
        if not all(isinstance(raw_slot.get(name), str) for name in required):
            return None
        label = raw_slot.get("label")
        if label is not None and not isinstance(label, str):
            return None
        safe_slot: dict[str, PlainData] = {
            name: _string(raw_slot[name]) for name in required
        }
        safe_slot["label"] = label
        safe_slots.append(safe_slot)
    return {
        "owner_id": owner_id,
        "session_id": session_id,
        "process": {"pid": pid, "pgid": pgid},
        "assignment": {"provider_name": provider_name, "slots": safe_slots},
        "logs": {"stdout_path": stdout_path, "stderr_path": stderr_path},
    }


def _same_session_adapter(
    adapter: QueueInspectableDispatchAdapter,
    item: QueueItem,
    projection: Mapping[str, PlainData],
) -> bool:
    handle = item.dispatch_handle
    return bool(
        handle is not None
        and getattr(adapter, "owner_id", None) == projection["owner_id"]
        and getattr(adapter, "session_id", None) == projection["session_id"]
    )


def _queue_relative_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and ".." not in value.split("/")
    )


def _mapping_or_none(value: PlainData) -> Mapping[str, PlainData] | None:
    return value if isinstance(value, Mapping) else None


def _plain_dict(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return {key: list(item) if key == "slots" and isinstance(item, list) else item for key, item in value.items()}


def _string(value: PlainData) -> str:
    assert isinstance(value, str)
    return value


def _authority_evidence(item: QueueItem) -> Mapping[str, PlainData]:
    if item.dispatch_handle is None:
        return {}
    evidence = item.dispatch_handle.evidence.get("resource_admission")
    if not isinstance(evidence, Mapping):
        return {}
    try:
        thawed = thaw_plain_data(
            {"resource_admission": evidence},
            path="authority_evidence",
        )
        frozen = freeze_plain_data(thawed, path="authority_evidence")
    except PlainDataError as exc:
        raise QueueServiceError(str(exc)) from exc
    if not isinstance(frozen, Mapping):
        raise QueueServiceError("authority_evidence must be a mapping")
    return frozen


def _item_inspection_dict(inspection: QueueItemInspection) -> dict[str, PlainData]:
    return {
        "item": None if inspection.item is None else inspection.item.to_dict(),
        "audit_events": [
            _audit_event_dict(event) for event in inspection.audit_events
        ],
        "recovery_records": [
            record.to_dict() for record in inspection.recovery_records
        ],
    }


def _audit_event_dict(event: QueueAuditEvent) -> dict[str, PlainData]:
    return event.to_dict()


__all__ = [
    "QueueCancellationStatus",
    "QueueActiveAttemptStatus",
    "QueueManagedItemStatus",
    "QueueOperationalStatus",
    "QueuePoolCounts",
    "QueuePoolStatus",
    "build_queue_operational_status",
    "build_queue_pool_status",
    "inspect_managed_queue_status",
    "queue_ownership_summary",
]
