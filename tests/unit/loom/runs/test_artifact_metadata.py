"""Tests for Stage 15 artifact metadata projection helpers."""

from __future__ import annotations

from typing import Any, cast

import pytest

from loom.artifacts import (
    ArtifactLocationKind,
    ArtifactLocationSummary,
    ArtifactRef,
    ArtifactStoreRef,
    ExternalArtifactDeclaration,
    PublishedArtifactRecord,
)
from loom.pipeline.stores import (
    ArtifactFactRecord,
    BackendRevision,
    CompletedRunBundleMetadata,
)
from loom.pipeline.stores.read_models import RunStatus
from loom.runs import (
    EXTERNAL_ARTIFACT_METADATA_KEY,
    PUBLISHED_ARTIFACT_METADATA_KEY,
    UNSUPPORTED_MATERIALIZATION_METADATA_KEY,
    ArtifactSummary,
    collect_artifact_metadata_summaries,
    unsupported_materialization_summary,
)
from loom.serialization import thaw_plain_data


pytestmark = pytest.mark.unit

CHECKSUM = "sha256:" + "3" * 64


def _external_declaration() -> ExternalArtifactDeclaration:
    return ExternalArtifactDeclaration(
        artifact_id="external-model",
        uri="s3://bucket/private/model",
        artifact_type="model",
        codec_key="json.v1",
        artifact_schema_version=1,
        store=ArtifactStoreRef(
            kind="object-store",
            display_uri="s3://bucket/redacted/model",
        ),
        location=ArtifactLocationSummary(
            kind=ArtifactLocationKind.EXTERNAL_IMMUTABLE,
            authority="authoritative",
            display_uri="s3://bucket/redacted/model",
            store=ArtifactStoreRef(kind="object-store", display_uri="s3://bucket"),
            checksum=CHECKSUM,
        ),
        checksum=CHECKSUM,
    )


def _published_record() -> PublishedArtifactRecord:
    return PublishedArtifactRecord(
        artifact_id="published-model",
        uri="tracking://run/model",
        artifact_type="model",
        codec_key="json.v1",
        artifact_schema_version=1,
        producer_run_uri="local://runs/demo",
        producer_stage="train",
        producer_artifact_id="model",
        reuse_key="model:abc",
        validation_policy={"checksum": CHECKSUM},
        store=ArtifactStoreRef(kind="tracking-system", display_uri="tracking://redacted"),
        checksum=CHECKSUM,
    )


def _artifact_ref() -> ArtifactRef:
    unsupported = unsupported_materialization_summary(
        "backend capability is unsupported",
        location=_external_declaration().location,
    )
    return ArtifactRef(
        artifact_id="external-model",
        uri="s3://bucket/private/model",
        artifact_type="model",
        codec_key="json.v1",
        checksum=CHECKSUM,
        metadata={
            EXTERNAL_ARTIFACT_METADATA_KEY: thaw_plain_data(
                _external_declaration().to_summary()
            ),
            PUBLISHED_ARTIFACT_METADATA_KEY: thaw_plain_data(
                _published_record().to_summary()
            ),
            UNSUPPORTED_MATERIALIZATION_METADATA_KEY: unsupported,
        },
    )


def test_collect_artifact_metadata_summaries_normalizes_stage_15_records() -> None:
    summaries = collect_artifact_metadata_summaries(_artifact_ref())

    external = cast(dict[str, Any], summaries[EXTERNAL_ARTIFACT_METADATA_KEY])
    assert external["artifact_id"] == "external-model"
    assert external["store"]["uri"] is None
    assert external["store"]["display_uri"] == "s3://bucket/redacted/model"

    published = cast(dict[str, Any], summaries[PUBLISHED_ARTIFACT_METADATA_KEY])
    assert published["reuse_key"] == "model:abc"
    unsupported = cast(
        dict[str, Any], summaries[UNSUPPORTED_MATERIALIZATION_METADATA_KEY]
    )
    assert unsupported["code"] == "artifact_materialization.unsupported"


def test_catalog_and_bundle_metadata_preserve_external_summaries() -> None:
    artifact = _artifact_ref()
    catalog_summary = ArtifactSummary(
        run_uri="local://runs/demo",
        artifact_id=artifact.artifact_id,
        logical_name="train/model",
        uri=artifact.uri,
        artifact_type=artifact.artifact_type,
        checksum=artifact.checksum,
        metadata=cast(dict[str, Any], thaw_plain_data(artifact.metadata)),
    )
    catalog_payload = catalog_summary.to_dict()
    catalog_summaries = collect_artifact_metadata_summaries(
        cast(dict[str, Any], catalog_payload["metadata"])
    )
    assert EXTERNAL_ARTIFACT_METADATA_KEY in catalog_summaries

    metadata = CompletedRunBundleMetadata(
        run_uri="local://runs/demo",
        status=RunStatus.SUCCEEDED,
        schema_version=1,
        revision=BackendRevision(sequence=1, token="rev-1"),
        artifact_facts=(
            ArtifactFactRecord(
                artifact_name="model",
                artifact=artifact,
                commit_id="commit-1",
                revision=BackendRevision(sequence=1, token="rev-1"),
            ),
        ),
    )
    bundle_payload = metadata.to_dict()
    artifact_facts = cast(list[dict[str, Any]], bundle_payload["artifact_facts"])
    artifact_payload = cast(dict[str, Any], artifact_facts[0]["artifact"])
    artifact_metadata = cast(dict[str, Any], artifact_payload["metadata"])
    bundle_summaries = collect_artifact_metadata_summaries(artifact_metadata)
    assert bundle_summaries[EXTERNAL_ARTIFACT_METADATA_KEY] == (
        catalog_summaries[EXTERNAL_ARTIFACT_METADATA_KEY]
    )
