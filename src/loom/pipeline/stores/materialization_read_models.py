"""Backend-neutral authoritative read and materialization helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from loom.errors import FingerprintError
from loom.fingerprints import compare_digests, hash_bytes
from loom.io.errors import UnsupportedURIError
from loom.io.uris import get_uri_scheme, path_to_file_uri, uri_to_path
from loom.pipeline.status import RunStatus
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData

from ._paths import VALID_CONFIG_SNAPSHOTS, VALID_LOG_STREAMS, VALID_PROVENANCE_NAMES
from .authority import PerRunAuthorityStore
from .read_models import (
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    AuthorityModelError,
    BackendRevision,
    CleanupCandidate,
    MaterializedRef,
    MaterializedRefKind,
    OutputCommitRecord,
    ReadModelWarning,
    ReadModelWarningCode,
    StageLifecycleSnapshot,
)
from .run_store import LocalRunStorePaths
from .schema_policy import (
    AuthoritySchemaCheck,
    AuthoritySchemaError,
    AuthoritySchemaFailure,
    AuthoritySchemaFailureKind,
)


class MaterializationReadModelError(ValueError):
    """Raised when a strict authoritative read rejects warning-only state."""

    def __init__(
        self, message: str, *, warnings: Sequence[ReadModelWarning] = ()
    ) -> None:
        super().__init__(message)
        self.warnings = tuple(warnings)


@dataclass(frozen=True, slots=True)
class AuthoritativeReadOptions:
    """Options for assembling an authoritative read model."""

    metadata_only: bool = True
    include_materialized_refs: bool = True
    verify_materialization: bool = False
    verify_materialization_checksums: bool = True
    strict: bool = False
    completed_run_only: bool = False
    projection_revision: BackendRevision | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "metadata_only",
            "include_materialized_refs",
            "verify_materialization",
            "verify_materialization_checksums",
            "strict",
            "completed_run_only",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise AuthorityModelError(f"{field_name} must be a bool")
        if self.projection_revision is not None and not isinstance(
            self.projection_revision, BackendRevision
        ):
            raise AuthorityModelError(
                "projection_revision must be a BackendRevision or None"
            )


@dataclass(frozen=True, slots=True)
class CompletedRunBundleMetadata:
    """Payload-free metadata projection for future completed-run bundle inputs."""

    run_uri: str
    status: RunStatus
    schema_version: int
    revision: BackendRevision
    stages: tuple[StageLifecycleSnapshot, ...] = ()
    submitted_operations: tuple[SubmittedOperationRecord, ...] = ()
    artifact_facts: tuple[ArtifactFactRecord, ...] = ()
    cleanup_candidates: tuple[CleanupCandidate, ...] = ()
    materialized_refs: tuple[MaterializedRef, ...] = ()
    warnings: tuple[ReadModelWarning, ...] = ()

    @classmethod
    def from_snapshot(
        cls, snapshot: AuthoritativeRunSnapshot
    ) -> "CompletedRunBundleMetadata":
        return cls(
            run_uri=snapshot.run_uri,
            status=snapshot.status,
            schema_version=snapshot.schema_version,
            revision=snapshot.revision,
            stages=snapshot.stages,
            submitted_operations=snapshot.submitted_operations,
            artifact_facts=tuple(
                fact for stage in snapshot.stages for fact in stage.artifact_facts
            ),
            cleanup_candidates=snapshot.cleanup_candidates,
            materialized_refs=snapshot.materialized_refs,
            warnings=snapshot.warnings,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "status": self.status.value,
            "schema_version": self.schema_version,
            "revision": self.revision.to_dict(),
            "stages": [stage.to_dict() for stage in self.stages],
            "submitted_operations": [
                operation.to_dict() for operation in self.submitted_operations
            ],
            "artifact_facts": [fact.to_dict() for fact in self.artifact_facts],
            "cleanup_candidates": [
                candidate.to_dict() for candidate in self.cleanup_candidates
            ],
            "materialized_refs": [ref.to_dict() for ref in self.materialized_refs],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class LocalMaterializationRequest:
    """Local file references to classify without reading legacy state as truth."""

    include_config_snapshots: bool = True
    include_provenance_docs: bool = True
    include_stage_logs: bool = True
    include_worker_handoff: bool = True
    extra_refs: tuple[MaterializedRef, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in (
            "include_config_snapshots",
            "include_provenance_docs",
            "include_stage_logs",
            "include_worker_handoff",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise AuthorityModelError(f"{field_name} must be a bool")
        object.__setattr__(
            self, "extra_refs", _tuple_of(self.extra_refs, MaterializedRef, "extra_refs")
        )


def read_authoritative_run(
    store: PerRunAuthorityStore,
    run_uri: str,
    *,
    options: AuthoritativeReadOptions | None = None,
    local_paths: LocalRunStorePaths | None = None,
    local_materialization: LocalMaterializationRequest | None = None,
) -> AuthoritativeRunSnapshot:
    """Assemble one backend-neutral read model over authoritative store facts."""

    read_options = options or AuthoritativeReadOptions()
    schema_check = store.check_schema(run_uri)
    schema_warnings = _schema_warnings(schema_check)
    if read_options.strict and schema_warnings:
        _raise_strict(schema_warnings)
    if schema_warnings:
        return _schema_unavailable_snapshot(run_uri, schema_check, schema_warnings)

    try:
        snapshot = store.snapshot(run_uri)
    except AuthoritySchemaError as exc:
        schema_warnings = _schema_error_warnings(exc, schema_check)
        if read_options.strict:
            _raise_strict(schema_warnings)
        return _schema_unavailable_snapshot(run_uri, schema_check, schema_warnings)
    warnings = [*snapshot.warnings, *schema_warnings]
    warnings.extend(_projection_warnings(snapshot, read_options.projection_revision))
    warnings.extend(_partial_commit_warnings(snapshot))
    warnings.extend(_completed_run_warnings(snapshot, read_options))

    stages = snapshot.stages
    materialized_refs = snapshot.materialized_refs
    if read_options.include_materialized_refs:
        stages, materialized_refs = _materialized_snapshot_refs(
            snapshot,
            local_paths=local_paths,
            local_materialization=local_materialization,
            verify=read_options.verify_materialization,
        )
        warnings.extend(
            _materialized_ref_warnings(
                materialized_refs,
                revision=snapshot.revision,
                verify_checksum=(
                    read_options.verify_materialization
                    and read_options.verify_materialization_checksums
                ),
            )
        )

    if read_options.verify_materialization:
        latest = store.snapshot(run_uri)
        if latest.revision.sequence != snapshot.revision.sequence:
            warnings.append(
                ReadModelWarning(
                    code=ReadModelWarningCode.ACTIVE_RUN_CHANGING,
                    message="authoritative run revision changed during read",
                    detail={
                        "before_revision": snapshot.revision.sequence,
                        "after_revision": latest.revision.sequence,
                    },
                    revision=latest.revision,
                )
            )

    assembled = AuthoritativeRunSnapshot(
        run_uri=snapshot.run_uri,
        status=snapshot.status,
        schema_version=snapshot.schema_version,
        revision=snapshot.revision,
        metadata=snapshot.metadata,
        stages=stages,
        submitted_operations=snapshot.submitted_operations,
        cleanup_candidates=snapshot.cleanup_candidates,
        materialized_refs=materialized_refs,
        warnings=tuple(warnings),
    )
    if read_options.strict and assembled.warnings:
        _raise_strict(assembled.warnings)
    return assembled


def read_completed_run_bundle_metadata(
    store: PerRunAuthorityStore,
    run_uri: str,
    *,
    options: AuthoritativeReadOptions | None = None,
    local_paths: LocalRunStorePaths | None = None,
    local_materialization: LocalMaterializationRequest | None = None,
) -> CompletedRunBundleMetadata:
    """Return payload-free completed-run metadata for future bundle workflows."""

    base_options = options or AuthoritativeReadOptions()
    read_options = replace(
        base_options,
        metadata_only=True,
        completed_run_only=True,
    )
    snapshot = read_authoritative_run(
        store,
        run_uri,
        options=read_options,
        local_paths=local_paths,
        local_materialization=local_materialization,
    )
    return CompletedRunBundleMetadata.from_snapshot(snapshot)


def artifact_payload_ref(
    fact: ArtifactFactRecord, *, verify: bool = False
) -> MaterializedRef:
    """Classify a committed artifact payload ref without loading its payload."""

    return _materialized_ref(
        kind=MaterializedRefKind.ARTIFACT_PAYLOAD,
        uri=fact.artifact.uri,
        checksum=fact.artifact.checksum,
        metadata={
            "artifact_name": fact.artifact_name,
            "artifact_id": fact.artifact.artifact_id,
            "artifact_type": fact.artifact.artifact_type,
            "commit_id": fact.commit_id,
        },
        verify=verify,
    )


def collect_local_materialized_refs(
    snapshot: AuthoritativeRunSnapshot,
    paths: LocalRunStorePaths,
    *,
    request: LocalMaterializationRequest | None = None,
    verify: bool = False,
) -> tuple[MaterializedRef, ...]:
    """Return expected local refs without reading their document contents."""

    materialization = request or LocalMaterializationRequest()
    refs: list[MaterializedRef] = []
    if materialization.include_config_snapshots:
        for name in sorted(VALID_CONFIG_SNAPSHOTS):
            refs.append(
                _path_ref(
                    MaterializedRefKind.CONFIG,
                    paths.local_config_path(snapshot.run_uri, name),
                    metadata={"name": name},
                    verify=verify,
                )
            )
    if materialization.include_provenance_docs:
        for name in sorted(VALID_PROVENANCE_NAMES):
            refs.append(
                _path_ref(
                    MaterializedRefKind.PROVENANCE,
                    paths.local_provenance_path(snapshot.run_uri, name),
                    metadata={"name": name},
                    verify=verify,
                )
            )
    for stage in snapshot.stages:
        if materialization.include_stage_logs:
            for stream in sorted(VALID_LOG_STREAMS):
                refs.append(
                    _path_ref(
                        MaterializedRefKind.STAGE_LOG,
                        paths.local_stage_log_path(
                            snapshot.run_uri, stage.stage_name, stream
                        ),
                        metadata={"stage_name": stage.stage_name, "stream": stream},
                        verify=verify,
                    )
                )
        if materialization.include_worker_handoff:
            refs.append(
                _path_ref(
                    MaterializedRefKind.WORKER_HANDOFF,
                    paths.local_stage_worker_request_path(
                        snapshot.run_uri, stage.stage_name
                    ),
                    metadata={"stage_name": stage.stage_name, "role": "request"},
                    verify=verify,
                )
            )
            refs.append(
                _path_ref(
                    MaterializedRefKind.WORKER_HANDOFF,
                    paths.local_stage_worker_result_path(
                        snapshot.run_uri, stage.stage_name
                    ),
                    metadata={"stage_name": stage.stage_name, "role": "result"},
                    verify=verify,
                )
            )
    refs.extend(_verified_ref(ref, verify=verify) for ref in materialization.extra_refs)
    return _deduplicate_refs(refs)


def _materialized_snapshot_refs(
    snapshot: AuthoritativeRunSnapshot,
    *,
    local_paths: LocalRunStorePaths | None,
    local_materialization: LocalMaterializationRequest | None,
    verify: bool,
) -> tuple[tuple[StageLifecycleSnapshot, ...], tuple[MaterializedRef, ...]]:
    top_level_refs: list[MaterializedRef] = [
        _verified_ref(ref, verify=verify) for ref in snapshot.materialized_refs
    ]
    stages: list[StageLifecycleSnapshot] = []
    for stage in snapshot.stages:
        stage_refs = (
            [
                _verified_ref(ref, verify=verify)
                for ref in stage.latest_commit.materialized_refs
            ]
            if stage.latest_commit
            else []
        )
        stage_refs.extend(
            artifact_payload_ref(fact, verify=verify) for fact in stage.artifact_facts
        )
        top_level_refs.extend(stage_refs)
        stages.append(_replace_commit_refs(stage, _deduplicate_refs(stage_refs)))
    if local_paths is not None:
        top_level_refs.extend(
            collect_local_materialized_refs(
                snapshot,
                local_paths,
                request=local_materialization,
                verify=verify,
            )
        )
    elif local_materialization is not None:
        top_level_refs.extend(
            _verified_ref(ref, verify=verify)
            for ref in local_materialization.extra_refs
        )
    return tuple(stages), _deduplicate_refs(top_level_refs)


def _replace_commit_refs(
    stage: StageLifecycleSnapshot, refs: tuple[MaterializedRef, ...]
) -> StageLifecycleSnapshot:
    if stage.latest_commit is None:
        return stage
    commit = OutputCommitRecord(
        commit_id=stage.latest_commit.commit_id,
        run_uri=stage.latest_commit.run_uri,
        stage_name=stage.latest_commit.stage_name,
        attempt_id=stage.latest_commit.attempt_id,
        committed_at=stage.latest_commit.committed_at,
        revision=stage.latest_commit.revision,
        output_names=stage.latest_commit.output_names,
        materialized_refs=refs,
    )
    return replace(stage, latest_commit=commit)


def _materialized_ref(
    *,
    kind: MaterializedRefKind,
    uri: str,
    metadata: Mapping[str, PlainData],
    verify: bool,
    checksum: str | None = None,
) -> MaterializedRef:
    exists = _safe_exists(uri) if verify else None
    return MaterializedRef(
        kind=kind,
        uri=uri,
        exists=exists,
        checksum=checksum,
        metadata=metadata,
    )


def _path_ref(
    kind: MaterializedRefKind,
    path: Path,
    *,
    metadata: Mapping[str, PlainData],
    verify: bool,
) -> MaterializedRef:
    uri = path_to_file_uri(path.resolve(strict=False))
    return _materialized_ref(kind=kind, uri=uri, metadata=metadata, verify=verify)


def _safe_exists(uri: str) -> bool | None:
    scheme = get_uri_scheme(uri)
    if scheme not in {None, "file"}:
        return None
    try:
        return uri_to_path(uri).exists()
    except (OSError, RuntimeError, UnsupportedURIError, ValueError):
        return False


def _verified_ref(ref: MaterializedRef, *, verify: bool) -> MaterializedRef:
    if not verify:
        return ref
    exists = _safe_exists(ref.uri)
    if exists is None:
        return ref
    return replace(ref, exists=exists)


def _schema_warnings(check: AuthoritySchemaCheck) -> tuple[ReadModelWarning, ...]:
    if check.failure is None:
        return ()
    failure = check.failure
    return (
        ReadModelWarning(
            code=ReadModelWarningCode.UNSUPPORTED_SCHEMA,
            message=failure.message,
            detail=_schema_warning_detail(failure),
        ),
    )


def _schema_error_warnings(
    error: AuthoritySchemaError, check: AuthoritySchemaCheck
) -> tuple[ReadModelWarning, ...]:
    message = str(error) or "authoritative schema could not be read"
    detail: dict[str, PlainData] = {
        "kind": AuthoritySchemaFailureKind.INVALID.value,
        "current_version": check.current_version,
        "authoritative_snapshot_available": False,
    }
    if check.found_version is not None:
        detail["found_version"] = check.found_version
    return (
        ReadModelWarning(
            code=ReadModelWarningCode.UNSUPPORTED_SCHEMA,
            message=message,
            detail=detail,
        ),
    )


def _schema_warning_detail(failure: AuthoritySchemaFailure) -> Mapping[str, PlainData]:
    detail: dict[str, PlainData] = {
        "kind": failure.kind.value,
        "current_version": failure.current_version,
        "authoritative_snapshot_available": False,
        **dict(failure.detail),
    }
    if failure.found_version is not None:
        detail["found_version"] = failure.found_version
    return detail


def _schema_unavailable_snapshot(
    run_uri: str,
    check: AuthoritySchemaCheck,
    warnings: Sequence[ReadModelWarning],
) -> AuthoritativeRunSnapshot:
    schema_version = check.found_version or check.current_version
    return AuthoritativeRunSnapshot(
        run_uri=run_uri,
        status=RunStatus.CREATED,
        schema_version=schema_version,
        revision=BackendRevision(
            sequence=1,
            token=f"schema-unavailable-{schema_version}",
        ),
        warnings=tuple(warnings),
    )


def _projection_warnings(
    snapshot: AuthoritativeRunSnapshot, projection_revision: BackendRevision | None
) -> tuple[ReadModelWarning, ...]:
    if projection_revision is None:
        return ()
    if projection_revision.sequence >= snapshot.revision.sequence:
        return ()
    return (
        ReadModelWarning(
            code=ReadModelWarningCode.STALE_PROJECTION,
            message="projection revision is older than authoritative backend revision",
            detail={
                "projection_revision": projection_revision.sequence,
                "backend_revision": snapshot.revision.sequence,
            },
            revision=snapshot.revision,
        ),
    )


def _partial_commit_warnings(
    snapshot: AuthoritativeRunSnapshot,
) -> tuple[ReadModelWarning, ...]:
    warnings: list[ReadModelWarning] = []
    for stage in snapshot.stages:
        fact_commit_ids = {fact.commit_id for fact in stage.artifact_facts}
        if stage.latest_commit is None:
            if fact_commit_ids:
                artifact_commit_ids = cast(list[PlainData], sorted(fact_commit_ids))
                warnings.append(
                    _partial_commit_warning(
                        stage,
                        "artifact facts exist without a latest output commit",
                        extra={"artifact_commit_ids": artifact_commit_ids},
                    )
                )
            continue
        expected_outputs = set(stage.latest_commit.output_names)
        fact_outputs = {fact.artifact_name for fact in stage.artifact_facts}
        mismatched_commit_ids = sorted(
            commit_id
            for commit_id in fact_commit_ids
            if commit_id != stage.latest_commit.commit_id
        )
        missing_outputs = cast(list[PlainData], sorted(expected_outputs - fact_outputs))
        extra_outputs = cast(list[PlainData], sorted(fact_outputs - expected_outputs))
        mismatched_ids = cast(list[PlainData], mismatched_commit_ids)
        if mismatched_commit_ids or missing_outputs or extra_outputs:
            warnings.append(
                _partial_commit_warning(
                    stage,
                    "stage output commit facts are incomplete or inconsistent",
                    extra={
                        "commit_id": stage.latest_commit.commit_id,
                        "mismatched_commit_ids": mismatched_ids,
                        "missing_outputs": missing_outputs,
                        "extra_outputs": extra_outputs,
                    },
                )
            )
    return tuple(warnings)


def _partial_commit_warning(
    stage: StageLifecycleSnapshot, message: str, *, extra: Mapping[str, PlainData]
) -> ReadModelWarning:
    return ReadModelWarning(
        code=ReadModelWarningCode.PARTIAL_COMMIT,
        message=message,
        detail={"stage_name": stage.stage_name, **dict(extra)},
        revision=stage.revision,
    )


def _completed_run_warnings(
    snapshot: AuthoritativeRunSnapshot, options: AuthoritativeReadOptions
) -> tuple[ReadModelWarning, ...]:
    if not options.completed_run_only or _terminal_status(snapshot.status):
        return ()
    return (
        ReadModelWarning(
            code=ReadModelWarningCode.ACTIVE_RUN_CHANGING,
            message="completed-run metadata was requested for a non-terminal run",
            detail={"status": snapshot.status.value},
            revision=snapshot.revision,
        ),
    )


def _materialized_ref_warnings(
    refs: Iterable[MaterializedRef],
    *,
    revision: BackendRevision,
    verify_checksum: bool,
) -> tuple[ReadModelWarning, ...]:
    warnings: list[ReadModelWarning] = []
    for ref in refs:
        if ref.exists is False:
            warnings.append(
                ReadModelWarning(
                    code=ReadModelWarningCode.MISSING_MATERIALIZED_REF,
                    message="materialized reference is missing",
                    detail={
                        "kind": ref.kind.value,
                        "uri": ref.uri,
                        **dict(ref.metadata),
                    },
                    revision=revision,
                )
            )
            continue
        checksum_result = _checksum_result(ref) if verify_checksum else None
        if checksum_result is None:
            continue
        actual_checksum, reason = checksum_result
        detail: dict[str, PlainData] = {
            "kind": ref.kind.value,
            "uri": ref.uri,
            "expected_checksum": ref.checksum,
            "reason": reason,
            **dict(ref.metadata),
        }
        if actual_checksum is not None:
            detail["actual_checksum"] = actual_checksum
        warnings.append(
            ReadModelWarning(
                code=ReadModelWarningCode.CORRUPT_MATERIALIZED_REF,
                message="materialized reference checksum could not be verified",
                detail=detail,
                revision=revision,
            )
        )
    return tuple(warnings)


def _checksum_result(ref: MaterializedRef) -> tuple[str | None, str] | None:
    if ref.checksum is None:
        return None
    if get_uri_scheme(ref.uri) not in {None, "file"}:
        return None
    try:
        path = uri_to_path(ref.uri)
        if not path.exists():
            return None
        if not path.is_file():
            return None, "checksum_unsupported"
        actual_checksum = hash_bytes(path.read_bytes())
        if compare_digests(actual_checksum, ref.checksum):
            return None
        return actual_checksum, "checksum_mismatch"
    except (OSError, RuntimeError, UnsupportedURIError, ValueError, FingerprintError):
        return None, "checksum_unreadable"


def _terminal_status(status: RunStatus) -> bool:
    return status in {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.INTERRUPTED,
    }


def _deduplicate_refs(refs: Iterable[MaterializedRef]) -> tuple[MaterializedRef, ...]:
    by_key: dict[tuple[str, str], MaterializedRef] = {}
    for ref in refs:
        key = (ref.kind.value, ref.uri)
        existing = by_key.get(key)
        if existing is None or (existing.exists is None and ref.exists is not None):
            by_key[key] = ref
    return tuple(by_key[key] for key in sorted(by_key))


def _tuple_of[T](values: object, value_type: type[T], field: str) -> tuple[T, ...]:
    result = tuple(values)  # type: ignore[arg-type]
    if any(not isinstance(value, value_type) for value in result):
        raise AuthorityModelError(f"{field} must contain {value_type.__name__} values")
    return result


def _raise_strict(warnings: Sequence[ReadModelWarning]) -> None:
    if not warnings:
        return
    summary = ", ".join(sorted({warning.code.value for warning in warnings}))
    raise MaterializationReadModelError(
        f"strict authoritative read rejected warning(s): {summary}",
        warnings=warnings,
    )


__all__ = [
    "AuthoritativeReadOptions",
    "CompletedRunBundleMetadata",
    "LocalMaterializationRequest",
    "MaterializationReadModelError",
    "artifact_payload_ref",
    "collect_local_materialized_refs",
    "read_authoritative_run",
    "read_completed_run_bundle_metadata",
]
