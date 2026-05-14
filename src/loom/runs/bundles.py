"""Local bundle export and inspection helpers."""

from __future__ import annotations

import io
import tarfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from loom.fingerprints import compare_digests, hash_bytes
from loom.io.errors import UnsupportedURIError
from loom.io.uris import get_uri_scheme, uri_to_path
from loom.serialization import PlainData, stable_json_bytes, thaw_plain_data

from .errors import CatalogValidationError
from .models import (
    RUN_BUNDLE_MANIFEST_KIND,
    RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
    PortableRunExportRecord,
    PortableRunSourceIdentity,
    PortableRunTargetIdentityPolicy,
    RunAdapterIdentity,
    RunBundleEntry,
    RunBundleEntryKind,
    RunBundleExportOptions,
    RunBundleExportResult,
    RunBundleInspection,
    RunBundleManifest,
    RunBundlePayloadReference,
    RunBundlePayloadSelection,
    RunExchangeDiagnostic,
    RunExchangeDiagnosticSeverity,
    RunExchangeOperationStatus,
    RunExporter,
    RunTargetIdentityPolicyMode,
    TransferRecordKind,
)

if TYPE_CHECKING:
    from loom.pipeline.stores import (
        AuthoritativeReadOptions,
        CompletedRunBundleMetadata,
        LocalMaterializationRequest,
        LocalRunStorePaths,
        MaterializedRef,
        PerRunAuthorityStore,
        ReadModelWarning,
    )

LOCAL_RUN_BUNDLE_ADAPTER = RunAdapterIdentity(
    name="local-bundle",
    version=str(RUN_BUNDLE_MANIFEST_SCHEMA_VERSION),
    kind=TransferRecordKind.BUNDLE.value,
)
RUN_BUNDLE_MANIFEST_MEMBER = "manifest.json"

_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_MEMBER_BYTES = 1024 * 1024 * 1024
_ERROR_SEVERITIES = {RunExchangeDiagnosticSeverity.ERROR}


class LocalRunBundleExporter:
    """Concrete local bundle exporter over the Phase 1 exporter protocol."""

    adapter = LOCAL_RUN_BUNDLE_ADAPTER

    def __init__(self, destination: str | Path) -> None:
        self.destination = Path(destination)

    def export(
        self,
        record: PortableRunExportRecord,
        *,
        options: RunBundleExportOptions | None = None,
    ) -> RunBundleExportResult:
        return write_local_run_bundle(record, self.destination, options=options)


def build_portable_run_export_record(
    metadata: "CompletedRunBundleMetadata",
    *,
    options: RunBundleExportOptions | None = None,
    adapter: RunAdapterIdentity = LOCAL_RUN_BUNDLE_ADAPTER,
) -> PortableRunExportRecord:
    """Build an adapter-neutral export record from completed-run metadata."""

    export_options = options or RunBundleExportOptions()
    selected_refs, diagnostics = _selected_payload_refs(metadata, export_options)
    source_identity = PortableRunSourceIdentity(
        source_kind="completed_run_metadata",
        run_uri=metadata.run_uri,
        extensions={
            "schema_version": metadata.schema_version,
            "revision": metadata.revision.to_dict(),
        },
    )
    target_identity = PortableRunTargetIdentityPolicy(
        mode=RunTargetIdentityPolicyMode.TARGET_LOCAL,
    )
    manifest = _build_manifest(
        metadata,
        source_identity=source_identity,
        target_identity=target_identity,
        selected_refs=selected_refs,
        options=export_options,
        diagnostics=diagnostics,
    )
    return PortableRunExportRecord(
        source_identity=source_identity,
        adapter=adapter,
        selected_payload_refs=selected_refs,
        target_identity=target_identity,
        manifest=manifest,
        diagnostics=diagnostics,
    )


def export_completed_run_bundle(
    metadata: "CompletedRunBundleMetadata",
    destination: str | Path,
    *,
    options: RunBundleExportOptions | None = None,
) -> RunBundleExportResult:
    """Export completed-run metadata through the local bundle adapter."""

    export_options = options or RunBundleExportOptions()
    record = build_portable_run_export_record(metadata, options=export_options)
    exporter: RunExporter = LocalRunBundleExporter(destination)
    return exporter.export(record, options=export_options)


def export_run_bundle(
    store: "PerRunAuthorityStore",
    run_uri: str,
    destination: str | Path,
    *,
    options: RunBundleExportOptions | None = None,
    read_options: "AuthoritativeReadOptions | None" = None,
    local_paths: "LocalRunStorePaths | None" = None,
    local_materialization: "LocalMaterializationRequest | None" = None,
) -> RunBundleExportResult:
    """Read completed-run facts from an authority store and write a local bundle."""

    from loom.pipeline.stores import (
        AuthoritativeReadOptions,
        read_completed_run_bundle_metadata,
    )

    export_options = options or RunBundleExportOptions()
    base_options = read_options or AuthoritativeReadOptions()
    effective_options = replace(
        base_options,
        include_materialized_refs=True,
        verify_materialization=True,
        verify_materialization_checksums=export_options.verify_checksums,
    )
    metadata = read_completed_run_bundle_metadata(
        store,
        run_uri,
        options=effective_options,
        local_paths=local_paths,
        local_materialization=local_materialization,
    )
    return export_completed_run_bundle(
        metadata,
        destination,
        options=export_options,
    )


def write_local_run_bundle(
    record: PortableRunExportRecord,
    destination: str | Path,
    *,
    options: RunBundleExportOptions | None = None,
) -> RunBundleExportResult:
    """Materialize a portable export record as a local bundle archive."""

    if record.manifest is None:
        diagnostic = _diagnostic(
            "run_bundle_export.manifest_missing",
            "portable export record is missing a bundle manifest",
        )
        return RunBundleExportResult(
            status=RunExchangeOperationStatus.FAILED,
            adapter=record.adapter,
            exported_payload_count=0,
            diagnostics=(diagnostic,),
        )

    manifest = record.manifest
    diagnostics = _dedupe_diagnostics(
        (*record.diagnostics, *manifest.diagnostics, *manifest.warnings)
    )
    if _has_error(diagnostics):
        return RunBundleExportResult(
            status=RunExchangeOperationStatus.FAILED,
            adapter=record.adapter,
            manifest=manifest,
            exported_payload_count=0,
            diagnostics=tuple(diagnostics),
        )

    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = stable_json_bytes(manifest.to_dict())
    payload_sources = _payload_sources(manifest.entries)

    with tarfile.open(destination_path, "w") as archive:
        _add_bytes_member(archive, RUN_BUNDLE_MANIFEST_MEMBER, manifest_bytes)
        for entry in manifest.entries:
            source = payload_sources.get(entry.path)
            if source is None:
                continue
            archive.add(source, arcname=entry.path, recursive=False)

    return RunBundleExportResult(
        status=RunExchangeOperationStatus.SUCCEEDED,
        adapter=record.adapter,
        manifest=manifest,
        exported_payload_count=len(payload_sources),
        diagnostics=tuple(diagnostics),
    )


def inspect_run_bundle(
    bundle_path: str | Path,
    *,
    verify_checksums: bool = False,
) -> RunBundleInspection:
    """Inspect a local bundle archive without extracting its members."""

    diagnostics: list[RunExchangeDiagnostic] = []
    path = Path(bundle_path)
    try:
        with tarfile.open(path, "r:*") as archive:
            members = archive.getmembers()
            diagnostics.extend(_archive_member_diagnostics(members))
            manifest_member = _find_manifest_member(members)
            manifest = _read_manifest(archive, manifest_member)
            if verify_checksums:
                diagnostics.extend(_checksum_diagnostics(archive, manifest))
    except (OSError, tarfile.TarError, CatalogValidationError) as exc:
        raise CatalogValidationError(f"bundle inspection failed: {exc}") from exc

    status = (
        RunExchangeOperationStatus.FAILED
        if _has_error(diagnostics)
        else RunExchangeOperationStatus.SUCCEEDED
    )
    return RunBundleInspection(
        status=status,
        manifest=manifest,
        included_payload_count=sum(1 for ref in manifest.payload_refs if ref.selected),
        diagnostics=tuple(diagnostics),
    )


def normalize_bundle_member_path(path: str) -> str:
    """Return a safe normalized POSIX archive member path."""

    if not isinstance(path, str) or not path:
        raise CatalogValidationError("archive member path must be a non-empty string")
    if "\\" in path:
        raise CatalogValidationError("archive member path must use POSIX separators")
    pure = PurePosixPath(path)
    if pure.is_absolute():
        raise CatalogValidationError("archive member path must be relative")
    parts = pure.parts
    if not parts:
        raise CatalogValidationError("archive member path must not be empty")
    if any(part in {"", ".", ".."} for part in parts):
        raise CatalogValidationError("archive member path contains unsafe components")
    return pure.as_posix()


def _build_manifest(
    metadata: "CompletedRunBundleMetadata",
    *,
    source_identity: PortableRunSourceIdentity,
    target_identity: PortableRunTargetIdentityPolicy,
    selected_refs: Sequence[RunBundlePayloadReference],
    options: RunBundleExportOptions,
    diagnostics: Sequence[RunExchangeDiagnostic],
) -> RunBundleManifest:
    entries = tuple(
        _entry_from_ref(ref)
        for ref in selected_refs
        if ref.size_bytes is not None
    )
    warnings = tuple(_warning_diagnostics(metadata.warnings))
    return RunBundleManifest(
        schema_version=RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
        kind=RUN_BUNDLE_MANIFEST_KIND,
        run_uri=metadata.run_uri,
        source_identity=source_identity,
        target_identity=target_identity,
        entries=entries,
        payload_refs=tuple(selected_refs),
        payload_selection=RunBundlePayloadSelection(
            include_artifacts=options.include_payloads,
            include_logs=options.include_logs,
            include_workspace=options.include_workspace,
        ),
        checksums={
            entry.path: entry.checksum
            for entry in entries
            if entry.checksum is not None
        },
        diagnostics=tuple(diagnostics),
        warnings=warnings,
        extensions={"completed_run": metadata.to_dict()},
    )


def _selected_payload_refs(
    metadata: "CompletedRunBundleMetadata",
    options: RunBundleExportOptions,
) -> tuple[tuple[RunBundlePayloadReference, ...], tuple[RunExchangeDiagnostic, ...]]:
    selected: list[RunBundlePayloadReference] = []
    diagnostics: list[RunExchangeDiagnostic] = []
    for index, ref in enumerate(metadata.materialized_refs, start=1):
        if not _select_ref(ref, options):
            continue
        payload_ref, ref_diagnostics = _payload_ref(index, ref)
        selected.append(payload_ref)
        diagnostics.extend(ref_diagnostics)

    if (
        options.max_payload_count is not None
        and len(selected) > options.max_payload_count
    ):
        diagnostics.append(
            _diagnostic(
                "run_bundle_export.payload_count_exceeded",
                "selected payload count exceeds the configured limit",
                selected_payload_count=len(selected),
                max_payload_count=options.max_payload_count,
            )
        )
    return tuple(selected), tuple(diagnostics)


def _select_ref(ref: "MaterializedRef", options: RunBundleExportOptions) -> bool:
    kind = ref.kind.value
    if kind == "artifact_payload":
        return options.include_payloads
    if kind == "stage_log":
        return options.include_logs
    if kind in {"config", "provenance", "worker_handoff"}:
        return options.include_workspace
    return False


def _payload_ref(
    index: int,
    ref: "MaterializedRef",
) -> tuple[RunBundlePayloadReference, tuple[RunExchangeDiagnostic, ...]]:
    diagnostics: list[RunExchangeDiagnostic] = []
    entry_path = _archive_path_for_ref(index, ref)
    checksum = ref.checksum
    size = _file_size(ref.uri)
    if size is None:
        diagnostics.append(
            _diagnostic(
                "run_bundle_export.payload_missing",
                "selected payload is missing or is not a local file",
                uri=ref.uri,
                kind=ref.kind.value,
            )
        )
    return (
        RunBundlePayloadReference(
            entry_id=entry_path,
            uri=ref.uri,
            kind=_bundle_kind_for_ref(ref),
            selected=True,
        checksum_algorithm="sha256" if checksum is not None else None,
        checksum=checksum,
        size_bytes=size,
        extensions={"materialized_ref": thaw_plain_data(ref.to_dict())},
    ),
        tuple(diagnostics),
    )


def _entry_from_ref(ref: RunBundlePayloadReference) -> RunBundleEntry:
    source = _local_file_path(ref.uri)
    checksum = ref.checksum or hash_bytes(source.read_bytes())
    extensions = cast(
        Mapping[str, PlainData],
        thaw_plain_data(ref.extensions, path="extensions"),
    )
    return RunBundleEntry(
        entry_name=ref.entry_id,
        kind=ref.kind,
        path=normalize_bundle_member_path(ref.entry_id),
        selected=ref.selected,
        checksum_algorithm=ref.checksum_algorithm or "sha256",
        checksum=checksum,
        size_bytes=ref.size_bytes if ref.size_bytes is not None else source.stat().st_size,
        metadata={"source_uri": ref.uri, **extensions},
    )


def _archive_path_for_ref(index: int, ref: "MaterializedRef") -> str:
    suffix = _source_name(ref.uri) or f"payload-{index}"
    safe_suffix = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in suffix
    ).strip(".")
    if not safe_suffix:
        safe_suffix = f"payload-{index}"
    return normalize_bundle_member_path(
        f"payloads/{index:04d}-{ref.kind.value}-{safe_suffix}"
    )


def _source_name(uri: str) -> str | None:
    try:
        return uri_to_path(uri).name
    except (UnsupportedURIError, ValueError):
        return uri.rsplit("/", maxsplit=1)[-1] or None


def _bundle_kind_for_ref(ref: "MaterializedRef") -> RunBundleEntryKind:
    kind = ref.kind.value
    if kind == "stage_log":
        return RunBundleEntryKind.LOG
    if kind in {"config", "provenance", "worker_handoff"}:
        return RunBundleEntryKind.METADATA
    return RunBundleEntryKind.PAYLOAD


def _payload_sources(entries: Sequence[RunBundleEntry]) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for entry in entries:
        source_uri = entry.metadata.get("source_uri")
        if not isinstance(source_uri, str):
            continue
        sources[entry.path] = _local_file_path(source_uri)
    return sources


def _local_file_path(uri: str) -> Path:
    if get_uri_scheme(uri) not in {None, "file"}:
        raise CatalogValidationError(f"only local file payload refs can be materialized: {uri!r}")
    try:
        path = uri_to_path(uri)
    except (UnsupportedURIError, ValueError) as exc:
        raise CatalogValidationError(f"payload ref is not a local file URI: {uri!r}") from exc
    if not path.is_file():
        raise CatalogValidationError(f"payload ref does not point to a file: {uri!r}")
    return path


def _file_size(uri: str) -> int | None:
    try:
        path = _local_file_path(uri)
    except CatalogValidationError:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _add_bytes_member(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(normalize_bundle_member_path(name))
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def _archive_member_diagnostics(
    members: Sequence[tarfile.TarInfo],
) -> tuple[RunExchangeDiagnostic, ...]:
    diagnostics: list[RunExchangeDiagnostic] = []
    seen: set[str] = set()
    for member in members:
        try:
            normalized = normalize_bundle_member_path(member.name)
        except CatalogValidationError as exc:
            diagnostics.append(
                _diagnostic(
                    "run_bundle_inspect.unsafe_member_path",
                    str(exc),
                    member_name=member.name,
                )
            )
            continue
        if normalized in seen:
            diagnostics.append(
                _diagnostic(
                    "run_bundle_inspect.duplicate_member",
                    "bundle archive contains a duplicate member",
                    member_name=normalized,
                )
            )
        seen.add(normalized)
        if member.issym() or member.islnk():
            diagnostics.append(
                _diagnostic(
                    "run_bundle_inspect.link_member",
                    "bundle archive contains a link member",
                    member_name=normalized,
                )
            )
        if member.isfile() and member.size > _MAX_MEMBER_BYTES:
            diagnostics.append(
                _diagnostic(
                    "run_bundle_inspect.member_too_large",
                    "bundle archive member exceeds the inspect size limit",
                    member_name=normalized,
                    size_bytes=member.size,
                    max_size_bytes=_MAX_MEMBER_BYTES,
                )
            )
    return tuple(diagnostics)


def _find_manifest_member(members: Sequence[tarfile.TarInfo]) -> tarfile.TarInfo:
    matches: list[tarfile.TarInfo] = []
    for member in members:
        try:
            normalized = normalize_bundle_member_path(member.name)
        except CatalogValidationError:
            continue
        if normalized == RUN_BUNDLE_MANIFEST_MEMBER:
            matches.append(member)
    if len(matches) != 1:
        raise CatalogValidationError("bundle archive must contain exactly one manifest")
    manifest = matches[0]
    if not manifest.isfile():
        raise CatalogValidationError("bundle manifest member must be a regular file")
    if manifest.size > _MAX_MANIFEST_BYTES:
        raise CatalogValidationError("bundle manifest member exceeds the size limit")
    return manifest


def _read_manifest(
    archive: tarfile.TarFile,
    manifest_member: tarfile.TarInfo,
) -> RunBundleManifest:
    extracted = archive.extractfile(manifest_member)
    if extracted is None:
        raise CatalogValidationError("bundle manifest could not be read")
    try:
        import json

        payload = json.loads(extracted.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CatalogValidationError("bundle manifest is not valid JSON") from exc
    return RunBundleManifest.from_dict(payload)


def _checksum_diagnostics(
    archive: tarfile.TarFile,
    manifest: RunBundleManifest,
) -> tuple[RunExchangeDiagnostic, ...]:
    diagnostics: list[RunExchangeDiagnostic] = []
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        try:
            members[normalize_bundle_member_path(member.name)] = member
        except CatalogValidationError:
            continue
    for entry in manifest.entries:
        if entry.checksum is None:
            continue
        member = members.get(entry.path)
        if member is None or not member.isfile():
            diagnostics.append(
                _diagnostic(
                    "run_bundle_inspect.payload_missing",
                    "manifest entry is missing from the archive",
                    member_name=entry.path,
                )
            )
            continue
        extracted = archive.extractfile(member)
        if extracted is None:
            diagnostics.append(
                _diagnostic(
                    "run_bundle_inspect.payload_unreadable",
                    "manifest entry could not be read",
                    member_name=entry.path,
                )
            )
            continue
        actual = hash_bytes(extracted.read())
        if not compare_digests(actual, entry.checksum):
            diagnostics.append(
                _diagnostic(
                    "run_bundle_inspect.checksum_mismatch",
                    "manifest entry checksum does not match archive bytes",
                    member_name=entry.path,
                    expected_checksum=entry.checksum,
                    actual_checksum=actual,
                )
            )
    return tuple(diagnostics)


def _warning_diagnostics(
    warnings: Iterable["ReadModelWarning"],
) -> tuple[RunExchangeDiagnostic, ...]:
    return tuple(
        RunExchangeDiagnostic(
            code=f"read_model.{warning.code.value}",
            message=warning.message,
            severity=RunExchangeDiagnosticSeverity.WARNING,
            details=warning.to_dict(),
        )
        for warning in warnings
    )


def _has_error(diagnostics: Sequence[RunExchangeDiagnostic]) -> bool:
    return any(diagnostic.severity in _ERROR_SEVERITIES for diagnostic in diagnostics)


def _dedupe_diagnostics(
    diagnostics: Iterable[RunExchangeDiagnostic],
) -> tuple[RunExchangeDiagnostic, ...]:
    deduped: list[RunExchangeDiagnostic] = []
    seen: set[bytes] = set()
    for diagnostic in diagnostics:
        key = stable_json_bytes(diagnostic.to_dict())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(diagnostic)
    return tuple(deduped)


def _diagnostic(
    code: str,
    message: str,
    **details: PlainData,
) -> RunExchangeDiagnostic:
    return RunExchangeDiagnostic(
        code=code,
        message=message,
        severity=RunExchangeDiagnosticSeverity.ERROR,
        details=cast(Mapping[str, PlainData], details),
    )


__all__ = [
    "LOCAL_RUN_BUNDLE_ADAPTER",
    "RUN_BUNDLE_MANIFEST_MEMBER",
    "LocalRunBundleExporter",
    "build_portable_run_export_record",
    "export_completed_run_bundle",
    "export_run_bundle",
    "inspect_run_bundle",
    "normalize_bundle_member_path",
    "write_local_run_bundle",
]
