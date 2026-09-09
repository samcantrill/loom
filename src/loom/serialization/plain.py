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

    pending = [(value, False)]
    active: set[int] = set()
    while pending:
        item, finished = pending.pop()
        if finished:
            active.remove(id(item))
        elif isinstance(item, (dict, list, tuple)):
            if id(item) in active:
                return False
            if isinstance(item, dict) and any(not isinstance(key, str) for key in item):
                return False
            active.add(id(item))
            pending.append((item, True))
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, False) for child in children)
        elif isinstance(item, float):
            if not _is_finite_float(item):
                return False
        elif item is not None and not isinstance(item, (bool, int, str)):
            return False
    return True


def ensure_plain_data(value: Any, *, path: str = "$") -> PlainData:
    """Ensure a value is valid plain data and return a normalized copy."""

    if not isinstance(value, (Mapping, list, tuple)) and not is_plain_data(value):
        raise _value_error(path, value)
    return _copy_plain_data(value, path)


def to_plain_data(value: Any, *, path: str = "$") -> PlainData:
    """Convert a supported object into plain structured data."""

    if is_plain_data(value) or isinstance(value, (Mapping, list, tuple)):
        return _copy_plain_data(value, path)

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

    if not isinstance(value, (Mapping, list, tuple)) and not is_plain_data(value):
        raise _value_error(path, value)
    return _copy_plain_data(value, path, frozen=True)


def thaw_plain_data(value: Any, *, path: str = "$") -> PlainData:
    """Convert frozen plain data into mutable dict/list structures."""

    return _copy_plain_data(value, path)


def _copy_plain_data(value: Any, path: str, *, frozen: bool = False) -> Any:
    """Copy a plain tree without using Python stack frames for its depth."""

    pending = [(value, path, False)]
    converted: list[Any] = []
    active: set[int] = set()
    while pending:
        item, item_path, finished = pending.pop()
        if finished:
            count = len(item)
            children = converted[-count:] if count else []
            if count:
                del converted[-count:]
            if isinstance(item, Mapping):
                result = dict(zip(item, children, strict=True))
                converted.append(MappingProxyType(result) if frozen else result)
            else:
                converted.append(tuple(children) if frozen else children)
            active.remove(id(item))
        elif isinstance(item, (Mapping, list, tuple)):
            if id(item) in active:
                raise PlainDataError(f"Invalid plain data at {item_path}: cycle")
            if isinstance(item, Mapping):
                entries = list(item.items())
                if any(not isinstance(key, str) for key, _ in entries):
                    raise PlainDataError(
                        f"Invalid mapping key at {item_path}: keys must be strings"
                    )
            else:
                entries = list(enumerate(item))
            active.add(id(item))
            pending.append((item, item_path, True))
            pending.extend(
                (child, f"{item_path}[{key!r}]", False)
                for key, child in reversed(entries)
            )
        else:
            converted.append(_plain_scalar(item, item_path))
    return converted[0]


def _plain_scalar(value: Any, path: str) -> PlainData:
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
    if isinstance(value, set | frozenset):
        raise PlainDataError(
            f"Invalid plain data at {path}: set-like values are not supported"
        )
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise PlainDataError(f"Invalid plain data at {path}: bytes are not supported")
    if isinstance(value, (datetime, Path)):
        raise PlainDataError(
            f"Invalid plain data at {path}: {type(value).__name__} is not supported"
        )
    if callable(value):
        raise PlainDataError(
            f"Invalid plain data at {path}: callables are not supported"
        )
    raise _value_error(path, value)


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
