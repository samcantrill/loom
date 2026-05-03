"""Record domain errors."""

from __future__ import annotations

from loom.errors import ValidationError


class RecordError(ValidationError):
    """Base error for invalid records."""


class RecordNotFoundError(RecordError, KeyError):
    """Raised when a record is not present."""


class ManifestError(RecordError):
    """Base error for manifest validation and lookup."""


class DuplicateRecordError(ManifestError):
    """Raised when manifest construction sees duplicate record IDs."""
