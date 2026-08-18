"""Unit tests for resource references."""

from typing import Any, cast

import pytest

from loom.refs import ResourceRef, ResourceRefError
from loom.serialization import PlainData


def test_resource_ref_is_frozen() -> None:
    ref = ResourceRef(uri="file:///data", resource_type="dataset")
    with pytest.raises(Exception):
        ref.uri = "file:///changed"  # type: ignore[attr-defined]


def test_resource_ref_to_dict_from_dict_round_trip() -> None:
    ref = ResourceRef(
        uri="file:///data/x",
        resource_type="dataset",
        codec_key=None,
        schema_version=2,
        checksum="sha256:" + "a" * 64,
        metadata=cast(
            dict[str, PlainData], {"split": {"name": "train", "folds": [1, 2]}}
        ),
    )
    assert ref.to_dict() == {
        "uri": "file:///data/x",
        "resource_type": "dataset",
        "codec_key": None,
        "schema_version": 2,
        "checksum": "sha256:" + "a" * 64,
        "metadata": {"split": {"name": "train", "folds": [1, 2]}},
    }
    assert ResourceRef.from_dict(ref.to_dict()) == ref


def test_resource_ref_codec_key_preserves_set_absent_and_none() -> None:
    explicit_none = ResourceRef.from_dict(
        {"uri": "x", "resource_type": "dataset", "codec_key": None}
    )
    omitted = ResourceRef.from_dict({"uri": "x", "resource_type": "dataset"})
    set_default = ResourceRef(uri="x", resource_type="dataset")

    assert explicit_none.codec_key is None
    assert omitted.codec_key is None
    assert set_default.codec_key is None
    assert explicit_none.to_dict()["codec_key"] is None
    assert omitted.to_dict()["codec_key"] is None


@pytest.mark.parametrize("schema_version", [True, 0, "1"])
def test_resource_ref_schema_version_constructor_and_deserializer_agree(
    schema_version: object,
) -> None:
    common: dict[str, Any] = {"uri": "file:///data", "resource_type": "dataset"}

    with pytest.raises(ResourceRefError, match="schema_version"):
        ResourceRef(schema_version=cast(Any, schema_version), **common)
    with pytest.raises(ResourceRefError, match="schema_version"):
        ResourceRef.from_dict({**common, "schema_version": schema_version})


def test_resource_ref_rejects_invalid_inputs() -> None:
    with pytest.raises(ResourceRefError):
        ResourceRef.from_dict({"resource_type": "dataset"})
    with pytest.raises(ResourceRefError):
        ResourceRef(uri="", resource_type="dataset")
    with pytest.raises(ResourceRefError):
        ResourceRef.from_dict(
            {"uri": "x", "resource_type": "dataset", "schema_version": 0}
        )
    with pytest.raises(ResourceRefError):
        ResourceRef.from_dict({"uri": "x", "resource_type": "dataset", "extra": 1})
    with pytest.raises(ResourceRefError):
        ResourceRef.from_dict(
            {"uri": "x", "resource_type": "dataset", "checksum": "not-valid"}
        )


def test_resource_ref_no_loading_methods() -> None:
    ref = ResourceRef(uri="x", resource_type="dataset")
    assert not hasattr(ref, "load")
    assert not hasattr(ref, "open")
    assert not hasattr(ref, "exists")


def test_resource_ref_metadata_is_immutable_and_to_dict_mutations_are_local() -> None:
    source_metadata: dict[str, Any] = {
        "split": {"name": "train", "partitions": ["a", "b"]}
    }
    ref = ResourceRef(
        uri="file:///x",
        resource_type="dataset",
        metadata=cast(dict[str, PlainData], source_metadata),
    )

    source_metadata["split"]["partitions"].append("c")
    source_metadata["split"]["new"] = "value"

    split = cast(dict[str, Any], ref.metadata["split"])
    assert split["name"] == "train"
    assert split["partitions"] == ("a", "b")
    assert split == {"name": "train", "partitions": ("a", "b")}
    with pytest.raises(TypeError):
        cast(Any, ref.metadata)["new"] = "value"
    with pytest.raises(TypeError):
        cast(Any, split["partitions"])[0] = "z"

    snapshot = cast(dict[str, Any], ref.to_dict())
    snapshot["metadata"]["split"]["partitions"].append("d")
    snapshot["metadata"]["split"]["new"] = "value"

    split_after = cast(dict[str, Any], ref.metadata["split"])
    assert split_after["partitions"] == ("a", "b")
    assert "new" not in split_after
