"""Schema-version helper functions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import cast

from .errors import SchemaVersionError


DocumentMigration = Callable[[Mapping[str, object]], Mapping[str, object]]


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
    migrations: Mapping[int, DocumentMigration] | None = None,
    field: str = "schema_version",
    path: str = "$",
) -> dict[str, object]:
    mapping = require_mapping(data, path=path)
    current = dict(mapping)
    current_version_value = current_version

    version = get_schema_version(current, field=field, path=path)
    if version > current_version_value:
        raise SchemaVersionError(f"{path}.{field}: unsupported schema version {version}")

    migration_map = {} if migrations is None else migrations
    while version < current_version_value:
        migration = migration_map.get(version)
        if migration is None:
            raise SchemaVersionError(
                f"{path}.{field}: missing migration for schema version {version}",
            )
        migrated = migration(current)
        if not isinstance(migrated, Mapping):
            raise SchemaVersionError(
                f"{path}.{field}: migration for schema version {version} must return a mapping",
            )
        migrated_mapping = dict(require_mapping(migrated, path=path))
        next_version = get_schema_version(migrated_mapping, field=field, path=path)
        expected_version = version + 1
        if next_version != expected_version:
            raise SchemaVersionError(
                f"{path}.{field}: migration for schema version {version} must return schema version {expected_version}, got {next_version}",
            )
        current = migrated_mapping
        version = next_version

    validate_document_fields(current, required=(set(required) | {field}), optional=optional, path=path)
    return dict(current)
