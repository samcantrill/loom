"""Metadata-first sweep collection records and helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loom.serialization import PlainData, PlainDataError, ensure_plain_data
from loom.timestamps import utc_timestamp

from .errors import SweepProtocolError
from .extraction import (
    SweepExtractionRequest,
    SweepExtractionResult,
    unsupported_extraction,
)
from .status import SweepTrialOutcome, SweepTrialStatus, build_sweep_status

if TYPE_CHECKING:
    from .runner import SweepPlan
    from .trials import SweepTrialRecord


SWEEP_COLLECTION_SCHEMA_VERSION = 1

RunStatusReader = Callable[[str], object | None]
ArtifactReader = Callable[[str], Mapping[str, object] | None]


def _required(mapping: Mapping[str, object], field_name: str) -> object:
    if field_name not in mapping:
        raise SweepProtocolError(f"missing required field {field_name!r}")
    return mapping[field_name]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], *, object_name: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SweepProtocolError(f"{object_name} payload has unknown field(s): {fields}")


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


def _non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SweepProtocolError(f"{field_name} must be a non-negative integer")
    return value


def _schema_version(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SweepProtocolError(f"{field_name} must be a positive integer")
    return value


def _plain_mapping(value: object, field_name: str) -> dict[str, PlainData]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    try:
        normalized = ensure_plain_data(value, path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(f"{field_name} must contain plain data") from exc
    if not isinstance(normalized, dict):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    return dict(normalized)


@dataclass(frozen=True, slots=True)
class SweepCollectionDiagnostic:
    """Machine-readable collection diagnostic."""

    code: str
    message: str
    trial_id: str | None = None
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _text(self.code, "code"))
        object.__setattr__(self, "message", _text(self.message, "message"))
        object.__setattr__(self, "trial_id", _optional_text(self.trial_id, "trial_id"))
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "trial_id": self.trial_id,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepCollectionDiagnostic":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepCollectionDiagnostic payload must be a mapping")
        _reject_unknown(
            data,
            {"code", "message", "trial_id", "detail"},
            object_name="SweepCollectionDiagnostic",
        )
        return cls(
            code=_text(_required(data, "code"), "code"),
            message=_text(_required(data, "message"), "message"),
            trial_id=_optional_text(data.get("trial_id"), "trial_id"),
            detail=_plain_mapping(data.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class SweepCollectedArtifact:
    """Collected artifact reference metadata for one trial."""

    key: str
    artifact_id: str
    uri: str
    artifact_type: str
    codec_key: str | None = None
    checksum: str | None = None
    fingerprint: str | None = None
    producer_stage: str | None = None
    created_at: str | None = None
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _text(self.key, "key"))
        object.__setattr__(self, "artifact_id", _text(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "uri", _text(self.uri, "uri"))
        object.__setattr__(
            self, "artifact_type", _text(self.artifact_type, "artifact_type")
        )
        object.__setattr__(self, "codec_key", _optional_text(self.codec_key, "codec_key"))
        object.__setattr__(self, "checksum", _optional_text(self.checksum, "checksum"))
        object.__setattr__(
            self, "fingerprint", _optional_text(self.fingerprint, "fingerprint")
        )
        object.__setattr__(
            self,
            "producer_stage",
            _optional_text(self.producer_stage, "producer_stage"),
        )
        object.__setattr__(
            self, "created_at", _optional_text(self.created_at, "created_at")
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "key": self.key,
            "artifact_id": self.artifact_id,
            "uri": self.uri,
            "artifact_type": self.artifact_type,
            "codec_key": self.codec_key,
            "checksum": self.checksum,
            "fingerprint": self.fingerprint,
            "producer_stage": self.producer_stage,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepCollectedArtifact":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepCollectedArtifact payload must be a mapping")
        _reject_unknown(
            data,
            {
                "key",
                "artifact_id",
                "uri",
                "artifact_type",
                "codec_key",
                "checksum",
                "fingerprint",
                "producer_stage",
                "created_at",
                "metadata",
            },
            object_name="SweepCollectedArtifact",
        )
        return cls(
            key=_text(_required(data, "key"), "key"),
            artifact_id=_text(_required(data, "artifact_id"), "artifact_id"),
            uri=_text(_required(data, "uri"), "uri"),
            artifact_type=_text(_required(data, "artifact_type"), "artifact_type"),
            codec_key=_optional_text(data.get("codec_key"), "codec_key"),
            checksum=_optional_text(data.get("checksum"), "checksum"),
            fingerprint=_optional_text(data.get("fingerprint"), "fingerprint"),
            producer_stage=_optional_text(
                data.get("producer_stage"), "producer_stage"
            ),
            created_at=_optional_text(data.get("created_at"), "created_at"),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class SweepCollectedTrial:
    """Collection record for one planned sweep trial."""

    sweep_id: str
    trial_id: str
    trial_index: int
    status: SweepTrialStatus
    run_uri: str | None = None
    provider_trial_id: str | None = None
    proposal_overrides: Mapping[str, PlainData] = field(default_factory=dict)
    trial_metadata: Mapping[str, PlainData] = field(default_factory=dict)
    artifacts: Sequence[SweepCollectedArtifact] = ()
    extraction_result: SweepExtractionResult | None = None
    diagnostics: Sequence[SweepCollectionDiagnostic] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sweep_id", _text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "trial_id", _text(self.trial_id, "trial_id"))
        object.__setattr__(
            self, "trial_index", _non_negative_int(self.trial_index, "trial_index")
        )
        if not isinstance(self.status, SweepTrialStatus):
            raise SweepProtocolError("status must be a SweepTrialStatus")
        object.__setattr__(self, "run_uri", _optional_text(self.run_uri, "run_uri"))
        object.__setattr__(
            self,
            "provider_trial_id",
            _optional_text(self.provider_trial_id, "provider_trial_id"),
        )
        object.__setattr__(
            self,
            "proposal_overrides",
            _plain_mapping(self.proposal_overrides, "proposal_overrides"),
        )
        object.__setattr__(
            self,
            "trial_metadata",
            _plain_mapping(self.trial_metadata, "trial_metadata"),
        )
        object.__setattr__(
            self,
            "artifacts",
            _collected_artifacts(self.artifacts, "artifacts"),
        )
        if self.extraction_result is not None and not isinstance(
            self.extraction_result, SweepExtractionResult
        ):
            raise SweepProtocolError(
                "extraction_result must be SweepExtractionResult when set"
            )
        object.__setattr__(
            self,
            "diagnostics",
            _collection_diagnostics(self.diagnostics, "diagnostics"),
        )

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "sweep_id": self.sweep_id,
            "trial_id": self.trial_id,
            "trial_index": self.trial_index,
            "run_uri": self.run_uri,
            "provider_trial_id": self.provider_trial_id,
            "proposal_overrides": dict(self.proposal_overrides),
            "trial_metadata": dict(self.trial_metadata),
            "status": self.status.to_dict(),
            "artifact_count": self.artifact_count,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "extraction_result": None
            if self.extraction_result is None
            else self.extraction_result.to_dict(),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepCollectedTrial":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepCollectedTrial payload must be a mapping")
        _reject_unknown(
            data,
            {
                "sweep_id",
                "trial_id",
                "trial_index",
                "run_uri",
                "provider_trial_id",
                "proposal_overrides",
                "trial_metadata",
                "status",
                "artifact_count",
                "artifacts",
                "extraction_result",
                "diagnostics",
            },
            object_name="SweepCollectedTrial",
        )
        status_data = _required(data, "status")
        if not isinstance(status_data, Mapping):
            raise SweepProtocolError("status must be a mapping")
        extraction_data = data.get("extraction_result")
        if extraction_data is not None and not isinstance(extraction_data, Mapping):
            raise SweepProtocolError("extraction_result must be a mapping when set")
        return cls(
            sweep_id=_text(_required(data, "sweep_id"), "sweep_id"),
            trial_id=_text(_required(data, "trial_id"), "trial_id"),
            trial_index=_non_negative_int(
                _required(data, "trial_index"), "trial_index"
            ),
            run_uri=_optional_text(data.get("run_uri"), "run_uri"),
            provider_trial_id=_optional_text(
                data.get("provider_trial_id"), "provider_trial_id"
            ),
            proposal_overrides=_plain_mapping(
                data.get("proposal_overrides", {}), "proposal_overrides"
            ),
            trial_metadata=_plain_mapping(
                data.get("trial_metadata", {}), "trial_metadata"
            ),
            status=SweepTrialStatus(
                sweep_id=_text(_required(status_data, "sweep_id"), "status.sweep_id"),
                trial_id=_text(_required(status_data, "trial_id"), "status.trial_id"),
                trial_index=_non_negative_int(
                    _required(status_data, "trial_index"), "status.trial_index"
                ),
                outcome=SweepTrialOutcome(
                    _text(_required(status_data, "outcome"), "status.outcome")
                ),
                run_uri=_optional_text(status_data.get("run_uri"), "status.run_uri"),
                run_status=_optional_text(
                    status_data.get("run_status"), "status.run_status"
                ),
                queue_item_id=_optional_text(
                    status_data.get("queue_item_id"), "status.queue_item_id"
                ),
                queue_status=_optional_text(
                    status_data.get("queue_status"), "status.queue_status"
                ),
                coordination_state=_optional_text(
                    status_data.get("coordination_state"),
                    "status.coordination_state",
                ),
                early_stopped=bool(status_data.get("early_stopped", False)),
                metadata=_plain_mapping(status_data.get("metadata", {}), "status.metadata"),
            ),
            artifacts=_collected_artifacts(
                list(data.get("artifacts", ())), "artifacts"
            ),
            extraction_result=SweepExtractionResult.from_dict(extraction_data)
            if extraction_data is not None
            else None,
            diagnostics=_collection_diagnostics(
                list(data.get("diagnostics", ())), "diagnostics"
            ),
        )


@dataclass(frozen=True, slots=True)
class SweepCollectionResult:
    """Metadata-first collection result for a finite sweep."""

    sweep_id: str
    collected_at: str
    trials: Sequence[SweepCollectedTrial]
    schema_version: int = SWEEP_COLLECTION_SCHEMA_VERSION
    diagnostics: Sequence[SweepCollectionDiagnostic] = ()

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_COLLECTION_SCHEMA_VERSION:
            raise SweepProtocolError("SweepCollectionResult.schema_version must be 1")
        object.__setattr__(self, "sweep_id", _text(self.sweep_id, "sweep_id"))
        object.__setattr__(
            self, "collected_at", _text(self.collected_at, "collected_at")
        )
        object.__setattr__(self, "trials", _collected_trials(self.trials, "trials"))
        object.__setattr__(
            self,
            "diagnostics",
            _collection_diagnostics(self.diagnostics, "diagnostics"),
        )

    @property
    def trial_count(self) -> int:
        return len(self.trials)

    @property
    def artifact_count(self) -> int:
        return sum(trial.artifact_count for trial in self.trials)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "sweep_id": self.sweep_id,
            "collected_at": self.collected_at,
            "trial_count": self.trial_count,
            "artifact_count": self.artifact_count,
            "trials": [trial.to_dict() for trial in self.trials],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepCollectionResult":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepCollectionResult payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "sweep_id",
                "collected_at",
                "trial_count",
                "artifact_count",
                "trials",
                "diagnostics",
            },
            object_name="SweepCollectionResult",
        )
        return cls(
            schema_version=_schema_version(
                _required(data, "schema_version"), "schema_version"
            ),
            sweep_id=_text(_required(data, "sweep_id"), "sweep_id"),
            collected_at=_text(_required(data, "collected_at"), "collected_at"),
            trials=_collected_trials(list(data.get("trials", ())), "trials"),
            diagnostics=_collection_diagnostics(
                list(data.get("diagnostics", ())), "diagnostics"
            ),
        )


def collect_sweep_results(
    plan: "SweepPlan",
    *,
    run_statuses: Mapping[str, object] | None = None,
    run_status_reader: RunStatusReader | None = None,
    artifact_reader: ArtifactReader | None = None,
    queue_items: Sequence[object] = (),
    coordination_trials: Sequence[object] = (),
    include_unsupported_extraction: bool = False,
    collected_at: str | None = None,
) -> SweepCollectionResult:
    """Collect trial metadata, statuses, and artifact refs without payloads."""

    timestamp = collected_at or utc_timestamp()
    status_summary = build_sweep_status(
        plan,
        run_statuses=run_statuses,
        run_status_reader=run_status_reader,
        queue_items=queue_items,
        coordination_trials=coordination_trials,
    )
    status_by_trial_id = {status.trial_id: status for status in status_summary.trials}
    collected_trials: list[SweepCollectedTrial] = []
    diagnostics: list[SweepCollectionDiagnostic] = []

    for trial in plan.trials:
        trial_diagnostics: list[SweepCollectionDiagnostic] = []
        artifacts = _read_trial_artifacts(
            trial,
            artifact_reader=artifact_reader,
            diagnostics=trial_diagnostics,
        )
        extraction_result = (
            _unsupported_extraction_for_trial(trial, requested_at=timestamp)
            if include_unsupported_extraction
            else None
        )
        diagnostics.extend(trial_diagnostics)
        collected_trials.append(
            SweepCollectedTrial(
                sweep_id=trial.sweep_id,
                trial_id=trial.trial_id,
                trial_index=trial.trial_index,
                run_uri=trial.run_uri,
                provider_trial_id=trial.provider_trial_id,
                proposal_overrides=trial.proposal_overrides,
                trial_metadata=trial.metadata,
                status=status_by_trial_id[trial.trial_id],
                artifacts=artifacts,
                extraction_result=extraction_result,
                diagnostics=tuple(trial_diagnostics),
            )
        )

    return SweepCollectionResult(
        sweep_id=plan.sweep_id,
        collected_at=timestamp,
        trials=tuple(collected_trials),
        diagnostics=tuple(diagnostics),
    )


def _read_trial_artifacts(
    trial: "SweepTrialRecord",
    *,
    artifact_reader: ArtifactReader | None,
    diagnostics: list[SweepCollectionDiagnostic],
) -> tuple[SweepCollectedArtifact, ...]:
    if artifact_reader is None:
        return ()
    if trial.run_uri is None:
        diagnostics.append(
            SweepCollectionDiagnostic(
                code="missing_run_uri",
                message="trial has no run URI for artifact collection",
                trial_id=trial.trial_id,
            )
        )
        return ()
    try:
        raw_artifacts = artifact_reader(trial.run_uri)
    except Exception as exc:  # noqa: BLE001 - collection reports per-trial diagnostics.
        diagnostics.append(
            SweepCollectionDiagnostic(
                code="artifact_collection_failed",
                message=str(exc) or type(exc).__name__,
                trial_id=trial.trial_id,
                detail={"exception_type": f"{type(exc).__module__}.{type(exc).__name__}"},
            )
        )
        return ()
    if raw_artifacts is None:
        return ()
    try:
        return _artifacts_from_mapping(raw_artifacts)
    except SweepProtocolError as exc:
        diagnostics.append(
            SweepCollectionDiagnostic(
                code="artifact_collection_malformed",
                message=str(exc),
                trial_id=trial.trial_id,
            )
        )
        return ()


def _unsupported_extraction_for_trial(
    trial: "SweepTrialRecord", *, requested_at: str
) -> SweepExtractionResult:
    return unsupported_extraction(
        SweepExtractionRequest(
            sweep_id=trial.sweep_id,
            trial_id=trial.trial_id,
            trial_index=trial.trial_index,
            requested_at=requested_at,
            run_uri=trial.run_uri,
            request_metadata={"source": "sweep_collection"},
        ),
        detail={"reason": "no extraction adapter configured"},
    )


def _artifacts_from_mapping(
    artifacts: Mapping[str, object],
) -> tuple[SweepCollectedArtifact, ...]:
    collected: list[SweepCollectedArtifact] = []
    for key in sorted(artifacts, key=str):
        collected.append(_artifact_from_object(key, artifacts[key]))
    return tuple(collected)


def _artifact_from_object(key: object, artifact: object) -> SweepCollectedArtifact:
    artifact_key = _text(key, "artifact key")
    payload = _artifact_payload(artifact)
    return SweepCollectedArtifact(
        key=artifact_key,
        artifact_id=_text(_required(payload, "artifact_id"), "artifact_id"),
        uri=_text(_required(payload, "uri"), "uri"),
        artifact_type=_text(_required(payload, "artifact_type"), "artifact_type"),
        codec_key=_optional_text(payload.get("codec_key"), "codec_key"),
        checksum=_optional_text(payload.get("checksum"), "checksum"),
        fingerprint=_optional_text(payload.get("fingerprint"), "fingerprint"),
        producer_stage=_optional_text(payload.get("producer_stage"), "producer_stage"),
        created_at=_optional_text(payload.get("created_at"), "created_at"),
        metadata=_plain_mapping(payload.get("metadata", {}), "metadata"),
    )


def _artifact_payload(artifact: object) -> dict[str, PlainData]:
    raw: object
    to_dict = getattr(artifact, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
    else:
        raw = artifact
    try:
        payload = ensure_plain_data(raw, path="artifact")
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError("artifact payload must contain plain data") from exc
    if not isinstance(payload, dict):
        raise SweepProtocolError("artifact payload must be a mapping")
    return dict(payload)


def _collected_artifacts(
    values: Sequence[object], field_name: str
) -> tuple[SweepCollectedArtifact, ...]:
    normalized: list[SweepCollectedArtifact] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepCollectedArtifact):
            normalized.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepProtocolError(
                f"{field_name}[{index}] must be a mapping or SweepCollectedArtifact"
            )
        normalized.append(SweepCollectedArtifact.from_dict(value))
    return tuple(normalized)


def _collection_diagnostics(
    values: Sequence[object], field_name: str
) -> tuple[SweepCollectionDiagnostic, ...]:
    normalized: list[SweepCollectionDiagnostic] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepCollectionDiagnostic):
            normalized.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepProtocolError(
                f"{field_name}[{index}] must be a mapping or SweepCollectionDiagnostic"
            )
        normalized.append(SweepCollectionDiagnostic.from_dict(value))
    return tuple(normalized)


def _collected_trials(
    values: Sequence[object], field_name: str
) -> tuple[SweepCollectedTrial, ...]:
    normalized: list[SweepCollectedTrial] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepCollectedTrial):
            normalized.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepProtocolError(
                f"{field_name}[{index}] must be a mapping or SweepCollectedTrial"
            )
        normalized.append(SweepCollectedTrial.from_dict(value))
    return tuple(normalized)


__all__ = [
    "SWEEP_COLLECTION_SCHEMA_VERSION",
    "ArtifactReader",
    "RunStatusReader",
    "SweepCollectedArtifact",
    "SweepCollectedTrial",
    "SweepCollectionDiagnostic",
    "SweepCollectionResult",
    "collect_sweep_results",
]
