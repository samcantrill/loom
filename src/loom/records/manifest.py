"""Manifest containers."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Protocol, cast

from loom.ids import RecordID
from loom.serialization import (
    PlainData,
    SchemaVersionError,
    freeze_plain_data,
    load_versioned_document,
    thaw_plain_data,
)

from .base import Record
from .errors import DuplicateRecordError, ManifestError, RecordNotFoundError


class Manifest(Protocol):
    """Structural protocol for manifest containers."""

    def __iter__(self) -> Iterator[Record]:
        ...

    def __len__(self) -> int:
        ...

    def get(self, record_id: RecordID) -> Record | None:
        ...

    def require(self, record_id: RecordID) -> Record:
        ...

    def to_dict(self) -> dict[str, object]:
        ...


_MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class InMemoryManifest:
    """Ordered in-memory manifest."""

    records: Iterable[Record]
    metadata: dict[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = tuple(self.records)
        seen: set[str] = set()
        for record in normalized:
            if not isinstance(record, Record):
                raise ManifestError("InMemoryManifest records must be Record instances")
            if record.record_id in seen:
                raise DuplicateRecordError(f"Duplicate record_id: {record.record_id!r}")
            seen.add(record.record_id)
        object.__setattr__(self, "records", normalized)
        object.__setattr__(self, "metadata", freeze_plain_data(self.metadata, path="metadata"))

    def __iter__(self) -> Iterator[Record]:
        return iter(self._records())

    def __len__(self) -> int:
        return len(self._records())

    def get(self, record_id: RecordID) -> Record | None:
        for record in self._records():
            if record.record_id == record_id:
                return record
        return None

    def require(self, record_id: RecordID) -> Record:
        result = self.get(record_id)
        if result is None:
            raise RecordNotFoundError(f"Record not found: {record_id!r}")
        return result

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "records": [record.to_dict() for record in self._records()],
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "InMemoryManifest":
        try:
            payload = load_versioned_document(
                data,
                current_version=_MANIFEST_SCHEMA_VERSION,
                required={"records"},
                optional={"metadata"},
            )
        except SchemaVersionError as exc:
            raise ManifestError(f"InMemoryManifest.from_dict: {exc}") from exc

        records = payload.get("records")
        if not isinstance(records, list):
            raise ManifestError("InMemoryManifest.from_dict records must be a list")

        deserialized = [Record.from_dict(item) for item in records]
        return cls(
            records=tuple(deserialized),
            metadata=cast(dict[str, PlainData], payload.get("metadata", {})),
        )

    def _records(self) -> tuple[Record, ...]:
        return cast(tuple[Record, ...], self.records)
