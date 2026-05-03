"""Unit tests for recursive merge behavior."""

from loom.config.merge import merge_configs


def test_recursive_merge_replaces_scalars_and_lists() -> None:
    base = {"a": {"b": 1}, "list": [1, 2], "value": 1, "_copy_": {"kind": "base"}}
    overlay = {"a": {"c": 2}, "list": [3], "value": None, "_copy_": {"kind": "overlay"}}
    merged = merge_configs(base, overlay)

    assert merged == {
        "a": {"b": 1, "c": 2},
        "list": [3],
        "value": None,
        "_copy_": {"kind": "overlay"},
    }


def test_merge_keeps_missing_overlay_keys() -> None:
    base = {"a": 1}
    overlay = {"b": 2}
    assert merge_configs(base, overlay) == {"a": 1, "b": 2}
