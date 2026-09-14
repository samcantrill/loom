"""Plain durable run intent, separate from in-process pipeline execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from loom.serialization import PlainData

from .errors import QueueServiceError
from .preparation import PrepareRunRequest


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Freeze one submission through native preparation, binding and admission.

    ``mode="exact"`` preserves the supplied target and queue identity and never
    retries on replay. ``mode="reconcile"`` requires both identities to be None;
    an installed project derives its canonical target after checking final inputs.
    ``retry_policy="one_observed_failure"`` authorizes one durably observed failed
    revision for that submission. Replay cannot authorize any later failure.
    Cancellation after binding cancels the shared target for all observers.
    """

    preparation: PrepareRunRequest
    queue_item_id: str | None = None
    mode: str = "exact"
    retry_policy: str = "never"

    def __post_init__(self) -> None:
        if not isinstance(self.preparation, PrepareRunRequest):
            raise QueueServiceError("run preparation is invalid")
        if (
            not isinstance(self.mode, str)
            or self.mode not in {"exact", "reconcile"}
            or not isinstance(self.retry_policy, str)
            or self.retry_policy not in {"never", "one_observed_failure"}
        ):
            raise QueueServiceError("run reconciliation intent is invalid")
        if self.mode == "reconcile":
            if self.queue_item_id is not None or self.preparation.run_name is not None:
                raise QueueServiceError("reconciled run target must be unresolved")
            return
        if self.preparation.run_name is None or self.retry_policy != "never":
            raise QueueServiceError("exact run requires a target and never retries")
        if not isinstance(self.queue_item_id, str) or not self.queue_item_id:
            raise QueueServiceError("queue_item_id must be a non-empty string")

    def to_dict(self) -> dict[str, PlainData]:
        if self.mode == "reconcile":
            return {
                "mode": "reconcile",
                "preparation": self.preparation.to_dict(),
                "queue_item_id": None,
                "retry_policy": self.retry_policy,
            }
        return {
            "preparation": self.preparation.to_dict(),
            "queue_item_id": self.queue_item_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunRequest:
        if data.get("mode") == "reconcile":
            if set(data) != {
                "mode",
                "preparation",
                "queue_item_id",
                "retry_policy",
            } or not isinstance(data["preparation"], Mapping):
                raise QueueServiceError("reconciled run fields are invalid")
            return cls(
                PrepareRunRequest.from_dict(data["preparation"]),
                cast(str | None, data["queue_item_id"]),
                "reconcile",
                cast(str, data["retry_policy"]),
            )
        if set(data) != {"preparation", "queue_item_id"}:
            raise QueueServiceError("run request fields are invalid")
        preparation, queue_id = data["preparation"], data["queue_item_id"]
        if not isinstance(preparation, Mapping) or not isinstance(queue_id, str):
            raise QueueServiceError("run request is invalid")
        return cls(PrepareRunRequest.from_dict(preparation), queue_id)


def _public_operation_id(operation_id: str) -> None:
    """Keep native cancellation identities unavailable to caller-owned controls."""
    from .errors import QueueConflictError

    if operation_id.startswith("cancel-run-"):
        raise QueueConflictError("run cancellation operation namespace is reserved")
