"""JSON serialization and parsing helpers."""

from __future__ import annotations

import json
from json import JSONDecodeError

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
        parsed = json.loads(text)
    except JSONDecodeError as exc:
        raise DeserializationError(f"Invalid JSON at {path}: {exc.msg}") from exc
    return ensure_plain_data(parsed, path=path)
