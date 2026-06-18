"""Plugin discovery errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .entrypoints import PluginDuplicate, PluginLoadResult


class PluginError(RuntimeError):
    """Base exception for plugin discovery."""


class PluginDiscoveryError(PluginError):
    """Raised when plugin discovery metadata cannot be parsed."""


class PluginInvalidEntryPointError(PluginDiscoveryError):
    """Raised when an entry point is missing required metadata."""


class PluginLoadError(PluginError):
    """Raised when plugin loading fails in strict mode."""

    def __init__(
        self,
        message: str,
        *,
        result: "PluginLoadResult | None" = None,
    ) -> None:
        self.result = result
        super().__init__(message)


class PluginDuplicateError(PluginLoadError):
    """Raised when duplicate entry point records are selected in strict mode."""

    def __init__(
        self,
        duplicates: tuple["PluginDuplicate", ...],
        *,
        result: "PluginLoadResult | None" = None,
    ) -> None:
        self.duplicates = duplicates
        super().__init__(
            "duplicate plugin selection is not allowed in strict mode",
            result=result,
        )


class PluginRegistrationError(PluginLoadError):
    """Raised when a plugin registration callback fails."""
