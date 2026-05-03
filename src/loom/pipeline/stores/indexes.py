"""Artifact index helpers for run-store persistence."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef, ArtifactValidationError
from loom.serialization import PlainData
from loom.serialization import ensure_plain_data

from .errors import ArtifactStoreError
from ._paths import validate_output_name, validate_stage_name


def format_artifact_key(stage_name: str, output_name: str) -> str:
    """Create a logical artifact key from a stage and output name."""

    validated_stage = validate_stage_name(stage_name, field="stage_name")
    validated_output = validate_output_name(output_name, field="output_name")
    return f"{validated_stage}.{validated_output}"


def parse_artifact_key(key: str) -> tuple[str, str]:
    """Split and validate a stage/output artifact key."""

    if not isinstance(key, str):
        raise ArtifactStoreError("artifact key must be a string")
    if key.count(".") != 1:
        raise ArtifactStoreError(f"artifact key must contain exactly one '.': {key!r}")
    stage_name, output_name = key.split(".", 1)
    return validate_stage_name(stage_name, field="stage_name"), validate_output_name(output_name, field="output_name")


def artifact_index_to_dict(index: Mapping[str, ArtifactRef]) -> dict[str, PlainData]:
    """Serialize an artifact index to JSON-friendly data."""

    if not isinstance(index, Mapping):
        raise ArtifactStoreError("artifact index must be a mapping")
    payload: dict[str, PlainData] = {}
    for key, ref in index.items():
        parsed_key = parse_artifact_key(key)
        _ = parsed_key
        if not isinstance(ref, ArtifactRef):
            raise ArtifactStoreError(f"artifact index entry {key!r} must be an ArtifactRef")
        payload[key] = ensure_plain_data(ref.to_dict(), path=f"artifact_index[{key!r}]")
    return payload


def artifact_index_from_dict(data: object) -> dict[str, ArtifactRef]:
    """Deserialize and validate a persisted artifact index payload."""

    if not isinstance(data, Mapping):
        raise ArtifactStoreError("artifact index payload must be an object")

    parsed: dict[str, ArtifactRef] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ArtifactStoreError("artifact index keys must be strings")
        parse_artifact_key(key)
        if not isinstance(value, Mapping):
            raise ArtifactStoreError(f"artifact index value for {key!r} must be an object")
        try:
            parsed[key] = ArtifactRef.from_dict(dict(value))
        except ArtifactValidationError as exc:
            raise ArtifactStoreError(f"invalid artifact ref for key {key!r}: {exc}") from exc
    return parsed


def merge_artifact_index(
    index: Mapping[str, ArtifactRef],
    updates: Mapping[str, ArtifactRef],
    *,
    replace: bool = False,
) -> dict[str, ArtifactRef]:
    """Merge artifact indexes with optional key replacement semantics."""

    if not isinstance(index, Mapping) or not isinstance(updates, Mapping):
        raise ArtifactStoreError("artifact index merge inputs must be mappings")

    merged: dict[str, ArtifactRef] = dict(index)
    for key, value in updates.items():
        parse_artifact_key(key)
        if not isinstance(value, ArtifactRef):
            raise ArtifactStoreError(f"artifact index update {key!r} must be an ArtifactRef")
        if not replace and key in merged and merged[key] != value:
            raise ArtifactStoreError(f"artifact key {key!r} already exists with a different artifact ref")
        merged[key] = value
    return merged


__all__ = [
    "format_artifact_key",
    "parse_artifact_key",
    "artifact_index_to_dict",
    "artifact_index_from_dict",
    "merge_artifact_index",
]
