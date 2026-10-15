"""JSON serialization and parsing helpers."""

from __future__ import annotations

import json
from json import JSONDecodeError
import math

from loom.serialization.plain import ensure_plain_data, to_plain_data
from .errors import DeserializationError


def stable_json_dumps(value: object) -> str:
    """Serialize plain data to compact stable JSON."""

    plain = to_plain_data(value)
    return json.dumps(
        plain,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def stable_json_bytes(value: object) -> bytes:
    """Serialize plain data to UTF-8 JSON bytes."""

    return stable_json_dumps(value).encode("utf-8")


def json_dumps_pretty(value: object, *, sort_keys: bool = True) -> str:
    """Serialize plain data to pretty JSON with a trailing newline."""

    plain = to_plain_data(value)
    return (
        json.dumps(
            plain,
            sort_keys=sort_keys,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def json_loads(text: str, *, path: str = "$") -> object:
    """Parse JSON text and validate as plain data."""

    try:
        # The decoder already creates an owned tree of plain dictionaries,
        # lists and scalars. Only its non-finite number extensions need a check;
        # copying every decoded member again is costly for retained reports.
        try:
            return json.loads(
                text, parse_float=_finite_float, parse_constant=_nonfinite_constant
            )
        except _NonfiniteNumber:
            # Keep the established nested-path diagnostic on this uncommon path.
            return ensure_plain_data(json.loads(text), path=path)
    except JSONDecodeError as exc:
        raise DeserializationError(f"Invalid JSON at {path}: {exc.msg}") from exc


class _NonfiniteNumber(ValueError):
    pass


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise _NonfiniteNumber
    return result


def _nonfinite_constant(value: str) -> None:
    raise _NonfiniteNumber
