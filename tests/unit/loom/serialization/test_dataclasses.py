"""Unit tests for dataclass serialization helpers."""

from dataclasses import dataclass

import pytest

from loom.serialization import PlainDataError, dataclass_from_dict, dataclass_to_dict


@dataclass
class Model:
    a: int
    b: str = "default"


@dataclass(frozen=True, slots=True)
class FrozenModel:
    a: int
    b: str


def test_dataclass_to_dict_converts_frozen_slots() -> None:
    value = FrozenModel(1, "x")
    assert dataclass_to_dict(value) == {"a": 1, "b": "x"}


def test_dataclass_to_dict_rejects_non_dataclass() -> None:
    with pytest.raises(PlainDataError):
        dataclass_to_dict(123)


def test_dataclass_from_dict_reconstructs() -> None:
    restored = dataclass_from_dict(Model, {"a": 3, "b": "y"})
    assert restored == Model(a=3, b="y")


def test_dataclass_from_dict_rejects_unknown_field() -> None:
    with pytest.raises(PlainDataError):
        dataclass_from_dict(Model, {"a": 1, "b": "x", "extra": 9})


def test_dataclass_from_dict_rejects_missing_required_field() -> None:
    with pytest.raises(PlainDataError):
        dataclass_from_dict(Model, {"b": "x"})
