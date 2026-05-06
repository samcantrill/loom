"""Unit tests for override parsing and application."""

from copy import deepcopy
from typing import Mapping, cast

import pytest

from loom.serialization import PlainData
from loom.config.errors import OverrideApplyError, OverrideParseError
from loom.config.overrides import apply_overrides, parse_overrides, split_include_and_ordinary_overrides


def plain_config(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return cast(dict[str, PlainData], value)


def test_parse_override_primitive_variants() -> None:
    overrides = parse_overrides(
        (
            "name=abc",
            "+a=true",
            "b=false",
            "c=null",
            "d=12",
            "e=1.5",
            "f=[1, 2]",
            "g={\"a\":1}",
            "h=1e3",
            "i=1.",
        )
    )

    assert [item.operation for item in overrides] == [
        "update",
        "add",
        "update",
        "update",
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
    assert overrides[8].value == 1000
    assert overrides[9].value == 1.0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('value="true"', "true"),
        ('value="false"', "false"),
        ('value="null"', "null"),
        ('value="123"', "123"),
        ('value="1.5"', "1.5"),
        ('value=""', ""),
        (r'value="escaped\nvalue"', "escaped\nvalue"),
        (r'value="quote: \"yes\""', 'quote: "yes"'),
        ('value="ordinary"', "ordinary"),
    ],
)
def test_parse_override_json_quoted_scalar_strings(raw: str, expected: str) -> None:
    parsed = parse_overrides((raw,))

    assert parsed[0].value == expected
    assert isinstance(parsed[0].value, str)


def test_parse_override_errors_for_invalid_forms() -> None:
    with pytest.raises(OverrideParseError):
        parse_overrides(("no-equal",))
    with pytest.raises(OverrideParseError):
        parse_overrides(("a..b=1",))
    with pytest.raises(OverrideParseError):
        parse_overrides(("+ =1",))
    with pytest.raises(OverrideParseError):
        parse_overrides(("value=[1,]",))


@pytest.mark.parametrize(
    ("raw",),
    [
        ('value="unterminated',),
        (r'value="bad\qescape"',),
    ],
)
def test_parse_override_rejects_malformed_json_quoted_scalar_strings(raw: str) -> None:
    with pytest.raises(OverrideParseError):
        parse_overrides((raw,))


def test_parse_override_rejects_nonfinite_json_float() -> None:
    with pytest.raises(OverrideParseError):
        parse_overrides(("value=[NaN]",))


def test_parse_override_rejects_empty_and_trailing_dot_paths() -> None:
    with pytest.raises(OverrideParseError):
        parse_overrides(("a..b=1",))
    with pytest.raises(OverrideParseError):
        parse_overrides((".a=1",))
    with pytest.raises(OverrideParseError):
        parse_overrides(("a.=1",))


def test_apply_override_update_and_add_paths() -> None:
    parsed = parse_overrides(("a.b=2", "+a.c=3", "+z=4"))
    merged = apply_overrides(plain_config({"a": {"b": 1}, "x": {"y": 1}}), parsed)
    assert merged == {"a": {"b": 2, "c": 3}, "x": {"y": 1}, "z": 4}


def test_apply_override_add_create_parents_for_explicit_add_and_then_update() -> None:
    parsed = parse_overrides(("+pipeline.paths={}", "+pipeline.paths.a=1", "pipeline.paths.a=2", "+pipeline.extra=c"))
    merged = apply_overrides(plain_config({}), parsed)
    assert merged == {"pipeline": {"paths": {"a": 2}, "extra": "c"}}


def test_apply_override_update_does_not_create_missing_parent() -> None:
    parsed = parse_overrides(("pipeline.paths.a=1",))
    with pytest.raises(OverrideApplyError):
        apply_overrides(plain_config({}), parsed)


def test_apply_override_add_fails_if_target_exists() -> None:
    parsed = parse_overrides(("+a.b=2",))
    with pytest.raises(OverrideApplyError):
        apply_overrides(plain_config({"a": {"b": 1}}), parsed)


def test_apply_override_update_fails_for_missing_path() -> None:
    parsed = parse_overrides(("a.c=2",))
    with pytest.raises(OverrideApplyError):
        apply_overrides(plain_config({"a": {"b": 1}}), parsed)


def test_apply_override_failure_has_structured_redacted_context() -> None:
    parsed = parse_overrides(("auth.token=super-secret",))
    with pytest.raises(OverrideApplyError) as exc:
        apply_overrides(plain_config({"auth": {}}), parsed)

    context = exc.value.context
    assert context is not None
    assert context.code == "missing_override_target"
    assert context.source_kind == "ordinary_override"
    assert context.config_path == "$.auth.token"
    assert context.details is not None
    assert context.details["override_raw"] == "***REDACTED***"
    assert context.details["override_path"] == "auth.token"
    assert context.details["override_redacted"] is True


def test_apply_override_rejects_list_parent() -> None:
    parsed = parse_overrides(("a.0=2",))
    with pytest.raises(OverrideApplyError):
        apply_overrides(plain_config({"a": [1, 2]}), parsed)


def test_apply_override_rejects_non_mapping_parent() -> None:
    parsed = parse_overrides(("a.b.c=2",))
    with pytest.raises(OverrideApplyError):
        apply_overrides(plain_config({"a": None}), parsed)


def test_apply_override_targets_numeric_like_keys_as_strings() -> None:
    parsed = parse_overrides(("a.0=2",))
    merged = apply_overrides(plain_config({"a": {"0": 1}}), parsed)
    assert merged == {"a": {"0": 2}}


def test_apply_override_does_not_mutate_input() -> None:
    config = plain_config({"a": {"b": 1}})
    parsed = parse_overrides(("a.b=2",))
    original = deepcopy(config)

    merged = apply_overrides(config, parsed)

    assert config == original
    assert merged == {"a": {"b": 2}}


def test_split_include_and_ordinary_overrides_keeps_original_order() -> None:
    parsed = parse_overrides(
        (
            "model.name=base",
            "model.component._include_=alternate.yaml",
            "+pipeline.stage=overlay",
            "pipeline.model._include_=another",
            "+pipeline.leaf=final",
        )
    )
    include_overrides, ordinary_overrides = split_include_and_ordinary_overrides(parsed)

    assert [override.path for override in include_overrides] == [
        "model.component._include_",
        "pipeline.model._include_",
    ]
    assert [override.path for override in ordinary_overrides] == [
        "model.name",
        "pipeline.stage",
        "pipeline.leaf",
    ]
