"""Metadata projection helpers for Stage 15 artifact summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from loom.artifacts import (
    ArtifactLocationSummary,
    ArtifactRef,
    ExternalArtifactDeclaration,
    PublishedArtifactRecord,
)
from loom.serialization import PlainData, ensure_plain_data, thaw_plain_data

from .errors import CatalogValidationError

EXTERNAL_ARTIFACT_METADATA_KEY = "external_artifact"
PUBLISHED_ARTIFACT_METADATA_KEY = "published_artifact"
ARTIFACT_LOCATION_METADATA_KEY = "artifact_location"
ARTIFACT_LOCATIONS_METADATA_KEY = "artifact_locations"
UNSUPPORTED_MATERIALIZATION_METADATA_KEY = "unsupported_materialization"


def collect_artifact_metadata_summaries(
    artifact_or_metadata: ArtifactRef | Mapping[str, PlainData],
) -> dict[str, PlainData]:
    """Return normalized Stage 15 summaries embedded in artifact metadata."""

    metadata = _metadata(artifact_or_metadata)
    summaries: dict[str, PlainData] = {}

    external = metadata.get(EXTERNAL_ARTIFACT_METADATA_KEY)
    if external is not None:
        summaries[EXTERNAL_ARTIFACT_METADATA_KEY] = cast(
            PlainData,
            thaw_plain_data(
                ExternalArtifactDeclaration.from_dict(_mapping(external)).to_summary(),
                path=EXTERNAL_ARTIFACT_METADATA_KEY,
            ),
        )

    published = metadata.get(PUBLISHED_ARTIFACT_METADATA_KEY)
    if published is not None:
        summaries[PUBLISHED_ARTIFACT_METADATA_KEY] = cast(
            PlainData,
            thaw_plain_data(
                PublishedArtifactRecord.from_dict(_mapping(published)).to_summary(),
                path=PUBLISHED_ARTIFACT_METADATA_KEY,
            ),
        )

    location = metadata.get(ARTIFACT_LOCATION_METADATA_KEY)
    if location is not None:
        summaries[ARTIFACT_LOCATION_METADATA_KEY] = cast(
            PlainData,
            thaw_plain_data(
                ArtifactLocationSummary.from_dict(_mapping(location)).to_summary(),
                path=ARTIFACT_LOCATION_METADATA_KEY,
            ),
        )

    locations = metadata.get(ARTIFACT_LOCATIONS_METADATA_KEY)
    if locations is not None:
        summaries[ARTIFACT_LOCATIONS_METADATA_KEY] = [
            thaw_plain_data(
                ArtifactLocationSummary.from_dict(_mapping(item)).to_summary(),
                path=f"{ARTIFACT_LOCATIONS_METADATA_KEY}[]",
            )
            for item in _sequence(locations, ARTIFACT_LOCATIONS_METADATA_KEY)
        ]

    unsupported = metadata.get(UNSUPPORTED_MATERIALIZATION_METADATA_KEY)
    if unsupported is not None:
        summaries[UNSUPPORTED_MATERIALIZATION_METADATA_KEY] = ensure_plain_data(
            unsupported,
            path=UNSUPPORTED_MATERIALIZATION_METADATA_KEY,
        )

    return summaries


def unsupported_materialization_summary(
    reason: str,
    *,
    uri: str | None = None,
    location: ArtifactLocationSummary | None = None,
    details: Mapping[str, PlainData] | None = None,
) -> dict[str, PlainData]:
    """Build a metadata-only unsupported-materialization summary."""

    if not isinstance(reason, str) or not reason:
        raise CatalogValidationError("reason must be a non-empty string")
    if uri is not None and (not isinstance(uri, str) or not uri):
        raise CatalogValidationError("uri must be None or a non-empty string")
    if location is not None and not isinstance(location, ArtifactLocationSummary):
        raise CatalogValidationError(
            "location must be ArtifactLocationSummary or None"
        )
    payload: dict[str, PlainData] = {
        "code": "artifact_materialization.unsupported",
        "message": "artifact materialization is not supported by this metadata",
        "reason": reason,
        "uri": uri,
        "location": None
        if location is None
        else thaw_plain_data(location.to_summary(), path="location"),
        "details": dict(details or {}),
    }
    return cast(
        dict[str, PlainData],
        ensure_plain_data(payload, path=UNSUPPORTED_MATERIALIZATION_METADATA_KEY),
    )


def _metadata(
    artifact_or_metadata: ArtifactRef | Mapping[str, PlainData],
) -> Mapping[str, PlainData]:
    if isinstance(artifact_or_metadata, ArtifactRef):
        return cast(
            Mapping[str, PlainData],
            thaw_plain_data(artifact_or_metadata.metadata, path="metadata"),
        )
    if isinstance(artifact_or_metadata, Mapping):
        return artifact_or_metadata
    raise CatalogValidationError("expected ArtifactRef or metadata mapping")


def _mapping(value: object) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise CatalogValidationError("artifact summary metadata must be a mapping")
    return cast(Mapping[str, PlainData], value)


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CatalogValidationError(f"{field} must be a sequence")
    return value


__all__ = [
    "EXTERNAL_ARTIFACT_METADATA_KEY",
    "PUBLISHED_ARTIFACT_METADATA_KEY",
    "ARTIFACT_LOCATION_METADATA_KEY",
    "ARTIFACT_LOCATIONS_METADATA_KEY",
    "UNSUPPORTED_MATERIALIZATION_METADATA_KEY",
    "collect_artifact_metadata_summaries",
    "unsupported_materialization_summary",
]
