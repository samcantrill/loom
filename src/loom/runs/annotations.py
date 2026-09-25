"""Revision-safe annotation requests and append-only native notes."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import json
from dataclasses import dataclass, field
from typing import cast

from loom.serialization import PlainData, stable_json_bytes, thaw_plain_data
from .context import RUN_CONTEXT_LIMITS, RunAnnotations, SubmissionContext, _text


def mutation_request(
    run_uri: str, mutation_id: str, operation: str, change: Mapping[str, object]
) -> dict[str, PlainData]:
    if not isinstance(run_uri, str) or not run_uri or len(run_uri.encode()) > 4096:
        raise ValueError("invalid run_uri")
    if (
        not isinstance(mutation_id, str)
        or not mutation_id
        or len(mutation_id.encode()) > RUN_CONTEXT_LIMITS["mutation_id_bytes"]
    ):
        raise ValueError("mutation_id must be nonempty text of at most 128 UTF-8 bytes")
    if operation == "patch_run_annotations":
        value: dict[str, PlainData] = AnnotationPatch.from_dict(change).to_dict()
    elif operation == "append_run_note" and set(change) == {"text"}:
        # Native identity and time cannot be assigned by the caller.
        value = {
            "text": _text(change["text"], "note text", RUN_CONTEXT_LIMITS["text_bytes"])
        }
    else:
        raise ValueError("invalid annotation operation or note fields")
    return {
        "run_uri": run_uri,
        "mutation_id": mutation_id,
        "operation": operation,
        "change": value,
    }


def page_notes(
    run_uri: str, notes: Sequence[RunNote], limit: int, cursor: str | None
) -> RunNotePage:
    if type(limit) is not int or not 1 <= limit <= RUN_CONTEXT_LIMITS["note_page_size"]:
        raise ValueError("note limit must be between 1 and 50")
    after = ("", "")
    if cursor is not None:
        try:
            value = json.loads(cursor)
            if (
                not isinstance(value, list)
                or len(value) != 3
                or value[0] != run_uri
                or any(not isinstance(item, str) for item in value)
            ):
                raise ValueError("invalid note cursor")
            after = (value[1], value[2])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid note cursor") from exc
    ordered = sorted(
        (note for note in notes if (note.created_at or "", note.note_id) > after),
        key=lambda note: (note.created_at or "", note.note_id),
    )
    selected: list[RunNote] = []
    encoded_bytes = 0
    for note in ordered[:limit]:
        size = len(
            json.dumps(
                note.to_dict(), ensure_ascii=True, separators=(",", ":")
            ).encode()
        )
        if selected and encoded_bytes + size > RUN_CONTEXT_LIMITS["note_page_bytes"]:
            break
        selected.append(note)
        encoded_bytes += size
    continuation = None
    if len(ordered) > len(selected):
        last = selected[-1]
        continuation = json.dumps(
            [run_uri, last.created_at or "", last.note_id], separators=(",", ":")
        )
    return RunNotePage(tuple(selected), continuation)


class AnnotationConflictError(ValueError):
    """A stale revision or reused mutation ID; rebase only as a new request."""

    def __init__(self, message: str, current_revision: int | None = None) -> None:
        super().__init__(message)
        self.current_revision = current_revision

    def __reduce__(self):
        return (type(self), (str(self), self.current_revision))


class AnnotationValidationError(ValueError):
    """The owner rejected an annotation before committing any effect."""


@dataclass(frozen=True, slots=True)
class AnnotationPatch:
    """Top-level key patch; absent description differs from explicit null.

    Set ``change_description`` to replace/clear the description. Metadata nulls
    are retained values; removals explicitly name keys. Nested values replace
    one top-level value. All resulting annotations obey the context limits.
    """

    expected_revision: int
    set_tags: Mapping[str, str] = field(default_factory=dict)
    remove_tags: tuple[str, ...] = ()
    set_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    remove_metadata: tuple[str, ...] = ()
    change_description: bool = False
    description: str | None = None

    def __post_init__(self) -> None:
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("expected_revision must be a nonnegative integer")
        if type(self.change_description) is not bool:
            raise ValueError("change_description must be boolean")
        if not self.change_description and self.description is not None:
            raise ValueError("description requires change_description")
        value = SubmissionContext(self.description, self.set_tags, self.set_metadata)
        object.__setattr__(self, "set_tags", value.tags)
        object.__setattr__(self, "set_metadata", value.metadata)
        for name, sets in (
            ("remove_tags", self.set_tags),
            ("remove_metadata", self.set_metadata),
        ):
            keys = getattr(self, name)
            if not isinstance(keys, (tuple, list)):
                raise ValueError(f"{name} must be a sequence of keys")
            for key in keys:
                _text(key, "removed key", RUN_CONTEXT_LIMITS["key_bytes"])
            if len(set(keys)) != len(keys) or set(keys) & sets.keys():
                raise ValueError("duplicate removal or set/remove overlap")
            object.__setattr__(self, name, tuple(keys))
        if len(stable_json_bytes(self.to_dict())) > RUN_CONTEXT_LIMITS["payload_bytes"]:
            raise ValueError("annotation patch exceeds 48 KiB")

    def to_dict(self) -> dict[str, PlainData]:
        value: dict[str, PlainData] = {
            "expected_revision": self.expected_revision,
            "set_tags": thaw_plain_data(self.set_tags),
            "remove_tags": list(self.remove_tags),
            "set_metadata": thaw_plain_data(self.set_metadata),
            "remove_metadata": list(self.remove_metadata),
        }
        if self.change_description:
            value["description"] = self.description
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> AnnotationPatch:
        if (
            not isinstance(data, Mapping)
            or "expected_revision" not in data
            or set(data)
            - {
                "expected_revision",
                "set_tags",
                "remove_tags",
                "set_metadata",
                "remove_metadata",
                "description",
            }
        ):
            raise ValueError("invalid annotation patch")
        return cls(
            cast(int, data["expected_revision"]),
            cast(Mapping[str, str], data.get("set_tags", {})),
            cast(tuple[str, ...], data.get("remove_tags", ())),
            cast(Mapping[str, PlainData], data.get("set_metadata", {})),
            cast(tuple[str, ...], data.get("remove_metadata", ())),
            "description" in data,
            cast(str | None, data.get("description")),
        )

    def apply(self, current: RunAnnotations) -> RunAnnotations:
        if current.revision != self.expected_revision:
            raise AnnotationConflictError(
                "annotation revision conflict", current.revision
            )
        tags = {
            key: value
            for key, value in current.tags.items()
            if key not in self.remove_tags
        }
        tags.update(self.set_tags)
        metadata = {
            key: value
            for key, value in current.metadata.items()
            if key not in self.remove_metadata
        }
        metadata.update(self.set_metadata)
        return RunAnnotations(
            current.run_uri,
            current.revision + 1,
            self.description if self.change_description else current.description,
            tags,
            metadata,
            current.initializer_operation_id,
            current.initializer_coordinator_id,
        )


@dataclass(frozen=True, slots=True)
class RunNote:
    """An immutable observation with native UTC time and authenticated identity.

    Legacy runtime notes have unknown author/time and ``source=legacy_runtime``.
    Correction means appending another note, never replacing an existing entry.
    """

    run_uri: str
    note_id: str
    text: str
    author: str | None
    created_at: str | None
    source: str = "native"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.run_uri, str)
            or not self.run_uri
            or not isinstance(self.note_id, str)
            or not self.note_id
            or self.source not in {"native", "legacy_runtime"}
        ):
            raise ValueError("invalid note identity")
        _text(self.text, "note text", RUN_CONTEXT_LIMITS["text_bytes"])
        for value in (self.author, self.created_at):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("invalid note attribution")
        if self.source == "native" and (not self.author or not self.created_at):
            raise ValueError("native notes require author and time")
        if self.source == "legacy_runtime" and (
            self.author is not None or self.created_at is not None
        ):
            raise ValueError("legacy attribution must remain unknown")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "note_id": self.note_id,
            "text": self.text,
            "author": self.author,
            "created_at": self.created_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunNote:
        if set(data) != {
            "run_uri",
            "note_id",
            "text",
            "author",
            "created_at",
            "source",
        }:
            raise ValueError("invalid run note")
        return cls(
            cast(str, data["run_uri"]),
            cast(str, data["note_id"]),
            cast(str, data["text"]),
            cast(str | None, data["author"]),
            cast(str | None, data["created_at"]),
            cast(str, data["source"]),
        )


@dataclass(frozen=True, slots=True)
class RunNotePage:
    """Bounded notes in native time/note-ID order; cursor continues a live view."""

    notes: tuple[RunNote, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(note, RunNote) for note in self.notes):
            raise ValueError("invalid note page entries")
        object.__setattr__(self, "notes", tuple(self.notes))
        if self.next_cursor is not None and (
            not isinstance(self.next_cursor, str) or not self.next_cursor
        ):
            raise ValueError("invalid note page cursor")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "notes": [note.to_dict() for note in self.notes],
            "next_cursor": self.next_cursor,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> RunNotePage:
        if set(data) != {"notes", "next_cursor"}:
            raise ValueError("invalid note page")
        return cls(
            tuple(
                RunNote.from_dict(item)
                for item in cast(list[Mapping[str, object]], data["notes"])
            ),
            cast(str | None, data["next_cursor"]),
        )
