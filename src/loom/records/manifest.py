"""Manifest containers."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Protocol, cast

from loom.ids import RecordID
from loom.serialization import PlainData, check_supported_schema, ensure_plain_data

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
        object.__setattr__(self, "metadata", ensure_plain_data(dict(self.metadata), path="metadata"))

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
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "InMemoryManifest":
        if not isinstance(data, dict):
            raise ManifestError("InMemoryManifest.from_dict expects mapping")

        unknown = set(data) - {"schema_version", "records", "metadata"}
        if unknown:
            raise ManifestError(f"InMemoryManifest.from_dict unknown fields: {', '.join(sorted(unknown))}")

        check_supported_schema(data, supported=(1,))
        records = data.get("records")
        if not isinstance(records, list):
            raise ManifestError("InMemoryManifest.from_dict records must be a list")

        deserialized = [Record.from_dict(item) for item in records]
        return cls(
            records=tuple(deserialized),
            metadata=cast(dict[str, PlainData], ensure_plain_data(data.get("metadata", {}), path="metadata")),
        )

    def _records(self) -> tuple[Record, ...]:
        return cast(tuple[Record, ...], self.records)
