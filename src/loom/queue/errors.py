"""Queue model and repository errors."""

from __future__ import annotations


class QueueError(Exception):
    """Base error for queue records and repositories."""


class QueueValidationError(ValueError, QueueError):
    """Raised when a queue record is invalid."""


class QueueConfigError(QueueValidationError):
    """Raised when queue configuration cannot be loaded or normalized."""


class QueueServiceError(RuntimeError, QueueError):
    """Raised when queue service operations are unavailable or invalid."""


class _AcceptedTimeError(QueueServiceError):
    """Bounded clock-health evidence for coordinator and agent retry logs."""

    def __init__(self, diagnostic: str, time_revision: int) -> None:
        super().__init__(
            "coordinator accepted-time is degraded; operator recovery is required"
        )
        self.diagnostic = diagnostic
        self.time_revision = time_revision

    def details(self) -> dict[str, str | int]:
        return {
            "code": "accepted_time_degraded",
            "diagnostic": self.diagnostic,
            "time_revision": self.time_revision,
            "retry_requires": "operator_time_recovery",
        }


class QueueServiceStateError(QueueServiceError):
    """Raised when an operation is invalid for the current service state."""


class QueueStorageError(RuntimeError, QueueError):
    """Raised when queue repository storage fails."""


class QueueConflictError(QueueStorageError):
    """Raised when a queue repository write conflicts with durable state."""


class QueueSchemaError(QueueStorageError):
    """Raised when a queue repository schema is missing or incompatible."""


__all__ = [
    "QueueConfigError",
    "QueueConflictError",
    "QueueError",
    "QueueSchemaError",
    "QueueServiceError",
    "QueueServiceStateError",
    "QueueStorageError",
    "QueueValidationError",
]
