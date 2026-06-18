"""Bounded cleanup selector records and matching helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import cast

from loom.pipeline.cleanup.errors import CleanupSelectorError
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp, utc_now

CLEANUP_SELECTOR_SCHEMA_VERSION = 1


class CleanupSelectionStatus(StrEnum):
    """Selector match outcomes."""

    SELECTED = "selected"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class CleanupSelector:
    """Bounded cleanup selector over authoritative cleanup candidate facts."""

    schema_version: int = CLEANUP_SELECTOR_SCHEMA_VERSION
    older_than_seconds: int | None = None
    recorded_before: str | None = None
    recorded_after: str | None = None
    candidate_kinds: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    retention_modes: tuple[str, ...] = ()
    stage_names: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    artifact_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    metadata_equals: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "older_than_seconds",
            _optional_positive_int(self.older_than_seconds, "older_than_seconds"),
        )
        object.__setattr__(
            self,
            "recorded_before",
            _optional_timestamp(self.recorded_before, "recorded_before"),
        )
        object.__setattr__(
            self,
            "recorded_after",
            _optional_timestamp(self.recorded_after, "recorded_after"),
        )
        object.__setattr__(
            self,
            "candidate_kinds",
            _string_tuple(self.candidate_kinds, "candidate_kinds"),
        )
        object.__setattr__(
            self, "reason_codes", _string_tuple(self.reason_codes, "reason_codes")
        )
        object.__setattr__(
            self,
            "retention_modes",
            _string_tuple(self.retention_modes, "retention_modes"),
        )
        object.__setattr__(
            self, "stage_names", _string_tuple(self.stage_names, "stage_names")
        )
        object.__setattr__(
            self, "artifact_ids", _string_tuple(self.artifact_ids, "artifact_ids")
        )
        object.__setattr__(
            self,
            "artifact_types",
            _string_tuple(self.artifact_types, "artifact_types"),
        )
        object.__setattr__(self, "tags", _string_tuple(self.tags, "tags"))
        object.__setattr__(
            self,
            "metadata_equals",
            _plain_mapping(self.metadata_equals, "metadata_equals"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "older_than_seconds": self.older_than_seconds,
            "recorded_before": self.recorded_before,
            "recorded_after": self.recorded_after,
            "candidate_kinds": list(self.candidate_kinds),
            "reason_codes": list(self.reason_codes),
            "retention_modes": list(self.retention_modes),
            "stage_names": list(self.stage_names),
            "artifact_ids": list(self.artifact_ids),
            "artifact_types": list(self.artifact_types),
            "tags": list(self.tags),
            "metadata_equals": thaw_plain_data(
                self.metadata_equals, path="metadata_equals"
            ),
        }

    @classmethod
    def from_dict(cls, data: object) -> "CleanupSelector":
        mapping = _mapping(data, "CleanupSelector")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "older_than_seconds",
                "recorded_before",
                "recorded_after",
                "candidate_kinds",
                "reason_codes",
                "retention_modes",
                "stage_names",
                "artifact_ids",
                "artifact_types",
                "tags",
                "metadata_equals",
            },
            "CleanupSelector",
        )
        return cls(
            schema_version=_require_schema_version(
                mapping.get("schema_version", CLEANUP_SELECTOR_SCHEMA_VERSION),
                "schema_version",
            ),
            older_than_seconds=_optional_positive_int(
                mapping.get("older_than_seconds"), "older_than_seconds"
            ),
            recorded_before=_optional_timestamp(
                mapping.get("recorded_before"), "recorded_before"
            ),
            recorded_after=_optional_timestamp(
                mapping.get("recorded_after"), "recorded_after"
            ),
            candidate_kinds=_string_tuple(
                _sequence(mapping.get("candidate_kinds", ())), "candidate_kinds"
            ),
            reason_codes=_string_tuple(
                _sequence(mapping.get("reason_codes", ())), "reason_codes"
            ),
            retention_modes=_string_tuple(
                _sequence(mapping.get("retention_modes", ())), "retention_modes"
            ),
            stage_names=_string_tuple(
                _sequence(mapping.get("stage_names", ())), "stage_names"
            ),
            artifact_ids=_string_tuple(
                _sequence(mapping.get("artifact_ids", ())), "artifact_ids"
            ),
            artifact_types=_string_tuple(
                _sequence(mapping.get("artifact_types", ())), "artifact_types"
            ),
            tags=_string_tuple(_sequence(mapping.get("tags", ())), "tags"),
            metadata_equals=_plain_mapping(
                mapping.get("metadata_equals", {}), "metadata_equals"
            ),
        )


@dataclass(frozen=True, slots=True)
class CleanupSelectorExplanation:
    """Explanation for one selector predicate."""

    field: str
    matched: bool
    reason_code: str
    expected: PlainData = None
    actual: PlainData = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "field", _non_empty_string(self.field, "field"))
        if not isinstance(self.matched, bool):
            raise CleanupSelectorError("matched must be a bool")
        object.__setattr__(
            self, "reason_code", _non_empty_string(self.reason_code, "reason_code")
        )
        object.__setattr__(
            self,
            "expected",
            freeze_plain_data(self.expected, path="expected"),
        )
        object.__setattr__(
            self,
            "actual",
            freeze_plain_data(self.actual, path="actual"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "field": self.field,
            "matched": self.matched,
            "reason_code": self.reason_code,
            "expected": thaw_plain_data(self.expected, path="expected"),
            "actual": thaw_plain_data(self.actual, path="actual"),
        }


@dataclass(frozen=True, slots=True)
class CleanupSelection:
    """Selector decision for one cleanup candidate."""

    candidate_id: str
    status: CleanupSelectionStatus
    explanations: tuple[CleanupSelectorExplanation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _non_empty_string(self.candidate_id, "candidate_id")
        )
        object.__setattr__(self, "status", _selection_status(self.status))
        explanations = tuple(self.explanations)
        if any(
            not isinstance(explanation, CleanupSelectorExplanation)
            for explanation in explanations
        ):
            raise CleanupSelectorError(
                "explanations must contain CleanupSelectorExplanation values"
            )
        object.__setattr__(self, "explanations", explanations)

    @property
    def selected(self) -> bool:
        return self.status is CleanupSelectionStatus.SELECTED

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "selected": self.selected,
            "explanations": [
                explanation.to_dict() for explanation in self.explanations
            ],
        }


def match_cleanup_candidate(
    candidate: object,
    selector: CleanupSelector | Mapping[str, PlainData] | None = None,
    *,
    metadata: Mapping[str, PlainData] | None = None,
    now: datetime | None = None,
) -> CleanupSelection:
    """Return whether a candidate matches a bounded cleanup selector."""

    normalized_selector = (
        CleanupSelector()
        if selector is None
        else selector
        if isinstance(selector, CleanupSelector)
        else CleanupSelector.from_dict(selector)
    )
    candidate_data = _candidate_mapping(candidate)
    candidate_id = _non_empty_string(
        candidate_data.get("candidate_id"), "candidate_id"
    )
    merged = _merge_metadata(candidate_data, metadata)
    explanations = _evaluate_selector(
        candidate_data, merged, normalized_selector, now=now
    )
    status = (
        CleanupSelectionStatus.SELECTED
        if all(explanation.matched for explanation in explanations)
        else CleanupSelectionStatus.SKIPPED
    )
    return CleanupSelection(
        candidate_id=candidate_id,
        status=status,
        explanations=tuple(explanations),
    )


def _evaluate_selector(
    candidate: Mapping[str, PlainData],
    metadata: Mapping[str, PlainData],
    selector: CleanupSelector,
    *,
    now: datetime | None,
) -> list[CleanupSelectorExplanation]:
    explanations: list[CleanupSelectorExplanation] = []
    if selector.older_than_seconds is not None:
        recorded_at = _candidate_timestamp(candidate)
        cutoff = (now or utc_now()).timestamp() - selector.older_than_seconds
        matched = recorded_at.timestamp() <= cutoff
        explanations.append(
            CleanupSelectorExplanation(
                field="older_than_seconds",
                matched=matched,
                reason_code="matched_age" if matched else "candidate_too_new",
                expected=selector.older_than_seconds,
                actual=candidate.get("recorded_at"),
            )
        )
    if selector.recorded_before is not None:
        recorded_at = _candidate_timestamp(candidate)
        before = parse_timestamp(selector.recorded_before)
        matched = recorded_at < before
        explanations.append(
            CleanupSelectorExplanation(
                field="recorded_before",
                matched=matched,
                reason_code="matched_recorded_before"
                if matched
                else "recorded_at_not_before",
                expected=selector.recorded_before,
                actual=candidate.get("recorded_at"),
            )
        )
    if selector.recorded_after is not None:
        recorded_at = _candidate_timestamp(candidate)
        after = parse_timestamp(selector.recorded_after)
        matched = recorded_at > after
        explanations.append(
            CleanupSelectorExplanation(
                field="recorded_after",
                matched=matched,
                reason_code="matched_recorded_after"
                if matched
                else "recorded_at_not_after",
                expected=selector.recorded_after,
                actual=candidate.get("recorded_at"),
            )
        )
    _append_membership(
        explanations,
        field="candidate_kinds",
        expected=selector.candidate_kinds,
        actual=_string_value(candidate.get("kind")),
    )
    reason = candidate.get("reason")
    reason_code = (
        _string_value(reason.get("code"))
        if isinstance(reason, Mapping)
        else _string_value(metadata.get("reason_code"))
    )
    _append_membership(
        explanations,
        field="reason_codes",
        expected=selector.reason_codes,
        actual=reason_code,
    )
    for selector_field, expected in (
        ("retention_modes", selector.retention_modes),
        ("stage_names", selector.stage_names),
        ("artifact_ids", selector.artifact_ids),
        ("artifact_types", selector.artifact_types),
        ("tags", selector.tags),
    ):
        actual = metadata.get(_metadata_key_for_selector_field(selector_field))
        _append_membership(
            explanations,
            field=selector_field,
            expected=expected,
            actual=actual,
        )
    for key, expected_value in selector.metadata_equals.items():
        actual_value = metadata.get(key)
        matched = actual_value == expected_value
        explanations.append(
            CleanupSelectorExplanation(
                field=f"metadata.{key}",
                matched=matched,
                reason_code="matched_metadata" if matched else "metadata_mismatch",
                expected=expected_value,
                actual=actual_value,
            )
        )
    if not explanations:
        explanations.append(
            CleanupSelectorExplanation(
                field="all",
                matched=True,
                reason_code="no_selector_constraints",
            )
        )
    return explanations


def _append_membership(
    explanations: list[CleanupSelectorExplanation],
    *,
    field: str,
    expected: tuple[str, ...],
    actual: PlainData,
) -> None:
    if not expected:
        return
    if isinstance(actual, Sequence) and not isinstance(actual, str):
        actual_values = {str(item) for item in actual if isinstance(item, str)}
        matched = bool(actual_values.intersection(expected))
    else:
        matched = isinstance(actual, str) and actual in expected
    explanations.append(
        CleanupSelectorExplanation(
            field=field,
            matched=matched,
            reason_code=f"matched_{field}" if matched else f"{field}_mismatch",
            expected=list(expected),
            actual=actual,
        )
    )


def _metadata_key_for_selector_field(field: str) -> str:
    return {
        "retention_modes": "retention_mode",
        "stage_names": "stage_name",
        "artifact_ids": "artifact_id",
        "artifact_types": "artifact_type",
        "tags": "tags",
    }[field]


def _candidate_mapping(candidate: object) -> Mapping[str, PlainData]:
    if isinstance(candidate, Mapping):
        return _plain_mapping(candidate, "candidate")
    to_dict = getattr(candidate, "to_dict", None)
    if callable(to_dict):
        return _plain_mapping(to_dict(), "candidate")
    raise CleanupSelectorError("candidate must be a mapping or expose to_dict()")


def _merge_metadata(
    candidate: Mapping[str, PlainData],
    metadata: Mapping[str, PlainData] | None,
) -> Mapping[str, PlainData]:
    merged: dict[str, PlainData] = {}
    candidate_metadata = candidate.get("metadata")
    if isinstance(candidate_metadata, Mapping):
        merged.update(_plain_mapping(candidate_metadata, "candidate.metadata"))
    reason = candidate.get("reason")
    if isinstance(reason, Mapping):
        detail = reason.get("detail")
        if isinstance(detail, Mapping):
            merged.update(_plain_mapping(detail, "candidate.reason.detail"))
    if metadata is not None:
        merged.update(_plain_mapping(metadata, "metadata"))
    return merged


def _candidate_timestamp(candidate: Mapping[str, PlainData]) -> datetime:
    recorded_at = _non_empty_string(candidate.get("recorded_at"), "recorded_at")
    try:
        return parse_timestamp(recorded_at)
    except ValueError as exc:
        raise CleanupSelectorError("recorded_at must be a UTC loom timestamp") from exc


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CleanupSelectorError(f"{path}.from_dict expects mapping")
    return value


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], path: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise CleanupSelectorError(
            f"{path}: unknown field(s): {', '.join(sorted(unknown))}"
        )


def _require_schema_version(value: object, field: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value != CLEANUP_SELECTOR_SCHEMA_VERSION
    ):
        raise CleanupSelectorError(
            f"{field} must be {CLEANUP_SELECTOR_SCHEMA_VERSION}"
        )
    return value


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CleanupSelectorError(f"{field} must be a positive integer")
    return value


def _optional_timestamp(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _non_empty_string(value, field)
    try:
        parse_timestamp(text)
    except ValueError as exc:
        raise CleanupSelectorError(f"{field} must be a UTC loom timestamp") from exc
    return text


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CleanupSelectorError(f"{field} must be a non-empty string")
    return value


def _string_tuple(values: Sequence[object], field: str) -> tuple[str, ...]:
    return tuple(_non_empty_string(value, f"{field}[]") for value in values)


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise CleanupSelectorError("expected a sequence")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise CleanupSelectorError(f"{field} must be a mapping")
    try:
        return cast(Mapping[str, PlainData], freeze_plain_data(value, path=field))
    except Exception as exc:
        raise CleanupSelectorError(f"{field} must contain plain data") from exc


def _selection_status(value: object) -> CleanupSelectionStatus:
    if isinstance(value, CleanupSelectionStatus):
        return value
    if isinstance(value, str):
        try:
            return CleanupSelectionStatus(value)
        except ValueError as exc:
            raise CleanupSelectorError(
                "status must be one of: selected, skipped"
            ) from exc
    raise CleanupSelectorError("status must be one of: selected, skipped")


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "CLEANUP_SELECTOR_SCHEMA_VERSION",
    "CleanupSelection",
    "CleanupSelectionStatus",
    "CleanupSelector",
    "CleanupSelectorExplanation",
    "match_cleanup_candidate",
]
