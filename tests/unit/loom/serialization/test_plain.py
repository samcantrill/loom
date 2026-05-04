"""Unit tests for plain structured-data helpers."""

from dataclasses import dataclass
from types import MappingProxyType

import pytest

from loom.serialization import (
    PlainDataError,
    ensure_plain_data,
    freeze_plain_data,
    is_plain_data,
    thaw_plain_data,
    to_plain_data,
)


@pytest.mark.unit

def test_to_plain_data_with_mappings_and_lists() -> None:
    data = {"x": [1, {"y": "z"}]}
    assert is_plain_data(data)
    assert ensure_plain_data(data) == data
    assert to_plain_data(data) == data


def test_to_plain_data_converts_dataclass() -> None:
    @dataclass
    class Model:
        a: int
        b: str

    model = Model(1, "two")
    assert to_plain_data(model) == {"a": 1, "b": "two"}


def test_to_plain_data_rejects_bytes_and_paths() -> None:
    from pathlib import Path

    with pytest.raises(PlainDataError):
        ensure_plain_data({Path("x"): "1"})
    with pytest.raises(PlainDataError):
        ensure_plain_data({"a": b"bad"})
    with pytest.raises(PlainDataError):
        to_plain_data({"f": {"a", "b"}})


def test_to_plain_data_rejects_set() -> None:
    with pytest.raises(PlainDataError):
        to_plain_data({"a": {1, 2}})


def test_to_plain_data_checks_nonfinite_float() -> None:
    with pytest.raises(PlainDataError):
        to_plain_data(float("nan"))
    with pytest.raises(PlainDataError):
        to_plain_data(float("inf"))
    assert to_plain_data(1.5) == 1.5


def test_freeze_plain_data_converts_structures() -> None:
    original = {"a": [1, {"b": 2}], "c": "d"}
    frozen = freeze_plain_data(original)
    assert isinstance(frozen, MappingProxyType)
    assert frozen["a"] == (1, MappingProxyType({"b": 2}))
    assert isinstance(frozen["a"], tuple)
    assert isinstance(frozen["a"][1], MappingProxyType)


def test_freeze_plain_data_rejects_non_plain_inputs() -> None:
    with pytest.raises(PlainDataError):
        freeze_plain_data({"a": {1, 2}})


def test_thaw_plain_data_converts_frozen_tree() -> None:
    frozen = MappingProxyType({"a": (1, MappingProxyType({"b": (2, 3)}))})
    thawed = thaw_plain_data(frozen)
    assert isinstance(thawed, dict)
    assert isinstance(thawed["a"], list)
    assert thawed == {"a": [1, {"b": [2, 3]}]}


def test_thaw_plain_data_copies_for_mutability() -> None:
    original = MappingProxyType({"a": ({"b": 1},)})
    thawed = thaw_plain_data(original)
    thawed["a"][0]["b"] = 2
    assert thawed["a"][0]["b"] == 2
    assert original["a"][0]["b"] == 1


def test_freeze_then_thaw_returns_mutable_data() -> None:
    value = {"nested": [{"a": 1}, 2, (3.5, "x")]}
    thawed = thaw_plain_data(freeze_plain_data(value))
    assert thawed == {"nested": [{"a": 1}, 2, [3.5, "x"]]}
