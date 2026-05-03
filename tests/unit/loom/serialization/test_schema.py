"""Unit tests for schema-version helpers."""

import pytest

from loom.serialization import SchemaVersionError, check_supported_schema, get_schema_version, require_schema_version


def test_get_schema_version_requires_positive_int() -> None:
    assert get_schema_version({"schema_version": 1}) == 1
    with pytest.raises(SchemaVersionError):
        get_schema_version({})
    with pytest.raises(SchemaVersionError):
        get_schema_version({"schema_version": "1"})


def test_require_schema_version_matches_expected() -> None:
    require_schema_version({"schema_version": 1}, expected=1)
    with pytest.raises(SchemaVersionError):
        require_schema_version({"schema_version": 2}, expected=1)


def test_check_supported_schema_rejects_unsupported() -> None:
    with pytest.raises(SchemaVersionError):
        check_supported_schema({"schema_version": 2}, supported=(1,))
