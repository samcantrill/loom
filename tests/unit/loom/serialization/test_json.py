"""Unit tests for JSON serialization helpers."""

import pytest

from loom.serialization import DeserializationError
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
