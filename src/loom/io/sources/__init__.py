"""Data source interfaces and implementations."""

from .base import DataSource
from .errors import DataSourceError, SourceNotFoundError, SourcePermissionError, UnsupportedSourceOperationError
from .local import LocalFileSystemSource

__all__ = [
    "DataSource",
    "LocalFileSystemSource",
    "DataSourceError",
    "SourceNotFoundError",
    "SourcePermissionError",
    "UnsupportedSourceOperationError",
]

