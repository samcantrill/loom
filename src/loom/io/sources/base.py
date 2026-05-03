"""Source protocol for byte/text resource access."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Mapping, TextIO, runtime_checkable, Protocol

from loom.serialization import PlainData


@runtime_checkable
class DataSource(Protocol):
    """Protocol for source backends."""

    name: str

    def supports(self, uri: str | Path) -> bool: ...

    def resolve(self, uri: str | Path) -> Path: ...

    def open(self, uri: str | Path, mode: str = "rb", *, encoding: str = "utf-8") -> BinaryIO | TextIO: ...

    def exists(self, uri: str | Path) -> bool: ...

    def stat(self, uri: str | Path) -> Mapping[str, PlainData]: ...

    def glob(self, pattern: str | Path) -> tuple[str, ...]: ...


__all__ = ["DataSource"]
