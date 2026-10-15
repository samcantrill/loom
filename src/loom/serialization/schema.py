"""Schema-version helper functions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

from .errors import SchemaVersionError


def get_schema_version(
    data: object,
    *,
    field: str = "schema_version",
    path: str = "$",
) -> int:
    if not isinstance(data, dict):
        raise SchemaVersionError(f"{path}: expected mapping")
    if field not in data:
        raise SchemaVersionError(f"{path}.{field}: missing schema version field")
    version = data[field]
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        raise SchemaVersionError(f"{path}.{field}: expected positive int")
    return version


def require_schema_version(
    data: object,
    expected: int,
    *,
    field: str = "schema_version",
    path: str = "$",
) -> None:
    actual = get_schema_version(data, field=field, path=path)
    if actual != expected:
        raise SchemaVersionError(f"{path}.{field}: expected {expected}, got {actual}")


def check_supported_schema(
    data: object,
    *,
    supported: Iterable[int],
    field: str = "schema_version",
    path: str = "$",
) -> int:
    actual = get_schema_version(data, field=field, path=path)
    if actual not in set(supported):
        raise SchemaVersionError(f"{path}.{field}: unsupported schema version {actual}")
    return actual


def require_mapping(data: object, *, path: str = "$") -> Mapping[str, object]:
    """Return a mapping with string keys or raise ``SchemaVersionError``."""
    if not isinstance(data, Mapping):
        raise SchemaVersionError(f"{path}: expected mapping")
    if any(not isinstance(key, str) for key in data):
        raise SchemaVersionError(f"{path}: expected mapping with string keys")
    return cast(Mapping[str, object], data)


def validate_document_fields(
    data: object,
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
    path: str = "$",
) -> Mapping[str, object]:
    mapping = require_mapping(data, path=path)
    required_fields = set(required)
    optional_fields = set(optional)
    missing = required_fields - set(mapping)
    unknown = set(mapping) - required_fields - optional_fields

    if missing:
        missing_text = ", ".join(sorted(missing))
        raise SchemaVersionError(f"{path}: missing required field(s): {missing_text}")
    if unknown:
        unknown_text = ", ".join(sorted(unknown))
        raise SchemaVersionError(f"{path}: unknown field(s): {unknown_text}")
    return mapping


def load_versioned_document(
    data: object,
    *,
    current_version: int,
    required: Iterable[str],
    optional: Iterable[str] = (),
    field: str = "schema_version",
    path: str = "$",
) -> dict[str, object]:
    """Load exactly the current document format without converting its contents."""
    mapping = require_mapping(data, path=path)
    current = dict(mapping)

    version = get_schema_version(current, field=field, path=path)
    if version != current_version:
        raise SchemaVersionError(
            f"{path}.{field}: unsupported schema version {version}; expected {current_version}",
        )

    validate_document_fields(current, required=(set(required) | {field}), optional=optional, path=path)
    return current
