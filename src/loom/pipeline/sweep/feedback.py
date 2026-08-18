"""Feedback and observation records for sweep trials."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from loom._validation import require_schema_version
from loom.serialization import (
    PlainData,
    PlainDataError,
    freeze_plain_data,
    thaw_plain_data,
)

from .errors import SweepProtocolError


class SweepFeedbackStatus(StrEnum):
    """Canonical result semantics for trial feedback."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


SWEEP_FEEDBACK_SCHEMA_VERSION = 1


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
        raise SweepProtocolError(
            f"{object_name} payload has unknown field(s): {fields}"
        )


def _non_empty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SweepProtocolError(f"{field_name} must be a string when set")
    if not value:
        raise SweepProtocolError(f"{field_name} must be a non-empty string when set")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SweepProtocolError(f"{field_name} must be a non-negative integer")
    return value


def _plain_mapping(value: object, field_name: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    try:
        normalized = freeze_plain_data(value, path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(f"{field_name} must contain plain data") from exc
    if not isinstance(normalized, Mapping):
        raise SweepProtocolError(f"{field_name} must be a mapping")
    return normalized


def _plain_value(value: object, field_name: str) -> PlainData:
    try:
        return freeze_plain_data(value, path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepProtocolError(f"{field_name} must be plain data") from exc


def _to_observations(
    values: Sequence[object], field_name: str
) -> tuple["SweepFeedbackObservation", ...]:
    observations: list[SweepFeedbackObservation] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepFeedbackObservation):
            observations.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepProtocolError(
                f"{field_name}[{index}] must be a mapping or SweepFeedbackObservation"
            )
        observations.append(SweepFeedbackObservation.from_dict(value))
    return tuple(observations)


@dataclass(frozen=True, slots=True)
class SweepFeedbackObservation:
    """Generic observation point for a sweep trial."""

    key: str
    value: PlainData
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _non_empty_text(self.key, "key"))
        object.__setattr__(self, "value", _plain_value(self.value, "value"))
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "key": self.key,
            "value": thaw_plain_data(self.value, path="value"),
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepFeedbackObservation":
        if not isinstance(data, Mapping):
            raise SweepProtocolError(
                "SweepFeedbackObservation payload must be a mapping"
            )
        _reject_unknown(
            data,
            {"key", "value", "metadata"},
            object_name="SweepFeedbackObservation",
        )
        return cls(
            key=_non_empty_text(_required(data, "key"), "key"),
            value=_plain_value(_required(data, "value"), "value"),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


@dataclass(frozen=True, slots=True)
class SweepTrialFeedbackRecord:
    """Outcome and observation record for one sweep trial."""

    sweep_id: str
    trial_id: str
    trial_index: int
    status: SweepFeedbackStatus
    observed_at: str
    schema_version: int = SWEEP_FEEDBACK_SCHEMA_VERSION
    run_uri: str | None = None
    provider_trial_id: str | None = None
    reason: str | None = None
    artifact_refs: Mapping[str, PlainData] = field(default_factory=dict)
    observations: tuple[SweepFeedbackObservation, ...] = ()
    metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_schema_version(
            self.schema_version,
            current=SWEEP_FEEDBACK_SCHEMA_VERSION,
            error_type=SweepProtocolError,
        )
        object.__setattr__(self, "sweep_id", _non_empty_text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "trial_id", _non_empty_text(self.trial_id, "trial_id"))
        object.__setattr__(
            self,
            "trial_index",
            _non_negative_int(self.trial_index, "trial_index"),
        )
        object.__setattr__(
            self,
            "status",
            SweepFeedbackStatus(self.status),
        )
        object.__setattr__(
            self, "observed_at", _non_empty_text(self.observed_at, "observed_at")
        )
        object.__setattr__(self, "run_uri", _optional_text(self.run_uri, "run_uri"))
        object.__setattr__(
            self,
            "provider_trial_id",
            _optional_text(self.provider_trial_id, "provider_trial_id"),
        )
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason"))
        object.__setattr__(
            self,
            "artifact_refs",
            _plain_mapping(self.artifact_refs, "artifact_refs"),
        )
        object.__setattr__(
            self,
            "observations",
            _to_observations(self.observations, "observations"),
        )
        object.__setattr__(self, "metadata", _plain_mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "sweep_id": self.sweep_id,
            "trial_id": self.trial_id,
            "trial_index": self.trial_index,
            "status": self.status.value,
            "observed_at": self.observed_at,
            "run_uri": self.run_uri,
            "provider_trial_id": self.provider_trial_id,
            "reason": self.reason,
            "artifact_refs": thaw_plain_data(self.artifact_refs, path="artifact_refs"),
            "observations": [
                observation.to_dict() for observation in self.observations
            ],
            "metadata": thaw_plain_data(self.metadata, path="metadata"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepTrialFeedbackRecord":
        if not isinstance(data, Mapping):
            raise SweepProtocolError(
                "SweepTrialFeedbackRecord payload must be a mapping"
            )
        _reject_unknown(
            data,
            {
                "schema_version",
                "sweep_id",
                "trial_id",
                "trial_index",
                "status",
                "observed_at",
                "run_uri",
                "provider_trial_id",
                "reason",
                "artifact_refs",
                "observations",
                "metadata",
            },
            object_name="SweepTrialFeedbackRecord",
        )
        status = _required(data, "status")
        return cls(
            schema_version=_non_negative_int(
                _required(data, "schema_version"), "schema_version"
            ),
            sweep_id=_non_empty_text(_required(data, "sweep_id"), "sweep_id"),
            trial_id=_non_empty_text(_required(data, "trial_id"), "trial_id"),
            trial_index=_non_negative_int(
                _required(data, "trial_index"), "trial_index"
            ),
            status=_feedback_status(status, "status"),
            observed_at=_non_empty_text(_required(data, "observed_at"), "observed_at"),
            run_uri=_optional_text(data.get("run_uri"), "run_uri"),
            provider_trial_id=_optional_text(
                data.get("provider_trial_id"), "provider_trial_id"
            ),
            reason=_optional_text(data.get("reason"), "reason"),
            artifact_refs=_plain_mapping(
                data.get("artifact_refs", {}), "artifact_refs"
            ),
            observations=_to_observations(
                list(data.get("observations", ())), "observations"
            ),
            metadata=_plain_mapping(data.get("metadata", {}), "metadata"),
        )


def _feedback_status(value: object, field_name: str) -> SweepFeedbackStatus:
    if isinstance(value, SweepFeedbackStatus):
        return value
    if not isinstance(value, str):
        raise SweepProtocolError(f"{field_name} must be a SweepFeedbackStatus")
    try:
        return SweepFeedbackStatus(value)
    except ValueError as exc:
        raise SweepProtocolError(
            f"{field_name} must be a valid SweepFeedbackStatus"
        ) from exc


def _normalize_feedback_records(
    values: Sequence[object], *, field: str
) -> tuple[SweepTrialFeedbackRecord, ...]:
    normalized: list[SweepTrialFeedbackRecord] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepTrialFeedbackRecord):
            normalized.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepProtocolError(
                f"{field}[{index}] must be a mapping or SweepTrialFeedbackRecord"
            )
        normalized.append(SweepTrialFeedbackRecord.from_dict(value))
    return tuple(normalized)


__all__ = [
    "SWEEP_FEEDBACK_SCHEMA_VERSION",
    "SweepFeedbackObservation",
    "SweepFeedbackStatus",
    "SweepTrialFeedbackRecord",
]
