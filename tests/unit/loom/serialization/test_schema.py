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


@pytest.mark.parametrize("version", [1, 3, True, None, "2"])
def test_load_versioned_document_rejects_noncurrent_version_without_changes(version) -> None:
    document = {"schema_version": version, "value": 1}
    before = dict(document)
    with pytest.raises(SchemaVersionError):
        load_versioned_document(
            document,
            current_version=2,
            required={"value"},
        )
    assert document == before


def test_load_versioned_document_rejects_non_mapping_input() -> None:
    with pytest.raises(SchemaVersionError):
        load_versioned_document("payload", current_version=1, required=set())


def test_load_versioned_document_copies_current_version_with_custom_field() -> None:
    document = {"format": 2, "value": 1, "label": "current"}
    loaded = load_versioned_document(
        document,
        current_version=2,
        required={"value"},
        optional={"label"},
        field="format",
    )
    assert loaded == document
    assert loaded is not document


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({"schema_version": 2}, "missing required field"),
        ({"schema_version": 2, "value": 1, "old_field": True}, "unknown field"),
        ({"value": 1}, "missing schema version field"),
    ],
)
def test_load_versioned_document_validates_current_fields(document, message) -> None:
    with pytest.raises(SchemaVersionError, match=message):
        load_versioned_document(document, current_version=2, required={"value"})
