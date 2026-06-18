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
