"""Read models for queue dispatch status joins."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError

from .controller import QueueDispatchInspection, QueueInspectableDispatchAdapter
from .errors import QueueServiceError
from .models import QueueAuditEvent, QueueItem, QueueItemStatus, QueueRecoveryRecord
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
class QueueOperationalStatus:
    """Operator-facing queue status read model."""

    service_status: QueueServiceStatus
    item_inspection: QueueItemInspection | None = None
    active_items: tuple[QueueManagedItemStatus, ...] = ()
    service_scope: str = "in_process_command"

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "service_scope": self.service_scope,
            "service": self.service_status.to_dict(),
            "item": None
            if self.item_inspection is None
            else _item_inspection_dict(self.item_inspection),
            "active_items": [status.to_dict() for status in self.active_items],
            "ownership": queue_ownership_summary(),
        }


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
    adapters: Mapping[str, QueueInspectableDispatchAdapter] | None = None,
) -> QueueOperationalStatus:
    """Build a queue status report without changing queue state."""

    item_inspection = (
        None if queue_item_id is None else service.inspect_item(queue_item_id)
    )
    active_items = (
        ()
        if adapters is None
        else inspect_managed_queue_status(service, adapters=adapters)
    )
    return QueueOperationalStatus(
        service_status=service.status(),
        item_inspection=item_inspection,
        active_items=active_items,
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
    "QueueManagedItemStatus",
    "QueueOperationalStatus",
    "build_queue_operational_status",
    "inspect_managed_queue_status",
    "queue_ownership_summary",
]
