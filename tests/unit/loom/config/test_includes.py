"""Unit tests for include target resolution primitives."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import pytest

from loom.config.includes import (
    ConfigIncludeExpansionError,
    ConfigIncludeResolutionError,
    IncludeResolutionResult,
    expand_config_includes,
    resolve_include_target,
)
from loom.config.source_maps import (
    ConfigPath,
    compose_config_with_sources,
)
from loom.config.provenance import ConfigSource
from loom.config.load import load_config
from loom.serialization import PlainData


def _config_source(
    path: Path, *, kind: Literal["base", "overlay"] = "base"
) -> ConfigSource:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("name: test\n", encoding="utf-8")
    return ConfigSource(
        kind=kind,
        path=str(path),
        order=0,
        content_digest="sha256:dummy",
        size_bytes=1,
    )


def test_resolve_bare_name_target_with_mapping_parent_segments(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "experiment.yaml")
    include_target = tmp_path / "model" / "resnet50.yaml"
    include_target.parent.mkdir(parents=True)
    include_target.write_text("name: base\n", encoding="utf-8")

    result = resolve_include_target(
        "resnet50",
        source=source_file,
        include_site_path=("model", "_include_"),
    )

    assert isinstance(result, IncludeResolutionResult)
    assert result.target_kind == "bare_name"
    assert result.explicit_escape is False
    assert result.resolved_path == include_target
    assert result.include_site_path == ("model", "_include_")
    assert result.source_path == str(source_file.path)


def test_resolve_nested_bare_name_target_with_dot_segment(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "project" / "config.yaml")
    include_target = tmp_path / "project" / "encoder.v1" / "small.yaml"
    include_target.parent.mkdir(parents=True)
    include_target.write_text("name: small\n", encoding="utf-8")

    result = resolve_include_target(
        "small",
        source=source_file,
        include_site_path=("encoder.v1", "_include_"),
    )

    assert result.resolved_path == include_target
    assert result.target_kind == "bare_name"
    assert result.include_site_path == ("encoder.v1", "_include_")


def test_bare_name_rejects_symlink_escape_from_derived_directory(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "configs" / "experiment.yaml")
    external_dir = tmp_path / "external-models"
    external_target = external_dir / "resnet50.yaml"
    external_dir.mkdir()
    external_target.write_text("name: escaped\n", encoding="utf-8")
    symlinked_mapping_dir = tmp_path / "configs" / "model"
    symlinked_mapping_dir.symlink_to(external_dir, target_is_directory=True)

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "resnet50",
            source=source_file,
            include_site_path=("model", "_include_"),
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "unsafe_include_target"
    assert context.config_path == "$.model._include_"
    details = context.details
    assert details is not None
    assert details["candidate_path"] == str(external_target)
    assert details["resolved_path"] == str(external_target)
    assert details["derived_dir"] == str(symlinked_mapping_dir)
    assert details["target_kind"] == "bare_name"
    assert details["explicit_escape"] is False
    assert details["reason"] == "bare_name_symlink_escape"


@pytest.mark.parametrize(
    "target, relative_path",
    [
        ("./local.yaml", "local.yaml"),
        ("../shared/optimizer.yaml", "../shared/optimizer.yaml"),
        ("components/resnet50.yaml", "components/resnet50.yaml"),
        ("resnet50.yaml", "resnet50.yaml"),
    ],
)
def test_resolve_explicit_relative_targets(
    tmp_path: Path, target: str, relative_path: str
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    explicit_file = tmp_path / relative_path
    explicit_file.parent.mkdir(parents=True, exist_ok=True)
    explicit_file.write_text("name: explicit\n", encoding="utf-8")

    result = resolve_include_target(
        target,
        source=source_file,
        include_site_path=("pipeline", "_include_"),
    )

    assert result.target_kind == "explicit_relative"
    assert result.explicit_escape is True
    assert result.resolved_path == explicit_file.resolve(strict=False)


def test_resolve_explicit_relative_target_normalizes_parent_segments(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "configs" / "base.yaml")
    explicit_file = tmp_path / "shared" / "optimizer.yaml"
    explicit_file.parent.mkdir(parents=True)
    explicit_file.write_text("name: explicit\n", encoding="utf-8")

    result = resolve_include_target(
        "../shared/optimizer.yaml",
        source=source_file,
        include_site_path=("pipeline", "_include_"),
    )

    assert result.target_kind == "explicit_relative"
    assert result.resolved_path == explicit_file
    assert ".." not in result.resolved_path.parts


def test_missing_explicit_relative_target_reports_normalized_candidate(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "configs" / "base.yaml")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "../shared/missing.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "target_not_found"
    details = context.details
    assert details is not None
    assert details["candidate_path"] == str(tmp_path / "shared" / "missing.yaml")


def test_resolve_absolute_path_target(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    absolute_target = tmp_path / "absolute.yaml"
    absolute_target.write_text("name: absolute\n", encoding="utf-8")

    result = resolve_include_target(
        str(absolute_target),
        source=source_file,
        include_site_path=("pipeline", "_include_"),
    )

    assert result.target_kind == "absolute"
    assert result.explicit_escape is True
    assert result.resolved_path == absolute_target


def test_resolve_file_uri_target(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    file_target = tmp_path / "nested" / "from uri.yaml"
    file_target.parent.mkdir(parents=True)
    file_target.write_text("name: uri\n", encoding="utf-8")

    result = resolve_include_target(
        file_target.as_uri(),
        source=source_file,
        include_site_path=("pipeline", "_include_"),
    )

    assert result.target_kind == "file_uri"
    assert result.explicit_escape is True
    assert result.resolved_path == file_target


@pytest.mark.parametrize("target", [".hidden", ".config.yaml", "..oops"])
def test_dot_prefixed_names_are_not_implicit_explicit_relative_targets(
    tmp_path: Path,
    target: str,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    dot_target = tmp_path / target
    dot_target.write_text("name: dot\n", encoding="utf-8")

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            target,
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )

    assert exc.value.context is not None
    assert exc.value.context.code == "unsupported_target_form"


def test_dot_prefixed_file_can_be_selected_with_documented_relative_indicator(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    dot_target = tmp_path / ".config.yaml"
    dot_target.write_text("name: dot\n", encoding="utf-8")

    result = resolve_include_target(
        "./.config.yaml",
        source=source_file,
        include_site_path=("pipeline", "_include_"),
    )

    assert result.target_kind == "explicit_relative"
    assert result.resolved_path == dot_target


@pytest.mark.parametrize(
    "include_site_path, code",
    [
        ((), "invalid_include_site"),
        (("model", "not_include"), "invalid_include_site"),
        (("model", 1, "_include_"), "invalid_include_site"),
        (("model", ".", "_include_"), "invalid_include_site"),
        (("model", "..", "_include_"), "invalid_include_site"),
        (("a/b", "_include_"), "invalid_include_site"),
    ],
)
def test_resolve_target_rejects_invalid_include_site(
    tmp_path: Path,
    include_site_path: tuple[object, ...],
    code: str,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "resnet50",
            source=source_file,
            include_site_path=cast(ConfigPath, include_site_path),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == code


@pytest.mark.parametrize(
    "target, expected",
    [
        ("", "invalid_target"),
        ("my config", "unsupported_target_form"),
        ("${oc.env:HOME}", "resolver_dependent"),
        ("s3://bucket/config.yaml", "unsupported_scheme"),
    ],
)
def test_resolve_target_rejects_unsupported_forms(
    tmp_path: Path, target: str, expected: str
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            target,
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == expected


def test_resolve_bare_name_target_requires_explicit_yaml_extension(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    include_site_path = ("pipeline", "_include_")

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "resnet50.yaml",
            source=source_file,
            include_site_path=include_site_path,
        )
    assert exc.value.context is not None
    assert exc.value.context.code in {"target_not_found", "target_not_file"}


def test_resolve_target_requires_exact_file_for_explicit_relative(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    base_dir = tmp_path
    missing = base_dir / "components" / "missing.yaml"
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "components/missing.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    context = exc.value.context
    assert context is not None
    assert context.code == "target_not_found"
    details = context.details
    assert details is not None
    assert details["candidate_path"] == str(missing)


def test_resolve_target_rejects_file_uri_host_query_fragment_and_malformed_escape(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "file://localhost/tmp/included.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "file:///tmp/target.yaml?download=1",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "file:///tmp/target.yaml#latest",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "file:///tmp/%zz.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "file:///tmp/a%2Fb.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == "invalid_file_uri"

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "file:///tmp/%ff.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_file_uri"
    details = context.details
    assert details is not None
    assert details["reason"] == "invalid_utf8_percent_escape"


def test_resolve_target_rejects_ambiguous_single_slash_file_uri(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "file:/tmp/included.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_file_uri"
    details = context.details
    assert details is not None
    assert details["reason"] == "ambiguous_file_uri_form"


def test_file_uri_rejects_decoded_nul_path_with_structured_error(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "file:///tmp/a%00.yaml",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_file_uri"
    assert context.config_path == "$.pipeline._include_"
    details = context.details
    assert details is not None
    assert details["reason"] == "embedded_nul_byte"
    assert details["path"] == "/tmp/a%00.yaml"
    assert details["authored_target"] == "file:///tmp/a%00.yaml"


def test_resolve_target_rejects_file_uri_path_as_directory(tmp_path: Path) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    target_dir = tmp_path / "directory"
    target_dir.mkdir()

    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            target_dir.as_uri() + "/",
            source=source_file,
            include_site_path=("pipeline", "_include_"),
        )
    assert exc.value.context is not None
    assert exc.value.context.code == "target_not_file"


def test_resolution_error_context_carries_candidate_and_target_kind(
    tmp_path: Path,
) -> None:
    source_file = _config_source(tmp_path / "base.yaml")
    include_site_path = ("pipeline", "_include_")
    with pytest.raises(ConfigIncludeResolutionError) as exc:
        resolve_include_target(
            "missing",
            source=source_file,
            include_site_path=include_site_path,
        )
    context = exc.value.context
    assert context is not None
    assert context.code == "target_not_found"
    assert context.config_path == "$.pipeline._include_"
    assert context.details is not None
    assert context.details["candidate_path"] == str(
        tmp_path / "pipeline" / "missing.yaml"
    )
    assert context.details["target_kind"] == "bare_name"
    assert context.details["explicit_escape"] is False


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _nested_mapping(config: dict[str, PlainData], *path: str) -> dict[str, PlainData]:
    value: PlainData = config
    for segment in path:
        assert isinstance(value, dict)
        value = value[segment]
    assert isinstance(value, dict)
    return cast(dict[str, PlainData], value)


def test_expand_config_includes_recursively_expands_nested_includes(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "base.yaml"
    include_dir = tmp_path / "includes"
    include_dir.mkdir()
    root_include = include_dir / "model.yaml"
    nested_include = include_dir / "nested.yaml"

    _write_yaml(
        base_path,
        (
            "pipeline:\n"
            "  model:\n"
            "    _include_: ./includes/model.yaml\n"
            "    from_included: from-base\n"
            "    unique: add-only\n"
        ),
    )
    _write_yaml(
        root_include,
        (
            "from_included: from-file\n"
            "nested:\n"
            "  _include_: ./nested.yaml\n"
        ),
    )
    _write_yaml(nested_include, "value: 7\n")

    base_config, base_source = load_config(base_path, kind="base", order=0)
    merged = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=(),
    )
    expanded = expand_config_includes(
        merged.config,
        source_map=merged.source_map,
        replacement_sites=merged.replacement_sites,
        mapping_sites=merged.mapping_sites,
    )

    model = _nested_mapping(expanded.config, "pipeline", "model")
    assert model == {
        "from_included": "from-base",
        "unique": "add-only",
        "nested": {"value": 7},
    }
    assert "_include_" not in model

    include_sites = [record.to_dict() for record in expanded.include_sites]
    assert len(include_sites) == 2
    assert include_sites[0]["include_site_path"] == [
        "pipeline",
        "model",
        "_include_",
    ]
    assert include_sites[0]["authored_target"] == "./includes/model.yaml"
    assert include_sites[1]["include_site_path"] == [
        "pipeline",
        "model",
        "nested",
        "_include_",
    ]
    assert include_sites[1]["explicit_escape"] is True

    local_customizations = [record.to_dict() for record in expanded.local_customizations]
    assert len(local_customizations) == 2
    assert local_customizations[0]["sibling_path"] == ["pipeline", "model", "from_included"]
    assert local_customizations[0]["kind"] == "override"
    assert local_customizations[1]["sibling_path"] == ["pipeline", "model", "unique"]
    assert local_customizations[1]["kind"] == "add"
    assert local_customizations[1]["source_path"] == str(base_path)


def test_expand_config_includes_resolves_nested_bare_include_from_included_file_path(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "base.yaml"
    include_dir = tmp_path / "includes"
    leaf_dir = include_dir / "component"
    leaf_dir.mkdir(parents=True)
    root_include = include_dir / "root.yaml"
    leaf_include = leaf_dir / "leaf.yaml"

    _write_yaml(
        base_path,
        "pipeline:\n  model:\n    _include_: ./includes/root.yaml\n",
    )
    _write_yaml(
        root_include,
        "component:\n  _include_: leaf\n",
    )
    _write_yaml(leaf_include, "value: from-leaf\n")

    base_config, base_source = load_config(base_path, kind="base", order=0)
    merged = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=(),
    )

    expanded = expand_config_includes(
        merged.config,
        source_map=merged.source_map,
        replacement_sites=merged.replacement_sites,
        mapping_sites=merged.mapping_sites,
    )

    assert _nested_mapping(expanded.config, "pipeline", "model") == {
        "component": {"value": "from-leaf"},
    }
    include_sites = [record.to_dict() for record in expanded.include_sites]
    assert include_sites[1]["include_site_path"] == [
        "pipeline",
        "model",
        "component",
        "_include_",
    ]
    assert include_sites[1]["target_kind"] == "bare_name"
    assert include_sites[1]["resolved_path"] == str(leaf_include)


def test_expand_config_includes_detects_cycles_by_resolved_path(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "base.yaml"
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    include_a = include_dir / "a.yaml"
    include_b = include_dir / "b.yaml"

    _write_yaml(
        base_path,
        "pipeline:\n  model:\n    _include_: ./include/a.yaml\n",
    )
    _write_yaml(include_a, "bridge:\n  _include_: ./b.yaml\n")
    _write_yaml(include_b, "bridge:\n  _include_: ./a.yaml\n")

    base_config, base_source = load_config(base_path, kind="base", order=0)
    merged = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=(),
    )

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        expand_config_includes(
            merged.config,
            source_map=merged.source_map,
            replacement_sites=merged.replacement_sites,
            mapping_sites=merged.mapping_sites,
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "include_cycle"
    assert context.source_path == str(include_b)
    assert context.source_kind == "overlay"
    assert context.source_order == 0
    assert context.config_path == "$.pipeline.model.bridge.bridge._include_"
    details = context.details
    assert details is not None
    assert details["reason"] == "include_cycle"
    include_stack = details["include_stack"]
    assert isinstance(include_stack, list)
    assert len(include_stack) >= 2
    repeated_frame = include_stack[0]
    assert isinstance(repeated_frame, dict)
    assert repeated_frame["resolved_path"] == str(include_a)
    assert repeated_frame["source_path"] == str(base_path)
    assert repeated_frame["source_kind"] == "base"
    assert repeated_frame["source_order"] == 0
    attempted_site = ["pipeline", "model", "bridge", "bridge", "_include_"]
    assert details["attempted_include_site_path"] == attempted_site
    assert details["attempted_target"] == str(include_a)


def test_expand_config_includes_rejects_non_string_value(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    _write_yaml(base_path, "pipeline:\n  model:\n    _include_: 1\n")

    base_source = ConfigSource(
        kind="base",
        path=str(base_path),
        order=0,
        content_digest="sha256:dummy",
        size_bytes=8,
    )
    merged = compose_config_with_sources(
        base_config={"pipeline": {"model": {"_include_": 1}}},
        base_source=base_source,
        overlays=(),
    )

    source_map = {
        (): base_source,
        ("pipeline",): base_source,
        ("pipeline", "model"): base_source,
        ("pipeline", "model", "_include_"): base_source,
    }

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        expand_config_includes(
            merged.config,
            source_map=source_map,
            replacement_sites=merged.replacement_sites,
            mapping_sites=merged.mapping_sites,
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_include_value"
    assert context.config_path == "$.pipeline.model._include_"


def test_expand_config_includes_fails_without_include_source_entry(
    tmp_path: Path,
) -> None:
    _write_yaml(tmp_path / "base.yaml", "pipeline:\n  model:\n    _include_: included.yaml\n")

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        expand_config_includes(
            {"pipeline": {"model": {"_include_": "include.yaml"}}},
            source_map={},
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "missing_include_source_map_entry"


def test_expand_config_includes_rejects_included_non_mapping_root(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "base.yaml"
    included = tmp_path / "included.yaml"
    _write_yaml(base_path, "pipeline:\n  model:\n    _include_: ./included.yaml\n")
    _write_yaml(included, "not-a-mapping\n")

    base_config, base_source = load_config(base_path, kind="base", order=0)
    merged = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=(),
    )

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        expand_config_includes(
            merged.config,
            source_map=merged.source_map,
            replacement_sites=merged.replacement_sites,
            mapping_sites=merged.mapping_sites,
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "included_root_not_mapping"
    assert context.config_path == "$.pipeline.model._include_"
    assert context.details is not None
    assert context.details["resolved_path"] == str(included)


def test_expand_config_includes_requires_same_site_replace_to_swap_existing_mapping(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "base.yaml"
    overlay_path = tmp_path / "overlay.yaml"
    included = tmp_path / "included.yaml"

    _write_yaml(
        base_path,
        "pipeline:\n  model:\n    existing: base\n",
    )
    _write_yaml(
        overlay_path,
        "pipeline:\n  model:\n    _include_: ./included.yaml\n",
    )
    _write_yaml(included, "from_include: value\n")

    base_config, base_source = load_config(base_path, kind="base", order=0)
    overlay_config, overlay_source = load_config(overlay_path, kind="overlay", order=1)
    merged = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=[(overlay_config, overlay_source)],
    )

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        expand_config_includes(
            merged.config,
            source_map=merged.source_map,
            replacement_sites=merged.replacement_sites,
            mapping_sites=merged.mapping_sites,
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "missing_required_replace_for_include"
    assert context.details is not None
    assert context.details["include_site_path"] == ["pipeline", "model", "_include_"]
    assert context.details["reason"] == "include_over_existing_mapping"


def test_expand_config_includes_allows_same_site_replace_included_mapping_swap(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    overlay_path = tmp_path / "overlay.yaml"
    included = tmp_path / "included.yaml"

    _write_yaml(
        base_path,
        "pipeline:\n  model:\n    existing: base\n",
    )
    _write_yaml(
        overlay_path,
        (
            "pipeline:\n"
            "  model:\n"
            "    _replace_: true\n"
            "    _include_: ./included.yaml\n"
            "    override: from-overlay\n"
        ),
    )
    _write_yaml(
        included,
        (
            "override: from-include\n"
            "base_only: value\n"
        ),
    )

    base_config, base_source = load_config(base_path, kind="base", order=0)
    overlay_config, overlay_source = load_config(overlay_path, kind="overlay", order=1)
    merged = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=[(overlay_config, overlay_source)],
    )
    expanded = expand_config_includes(
        merged.config,
        source_map=merged.source_map,
        replacement_sites=merged.replacement_sites,
        mapping_sites=merged.mapping_sites,
    )

    model = _nested_mapping(expanded.config, "pipeline", "model")
    assert model == {
        "override": "from-overlay",
        "base_only": "value",
    }
    local_customizations = [record.to_dict() for record in expanded.local_customizations]
    assert len(local_customizations) == 1
    assert local_customizations[0]["kind"] == "override"
    assert local_customizations[0]["sibling_path"] == ["pipeline", "model", "override"]


def test_expand_config_includes_rejects_unconsumed_local_replace_marker(
    tmp_path: Path,
) -> None:
    base_path = tmp_path / "base.yaml"
    included = tmp_path / "included.yaml"
    _write_yaml(
        base_path,
        (
            "pipeline:\n"
            "  model:\n"
            "    _replace_: true\n"
            "    _include_: ./included.yaml\n"
        ),
    )
    _write_yaml(included, "from_include: value\n")

    base_config, base_source = load_config(base_path, kind="base", order=0)
    merged = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=(),
    )

    with pytest.raises(ConfigIncludeExpansionError) as exc:
        expand_config_includes(
            merged.config,
            source_map=merged.source_map,
            replacement_sites=merged.replacement_sites,
            mapping_sites=merged.mapping_sites,
        )

    context = exc.value.context
    assert context is not None
    assert context.code == "invalid_include_replace_marker"
