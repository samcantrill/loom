"""Unit tests for override parsing and application."""

import pytest

from loom.config.errors import OverrideApplyError, OverrideParseError
from loom.config.overrides import apply_overrides, parse_overrides


def test_parse_override_primitive_variants() -> None:
    overrides = parse_overrides(("name=abc", "+a=true", "b=false", "c=null", "d=12", "e=1.5", "f=[1, 2]", "g={\"a\":1}"))

    assert [item.operation for item in overrides] == [
        "update",
        "add",
        "update",
        "update",
        "update",
        "update",
        "update",
        "update",
    ]
    assert overrides[0].value == "abc"
    assert overrides[1].value is True
    assert overrides[2].value is False
    assert overrides[3].value is None
    assert overrides[4].value == 12
    assert overrides[5].value == 1.5
    assert overrides[6].value == [1, 2]
    assert overrides[7].value == {"a": 1}


def test_parse_override_errors_for_invalid_forms() -> None:
    with pytest.raises(OverrideParseError):
        parse_overrides(("no-equal",))
    with pytest.raises(OverrideParseError):
        parse_overrides(("a..b=1",))
    with pytest.raises(OverrideParseError):
        parse_overrides(("+ =1",))
    with pytest.raises(OverrideParseError):
        parse_overrides(("value=[1,]",))


def test_parse_override_rejects_nonfinite_json_float() -> None:
    with pytest.raises(OverrideParseError):
        parse_overrides(("value=[NaN]",))


def test_apply_override_update_and_add_paths() -> None:
    parsed = parse_overrides(("a.b=2", "+a.c=3", "+z=4"))
    merged = apply_overrides({"a": {"b": 1}, "x": {"y": 1}}, parsed)
    assert merged == {"a": {"b": 2, "c": 3}, "x": {"y": 1}, "z": 4}


def test_apply_override_add_fails_if_target_exists() -> None:
    parsed = parse_overrides(("+a.b=2",))
    with pytest.raises(OverrideApplyError):
        apply_overrides({"a": {"b": 1}}, parsed)


def test_apply_override_update_fails_for_missing_path() -> None:
    parsed = parse_overrides(("a.c=2",))
    with pytest.raises(OverrideApplyError):
        apply_overrides({"a": {"b": 1}}, parsed)


def test_apply_override_rejects_list_parent() -> None:
    parsed = parse_overrides(("a.0=2",))
    with pytest.raises(OverrideApplyError):
        apply_overrides({"a": [1, 2]}, parsed)
