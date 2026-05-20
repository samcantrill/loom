"""Package tests for JSON helpers."""

import pytest

from weave.json import json_loads, json_dumps_pretty, stable_json_bytes, stable_json_dumps
from weave.errors import DeserializationError


pytestmark = pytest.mark.package


def test_stable_json_dumps_is_compact_and_sorted() -> None:
    value = {"b": 1, "a": 2}
    assert stable_json_dumps(value) == '{"a":2,"b":1}'


def test_stable_json_bytes_are_utf8() -> None:
    assert stable_json_bytes({"a": 1}).decode("utf-8") == '{"a":1}'


def test_json_dumps_pretty_is_deterministic() -> None:
    out = json_dumps_pretty({"a": 1})
    assert out.endswith("\n")
    assert out == '{\n  "a": 1\n}' + "\n"


def test_json_loads_round_trips_plain_data() -> None:
    payload = '{"a": [1, 2], "b": null}'
    assert json_loads(payload) == {"a": [1, 2], "b": None}


def test_json_loads_rejects_bad_payload() -> None:
    with pytest.raises(DeserializationError):
        json_loads("{")
