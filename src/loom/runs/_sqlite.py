"""Private SQLite sidecar storage for run catalog rebuilds."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from loom.serialization import PlainData, json_loads, stable_json_dumps
from loom.serialization.errors import DeserializationError, PlainDataError
from loom.timestamps import utc_timestamp

from ._extract import CurrentRunSummary
from ._scan import scan_current_collection_records
from .errors import CatalogStorageError
from .models import (
    ArtifactSummary,
    CatalogIndexResult,
    RunFilterKind,
    RunSummary,
    StageSummary,
    SubmittedOperationSummary,
)

CATALOG_SIDECAR_DIR = ".loom_catalog"
CATALOG_DB_FILENAME = "catalog.sqlite"
CATALOG_SCHEMA_VERSION = 1
_BUSY_TIMEOUT_MS = 5000


class _RecoverableCatalogDatabaseError(CatalogStorageError):
    """Raised when deleting the derived DB and rebuilding is safe."""


def catalog_sidecar_dir(collection_path: str | Path) -> Path:
    """Return the private sidecar directory for a local run collection."""

    return Path(collection_path) / CATALOG_SIDECAR_DIR


def catalog_db_path(collection_path: str | Path) -> Path:
    """Return the private SQLite DB path for a local run collection."""

    return catalog_sidecar_dir(collection_path) / CATALOG_DB_FILENAME


def rebuild_catalog(collection_path: str | Path) -> CatalogIndexResult:
    """Rebuild the derived catalog DB from authoritative run-store metadata."""

    collection = Path(collection_path)
    scan = scan_current_collection_records(collection)
    if collection.is_dir():
        _replace_catalog_records(collection, scan.records, checked_at=scan.checked_at)
    return CatalogIndexResult(
        indexed_count=len(scan.records),
        skipped_count=len(scan.warnings),
        warnings=scan.warnings,
        checked_at=scan.checked_at,
    )


def read_catalog_summaries(collection_path: str | Path) -> tuple[RunSummary, ...]:
    """Return summaries from the private sidecar.

    This helper is private and exists for internal Phase 4 reads and storage tests.
    """

    db_path = catalog_db_path(collection_path)
    if not db_path.exists():
        return ()

    sqlite = _sqlite3()
    try:
        with _connect(db_path) as connection:
            _ensure_schema(connection)
            rows = connection.execute(
                "SELECT summary_json FROM run_summaries ORDER BY run_uri"
            ).fetchall()
    except sqlite.DatabaseError as exc:
        raise CatalogStorageError(f"unable to read catalog sidecar: {exc}") from exc
    return tuple(_run_summary_from_json(row[0]) for row in rows)


def _replace_catalog_records(
    collection_path: Path,
    records: Sequence[CurrentRunSummary],
    *,
    checked_at: str | None,
) -> None:
    db_path = catalog_db_path(collection_path)
    sqlite = _sqlite3()

    for attempt in range(2):
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with _connect(db_path) as connection:
                _ensure_schema(connection)
                _replace_records(connection, records, checked_at=checked_at)
            return
        except _RecoverableCatalogDatabaseError:
            if attempt == 0:
                _delete_catalog_files(db_path)
                continue
            raise
        except sqlite.DatabaseError as exc:
            if attempt == 0 and _is_recoverable_database_error(exc):
                _delete_catalog_files(db_path)
                continue
            raise CatalogStorageError(
                f"unable to rebuild catalog sidecar: {exc}"
            ) from exc
        except OSError as exc:
            raise CatalogStorageError(f"unable to access catalog sidecar: {exc}") from exc


def _connect(db_path: Path) -> Any:
    sqlite = _sqlite3()
    connection = sqlite.connect(str(db_path), timeout=_BUSY_TIMEOUT_MS / 1000)
    connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    try:
        connection.execute("PRAGMA journal_mode=WAL")
    except sqlite.DatabaseError:
        # WAL is best-effort. SQLite may reject it on some filesystems.
        pass
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_schema(connection: Any) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    row = connection.execute(
        "SELECT value FROM catalog_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        _create_schema(connection)
        connection.execute(
            """
            INSERT OR REPLACE INTO catalog_metadata(key, value)
            VALUES('schema_version', ?)
            """,
            (str(CATALOG_SCHEMA_VERSION),),
        )
        connection.commit()
        return
    if row[0] != str(CATALOG_SCHEMA_VERSION):
        raise _RecoverableCatalogDatabaseError(
            "catalog sidecar uses an incompatible schema version"
        )
    _create_schema(connection)
    connection.commit()


def _create_schema(connection: Any) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS run_summaries (
            run_uri TEXT PRIMARY KEY,
            summary_json TEXT NOT NULL,
            path TEXT,
            display_name TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            metadata_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            config_fingerprint TEXT,
            pipeline_fingerprint TEXT,
            git_commit TEXT,
            executor TEXT,
            backend TEXT,
            freshness_token TEXT NOT NULL,
            freshness_updated_at TEXT NOT NULL,
            freshness_revision INTEGER NOT NULL,
            indexed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stage_summaries (
            run_uri TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            status TEXT,
            attempt INTEGER,
            fingerprint TEXT,
            started_at TEXT,
            finished_at TEXT,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY(run_uri, stage_name),
            FOREIGN KEY(run_uri) REFERENCES run_summaries(run_uri)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS artifact_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_uri TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            logical_name TEXT,
            uri TEXT,
            artifact_type TEXT,
            checksum TEXT,
            fingerprint TEXT,
            producer_stage TEXT,
            metadata_json TEXT NOT NULL,
            FOREIGN KEY(run_uri) REFERENCES run_summaries(run_uri)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS submitted_operations (
            run_uri TEXT NOT NULL,
            submission_id TEXT NOT NULL,
            backend TEXT NOT NULL,
            mode TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            active INTEGER NOT NULL,
            summary_counts_json TEXT NOT NULL,
            PRIMARY KEY(run_uri, submission_id),
            FOREIGN KEY(run_uri) REFERENCES run_summaries(run_uri)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS filter_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_uri TEXT NOT NULL,
            kind TEXT NOT NULL,
            key TEXT,
            value TEXT NOT NULL,
            FOREIGN KEY(run_uri) REFERENCES run_summaries(run_uri)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_filter_facts_lookup
            ON filter_facts(kind, key, value, run_uri);
        CREATE INDEX IF NOT EXISTS idx_stage_status
            ON stage_summaries(stage_name, status, run_uri);
        CREATE INDEX IF NOT EXISTS idx_artifact_identity
            ON artifact_summaries(artifact_id, checksum, run_uri);
        CREATE INDEX IF NOT EXISTS idx_run_status
            ON run_summaries(status, run_uri);
        """
    )


def _replace_records(
    connection: Any,
    records: Sequence[CurrentRunSummary],
    *,
    checked_at: str | None,
) -> None:
    indexed_at = checked_at or utc_timestamp()
    connection.execute("BEGIN IMMEDIATE")
    try:
        for table in (
            "filter_facts",
            "submitted_operations",
            "artifact_summaries",
            "stage_summaries",
            "run_summaries",
        ):
            connection.execute(f"DELETE FROM {table}")
        connection.execute(
            """
            INSERT OR REPLACE INTO catalog_metadata(key, value)
            VALUES('last_rebuild_at', ?)
            """,
            (indexed_at,),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO catalog_metadata(key, value)
            VALUES('last_checked_at', ?)
            """,
            (checked_at or indexed_at,),
        )
        for record in records:
            _insert_record(connection, record, indexed_at=indexed_at)
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def _insert_record(
    connection: Any, record: CurrentRunSummary, *, indexed_at: str
) -> None:
    summary = record.summary
    freshness = record.freshness
    summary_data = summary.to_dict()
    connection.execute(
        """
        INSERT INTO run_summaries(
            run_uri,
            summary_json,
            path,
            display_name,
            status,
            created_at,
            updated_at,
            started_at,
            finished_at,
            metadata_json,
            tags_json,
            config_fingerprint,
            pipeline_fingerprint,
            git_commit,
            executor,
            backend,
            freshness_token,
            freshness_updated_at,
            freshness_revision,
            indexed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            summary.run_uri,
            _json(summary_data),
            summary.path,
            summary.display_name,
            summary.status,
            summary.created_at,
            summary.updated_at,
            summary.started_at,
            summary.finished_at,
            _json(summary_data["metadata"]),
            _json(summary_data["tags"]),
            summary.config_fingerprint,
            summary.pipeline_fingerprint,
            summary.git_commit,
            summary.executor,
            summary.backend,
            freshness.token,
            freshness.updated_at,
            freshness.revision,
            indexed_at,
        ),
    )
    for stage in summary.stages:
        _insert_stage(connection, summary.run_uri, stage)
    for artifact in summary.artifacts:
        _insert_artifact(connection, summary.run_uri, artifact)
    for operation in summary.submitted_operations:
        _insert_submitted_operation(connection, summary.run_uri, operation)
    for kind, key, value in _filter_facts(summary):
        connection.execute(
            """
            INSERT INTO filter_facts(run_uri, kind, key, value)
            VALUES (?, ?, ?, ?)
            """,
            (summary.run_uri, kind, key, value),
        )


def _insert_stage(connection: Any, run_uri: str, stage: StageSummary) -> None:
    stage_data = stage.to_dict()
    connection.execute(
        """
        INSERT INTO stage_summaries(
            run_uri,
            stage_name,
            status,
            attempt,
            fingerprint,
            started_at,
            finished_at,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_uri,
            stage.stage_name,
            stage.status,
            stage.attempt,
            stage.fingerprint,
            stage.started_at,
            stage.finished_at,
            _json(stage_data["metadata"]),
        ),
    )


def _insert_artifact(
    connection: Any, run_uri: str, artifact: ArtifactSummary
) -> None:
    artifact_data = artifact.to_dict()
    connection.execute(
        """
        INSERT INTO artifact_summaries(
            run_uri,
            artifact_id,
            logical_name,
            uri,
            artifact_type,
            checksum,
            fingerprint,
            producer_stage,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_uri,
            artifact.artifact_id,
            artifact.logical_name,
            artifact.uri,
            artifact.artifact_type,
            artifact.checksum,
            artifact.fingerprint,
            artifact.producer_stage,
            _json(artifact_data["metadata"]),
        ),
    )


def _insert_submitted_operation(
    connection: Any, run_uri: str, operation: SubmittedOperationSummary
) -> None:
    operation_data = operation.to_dict()
    connection.execute(
        """
        INSERT INTO submitted_operations(
            run_uri,
            submission_id,
            backend,
            mode,
            state,
            created_at,
            updated_at,
            active,
            summary_counts_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_uri,
            operation.submission_id,
            operation.backend,
            operation.mode,
            operation.state,
            operation.created_at,
            operation.updated_at,
            int(operation.active),
            _json(operation_data["summary_counts"]),
        ),
    )


def _filter_facts(summary: RunSummary) -> Iterable[tuple[str, str | None, str]]:
    if summary.status is not None:
        yield (RunFilterKind.RUN_STATUS.value, None, summary.status)
    for key, value in sorted(summary.tags.items()):
        yield (RunFilterKind.TAG.value, key, value)
    for kind, value in (
        (RunFilterKind.CONFIG_FINGERPRINT, summary.config_fingerprint),
        (RunFilterKind.PIPELINE_FINGERPRINT, summary.pipeline_fingerprint),
        (RunFilterKind.GIT_COMMIT, summary.git_commit),
        (RunFilterKind.EXECUTOR, summary.executor),
        (RunFilterKind.BACKEND, summary.backend),
    ):
        if value is not None:
            yield (kind.value, None, value)
    for stage in summary.stages:
        if stage.status is not None:
            yield (RunFilterKind.STAGE_STATUS.value, stage.stage_name, stage.status)
    for artifact in summary.artifacts:
        artifact_key = artifact.logical_name or artifact.artifact_id
        yield (RunFilterKind.ARTIFACT_IDENTITY.value, artifact_key, artifact.artifact_id)
        if artifact.checksum is not None:
            yield (
                RunFilterKind.ARTIFACT_CHECKSUM.value,
                artifact_key,
                artifact.checksum,
            )


def _delete_catalog_files(db_path: Path) -> None:
    for path in (
        db_path,
        db_path.with_name(f"{db_path.name}-wal"),
        db_path.with_name(f"{db_path.name}-shm"),
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _is_recoverable_database_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "locked" in text or "readonly" in text or "permission" in text:
        return False
    return any(
        marker in text
        for marker in (
            "file is not a database",
            "database disk image is malformed",
            "malformed",
            "no such table",
            "no column named",
            "has no column",
        )
    )


def _json(value: object) -> str:
    return stable_json_dumps(value)


def _run_summary_from_json(text: str) -> RunSummary:
    data = json_loads(text, path="summary_json")
    if not isinstance(data, Mapping):
        raise CatalogStorageError("catalog summary payload is not a mapping")
    return _run_summary_from_data(data)


def _run_summary_from_data(data: Mapping[str, PlainData]) -> RunSummary:
    try:
        stages = _mapping_sequence(data.get("stages"), "stages")
        artifacts = _mapping_sequence(data.get("artifacts"), "artifacts")
        submitted_operations = _mapping_sequence(
            data.get("submitted_operations"), "submitted_operations"
        )
        return RunSummary(
            run_uri=_require_str(data, "run_uri"),
            status=_optional_str(data.get("status"), "status"),
            display_name=_optional_str(data.get("display_name"), "display_name"),
            path=_optional_str(data.get("path"), "path"),
            created_at=_optional_str(data.get("created_at"), "created_at"),
            updated_at=_optional_str(data.get("updated_at"), "updated_at"),
            started_at=_optional_str(data.get("started_at"), "started_at"),
            finished_at=_optional_str(data.get("finished_at"), "finished_at"),
            metadata=_plain_mapping(data.get("metadata"), "metadata"),
            tags=_str_mapping(data.get("tags"), "tags"),
            config_fingerprint=_optional_str(
                data.get("config_fingerprint"), "config_fingerprint"
            ),
            pipeline_fingerprint=_optional_str(
                data.get("pipeline_fingerprint"), "pipeline_fingerprint"
            ),
            git_commit=_optional_str(data.get("git_commit"), "git_commit"),
            executor=_optional_str(data.get("executor"), "executor"),
            backend=_optional_str(data.get("backend"), "backend"),
            stages=tuple(_stage_from_data(stage) for stage in stages),
            artifacts=tuple(_artifact_from_data(artifact) for artifact in artifacts),
            submitted_operations=tuple(
                _submitted_operation_from_data(operation)
                for operation in submitted_operations
            ),
        )
    except (DeserializationError, PlainDataError, TypeError, ValueError) as exc:
        raise CatalogStorageError(f"invalid catalog summary payload: {exc}") from exc


def _stage_from_data(data: Mapping[str, PlainData]) -> StageSummary:
    return StageSummary(
        stage_name=_require_str(data, "stage_name"),
        status=_optional_str(data.get("status"), "status"),
        attempt=_optional_int(data.get("attempt"), "attempt"),
        fingerprint=_optional_str(data.get("fingerprint"), "fingerprint"),
        started_at=_optional_str(data.get("started_at"), "started_at"),
        finished_at=_optional_str(data.get("finished_at"), "finished_at"),
        metadata=_plain_mapping(data.get("metadata"), "metadata"),
    )


def _artifact_from_data(data: Mapping[str, PlainData]) -> ArtifactSummary:
    return ArtifactSummary(
        run_uri=_require_str(data, "run_uri"),
        artifact_id=_require_str(data, "artifact_id"),
        logical_name=_optional_str(data.get("logical_name"), "logical_name"),
        uri=_optional_str(data.get("uri"), "uri"),
        artifact_type=_optional_str(data.get("artifact_type"), "artifact_type"),
        checksum=_optional_str(data.get("checksum"), "checksum"),
        fingerprint=_optional_str(data.get("fingerprint"), "fingerprint"),
        producer_stage=_optional_str(data.get("producer_stage"), "producer_stage"),
        metadata=_plain_mapping(data.get("metadata"), "metadata"),
    )


def _submitted_operation_from_data(
    data: Mapping[str, PlainData],
) -> SubmittedOperationSummary:
    return SubmittedOperationSummary(
        submission_id=_require_str(data, "submission_id"),
        backend=_require_str(data, "backend"),
        mode=_require_str(data, "mode"),
        state=_require_str(data, "state"),
        created_at=_require_str(data, "created_at"),
        updated_at=_require_str(data, "updated_at"),
        active=_require_bool(data.get("active"), "active"),
        summary_counts=_int_mapping(data.get("summary_counts"), "summary_counts"),
    )


def _mapping_sequence(value: object, field: str) -> tuple[Mapping[str, PlainData], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CatalogStorageError(f"{field} must be a sequence")
    output: list[Mapping[str, PlainData]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise CatalogStorageError(f"{field}[{index}] must be a mapping")
        output.append(cast(Mapping[str, PlainData], item))
    return tuple(output)


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CatalogStorageError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], value)


def _str_mapping(value: object, field: str) -> Mapping[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CatalogStorageError(f"{field} must be a mapping")
    output: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise CatalogStorageError(f"{field} must map strings to strings")
        output[key] = item
    return output


def _int_mapping(value: object, field: str) -> Mapping[str, int]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CatalogStorageError(f"{field} must be a mapping")
    output: dict[str, int] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not isinstance(item, int)
            or isinstance(item, bool)
        ):
            raise CatalogStorageError(f"{field} must map strings to integers")
        output[key] = item
    return output


def _require_str(data: Mapping[str, PlainData], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise CatalogStorageError(f"{field} must be a non-empty string")
    return value


def _optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CatalogStorageError(f"{field} must be a non-empty string or None")
    return value


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise CatalogStorageError(f"{field} must be an integer or None")
    return value


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogStorageError(f"{field} must be a bool")
    return value


def _sqlite3() -> ModuleType:
    import sqlite3

    return sqlite3


__all__ = [
    "CATALOG_DB_FILENAME",
    "CATALOG_SCHEMA_VERSION",
    "CATALOG_SIDECAR_DIR",
    "catalog_db_path",
    "catalog_sidecar_dir",
    "read_catalog_summaries",
    "rebuild_catalog",
]
