"""Unit tests for local artifact store behavior."""

from pathlib import Path

import pytest

from loom.pipeline.stores import (
    ArtifactChecksumMismatchError,
    ArtifactChecksumUnsupportedError,
    ArtifactTypeMismatchError,
    ArtifactStoreError,
    LocalArtifactStore,
    MissingArtifactCodecError,
    UnsupportedArtifactURIError,
)


def test_local_artifact_save_load_json_text_and_bytes(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")

    json_ref = store.save(
        {"b": 2, "a": 1},
        run_id="run1",
        stage_name="stage",
        name="out",
        artifact_type="json",
        codec_key="json.v1",
    )
    assert json_ref.uri.startswith("file://")
    assert store.exists(json_ref)
    assert store.load(json_ref, expected_type="json") == {"b": 2, "a": 1}

    text_ref = store.save(
        "hello",
        run_id="run1",
        stage_name="stage",
        name="txt",
        artifact_type="text",
        codec_key="text.v1",
    )
    assert (tmp_path / "run" / "stage" / "txt.txt").exists()
    assert store.load(text_ref, expected_type="text") == "hello"

    bytes_ref = store.save(
        b"abc",
        run_id="run1",
        stage_name="stage",
        name="raw",
        artifact_type="bin",
        codec_key="bytes.v1",
    )
    assert (tmp_path / "run" / "stage" / "raw.bin").exists()
    assert store.load(bytes_ref, expected_type="bin") == b"abc"


def test_local_artifact_load_requires_codec(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    artifact_path = tmp_path / "run" / "stage" / "out.txt"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("hello")
    registered = store.register(
        artifact_path,
        run_id="run1",
        stage_name="stage",
        name="out",
        artifact_type="text",
        codec_key=None,
    )
    assert registered.codec_key is None
    with pytest.raises(MissingArtifactCodecError):
        store.load(registered, expected_type="text")
    assert store.load(registered, expected_type="text", codec_key="text.v1") == "hello"


def test_local_artifact_register_external_controls(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    external = tmp_path / "external.txt"
    external.write_text("payload")
    # Path is outside the stage directory by default.
    with pytest.raises(ArtifactStoreError):
        store.register(
            external,
            run_id="run1",
            stage_name="stage",
            name="out",
            artifact_type="text",
            codec_key=None,
        )

    registered = store.register(
        external,
        run_id="run1",
        stage_name="stage",
        name="out",
        artifact_type="text",
        codec_key=None,
        allow_external=True,
    )
    assert registered.uri.endswith("external.txt")


def test_local_artifact_checksum_behavior(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    source = tmp_path / "run" / "stage" / "file.bin"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"abc")
    with pytest.raises(ArtifactChecksumMismatchError):
        store.register(
            source,
            run_id="run1",
            stage_name="stage",
            name="bad",
            artifact_type="bytes",
            checksum=f"sha256:{'0' * 64}",
        )

    directory = tmp_path / "run" / "stage" / "dir"
    directory.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ArtifactChecksumUnsupportedError):
        store.register(
            directory,
            run_id="run1",
            stage_name="stage",
            name="dir",
            artifact_type="tree",
            checksum=f"sha256:{'a' * 64}",
        )


def test_local_artifact_load_rejects_directory_artifacts(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    directory = tmp_path / "run" / "stage" / "dir"
    directory.mkdir(parents=True, exist_ok=True)
    registered = store.register(
        directory,
        run_id="run1",
        stage_name="stage",
        name="dir",
        artifact_type="tree",
        codec_key="json.v1",
    )

    with pytest.raises(ArtifactTypeMismatchError):
        store.load(registered)


def test_local_artifact_type_mismatch_raises(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    ref = store.save(
        "hello",
        run_id="run1",
        stage_name="stage",
        name="txt",
        artifact_type="text",
        codec_key="text.v1",
    )
    with pytest.raises(ArtifactTypeMismatchError):
        store.validate(ref, expected_type="json")


def test_local_artifact_rejects_unsupported_uri(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    with pytest.raises(UnsupportedArtifactURIError):
        store.register(
            "https://example.com/x",
            run_id="run1",
            stage_name="stage",
            name="out",
            artifact_type="text",
        )
