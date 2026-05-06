"""Recursive secret redaction helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from loom.serialization import PlainData

REDACTION_MARKER = "***REDACTED***"
_SECRET_PATTERNS = {"token", "secret", "password", "apikey", "credential", "privatekey"}


def redact_secrets(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    return _redact_mapping(value)


def redact_secret_like_value(key: str, value: PlainData) -> PlainData:
    """Redact a single artifact-facing value using the default key policy."""
    if is_secret_key(key):
        return REDACTION_MARKER
    return _redact_item(value)


def contains_secret_like_value(key: str, value: PlainData) -> bool:
    """Return whether a key/value pair contains data redacted by the policy."""
    if is_secret_key(key):
        return True
    return _contains_secret_item(value)


def _redact_mapping(mapping: Mapping[str, PlainData]) -> dict[str, PlainData]:
    redacted: dict[str, PlainData] = {}
    for key, value in mapping.items():
        if is_secret_key(key):
            redacted[key] = REDACTION_MARKER
            continue
        redacted[key] = _redact_item(value)
    return redacted


def _redact_item(value: PlainData) -> PlainData:
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_item(item) for item in value]
    return value


def _contains_secret_item(value: PlainData) -> bool:
    if isinstance(value, dict):
        return any(is_secret_key(key) or _contains_secret_item(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret_item(item) for item in value)
    return False


def is_secret_key(key: str) -> bool:
    """Return whether key should be treated as sensitive by default redaction."""
    normalized = "".join(char.lower() for char in key if char.isalnum())
    return any(pattern in normalized for pattern in _SECRET_PATTERNS)


def is_secret_path(path: str | Sequence[object]) -> bool:
    """Return whether any config path segment should be treated as sensitive."""
    if isinstance(path, str):
        return is_secret_key(path)
    return any(is_secret_key(str(segment)) for segment in path)


def _is_secret_key(key: str) -> bool:
    return is_secret_key(key)


def redaction_policy() -> dict[str, PlainData]:
    return {
        "marker": REDACTION_MARKER,
        "pattern_names": cast(PlainData, sorted(_SECRET_PATTERNS)),
    }
