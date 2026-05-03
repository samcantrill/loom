"""Codec-specific errors."""

from __future__ import annotations

from loom.io.errors import LoomIOError


class CodecError(LoomIOError):
    """Base error for codec failures."""


class CodecRegistrationError(CodecError):
    """Error raised for invalid or duplicate codec registration."""


class UnknownCodecError(CodecError):
    """Error raised for lookup of an unregistered codec key."""


class CodecEncodeError(CodecError):
    """Error raised when a codec fails to encode."""


class CodecDecodeError(CodecError):
    """Error raised when a codec fails to decode."""


__all__ = [
    "CodecError",
    "CodecRegistrationError",
    "UnknownCodecError",
    "CodecEncodeError",
    "CodecDecodeError",
]

