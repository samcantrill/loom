"""Errors for deterministic sweep contracts."""

from __future__ import annotations

from dataclasses import dataclass

from loom.serialization import PlainData


class SweepError(ValueError):
    """Base error for sweep contract validation and decoding failures."""


class SweepProtocolError(SweepError):
    """Raised when provider/dispatch/feedback contracts are invalid."""


class SweepManifestError(SweepError):
    """Raised when a sweep manifest cannot be parsed or is incompatible."""


@dataclass(frozen=True, slots=True)
class SweepManifestCompatibilityDiagnostic:
    """Structured diagnostic for manifest compatibility checks."""

    code: str
    sweep_dir: str
    manifest_name: str
    message: str
    detail: dict[str, PlainData]


class SweepExtractionError(SweepError):
    """Raised when extraction request or result contracts are malformed."""


__all__ = [
    "SweepError",
    "SweepProtocolError",
    "SweepManifestError",
    "SweepManifestCompatibilityDiagnostic",
    "SweepExtractionError",
]
