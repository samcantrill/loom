"""Recursive secret redaction helpers."""

from __future__ import annotations

from collections.abc import Mapping

from loom.serialization import PlainData

_SECRET_PATTERNS = {"token", "secret", "password", "apikey", "credential", "privatekey"}


def redact_secrets(value: object) -> PlainData:
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_item(item) for item in value]
    return value


def _redact_mapping(mapping: Mapping[str, object]) -> dict[str, PlainData]:
    redacted: dict[str, PlainData] = {}
    for key, value in mapping.items():
        if _is_secret_key(key):
            redacted[key] = "***REDACTED***"
            continue
        redacted[key] = _redact_item(value)
    return redacted


def _redact_item(value: object) -> PlainData:
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_item(item) for item in value]
    return value


def _is_secret_key(key: str) -> bool:
    normalized = "".join(char.lower() for char in key if char.isalnum())
    return any(pattern in normalized for pattern in _SECRET_PATTERNS)
