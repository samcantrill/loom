"""Plain durable run intent, separate from in-process pipeline execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from loom.serialization import PlainData

from .errors import QueueServiceError
from .preparation import PrepareRunRequest


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Prepare and admit once using the preparation operation and exact queue ID.

    Replaying this intent observes its original admission, including failure;
    it never requests an explicit failed-admission retry.
    """

    preparation: PrepareRunRequest
    queue_item_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.preparation, PrepareRunRequest):
            raise QueueServiceError("run preparation is invalid")
        if not isinstance(self.queue_item_id, str) or not self.queue_item_id:
            raise QueueServiceError("queue_item_id must be a non-empty string")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "preparation": self.preparation.to_dict(),
            "queue_item_id": self.queue_item_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunRequest:
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
