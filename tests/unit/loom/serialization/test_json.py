"""Unit tests for JSON serialization helpers."""

import pytest

from loom.serialization import DeserializationError, PlainDataError
from loom.serialization import json_dumps_pretty, json_loads, stable_json_bytes, stable_json_dumps


def test_stable_json_dumps_is_compact_and_sorted() -> None:
    value = {"b": 1, "a": 2}
    assert stable_json_dumps(value) == '{"a":2,"b":1}'


def test_stable_json_bytes_use_utf8() -> None:
    assert stable_json_bytes({"a": 1}).decode("utf-8") == '{"a":1}'


def test_json_dumps_pretty_has_newline() -> None:
    out = json_dumps_pretty({"a": 1})
    assert out.endswith("\n")
    assert "\n" in out


def test_json_loads_round_trips_plain_data() -> None:
    payload = '{"a": [1, 2], "b": null}'
    assert json_loads(payload) == {"a": [1, 2], "b": None}


def test_json_loads_rejects_invalid_json() -> None:
    with pytest.raises(DeserializationError):
        json_loads("{")


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_json_loads_rejects_nonfinite_numbers_with_original_path(number) -> None:
    with pytest.raises(PlainDataError, match=r"report\['nested'\]\[0\]"):
        json_loads('{"nested": [' + number + "]}", path="report")


def test_json_loads_preserves_finite_values_and_owned_nested_data() -> None:
    import math

    text = '{"unicode": "é", "values": [-0.0, 1e308, 1e-999, 123, true, null]}'
    first = json_loads(text)
    second = json_loads(text)
    assert isinstance(first, dict) and isinstance(second, dict)
    assert first == second == {
        "unicode": "é", "values": [-0.0, 1e308, 0.0, 123, True, None]
    }
    assert math.copysign(1, first["values"][0]) == -1
    first["values"].append("changed")
    assert len(second["values"]) == 6


def test_json_loads_keeps_decode_errors_and_duplicate_key_behavior() -> None:
    with pytest.raises(DeserializationError, match="Invalid JSON at report"):
        json_loads('{"a": NaN,', path="report")
    assert json_loads('{"a": NaN, "a": 1}') == {"a": 1}
