"""Unit tests for config source loading."""

from pathlib import Path
from typing import Literal

import pytest
import yaml

from weave.digests import hash_bytes
from weave.errors import ConfigLoadError
from weave.load import load_config


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
    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="overlay", order=1)
    assert exc.value.context is not None
    assert exc.value.context.code == "non_mapping_root"


def test_load_rejects_non_string_keys(tmp_path: Path) -> None:
    source_path = tmp_path / "bad.yaml"
    source_path.write_text("1: one\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="base", order=0)
    assert exc.value.context is not None
    assert exc.value.context.code == "non_plain_data"
    assert exc.value.context.config_path == "$"


@pytest.mark.parametrize(
    ("kind", "order"),
    [
        ("base", 0),
        ("overlay", 1),
    ],
)
def test_load_rejects_duplicate_yaml_keys_with_structured_context(
    tmp_path: Path,
    kind: Literal["base", "overlay"],
    order: int,
) -> None:
    source_path = tmp_path / f"{kind}.yaml"
    source_path.write_text("name: first\nname: second\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind=kind, order=order)

    context = exc.value.context
    assert context is not None
    assert context.code == "duplicate_key"
    assert context.source_kind == kind
    assert context.source_order == order
    assert context.source_path == str(source_path.resolve())
    assert context.config_path == "$.name"
    assert context.expected == "unique YAML mapping keys"
    assert context.actual == "name"
    assert context.details == {"key": "name"}


def test_load_rejects_nested_duplicate_yaml_keys_with_config_path(tmp_path: Path) -> None:
    source_path = tmp_path / "nested.yaml"
    source_path.write_text(
        "model:\n"
        "  layer: first\n"
        "  layer: second\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="base", order=0)

    context = exc.value.context
    assert context is not None
    assert context.code == "duplicate_key"
    assert context.config_path == "$.model.layer"
    assert context.details == {"key": "layer"}


def test_load_rejects_duplicate_yaml_keys_inside_sequences_with_config_path(tmp_path: Path) -> None:
    source_path = tmp_path / "sequence.yaml"
    source_path.write_text(
        "items:\n"
        "  - name: first\n"
        "    name: second\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="base", order=0)

    context = exc.value.context
    assert context is not None
    assert context.code == "duplicate_key"
    assert context.config_path == "$.items[0].name"
    assert context.details == {"key": "name"}


def test_duplicate_key_rejection_does_not_mutate_pyyaml_safe_loader(tmp_path: Path) -> None:
    source_path = tmp_path / "duplicate.yaml"
    source_path.write_text("name: first\nname: second\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError):
        load_config(source_path, kind="base", order=0)

    assert yaml.safe_load("name: first\nname: second\n") == {"name": "second"}


def test_load_rejects_recursive_yaml_aliases_with_structured_context(tmp_path: Path) -> None:
    source_path = tmp_path / "recursive.yaml"
    source_path.write_text(
        "root: &root\n"
        "  child: *root\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="base", order=0)

    assert exc.value.context is not None
    assert exc.value.context.code == "non_plain_data"
    assert exc.value.context.config_path == "$.root.child"
    assert exc.value.context.expected == "acyclic plain YAML value"
    assert exc.value.context.actual == "recursive alias"
    assert exc.value.context.details == {"referenced_path": "$.root"}


def test_load_rejects_multiple_yaml_documents(tmp_path: Path) -> None:
    source_path = tmp_path / "multi.yaml"
    source_path.write_text("a: 1\n---\nb: 2\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="base", order=0)
    assert exc.value.context is not None
    assert exc.value.context.code == "multi_document_yaml"
    assert exc.value.context.expected == 1
    assert exc.value.context.actual == 2


def test_load_rejects_empty_mapping_root(tmp_path: Path) -> None:
    source_path = tmp_path / "empty.yaml"
    source_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="base", order=0)
    assert exc.value.context is not None
    assert exc.value.context.code == "empty_root"


def test_load_rejects_invalid_utf8(tmp_path: Path) -> None:
    source_path = tmp_path / "bad.bin"
    source_path.write_bytes(b"\xff")
    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="base", order=0)
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_utf8"


def test_load_rejects_unsafe_yaml_tags(tmp_path: Path) -> None:
    source_path = tmp_path / "unsafe.yaml"
    source_path.write_text("value: !!python/object/apply:os.system [\"echo hi\"]\n", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind="base", order=0)
    assert exc.value.context is not None
    assert exc.value.context.code in {"non_plain_data", "invalid_yaml"}


def test_load_rejects_copy_directive_at_root_and_nested_paths(tmp_path: Path) -> None:
    cases = {
        "root": "_copy_: true\nname: root\n",
        "nested": "model:\n  layer:\n    _copy_: true\n",
        "list": "pipelines:\n  - stage: train\n    _copy_: true\n",
    }
    for path_label, content in cases.items():
        source_path = tmp_path / f"copy_{path_label}.yaml"
        source_path.write_text(content, encoding="utf-8")
        with pytest.raises(ConfigLoadError) as exc:
            load_config(source_path, kind="base", order=0)
        assert exc.value.context is not None
        assert exc.value.context.code == "unsupported_directive"
        assert exc.value.context.directive == "_copy_"


@pytest.mark.parametrize(
    ("kind",),
    [
        ("base",),
        ("overlay",),
    ],
)
def test_load_rejects_schema_authoring_directive(
    tmp_path: Path,
    kind: Literal["base", "overlay"],
) -> None:
    source_path = tmp_path / f"{kind}.yaml"
    source_path.write_text("name: base\n_schema_: {}\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as exc:
        load_config(source_path, kind=kind, order=0)

    assert exc.value.context is not None
    assert exc.value.context.code == "unsupported_directive"
    assert exc.value.context.directive == "_schema_"
    assert exc.value.context.config_path == "$._schema_"
    assert exc.value.context.source_kind == kind
    assert exc.value.context.actual == "_schema_"
    assert "raw source" not in str(exc.value.context.expected)
