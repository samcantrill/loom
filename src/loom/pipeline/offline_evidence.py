"""Versioned offline execution evidence manifests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_bytes
from loom.io.errors import UnsupportedURIError
from loom.io.uris import uri_to_path
from loom.pipeline.events import PipelineEventRecord
from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.status import StageStatusRecord
from loom.pipeline.stores.atomic import atomic_write_json
from loom.pipeline.stores.local_runs import LocalRunStore
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError
from loom.state_sources import offline_evidence_source
from loom.timestamps import utc_timestamp

OFFLINE_EVIDENCE_SCHEMA_VERSION = 1
OFFLINE_EVIDENCE_KIND = "loom.offline_evidence_manifest"
OFFLINE_EVIDENCE_RELATIVE_PATH = "offline-evidence/manifest.json"

_CONFIG_SNAPSHOT_NAMES = (
    "raw",
    "overlays",
    "cli_overrides",
    "resolved",
    "resolved_redacted",
)
_PROVENANCE_NAMES = ("environment", "git", "command", "dependencies")
_LOG_STREAMS = ("stdout", "stderr")
_TERMINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"}


class OfflineEvidenceError(ValueError):
    """Raised when offline evidence cannot be read, written, or validated."""


class OfflineEvidenceSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class OfflineEvidenceManifestStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class OfflineEvidenceDiagnostic:
    """Diagnostic attached to an offline evidence manifest."""

    code: str
    message: str
    severity: OfflineEvidenceSeverity = OfflineEvidenceSeverity.ERROR
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _non_empty(self.code, "code"))
        object.__setattr__(self, "message", _non_empty(self.message, "message"))
        object.__setattr__(
            self,
            "severity",
            _enum(self.severity, OfflineEvidenceSeverity, "severity"),
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: object) -> "OfflineEvidenceDiagnostic":
        mapping = _mapping(data, "OfflineEvidenceDiagnostic")
        _reject_unknown(
            mapping,
            {"code", "message", "severity", "detail"},
            "OfflineEvidenceDiagnostic",
        )
        return cls(
            code=_non_empty(_required(mapping, "code"), "code"),
            message=_non_empty(_required(mapping, "message"), "message"),
            severity=_enum(
                mapping.get("severity", OfflineEvidenceSeverity.ERROR.value),
                OfflineEvidenceSeverity,
                "severity",
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class OfflineEvidenceFileRef:
    """Local evidence about a referenced payload or log file."""

    path: str
    exists: bool
    size_bytes: int | None = None
    checksum: str | None = None
    diagnostics: tuple[OfflineEvidenceDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _non_empty(self.path, "path"))
        if not isinstance(self.exists, bool):
            raise OfflineEvidenceError("exists must be a bool")
        if self.size_bytes is not None:
            object.__setattr__(
                self, "size_bytes", _non_negative_int(self.size_bytes, "size_bytes")
            )
        if self.checksum is not None:
            object.__setattr__(self, "checksum", _non_empty(self.checksum, "checksum"))
        object.__setattr__(
            self,
            "diagnostics",
            _diagnostic_tuple(self.diagnostics, "diagnostics"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "path": self.path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: object) -> "OfflineEvidenceFileRef":
        mapping = _mapping(data, "OfflineEvidenceFileRef")
        _reject_unknown(
            mapping,
            {"path", "exists", "size_bytes", "checksum", "diagnostics"},
            "OfflineEvidenceFileRef",
        )
        return cls(
            path=_non_empty(_required(mapping, "path"), "path"),
            exists=_bool(_required(mapping, "exists"), "exists"),
            size_bytes=_optional_non_negative_int(
                mapping.get("size_bytes"), "size_bytes"
            ),
            checksum=_optional_non_empty(mapping.get("checksum"), "checksum"),
            diagnostics=tuple(
                OfflineEvidenceDiagnostic.from_dict(item)
                for item in _sequence(mapping.get("diagnostics", ()), "diagnostics")
            ),
        )


@dataclass(frozen=True, slots=True)
class OfflineArtifactEvidence:
    """Evidence for one produced artifact reference."""

    name: str
    ref: ArtifactRef
    payload: OfflineEvidenceFileRef | None = None
    diagnostics: tuple[OfflineEvidenceDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty(self.name, "name"))
        if not isinstance(self.ref, ArtifactRef):
            raise OfflineEvidenceError("ref must be an ArtifactRef")
        if self.payload is not None and not isinstance(
            self.payload, OfflineEvidenceFileRef
        ):
            raise OfflineEvidenceError("payload must be an OfflineEvidenceFileRef")
        object.__setattr__(
            self,
            "diagnostics",
            _diagnostic_tuple(self.diagnostics, "diagnostics"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "name": self.name,
            "ref": cast(dict[str, PlainData], self.ref.to_dict()),
            "payload": None if self.payload is None else self.payload.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: object) -> "OfflineArtifactEvidence":
        mapping = _mapping(data, "OfflineArtifactEvidence")
        _reject_unknown(
            mapping,
            {"name", "ref", "payload", "diagnostics"},
            "OfflineArtifactEvidence",
        )
        payload = mapping.get("payload")
        return cls(
            name=_non_empty(_required(mapping, "name"), "name"),
            ref=ArtifactRef.from_dict(_required(mapping, "ref")),
            payload=None if payload is None else OfflineEvidenceFileRef.from_dict(payload),
            diagnostics=tuple(
                OfflineEvidenceDiagnostic.from_dict(item)
                for item in _sequence(mapping.get("diagnostics", ()), "diagnostics")
            ),
        )


@dataclass(frozen=True, slots=True)
class OfflineStageEvidence:
    """Evidence for one planned stage."""

    stage_name: str
    plan: Mapping[str, PlainData]
    status: Mapping[str, PlainData] | None
    inputs: Mapping[str, PlainData] | None = None
    outputs: Mapping[str, PlainData] | None = None
    fingerprint: Mapping[str, PlainData] | None = None
    failure: Mapping[str, PlainData] | None = None
    resources: Mapping[str, PlainData] | None = None
    artifacts: tuple[OfflineArtifactEvidence, ...] = ()
    logs: Mapping[str, Mapping[str, PlainData]] = field(default_factory=dict)
    diagnostics: tuple[OfflineEvidenceDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_name", _non_empty(self.stage_name, "stage_name"))
        object.__setattr__(self, "plan", _plain_mapping(self.plan, "plan"))
        for field_name in ("status", "inputs", "outputs", "fingerprint", "failure"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self, field_name, _plain_mapping(value, field_name)
                )
        if self.resources is not None:
            object.__setattr__(
                self, "resources", _plain_mapping(self.resources, "resources")
            )
        artifacts = tuple(self.artifacts)
        if any(not isinstance(item, OfflineArtifactEvidence) for item in artifacts):
            raise OfflineEvidenceError("artifacts must contain OfflineArtifactEvidence")
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "logs", _nested_plain_mapping(self.logs, "logs"))
        object.__setattr__(
            self,
            "diagnostics",
            _diagnostic_tuple(self.diagnostics, "diagnostics"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "stage_name": self.stage_name,
            "plan": dict(self.plan),
            "status": None if self.status is None else dict(self.status),
            "inputs": None if self.inputs is None else dict(self.inputs),
            "outputs": None if self.outputs is None else dict(self.outputs),
            "fingerprint": None
            if self.fingerprint is None
            else dict(self.fingerprint),
            "failure": None if self.failure is None else dict(self.failure),
            "resources": None if self.resources is None else dict(self.resources),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "logs": {name: dict(value) for name, value in self.logs.items()},
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: object) -> "OfflineStageEvidence":
        mapping = _mapping(data, "OfflineStageEvidence")
        _reject_unknown(
            mapping,
            {
                "stage_name",
                "plan",
                "status",
                "inputs",
                "outputs",
                "fingerprint",
                "failure",
                "resources",
                "artifacts",
                "logs",
                "diagnostics",
            },
            "OfflineStageEvidence",
        )
        return cls(
            stage_name=_non_empty(_required(mapping, "stage_name"), "stage_name"),
            plan=_plain_mapping(_required(mapping, "plan"), "plan"),
            status=_optional_plain_mapping(mapping.get("status"), "status"),
            inputs=_optional_plain_mapping(mapping.get("inputs"), "inputs"),
            outputs=_optional_plain_mapping(mapping.get("outputs"), "outputs"),
            fingerprint=_optional_plain_mapping(
                mapping.get("fingerprint"), "fingerprint"
            ),
            failure=_optional_plain_mapping(mapping.get("failure"), "failure"),
            resources=_optional_plain_mapping(mapping.get("resources"), "resources"),
            artifacts=tuple(
                OfflineArtifactEvidence.from_dict(item)
                for item in _sequence(mapping.get("artifacts", ()), "artifacts")
            ),
            logs=_nested_plain_mapping(mapping.get("logs", {}), "logs"),
            diagnostics=tuple(
                OfflineEvidenceDiagnostic.from_dict(item)
                for item in _sequence(mapping.get("diagnostics", ()), "diagnostics")
            ),
        )


@dataclass(frozen=True, slots=True)
class OfflineEvidenceManifest:
    """Versioned evidence manifest for one explicit offline-first run."""

    run_uri: str
    generated_at: str
    manifest_status: OfflineEvidenceManifestStatus
    run_status: Mapping[str, PlainData] | None
    plan: Mapping[str, PlainData] | None
    runtime: Mapping[str, PlainData] | None
    config: Mapping[str, PlainData]
    provenance: Mapping[str, PlainData]
    stages: tuple[OfflineStageEvidence, ...]
    events: tuple[Mapping[str, PlainData], ...]
    artifact_index: Mapping[str, Mapping[str, PlainData]]
    diagnostics: tuple[OfflineEvidenceDiagnostic, ...] = ()
    state_source: Mapping[str, PlainData] = field(default_factory=offline_evidence_source)
    schema_version: int = OFFLINE_EVIDENCE_SCHEMA_VERSION
    kind: str = OFFLINE_EVIDENCE_KIND

    def __post_init__(self) -> None:
        if self.schema_version != OFFLINE_EVIDENCE_SCHEMA_VERSION:
            raise OfflineEvidenceError(
                "OfflineEvidenceManifest.schema_version must be "
                f"{OFFLINE_EVIDENCE_SCHEMA_VERSION}"
            )
        if self.kind != OFFLINE_EVIDENCE_KIND:
            raise OfflineEvidenceError(
                f"OfflineEvidenceManifest.kind must be {OFFLINE_EVIDENCE_KIND!r}"
            )
        object.__setattr__(self, "run_uri", _non_empty(self.run_uri, "run_uri"))
        object.__setattr__(
            self, "generated_at", _non_empty(self.generated_at, "generated_at")
        )
        object.__setattr__(
            self,
            "manifest_status",
            _enum(
                self.manifest_status,
                OfflineEvidenceManifestStatus,
                "manifest_status",
            ),
        )
        object.__setattr__(
            self,
            "run_status",
            _optional_plain_mapping(self.run_status, "run_status"),
        )
        object.__setattr__(self, "plan", _optional_plain_mapping(self.plan, "plan"))
        object.__setattr__(
            self, "runtime", _optional_plain_mapping(self.runtime, "runtime")
        )
        object.__setattr__(self, "config", _plain_mapping(self.config, "config"))
        object.__setattr__(
            self, "provenance", _plain_mapping(self.provenance, "provenance")
        )
        stages = tuple(self.stages)
        if any(not isinstance(stage, OfflineStageEvidence) for stage in stages):
            raise OfflineEvidenceError("stages must contain OfflineStageEvidence")
        object.__setattr__(self, "stages", stages)
        object.__setattr__(
            self,
            "events",
            tuple(_plain_mapping(event, "events[]") for event in self.events),
        )
        object.__setattr__(
            self,
            "artifact_index",
            {
                _non_empty(name, "artifact_index key"): _plain_mapping(
                    value, f"artifact_index[{name}]"
                )
                for name, value in self.artifact_index.items()
            },
        )
        object.__setattr__(
            self,
            "diagnostics",
            _diagnostic_tuple(self.diagnostics, "diagnostics"),
        )
        state_source = _plain_mapping(self.state_source, "state_source")
        if state_source.get("authoritative") is not False:
            raise OfflineEvidenceError("offline evidence state_source must be non-authoritative")
        object.__setattr__(self, "state_source", state_source)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_uri": self.run_uri,
            "generated_at": self.generated_at,
            "manifest_status": self.manifest_status.value,
            "state_source": dict(self.state_source),
            "run_status": None
            if self.run_status is None
            else dict(self.run_status),
            "plan": None if self.plan is None else dict(self.plan),
            "runtime": None if self.runtime is None else dict(self.runtime),
            "config": dict(self.config),
            "provenance": dict(self.provenance),
            "stages": [stage.to_dict() for stage in self.stages],
            "events": [dict(event) for event in self.events],
            "artifact_index": {
                name: dict(value) for name, value in self.artifact_index.items()
            },
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: object) -> "OfflineEvidenceManifest":
        mapping = _mapping(data, "OfflineEvidenceManifest")
        _reject_unknown(
            mapping,
            {
                "schema_version",
                "kind",
                "run_uri",
                "generated_at",
                "manifest_status",
                "state_source",
                "run_status",
                "plan",
                "runtime",
                "config",
                "provenance",
                "stages",
                "events",
                "artifact_index",
                "diagnostics",
            },
            "OfflineEvidenceManifest",
        )
        return cls(
            schema_version=_schema_version(_required(mapping, "schema_version")),
            kind=_non_empty(_required(mapping, "kind"), "kind"),
            run_uri=_non_empty(_required(mapping, "run_uri"), "run_uri"),
            generated_at=_non_empty(_required(mapping, "generated_at"), "generated_at"),
            manifest_status=_enum(
                _required(mapping, "manifest_status"),
                OfflineEvidenceManifestStatus,
                "manifest_status",
            ),
            state_source=_plain_mapping(
                _required(mapping, "state_source"), "state_source"
            ),
            run_status=_optional_plain_mapping(mapping.get("run_status"), "run_status"),
            plan=_optional_plain_mapping(mapping.get("plan"), "plan"),
            runtime=_optional_plain_mapping(mapping.get("runtime"), "runtime"),
            config=_plain_mapping(_required(mapping, "config"), "config"),
            provenance=_plain_mapping(_required(mapping, "provenance"), "provenance"),
            stages=tuple(
                OfflineStageEvidence.from_dict(item)
                for item in _sequence(_required(mapping, "stages"), "stages")
            ),
            events=tuple(
                _plain_mapping(item, "events[]")
                for item in _sequence(_required(mapping, "events"), "events")
            ),
            artifact_index={
                _non_empty(name, "artifact_index key"): _plain_mapping(
                    value, f"artifact_index[{name}]"
                )
                for name, value in _mapping(
                    _required(mapping, "artifact_index"), "artifact_index"
                ).items()
            },
            diagnostics=tuple(
                OfflineEvidenceDiagnostic.from_dict(item)
                for item in _sequence(mapping.get("diagnostics", ()), "diagnostics")
            ),
        )

    @property
    def complete(self) -> bool:
        return self.manifest_status is OfflineEvidenceManifestStatus.COMPLETE


def offline_evidence_manifest_path(store: LocalRunStore, run_uri: str) -> Path:
    """Return the canonical v10 offline evidence manifest path for a run."""

    return store.local_generated_artifact_path(run_uri, OFFLINE_EVIDENCE_RELATIVE_PATH)


def collect_offline_evidence_manifest(
    store: LocalRunStore,
    run_uri: str,
    *,
    generated_at: str | None = None,
) -> OfflineEvidenceManifest:
    """Collect manifest evidence from an explicit offline local run."""

    diagnostics: list[OfflineEvidenceDiagnostic] = []
    generated = generated_at or utc_timestamp()
    run_status = _read_run_status(store, run_uri, diagnostics)
    plan_payload = _read_plan(store, run_uri, diagnostics)
    runtime = _read_runtime(store, run_uri, diagnostics)
    plan = _execution_plan(plan_payload, diagnostics)
    stage_names = _stage_names(store, run_uri, plan, diagnostics)
    stages = tuple(
        _stage_evidence(
            store,
            run_uri=run_uri,
            stage_name=stage_name,
            plan_payload=_stage_plan_payload(plan, stage_name),
            runtime=runtime,
        )
        for stage_name in stage_names
    )
    for stage in stages:
        diagnostics.extend(stage.diagnostics)
    artifact_index = _artifact_index(store, run_uri, diagnostics)
    events = _events(store, run_uri, diagnostics)
    config = _config_evidence(store, run_uri, diagnostics)
    provenance = _provenance_evidence(store, run_uri, diagnostics)
    if run_status is not None:
        status_value = run_status.get("status")
        if status_value not in _TERMINAL_RUN_STATUSES:
            diagnostics.append(
                OfflineEvidenceDiagnostic(
                    code="offline_evidence.run_not_terminal",
                    message="offline evidence was collected before a terminal run status",
                    detail={"status": status_value},
                )
            )
    complete = not any(
        diagnostic.severity is OfflineEvidenceSeverity.ERROR
        for diagnostic in diagnostics
    )
    return OfflineEvidenceManifest(
        run_uri=run_uri,
        generated_at=generated,
        manifest_status=OfflineEvidenceManifestStatus.COMPLETE
        if complete
        else OfflineEvidenceManifestStatus.INCOMPLETE,
        run_status=run_status,
        plan=plan_payload,
        runtime=runtime,
        config=config,
        provenance=provenance,
        stages=stages,
        events=events,
        artifact_index=artifact_index,
        diagnostics=tuple(diagnostics),
    )


def write_offline_evidence_manifest(
    store: LocalRunStore,
    run_uri: str,
    *,
    generated_at: str | None = None,
) -> OfflineEvidenceManifest:
    """Collect and atomically write the canonical offline evidence manifest."""

    manifest = collect_offline_evidence_manifest(
        store,
        run_uri,
        generated_at=generated_at,
    )
    atomic_write_json(offline_evidence_manifest_path(store, run_uri), manifest.to_dict())
    return manifest


def read_offline_evidence_manifest(path: str | Path) -> OfflineEvidenceManifest:
    """Read and validate an offline evidence manifest JSON document."""

    from loom.serialization import json_loads

    path_obj = Path(path)
    try:
        data = json_loads(path_obj.read_text(encoding="utf-8"), path=str(path_obj))
    except OSError as exc:
        raise OfflineEvidenceError(f"failed to read offline evidence manifest: {path_obj}") from exc
    return OfflineEvidenceManifest.from_dict(data)


def _read_run_status(
    store: LocalRunStore,
    run_uri: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> dict[str, PlainData] | None:
    try:
        status = store.read_run_status(run_uri)
    except Exception as exc:
        diagnostics.append(_error("offline_evidence.run_status_unreadable", str(exc)))
        return None
    if status is None:
        diagnostics.append(
            _error(
                "offline_evidence.run_status_missing",
                "run status is missing from local evidence",
            )
        )
        return None
    return status.to_dict()


def _read_plan(
    store: LocalRunStore,
    run_uri: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> dict[str, PlainData] | None:
    try:
        plan = store.read_plan(run_uri)
    except Exception as exc:
        diagnostics.append(_error("offline_evidence.plan_unreadable", str(exc)))
        return None
    if plan is None:
        diagnostics.append(
            _error("offline_evidence.plan_missing", "execution plan is missing")
        )
    return plan


def _read_runtime(
    store: LocalRunStore,
    run_uri: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> dict[str, PlainData] | None:
    try:
        runtime = store.read_runtime_metadata(run_uri)
    except Exception as exc:
        diagnostics.append(_error("offline_evidence.runtime_unreadable", str(exc)))
        return None
    if runtime is None:
        diagnostics.append(
            _error("offline_evidence.runtime_missing", "runtime metadata is missing")
        )
    return runtime


def _execution_plan(
    plan_payload: Mapping[str, PlainData] | None,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> ExecutionPlan | None:
    if plan_payload is None:
        return None
    try:
        return ExecutionPlan.from_dict(plan_payload)
    except Exception as exc:
        diagnostics.append(
            _error(
                "offline_evidence.plan_invalid",
                f"execution plan is invalid: {exc}",
            )
        )
        return None


def _stage_names(
    store: LocalRunStore,
    run_uri: str,
    plan: ExecutionPlan | None,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> tuple[str, ...]:
    if plan is not None:
        return tuple(plan.stage_order)
    try:
        return store.list_run_stages(run_uri)
    except Exception as exc:
        diagnostics.append(
            _error("offline_evidence.stage_list_unreadable", str(exc))
        )
        return ()


def _stage_plan_payload(
    plan: ExecutionPlan | None, stage_name: str
) -> dict[str, PlainData]:
    if plan is None:
        return {"stage_name": stage_name, "missing_plan": True}
    for stage_plan in plan.stage_plans:
        if stage_plan.stage_name == stage_name:
            return stage_plan.to_dict()
    return {"stage_name": stage_name, "missing_stage_plan": True}


def _stage_evidence(
    store: LocalRunStore,
    *,
    run_uri: str,
    stage_name: str,
    plan_payload: Mapping[str, PlainData],
    runtime: Mapping[str, PlainData] | None,
) -> OfflineStageEvidence:
    diagnostics: list[OfflineEvidenceDiagnostic] = []
    status_record = _stage_status(store, run_uri, stage_name, diagnostics)
    attempt = None if status_record is None else status_record.attempt
    inputs = _stage_mapping(store.read_stage_inputs, run_uri, stage_name, "inputs", diagnostics)
    outputs = _stage_mapping(store.read_stage_outputs, run_uri, stage_name, "outputs", diagnostics)
    fingerprint = _stage_mapping(
        store.read_stage_fingerprint, run_uri, stage_name, "fingerprint", diagnostics
    )
    failure = _stage_mapping(
        store.read_stage_failure, run_uri, stage_name, "failure", diagnostics
    )
    if status_record is None:
        diagnostics.append(
            _error(
                "offline_evidence.stage_status_missing",
                "stage status is missing from local evidence",
                stage=stage_name,
            )
        )
    resources = _stage_resources(runtime, stage_name)
    artifacts = tuple(
        _artifact_evidence(name, ArtifactRef.from_dict(ref), diagnostics)
        for name, ref in (outputs or {}).items()
        if isinstance(ref, Mapping)
    )
    return OfflineStageEvidence(
        stage_name=stage_name,
        plan=plan_payload,
        status=None if status_record is None else status_record.to_dict(),
        inputs=inputs,
        outputs=outputs,
        fingerprint=fingerprint,
        failure=failure,
        resources=resources,
        artifacts=artifacts,
        logs=_stage_logs(store, run_uri, stage_name, attempt),
        diagnostics=tuple(diagnostics),
    )


def _stage_status(
    store: LocalRunStore,
    run_uri: str,
    stage_name: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> StageStatusRecord | None:
    try:
        return store.read_stage_status(run_uri, stage_name)
    except Exception as exc:
        diagnostics.append(
            _error(
                "offline_evidence.stage_status_unreadable",
                str(exc),
                stage=stage_name,
            )
        )
        return None


def _stage_mapping(
    reader: Any,
    run_uri: str,
    stage_name: str,
    label: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> dict[str, PlainData] | None:
    try:
        value = reader(run_uri, stage_name)
    except Exception as exc:
        diagnostics.append(
            _warning(
                f"offline_evidence.stage_{label}_unreadable",
                str(exc),
                stage=stage_name,
            )
        )
        return None
    if value is None:
        return None
    if label in {"inputs", "outputs"}:
        return {
            name: cast(dict[str, PlainData], artifact.to_dict())
            for name, artifact in value.items()
        }
    return _plain_mapping(value, label)


def _stage_resources(
    runtime: Mapping[str, PlainData] | None, stage_name: str
) -> dict[str, PlainData] | None:
    if runtime is None:
        return None
    stages = runtime.get("stages")
    if not isinstance(stages, Mapping):
        return None
    stage_runtime = stages.get(stage_name)
    if not isinstance(stage_runtime, Mapping):
        return None
    resources = stage_runtime.get("resources")
    if not isinstance(resources, Mapping):
        return None
    return _plain_mapping(resources, "resources")


def _stage_logs(
    store: LocalRunStore, run_uri: str, stage_name: str, attempt: int | None
) -> dict[str, Mapping[str, PlainData]]:
    _ = attempt
    return {
        stream: _file_ref_for_path(
            store.local_stage_log_path(run_uri, stage_name, stream),
            missing_code=f"offline_evidence.{stream}_log_missing",
            missing_is_error=False,
        ).to_dict()
        for stream in _LOG_STREAMS
    }


def _artifact_evidence(
    name: str,
    ref: ArtifactRef,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> OfflineArtifactEvidence:
    payload = _payload_file_ref(ref)
    for diagnostic in payload.diagnostics:
        if diagnostic.severity is OfflineEvidenceSeverity.ERROR:
            diagnostics.append(diagnostic)
    return OfflineArtifactEvidence(name=name, ref=ref, payload=payload)


def _artifact_index(
    store: LocalRunStore,
    run_uri: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> dict[str, Mapping[str, PlainData]]:
    try:
        return {
            name: cast(dict[str, PlainData], ref.to_dict())
            for name, ref in store.read_artifact_index(run_uri).items()
        }
    except Exception as exc:
        diagnostics.append(_error("offline_evidence.artifact_index_unreadable", str(exc)))
        return {}


def _events(
    store: LocalRunStore,
    run_uri: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> tuple[Mapping[str, PlainData], ...]:
    try:
        records = store.read_events(run_uri)
    except Exception as exc:
        diagnostics.append(_error("offline_evidence.events_unreadable", str(exc)))
        return ()
    return tuple(_event_record(record) for record in records)


def _event_record(record: PipelineEventRecord) -> Mapping[str, PlainData]:
    return record.to_dict()


def _config_evidence(
    store: LocalRunStore,
    run_uri: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> dict[str, PlainData]:
    composition_manifest = None
    recipe_manifest: Sequence[Mapping[str, PlainData]] | None = None
    try:
        composition_manifest = store.read_composition_manifest(run_uri)
    except Exception as exc:
        diagnostics.append(
            _warning("offline_evidence.composition_manifest_unreadable", str(exc))
        )
    try:
        recipe_manifest = store.read_recipe_manifest(run_uri)
    except Exception as exc:
        diagnostics.append(
            _warning("offline_evidence.recipe_manifest_unreadable", str(exc))
        )
    return {
        "composition_manifest": composition_manifest,
        "recipe_manifest": list(recipe_manifest or ()),
        "snapshots": {
            name: _file_ref_for_path(
                store.local_config_path(run_uri, name),
                missing_code=f"offline_evidence.config_{name}_missing",
                missing_is_error=False,
            ).to_dict()
            for name in _CONFIG_SNAPSHOT_NAMES
        },
    }


def _provenance_evidence(
    store: LocalRunStore,
    run_uri: str,
    diagnostics: list[OfflineEvidenceDiagnostic],
) -> dict[str, PlainData]:
    documents: dict[str, PlainData] = {}
    for name in _PROVENANCE_NAMES:
        try:
            value = store.read_provenance_document(run_uri, name)
        except Exception as exc:
            diagnostics.append(
                _warning(
                    f"offline_evidence.provenance_{name}_unreadable",
                    str(exc),
                )
            )
            value = None
        documents[name] = value
    return {"documents": documents}


def _payload_file_ref(ref: ArtifactRef) -> OfflineEvidenceFileRef:
    try:
        path = uri_to_path(ref.uri)
    except UnsupportedURIError:
        return OfflineEvidenceFileRef(
            path=ref.uri,
            exists=False,
            diagnostics=(
                _warning(
                    "offline_evidence.artifact_payload_non_local",
                    "artifact payload URI is not a local file URI",
                    artifact_id=ref.artifact_id,
                    uri=ref.uri,
                ),
            ),
        )
    return _file_ref_for_path(
        path,
        missing_code="offline_evidence.artifact_payload_missing",
        detail={"artifact_id": ref.artifact_id, "uri": ref.uri},
    )


def _file_ref_for_path(
    path: str | Path,
    *,
    missing_code: str,
    missing_is_error: bool = True,
    detail: Mapping[str, PlainData] | None = None,
) -> OfflineEvidenceFileRef:
    path_obj = Path(path)
    base_detail = {} if detail is None else dict(detail)
    if not path_obj.exists():
        diagnostic = (
            _error if missing_is_error else _warning
        )(
            missing_code,
            "referenced evidence file is missing",
            path=str(path_obj),
            **base_detail,
        )
        return OfflineEvidenceFileRef(
            path=str(path_obj),
            exists=False,
            diagnostics=(diagnostic,),
        )
    if not path_obj.is_file():
        return OfflineEvidenceFileRef(
            path=str(path_obj),
            exists=True,
            diagnostics=(
                _error(
                    "offline_evidence.file_not_regular",
                    "referenced evidence path is not a regular file",
                    path=str(path_obj),
                    **base_detail,
                ),
            ),
        )
    try:
        data = path_obj.read_bytes()
    except OSError as exc:
        return OfflineEvidenceFileRef(
            path=str(path_obj),
            exists=True,
            diagnostics=(
                _error(
                    "offline_evidence.file_unreadable",
                    f"referenced evidence file is unreadable: {exc}",
                    path=str(path_obj),
                    **base_detail,
                ),
            ),
        )
    return OfflineEvidenceFileRef(
        path=str(path_obj),
        exists=True,
        size_bytes=len(data),
        checksum=hash_bytes(data),
    )


def _schema_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise OfflineEvidenceError("schema_version must be an integer")
    return value


def _enum(value: object, enum_type: type[Any], field: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise OfflineEvidenceError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise OfflineEvidenceError(f"invalid {field}: {value!r}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise OfflineEvidenceError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise OfflineEvidenceError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _plain_mapping(value: object, field: str) -> dict[str, PlainData]:
    try:
        plain = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise OfflineEvidenceError(f"{field} must be plain-data compatible: {exc}") from exc
    if not isinstance(plain, dict):
        raise OfflineEvidenceError(f"{field} must be a mapping")
    return plain


def _optional_plain_mapping(
    value: object | None, field: str
) -> dict[str, PlainData] | None:
    if value is None:
        return None
    return _plain_mapping(value, field)


def _nested_plain_mapping(value: object, field: str) -> dict[str, Mapping[str, PlainData]]:
    mapping = _mapping(value, field)
    return {
        _non_empty(name, f"{field} key"): _plain_mapping(item, f"{field}[{name}]")
        for name, item in mapping.items()
    }


def _diagnostic_tuple(
    value: Sequence[OfflineEvidenceDiagnostic],
    field: str,
) -> tuple[OfflineEvidenceDiagnostic, ...]:
    diagnostics = tuple(value)
    if any(not isinstance(item, OfflineEvidenceDiagnostic) for item in diagnostics):
        raise OfflineEvidenceError(f"{field} must contain OfflineEvidenceDiagnostic")
    return diagnostics


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise OfflineEvidenceError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise OfflineEvidenceError(
            f"{field} received unknown field(s): {', '.join(sorted(unknown))}"
        )


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise OfflineEvidenceError(f"{field} must be a sequence")
    return tuple(value)


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise OfflineEvidenceError(f"{field} must be a non-empty string")
    return value


def _optional_non_empty(value: object | None, field: str) -> str | None:
    if value is None:
        return None
    return _non_empty(value, field)


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise OfflineEvidenceError(f"{field} must be a bool")
    return value


def _non_negative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OfflineEvidenceError(f"{field} must be a non-negative integer")
    return value


def _optional_non_negative_int(value: object | None, field: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, field)


def _error(code: str, message: str, **detail: PlainData) -> OfflineEvidenceDiagnostic:
    return OfflineEvidenceDiagnostic(
        code=code,
        message=message,
        severity=OfflineEvidenceSeverity.ERROR,
        detail=detail,
    )


def _warning(code: str, message: str, **detail: PlainData) -> OfflineEvidenceDiagnostic:
    return OfflineEvidenceDiagnostic(
        code=code,
        message=message,
        severity=OfflineEvidenceSeverity.WARNING,
        detail=detail,
    )


__all__ = [
    "OFFLINE_EVIDENCE_KIND",
    "OFFLINE_EVIDENCE_RELATIVE_PATH",
    "OFFLINE_EVIDENCE_SCHEMA_VERSION",
    "OfflineArtifactEvidence",
    "OfflineEvidenceDiagnostic",
    "OfflineEvidenceError",
    "OfflineEvidenceFileRef",
    "OfflineEvidenceManifest",
    "OfflineEvidenceManifestStatus",
    "OfflineEvidenceSeverity",
    "OfflineStageEvidence",
    "collect_offline_evidence_manifest",
    "offline_evidence_manifest_path",
    "read_offline_evidence_manifest",
    "write_offline_evidence_manifest",
]
