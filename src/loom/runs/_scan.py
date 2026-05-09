"""Private direct scan helpers for local run collections."""

from __future__ import annotations

from pathlib import Path

from loom.pipeline.stores import (
    CorruptStoreDocumentError,
    LocalRunStore,
    MissingStoreDocumentError,
    RunNotFoundError,
    UnsafeStorePathError,
    path_to_run_uri,
)
from loom.timestamps import utc_timestamp

from ._extract import extract_current_summary_with_warning
from .models import CatalogWarning, CatalogWarningCode, ListRunsResult, RunSummary

_CATALOG_SIDECAR_DIR = ".loom_catalog"


def scan_current_collection(collection_path: str | Path) -> ListRunsResult:
    """Directly scan a local run collection for current run summaries."""

    collection = Path(collection_path)
    warnings: list[CatalogWarning] = []
    summaries: list[RunSummary] = []

    if not collection.exists():
        return ListRunsResult(
            warnings=[
                _warning(
                    CatalogWarningCode.UNREADABLE_RUN,
                    "run collection does not exist",
                    path=collection,
                )
            ],
            checked_at=utc_timestamp(),
        )
    if not collection.is_dir():
        return ListRunsResult(
            warnings=[
                _warning(
                    CatalogWarningCode.INVALID_RUN,
                    "run collection path is not a directory",
                    path=collection,
                )
            ],
            checked_at=utc_timestamp(),
        )

    store = LocalRunStore(root=collection)
    try:
        candidates = _iter_candidates(collection)
    except PermissionError as exc:
        return ListRunsResult(
            warnings=[
                _warning(
                    CatalogWarningCode.UNREADABLE_RUN,
                    str(exc),
                    path=collection,
                )
            ],
            checked_at=utc_timestamp(),
        )

    for candidate in candidates:
        summary, warning = _scan_candidate(store, candidate)
        if summary is not None:
            summaries.append(summary)
        if warning is not None:
            warnings.append(warning)

    return ListRunsResult(
        summaries=tuple(sorted(summaries, key=lambda summary: summary.run_uri)),
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
) -> tuple[RunSummary | None, CatalogWarning | None]:
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
        message = str(exc)
        if "unsupported" in message.lower() and "schema" in message.lower():
            return None, _warning(
                CatalogWarningCode.UNSUPPORTED_SCHEMA,
                "run uses an unsupported schema",
                path=candidate,
            )
        return None, _warning(
            CatalogWarningCode.PARTIAL_RUN,
            f"run metadata is incomplete or invalid: {message}",
            path=candidate,
        )
    return extract_current_summary_with_warning(store, run_uri=run_uri, path=candidate)


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


__all__ = ["scan_current_collection"]
