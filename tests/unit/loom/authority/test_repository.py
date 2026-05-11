"""Unit tests for the private authority repository foundation."""

from __future__ import annotations

import pytest

from loom.authority._repository import (
    AUTHORITY_REPOSITORY_SCHEMA_VERSION,
    AuthorityRepository,
    AuthorityRepositoryCompatibilityError,
    AuthorityRepositoryCompatibilityFailure,
    AuthorityRepositoryCompatibilityKind,
    AuthorityRepositoryIdentity,
    generate_service_generation,
)


pytestmark = pytest.mark.unit


def test_compatibility_failure_serializes_stable_code() -> None:
    failure = AuthorityRepositoryCompatibilityFailure(
        kind=AuthorityRepositoryCompatibilityKind.UNSUPPORTED_NEWER,
        message="newer schema",
        found_version=3,
        detail={"database_path": "/tmp/authority.sqlite3"},
    )

    assert failure.code == "authority_repository_unsupported_newer"
    assert failure.to_dict() == {
        "kind": "unsupported_newer",
        "code": "authority_repository_unsupported_newer",
        "message": "newer schema",
        "found_version": 3,
        "current_version": AUTHORITY_REPOSITORY_SCHEMA_VERSION,
        "detail": {"database_path": "/tmp/authority.sqlite3"},
    }


def test_service_generation_is_opaque_non_empty_token() -> None:
    first = generate_service_generation()
    second = generate_service_generation()

    assert first.startswith("authority-generation-")
    assert second.startswith("authority-generation-")
    assert first != second


def test_repository_requires_valid_database_name(tmp_path) -> None:
    with pytest.raises(ValueError, match="database_name"):
        AuthorityRepository(tmp_path, database_name="nested/authority.sqlite3")


def test_repository_identity_serializes_paths_and_metadata(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)
    identity = repository.initialize(service_generation="generation-1")

    assert isinstance(identity, AuthorityRepositoryIdentity)
    assert identity.state_dir == tmp_path
    assert identity.database_path == tmp_path / "authority.sqlite3"
    assert identity.schema_version == AUTHORITY_REPOSITORY_SCHEMA_VERSION
    assert identity.service_generation == "generation-1"
    assert identity.to_dict()["state_dir"] == str(tmp_path)
    assert identity.to_dict()["database_path"] == str(tmp_path / "authority.sqlite3")


def test_read_identity_fails_for_missing_database(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        repository.read_identity()

    assert exc_info.value.failure.kind is AuthorityRepositoryCompatibilityKind.MISSING
