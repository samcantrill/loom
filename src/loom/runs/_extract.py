"""Private direct run-summary extraction helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from loom.artifacts import ArtifactRef
from loom.state_sources import local_materialization_source
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.pipeline.stores import (
    CorruptStoreDocumentError,
    LocalRunStore,
    MissingStoreDocumentError,
    RunFreshnessRecord,
    RunNotFoundError,
    UnsafeStorePathError,
)
from loom.serialization import PlainData

from .models import (
    ArtifactSummary,
    CatalogWarning,
    CatalogWarningCode,
    RunSummary,
    StageSummary,
    SubmittedOperationSummary,
)

_MAX_FRESHNESS_RETRIES = 1


@dataclass(frozen=True, slots=True)
class CurrentRunSummary:
    """Private current summary paired with the freshness evidence it validated."""

    summary: RunSummary
    freshness: RunFreshnessRecord


class _SummaryStore(Protocol):
    def read_run_freshness(self, run_uri: str) -> RunFreshnessRecord | None: ...

    def read_run_document(self, run_uri: str) -> dict[str, PlainData]: ...

    def read_run_user_metadata(self, run_uri: str) -> dict[str, PlainData]: ...

    def read_run_status(self, run_uri: str) -> RunStatusRecord | None: ...

    def read_runtime_metadata(self, run_uri: str) -> dict[str, PlainData] | None: ...

    def read_composition_manifest(
        self, run_uri: str
    ) -> dict[str, PlainData] | None: ...

    def read_plan(self, run_uri: str) -> dict[str, PlainData] | None: ...

    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None: ...

    def list_run_stages(self, run_uri: str) -> tuple[str, ...]: ...

    def read_stage_status(
        self, run_uri: str, stage_name: str
    ) -> StageStatusRecord | None: ...

    def read_stage_fingerprint(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None: ...

    def read_artifact_index(self, run_uri: str) -> dict[str, ArtifactRef]: ...

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]: ...


def extract_current_summary(
    store: _SummaryStore,
    *,
    run_uri: str,
    path: Path,
    max_retries: int = _MAX_FRESHNESS_RETRIES,
) -> tuple[RunSummary | None, CatalogWarning | None]:
    """Extract one summary only when run-store freshness is stable."""

    record, warning = extract_current_summary_record(
        store, run_uri=run_uri, path=path, max_retries=max_retries
    )
    if record is None:
        return None, warning
    return record.summary, warning


def extract_current_summary_record(
    store: _SummaryStore,
    *,
    run_uri: str,
    path: Path,
    max_retries: int = _MAX_FRESHNESS_RETRIES,
) -> tuple[CurrentRunSummary | None, CatalogWarning | None]:
    """Extract one private summary record only when run-store freshness is stable."""

    for _ in range(max_retries + 1):
        before = store.read_run_freshness(run_uri)
        if before is None:
            return None, _warning(
                CatalogWarningCode.PARTIAL_RUN,
                "run has no freshness metadata",
                run_uri=run_uri,
                path=path,
            )
        summary = _extract_summary(store, run_uri=run_uri, path=path)
        after = store.read_run_freshness(run_uri)
        if after is None:
            return None, _warning(
                CatalogWarningCode.PARTIAL_RUN,
                "run freshness metadata disappeared during extraction",
                run_uri=run_uri,
                path=path,
            )
        if before.token == after.token and before.revision == after.revision:
            return CurrentRunSummary(summary=summary, freshness=after), None

    return None, _warning(
        CatalogWarningCode.ACTIVELY_CHANGING_RUN,
        "run changed while catalog summary was being extracted",
        run_uri=run_uri,
        path=path,
    )


def extract_current_summary_with_warning(
    store: LocalRunStore,
    *,
    run_uri: str,
    path: Path,
) -> tuple[RunSummary | None, CatalogWarning | None]:
    """Extract one local run summary and convert ordinary store errors to warnings."""

    record, warning = extract_current_summary_with_warning_record(
        store, run_uri=run_uri, path=path
    )
    if record is None:
        return None, warning
    return record.summary, warning


def extract_current_summary_with_warning_record(
    store: _SummaryStore,
    *,
    run_uri: str,
    path: Path,
) -> tuple[CurrentRunSummary | None, CatalogWarning | None]:
    """Extract one private local summary record and convert store errors to warnings."""

    try:
        return extract_current_summary_record(store, run_uri=run_uri, path=path)
    except FileNotFoundError:
        return None, _warning(
            CatalogWarningCode.DISAPPEARED_RUN,
            "run disappeared during scan",
            run_uri=run_uri,
            path=path,
        )
    except PermissionError as exc:
        return None, _warning(
            CatalogWarningCode.UNREADABLE_RUN,
            f"run is unreadable: {exc}",
            run_uri=run_uri,
            path=path,
        )
    except (RunNotFoundError, MissingStoreDocumentError):
        return None, _warning(
            CatalogWarningCode.DISAPPEARED_RUN,
            "run disappeared during scan",
            run_uri=run_uri,
            path=path,
        )
    except (CorruptStoreDocumentError, UnsafeStorePathError, OSError) as exc:
        return None, _warning_for_exception(exc, run_uri=run_uri, path=path)


def _extract_summary(store: _SummaryStore, *, run_uri: str, path: Path) -> RunSummary:
    run_document = store.read_run_document(run_uri)
    user_metadata = store.read_run_user_metadata(run_uri)
    run_status = store.read_run_status(run_uri)
    runtime = store.read_runtime_metadata(run_uri) or {}
    composition = store.read_composition_manifest(run_uri) or {}
    plan = store.read_plan(run_uri) or {}
    git = store.read_provenance_document(run_uri, "git") or {}
    artifacts = store.read_artifact_index(run_uri)
    submitted_operations = tuple(store.list_submitted_operations(run_uri))
    state_source = _summary_state_source(store, run_uri=run_uri, path=path)

    return RunSummary(
        run_uri=run_uri,
        status=None if run_status is None else run_status.status.value,
        display_name=path.name,
        path=str(path),
        created_at=_string_or_none(run_document.get("created_at")),
        updated_at=None if run_status is None else run_status.updated_at,
        started_at=None if run_status is None else run_status.started_at,
        finished_at=None if run_status is None else run_status.finished_at,
        metadata=user_metadata,
        tags=_extract_tags(user_metadata, runtime),
        config_fingerprint=_first_string(
            composition,
            "config_fingerprint",
            "fingerprint",
            "artifact_fingerprint",
            "content_fingerprint",
        ),
        pipeline_fingerprint=_first_string(
            plan,
            "pipeline_fingerprint",
            "fingerprint",
            "plan_fingerprint",
        ),
        git_commit=_first_string(git, "commit", "sha", "head_commit", "revision"),
        executor=_first_string(runtime, "executor")
        or _first_string(user_metadata, "executor"),
        backend=_first_string(runtime, "backend")
        or _first_submitted_backend(submitted_operations),
        state_source=state_source,
        stages=_extract_stages(store, run_uri, state_source=state_source),
        artifacts=tuple(
            _artifact_summary(
                run_uri,
                logical_name,
                artifact,
                state_source=state_source,
            )
            for logical_name, artifact in sorted(artifacts.items())
        ),
        submitted_operations=tuple(
            SubmittedOperationSummary(
                submission_id=operation.submission_id,
                backend=operation.backend,
                mode=operation.mode,
                state=operation.state.value,
                created_at=operation.created_at,
                updated_at=operation.updated_at,
                active=operation.active,
                summary_counts=operation.summary_counts,
                state_source=state_source,
            )
            for operation in submitted_operations
        ),
    )


def _extract_stages(
    store: _SummaryStore,
    run_uri: str,
    *,
    state_source: Mapping[str, PlainData],
) -> tuple[StageSummary, ...]:
    summaries: list[StageSummary] = []
    for stage_name in store.list_run_stages(run_uri):
        status = store.read_stage_status(run_uri, stage_name)
        fingerprint = store.read_stage_fingerprint(run_uri, stage_name) or {}
        summaries.append(
            StageSummary(
                stage_name=stage_name,
                status=None if status is None else status.status.value,
                attempt=None if status is None else status.attempt,
                fingerprint=_first_string(fingerprint, "fingerprint", "digest"),
                started_at=None if status is None else status.started_at,
                finished_at=None if status is None else status.finished_at,
                metadata={} if status is None else status.metadata,
                state_source=state_source,
            )
        )
    return tuple(summaries)


def _artifact_summary(
    run_uri: str,
    logical_name: str,
    artifact: ArtifactRef,
    *,
    state_source: Mapping[str, PlainData],
) -> ArtifactSummary:
    return ArtifactSummary(
        run_uri=run_uri,
        artifact_id=artifact.artifact_id,
        logical_name=logical_name,
        uri=artifact.uri,
        artifact_type=artifact.artifact_type,
        checksum=artifact.checksum,
        fingerprint=artifact.fingerprint,
        producer_stage=artifact.producer_stage,
        metadata=artifact.metadata,
        state_source=state_source,
    )


def _summary_state_source(
    store: _SummaryStore,
    *,
    run_uri: str,
    path: Path,
) -> Mapping[str, PlainData]:
    source = getattr(store, "summary_state_source", None)
    if callable(source):
        raw_source = source(run_uri)
        if isinstance(raw_source, Mapping):
            return cast(Mapping[str, PlainData], raw_source)
    return local_materialization_source(path=str(path))


def _extract_tags(
    user_metadata: Mapping[str, PlainData], runtime: Mapping[str, PlainData]
) -> Mapping[str, str]:
    tags: dict[str, str] = {}
    for source in (runtime.get("tags"), user_metadata.get("tags")):
        if not isinstance(source, Mapping):
            continue
        for key, value in source.items():
            if isinstance(key, str) and key and isinstance(value, str) and value:
                tags[key] = value
    return tags


def _first_string(mapping: Mapping[str, PlainData], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _first_submitted_backend(
    submitted_operations: tuple[SubmittedOperationRecord, ...],
) -> str | None:
    if not submitted_operations:
        return None
    backend = getattr(submitted_operations[0], "backend", None)
    return backend if isinstance(backend, str) and backend else None


def _warning_for_exception(
    exc: BaseException, *, run_uri: str | None, path: Path
) -> CatalogWarning:
    text = str(exc)
    lowered = text.lower()
    if "unsupported schema_version" in lowered or "schema_version" in lowered:
        code = CatalogWarningCode.UNSUPPORTED_SCHEMA
        message = "run uses an unsupported schema"
    elif isinstance(exc, PermissionError):
        code = CatalogWarningCode.UNREADABLE_RUN
        message = f"run is unreadable: {text}"
    else:
        code = CatalogWarningCode.PARTIAL_RUN
        message = f"run metadata is incomplete or invalid: {text}"
    return _warning(code, message, run_uri=run_uri, path=path)


def _warning(
    code: CatalogWarningCode,
    message: str,
    *,
    run_uri: str | None = None,
    path: Path | None = None,
) -> CatalogWarning:
    return CatalogWarning(
        code=code,
        message=message,
        run_uri=run_uri,
        path=None if path is None else str(path),
    )


__all__ = [
    "CurrentRunSummary",
    "extract_current_summary",
    "extract_current_summary_record",
    "extract_current_summary_with_warning",
    "extract_current_summary_with_warning_record",
]
