from typing import Mapping, cast

import pytest

from weave.plain import PlainData
from weave.merge import merge_configs
from weave.errors import ConfigMergeError


def plain_config(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return cast(dict[str, PlainData], value)


def test_merge_replaces_scalars_lists_and_nulls() -> None:
    base = plain_config({"a": {"b": 1}, "list": [1, 2], "value": 1, "_copy_": {"kind": "base"}})
    overlay = plain_config({"a": {"c": 2}, "list": [3], "value": None, "_copy_": {"kind": "overlay"}})
    merged = merge_configs(base, overlay)

    assert merged == {
        "a": {"b": 1, "c": 2},
        "list": [3],
        "value": None,
        "_copy_": {"kind": "overlay"},
    }


def test_merge_keeps_missing_overlay_keys() -> None:
    base = plain_config({"a": 1})
    overlay = plain_config({"b": 2})
    assert merge_configs(base, overlay) == {"a": 1, "b": 2}


def test_merge_mapping_recurse_without_replace_marker() -> None:
    base = plain_config({"a": {"b": 1, "c": {"d": 1}}})
    overlay = plain_config({"a": {"c": {"e": 2}, "f": 3}})
    assert merge_configs(base, overlay) == {"a": {"b": 1, "c": {"d": 1, "e": 2}, "f": 3}}


def test_merge_replace_marker_consumed_as_whole_mapping_replacement() -> None:
    base = plain_config({"a": {"b": 1, "c": 2}})
    overlay = plain_config({"a": {"_replace_": True, "d": 3}})

    assert merge_configs(base, overlay) == {"a": {"d": 3}}


def test_merge_root_replace_marker_consumed_as_whole_mapping_replacement() -> None:
    base = plain_config({"a": {"b": 1}, "c": 2})
    overlay = plain_config({"_replace_": True, "d": 3})

    assert merge_configs(base, overlay) == {"d": 3}


def test_merge_replace_marker_removes_marker_from_result() -> None:
    base = plain_config({"section": {"a": 1}})
    overlay = plain_config({"section": {"_replace_": True, "a": 2}})
    merged = merge_configs(base, overlay)
    section = merged["section"]
    if not isinstance(section, dict):
        raise AssertionError("Expected merged section to be a mapping")

    assert "_replace_" not in section


def test_merge_nested_replace_marker_under_replaced_section_is_consumed() -> None:
    base = plain_config({"section": {"nested": {"old": 1}, "stale": True}})
    overlay = plain_config({"section": {"_replace_": True, "nested": {"_replace_": True, "new": 2}}})

    assert merge_configs(base, overlay) == {"section": {"nested": {"new": 2}}}


def test_merge_nested_replace_marker_under_root_replacement_is_consumed() -> None:
    base = plain_config({"nested": {"old": 1}, "stale": True})
    overlay = plain_config({"_replace_": True, "nested": {"_replace_": True, "new": 2}})

    assert merge_configs(base, overlay) == {"nested": {"new": 2}}


def test_merge_nested_replace_marker_in_replacement_requires_lower_mapping() -> None:
    base = plain_config({"section": {"other": 1}})
    overlay = plain_config({"section": {"_replace_": True, "nested": {"_replace_": True, "new": 2}}})

    with pytest.raises(ConfigMergeError):
        merge_configs(base, overlay)


def test_merge_replace_marker_fails_when_lower_value_missing() -> None:
    base = plain_config({})
    overlay = plain_config({"section": {"_replace_": True, "a": 1}})
    with pytest.raises(ConfigMergeError):
        merge_configs(base, overlay)


def test_merge_replace_marker_fails_when_lower_value_not_mapping() -> None:
    base = plain_config({"section": 1})
    overlay = plain_config({"section": {"_replace_": True, "a": 1}})
    with pytest.raises(ConfigMergeError) as exc:
        merge_configs(base, overlay)
    context = exc.value.context
    assert context is not None
    assert context.code == "replace_target_not_mapping"
    assert context.config_path == "$['section']"
    assert context.directive == "_replace_"
    assert context.remediation is not None


def test_merge_replace_marker_fails_with_no_sibling_replacement_keys() -> None:
    base = plain_config({"section": {"a": 1}})
    overlay = plain_config({"section": {"_replace_": True}})
    with pytest.raises(ConfigMergeError):
        merge_configs(base, overlay)


def test_merge_replace_marker_rejects_non_true_value() -> None:
    base = plain_config({"section": {"a": 1}})
    overlay = plain_config({"section": {"_replace_": False, "a": 2}})
    with pytest.raises(ConfigMergeError):
        merge_configs(base, overlay)


def test_merge_root_replace_marker_rejects_non_true_value() -> None:
    base = plain_config({"a": 1})
    overlay = plain_config({"_replace_": False, "b": 2})
    with pytest.raises(ConfigMergeError):
        merge_configs(base, overlay)


def test_merge_root_replace_marker_fails_with_no_sibling_replacement_keys() -> None:
    base = plain_config({"a": 1})
    overlay = plain_config({"_replace_": True})
    with pytest.raises(ConfigMergeError):
        merge_configs(base, overlay)


def test_merge_scalar_over_mapping_replacement_without_replace_marker() -> None:
    base = plain_config({"a": {"b": 1}})
    overlay = plain_config({"a": 2})
    assert merge_configs(base, overlay) == {"a": 2}


def test_merge_mapping_over_scalar_replacement_without_replace_marker() -> None:
    base = plain_config({"a": 2})
    overlay = plain_config({"a": {"b": 1}})
    assert merge_configs(base, overlay) == {"a": {"b": 1}}


def test_merge_inputs_are_not_mutated() -> None:
    base = plain_config({"a": {"b": 1}})
    overlay = plain_config({"a": {"c": 2}})
    base_original = {"a": {"b": 1}}
    overlay_original = {"a": {"c": 2}}

    merge_configs(base, overlay)

    assert base == base_original
    assert overlay == overlay_original
