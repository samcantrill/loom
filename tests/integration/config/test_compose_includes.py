"""Integration checks for file-authored config include composition."""

from pathlib import Path
from typing import cast

import pytest

from weave import compose_config
from weave.errors import ConfigIncludeExpansionError, ConfigIncludeResolutionError, ConfigLoadError
from loom.serialization import PlainData


def _model_mapping(config: dict[str, PlainData]) -> dict[str, PlainData]:
    pipeline = config["pipeline"]
    assert isinstance(pipeline, dict)
    model = pipeline["model"]
    assert isinstance(model, dict)
    return cast(dict[str, PlainData], model)


def _assert_no_replace_markers(value: PlainData) -> None:
    if isinstance(value, dict):
        assert "_replace_" not in value
        for child in value.values():
            _assert_no_replace_markers(child)
        return

    if isinstance(value, list):
        for child in value:
            _assert_no_replace_markers(child)


def test_public_compose_includes_base_and_overlay_after_source_aware_merge(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    (include_dir / "model-base.yaml").write_text("source: base\n", encoding="utf-8")

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/model-base.yaml\n"
        "    local: from-base\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "pipeline:\n"
        "  model:\n"
        "    local: from-overlay\n"
        "    overlay_only: 'yes'\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overlays=(overlay,))
    model = _model_mapping(composed.resolved)
    assert model == {
        "source": "base",
        "local": "from-overlay",
        "overlay_only": "yes",
    }
    _assert_no_replace_markers(composed.resolved)


def test_public_compose_includes_nested_include_relative_to_including_file(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    (include_dir / "root.yaml").write_text(
        "outer:\n"
        "  _include_: nested\n"
        "base_key: root\n",
        encoding="utf-8",
    )
    nested_dir = include_dir / "outer"
    nested_dir.mkdir()
    (nested_dir / "nested.yaml").write_text("inner: 'yes'\n", encoding="utf-8")

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/root.yaml\n"
        "    local: local\n",
        encoding="utf-8",
    )

    composed = compose_config(base)
    model = _model_mapping(composed.resolved)
    assert model == {
        "outer": {"inner": "yes"},
        "base_key": "root",
        "local": "local",
    }


def test_public_compose_nested_include_resolution_error_records_active_stack(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    (include_dir / "root.yaml").write_text(
        "outer:\n"
        "  _include_: ./missing.yaml\n",
        encoding="utf-8",
    )
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./include/root.yaml\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "target_not_found"
    assert context.remediation is not None
    assert context.details is not None
    stack = cast(list[dict[str, object]], context.details["active_include_stack"])
    assert isinstance(stack, list)
    assert len(stack) == 1
    assert stack[0]["include_site_path"] == ["pipeline", "model", "_include_"]


def test_public_compose_includes_requires_same_site_replace_for_mapping_swap(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    included = tmp_path / "model.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    existing: base\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./model.yaml\n",
        encoding="utf-8",
    )
    included.write_text("from_include: value\n", encoding="utf-8")

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        compose_config(base, overlays=(overlay,))
    assert exc.value.context is not None
    assert exc.value.context.code == "missing_required_replace_for_include"


def test_public_compose_includes_with_same_site_replace_stays_enabled(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    included = tmp_path / "model.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    existing: base\n",
        encoding="utf-8",
    )
    overlay.write_text(
        "pipeline:\n"
        "  model:\n"
        "    _replace_: true\n"
        "    _include_: ./model.yaml\n"
        "    override: overlay\n",
        encoding="utf-8",
    )
    included.write_text(
        "override: include\n"
        "base_only: keep\n",
        encoding="utf-8",
    )

    composed = compose_config(base, overlays=(overlay,))
    model = _model_mapping(composed.resolved)
    assert model == {
        "override": "overlay",
        "base_only": "keep",
    }
    _assert_no_replace_markers(composed.resolved)


def test_public_compose_rejects_replace_marker_authored_inside_included_file(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    included = tmp_path / "included.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: ./included.yaml\n",
        encoding="utf-8",
    )
    included.write_text("_replace_: true\nstage: included\n", encoding="utf-8")

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_included_replace_marker"
    assert context.source_path == str(included)
    assert context.config_path == "$.pipeline.model._replace_"
    assert context.directive == "_replace_"


def test_public_compose_user_overrides_apply_after_file_include_expansion(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: included.yaml\n"
        "    local: base\n",
        encoding="utf-8",
    )
    (tmp_path / "included.yaml").write_text("source: included\n", encoding="utf-8")

    composed = compose_config(
        base,
        overrides=("pipeline.model.local=override", "+pipeline.model.extra=added"),
    )

    model = _model_mapping(composed.resolved)
    assert model["local"] == "override"
    assert model["extra"] == "added"
    assert model["source"] == "included"


def test_public_compose_rejects_schema_directive_in_included_file(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    included = tmp_path / "included.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: included.yaml\n",
        encoding="utf-8",
    )
    included.write_text(
        "source: included\n"
        "_schema_: {}\n"
        "stage: model\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_directive"
    assert context.source_kind == "overlay"
    assert context.config_path == "$._schema_"
    assert context.directive == "_schema_"
    assert context.expected == "schema declarations from authored files"
    assert context.source_path == str(included.resolve())


def test_public_compose_rejects_copy_directive_in_included_file(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    included = tmp_path / "included.yaml"

    base.write_text(
        "name: base\n"
        "pipeline:\n"
        "  model:\n"
        "    _include_: included.yaml\n",
        encoding="utf-8",
    )
    included.write_text(
        "source: included\n"
        "_copy_: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigLoadError) as exc:
        compose_config(base)

    context = exc.value.context
    assert context is not None
    assert context.code == "unsupported_directive"
    assert context.source_kind == "overlay"
    assert context.config_path == "$._copy_"
    assert context.directive == "_copy_"
    assert context.source_path == str(included.resolve())
