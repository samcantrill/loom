"""Unit tests for records and manifests."""

from typing import Any, cast

import pytest

from loom.records import DuplicateRecordError, InMemoryManifest, ManifestView, Record, HasResource, MetadataEquals, MetadataIn, RecordNotFoundError
from loom.refs import ResourceRef
from loom.serialization import PlainData


def _make_record(value: str) -> Record:
    return Record(record_id=value, resources={}, metadata={"tag": value})


def test_record_round_trip_and_resource_lookup() -> None:
    resource = ResourceRef(uri="file:///x", resource_type="dataset")
    record = Record(
        record_id="sample",
        resources={"input": resource},
        metadata=cast(dict[str, PlainData], {"split": {"name": "train", "folds": [1, 2]}}),
        annotations=cast(
            dict[str, PlainData],
            {"stage": {"name": "prep", "flags": ["reviewed"]}},
        ),
        provenance=cast(dict[str, PlainData], {"sources": [{"uri": "file:///x"}]}),
    )
    assert record.has_resource("input")
    assert record.get_resource("input") == resource
    assert record.require_resource("input") == resource
    assert record.to_dict()["record_id"] == "sample"
    assert Record.from_dict(record.to_dict()) == record


def test_in_memory_manifest_preserves_order_and_rejects_duplicates() -> None:
    manifest = InMemoryManifest(records=(_make_record("a"), _make_record("b"), _make_record("c")))
    assert list(record.record_id for record in manifest) == ["a", "b", "c"]
    assert len(manifest) == 3
    assert manifest.get("b") is not None
    with pytest.raises(DuplicateRecordError):
        InMemoryManifest(records=[_make_record("a"), _make_record("a")])


def test_manifest_lookup_and_to_dict() -> None:
    manifest = InMemoryManifest(records=(_make_record("a"), _make_record("b")))
    assert manifest.to_dict()["schema_version"] == 1
    assert manifest.require("a") == _make_record("a")
    assert manifest.get("missing") is None
    with pytest.raises(RecordNotFoundError):
        manifest.require("missing")


def test_manifest_view_filters_and_materialize() -> None:
    view = ManifestView(source=InMemoryManifest(records=(_make_record("a"), _make_record("b"), _make_record("c"))))
    narrowed = view.filter(MetadataEquals("tag", "b")).filter(HasResource("input"))
    assert list(record.record_id for record in narrowed) == []
    materialized = narrowed.materialize()
    assert isinstance(materialized, InMemoryManifest)
    assert list(materialized) == []


def test_record_view_filter_composition() -> None:
    records = (
        Record(record_id="a", resources={}, metadata={"class": "x"}),
        Record(record_id="b", resources={"in": ResourceRef(uri="file:///x", resource_type="dataset")}, metadata={"class": "x"}),
        Record(record_id="c", resources={"in": ResourceRef(uri="file:///x", resource_type="dataset")}, metadata={"class": "y"}),
    )
    view = ManifestView(source=InMemoryManifest(records=records))
    assert [r.record_id for r in view.filter(MetadataIn("class", ["x"]))] == ["a", "b"]
    assert [r.record_id for r in view.filter(MetadataEquals("class", "y")).filter(HasResource("in"))] == ["c"]
    assert view.get("b") is not None
    assert view.filter(MetadataEquals("missing", "x")).get("a") is None


def test_record_from_dict_rejects_invalid_payloads() -> None:
    with pytest.raises(Exception):
        Record.from_dict({"record_id": "a", "resources": [1, 2, 3]})
    with pytest.raises(Exception):
        Record.from_dict({"resources": {}, "record_id": 1})
    with pytest.raises(Exception):
        Record.from_dict({"record_id": "a", "resources": {"x": 1}})
    with pytest.raises(Exception):
        Record.from_dict({"record_id": "a", "resources": {1: {"uri": "x", "resource_type": "dataset"}}})


def test_record_and_manifest_metadata_are_immutable_and_constructor_inputs_are_copied() -> None:
    resource_metadata: dict[str, Any] = {"owner": "team", "tags": ["train", "valid"]}
    resource = ResourceRef(
        uri="file:///x",
        resource_type="dataset",
        metadata=cast(dict[str, PlainData], resource_metadata),
    )
    metadata: dict[str, Any] = {"split": {"name": "train", "ratios": [0.8, 0.2]}}
    annotations: dict[str, Any] = {"audit": {"notes": ["first"]}}
    provenance: dict[str, Any] = {"lineage": {"steps": ["raw"]}}
    record = Record(
        record_id="sample",
        resources={"primary": resource},
        metadata=cast(dict[str, PlainData], metadata),
        annotations=cast(dict[str, PlainData], annotations),
        provenance=cast(dict[str, PlainData], provenance),
    )

    metadata["split"]["ratios"][0] = 0.5
    annotations["audit"]["notes"].append("second")
    provenance["lineage"]["steps"].append("transformed")
    resource_metadata["tags"].append("release")

    assert record.resources["primary"].metadata["owner"] == "team"
    assert record.resources["primary"].metadata["tags"] == ("train", "valid")
    split = cast(dict[str, Any], record.metadata["split"])
    assert split["ratios"] == (0.8, 0.2)
    assert record.annotations["audit"] == {"notes": ("first",)}
    assert record.provenance["lineage"] == {"steps": ("raw",)}
    with pytest.raises(TypeError):
        cast(Any, record.resources)["primary"] = resource
    with pytest.raises(TypeError):
        cast(Any, split["ratios"])[0] = 0.1

    snapshot = cast(dict[str, Any], record.to_dict())
    snapshot["metadata"]["split"]["ratios"][0] = 0.9
    snapshot["annotations"]["audit"]["notes"].append("extra")
    snapshot["provenance"]["lineage"]["steps"].append("post")
    snapshot["resources"]["primary"]["metadata"]["owner"] = "hacked"

    split_after = cast(dict[str, Any], record.metadata["split"])
    assert split_after["ratios"] == (0.8, 0.2)
    assert record.annotations["audit"] == {"notes": ("first",)}
    assert record.provenance["lineage"] == {"steps": ("raw",)}


def test_manifest_metadata_is_immutable_and_to_dict_returns_mutable_plain_data() -> None:
    manifest_metadata: dict[str, Any] = {"owner": {"team": "analysis", "labels": ["x", "y"]}}
    manifest = InMemoryManifest(
        records=(_make_record("a"),),
        metadata=cast(dict[str, PlainData], manifest_metadata),
    )
    manifest_view = ManifestView(source=manifest)

    manifest_metadata["labels"] = ["z"]
    manifest_metadata["owner"]["team"] = "ops"

    assert manifest.metadata["owner"] == {"team": "analysis", "labels": ("x", "y")}
    with pytest.raises(TypeError):
        cast(Any, manifest.metadata["owner"])["team"] = "ops"
    with pytest.raises(TypeError):
        cast(Any, manifest.metadata)["new"] = 1

    manifest_dict = cast(dict[str, Any], manifest.to_dict())
    manifest_dict["metadata"]["owner"]["labels"].append("z")
    manifest_dict["records"][0]["metadata"]["tag"] = "override"

    assert manifest.metadata == {"owner": {"team": "analysis", "labels": ("x", "y")}}

    filtered_view = manifest_view.filter(MetadataEquals("tag", "a"))
    assert filtered_view.to_dict()["metadata"] == {}
    filtered_dict = cast(dict[str, Any], filtered_view.to_dict())
    filtered_dict["metadata"]["team"] = "changed"

    assert manifest_view.metadata == {}


def test_in_memory_manifest_from_dict_rejects_unknown_fields() -> None:
    with pytest.raises(Exception):
        InMemoryManifest.from_dict(
            {
                "schema_version": 1,
                "records": [],
                "unexpected": True,
            },
        )


def test_in_memory_manifest_from_dict_round_trips_nested_metadata() -> None:
    manifest = InMemoryManifest(
        records=(_make_record("a"),),
        metadata=cast(
            dict[str, PlainData],
            {"owner": {"team": "analysis", "labels": ["x", "y"]}},
        ),
    )

    restored = InMemoryManifest.from_dict(manifest.to_dict())

    assert restored == manifest
    owner = cast(dict[str, Any], restored.metadata["owner"])
    assert owner["labels"] == ("x", "y")


def test_in_memory_manifest_from_dict_rejects_unsupported_schema_version() -> None:
    with pytest.raises(Exception):
        InMemoryManifest.from_dict(
            {
                "schema_version": 2,
                "records": [],
            },
        )
