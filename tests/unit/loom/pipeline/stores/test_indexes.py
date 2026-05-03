"""Unit tests for logical artifact index helpers."""

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.stores import artifact_index_from_dict, artifact_index_to_dict, format_artifact_key, merge_artifact_index, parse_artifact_key


def test_artifact_key_format_and_parse_roundtrip() -> None:
    key = format_artifact_key("stage", "output")
    assert key == "stage.output"
    stage, output = parse_artifact_key(key)
    assert stage == "stage"
    assert output == "output"


def test_artifact_key_rejects_invalid_shape() -> None:
    for invalid in ("stage", "stage.output.extra", ".output", "stage.", "s.tage.out", ""):
        with pytest.raises(Exception):
            parse_artifact_key(invalid)


def test_artifact_index_to_from_dict_roundtrip() -> None:
    index = {
        "stage.output": ArtifactRef(
            artifact_id="stage/output",
            uri="file:///tmp/stage_output.json",
            artifact_type="json",
            codec_key="json.v1",
        ),
    }
    payload = artifact_index_to_dict(index)
    assert payload["stage.output"] == {
        "artifact_id": "stage/output",
        "uri": "file:///tmp/stage_output.json",
        "artifact_type": "json",
        "codec_key": "json.v1",
        "schema_version": 1,
        "checksum": None,
        "fingerprint": None,
        "producer_stage": None,
        "created_at": None,
        "metadata": {},
    }

    parsed = artifact_index_from_dict(payload)
    assert parsed == index


def test_merge_artifact_index_rejects_duplicate_different_refs_by_default() -> None:
    left = {"s.x": ArtifactRef(artifact_id="s/x", uri="file:///tmp/a", artifact_type="text", codec_key="text.v1")}
    right = {"s.x": ArtifactRef(artifact_id="s/x", uri="file:///tmp/b", artifact_type="text", codec_key="text.v1")}
    with pytest.raises(Exception):
        merge_artifact_index(left, right)


def test_merge_artifact_index_replace_allows_updates() -> None:
    left = {"s.x": ArtifactRef(artifact_id="s/x", uri="file:///tmp/a", artifact_type="text", codec_key="text.v1")}
    right = {"s.x": ArtifactRef(artifact_id="s/x", uri="file:///tmp/b", artifact_type="text", codec_key="text.v1")}
    merged = merge_artifact_index(left, right, replace=True)
    assert merged["s.x"].uri == "file:///tmp/b"
