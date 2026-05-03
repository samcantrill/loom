"""Integration checks for source + codec cooperation."""

from __future__ import annotations

from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.io import create_default_codec_registry, LocalFileSystemSource
from loom.refs import ResourceRef


def test_local_source_and_codecs_roundtrip(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    registry = create_default_codec_registry()

    text_path = tmp_path / "report.txt"
    with source.open(text_path, "wb") as handle:
        handle.write(registry.encode("text.v1", "hello"))
    with source.open(text_path, "rb") as handle:
        assert registry.decode("text.v1", handle.read()) == "hello"

    json_path = tmp_path / "payload.json"
    with source.open(json_path, "wb") as handle:
        handle.write(registry.encode("json.v1", {"a": [1, 2, 3]}))
    with source.open(json_path, "rb") as handle:
        assert registry.decode("json.v1", handle.read()) == {"a": [1, 2, 3]}

    bytes_path = tmp_path / "raw.bin"
    with source.open(bytes_path, "wb") as handle:
        handle.write(registry.encode("bytes.v1", b"blob"))
    with source.open(bytes_path, "rb") as handle:
        assert registry.decode("bytes.v1", handle.read()) == b"blob"

    uris = source.glob("*.txt")
    assert len(uris) == 1
    assert uris[0].startswith("file://")


def test_refs_are_passive_placeholders(tmp_path: Path) -> None:
    del tmp_path
    resource = ResourceRef(uri="file:///tmp/input.txt", resource_type="text")
    artifact = ArtifactRef(
        artifact_id="output",
        uri="file:///tmp/output.txt",
        artifact_type="text",
    )

    for value in (resource, artifact):
        assert not hasattr(value, "open")
        assert not hasattr(value, "save")
        assert not hasattr(value, "load")
        assert not hasattr(value, "exists")

