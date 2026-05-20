from typing import Literal, Mapping, cast

import pytest

from weave.errors import ConfigMergeError
from weave.merge import merge_configs
from weave.provenance import ConfigSource
from weave.source_maps import (
    ConfigPath,
    build_base_source_map,
    compose_config_with_sources,
    format_config_path,
)
from weave.plain import PlainData


def plain_config(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return cast(dict[str, PlainData], value)


def source(*, kind: Literal["base", "overlay"], path: str, order: int = 0) -> ConfigSource:
    return ConfigSource(
        kind=kind,
        path=path,
        order=order,
        content_digest=f"sha256:{order:016x}",
        size_bytes=8,
    )


def assert_source(path: ConfigPath, config_map: dict[ConfigPath, ConfigSource], expected: ConfigSource) -> None:
    actual = config_map[path]
    assert actual.kind == expected.kind
    assert actual.path == expected.path
    assert actual.order == expected.order


def test_format_config_path_preserves_exact_literal_keys() -> None:
    assert format_config_path(()) == "$"
    assert format_config_path(("pipeline",)) == "$.pipeline"
    assert format_config_path(("pipeline", "model.path", 0, "_include_")) == "$.pipeline['model.path'][0]._include_"


def test_build_base_source_map_tracks_root_mapping_list_and_descendant_nodes() -> None:
    base_source = source(kind="base", path="/base/config.yaml")
    base = plain_config({"name": "base", "nested.key": {"value": 1, "list": [{"inner": 0}, None]}})

    source_map = build_base_source_map(base, source=base_source)

    assert source_map[()] == base_source
    assert source_map[("name",)] == base_source
    assert source_map[("nested.key",)] == base_source
    assert source_map[("nested.key", "value")] == base_source
    assert source_map[("nested.key", "list")] == base_source
    assert source_map[("nested.key", "list", 0)] == base_source
    assert source_map[("nested.key", "list", 0, "inner")] == base_source
    assert source_map[("nested.key", "list", 1)] == base_source


def test_compose_config_with_sources_tracks_overlay_order_and_authorship() -> None:
    base = plain_config({"shared": "base", "container": {"x": 1}})
    overlay_one = plain_config({"shared": "overlap", "container": {"overlay": "value"}})
    overlay_two = plain_config({"container": {"overlay": "value"}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_one_source = source(kind="overlay", path="/overlay-one.yaml", order=1)
    overlay_two_source = source(kind="overlay", path="/overlay-two.yaml", order=2)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay_one, overlay_one_source), (overlay_two, overlay_two_source)],
    )

    assert merged.config["shared"] == "overlap"
    assert merged.config["container"] == {"x": 1, "overlay": "value"}
    assert_source((), merged.source_map, base_source)
    assert_source(("shared",), merged.source_map, overlay_one_source)
    assert_source(("container",), merged.source_map, overlay_two_source)
    assert_source(("container", "x"), merged.source_map, base_source)
    assert_source(("container", "overlay"), merged.source_map, overlay_two_source)


def test_recursive_merge_preserves_surviving_base_descendants() -> None:
    base = plain_config(
        {"pipeline": {"base": {"seed": 1}, "shared": {"from_base": "yes", "preserve": 7}, "overlay": {"from_base": "yes"}}},
    )
    overlay = plain_config({"pipeline": {"shared": {"overlay": "added"}, "new": {"child": "value"}}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay, overlay_source)],
    )

    assert merged.config == {
        "pipeline": {
            "base": {"seed": 1},
            "shared": {"from_base": "yes", "preserve": 7, "overlay": "added"},
            "overlay": {"from_base": "yes"},
            "new": {"child": "value"},
        },
    }
    assert_source(("pipeline",), merged.source_map, overlay_source)
    assert_source(("pipeline", "shared"), merged.source_map, overlay_source)
    assert_source(("pipeline", "shared", "from_base"), merged.source_map, base_source)
    assert_source(("pipeline", "shared", "preserve"), merged.source_map, base_source)
    assert_source(("pipeline", "shared", "overlay"), merged.source_map, overlay_source)
    assert_source(("pipeline", "base"), merged.source_map, base_source)
    assert_source(("pipeline", "overlay"), merged.source_map, base_source)
    assert_source(("pipeline", "new"), merged.source_map, overlay_source)


def test_list_and_scalar_replacements_mark_overlay_source_for_winning_nodes() -> None:
    base = plain_config({"nums": [1, 2], "value": 1, "nullable": "x", "section": {"inner": 1}})
    overlay = plain_config({"nums": [9], "value": None, "nullable": None, "section": ["list"], "marker": {"x": 1}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay, overlay_source)],
    )

    assert merged.config["nums"] == [9]
    assert merged.config["value"] is None
    assert merged.config["nullable"] is None
    assert merged.config["section"] == ["list"]
    assert_source(("nums",), merged.source_map, overlay_source)
    assert_source(("nums", 0), merged.source_map, overlay_source)
    assert_source(("value",), merged.source_map, overlay_source)
    assert_source(("nullable",), merged.source_map, overlay_source)
    assert_source(("section",), merged.source_map, overlay_source)
    assert_source(("section", 0), merged.source_map, overlay_source)
    assert_source(("marker",), merged.source_map, overlay_source)


def test_replace_marker_discarded_and_removes_replaced_descendants() -> None:
    base = plain_config({"section": {"kept": {"old": 1}, "removed": True, "stale": "keep-this? no"}})
    overlay = plain_config({"section": {"_replace_": True, "kept": {"new": 2}, "stale": "still-there"}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay, overlay_source)],
    )

    assert merged.config == merge_configs(base, overlay)
    assert merged.config == {"section": {"kept": {"new": 2}, "stale": "still-there"}}
    assert ("section", "_replace_") not in merged.source_map
    assert ("section", "removed") not in merged.source_map
    assert ("section", "kept", "old") not in merged.source_map
    assert_source(("section",), merged.source_map, overlay_source)
    assert_source(("section", "kept"), merged.source_map, overlay_source)
    assert_source(("section", "kept", "new"), merged.source_map, overlay_source)
    assert_source(("section", "stale"), merged.source_map, overlay_source)


def test_nested_replace_marker_under_replaced_section_matches_merge_configs() -> None:
    base = plain_config({"section": {"nested": {"old": 1}, "stale": True}})
    overlay = plain_config({"section": {"_replace_": True, "nested": {"_replace_": True, "new": 2}}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay, overlay_source)],
    )

    assert merged.config == merge_configs(base, overlay)
    assert merged.config == {"section": {"nested": {"new": 2}}}
    assert ("section", "_replace_") not in merged.source_map
    assert ("section", "nested", "_replace_") not in merged.source_map
    assert ("section", "nested", "old") not in merged.source_map
    assert ("section", "stale") not in merged.source_map
    assert_source(("section",), merged.source_map, overlay_source)
    assert_source(("section", "nested"), merged.source_map, overlay_source)
    assert_source(("section", "nested", "new"), merged.source_map, overlay_source)


def test_nested_replace_marker_under_root_replacement_matches_merge_configs() -> None:
    base = plain_config({"nested": {"old": 1}, "stale": True})
    overlay = plain_config({"_replace_": True, "nested": {"_replace_": True, "new": 2}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay, overlay_source)],
    )

    assert merged.config == merge_configs(base, overlay)
    assert merged.config == {"nested": {"new": 2}}
    assert ("_replace_",) not in merged.source_map
    assert ("nested", "_replace_") not in merged.source_map
    assert ("nested", "old") not in merged.source_map
    assert ("stale",) not in merged.source_map
    assert_source((), merged.source_map, overlay_source)
    assert_source(("nested",), merged.source_map, overlay_source)
    assert_source(("nested", "new"), merged.source_map, overlay_source)


def test_nested_replace_marker_missing_lower_mapping_matches_merge_configs_failure() -> None:
    base = plain_config({"section": {"a": 1}})
    overlay = plain_config({"section": {"_replace_": True, "nested": {"_replace_": True, "x": 1}}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    with pytest.raises(ConfigMergeError):
        merge_configs(base, overlay)
    with pytest.raises(ConfigMergeError):
        compose_config_with_sources(
            base_config=base,
            base_source=base_source,
            overlays=[(overlay, overlay_source)],
        )


def test_nested_replace_marker_under_root_missing_lower_mapping_matches_merge_configs_failure() -> None:
    base = plain_config({"section": {"a": 1}})
    overlay = plain_config({"_replace_": True, "nested": {"_replace_": True, "x": 1}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    with pytest.raises(ConfigMergeError):
        merge_configs(base, overlay)
    with pytest.raises(ConfigMergeError):
        compose_config_with_sources(
            base_config=base,
            base_source=base_source,
            overlays=[(overlay, overlay_source)],
        )


def test_include_like_key_sources_are_overlay_authored() -> None:
    base = plain_config({"pipeline": {"_include_": "base.yaml"}})
    overlay = plain_config({"pipeline": {"_include_": "overlay.yaml"}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay, overlay_source)],
    )

    assert merged.config == {"pipeline": {"_include_": "overlay.yaml"}}
    assert_source(("pipeline", "_include_"), merged.source_map, overlay_source)


def test_compose_config_with_sources_tracks_root_mapping_site_for_mapping_overlay() -> None:
    base = plain_config({"pipeline": {"stage": "base"}})
    overlay = plain_config({"pipeline": {"paths": {"root": "/tmp"}}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay, overlay_source)],
    )

    assert () in merged.mapping_sites
    assert ("pipeline",) in merged.mapping_sites


def test_compose_config_with_sources_tracks_replacement_site_for_replace_marker() -> None:
    base = plain_config({"pipeline": {"stage": "base"}})
    overlay = plain_config({"pipeline": {"_replace_": True, "paths": {"root": "/tmp"}}})

    base_source = source(kind="base", path="/base.yaml", order=0)
    overlay_source = source(kind="overlay", path="/overlay.yaml", order=1)

    merged = compose_config_with_sources(
        base_config=base,
        base_source=base_source,
        overlays=[(overlay, overlay_source)],
    )

    assert () in merged.mapping_sites
    assert ("pipeline",) in merged.replacement_sites
