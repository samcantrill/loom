"""Integration checks for source-map behavior on loaded config composition."""

from pathlib import Path

from weave.load import load_config
from weave.source_maps import compose_config_with_sources


def test_internal_source_aware_helper_preserves_overlay_order_across_loaded_configs(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    overlay_path_one = tmp_path / "overlay_one.yaml"
    overlay_path_two = tmp_path / "overlay_two.yaml"

    base_path.write_text(
        "name: base\n"
        "pipeline:\n"
        "  stage: base\n"
        "  paths:\n"
        "    root: /base\n"
        "model:\n"
        "  _include_: base.yaml\n",
        encoding="utf-8",
    )
    overlay_path_one.write_text(
        "pipeline:\n"
        "  stage: first\n"
        "  paths:\n"
        "    feature: one\n",
        encoding="utf-8",
    )
    overlay_path_two.write_text(
        "pipeline:\n"
        "  stage: second\n"
        "  paths:\n"
        "    child: /overrides/child\n"
        "model:\n"
        "  _include_: overlay-two.yaml\n",
        encoding="utf-8",
    )

    base_config, base_source = load_config(base_path, kind="base", order=0)
    overlay_one_config, overlay_one_source = load_config(overlay_path_one, kind="overlay", order=1)
    overlay_two_config, overlay_two_source = load_config(overlay_path_two, kind="overlay", order=2)

    merged = compose_config_with_sources(
        base_config=base_config,
        base_source=base_source,
        overlays=[(overlay_one_config, overlay_one_source), (overlay_two_config, overlay_two_source)],
    )

    assert merged.config == {
        "name": "base",
        "pipeline": {
            "stage": "second",
            "paths": {"root": "/base", "feature": "one", "child": "/overrides/child"},
        },
        "model": {"_include_": "overlay-two.yaml"},
    }

    assert merged.source_map[("name",)] == base_source
    assert merged.source_map[("pipeline", "stage")] == overlay_two_source
    assert merged.source_map[("pipeline", "paths", "root")] == base_source
    assert merged.source_map[("pipeline", "paths", "feature")] == overlay_one_source
    assert merged.source_map[("pipeline", "paths", "child")] == overlay_two_source
    assert merged.source_map[("model", "_include_")] == overlay_two_source
