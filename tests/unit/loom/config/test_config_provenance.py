"""Unit tests for config provenance models."""

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


def test_parsed_override_round_trip() -> None:
    override = ParsedOverride(raw="x=1", path="x", operation="update", value=1, order=0)
    assert ParsedOverride.from_dict(override.to_dict()) == override


def test_config_provenance_round_trip() -> None:
    provenance = ConfigProvenance(
        schema_version=SCHEMA_VERSION,
        config_path="/tmp/base.yaml",
        sources=(ConfigSource(kind="base", path="/tmp/base.yaml", order=0, content_digest="sha256:abcd", size_bytes=1),),
        overrides=(ParsedOverride(raw="a=1", path="a", operation="update", value=1, order=0),),
        resolved_fingerprint="sha256:abcd",
        recipe_manifest_count=0,
        metadata={},
    )
    assert ConfigProvenance.from_dict(provenance.to_dict()) == provenance


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
