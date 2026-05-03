"""Schema-version helper functions."""

from __future__ import annotations

from collections.abc import Iterable

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
