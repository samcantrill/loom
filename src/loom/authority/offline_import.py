"""Strict v10 offline evidence import validation and service helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

from loom.pipeline.offline_evidence import (
    OFFLINE_EVIDENCE_KIND,
    OFFLINE_EVIDENCE_SCHEMA_VERSION,
    OfflineEvidenceManifest,
    OfflineEvidenceManifestStatus,
    OfflineEvidenceSeverity,
    OfflineStageEvidence,
    read_offline_evidence_manifest,
)
from loom.pipeline.events import PipelineEventRecord
from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import AuthoritativeRunSnapshot
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from ._repository import AuthorityRepository, AuthorityRepositoryError


class OfflineImportRejectionKind(StrEnum):
    """Machine-readable offline import rejection kinds."""

    SCHEMA = "schema"
    SOURCE = "source"
    INCOMPLETE = "incomplete"
    RUN_STATUS = "run_status"
    PLAN = "plan"
    STAGE = "stage"
    ARTIFACT = "artifact"
    EVENT = "event"
    CONFLICT = "conflict"
    TRANSACTION = "transaction"


class OfflineImportError(ValueError):
    """Raised when offline evidence import is rejected."""

    def __init__(
        self,
        message: str,
        *,
        kind: OfflineImportRejectionKind,
        diagnostics: Sequence["OfflineImportDiagnostic"] = (),
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.diagnostics = tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class OfflineImportDiagnostic:
    """One concrete validation or import rejection reason."""

    code: str
    message: str
    kind: OfflineImportRejectionKind
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _non_empty(self.code, "code"))
        object.__setattr__(self, "message", _non_empty(self.message, "message"))
        object.__setattr__(
            self,
            "kind",
            _coerce_kind(self.kind),
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "kind": self.kind.value,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class OfflineImportResult:
    """Accepted offline import result facts."""

    run_uri: str
    status: str
    revision_sequence: int
    imported_stage_count: int
    imported_artifact_count: int
    import_provenance: Mapping[str, PlainData]

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_uri", _non_empty(self.run_uri, "run_uri"))
        object.__setattr__(self, "status", _non_empty(self.status, "status"))
        if (
            not isinstance(self.revision_sequence, int)
            or isinstance(self.revision_sequence, bool)
            or self.revision_sequence <= 0
        ):
            raise ValueError("revision_sequence must be a positive integer")
        for field_name in ("imported_stage_count", "imported_artifact_count"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer")
        object.__setattr__(
            self,
            "import_provenance",
            _plain_mapping(self.import_provenance, "import_provenance"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "status": self.status,
            "revision_sequence": self.revision_sequence,
            "imported_stage_count": self.imported_stage_count,
            "imported_artifact_count": self.imported_artifact_count,
            "import_provenance": dict(self.import_provenance),
        }


def load_offline_import_manifest(path: str | Path) -> OfflineEvidenceManifest:
    """Read a v10 offline evidence manifest from disk."""

    return read_offline_evidence_manifest(path)


def validate_offline_import_manifest(
    manifest: OfflineEvidenceManifest,
) -> tuple[OfflineImportDiagnostic, ...]:
    """Return strict import rejection diagnostics for a v10 manifest."""

    diagnostics: list[OfflineImportDiagnostic] = []
    if manifest.kind != OFFLINE_EVIDENCE_KIND:
        diagnostics.append(
            _diagnostic(
                "offline_import.kind",
                "offline evidence kind is not importable",
                OfflineImportRejectionKind.SCHEMA,
                expected=OFFLINE_EVIDENCE_KIND,
                actual=manifest.kind,
            )
        )
    if manifest.schema_version != OFFLINE_EVIDENCE_SCHEMA_VERSION:
        diagnostics.append(
            _diagnostic(
                "offline_import.schema_version",
                "offline evidence schema version is not supported",
                OfflineImportRejectionKind.SCHEMA,
                expected=OFFLINE_EVIDENCE_SCHEMA_VERSION,
                actual=manifest.schema_version,
            )
        )
    if manifest.state_source.get("authoritative") is not False:
        diagnostics.append(
            _diagnostic(
                "offline_import.authoritative_source",
                "offline import requires non-authoritative evidence",
                OfflineImportRejectionKind.SOURCE,
            )
        )
    if manifest.manifest_status is not OfflineEvidenceManifestStatus.COMPLETE:
        diagnostics.append(
            _diagnostic(
                "offline_import.incomplete_manifest",
                "offline evidence manifest is incomplete",
                OfflineImportRejectionKind.INCOMPLETE,
                manifest_status=manifest.manifest_status.value,
            )
        )
    for evidence_diagnostic in manifest.diagnostics:
        if evidence_diagnostic.severity is OfflineEvidenceSeverity.ERROR:
            diagnostics.append(
                _diagnostic(
                    "offline_import.evidence_error",
                    "offline evidence contains an error diagnostic",
                    OfflineImportRejectionKind.INCOMPLETE,
                    evidence_code=evidence_diagnostic.code,
                    evidence_message=evidence_diagnostic.message,
                )
            )

    run_status = _mapping_or_none(manifest.run_status)
    if run_status is None:
        diagnostics.append(
            _diagnostic(
                "offline_import.run_status_missing",
                "offline evidence is missing run status",
                OfflineImportRejectionKind.RUN_STATUS,
            )
        )
    else:
        if run_status.get("run_uri") != manifest.run_uri:
            diagnostics.append(
                _diagnostic(
                    "offline_import.run_uri_mismatch",
                    "manifest run URI and run status URI differ",
                    OfflineImportRejectionKind.RUN_STATUS,
                    manifest_run_uri=manifest.run_uri,
                    status_run_uri=run_status.get("run_uri"),
                )
            )
        try:
            status = RunStatus(cast(str, run_status.get("status")))
        except (TypeError, ValueError):
            diagnostics.append(
                _diagnostic(
                    "offline_import.run_status_invalid",
                    "run status is not a known run status",
                    OfflineImportRejectionKind.RUN_STATUS,
                    status=run_status.get("status"),
                )
            )
        else:
            if status not in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
                RunStatus.INTERRUPTED,
            }:
                diagnostics.append(
                    _diagnostic(
                        "offline_import.run_status_non_terminal",
                        "run status must be terminal before import",
                        OfflineImportRejectionKind.RUN_STATUS,
                        status=status.value,
                    )
                )

    plan = _execution_plan(manifest, diagnostics)
    stage_names = tuple(stage.stage_name for stage in manifest.stages)
    if plan is not None and tuple(plan.stage_order) != stage_names:
        diagnostics.append(
            _diagnostic(
                "offline_import.stage_order_mismatch",
                "manifest stage order does not match execution plan",
                OfflineImportRejectionKind.PLAN,
                plan_stage_order=list(plan.stage_order),
                manifest_stage_order=list(stage_names),
            )
        )
    if len(set(stage_names)) != len(stage_names):
        diagnostics.append(
            _diagnostic(
                "offline_import.duplicate_stage",
                "offline evidence contains duplicate stage names",
                OfflineImportRejectionKind.STAGE,
            )
        )

    for stage in manifest.stages:
        _validate_stage(stage, diagnostics)
    _validate_events(manifest, diagnostics)
    return tuple(diagnostics)


def reject_if_offline_import_invalid(manifest: OfflineEvidenceManifest) -> None:
    """Raise an import error when the manifest is not importable."""

    diagnostics = validate_offline_import_manifest(manifest)
    if not diagnostics:
        return
    first = diagnostics[0]
    raise OfflineImportError(
        first.message,
        kind=first.kind,
        diagnostics=diagnostics,
    )


def import_offline_evidence_manifest(
    repository: AuthorityRepository,
    manifest: OfflineEvidenceManifest,
    *,
    imported_by: str = "offline-import",
    workspace_id: str | None = None,
) -> OfflineImportResult:
    """Validate and import one manifest through the private authority repository."""

    reject_if_offline_import_invalid(manifest)
    try:
        snapshot = repository.import_offline_evidence_manifest(
            manifest,
            imported_by=imported_by,
            workspace_id=workspace_id,
        )
    except AuthorityRepositoryError as exc:
        text = str(exc)
        kind = (
            OfflineImportRejectionKind.CONFLICT
            if "already exists" in text
            else OfflineImportRejectionKind.TRANSACTION
        )
        raise OfflineImportError(
            text,
            kind=kind,
            diagnostics=(
                _diagnostic(
                    "offline_import.repository_rejected",
                    text,
                    kind,
                    run_uri=manifest.run_uri,
                ),
            ),
        ) from exc
    return _result_from_snapshot(snapshot)


def _result_from_snapshot(snapshot: AuthoritativeRunSnapshot) -> OfflineImportResult:
    import_provenance = snapshot.metadata.get("authority_import", {})
    if not isinstance(import_provenance, Mapping):
        import_provenance = {}
    return OfflineImportResult(
        run_uri=snapshot.run_uri,
        status=snapshot.status.value,
        revision_sequence=snapshot.revision.sequence,
        imported_stage_count=len(snapshot.stages),
        imported_artifact_count=sum(len(stage.artifact_facts) for stage in snapshot.stages),
        import_provenance=cast(Mapping[str, PlainData], import_provenance),
    )


def _execution_plan(
    manifest: OfflineEvidenceManifest,
    diagnostics: list[OfflineImportDiagnostic],
) -> ExecutionPlan | None:
    if manifest.plan is None:
        diagnostics.append(
            _diagnostic(
                "offline_import.plan_missing",
                "offline evidence is missing an execution plan",
                OfflineImportRejectionKind.PLAN,
            )
        )
        return None
    try:
        return ExecutionPlan.from_dict(manifest.plan)
    except Exception as exc:
        diagnostics.append(
            _diagnostic(
                "offline_import.plan_invalid",
                "offline evidence execution plan is invalid",
                OfflineImportRejectionKind.PLAN,
                error=str(exc),
            )
        )
        return None


def _validate_stage(
    stage: OfflineStageEvidence,
    diagnostics: list[OfflineImportDiagnostic],
) -> None:
    status_data = _mapping_or_none(stage.status)
    if status_data is None:
        diagnostics.append(
            _diagnostic(
                "offline_import.stage_status_missing",
                "offline evidence is missing stage status",
                OfflineImportRejectionKind.STAGE,
                stage=stage.stage_name,
            )
        )
        return
    if status_data.get("stage_name") not in {None, stage.stage_name}:
        diagnostics.append(
            _diagnostic(
                "offline_import.stage_status_name_mismatch",
                "stage status does not match evidence stage name",
                OfflineImportRejectionKind.STAGE,
                stage=stage.stage_name,
                status_stage=status_data.get("stage_name"),
            )
        )
    try:
        status = StageStatus(cast(str, status_data.get("status")))
    except (TypeError, ValueError):
        diagnostics.append(
            _diagnostic(
                "offline_import.stage_status_invalid",
                "stage status is not a known stage status",
                OfflineImportRejectionKind.STAGE,
                stage=stage.stage_name,
                status=status_data.get("status"),
            )
        )
        return
    if status not in {
        StageStatus.SUCCEEDED,
        StageStatus.FAILED,
        StageStatus.BLOCKED,
        StageStatus.SKIPPED,
        StageStatus.STALE,
        StageStatus.CANCELLED,
    }:
        diagnostics.append(
            _diagnostic(
                "offline_import.stage_status_non_terminal",
                "stage status must be terminal before import",
                OfflineImportRejectionKind.STAGE,
                stage=stage.stage_name,
                status=status.value,
            )
        )
    attempt = status_data.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
        diagnostics.append(
            _diagnostic(
                "offline_import.stage_attempt_missing",
                "stage status must include a positive attempt",
                OfflineImportRejectionKind.STAGE,
                stage=stage.stage_name,
                attempt=attempt,
            )
        )
    output_names = set((stage.outputs or {}).keys())
    artifact_names = {artifact.name for artifact in stage.artifacts}
    if not artifact_names.issubset(output_names):
        diagnostics.append(
            _diagnostic(
                "offline_import.artifact_without_output",
                "stage artifact evidence references an unknown output",
                OfflineImportRejectionKind.ARTIFACT,
                stage=stage.stage_name,
                artifact_names=list(sorted(artifact_names)),
                output_names=list(sorted(output_names)),
            )
        )
    for output_name, output in (stage.outputs or {}).items():
        if not isinstance(output, Mapping):
            diagnostics.append(
                _diagnostic(
                    "offline_import.output_invalid",
                    "stage output is not an artifact reference mapping",
                    OfflineImportRejectionKind.ARTIFACT,
                    stage=stage.stage_name,
                    output=output_name,
                )
            )
    for artifact in stage.artifacts:
        payload = artifact.payload
        if payload is None:
            continue
        for payload_diagnostic in payload.diagnostics:
            if payload_diagnostic.severity is OfflineEvidenceSeverity.ERROR:
                diagnostics.append(
                    _diagnostic(
                        "offline_import.artifact_payload_error",
                        "artifact payload evidence contains an error diagnostic",
                        OfflineImportRejectionKind.ARTIFACT,
                        stage=stage.stage_name,
                        artifact=artifact.name,
                        evidence_code=payload_diagnostic.code,
                    )
                )


def _validate_events(
    manifest: OfflineEvidenceManifest,
    diagnostics: list[OfflineImportDiagnostic],
) -> None:
    previous_sequence = 0
    for event in manifest.events:
        try:
            record = PipelineEventRecord.from_dict(event)
        except Exception as exc:
            diagnostics.append(
                _diagnostic(
                    "offline_import.event_invalid",
                    "offline event is not a valid pipeline event record",
                    OfflineImportRejectionKind.EVENT,
                    error=str(exc),
                )
            )
            continue
        if record.run_uri != manifest.run_uri:
            diagnostics.append(
                _diagnostic(
                    "offline_import.event_run_uri_mismatch",
                    "offline event run URI does not match manifest run URI",
                    OfflineImportRejectionKind.EVENT,
                    manifest_run_uri=manifest.run_uri,
                    event_run_uri=record.run_uri,
                )
            )
        if record.sequence <= previous_sequence:
            diagnostics.append(
                _diagnostic(
                    "offline_import.event_order",
                    "offline event sequences must be strictly increasing",
                    OfflineImportRejectionKind.EVENT,
                    previous_sequence=previous_sequence,
                    sequence=record.sequence,
                )
            )
        previous_sequence = record.sequence


def _mapping_or_none(value: object) -> Mapping[str, PlainData] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, PlainData], value)


def _diagnostic(
    code: str,
    message: str,
    kind: OfflineImportRejectionKind,
    **detail: PlainData,
) -> OfflineImportDiagnostic:
    return OfflineImportDiagnostic(
        code=code,
        message=message,
        kind=kind,
        detail=detail,
    )


def _coerce_kind(value: object) -> OfflineImportRejectionKind:
    if isinstance(value, OfflineImportRejectionKind):
        return value
    if not isinstance(value, str):
        raise ValueError("kind must be a string")
    try:
        return OfflineImportRejectionKind(value)
    except ValueError as exc:
        raise ValueError(f"invalid kind: {value!r}") from exc


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise ValueError(f"{field} must be plain-data compatible") from exc
    if not isinstance(normalized, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "OfflineImportDiagnostic",
    "OfflineImportError",
    "OfflineImportRejectionKind",
    "OfflineImportResult",
    "import_offline_evidence_manifest",
    "load_offline_import_manifest",
    "reject_if_offline_import_invalid",
    "validate_offline_import_manifest",
]
