"""Unit tests for atomic filesystem helpers."""

from pathlib import Path

import pytest

from loom.pipeline.stores import atomic_write_bytes, atomic_write_json, atomic_write_text, ensure_dir, replace_file, unique_temp_path
from loom.pipeline.stores.atomic import AtomicWriteError, unique_temp_path as atomic_unique_temp_path


def test_ensure_dir_is_idempotent(tmp_path: Path) -> None:
    dir_path = tmp_path / "a" / "b"
    ensure_dir(dir_path)
    ensure_dir(dir_path)
    assert dir_path.exists()
    assert dir_path.is_dir()


def test_atomic_write_text_writes_expected_content(tmp_path: Path) -> None:
    path = tmp_path / "text.txt"
    atomic_write_text(path, "hello")
    assert path.read_text(encoding="utf-8") == "hello"


def test_atomic_write_bytes_writes_expected_content(tmp_path: Path) -> None:
    path = tmp_path / "bytes.bin"
    atomic_write_bytes(path, b"bytes")
    assert path.read_bytes() == b"bytes"


def test_atomic_write_json_is_deterministic_and_pretty(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    atomic_write_json(path, {"b": 2, "a": 1})
    expected = '{\n  "a": 1,\n  "b": 2\n}\n'
    assert path.read_text(encoding="utf-8") == expected


def test_replace_file_updates_target(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("old")
    replace_file(source, target)
    assert target.read_text(encoding="utf-8") == "old"


def test_replace_file_fsyncs_parent_directory(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("new")
    synced_paths: list[Path] = []

    monkeypatch.setattr("loom.pipeline.stores.atomic._fsync_path", synced_paths.append)

    replace_file(source, target)

    assert target.read_text(encoding="utf-8") == "new"
    assert synced_paths == [target.parent]


def test_unique_temp_path_is_within_target_directory(tmp_path: Path) -> None:
    path = tmp_path / "run" / "value.json"
    candidate = unique_temp_path(path)
    assert candidate.parent == path.parent


def test_unique_temp_path_does_not_overlap(tmp_path: Path) -> None:
    path = tmp_path / "same"
    first = unique_temp_path(path)
    first.touch()
    second = atomic_unique_temp_path(path)
    assert first != second
    assert second.name.startswith(f".{path.name}.tmp.")


def test_atomic_write_bytes_cleans_temp_on_failure(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "value.bin"
    temp = tmp_path / ".value.bin.tmp"
    monkeypatch.setattr(
        "loom.pipeline.stores.atomic.unique_temp_path",
        lambda _path: temp,
    )

    def _fail_replace(*_args: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("loom.pipeline.stores.atomic.replace_file", _fail_replace)

    with pytest.raises(AtomicWriteError):
        atomic_write_bytes(target, b"abc")
    assert not temp.exists()
