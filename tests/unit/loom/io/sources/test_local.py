"""Unit tests for local filesystem sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from loom.io.sources import (
    LocalFileSystemSource,
    SourceNotFoundError,
    UnsupportedSourceOperationError,
)


def test_local_source_supports_paths_and_file_uris(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    assert source.supports("relative.txt")
    assert source.supports(str(tmp_path / "absolute.txt"))
    assert source.supports("file:///tmp/abc.txt")
    assert not source.supports("https://example.com/data")
    assert not source.supports("file://server/share/file.txt")
    assert not source.supports("file:///tmp/file.txt?download=1")


def test_local_source_resolve_applies_root_for_relative_path(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    resolved = source.resolve("relative/data.json")
    assert resolved == (tmp_path / "relative" / "data.json").resolve()


def test_local_source_resolve_without_root_depends_on_cwd(tmp_path: Path) -> None:
    source = LocalFileSystemSource()
    resolved = source.resolve("relative/data.json")
    assert isinstance(resolved, Path)
    assert resolved.is_absolute()
    assert resolved.name == "data.json"


def test_local_source_open_write_and_read(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    path = tmp_path / "text.txt"
    with source.open("text.txt", "wt", encoding="utf-8") as handle:
        handle.write("hello")
    with source.open("text.txt", "rt", encoding="utf-8") as handle:
        assert handle.read() == "hello"
    with source.open(path, "wb") as handle:
        handle.write(b"bytes")
    with source.open(path, "rb") as handle:
        assert handle.read() == b"bytes"


def test_local_source_open_missing_path_raises_not_found(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    with pytest.raises(SourceNotFoundError):
        source.open("missing.txt", "rb")


def test_local_source_open_invalid_mode_raises(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    with pytest.raises(UnsupportedSourceOperationError):
        source.open("x.bin", "r+")  # type: ignore[arg-type]


def test_local_source_exists_and_stat(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    missing = source.exists("missing.txt")
    assert missing is False
    with source.open("present.txt", "wt", encoding="utf-8") as handle:
        handle.write("ok")
    assert source.exists("present.txt")

    metadata = source.stat("present.txt")
    assert metadata["exists"] is True
    assert metadata["backend"] == "local"
    assert isinstance(metadata["size_bytes"], int)
    assert metadata["mtime"] is not None
    assert isinstance(metadata["uri"], str)

    with pytest.raises(SourceNotFoundError):
        source.stat("missing.txt")


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/data.txt",
        "file://server/share/file.txt",
        "file:///tmp/file.txt?download=1",
    ],
)
def test_local_source_exists_unsupported_uri_raises(tmp_path: Path, uri: str) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    with pytest.raises(UnsupportedSourceOperationError):
        source.exists(uri)


def test_local_source_glob_returns_sorted_file_uris(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    with source.open("b.txt", "wt", encoding="utf-8") as handle:
        handle.write("b")
    with source.open("a.txt", "wt", encoding="utf-8") as handle:
        handle.write("a")
    uris = source.glob("*.txt")
    assert len(uris) == 2
    assert uris[0].endswith("/a.txt")
    assert uris[1].endswith("/b.txt")


def test_local_source_unsupported_operation_for_pattern(tmp_path: Path) -> None:
    source = LocalFileSystemSource(root=tmp_path)
    with pytest.raises(UnsupportedSourceOperationError):
        source.glob("file://server/share/*.txt")
