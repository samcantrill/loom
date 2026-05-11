"""File-backed integration tests for the private authority repository."""

from __future__ import annotations

import sqlite3

import pytest

from loom.authority._repository import (
    AUTHORITY_REPOSITORY_SCHEMA_VERSION,
    AuthorityRepository,
    AuthorityRepositoryCompatibilityError,
    AuthorityRepositoryCompatibilityKind,
    initialize_authority_repository,
)
from loom.timestamps import utc_now, utc_timestamp


pytestmark = pytest.mark.integration


def test_initialize_repository_creates_private_database_and_identity(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )

    identity = repository.read_identity()

    assert repository.database_path == tmp_path / "authority.sqlite3"
    assert repository.database_path.exists()
    assert identity.schema_version == AUTHORITY_REPOSITORY_SCHEMA_VERSION
    assert identity.service_generation == "generation-1"


def test_reopen_preserves_existing_service_generation(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)
    first = repository.initialize(service_generation="generation-1")

    reopened = AuthorityRepository(tmp_path)
    second = reopened.initialize(service_generation="generation-2")

    assert second.service_generation == first.service_generation
    assert second.service_generation == "generation-1"


def test_transaction_commits_and_rolls_back(tmp_path) -> None:
    repository = initialize_authority_repository(
        tmp_path, service_generation="generation-1"
    )
    with repository.transaction() as conn:
        conn.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    with repository.transaction() as conn:
        conn.execute("INSERT INTO probe(value) VALUES ('committed')")

    with pytest.raises(RuntimeError, match="rollback"):
        with repository.transaction() as conn:
            conn.execute("INSERT INTO probe(value) VALUES ('rolled-back')")
            raise RuntimeError("rollback")

    with sqlite3.connect(repository.database_path) as conn:
        rows = conn.execute("SELECT value FROM probe ORDER BY id").fetchall()
    assert [row[0] for row in rows] == ["committed"]


def test_missing_repository_database_fails_loudly(tmp_path) -> None:
    repository = AuthorityRepository(tmp_path)

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        repository.read_identity()

    assert exc_info.value.failure.kind is AuthorityRepositoryCompatibilityKind.MISSING


def test_newer_repository_schema_is_rejected(tmp_path) -> None:
    _write_metadata(tmp_path, schema_version=999)

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        AuthorityRepository(tmp_path).read_identity()

    assert (
        exc_info.value.failure.kind
        is AuthorityRepositoryCompatibilityKind.UNSUPPORTED_NEWER
    )
    assert exc_info.value.failure.found_version == 999


def test_older_repository_schema_is_rejected(tmp_path) -> None:
    _write_metadata(tmp_path, schema_version=1)

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        AuthorityRepository(tmp_path, schema_version=2).read_identity()

    assert (
        exc_info.value.failure.kind
        is AuthorityRepositoryCompatibilityKind.UNSUPPORTED_OLDER
    )
    assert exc_info.value.failure.found_version == 1


def test_corrupt_repository_database_is_rejected(tmp_path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "authority.sqlite3").write_text("not a sqlite database", encoding="utf-8")

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        AuthorityRepository(tmp_path).read_identity()

    assert exc_info.value.failure.kind is AuthorityRepositoryCompatibilityKind.CORRUPT


def test_incomplete_metadata_is_rejected(tmp_path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(tmp_path / "authority.sqlite3") as conn:
        conn.execute(
            """
            CREATE TABLE repository_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

    with pytest.raises(AuthorityRepositoryCompatibilityError) as exc_info:
        AuthorityRepository(tmp_path).read_identity()

    assert exc_info.value.failure.kind is AuthorityRepositoryCompatibilityKind.MISSING


def _write_metadata(tmp_path, *, schema_version: int) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    timestamp = utc_timestamp(utc_now())
    with sqlite3.connect(tmp_path / "authority.sqlite3") as conn:
        conn.execute(
            """
            CREATE TABLE repository_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO repository_metadata(key, value) VALUES (?, ?)",
            (
                ("schema_version", str(schema_version)),
                ("service_generation", "generation-1"),
                ("created_at", timestamp),
                ("updated_at", timestamp),
            ),
        )
