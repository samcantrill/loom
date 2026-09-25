"""Inert, bounded caller context, separate from native execution evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from loom.serialization import (
    PlainData,
    freeze_plain_data,
    stable_json_bytes,
    thaw_plain_data,
)
from loom.serialization.errors import PlainDataError


RUN_CONTEXT_CAPABILITY = "run-context-v1"
RUN_CONTEXT_LIMITS = {
    "text_bytes": 16 * 1024,
    "payload_bytes": 48 * 1024,
    "tag_keys": 128,
    "key_bytes": 128,
    "tag_value_bytes": 1024,
    "mutation_id_bytes": 128,
    "note_page_size": 50,
    "note_page_bytes": 768 * 1024,
    "request_bytes": 64 * 1024,
}


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
        raise ValueError(f"{name} must be text of at most {limit} UTF-8 bytes")
    return value


@dataclass(frozen=True, slots=True)
class SubmissionContext:
    """Caller description, string labels and deeply immutable finite JSON metadata.

    Values never select execution or replace authenticated/native provenance.
    Text and the complete JSON payload obey ``RUN_CONTEXT_LIMITS``.
    """

    description: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.description is not None:
            _text(self.description, "description", RUN_CONTEXT_LIMITS["text_bytes"])
        if (
            not isinstance(self.tags, Mapping)
            or len(self.tags) > RUN_CONTEXT_LIMITS["tag_keys"]
        ):
            raise ValueError("context tags must be a mapping with at most 128 keys")
        for key, value in self.tags.items():
            _text(key, "tag key", RUN_CONTEXT_LIMITS["key_bytes"])
            _text(value, "tag value", RUN_CONTEXT_LIMITS["tag_value_bytes"])
        if not isinstance(self.metadata, Mapping):
            raise ValueError("context metadata must be a mapping")
        for key in self.metadata:
            _text(key, "metadata key", RUN_CONTEXT_LIMITS["key_bytes"])
        try:
            object.__setattr__(self, "tags", freeze_plain_data(self.tags))
            object.__setattr__(self, "metadata", freeze_plain_data(self.metadata))
            encoded = stable_json_bytes(self.to_dict())
        except (PlainDataError, RecursionError) as exc:
            raise ValueError("context must contain finite JSON data") from exc
        if len(encoded) > RUN_CONTEXT_LIMITS["payload_bytes"]:
            raise ValueError("context payload exceeds 48 KiB")

    @property
    def empty(self) -> bool:
        """Whether omission preserves exactly the same submission intent."""
        return self.description is None and not self.tags and not self.metadata

    def to_dict(self) -> dict[str, PlainData]:
        """Return detached JSON data, preserving numeric and null values."""
        return {
            "description": self.description,
            "tags": thaw_plain_data(self.tags),
            "metadata": thaw_plain_data(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> SubmissionContext:
        if not isinstance(data, Mapping) or set(data) - {
            "description",
            "tags",
            "metadata",
        }:
            raise ValueError("submission context is invalid")
        return cls(
            cast(str | None, data.get("description")),
            cast(Mapping[str, str], data.get("tags", {})),
            cast(Mapping[str, PlainData], data.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class RunAnnotations:
    """Current authority annotations and the native initializing submission link.

    ``revision`` is independent of lifecycle revisions. A null initializer denotes
    legacy evidence whose original submission is unknown.
    """

    run_uri: str
    revision: int
    description: str | None
    tags: Mapping[str, str]
    metadata: Mapping[str, PlainData]
    initializer_operation_id: str | None = None
    initializer_coordinator_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise ValueError("annotations require run_uri")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("annotation revision must be a nonnegative integer")
        value = SubmissionContext(self.description, self.tags, self.metadata)
        object.__setattr__(self, "tags", value.tags)
        object.__setattr__(self, "metadata", value.metadata)
        for item in (self.initializer_operation_id, self.initializer_coordinator_id):
            if item is not None and (not isinstance(item, str) or not item):
                raise ValueError("annotation initializer is invalid")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "revision": self.revision,
            "description": self.description,
            "tags": thaw_plain_data(self.tags),
            "metadata": thaw_plain_data(self.metadata),
            "initializer_operation_id": self.initializer_operation_id,
            "initializer_coordinator_id": self.initializer_coordinator_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunAnnotations:
        if set(data) != {
            "run_uri",
            "revision",
            "description",
            "tags",
            "metadata",
            "initializer_operation_id",
            "initializer_coordinator_id",
        }:
            raise ValueError("run annotations are invalid")
        return cls(
            cast(str, data["run_uri"]),
            cast(int, data["revision"]),
            cast(str | None, data["description"]),
            cast(Mapping[str, str], data["tags"]),
            cast(Mapping[str, PlainData], data["metadata"]),
            cast(str | None, data["initializer_operation_id"]),
            cast(str | None, data["initializer_coordinator_id"]),
        )


@dataclass(frozen=True, slots=True)
class RunContext:
    """Bounded context overview with existing native inspection and partial evidence.

    Submission links contain native operation IDs for explicit follow-up. At most
    20 links are embedded; ``submission_count`` reports the retained total.
    ``initializer_submission`` preserves original caller context, not later labels.
    Inspection contains metadata and output references, never artifact payloads.
    """

    run_uri: str
    annotations: RunAnnotations | None
    initializer_submission: Mapping[str, PlainData] | None
    submissions: tuple[Mapping[str, PlainData], ...]
    submission_count: int
    inspection: Mapping[str, PlainData] | None
    unavailable: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.run_uri, str) or not self.run_uri:
            raise ValueError("context requires run_uri")
        if self.annotations is not None and (
            not isinstance(self.annotations, RunAnnotations)
            or self.annotations.run_uri != self.run_uri
        ):
            raise ValueError("context annotations mismatch")
        if (
            type(self.submission_count) is not int
            or self.submission_count < len(self.submissions)
            or len(self.submissions) > 20
        ):
            raise ValueError("context submission count is invalid")
        for name in ("initializer_submission", "inspection"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Mapping):
                raise ValueError(f"context {name} is invalid")
            object.__setattr__(self, name, freeze_plain_data(value))
        if any(not isinstance(item, Mapping) for item in self.submissions):
            raise ValueError("context submission links are invalid")
        object.__setattr__(
            self,
            "submissions",
            tuple(freeze_plain_data(item) for item in self.submissions),
        )
        if any(not isinstance(item, str) for item in self.unavailable):
            raise ValueError("context unavailable evidence is invalid")
        object.__setattr__(self, "unavailable", tuple(self.unavailable))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "annotations": None
            if self.annotations is None
            else self.annotations.to_dict(),
            "initializer_submission": thaw_plain_data(self.initializer_submission),
            "submissions": thaw_plain_data(self.submissions),
            "submission_count": self.submission_count,
            "inspection": thaw_plain_data(self.inspection),
            "unavailable": list(self.unavailable),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunContext:
        if set(data) != {
            "run_uri",
            "annotations",
            "initializer_submission",
            "submissions",
            "submission_count",
            "inspection",
            "unavailable",
        }:
            raise ValueError("run context is invalid")
        return cls(
            cast(str, data["run_uri"]),
            None
            if data["annotations"] is None
            else RunAnnotations.from_dict(
                cast(Mapping[str, object], data["annotations"])
            ),
            cast(Mapping[str, PlainData] | None, data["initializer_submission"]),
            tuple(cast(list[Mapping[str, PlainData]], data["submissions"])),
            cast(int, data["submission_count"]),
            cast(Mapping[str, PlainData] | None, data["inspection"]),
            tuple(cast(list[str], data["unavailable"])),
        )
