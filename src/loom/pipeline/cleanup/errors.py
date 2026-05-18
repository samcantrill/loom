"""Cleanup-specific errors."""

from __future__ import annotations


class CleanupError(ValueError):
    """Base error for cleanup records, selectors, and safety decisions."""


class CleanupRecordError(CleanupError):
    """Raised when cleanup records are malformed."""


class CleanupSelectorError(CleanupError):
    """Raised when cleanup selector records are malformed."""


class CleanupSafetyError(CleanupError):
    """Raised when cleanup safety inputs are malformed."""


__all__ = [
    "CleanupError",
    "CleanupRecordError",
    "CleanupSelectorError",
    "CleanupSafetyError",
]
