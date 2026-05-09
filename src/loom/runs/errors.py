"""Public run-catalog error hierarchy."""

from __future__ import annotations

from loom.errors import LoomError, ValidationError


class CatalogError(LoomError):
    """Base error for run-catalog operations."""


class CatalogValidationError(CatalogError, ValidationError):
    """Raised when public run-catalog data is invalid."""


class CatalogFeatureUnavailableError(CatalogError):
    """Raised when a catalog feature is defined but not implemented yet."""


class CatalogStorageError(CatalogError):
    """Raised for catalog storage failures."""


__all__ = [
    "CatalogError",
    "CatalogFeatureUnavailableError",
    "CatalogStorageError",
    "CatalogValidationError",
]
