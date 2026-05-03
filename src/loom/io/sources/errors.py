"""Errors for local/remote data sources."""

from __future__ import annotations

from loom.io.errors import LoomIOError


class DataSourceError(LoomIOError):
    """Base error for source-level operations."""


class SourceNotFoundError(DataSourceError):
    """Error raised when a source resource is missing."""


class SourcePermissionError(DataSourceError):
    """Error raised for permission problems while accessing a source."""


class UnsupportedSourceOperationError(DataSourceError):
    """Error raised when a source operation is unsupported."""


__all__ = [
    "DataSourceError",
    "SourceNotFoundError",
    "SourcePermissionError",
    "UnsupportedSourceOperationError",
]

