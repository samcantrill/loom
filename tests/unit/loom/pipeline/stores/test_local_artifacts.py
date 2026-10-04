"""Unit tests for local artifact store behavior."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from loom.pipeline.stores import (
    ArtifactChecksumMismatchError,
    ArtifactChecksumUnsupportedError,
    ArtifactNotFoundError,
    ArtifactTypeMismatchError,
    ArtifactStoreError,
    LocalRunArtifactStore,
    LocalArtifactStore,
    MissingArtifactCodecError,
    UnsupportedArtifactURIError,
    path_to_run_uri,
)
from loom.pipeline.stores.local_runs import LocalRunStore


def test_local_artifact_save_load_json_text_and_bytes(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")

    json_ref = store.save(
        {"b": 2, "a": 1},
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
        stage_name="stage",
        name="txt",
        artifact_type="text",
        codec_key="text.v1",
    )
    assert (tmp_path / "run" / "stage" / "txt.txt").exists()
    assert store.load(text_ref, expected_type="text") == "hello"

    bytes_ref = store.save(
        b"abc",
        stage_name="stage",
        name="raw",
        artifact_type="bin",
        codec_key="bytes.v1",
    )
    assert (tmp_path / "run" / "stage" / "raw.bin").exists()
    assert store.load(bytes_ref, expected_type="bin") == b"abc"


def test_local_artifact_load_accepts_frozen_nested_metadata(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")

    ref = store.save(
        {"ok": True},
        stage_name="stage",
        name="out",
        artifact_type="json",
        codec_key="json.v1",
        metadata={"nested": {"labels": ["raw", "processed"]}},
    )

    assert store.load(ref, expected_type="json") == {"ok": True}
    assert ref.to_dict()["metadata"] == {"nested": {"labels": ["raw", "processed"]}}


def test_local_artifact_load_requires_codec(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    artifact_path = tmp_path / "run" / "stage" / "out.txt"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("hello")
    registered = store.register(
        artifact_path,
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
            stage_name="stage",
            name="out",
            artifact_type="text",
            codec_key=None,
        )

    registered = store.register(
        external,
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
        stage_name="stage",
        name="dir",
        artifact_type="tree",
        codec_key="json.v1",
    )

    with pytest.raises(ArtifactTypeMismatchError):
        store.load(registered)


def test_large_native_checkpoint_validation_streams_and_detects_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    source = tmp_path / "run" / "fit" / "selected_checkpoint.ckpt"
    source.parent.mkdir(parents=True)
    block = bytes(range(256)) * 4096
    expected = hashlib.sha256()
    with source.open("wb") as output:
        for _ in range(128):
            output.write(block)
            expected.update(block)
    ref = store.register(
        source, stage_name="fit", name="selected_checkpoint", artifact_type="checkpoint"
    )
    assert not ref.metadata
    assert ref.checksum == f"sha256:{expected.hexdigest()}"

    original_open = Path.open
    original_read_bytes = Path.read_bytes
    read_lengths: list[int] = []

    class ObservedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size=-1):
            assert 0 < size <= 64 * 1024
            chunk = self.stream.read(size)
            read_lengths.append(len(chunk))
            return chunk

    def observed_open(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        return ObservedReader(stream) if path == source and mode == "rb" else stream

    def no_whole_checkpoint_read(path):
        if path == source:
            raise AssertionError("native validation must not load the whole checkpoint")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "open", observed_open)
    monkeypatch.setattr(Path, "read_bytes", no_whole_checkpoint_read)
    assert store.validate(ref, expected_type="checkpoint") is None
    assert store.verify_checksum(ref) is True
    assert sum(read_lengths) == 2 * 128 * 1024 * 1024
    assert max(read_lengths) == 64 * 1024

    with source.open("r+b") as output:
        output.write(b"changed!")
    assert source.stat().st_size == 128 * 1024 * 1024
    with pytest.raises(ArtifactChecksumMismatchError, match="Checksum mismatch"):
        store.validate(ref)
    with source.open("ab") as output:
        output.write(b"extra")
    with pytest.raises(ArtifactChecksumMismatchError, match="Checksum mismatch"):
        store.verify_checksum(ref)


def test_checksum_validation_preserves_absent_and_non_file_errors(
    tmp_path: Path,
) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    ref = store.save(
        b"checkpoint",
        stage_name="fit",
        name="checkpoint",
        artifact_type="checkpoint",
        codec_key="bytes.v1",
    )
    path = store.local_path(ref)
    assert store.verify_checksum(replace(ref, checksum=None)) is False
    path.unlink()
    with pytest.raises(ArtifactNotFoundError, match="Artifact file does not exist"):
        store.validate(ref)
    with pytest.raises(ArtifactNotFoundError, match="Artifact file does not exist"):
        store.verify_checksum(ref)
    path.mkdir()
    with pytest.raises(ArtifactChecksumUnsupportedError, match="directory artifact"):
        store.validate(ref)
    with pytest.raises(ArtifactChecksumUnsupportedError, match="non-regular"):
        store.verify_checksum(ref)


def test_local_artifact_type_mismatch_raises(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "run")
    ref = store.save(
        "hello",
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
            stage_name="stage",
            name="out",
            artifact_type="text",
        )


def test_local_run_artifact_store_wraps_run_materialization(tmp_path: Path) -> None:
    local_store = LocalRunStore(root=tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    local_store.create_run(run_uri)
    store = LocalRunArtifactStore(local_store=local_store)

    store.write_config_snapshot(run_uri, "resolved", "a: 1\n")
    store.write_composition_manifest(run_uri, {"schema_version": 1})
    store.write_recipe_manifest(run_uri, ({"name": "recipe"},))
    store.write_runtime_metadata(run_uri, {"executor": "local"})
    store.write_provenance_document(run_uri, "environment", {"python": "3.12"})

    assert store.artifact_store_kind() == "run_artifacts"
    assert store.resolve_run_uri(run_uri) == run_uri
    assert (
        store.local_artifact_root(run_uri) == tmp_path / "runs" / "run1" / "artifacts"
    )
    assert (
        store.local_generated_artifact_path(
            run_uri,
            "generated/manifest.json",
        )
        == tmp_path / "runs" / "run1" / "generated" / "manifest.json"
    )
    assert store.read_config_snapshot(run_uri, "resolved") == "a: 1\n"
    assert store.read_composition_manifest(run_uri) == {"schema_version": 1}
    assert store.read_recipe_manifest(run_uri) == ({"name": "recipe"},)
    assert store.read_runtime_metadata(run_uri) == {"executor": "local"}
    assert store.read_provenance_document(run_uri, "environment") == {"python": "3.12"}
    assert not hasattr(store, "write_run_status")
    assert not hasattr(store, "write_submitted_operation")


def test_local_stage_artifact_store_wraps_stage_materialization(tmp_path: Path) -> None:
    local_store = LocalRunStore(root=tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run1")
    local_store.create_run(run_uri)
    stage = LocalRunArtifactStore(local_store=local_store).stage_artifacts(
        run_uri,
        "build",
    )

    stage.prepare_stage_workspace()
    stage.write_stage_log("stdout", "hello")
    stage.write_stage_worker_request({"stage": "build"}, attempt=1)
    stage.write_stage_worker_result({"status": "ok"}, attempt=1)
    stage.write_stage_provenance({"tool": "pytest"}, attempt=1)

    assert stage.artifact_store_kind() == "stage_artifacts"
    assert stage.local_stage_artifact_dir() == (
        tmp_path / "runs" / "run1" / "artifacts" / "build"
    )
    assert stage.local_stage_workspace_dir().is_dir()
    assert stage.local_stage_log_path("stdout").name == "stdout.log"
    assert stage.read_stage_log("stdout") == "hello"
    assert stage.read_stage_worker_request(attempt=1) == {"stage": "build"}
    assert stage.read_stage_worker_result(attempt=1) == {"status": "ok"}
    assert stage.read_stage_provenance() == {"tool": "pytest"}
    assert not hasattr(stage, "write_stage_status")
    assert not hasattr(stage, "record_output_commit")
