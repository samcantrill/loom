"""Store-specific error hierarchy for artifact and run persistence."""

from __future__ import annotations

from loom.errors import ArtifactError, PipelineError


class StoreError(PipelineError):
    """Base error for run and artifact store failures."""


class ArtifactStoreError(StoreError, ArtifactError):
    """Base error for artifact store failures."""


class RunStoreError(StoreError):
    """Base error for run-store failures."""


class RunLockError(RunStoreError):
    """Base error for run lock failures."""


class RunLockConflictError(RunLockError):
    """Raised when a run lock already exists."""


class RunLockReleaseError(RunLockError):
    """Raised when a run lock cannot be released."""


class UnsafeStorePathError(StoreError):
    """Raised when a filesystem path component is unsafe."""


class InvalidRunURIError(RunStoreError):
    """Raised when a run URI is malformed or unsupported."""


class AtomicWriteError(StoreError):
    """Raised when atomic file writes cannot complete."""


class UnsupportedArtifactURIError(ArtifactStoreError):
    """Raised when artifact references use unsupported URI schemes."""


class ArtifactNotFoundError(ArtifactStoreError):
    """Raised when the artifact source path is missing."""


class MissingArtifactCodecError(ArtifactStoreError):
    """Raised when artifact loading cannot determine a codec."""


class ArtifactTypeMismatchError(ArtifactStoreError):
    """Raised when artifact type/shape is incompatible with an operation."""


class ArtifactChecksumMismatchError(ArtifactStoreError):
    """Raised when artifact checksum validation fails."""


class ArtifactChecksumUnsupportedError(ArtifactStoreError):
    """Raised when checksum behavior is unsupported for an artifact."""


class RunAlreadyExistsError(RunStoreError):
    """Raised when attempting to initialize an existing run directory."""


class RunNotFoundError(RunStoreError):
    """Raised when a run directory is missing."""


class MissingStoreDocumentError(RunStoreError):
    """Raised when a required store document is missing."""


class CorruptStoreDocumentError(RunStoreError):
    """Raised when a persisted store document is invalid."""


class StageStateNotFoundError(RunStoreError):
    """Raised when stage state for a run is missing."""


__all__ = [
    "StoreError",
    "ArtifactStoreError",
    "RunStoreError",
    "RunLockError",
    "RunLockConflictError",
    "RunLockReleaseError",
    "UnsafeStorePathError",
    "InvalidRunURIError",
    "UnsupportedArtifactURIError",
    "ArtifactNotFoundError",
    "MissingArtifactCodecError",
    "ArtifactTypeMismatchError",
    "ArtifactChecksumMismatchError",
    "ArtifactChecksumUnsupportedError",
    "RunAlreadyExistsError",
    "RunNotFoundError",
    "MissingStoreDocumentError",
    "CorruptStoreDocumentError",
    "StageStateNotFoundError",
    "AtomicWriteError",
]
