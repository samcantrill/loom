"""Unit tests for plain structured-data helpers."""

from dataclasses import dataclass

import pytest

from loom.serialization import PlainDataError, is_plain_data, to_plain_data, ensure_plain_data


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
