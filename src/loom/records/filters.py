"""Generic record filters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from loom.serialization import PlainData, ensure_plain_data

from .base import Record


class RecordFilter(Protocol):
    """Structural filter protocol for records."""

    def __call__(self, record: Record) -> bool:
        ...


class HasResource:
    """Filter for the presence of a resource key."""

    key: str

    def __init__(self, key: str) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("HasResource requires non-empty key")
        self.key = key

    def __call__(self, record: Record) -> bool:
        return self.key in record.resources


class MetadataEquals:
    """Filter for strict metadata equality."""

    key: str
    value: PlainData

    def __init__(self, key: str, value: PlainData) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("MetadataEquals requires non-empty key")
        self.key = key
        self.value = ensure_plain_data(value, path=f"value[{key!r}]")

    def __call__(self, record: Record) -> bool:
        return record.metadata.get(self.key) == self.value


class MetadataIn:
    """Filter where metadata value appears in a provided sequence."""

    key: str
    values: tuple[PlainData, ...]

    def __init__(self, key: str, values: Iterable[PlainData]) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("MetadataIn requires non-empty key")
        self.key = key
        self.values = tuple(ensure_plain_data(value, path=f"values[{index}]") for index, value in enumerate(values))

    def __call__(self, record: Record) -> bool:
        return record.metadata.get(self.key) in self.values
