"""Package tests for plain-data helpers."""

from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from weave.plain import (
    PlainDataError,
    freeze_plain_data,
    is_plain_data,
    ensure_plain_data,
    thaw_plain_data,
    to_plain_data,
)


pytestmark = pytest.mark.package



def test_to_plain_data_maps_and_tuples_normalize() -> None:
    payload = {"x": (1, ["a", {"b": 2}])}
    assert is_plain_data(payload)
    assert ensure_plain_data(payload) == {"x": [1, ["a", {"b": 2}]]}
    assert to_plain_data(payload) == {"x": [1, ["a", {"b": 2}]]}


def test_to_plain_data_converts_to_dict_when_supported() -> None:
    class Model:
        def __init__(self, a: int, b: str) -> None:
            self.a = a
            self.b = b

        def to_dict(self) -> dict[str, Any]:
            return {"a": self.a, "b": self.b}

    assert to_plain_data(Model(a=1, b="two")) == {"a": 1, "b": "two"}


def test_to_plain_data_rejects_invalid_types() -> None:
    from pathlib import Path

    with pytest.raises(PlainDataError):
        ensure_plain_data({Path("x"): "1"})
    with pytest.raises(PlainDataError):
        ensure_plain_data({"a": b"bad"})
    with pytest.raises(PlainDataError):
        to_plain_data({"a": {1, 2}})


def test_to_plain_data_rejects_non_finite_float() -> None:
    with pytest.raises(PlainDataError):
        to_plain_data(float("nan"))
    with pytest.raises(PlainDataError):
        to_plain_data(float("inf"))


def test_to_plain_data_rejects_callables_and_paths() -> None:
    def not_plain() -> None:
        pass

    with pytest.raises(PlainDataError):
        to_plain_data(not_plain)
    with pytest.raises(PlainDataError):
        to_plain_data(Path("/tmp"))


def test_freeze_plain_data_rejects_non_plain_inputs() -> None:
    with pytest.raises(PlainDataError):
        freeze_plain_data({"a": {1, 2}})


def test_freeze_and_thaw_round_trip() -> None:
    value = {"nested": (1, [2, {"a": 3}])}
    frozen = freeze_plain_data(value)
    assert isinstance(frozen, MappingProxyType)
    assert isinstance(frozen["nested"], tuple)

    thawed = thaw_plain_data(frozen)
    assert thawed == {"nested": [1, [2, {"a": 3}]]}
    thawed["nested"][1][1]["a"] = 9
    assert value["nested"] == (1, [2, {"a": 3}])


def test_py_package_marker_present() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "src" / "weave" / "py.typed").is_file()
