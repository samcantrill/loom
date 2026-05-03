"""Codec protocol for in-memory conversions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from loom.serialization import PlainData


@runtime_checkable
class Codec(Protocol):
    """Protocol for codec implementations."""

    key: str

    def encode(self, obj: object, *, metadata: Mapping[str, PlainData] | None = None) -> bytes: ...

    def decode(self, data: bytes, *, metadata: Mapping[str, PlainData] | None = None) -> object: ...


__all__ = ["Codec"]
