"""Private direct scan helpers for local run collections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from loom.pipeline.stores import (
    CorruptStoreDocumentError,
    LocalRunStore,
    MissingStoreDocumentError,
    PerRunAuthorityStore,
    RunNotFoundError,
    UnsafeStorePathError,
    path_to_run_uri,
)
from loom.pipeline.stores.schema_policy import AuthoritySchemaFailureKind
from loom.timestamps import utc_timestamp

from ._extract import CurrentRunSummary, extract_current_summary_with_warning_record
from .models import CatalogWarning, CatalogWarningCode, ListRunsResult

_CATALOG_SIDECAR_DIR = ".loom_catalog"


@dataclass(frozen=True, slots=True)
class CurrentCatalogScan:
    """Private direct-scan result with freshness evidence for indexed rebuilds."""

    records: tuple[CurrentRunSummary, ...] = ()
    warnings: tuple[CatalogWarning, ...] = ()
    checked_at: str | None = None


def scan_current_collection(collection_path: str | Path) -> ListRunsResult:
    """Directly scan a local run collection for current run summaries."""

    scan = scan_current_collection_records(collection_path)
    return ListRunsResult(
        summaries=tuple(record.summary for record in scan.records),
        warnings=scan.warnings,
        checked_at=scan.checked_at,
    )


def scan_current_collection_records(collection_path: str | Path) -> CurrentCatalogScan:
    """Directly scan a local run collection with private freshness evidence."""

    collection = Path(collection_path)
    warnings: list[CatalogWarning] = []
    records: list[CurrentRunSummary] = []

    if not collection.exists():
        return CurrentCatalogScan(
            warnings=(
                _warning(
                    CatalogWarningCode.UNREADABLE_RUN,
                    "run collection does not exist",
                    path=collection,
                ),
            ),
            checked_at=utc_timestamp(),
        )
    if not collection.is_dir():
        return CurrentCatalogScan(
            warnings=(
                _warning(
                    CatalogWarningCode.INVALID_RUN,
                    "run collection path is not a directory",
                    path=collection,
                ),
            ),
            checked_at=utc_timestamp(),
        )

    store = LocalRunStore(root=collection)
    try:
        candidates = _iter_candidates(collection)
    except PermissionError as exc:
        return CurrentCatalogScan(
            warnings=(
                _warning(
                    CatalogWarningCode.UNREADABLE_RUN,
                    str(exc),
                    path=collection,
                ),
            ),
            checked_at=utc_timestamp(),
        )

    for candidate in candidates:
        record, warning = _scan_candidate(store, candidate)
        if record is not None:
            records.append(record)
        if warning is not None:
            warnings.append(warning)

    return CurrentCatalogScan(
        records=tuple(sorted(records, key=lambda record: record.summary.run_uri)),
        warnings=tuple(warnings),
        checked_at=utc_timestamp(),
    )


def _iter_candidates(collection: Path) -> tuple[Path, ...]:
    try:
        children = collection.iterdir()
        return tuple(
            sorted(
                (child for child in children if child.name != _CATALOG_SIDECAR_DIR),
                key=lambda path: path.name,
            )
        )
    except PermissionError as exc:
        raise PermissionError(f"run collection is unreadable: {collection}") from exc


def _scan_candidate(
    store: LocalRunStore, candidate: Path
) -> tuple[CurrentRunSummary | None, CatalogWarning | None]:
    if not candidate.exists():
        return None, _warning(
            CatalogWarningCode.DISAPPEARED_RUN,
            "run candidate disappeared during scan",
            path=candidate,
        )
    if not candidate.is_dir():
        return None, _warning(
            CatalogWarningCode.INVALID_RUN,
            "run candidate is not a directory",
            path=candidate,
        )
    if not (candidate / "run.json").exists():
        return None, _warning(
            CatalogWarningCode.INVALID_RUN,
            "run candidate has no run metadata marker",
            path=candidate,
        )

    run_uri = path_to_run_uri(candidate)
    try:
        store.open_run(run_uri)
    except PermissionError as exc:
        return None, _warning(
            CatalogWarningCode.UNREADABLE_RUN,
            f"run is unreadable: {exc}",
            path=candidate,
        )
    except (RunNotFoundError, MissingStoreDocumentError):
        return None, _warning(
            CatalogWarningCode.DISAPPEARED_RUN,
            "run disappeared during scan",
            path=candidate,
        )
    except (CorruptStoreDocumentError, UnsafeStorePathError, OSError) as exc:
        return None, _warning_for_store_exception(exc, path=candidate)
    try:
        authority_store = _authority_store_for_candidate(run_uri)
    except (CorruptStoreDocumentError, OSError) as exc:
        return None, _warning_for_store_exception(exc, path=candidate)
    if authority_store is not None:
        from loom.pipeline.execution.authority_adapter import (
            create_authority_backed_serial_run_store,
        )

        return extract_current_summary_with_warning_record(
            create_authority_backed_serial_run_store(
                store.root,
                authority_store=authority_store,
            ),
            run_uri=run_uri,
            path=candidate,
        )
    return extract_current_summary_with_warning_record(
        store, run_uri=run_uri, path=candidate
    )


def _warning_for_store_exception(
    exc: BaseException, *, path: Path
) -> CatalogWarning:
    message = str(exc)
    lowered = message.lower()
    if isinstance(exc, PermissionError):
        return _warning(
            CatalogWarningCode.UNREADABLE_RUN,
            f"run is unreadable: {message}",
            path=path,
        )
    if "unsupported" in lowered and "schema" in lowered:
        return _warning(
            CatalogWarningCode.UNSUPPORTED_SCHEMA,
            "run uses an unsupported schema",
            path=path,
        )
    return _warning(
        CatalogWarningCode.PARTIAL_RUN,
        f"run metadata is incomplete or invalid: {message}",
        path=path,
    )


def _authority_store_for_candidate(run_uri: str) -> PerRunAuthorityStore | None:
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

    authority_store = SQLitePerRunAuthorityStore()
    check = authority_store.check_schema(run_uri)
    if check.failure is None:
        return cast(PerRunAuthorityStore, authority_store)
    if check.failure.kind is AuthoritySchemaFailureKind.MISSING:
        return None
    raise CorruptStoreDocumentError(check.failure.message)


def _warning(
    code: CatalogWarningCode,
    message: str,
    *,
    path: Path | None = None,
) -> CatalogWarning:
    return CatalogWarning(
        code=code,
        message=message,
        path=None if path is None else str(path),
    )


__all__ = [
    "CurrentCatalogScan",
    "scan_current_collection",
    "scan_current_collection_records",
]
