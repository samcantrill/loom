"""Unit tests for config provenance models."""

import pytest

from loom.config.errors import ConfigErrorContext, ConfigProvenanceError
from loom.config.provenance import (
    SCHEMA_VERSION,
    ConfigProvenance,
    ConfigSource,
    ParsedOverride,
    build_config_fingerprint,
)


def test_config_source_round_trip() -> None:
    source = ConfigSource(kind="base", path="/tmp/config.yaml", order=0, content_digest="sha256:abcd", size_bytes=3)
    round_trip = ConfigSource.from_dict(source.to_dict())
    assert source == round_trip


def test_config_source_from_dict_failure_has_context() -> None:
    with pytest.raises(ConfigProvenanceError) as exc:
        ConfigSource.from_dict(
            {
                "kind": "runtime",
                "path": "/tmp/config.yaml",
                "order": 0,
                "content_digest": "sha256:abcd",
                "size_bytes": 3,
            }
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_config_source_kind"
    assert context.config_path == "ConfigSource.kind"
    assert context.details is not None
    assert context.details["stage"] == "provenance_from_dict"
    assert ConfigErrorContext.from_dict(context.to_dict()) == context


def test_parsed_override_round_trip() -> None:
    override = ParsedOverride(raw="x=1", path="x", operation="update", value=1, order=0)
    assert ParsedOverride.from_dict(override.to_dict()) == override


def test_parsed_override_failure_context_omits_raw_secret_like_override() -> None:
    with pytest.raises(ConfigProvenanceError) as exc:
        ParsedOverride.from_dict(
            {
                "raw": 123,
                "path": "auth.token",
                "operation": "update",
                "value": "secret-value",
                "order": 0,
            }
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_override_raw"
    assert context.config_path == "ParsedOverride.raw"
    assert context.actual == "int"
    assert context.details is not None
    assert context.details["stage"] == "provenance_from_dict"
    assert "secret-value" not in repr(context.to_dict())


def test_config_provenance_round_trip() -> None:
    provenance = ConfigProvenance(
        schema_version=SCHEMA_VERSION,
        config_path="/tmp/base.yaml",
        sources=(ConfigSource(kind="base", path="/tmp/base.yaml", order=0, content_digest="sha256:abcd", size_bytes=1),),
        overrides=(ParsedOverride(raw="a=1", path="a", operation="update", value=1, order=0),),
        recipe_manifest_count=0,
        metadata={},
        artifact_fingerprint="sha256:artifact",
    )
    payload = provenance.to_dict()
    assert payload["artifact_fingerprint"] == "sha256:artifact"
    assert "resolved_fingerprint" not in payload
    assert ConfigProvenance.from_dict(payload) == provenance


def test_config_provenance_v2_write_requires_artifact_fingerprint() -> None:
    provenance = ConfigProvenance(
        schema_version=SCHEMA_VERSION,
        config_path="/tmp/base.yaml",
        sources=(ConfigSource(kind="base", path="/tmp/base.yaml", order=0, content_digest="sha256:abcd", size_bytes=1),),
        overrides=(),
        recipe_manifest_count=0,
        metadata={},
    )

    with pytest.raises(ConfigProvenanceError) as exc:
        provenance.to_dict()

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_config_provenance_artifact_fingerprint"
    assert context.config_path == "ConfigProvenance.artifact_fingerprint"
    assert context.details is not None
    assert context.details["stage"] == "provenance_serialization"


def test_config_provenance_reads_legacy_v1_resolved_fingerprint_only_as_metadata() -> None:
    provenance = ConfigProvenance.from_dict(
        {
            "schema_version": 1,
            "config_path": "/tmp/base.yaml",
            "sources": (
                {
                    "kind": "base",
                    "path": "/tmp/base.yaml",
                    "order": 0,
                    "content_digest": "sha256:abcd",
                    "size_bytes": 1,
                },
            ),
            "overrides": (),
            "resolved_fingerprint": "sha256:legacy",
            "recipe_manifest_count": 0,
            "metadata": {"source": "legacy"},
        }
    )

    assert provenance.schema_version == 1
    assert provenance.artifact_fingerprint is None
    assert provenance.metadata["legacy_resolved_fingerprint"] == "sha256:legacy"

    with pytest.raises(ConfigProvenanceError) as exc:
        provenance.to_dict()

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_config_provenance_schema_version"
    assert context.config_path == "ConfigProvenance.schema_version"
    assert context.expected == SCHEMA_VERSION
    assert context.actual == "int"
    assert context.details is not None
    assert context.details["stage"] == "provenance_serialization"


def test_config_provenance_from_dict_failure_has_context() -> None:
    with pytest.raises(ConfigProvenanceError) as exc:
        ConfigProvenance.from_dict(
            {
                "schema_version": SCHEMA_VERSION,
                "config_path": "/tmp/base.yaml",
                "sources": (),
                "overrides": (),
                "artifact_fingerprint": "sha256:artifact",
                "recipe_manifest_count": 0,
                "metadata": [],
            }
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_config_provenance_metadata"
    assert context.config_path == "ConfigProvenance.metadata"
    assert context.details is not None
    assert context.details["stage"] == "provenance_from_dict"


def test_config_provenance_v2_rejects_legacy_resolved_fingerprint_field() -> None:
    with pytest.raises(ConfigProvenanceError) as exc:
        ConfigProvenance.from_dict(
            {
                "schema_version": SCHEMA_VERSION,
                "config_path": "/tmp/base.yaml",
                "sources": (),
                "overrides": (),
                "artifact_fingerprint": "sha256:artifact",
                "resolved_fingerprint": "sha256:legacy",
                "recipe_manifest_count": 0,
                "metadata": {},
            }
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "config_provenance_unknown_fields"
    assert context.config_path == "ConfigProvenance"


def test_fingerprint_reflects_override_content() -> None:
    source = ConfigSource(kind="base", path="/tmp/base.yaml", order=0, content_digest="sha256:abcd", size_bytes=1)
    override = ParsedOverride(raw="x=1", path="x", operation="update", value=1, order=0)
    resolved = {"name": "demo", "pipeline": {}}

    first = build_config_fingerprint(
        resolved=resolved,
        sources=(source,),
        overrides=(override,),
        schema_version=SCHEMA_VERSION,
    )
    override_2 = ParsedOverride(raw="x=2", path="x", operation="update", value=2, order=0)
    second = build_config_fingerprint(
        resolved=resolved,
        sources=(source,),
        overrides=(override_2,),
        schema_version=SCHEMA_VERSION,
    )

    assert first != second
    assert isinstance(first, str)
    assert isinstance(second, str)


def test_fingerprint_reflects_recipe_manifest_records() -> None:
    source = ConfigSource(kind="base", path="/tmp/base.yaml", order=0, content_digest="sha256:abcd", size_bytes=1)
    resolved = {"name": "demo", "pipeline": {"value": "same"}}
    manifest = {
        "path": "pipeline",
        "name": "a",
        "target": "tests.support.config_samples:function_recipe",
        "arguments": {"value": "same"},
        "expanded_hash": "sha256:1111",
        "expanded_path": "pipeline",
        "loom_version": "0.1.0",
    }

    first = build_config_fingerprint(
        resolved=resolved,
        sources=(source,),
        overrides=(),
        recipe_manifest=(manifest,),
        schema_version=SCHEMA_VERSION,
    )
    second = build_config_fingerprint(
        resolved=resolved,
        sources=(source,),
        overrides=(),
        recipe_manifest=({**manifest, "name": "b"},),
        schema_version=SCHEMA_VERSION,
    )

    assert first != second
