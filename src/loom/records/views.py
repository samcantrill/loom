"""Manifest views."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from loom.ids import RecordID
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .base import Record
from .errors import RecordNotFoundError
from .filters import RecordFilter
from .manifest import InMemoryManifest, Manifest


@dataclass(frozen=True, slots=True)
class ManifestView:
    """Lazy filtered projection over a manifest."""

    source: Manifest
    filters: tuple[RecordFilter, ...] = ()
    metadata: dict[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "filters", tuple(self.filters))
        object.__setattr__(self, "metadata", freeze_plain_data(self.metadata, path="metadata"))

    def __iter__(self) -> Iterator[Record]:
        for record in self.source:
            if all(predicate(record) for predicate in self.filters):
                yield record

    def filter(self, predicate: RecordFilter) -> "ManifestView":
        return ManifestView(
            source=self.source,
            filters=self.filters + (predicate,),
            metadata=thaw_plain_data(self.metadata, path="metadata"),
        )

    def get(self, record_id: RecordID) -> Record | None:
        for record in self:
            if record.record_id == record_id:
                return record
        return None

    def require(self, record_id: RecordID) -> Record:
        result = self.get(record_id)
        if result is None:
            raise RecordNotFoundError(f"Record not found in view: {record_id!r}")
        return result

    def materialize(self) -> InMemoryManifest:
        return InMemoryManifest(records=tuple(self), metadata=thaw_plain_data(self.metadata, path="metadata"))

    def to_dict(self) -> dict[str, object]:
        return self.materialize().to_dict()
