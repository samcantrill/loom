"""Focused archive capture and extraction contracts for staged preparation."""

from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
import shutil
import tarfile

import pytest

from loom.io.uris import path_to_file_uri, uri_to_path
from loom.queue import preparation as inputs
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.errors import QueueServiceError
from loom.queue.preparation import (
    PreparationChildInput,
    PreparationSource,
    PrepareRunRequest,
    StagedInputReceipt,
    capture_staged_input,
    discard_staged_input_temporaries,
    input_receipt_from_dict,
    resolve_staged_input,
)
from loom.serialization import freeze_plain_data


def _request() -> PrepareRunRequest:
    return PrepareRunRequest(
        "prepare-staged-001",
        "staged-001",
        PreparationSource("staged", "projects", "example-project", ("configs",)),
        "configs/experiment.yaml",
        "example-cpu",
    )


def _source(tmp_path: Path, *, content: bytes = b"pipeline: {}\n") -> Path:
    root = tmp_path / "projects"
    config = root / "example-project" / "configs" / "experiment.yaml"
    config.parent.mkdir(parents=True)
    config.write_bytes(content)
    return root


def _receipt(
    tmp_path: Path, *, content: bytes = b"pipeline: {}\n"
) -> StagedInputReceipt:
    return capture_staged_input(
        _request(),
        source_root=_source(tmp_path, content=content),
        artifact_root=tmp_path / "artifacts",
        owner_id="coordinator-a",
    )


def _replace_archive(receipt: StagedInputReceipt, archive: Path) -> StagedInputReceipt:
    return replace(
        receipt,
        reference=replace(
            receipt.reference,
            uri=path_to_file_uri(archive),
            checksum=inputs._file_checksum(archive),
        ),
    )


def test_staged_capture_commits_a_native_receipt_and_child_union(
    tmp_path: Path,
) -> None:
    receipt = _receipt(tmp_path)
    archive = uri_to_path(receipt.reference.uri)
    assert archive.is_file()
    assert receipt.reference.artifact_type == "bytes"
    assert receipt.reference.codec_key == "bytes.v1"
    assert receipt.reference.checksum == inputs._file_checksum(archive)
    assert input_receipt_from_dict(receipt.to_dict()) == receipt

    binding = PreparationChildInput(
        "prepare-staged-001",
        "example-cpu",
        "configs/experiment.yaml",
        receipt,
        ResidentProfileDescriptor(
            "local", "v1", "project", "env", "executor"
        ).to_dict(),
    )
    assert PreparationChildInput.from_dict(binding.to_dict()) == binding
    assert (
        PreparationChildInput.from_dict(freeze_plain_data(binding.to_dict())) == binding
    )


def test_staged_capture_rejects_archive_padding_above_transfer_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _source(tmp_path, content=b"x")
    artifact_root = tmp_path / "artifacts"
    # A tar has fixed block padding, so its transport size can exceed its selected
    # content size without needing a large fixture.
    monkeypatch.setattr(inputs, "_MAX_BYTES", 4096)
    with pytest.raises(QueueServiceError, match="input_limit_exceeded"):
        capture_staged_input(
            _request(),
            source_root=root,
            artifact_root=artifact_root,
            owner_id="coordinator-a",
        )
    assert not tuple(artifact_root.iterdir())


def test_staged_capture_replay_rejects_existing_oversized_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _receipt(tmp_path, content=b"x")
    root = tmp_path / "projects"
    artifact_root = tmp_path / "artifacts"
    archive = uri_to_path(receipt.reference.uri)
    monkeypatch.setattr(inputs, "_MAX_BYTES", 4096)
    with pytest.raises(QueueServiceError, match="input_limit_exceeded"):
        capture_staged_input(
            _request(),
            source_root=root,
            artifact_root=artifact_root,
            owner_id="coordinator-a",
        )
    assert tuple(artifact_root.iterdir()) == (archive,)


def test_staged_capture_detects_source_change_before_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _source(tmp_path)
    config = root / "example-project" / "configs" / "experiment.yaml"
    write_archive = inputs._write_staged_archive

    def change_after_archive(path: Path, manifest: object, contents: object) -> None:
        write_archive(path, manifest, contents)  # type: ignore[arg-type]
        config.write_text("changed", encoding="utf-8")

    monkeypatch.setattr(inputs, "_write_staged_archive", change_after_archive)
    with pytest.raises(QueueServiceError, match="source_changed"):
        capture_staged_input(
            _request(),
            source_root=root,
            artifact_root=tmp_path / "artifacts",
            owner_id="coordinator-a",
        )
    assert not tuple((tmp_path / "artifacts").iterdir())


def test_staged_capture_cleanup_is_limited_to_the_operation_owner(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    request = _request()
    for owner, suffix in (("coordinator-a", "a"), ("coordinator-b", "b")):
        key = inputs._capture_operation_key(request.operation_id, owner)
        (artifact_root / f".{key}.tmp-{'1' * 32}.tar").write_text(suffix)

    discard_staged_input_temporaries(
        request, artifact_root=artifact_root, owner_id="coordinator-a"
    )
    other_key = inputs._capture_operation_key(request.operation_id, "coordinator-b")
    assert {path.name for path in artifact_root.iterdir()} == {
        f".{other_key}.tmp-{'1' * 32}.tar"
    }


def test_staged_extraction_is_verified_and_replay_does_not_mutate(
    tmp_path: Path,
) -> None:
    receipt = _receipt(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    name = "preparation-input-" + receipt.manifest_digest.removeprefix("sha256:")
    stale = workspace / f".{name}.tmp-{'a' * 32}"
    stale.mkdir()
    (stale / "partial").write_text("partial")

    resolved = resolve_staged_input(
        receipt,
        archive_path=uri_to_path(receipt.reference.uri),
        workspace_root=workspace,
    )
    assert resolved == workspace / name / "files"
    captured = resolved / "configs" / "experiment.yaml"
    before = (captured.read_bytes(), captured.stat().st_mtime_ns)
    assert not stale.exists()
    assert (
        resolve_staged_input(
            receipt,
            archive_path=uri_to_path(receipt.reference.uri),
            workspace_root=workspace,
        )
        == resolved
    )
    assert (captured.read_bytes(), captured.stat().st_mtime_ns) == before


@pytest.mark.parametrize(
    ("kind", "message"),
    (
        ("traversal", "unsafe destination"),
        ("duplicate", "duplicate destination"),
        ("link", "unsupported member"),
        ("fifo", "unsupported member"),
    ),
)
def test_staged_extraction_rejects_unsafe_archive_members(
    tmp_path: Path, kind: str, message: str
) -> None:
    receipt = _receipt(tmp_path)
    archive = tmp_path / f"{kind}.tar"
    shutil.copyfile(uri_to_path(receipt.reference.uri), archive)
    with tarfile.open(archive, "a") as output:
        if kind == "traversal":
            member = tarfile.TarInfo("files/../../escape")
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
        elif kind == "duplicate":
            member = tarfile.TarInfo("files/configs/experiment.yaml")
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
        else:
            member = tarfile.TarInfo("files/unsafe")
            member.type = tarfile.SYMTYPE if kind == "link" else tarfile.FIFOTYPE
            member.linkname = "target"
            output.addfile(member)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(QueueServiceError, match=message):
        resolve_staged_input(
            _replace_archive(receipt, archive),
            archive_path=archive,
            workspace_root=workspace,
        )
    assert not tuple(workspace.iterdir())


@pytest.mark.parametrize(("limit", "content"), (("bytes", b"x" * 250),))
def test_staged_extraction_applies_expanded_size_limit_before_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
    content: bytes,
) -> None:
    del limit
    receipt = _receipt(tmp_path, content=content)
    monkeypatch.setattr(inputs, "_MAX_BYTES", 200)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(QueueServiceError, match="input_limit_exceeded"):
        resolve_staged_input(
            receipt,
            archive_path=uri_to_path(receipt.reference.uri),
            workspace_root=workspace,
        )
    assert not tuple(workspace.iterdir())


def test_staged_extraction_rejects_checksum_mismatch_without_partial_files(
    tmp_path: Path,
) -> None:
    receipt = _receipt(tmp_path)
    archive = uri_to_path(receipt.reference.uri)
    with archive.open("ab") as stream:
        stream.write(b"changed")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(QueueServiceError, match="checksum"):
        resolve_staged_input(receipt, archive_path=archive, workspace_root=workspace)
    assert not tuple(workspace.iterdir())


def test_staged_extraction_verifies_manifest_content_identity(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    original = uri_to_path(receipt.reference.uri)
    archive = tmp_path / "wrong-content.tar"
    with tarfile.open(original, "r:") as source, tarfile.open(archive, "w") as output:
        for member in source.getmembers():
            payload = source.extractfile(member)
            assert payload is not None
            with payload:
                data = payload.read()
            if member.name == "files/configs/experiment.yaml":
                data = b"different"
                member.size = len(data)
            output.addfile(member, io.BytesIO(data))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(QueueServiceError, match="capture is invalid"):
        resolve_staged_input(
            _replace_archive(receipt, archive),
            archive_path=archive,
            workspace_root=workspace,
        )
    assert not tuple(workspace.iterdir())
