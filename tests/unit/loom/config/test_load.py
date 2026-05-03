"""Unit tests for config source loading."""

from pathlib import Path

import pytest

from loom.fingerprints import hash_bytes
from loom.config.errors import ConfigLoadError
from loom.config.load import load_config


def test_load_reads_mapping_with_metadata(tmp_path: Path) -> None:
    content = "name: base\npipeline: {}\n"
    source_path = tmp_path / "base.yaml"
    source_path.write_text(content, encoding="utf-8")

    resolved, source = load_config(source_path, kind="base", order=0)

    assert resolved == {"name": "base", "pipeline": {}}
    assert source.kind == "base"
    assert source.order == 0
    assert source.path == str(source_path.resolve())
    assert source.size_bytes == len(content.encode("utf-8"))
    assert source.content_digest == hash_bytes(content.encode("utf-8"))


def test_load_rejects_empty_root_documents(tmp_path: Path) -> None:
    source_path = tmp_path / "null.yaml"
    source_path.write_text("null\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        load_config(source_path, kind="base", order=0)


def test_load_rejects_non_mapping_root(tmp_path: Path) -> None:
    source_path = tmp_path / "list.yaml"
    source_path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        load_config(source_path, kind="overlay", order=1)


def test_load_rejects_non_string_keys(tmp_path: Path) -> None:
    source_path = tmp_path / "bad.yaml"
    source_path.write_text("1: one\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        load_config(source_path, kind="base", order=0)


def test_load_rejects_invalid_utf8(tmp_path: Path) -> None:
    source_path = tmp_path / "bad.bin"
    source_path.write_bytes(b"\xff")
    with pytest.raises(ConfigLoadError):
        load_config(source_path, kind="base", order=0)


def test_load_rejects_unsafe_yaml_tags(tmp_path: Path) -> None:
    source_path = tmp_path / "unsafe.yaml"
    source_path.write_text("value: !!python/object/apply:os.system [\"echo hi\"]\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError):
        load_config(source_path, kind="base", order=0)
