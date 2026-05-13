"""Read models for queue dispatch status joins."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.serialization.errors import PlainDataError

from .controller import QueueDispatchInspection, QueueInspectableDispatchAdapter
from .errors import QueueServiceError
from .models import QueueItem, QueueItemStatus, QueueRecoveryRecord
from .service import QueueService


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


__all__ = ["QueueManagedItemStatus", "inspect_managed_queue_status"]
