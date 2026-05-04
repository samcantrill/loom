"""Record model definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, cast
from types import MappingProxyType

from loom.ids import RecordID, ResourceKey
from loom.refs import ResourceRef
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .errors import RecordError


@dataclass(frozen=True, slots=True)
class Record:
    """Domain-neutral logical record."""

    record_id: RecordID
    resources: Mapping[ResourceKey, ResourceRef] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
    annotations: Mapping[str, PlainData] = field(default_factory=dict)
    provenance: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id:
            raise RecordError("record_id must be a non-empty string")

        normalized_resources: dict[str, ResourceRef] = {}
        if not isinstance(self.resources, Mapping):
            raise RecordError("resources must be a mapping")
        for key, value in dict(self.resources).items():
            if not isinstance(key, str) or not key:
                raise RecordError("resource keys must be non-empty strings")
            if not isinstance(value, ResourceRef):
                raise RecordError("resources values must be ResourceRef")
            normalized_resources[key] = value

        object.__setattr__(self, "resources", MappingProxyType(normalized_resources))
        object.__setattr__(self, "metadata", freeze_plain_data(self.metadata, path="metadata"))
        object.__setattr__(self, "annotations", freeze_plain_data(self.annotations, path="annotations"))
        object.__setattr__(self, "provenance", freeze_plain_data(self.provenance, path="provenance"))

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "resources": {name: value.to_dict() for name, value in self.resources.items()},
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
            "annotations": thaw_plain_data(self.annotations, path="annotations"),
            "provenance": thaw_plain_data(self.provenance, path="provenance"),
        }

    def has_resource(self, key: str) -> bool:
        return key in self.resources

    def get_resource(self, key: str, default: ResourceRef | None = None) -> ResourceRef | None:
        return self.resources.get(key, default)

    def require_resource(self, key: str) -> ResourceRef:
        if key not in self.resources:
            raise KeyError(f"Missing resource key: {key!r}")
        return self.resources[key]

    @classmethod
    def from_dict(cls, data: object) -> "Record":
        if not isinstance(data, dict):
            raise RecordError("Record.from_dict expects mapping")
        allowed = {"record_id", "resources", "metadata", "annotations", "provenance"}
        unknown = set(data) - allowed
        if unknown:
            raise RecordError(f"Record.from_dict unknown fields: {', '.join(sorted(unknown))}")
        record_id = data.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RecordError("Record.from_dict missing or invalid record_id")

        raw_resources = data.get("resources", {})
        if not isinstance(raw_resources, Mapping):
            raise RecordError("Record.from_dict resources must be a mapping")
        resources: dict[str, ResourceRef] = {}
        for key, value in raw_resources.items():
            if not isinstance(key, str) or not key:
                raise RecordError("resource keys must be non-empty strings")
            if not isinstance(value, Mapping):
                raise RecordError(f"Record.from_dict resource value for {key!r} must be a mapping")
            resources[str(key)] = ResourceRef.from_dict(value)

        return cls(
            record_id=record_id,
            resources=resources,
            metadata=cast(Mapping[str, PlainData], data.get("metadata", {})),
            annotations=cast(Mapping[str, PlainData], data.get("annotations", {})),
            provenance=cast(Mapping[str, PlainData], data.get("provenance", {})),
        )
