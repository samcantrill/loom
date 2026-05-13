"""Queue model and repository errors."""

from __future__ import annotations


class QueueError(Exception):
    """Base error for queue records and repositories."""


class QueueValidationError(ValueError, QueueError):
    """Raised when a queue record is invalid."""


class QueueStorageError(RuntimeError, QueueError):
    """Raised when queue repository storage fails."""


class QueueConflictError(QueueStorageError):
    """Raised when a queue repository write conflicts with durable state."""


class QueueSchemaError(QueueStorageError):
    """Raised when a queue repository schema is missing or incompatible."""


__all__ = [
    "QueueConflictError",
    "QueueError",
    "QueueSchemaError",
    "QueueStorageError",
    "QueueValidationError",
]
