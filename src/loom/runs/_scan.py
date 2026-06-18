"""Private direct scan helpers for local run collections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.state_sources import (
    authoritative_service_source,
    local_materialization_source,
    unavailable_authority_source,
)
from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus, StageStatusRecord
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.pipeline.stores import (
    AuthoritativeReadOptions,
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityStoreError,
    CorruptStoreDocumentError,
    LocalMaterializationRequest,
    LocalRunStore,
    MissingStoreDocumentError,
    PerRunAuthorityStore,
    RunNotFoundError,
    RunFreshnessRecord,
    UnsafeStorePathError,
    authority_config_from_env,
    format_artifact_key,
    path_to_run_uri,
    read_authoritative_run,
)
from loom.pipeline.stores.read_models import (
    AuthoritativeRunSnapshot,
    StageLifecycleSnapshot,
)
from loom.serialization import PlainData
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


@dataclass(frozen=True, slots=True)
class _AuthorityScanContext:
    config: AuthorityConfig
    authority_store: PerRunAuthorityStore | None


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
    authority_context = _authority_scan_context()
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
        record, warning = _scan_candidate(store, candidate, authority_context)
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
    store: LocalRunStore,
    candidate: Path,
    authority_context: _AuthorityScanContext,
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
        authority_store, authority_warning = _authority_store_for_candidate(
            run_uri,
            candidate,
            store,
            authority_context,
        )
    except (CorruptStoreDocumentError, OSError) as exc:
        return None, _warning_for_store_exception(exc, path=candidate)
    if authority_warning is not None:
        return None, authority_warning
    if authority_store is not None:
        return extract_current_summary_with_warning_record(
            _AuthoritativeSummaryStore(
                local_store=store,
                authority_store=authority_store,
            ),
            run_uri=run_uri,
            path=candidate,
        )
    record, warning = extract_current_summary_with_warning_record(
        store,
        run_uri=run_uri,
        path=candidate,
    )
    if record is None and _authority_marker_exists(candidate):
        warning = _missing_authority_warning_for_unfresh_marker(warning, path=candidate)
    return record, warning


class _AuthoritativeSummaryStore:
    """Run summary reader that uses backend snapshots for live state."""

    def __init__(
        self, *, local_store: LocalRunStore, authority_store: PerRunAuthorityStore
    ) -> None:
        self._local_store = local_store
        self._authority_store = authority_store

    def read_run_freshness(self, run_uri: str) -> RunFreshnessRecord | None:
        revision = self._snapshot(run_uri).revision
        return RunFreshnessRecord(
            run_uri=run_uri,
            token=revision.token,
            updated_at=revision.created_at or utc_timestamp(),
            revision=revision.sequence,
            reason="authority_revision",
        )

    def read_run_document(self, run_uri: str) -> dict[str, PlainData]:
        return self._local_store.read_run_document(run_uri)

    def read_run_user_metadata(self, run_uri: str) -> dict[str, PlainData]:
        return self._local_store.read_run_user_metadata(run_uri)

    def read_run_status(self, run_uri: str) -> RunStatusRecord | None:
        snapshot = self._snapshot(run_uri)
        created_at = _run_created_at(
            self._local_store, run_uri, snapshot.revision.created_at
        )
        updated_at = snapshot.revision.created_at or created_at
        return RunStatusRecord(
            run_uri=run_uri,
            status=snapshot.status,
            created_at=created_at,
            updated_at=updated_at,
            started_at=created_at if snapshot.status is not RunStatus.CREATED else None,
            finished_at=updated_at
            if snapshot.status
            in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
            else None,
        )

    def read_runtime_metadata(self, run_uri: str) -> dict[str, PlainData] | None:
        return self._local_store.read_runtime_metadata(run_uri)

    def read_composition_manifest(
        self, run_uri: str
    ) -> dict[str, PlainData] | None:
        return self._local_store.read_composition_manifest(run_uri)

    def read_plan(self, run_uri: str) -> dict[str, PlainData] | None:
        return self._local_store.read_plan(run_uri)

    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None:
        return self._local_store.read_provenance_document(run_uri, name)

    def list_run_stages(self, run_uri: str) -> tuple[str, ...]:
        return tuple(stage.stage_name for stage in self._snapshot(run_uri).stages)

    def read_stage_status(
        self, run_uri: str, stage_name: str
    ) -> StageStatusRecord | None:
        stage = self._stage_snapshot(run_uri, stage_name)
        if stage is None:
            return None
        attempt = stage.attempts[-1].attempt if stage.attempts else 1
        updated_at = stage.revision.created_at or utc_timestamp()
        reason = stage.reason
        return StageStatusRecord(
            run_uri=run_uri,
            stage_name=stage.stage_name,
            status=stage.status,
            attempt=attempt,
            updated_at=updated_at,
            started_at=_stage_started_at(stage),
            finished_at=_stage_finished_at(stage, updated_at),
            message=None if reason is None else reason.message,
            metadata={} if reason is None else dict(reason.detail),
        )

    def read_stage_fingerprint(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return self._local_store.read_stage_fingerprint(run_uri, stage_name)

    def read_artifact_index(self, run_uri: str) -> dict[str, ArtifactRef]:
        try:
            index = dict(self._local_store.read_artifact_index(run_uri))
        except Exception:
            index = {}
        for stage in self._snapshot(run_uri).stages:
            for fact in stage.artifact_facts:
                index[format_artifact_key(stage.stage_name, fact.artifact_name)] = (
                    fact.artifact
                )
        return index

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        return self._snapshot(run_uri).submitted_operations

    def summary_state_source(self, _run_uri: str) -> dict[str, PlainData]:
        return authoritative_service_source(
            backend_name=self._authority_store.capabilities().backend_name
        )

    def _snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot:
        return read_authoritative_run(
            self._authority_store,
            run_uri,
            options=AuthoritativeReadOptions(include_materialized_refs=True),
            local_paths=self._local_store,
            local_materialization=LocalMaterializationRequest(),
        )

    def _stage_snapshot(
        self, run_uri: str, stage_name: str
    ) -> StageLifecycleSnapshot | None:
        for stage in self._snapshot(run_uri).stages:
            if stage.stage_name == stage_name:
                return stage
        return None


def _run_created_at(
    local_store: LocalRunStore, run_uri: str, fallback: str | None
) -> str:
    try:
        document = local_store.read_run_document(run_uri)
    except Exception:
        return fallback or utc_timestamp()
    created_at = document.get("created_at")
    return created_at if isinstance(created_at, str) else fallback or utc_timestamp()


def _stage_started_at(stage: StageLifecycleSnapshot) -> str | None:
    if not stage.attempts:
        return None
    return stage.attempts[-1].created_at


def _stage_finished_at(stage: StageLifecycleSnapshot, updated_at: str) -> str | None:
    if stage.status is StageStatus.SUCCEEDED and stage.latest_commit is not None:
        return stage.latest_commit.committed_at
    if stage.status in {
        StageStatus.FAILED,
        StageStatus.BLOCKED,
        StageStatus.SKIPPED,
        StageStatus.CANCELLED,
    }:
        return updated_at
    return None


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


def _authority_store_for_candidate(
    run_uri: str,
    candidate: Path,
    store: LocalRunStore,
    authority_context: _AuthorityScanContext,
) -> tuple[PerRunAuthorityStore | None, CatalogWarning | None]:
    config = authority_context.config
    if _is_historical_portable_import(store, run_uri):
        return None, None
    if config.backend_kind in {
        AuthorityBackendKind.CO_LOCATED_SERVICE,
        AuthorityBackendKind.MANAGED_SERVICE,
        AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
    }:
        authority_store = authority_context.authority_store
        if authority_store is None:
            if config.endpoint is None:
                if not _authority_marker_exists(candidate):
                    return None, _warning(
                        CatalogWarningCode.LOCAL_LIFECYCLE_UNSUPPORTED,
                        (
                            "run has local-only lifecycle state; service "
                            "authority-backed lifecycle state is required"
                        ),
                        path=candidate,
                        details={
                            "state_source": local_materialization_source(
                                path=str(candidate)
                            ),
                            "guidance": (
                                "start/status/restart the selected authority "
                                "or choose explicit offline mode"
                            ),
                        },
                    )
                return None, None
            return None, _warning(
                CatalogWarningCode.PARTIAL_RUN,
                "configured authority service is unavailable",
                path=candidate,
                details={
                    "state_source": unavailable_authority_source(
                        reason="configured_service_unavailable"
                    ),
                    "guidance": "check `loom authority status` or restart the authority",
                },
            )
        check = authority_store.check_schema(run_uri)
        if check.failure is None:
            try:
                authority_store.open_run(run_uri)
            except Exception:
                if _authority_marker_exists(candidate):
                    return None, _warning(
                        CatalogWarningCode.PARTIAL_RUN,
                        "run authoritative backend is missing",
                        path=candidate,
                        details={
                            "state_source": unavailable_authority_source(
                                reason="backend_missing"
                            ),
                            "guidance": "start or restore the selected authority",
                        },
                    )
                return None, _warning(
                    CatalogWarningCode.LOCAL_LIFECYCLE_UNSUPPORTED,
                    (
                        "run has local-only lifecycle state; service "
                        "authority-backed lifecycle state is required"
                    ),
                    path=candidate,
                    details={
                        "state_source": local_materialization_source(
                            path=str(candidate)
                        ),
                        "guidance": (
                            "start/status/restart the selected authority "
                            "or choose explicit offline mode"
                        ),
                    },
                )
            return cast(PerRunAuthorityStore, authority_store), None
        raise CorruptStoreDocumentError(check.failure.message)

    if config.backend_kind is AuthorityBackendKind.TRANSITIONAL_SQLITE:
        return None, _warning(
            CatalogWarningCode.LOCAL_LIFECYCLE_UNSUPPORTED,
            "run-local SQLite authority is no longer a supported runtime backend",
            path=candidate,
            details={
                "state_source": local_materialization_source(path=str(candidate)),
                "guidance": "select a service authority endpoint",
            },
        )
    if _authority_marker_exists(candidate):
        return None, _warning(
            CatalogWarningCode.PARTIAL_RUN,
            "run authoritative backend is missing",
            path=candidate,
            details={
                "state_source": unavailable_authority_source(reason="backend_missing"),
                "guidance": "start or restore the selected authority",
            },
        )
    return None, _warning(
        CatalogWarningCode.LOCAL_LIFECYCLE_UNSUPPORTED,
        "run has local-only lifecycle state; service authority-backed lifecycle state is required",
        path=candidate,
        details={
            "state_source": local_materialization_source(path=str(candidate)),
            "guidance": (
                "start/status/restart the selected authority or choose explicit "
                "offline mode"
            ),
        },
    )


def _is_historical_portable_import(store: LocalRunStore, run_uri: str) -> bool:
    try:
        runtime = store.read_runtime_metadata(run_uri) or {}
    except Exception:
        return False
    return (
        runtime.get("historical_only") is True
        and isinstance(runtime.get("portable_run_import"), dict)
    )


def _authority_scan_context() -> _AuthorityScanContext:
    config = authority_config_from_env()
    if config.backend_kind in {
        AuthorityBackendKind.CO_LOCATED_SERVICE,
        AuthorityBackendKind.MANAGED_SERVICE,
        AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
    } and config.endpoint is not None:
        from loom.pipeline.stores.service_authority import create_service_authority_store

        try:
            authority_store = create_service_authority_store(config)
        except AuthorityStoreError:
            authority_store = None
        return _AuthorityScanContext(
            config=config,
            authority_store=authority_store,
        )
    return _AuthorityScanContext(config=config, authority_store=None)


def _authority_marker_exists(candidate: Path) -> bool:
    return (candidate / ".loom").exists()


def _missing_authority_warning_for_unfresh_marker(
    warning: CatalogWarning | None, *, path: Path
) -> CatalogWarning | None:
    if (
        warning is not None
        and warning.code is CatalogWarningCode.PARTIAL_RUN
        and warning.message == "run has no freshness metadata"
    ):
        return _warning(
            CatalogWarningCode.PARTIAL_RUN,
            "run authoritative backend is missing",
            path=path,
            details={
                "state_source": unavailable_authority_source(reason="backend_missing"),
                "guidance": "start or restore the selected authority",
            },
        )
    return warning


def _warning(
    code: CatalogWarningCode,
    message: str,
    *,
    path: Path | None = None,
    details: dict[str, PlainData] | None = None,
) -> CatalogWarning:
    return CatalogWarning(
        code=code,
        message=message,
        path=None if path is None else str(path),
        details={} if details is None else details,
    )


__all__ = [
    "CurrentCatalogScan",
    "scan_current_collection",
    "scan_current_collection_records",
]
