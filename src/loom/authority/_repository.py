"""Private SQLite repository foundation for the authority service."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError
from loom.timestamps import parse_timestamp, utc_now, utc_timestamp


AUTHORITY_REPOSITORY_SCHEMA_VERSION = 1
AUTHORITY_REPOSITORY_DB_NAME = "authority.sqlite3"
_SQLITE_TIMEOUT_SECONDS = 30.0
_METADATA_TABLE = "repository_metadata"
_REQUIRED_SCHEMA_COLUMNS = {
    _METADATA_TABLE: frozenset({"key", "value"}),
}
_REQUIRED_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "service_generation",
        "created_at",
        "updated_at",
    }
)


class AuthorityRepositoryError(RuntimeError):
    """Base error for private authority repository failures."""


class AuthorityRepositoryCompatibilityKind(StrEnum):
    """Private repository compatibility failure kinds."""

    MISSING = "missing"
    UNSUPPORTED_OLDER = "unsupported_older"
    UNSUPPORTED_NEWER = "unsupported_newer"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class AuthorityRepositoryCompatibilityFailure:
    """Structured compatibility failure for later server/protocol mapping."""

    kind: AuthorityRepositoryCompatibilityKind
    message: str
    found_version: int | None = None
    current_version: int = AUTHORITY_REPOSITORY_SCHEMA_VERSION
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _coerce_kind(self.kind, "kind"),
        )
        object.__setattr__(self, "message", _non_empty(self.message, "message"))
        if self.found_version is not None:
            object.__setattr__(
                self,
                "found_version",
                _positive_int(self.found_version, "found_version"),
            )
        object.__setattr__(
            self,
            "current_version",
            _positive_int(self.current_version, "current_version"),
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    @property
    def code(self) -> str:
        return f"authority_repository_{self.kind.value}"

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind.value,
            "code": self.code,
            "message": self.message,
            "found_version": self.found_version,
            "current_version": self.current_version,
            "detail": dict(self.detail),
        }


class AuthorityRepositoryCompatibilityError(AuthorityRepositoryError):
    """Raised when a private repository is missing or incompatible."""

    def __init__(self, failure: AuthorityRepositoryCompatibilityFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class AuthorityRepositoryIdentity:
    """Stable identity facts for a private authority repository."""

    state_dir: Path
    database_path: Path
    schema_version: int
    service_generation: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_dir", Path(self.state_dir))
        object.__setattr__(self, "database_path", Path(self.database_path))
        object.__setattr__(
            self,
            "schema_version",
            _positive_int(self.schema_version, "schema_version"),
        )
        object.__setattr__(
            self,
            "service_generation",
            _non_empty(self.service_generation, "service_generation"),
        )
        parse_timestamp(self.created_at)
        parse_timestamp(self.updated_at)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "state_dir": str(self.state_dir),
            "database_path": str(self.database_path),
            "schema_version": self.schema_version,
            "service_generation": self.service_generation,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class AuthorityRepository:
    """Private SQLite repository handle for an authority service state dir."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        schema_version: int = AUTHORITY_REPOSITORY_SCHEMA_VERSION,
        database_name: str = AUTHORITY_REPOSITORY_DB_NAME,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.schema_version = _positive_int(schema_version, "schema_version")
        self.database_name = _database_name(database_name)
        self.database_path = self.state_dir / self.database_name

    def initialize(
        self,
        *,
        service_generation: str | None = None,
    ) -> AuthorityRepositoryIdentity:
        generation = (
            _non_empty(service_generation, "service_generation")
            if service_generation is not None
            else generate_service_generation()
        )
        now = utc_timestamp(utc_now())
        try:
            with self._connection(create_parent=True) as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    _initialize_schema(
                        conn,
                        schema_version=self.schema_version,
                        service_generation=generation,
                        timestamp=now,
                    )
                    failure = _compatibility_failure(
                        conn, current_version=self.schema_version
                    )
                    if failure is not None:
                        raise AuthorityRepositoryCompatibilityError(failure)
                    identity = _identity_from_connection(self, conn)
                except Exception:
                    conn.rollback()
                    raise
                else:
                    conn.commit()
                    return identity
        except sqlite3.DatabaseError as exc:
            raise AuthorityRepositoryCompatibilityError(
                _corrupt_failure(
                    "authority repository database is corrupt or unreadable",
                    current_version=self.schema_version,
                )
            ) from exc

    def read_identity(self) -> AuthorityRepositoryIdentity:
        with self._connection(create_parent=False) as conn:
            failure = _compatibility_failure(conn, current_version=self.schema_version)
            if failure is not None:
                raise AuthorityRepositoryCompatibilityError(failure)
            return _identity_from_connection(self, conn)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open an explicit private repository write transaction."""

        with self._connection(create_parent=False) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                failure = _compatibility_failure(
                    conn, current_version=self.schema_version
                )
                if failure is not None:
                    raise AuthorityRepositoryCompatibilityError(failure)
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    @contextmanager
    def _connection(self, *, create_parent: bool) -> Iterator[sqlite3.Connection]:
        if create_parent:
            self.state_dir.mkdir(parents=True, exist_ok=True)
        elif not self.database_path.exists():
            raise AuthorityRepositoryCompatibilityError(
                AuthorityRepositoryCompatibilityFailure(
                    kind=AuthorityRepositoryCompatibilityKind.MISSING,
                    message="authority repository database is missing",
                    current_version=self.schema_version,
                    detail={"database_path": str(self.database_path)},
                )
            )
        conn = sqlite3.connect(
            self.database_path,
            timeout=_SQLITE_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()


def initialize_authority_repository(
    state_dir: str | Path,
    *,
    service_generation: str | None = None,
) -> AuthorityRepository:
    """Initialize and return a private authority repository handle."""

    repository = AuthorityRepository(state_dir)
    repository.initialize(service_generation=service_generation)
    return repository


def generate_service_generation() -> str:
    """Return a new opaque service generation token."""

    return f"authority-generation-{uuid.uuid4().hex}"


def _initialize_schema(
    conn: sqlite3.Connection,
    *,
    schema_version: int,
    service_generation: str,
    timestamp: str,
) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repository_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    _insert_metadata_if_missing(conn, "schema_version", str(schema_version))
    _insert_metadata_if_missing(conn, "service_generation", service_generation)
    _insert_metadata_if_missing(conn, "created_at", timestamp)
    conn.execute(
        """
        INSERT INTO repository_metadata(key, value)
        VALUES ('updated_at', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (timestamp,),
    )


def _insert_metadata_if_missing(
    conn: sqlite3.Connection, key: str, value: str
) -> None:
    conn.execute(
        """
        INSERT INTO repository_metadata(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO NOTHING
        """,
        (key, value),
    )


def _compatibility_failure(
    conn: sqlite3.Connection, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure | None:
    try:
        tables = {
            cast(str, row["name"])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_schema
                WHERE type = 'table'
                """
            )
        }
    except sqlite3.DatabaseError:
        return _corrupt_failure(
            "authority repository database is corrupt or unreadable",
            current_version=current_version,
        )
    if _METADATA_TABLE not in tables:
        return AuthorityRepositoryCompatibilityFailure(
            kind=AuthorityRepositoryCompatibilityKind.MISSING,
            message="authority repository metadata is missing",
            current_version=current_version,
        )
    shape_failure = _schema_shape_failure(conn, current_version=current_version)
    if shape_failure is not None:
        return shape_failure
    metadata = _read_metadata(conn, current_version=current_version)
    if isinstance(metadata, AuthorityRepositoryCompatibilityFailure):
        return metadata
    missing_keys = _REQUIRED_METADATA_KEYS - set(metadata)
    if missing_keys:
        missing_key_values: list[PlainData] = list(sorted(missing_keys))
        return AuthorityRepositoryCompatibilityFailure(
            kind=AuthorityRepositoryCompatibilityKind.MISSING,
            message="authority repository metadata is incomplete",
            current_version=current_version,
            detail={"missing_keys": missing_key_values},
        )
    version_failure = _schema_version_failure(
        metadata["schema_version"], current_version=current_version
    )
    if version_failure is not None:
        return version_failure
    for metadata_field in ("service_generation", "created_at", "updated_at"):
        if not metadata[metadata_field]:
            return _corrupt_failure(
                f"authority repository metadata field {metadata_field!r} is empty",
                current_version=current_version,
            )
    try:
        parse_timestamp(metadata["created_at"])
        parse_timestamp(metadata["updated_at"])
    except ValueError:
        return _corrupt_failure(
            "authority repository timestamps are invalid",
            current_version=current_version,
        )
    return None


def _schema_shape_failure(
    conn: sqlite3.Connection, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure | None:
    try:
        for table_name, expected_columns in _REQUIRED_SCHEMA_COLUMNS.items():
            columns = {
                cast(str, row["name"])
                for row in conn.execute(f"PRAGMA table_info({table_name})")
            }
            if not expected_columns.issubset(columns):
                return _corrupt_failure(
                    "authority repository schema is incomplete or invalid",
                    current_version=current_version,
                )
    except sqlite3.DatabaseError:
        return _corrupt_failure(
            "authority repository schema is corrupt or unreadable",
            current_version=current_version,
        )
    return None


def _read_metadata(
    conn: sqlite3.Connection, *, current_version: int
) -> dict[str, str] | AuthorityRepositoryCompatibilityFailure:
    try:
        return {
            cast(str, row["key"]): cast(str, row["value"])
            for row in conn.execute(
                "SELECT key, value FROM repository_metadata"
            )
        }
    except sqlite3.DatabaseError:
        return _corrupt_failure(
            "authority repository metadata is corrupt or unreadable",
            current_version=current_version,
        )


def _schema_version_failure(
    raw_version: str, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure | None:
    try:
        version = int(raw_version)
    except ValueError:
        return _corrupt_failure(
            "authority repository schema version is invalid",
            current_version=current_version,
        )
    if version <= 0:
        return _corrupt_failure(
            "authority repository schema version is invalid",
            current_version=current_version,
        )
    if version < current_version:
        return AuthorityRepositoryCompatibilityFailure(
            kind=AuthorityRepositoryCompatibilityKind.UNSUPPORTED_OLDER,
            message=(
                f"unsupported older authority repository schema {version}; "
                f"expected {current_version}"
            ),
            found_version=version,
            current_version=current_version,
        )
    if version > current_version:
        return AuthorityRepositoryCompatibilityFailure(
            kind=AuthorityRepositoryCompatibilityKind.UNSUPPORTED_NEWER,
            message=(
                f"unsupported newer authority repository schema {version}; "
                f"this Loom version supports {current_version}"
            ),
            found_version=version,
            current_version=current_version,
        )
    return None


def _identity_from_connection(
    repository: AuthorityRepository, conn: sqlite3.Connection
) -> AuthorityRepositoryIdentity:
    metadata = _read_metadata(conn, current_version=repository.schema_version)
    if isinstance(metadata, AuthorityRepositoryCompatibilityFailure):
        raise AuthorityRepositoryCompatibilityError(metadata)
    return AuthorityRepositoryIdentity(
        state_dir=repository.state_dir,
        database_path=repository.database_path,
        schema_version=int(metadata["schema_version"]),
        service_generation=metadata["service_generation"],
        created_at=metadata["created_at"],
        updated_at=metadata["updated_at"],
    )


def _corrupt_failure(
    message: str, *, current_version: int
) -> AuthorityRepositoryCompatibilityFailure:
    return AuthorityRepositoryCompatibilityFailure(
        kind=AuthorityRepositoryCompatibilityKind.CORRUPT,
        message=message,
        current_version=current_version,
    )


def _coerce_kind(
    value: object, field: str
) -> AuthorityRepositoryCompatibilityKind:
    if isinstance(value, AuthorityRepositoryCompatibilityKind):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    try:
        return AuthorityRepositoryCompatibilityKind(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field} {value!r}") from exc


def _database_name(value: object) -> str:
    name = _non_empty(value, "database_name")
    if Path(name).name != name:
        raise ValueError("database_name must not include path separators")
    return name


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise ValueError(f"{field} must contain plain data") from exc
    if not isinstance(normalized, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


__all__ = [
    "AUTHORITY_REPOSITORY_DB_NAME",
    "AUTHORITY_REPOSITORY_SCHEMA_VERSION",
    "AuthorityRepository",
    "AuthorityRepositoryCompatibilityError",
    "AuthorityRepositoryCompatibilityFailure",
    "AuthorityRepositoryCompatibilityKind",
    "AuthorityRepositoryError",
    "AuthorityRepositoryIdentity",
    "generate_service_generation",
    "initialize_authority_repository",
]
