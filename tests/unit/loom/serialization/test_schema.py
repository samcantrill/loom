"""Unit tests for schema-version helpers."""

import pytest

from loom.serialization import (
    SchemaVersionError,
    check_supported_schema,
    get_schema_version,
    load_versioned_document,
    require_mapping,
    require_schema_version,
    validate_document_fields,
)


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


def test_require_mapping_rejects_non_mapping() -> None:
    with pytest.raises(SchemaVersionError):
        require_mapping([])


def test_require_mapping_rejects_non_string_keys() -> None:
    with pytest.raises(SchemaVersionError, match="string keys"):
        require_mapping({1: "nope"})


def test_validate_document_fields_rejects_missing_required() -> None:
    with pytest.raises(SchemaVersionError, match="missing required field"):
        validate_document_fields(
            {"schema_version": 1, "value": 2},
            required={"schema_version", "required"},
            optional={"value"},
        )


def test_validate_document_fields_rejects_unknown_fields() -> None:
    with pytest.raises(SchemaVersionError, match="unknown field"):
        validate_document_fields(
            {"schema_version": 1, "value": 2},
            required={"schema_version"},
            optional=set(),
        )


def test_load_versioned_document_rejects_future_schema_version() -> None:
    with pytest.raises(SchemaVersionError):
        load_versioned_document(
            {"schema_version": 2, "value": 1},
            current_version=1,
            required={"value"},
        )


def test_load_versioned_document_rejects_missing_migration() -> None:
    with pytest.raises(SchemaVersionError, match="missing migration"):
        load_versioned_document(
            {"schema_version": 1, "value": 1},
            current_version=2,
            required={"value"},
        )


def test_load_versioned_document_rejects_invalid_migration_output() -> None:
    def migration(payload: dict[str, object]) -> dict[str, object]:
        value = dict(payload)
        value["schema_version"] = "bad"
        return value

    with pytest.raises(SchemaVersionError):
        load_versioned_document(
            {"schema_version": 1, "value": 1},
            current_version=2,
            required={"value"},
            migrations={1: migration},
        )


def test_load_versioned_document_rejects_non_mapping_input() -> None:
    with pytest.raises(SchemaVersionError):
        load_versioned_document("payload", current_version=1, required=set())


def test_load_versioned_document_migrates_to_current_version() -> None:
    def migration(payload: dict[str, object]) -> dict[str, object]:
        value = dict(payload)
        value["schema_version"] = 2
        value["new_field"] = True
        return value

    assert load_versioned_document(
        {"schema_version": 1, "value": 1},
        current_version=2,
        required={"value"},
        optional={"new_field"},
        migrations={1: migration},
    ) == {"schema_version": 2, "value": 1, "new_field": True}
