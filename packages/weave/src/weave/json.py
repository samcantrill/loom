"""Stable JSON helpers for config artifacts."""

from __future__ import annotations

import json
from json import JSONDecodeError

from .errors import DeserializationError
from .plain import to_plain_data


def stable_json_dumps(value: object) -> str:
    """Serialize plain data to deterministic compact JSON text."""

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
    """Serialize plain data to pretty JSON with deterministic sorting."""

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
    from .plain import ensure_plain_data

    return ensure_plain_data(parsed, path=path)


__all__ = [
    "stable_json_dumps",
    "stable_json_bytes",
    "json_dumps_pretty",
    "json_loads",
]
