"""Plain structured data conversion helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import is_dataclass
from pathlib import Path
from types import MappingProxyType
from datetime import datetime
from typing import Any, Callable

from loom.serialization.errors import PlainDataError

PlainData = None | bool | int | float | str | list["PlainData"] | dict[str, "PlainData"]


def is_plain_data(value: Any) -> bool:
    """Return true when a value is valid plain structured data."""

    if value is None or isinstance(value, (bool, int, str)):
        return True
    if isinstance(value, float):
        return _is_finite_float(value)
    if isinstance(value, list):
        return all(is_plain_data(item) for item in value)
    if isinstance(value, tuple):
        return all(is_plain_data(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_plain_data(val) for key, val in value.items())
    return False


def ensure_plain_data(value: Any, *, path: str = "$") -> PlainData:
    """Ensure a value is valid plain data and return a normalized copy."""

    if isinstance(value, Mapping):
        return _convert_mapping(value, path)
    if isinstance(value, (list, tuple)):
        return [_to_plain(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if not is_plain_data(value):
        raise _value_error(path, value)
    return _to_plain(value, path)


def to_plain_data(value: Any, *, path: str = "$") -> PlainData:
    """Convert a supported object into plain structured data."""

    if is_plain_data(value):
        return _to_plain(value, path)

    if isinstance(value, Mapping):
        return _convert_mapping(value, path)
    if isinstance(value, (list, tuple)):
        return [_to_plain(item, f"{path}[{index}]") for index, item in enumerate(value)]

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        if not _takes_no_args(to_dict):
            raise _value_error(path, value)
        return to_plain_data(to_dict(), path=path)

    if is_dataclass(value):
        from .dataclasses import dataclass_to_dict

        return dataclass_to_dict(value, path=path)

    raise _value_error(path, value)


def freeze_plain_data(value: Any, *, path: str = "$") -> Any:
    """Convert plain data into an immutable representation."""

    validated = ensure_plain_data(value, path=path)
    return _freeze_plain_data(validated)


def thaw_plain_data(value: Any, *, path: str = "$") -> PlainData:
    """Convert frozen plain data into mutable dict/list structures."""

    return _thaw_plain_data(value, path)


def _convert_mapping(value: Mapping[Any, Any], path: str) -> dict[str, PlainData]:
    output: dict[str, PlainData] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PlainDataError(f"Invalid mapping key at {path}: keys must be strings")
        output[key] = _to_plain(item, f"{path}[{key!r}]")
    return output


def _to_plain(value: Any, path: str) -> PlainData:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return _coerce_float(value, path)
    if isinstance(value, list):
        return [_to_plain(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, tuple):
        return [_to_plain(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        return _convert_mapping(value, path)
    if isinstance(value, set | frozenset):
        raise PlainDataError(f"Invalid plain data at {path}: set-like values are not supported")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise PlainDataError(f"Invalid plain data at {path}: bytes are not supported")
    if isinstance(value, (datetime, Path, MappingProxyType)):
        raise PlainDataError(f"Invalid plain data at {path}: {type(value).__name__} is not supported")
    if callable(value):
        raise PlainDataError(f"Invalid plain data at {path}: callables are not supported")
    if not is_plain_data(value):
        raise _value_error(path, value)
    return value


def _coerce_float(value: float, path: str) -> float:
    if not _is_finite_float(value):
        raise PlainDataError(f"Invalid non-finite float at {path}")
    return float(value)


def _is_finite_float(value: float) -> bool:
    return value == value and value != float("inf") and value != float("-inf")


def _value_error(path: str, value: Any) -> PlainDataError:
    return PlainDataError(f"Invalid plain data at {path}: {type(value).__name__}")


def _takes_no_args(func: Callable[..., object]) -> bool:
    try:
        import inspect

        signature = inspect.signature(func)
        return len(signature.parameters) == 0
    except (ValueError, TypeError):
        return False


def _freeze_plain_data(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_plain_data(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_plain_data(item) for item in value)
    return value


def _thaw_plain_data(value: Any, path: str) -> PlainData:
    if isinstance(value, MappingProxyType):
        return _thaw_mapping(value, path)
    if isinstance(value, dict):
        return _thaw_mapping(value, path)
    if isinstance(value, list):
        return [_thaw_plain_data(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, tuple):
        return [_thaw_plain_data(item, f"{path}[{index}]") for index, item in enumerate(value)]
    return _to_plain(value, path)


def _thaw_mapping(value: Mapping[Any, Any], path: str) -> dict[str, PlainData]:
    output: dict[str, PlainData] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PlainDataError(f"Invalid mapping key at {path}: keys must be strings")
        output[key] = _thaw_plain_data(item, f"{path}[{key!r}]")
    return output
