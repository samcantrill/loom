"""Recursive secret redaction helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from loom.serialization import PlainData

REDACTION_MARKER = "***REDACTED***"
_SECRET_PATTERNS = {"token", "secret", "password", "apikey", "credential", "privatekey"}


def redact_secrets(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return _redact_mapping(value)


def _redact_mapping(mapping: Mapping[str, PlainData]) -> dict[str, PlainData]:
    redacted: dict[str, PlainData] = {}
    for key, value in mapping.items():
        if is_secret_key(key):
            redacted[key] = "***REDACTED***"
            continue
        redacted[key] = _redact_item(value)
    return redacted


def _redact_item(value: PlainData) -> PlainData:
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_item(item) for item in value]
    return value


def is_secret_key(key: str) -> bool:
    """Return whether key should be treated as sensitive by default redaction."""
    normalized = "".join(char.lower() for char in key if char.isalnum())
    return any(pattern in normalized for pattern in _SECRET_PATTERNS)


def _is_secret_key(key: str) -> bool:
    return is_secret_key(key)


def redaction_policy() -> dict[str, PlainData]:
    return {
        "marker": REDACTION_MARKER,
        "pattern_names": cast(PlainData, sorted(_SECRET_PATTERNS)),
    }
