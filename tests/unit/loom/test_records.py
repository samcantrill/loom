"""Unit tests for records and manifests."""

import pytest

from loom.records import DuplicateRecordError, InMemoryManifest, ManifestView, Record, HasResource, MetadataEquals, MetadataIn, RecordNotFoundError
from loom.refs import ResourceRef


def _make_record(value: str) -> Record:
    return Record(record_id=value, resources={}, metadata={"tag": value})


def test_record_round_trip_and_resource_lookup() -> None:
    resource = ResourceRef(uri="file:///x", resource_type="dataset")
    record = Record(
        record_id="sample",
        resources={"input": resource},
        metadata={"split": "train"},
        annotations={"stage": "prep"},
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
