"""Portable run import helpers for local bundles and offline evidence."""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import unquote, urlparse

from loom.artifacts import ArtifactRef
from loom.fingerprints import compare_digests, hash_bytes
from loom.io.uris import path_to_file_uri
from loom.serialization import PlainData, thaw_plain_data
from loom.timestamps import utc_timestamp

from .bundles import (
    LOCAL_RUN_BUNDLE_ADAPTER,
    RUN_BUNDLE_MANIFEST_MEMBER,
    inspect_run_bundle,
    normalize_bundle_member_path,
)
from .errors import CatalogValidationError
from .models import (
    MigrationReadinessBlocker,
    MigrationReadinessBlockerCode,
    MigrationResumeReadiness,
    PortableRunImportRecord,
    PortableRunSourceIdentity,
    PortableRunTargetIdentityPolicy,
    RunAdapterIdentity,
    RunBundleImportPolicy,
    RunBundleImportResult,
    RunBundleInspection,
    RunBundleManifest,
    RunBundlePayloadReference,
    RunExchangeDiagnostic,
    RunExchangeDiagnosticSeverity,
    RunExchangeOperationStatus,
    RunImportChecksumPolicy,
    RunImportMaterializationPolicy,
    RunImportResumeMode,
    RunImporter,
    RunTargetIdentityPolicyMode,
    TransferRecordKind,
)

if TYPE_CHECKING:
    from loom.authority._repository import AuthorityRepository
    from loom.authority.offline_import import OfflineImportDiagnostic
    from loom.pipeline.offline_evidence import OfflineEvidenceManifest
    from loom.pipeline.stores import CompletedRunBundleMetadata


OFFLINE_EVIDENCE_IMPORT_ADAPTER = RunAdapterIdentity(
    name="offline-evidence",
    version="1",
    kind=TransferRecordKind.OFFLINE_EVIDENCE.value,
)

_ERROR_SEVERITIES = {RunExchangeDiagnosticSeverity.ERROR}
_IMPORT_PAYLOAD_ROOT = "imported_payloads"


class LocalRunBundleImporter:
    """Concrete local bundle importer over the Phase 1 importer protocol."""

    adapter = LOCAL_RUN_BUNDLE_ADAPTER

    def __init__(self, target_collection: str | Path) -> None:
        self.target_collection = Path(target_collection)

    def inspect(
        self,
        record: PortableRunImportRecord,
        *,
        policy: RunBundleImportPolicy | None = None,
    ) -> RunBundleInspection:
        del policy
        diagnostics = _dedupe_diagnostics(
            (*record.diagnostics, *record.manifest.diagnostics, *record.manifest.warnings)
        )
        return RunBundleInspection(
            status=_status_for_diagnostics(diagnostics),
            manifest=record.manifest,
            included_payload_count=sum(
                1 for ref in record.manifest.payload_refs if ref.selected
            ),
            diagnostics=diagnostics,
        )

    def import_record(
        self,
        record: PortableRunImportRecord,
        *,
        policy: RunBundleImportPolicy | None = None,
    ) -> RunBundleImportResult:
        import_policy = policy or RunBundleImportPolicy()
        diagnostics = list(
            _dedupe_diagnostics(
                (
                    *record.diagnostics,
                    *record.manifest.diagnostics,
                    *record.manifest.warnings,
                )
            )
        )
        blockers: list[MigrationReadinessBlocker] = []
        metadata = _completed_run_metadata(record.manifest, diagnostics)
        target_run_uri: str | None = None
        target_dir: Path | None = None
        if metadata is not None:
            target_run_uri, target_dir = _target_run_uri(
                self.target_collection,
                metadata.run_uri,
            )
            if target_dir.exists():
                diagnostics.append(
                    _diagnostic(
                        "run_bundle_import.target_collision",
                        "target run already exists",
                        target_run_uri=target_run_uri,
                        target_path=str(target_dir),
                    )
                )
                blockers.append(
                    _blocker(
                        MigrationReadinessBlockerCode.RUN_URI_COLLISION,
                        "target run already exists",
                        target_run_uri=target_run_uri,
                    )
                )

        bundle_path = _record_bundle_path(record)
        if bundle_path is not None:
            diagnostics.extend(
                _bundle_validation_diagnostics(
                    bundle_path,
                    record.manifest,
                    verify_checksums=True,
                )
            )
        elif record.manifest.entries:
            diagnostics.append(
                _diagnostic(
                    "run_bundle_import.bundle_path_missing",
                    "portable import record does not include a readable bundle path",
                )
            )

        resume_mode = RunImportResumeMode(import_policy.resume_mode)
        materialization_policy = RunImportMaterializationPolicy(
            import_policy.materialization_policy
        )
        if resume_mode is not RunImportResumeMode.HISTORICAL_ONLY:
            diagnostics.append(
                _diagnostic(
                    "run_bundle_import.resume_unsupported",
                    "live migrated resume is unsupported in v12",
                    resume_mode=resume_mode.value,
                )
            )

        if _has_error(diagnostics):
            return _bundle_import_result(
                status=RunExchangeOperationStatus.FAILED,
                source_identity=record.source_identity,
                adapter=record.adapter,
                target_run_uri=target_run_uri,
                readiness=_historical_readiness(*blockers),
                diagnostics=diagnostics,
            )

        assert metadata is not None
        assert target_run_uri is not None
        assert target_dir is not None
        imported_payload_refs: tuple[RunBundlePayloadReference, ...] = ()
        import_provenance = _bundle_import_provenance(record, target_run_uri)
        try:
            copied_payloads = _write_imported_run(
                self.target_collection,
                metadata,
                target_run_uri=target_run_uri,
                target_dir=target_dir,
                import_provenance=import_provenance,
                bundle_path=bundle_path,
                manifest=record.manifest,
                complete=materialization_policy
                is RunImportMaterializationPolicy.COMPLETE,
            )
            imported_payload_refs = tuple(copied_payloads.payload_refs)
        except Exception as exc:  # noqa: BLE001 - convert failed imports to diagnostics.
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            diagnostics.append(
                _diagnostic(
                    "run_bundle_import.commit_failed",
                    "bundle import failed before commit completed",
                    error=str(exc),
                )
            )
            return _bundle_import_result(
                status=RunExchangeOperationStatus.FAILED,
                source_identity=record.source_identity,
                adapter=record.adapter,
                target_run_uri=target_run_uri,
                readiness=_historical_readiness(*blockers),
                diagnostics=diagnostics,
                import_provenance=import_provenance,
            )

        _refresh_catalog(self.target_collection)
        return _bundle_import_result(
            status=RunExchangeOperationStatus.SUCCEEDED,
            source_identity=record.source_identity,
            adapter=record.adapter,
            target_run_uri=target_run_uri,
            imported_entry_count=len(record.manifest.entries),
            imported_payload_count=len(imported_payload_refs),
            readiness=_historical_readiness(*blockers),
            imported_source_payload_refs=imported_payload_refs,
            diagnostics=diagnostics,
            import_provenance=import_provenance,
        )


class OfflineEvidenceRunImporter:
    """Adapter that maps v10 offline evidence into shared import results."""

    adapter = OFFLINE_EVIDENCE_IMPORT_ADAPTER

    def __init__(
        self,
        repository: "AuthorityRepository",
        *,
        imported_by: str = "offline-import",
        workspace_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.imported_by = imported_by
        self.workspace_id = workspace_id

    def inspect(
        self,
        record: PortableRunImportRecord,
        *,
        policy: RunBundleImportPolicy | None = None,
    ) -> RunBundleInspection:
        del policy
        manifest = _offline_manifest_from_record(record)
        diagnostics = _offline_validation_diagnostics(manifest)
        return RunBundleInspection(
            status=_status_for_diagnostics(diagnostics),
            manifest=record.manifest,
            included_payload_count=0,
            diagnostics=diagnostics,
        )

    def import_record(
        self,
        record: PortableRunImportRecord,
        *,
        policy: RunBundleImportPolicy | None = None,
    ) -> RunBundleImportResult:
        del policy
        manifest = _offline_manifest_from_record(record)
        return import_offline_evidence(
            self.repository,
            manifest,
            imported_by=self.imported_by,
            workspace_id=self.workspace_id,
        )


def build_portable_run_import_record(
    bundle_path: str | Path,
    *,
    policy: RunBundleImportPolicy | None = None,
) -> PortableRunImportRecord:
    """Build a portable import record from a local bundle."""

    import_policy = policy or RunBundleImportPolicy()
    checksum_policy = RunImportChecksumPolicy(import_policy.checksum_policy)
    path = Path(bundle_path)
    inspection = inspect_run_bundle(
        path,
        verify_checksums=checksum_policy is RunImportChecksumPolicy.STRICT,
    )
    diagnostics = tuple(inspection.diagnostics)
    return PortableRunImportRecord(
        source_identity=inspection.manifest.source_identity,
        adapter=LOCAL_RUN_BUNDLE_ADAPTER,
        manifest=inspection.manifest,
        selected_payload_refs=inspection.manifest.payload_refs,
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL
        ),
        provenance={
            "bundle_path": str(path),
            "bundle_member": RUN_BUNDLE_MANIFEST_MEMBER,
        },
        diagnostics=diagnostics,
        extensions={"bundle_path": str(path)},
    )


def import_run_bundle(
    bundle_path: str | Path,
    target_collection: str | Path,
    *,
    policy: RunBundleImportPolicy | None = None,
) -> RunBundleImportResult:
    """Import a local bundle into a target local run collection."""

    source_identity = PortableRunSourceIdentity(
        source_kind="local_bundle",
        run_uri=path_to_file_uri(Path(bundle_path).resolve(strict=False)),
    )
    try:
        record = build_portable_run_import_record(bundle_path, policy=policy)
    except CatalogValidationError as exc:
        return _bundle_import_result(
            status=RunExchangeOperationStatus.FAILED,
            source_identity=source_identity,
            adapter=LOCAL_RUN_BUNDLE_ADAPTER,
            target_run_uri=None,
            readiness=_historical_readiness(),
            diagnostics=(
                _diagnostic(
                    "run_bundle_import.inspect_failed",
                    "bundle could not be inspected for import",
                    error=str(exc),
                ),
            ),
        )
    importer: RunImporter = LocalRunBundleImporter(target_collection)
    return importer.import_record(record, policy=policy)


def build_offline_evidence_import_record(
    manifest_or_path: "OfflineEvidenceManifest | str | Path",
) -> PortableRunImportRecord:
    """Build a portable import record for v10 offline evidence."""

    manifest = _load_offline_manifest(manifest_or_path)
    source_identity = PortableRunSourceIdentity(
        source_kind="offline_evidence",
        run_uri=manifest.run_uri,
        extensions={
            "schema_version": manifest.schema_version,
            "kind": manifest.kind,
            "generated_at": manifest.generated_at,
        },
    )
    bundle_manifest = RunBundleManifest(
        run_uri=manifest.run_uri,
        source_identity=source_identity,
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL
        ),
        extensions={
            "offline_evidence": {
                "schema_version": manifest.schema_version,
                "kind": manifest.kind,
                "manifest_status": manifest.manifest_status.value,
            }
        },
    )
    return PortableRunImportRecord(
        source_identity=source_identity,
        adapter=OFFLINE_EVIDENCE_IMPORT_ADAPTER,
        manifest=bundle_manifest,
        target_identity=bundle_manifest.target_identity,
        provenance={"offline_evidence": manifest.to_dict()},
        extensions={"offline_evidence_manifest": manifest.to_dict()},
    )


def import_offline_evidence(
    repository: "AuthorityRepository",
    manifest_or_path: "OfflineEvidenceManifest | str | Path",
    *,
    imported_by: str = "offline-import",
    workspace_id: str | None = None,
) -> RunBundleImportResult:
    """Import offline evidence through authority code and shared result semantics."""

    from loom.authority.offline_import import (
        OfflineImportError,
        import_offline_evidence_manifest,
    )

    manifest = _load_offline_manifest(manifest_or_path)
    source_identity = _offline_source_identity(manifest)
    try:
        result = import_offline_evidence_manifest(
            repository,
            manifest,
            imported_by=imported_by,
            workspace_id=workspace_id,
        )
    except OfflineImportError as exc:
        diagnostics = _offline_error_diagnostics(exc.diagnostics)
        if not diagnostics:
            diagnostics = (
                _diagnostic(
                    f"offline_import.{exc.kind.value}",
                    str(exc),
                    kind=exc.kind.value,
                ),
            )
        return _bundle_import_result(
            status=RunExchangeOperationStatus.FAILED,
            source_identity=source_identity,
            adapter=OFFLINE_EVIDENCE_IMPORT_ADAPTER,
            target_run_uri=None,
            readiness=_historical_readiness(_blocker_for_offline_kind(exc.kind.value)),
            diagnostics=diagnostics,
        )

    return _bundle_import_result(
        status=RunExchangeOperationStatus.SUCCEEDED,
        source_identity=source_identity,
        adapter=OFFLINE_EVIDENCE_IMPORT_ADAPTER,
        target_run_uri=result.run_uri,
        imported_entry_count=result.imported_stage_count
        + result.imported_artifact_count,
        imported_payload_count=0,
        readiness=_historical_readiness(),
        import_provenance=result.import_provenance,
    )


class _CopiedPayloads:
    def __init__(
        self,
        *,
        payload_refs: Sequence[RunBundlePayloadReference] = (),
        artifact_uris: Mapping[str, str] | None = None,
    ) -> None:
        self.payload_refs = tuple(payload_refs)
        self.artifact_uris = dict(artifact_uris or {})


def _completed_run_metadata(
    manifest: RunBundleManifest,
    diagnostics: list[RunExchangeDiagnostic],
) -> "CompletedRunBundleMetadata | None":
    completed_run = manifest.extensions.get("completed_run")
    if completed_run is None:
        diagnostics.append(
            _diagnostic(
                "run_bundle_import.completed_run_missing",
                "bundle manifest does not include completed-run metadata",
            )
        )
        return None
    try:
        return _completed_metadata_from_dict(thaw_plain_data(completed_run))
    except Exception as exc:
        diagnostics.append(
            _diagnostic(
                "run_bundle_import.completed_run_invalid",
                "bundle completed-run metadata is invalid",
                error=str(exc),
            )
        )
        return None


def _target_run_uri(target_collection: Path, source_run_uri: str) -> tuple[str, Path]:
    from loom.pipeline.stores import path_to_run_uri

    name = _safe_target_name(source_run_uri)
    target_dir = target_collection / name
    return path_to_run_uri(target_dir), target_dir


def _safe_target_name(source_run_uri: str) -> str:
    parsed = urlparse(source_run_uri)
    raw_name = Path(unquote(parsed.path)).name if parsed.path else ""
    if not raw_name:
        raw_name = "imported-run"
    safe = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in raw_name
    ).strip(".-")
    return safe or "imported-run"


def _completed_metadata_from_dict(data: object) -> "CompletedRunBundleMetadata":
    from loom.pipeline.status import RunStatus
    from loom.pipeline.stores import (
        ArtifactFactRecord,
        BackendRevision,
        CleanupCandidate,
        CompletedRunBundleMetadata,
        MaterializedRef,
        ReadModelWarning,
        StageLifecycleSnapshot,
    )
    from loom.pipeline.submitted import SubmittedOperationRecord

    if not isinstance(data, Mapping):
        raise CatalogValidationError("completed_run must be a mapping")
    return CompletedRunBundleMetadata(
        run_uri=_required_str(data, "run_uri"),
        status=RunStatus(_required_str(data, "status")),
        schema_version=_required_int(data, "schema_version"),
        revision=BackendRevision.from_dict(data["revision"]),
        stages=tuple(
            StageLifecycleSnapshot.from_dict(item)
            for item in _sequence(data.get("stages", ()), "stages")
        ),
        submitted_operations=tuple(
            SubmittedOperationRecord.from_dict(item)
            for item in _sequence(
                data.get("submitted_operations", ()),
                "submitted_operations",
            )
        ),
        artifact_facts=tuple(
            ArtifactFactRecord.from_dict(item)
            for item in _sequence(data.get("artifact_facts", ()), "artifact_facts")
        ),
        cleanup_candidates=tuple(
            CleanupCandidate.from_dict(item)
            for item in _sequence(
                data.get("cleanup_candidates", ()),
                "cleanup_candidates",
            )
        ),
        materialized_refs=tuple(
            MaterializedRef.from_dict(item)
            for item in _sequence(
                data.get("materialized_refs", ()),
                "materialized_refs",
            )
        ),
        warnings=tuple(
            ReadModelWarning.from_dict(item)
            for item in _sequence(data.get("warnings", ()), "warnings")
        ),
    )


def _required_str(data: Mapping[object, object], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value:
        raise CatalogValidationError(f"{field_name} must be a non-empty string")
    return value


def _required_int(data: Mapping[object, object], field_name: str) -> int:
    value = data.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise CatalogValidationError(f"{field_name} must be an integer")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, tuple | list):
        return value
    raise CatalogValidationError(f"{field_name} must be a sequence")


def _record_bundle_path(record: PortableRunImportRecord) -> Path | None:
    value = record.extensions.get("bundle_path")
    if not isinstance(value, str) or not value:
        value = record.provenance.get("bundle_path")
    if not isinstance(value, str) or not value:
        return None
    return Path(value)


def _bundle_validation_diagnostics(
    bundle_path: Path,
    manifest: RunBundleManifest,
    *,
    verify_checksums: bool,
) -> tuple[RunExchangeDiagnostic, ...]:
    try:
        inspection = inspect_run_bundle(bundle_path, verify_checksums=verify_checksums)
    except CatalogValidationError as exc:
        return (
            _diagnostic(
                "run_bundle_import.inspect_failed",
                "bundle could not be inspected for import",
                error=str(exc),
            ),
        )
    diagnostics = list(inspection.diagnostics)
    if inspection.manifest.run_uri != manifest.run_uri:
        diagnostics.append(
            _diagnostic(
                "run_bundle_import.manifest_mismatch",
                "bundle manifest run URI changed between inspection and import",
                expected_run_uri=manifest.run_uri,
                actual_run_uri=inspection.manifest.run_uri,
            )
        )
    return tuple(diagnostics)


def _copy_bundle_payloads(
    bundle_path: Path | None,
    manifest: RunBundleManifest,
    *,
    destination_root: Path,
    uri_root: Path,
    complete: bool,
) -> _CopiedPayloads:
    if not complete or not manifest.entries:
        return _CopiedPayloads()
    if bundle_path is None:
        raise CatalogValidationError("bundle path is required for complete import")

    payload_refs: list[RunBundlePayloadReference] = []
    artifact_uris: dict[str, str] = {}
    with tarfile.open(bundle_path, "r:*") as archive:
        members = {
            normalize_bundle_member_path(member.name): member
            for member in archive.getmembers()
        }
        for entry in manifest.entries:
            member = members.get(entry.path)
            if member is None or not member.isfile():
                raise CatalogValidationError(f"missing bundle payload: {entry.path}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise CatalogValidationError(f"unreadable bundle payload: {entry.path}")
            payload = extracted.read()
            if entry.checksum is not None and not compare_digests(
                hash_bytes(payload),
                entry.checksum,
            ):
                raise CatalogValidationError(f"bundle payload checksum mismatch: {entry.path}")
            target_path = destination_root / entry.path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(payload)
            payload_ref = _payload_ref_for_import(entry.path, manifest.payload_refs)
            if payload_ref is not None:
                payload_refs.append(payload_ref)
                artifact_id = _payload_artifact_id(payload_ref)
                if artifact_id is not None:
                    artifact_uris[artifact_id] = path_to_file_uri(uri_root / entry.path)
    return _CopiedPayloads(payload_refs=tuple(payload_refs), artifact_uris=artifact_uris)


def _payload_ref_for_import(
    entry_path: str,
    payload_refs: Sequence[RunBundlePayloadReference],
) -> RunBundlePayloadReference | None:
    for ref in payload_refs:
        if ref.entry_id == entry_path:
            return ref
    return None


def _payload_artifact_id(ref: RunBundlePayloadReference) -> str | None:
    materialized = ref.extensions.get("materialized_ref")
    if not isinstance(materialized, Mapping):
        return None
    metadata = materialized.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    artifact_id = metadata.get("artifact_id")
    return artifact_id if isinstance(artifact_id, str) and artifact_id else None


def _write_imported_run(
    target_collection: Path,
    metadata: "CompletedRunBundleMetadata",
    *,
    target_run_uri: str,
    target_dir: Path,
    import_provenance: Mapping[str, PlainData],
    bundle_path: Path | None,
    manifest: RunBundleManifest,
    complete: bool,
) -> _CopiedPayloads:
    from loom.pipeline.status import RunStatusRecord, StageStatusRecord
    from loom.pipeline.stores import LocalRunStore

    target_collection.mkdir(parents=True, exist_ok=True)
    store = LocalRunStore(target_collection)
    now = utc_timestamp()
    run_metadata = {
        "portable_run_import": dict(import_provenance),
        "source_run_uri": metadata.run_uri,
        "historical_only": True,
    }
    payload_root = target_dir / _IMPORT_PAYLOAD_ROOT
    staging_dir: Path | None = None
    try:
        copied_payloads = _CopiedPayloads()
        if complete and manifest.entries:
            staging_dir = Path(
                tempfile.mkdtemp(
                    prefix=f".{target_dir.name}.importing-",
                    dir=target_collection,
                )
            )
            copied_payloads = _copy_bundle_payloads(
                bundle_path,
                manifest,
                destination_root=staging_dir,
                uri_root=payload_root,
                complete=complete,
            )

        store.create_run(target_run_uri, metadata=run_metadata)
        if staging_dir is not None:
            _promote_staged_payloads(staging_dir, payload_root)
            staging_dir = None
        store.write_run_status(
            target_run_uri,
            RunStatusRecord(
                run_uri=target_run_uri,
                status=metadata.status,
                created_at=now,
                updated_at=now,
                finished_at=now,
                metadata={"portable_run_import": dict(import_provenance)},
            ),
        )
        store.write_runtime_metadata(
            target_run_uri,
            {
                "executor": "portable-run-import",
                "backend": "local-bundle",
                "historical_only": True,
                "source_run_uri": metadata.run_uri,
                "portable_run_import": dict(import_provenance),
            },
        )
        for stage in metadata.stages:
            store.write_stage_status(
                target_run_uri,
                stage.stage_name,
                StageStatusRecord(
                    run_uri=target_run_uri,
                    stage_name=stage.stage_name,
                    status=stage.status,
                    attempt=_stage_attempt_number(stage),
                    updated_at=now,
                    finished_at=now,
                    metadata={
                        "portable_run_import": {
                            "source_run_uri": metadata.run_uri,
                            "source_stage_name": stage.stage_name,
                        }
                    },
                ),
            )
        artifacts = _artifact_index_for_import(metadata, copied_payloads.artifact_uris)
        if artifacts:
            store.write_artifact_index(target_run_uri, artifacts)
        return copied_payloads
    finally:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def _promote_staged_payloads(staging_dir: Path, payload_root: Path) -> None:
    payload_root.parent.mkdir(parents=True, exist_ok=True)
    staging_dir.replace(payload_root)


def _artifact_index_for_import(
    metadata: "CompletedRunBundleMetadata",
    artifact_uris: Mapping[str, str],
) -> dict[str, ArtifactRef]:
    from loom.pipeline.stores import format_artifact_key

    artifacts: dict[str, ArtifactRef] = {}
    for stage in metadata.stages:
        for fact in stage.artifact_facts:
            artifacts[format_artifact_key(stage.stage_name, fact.artifact_name)] = (
                _rebased_artifact_ref(fact.artifact, artifact_uris)
            )
    return artifacts


def _stage_attempt_number(stage: object) -> int:
    attempts = getattr(stage, "attempts", ())
    if attempts:
        return max(int(getattr(attempt, "attempt", 1)) for attempt in attempts)
    return 1


def _rebased_artifact_ref(
    artifact: ArtifactRef,
    artifact_uris: Mapping[str, str],
) -> ArtifactRef:
    uri = artifact_uris.get(artifact.artifact_id, artifact.uri)
    metadata = cast(Mapping[str, PlainData], thaw_plain_data(artifact.metadata))
    if uri != artifact.uri:
        metadata = {**metadata, "source_uri": artifact.uri}
    return ArtifactRef(
        artifact_id=artifact.artifact_id,
        uri=uri,
        artifact_type=artifact.artifact_type,
        codec_key=artifact.codec_key,
        schema_version=artifact.schema_version,
        checksum=artifact.checksum,
        fingerprint=artifact.fingerprint,
        producer_stage=artifact.producer_stage,
        created_at=artifact.created_at,
        metadata=metadata,
    )


def _refresh_catalog(target_collection: Path) -> None:
    from .catalog import RunCatalog

    RunCatalog.open(target_collection).rebuild()


def _bundle_import_provenance(
    record: PortableRunImportRecord,
    target_run_uri: str,
) -> dict[str, PlainData]:
    return {
        "adapter": record.adapter.to_dict(),
        "source_identity": record.source_identity.to_dict(),
        "target_identity": record.target_identity.to_dict(),
        "source_run_uri": record.manifest.run_uri,
        "target_run_uri": target_run_uri,
        "imported_at": utc_timestamp(),
        "historical_only": True,
    }


def _bundle_import_result(
    *,
    status: RunExchangeOperationStatus,
    source_identity: PortableRunSourceIdentity,
    adapter: RunAdapterIdentity,
    target_run_uri: str | None,
    readiness: MigrationResumeReadiness,
    imported_entry_count: int = 0,
    imported_payload_count: int = 0,
    imported_source_payload_refs: Sequence[RunBundlePayloadReference] = (),
    diagnostics: Sequence[RunExchangeDiagnostic] = (),
    import_provenance: Mapping[str, PlainData] | None = None,
) -> RunBundleImportResult:
    return RunBundleImportResult(
        status=status,
        source_identity=source_identity,
        adapter=adapter,
        target_run_uri=target_run_uri,
        imported_entry_count=imported_entry_count,
        imported_payload_count=imported_payload_count,
        readiness=readiness,
        imported_source_payload_refs=tuple(imported_source_payload_refs),
        diagnostics=tuple(diagnostics),
        import_provenance=import_provenance or {},
    )


def _historical_readiness(
    *additional_blockers: MigrationReadinessBlocker,
) -> MigrationResumeReadiness:
    return MigrationResumeReadiness(
        mode=RunImportResumeMode.HISTORICAL_ONLY,
        blockers=(
            _blocker(
                MigrationReadinessBlockerCode.HISTORICAL_ONLY_POLICY,
                "imported runs are historical-only in v12",
            ),
            *additional_blockers,
        ),
    )


def _offline_source_identity(
    manifest: "OfflineEvidenceManifest",
) -> PortableRunSourceIdentity:
    return PortableRunSourceIdentity(
        source_kind="offline_evidence",
        run_uri=manifest.run_uri,
        extensions={
            "schema_version": manifest.schema_version,
            "kind": manifest.kind,
            "generated_at": manifest.generated_at,
        },
    )


def _load_offline_manifest(
    manifest_or_path: "OfflineEvidenceManifest | str | Path",
) -> "OfflineEvidenceManifest":
    from loom.authority.offline_import import load_offline_import_manifest
    from loom.pipeline.offline_evidence import OfflineEvidenceManifest

    if isinstance(manifest_or_path, OfflineEvidenceManifest):
        return manifest_or_path
    return load_offline_import_manifest(manifest_or_path)


def _offline_manifest_from_record(
    record: PortableRunImportRecord,
) -> "OfflineEvidenceManifest":
    from loom.pipeline.offline_evidence import OfflineEvidenceManifest

    payload = record.extensions.get("offline_evidence_manifest")
    if payload is None:
        raise CatalogValidationError("offline evidence import record is missing manifest")
    return OfflineEvidenceManifest.from_dict(thaw_plain_data(payload))


def _offline_validation_diagnostics(
    manifest: "OfflineEvidenceManifest",
) -> tuple[RunExchangeDiagnostic, ...]:
    from loom.authority.offline_import import validate_offline_import_manifest

    return _offline_error_diagnostics(validate_offline_import_manifest(manifest))


def _offline_error_diagnostics(
    diagnostics: Sequence["OfflineImportDiagnostic"],
) -> tuple[RunExchangeDiagnostic, ...]:
    return tuple(
        _diagnostic(
            _offline_diagnostic_code(diagnostic.code),
            diagnostic.message,
            offline_kind=diagnostic.kind.value,
            detail=dict(diagnostic.detail),
        )
        for diagnostic in diagnostics
    )


def _offline_diagnostic_code(code: str) -> str:
    return code if code.startswith("offline_import.") else f"offline_import.{code}"


def _blocker_for_offline_kind(kind: str) -> MigrationReadinessBlocker:
    if kind == "conflict":
        return _blocker(
            MigrationReadinessBlockerCode.RUN_URI_COLLISION,
            "offline evidence target run already exists",
        )
    if kind in {"schema", "source"}:
        return _blocker(
            MigrationReadinessBlockerCode.UNSUPPORTED_SOURCE_SCHEMA,
            "offline evidence source is unsupported",
            kind=kind,
        )
    if kind == "run_status":
        return _blocker(
            MigrationReadinessBlockerCode.NON_TERMINAL_SOURCE,
            "offline evidence run status is not importable",
        )
    return _blocker(
        MigrationReadinessBlockerCode.HISTORICAL_ONLY_POLICY,
        "offline evidence import is historical-only",
        kind=kind,
    )


def _status_for_diagnostics(
    diagnostics: Sequence[RunExchangeDiagnostic],
) -> RunExchangeOperationStatus:
    return (
        RunExchangeOperationStatus.FAILED
        if _has_error(diagnostics)
        else RunExchangeOperationStatus.SUCCEEDED
    )


def _has_error(diagnostics: Sequence[RunExchangeDiagnostic]) -> bool:
    return any(diagnostic.severity in _ERROR_SEVERITIES for diagnostic in diagnostics)


def _dedupe_diagnostics(
    diagnostics: Iterable[RunExchangeDiagnostic],
) -> tuple[RunExchangeDiagnostic, ...]:
    deduped: list[RunExchangeDiagnostic] = []
    seen: set[tuple[str, str, str]] = set()
    for diagnostic in diagnostics:
        key = (
            diagnostic.code,
            diagnostic.message,
            RunExchangeDiagnosticSeverity(diagnostic.severity).value,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(diagnostic)
    return tuple(deduped)


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: RunExchangeDiagnosticSeverity = RunExchangeDiagnosticSeverity.ERROR,
    **details: PlainData,
) -> RunExchangeDiagnostic:
    return RunExchangeDiagnostic(
        code=code,
        message=message,
        severity=severity,
        details=cast(Mapping[str, PlainData], details),
    )


def _blocker(
    code: MigrationReadinessBlockerCode,
    message: str,
    **details: PlainData,
) -> MigrationReadinessBlocker:
    return MigrationReadinessBlocker(
        code=code,
        message=message,
        details=cast(Mapping[str, PlainData], details),
    )


__all__ = [
    "OFFLINE_EVIDENCE_IMPORT_ADAPTER",
    "LocalRunBundleImporter",
    "OfflineEvidenceRunImporter",
    "build_offline_evidence_import_record",
    "build_portable_run_import_record",
    "import_offline_evidence",
    "import_run_bundle",
]
