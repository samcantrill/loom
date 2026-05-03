"""Provenance-specific errors."""

from __future__ import annotations

from loom.errors import ProvenanceError as _ProvenanceError


class ProvenanceCaptureError(_ProvenanceError):
    """Error raised when provenance capture cannot complete in strict mode."""


class ProvenanceValidationError(_ProvenanceError):
    """Error raised when provenance documents are invalid."""


class ProvenanceRedactionError(_ProvenanceError):
    """Error raised when redaction cannot be applied."""


__all__ = ["ProvenanceCaptureError", "ProvenanceValidationError", "ProvenanceRedactionError"]
