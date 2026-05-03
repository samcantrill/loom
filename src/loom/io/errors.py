"""I/O error hierarchy."""

from __future__ import annotations

from loom.errors import IOErrorBase


class LoomIOError(IOErrorBase):
    """Base error for I/O layer failures."""


class UnsupportedURIError(LoomIOError):
    """Error raised when an input URI or path is unsupported."""


__all__ = ["LoomIOError", "UnsupportedURIError"]

