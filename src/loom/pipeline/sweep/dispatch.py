"""Adapter-neutral dispatch intent and dispatch outcome records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from loom.serialization import PlainData, PlainDataError, ensure_plain_data

from .errors import SweepProtocolError


class SweepDispatchStatus(StrEnum):
    """Lifecycle outcomes for a dispatch attempt."""

    PLANNED = "planned"
    ACCEPTED = "accepted"
    QUEUED = "queued"
    SUBMITTED = "submitted"
    DISPATCHED = "dispatched"
    REJECTED = "rejected"
    FAILED = "failed"


SWEEP_DISPATCH_SCHEMA_VERSION = 1


def _required(mapping: Mapping[str, object], field_name: str) -> object:
    if field_name not in mapping:
        raise SweepProtocolError(f"missing required field {field_name!r}")
    return mapping[field_name]


def _reject_unknown(mapping: Mapping[str, object], allowed: set[str], *, object_name: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SweepProtocolError(
            f"{object_name} payload has unknown field(s): {fields}"
        )


def _text(value: object, field_name: str) -> str:
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


def _plain_mapping(value: object, field_name: str) -> dict[str, PlainData]:
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
class SweepDispatchRequest:
    """Adapter-neutral planned sweep dispatch intent."""

    sweep_id: str
    trial_id: str
    trial_index: int
    requested_at: str
    schema_version: int = SWEEP_DISPATCH_SCHEMA_VERSION
    run_uri: str | None = None
    provider_trial_id: str | None = None
    request_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_DISPATCH_SCHEMA_VERSION:
            raise SweepProtocolError(
                "SweepDispatchRequest.schema_version must be 1"
            )
        object.__setattr__(self, "sweep_id", _text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "trial_id", _text(self.trial_id, "trial_id"))
        object.__setattr__(
            self,
            "trial_index",
            _non_negative_int(self.trial_index, "trial_index"),
        )
        object.__setattr__(
            self, "requested_at", _text(self.requested_at, "requested_at")
        )
        object.__setattr__(self, "run_uri", _optional_text(self.run_uri, "run_uri"))
        object.__setattr__(
            self,
            "provider_trial_id",
            _optional_text(self.provider_trial_id, "provider_trial_id"),
        )
        object.__setattr__(
            self,
            "request_metadata",
            _plain_mapping(self.request_metadata, "request_metadata"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "sweep_id": self.sweep_id,
            "trial_id": self.trial_id,
            "trial_index": self.trial_index,
            "requested_at": self.requested_at,
            "run_uri": self.run_uri,
            "provider_trial_id": self.provider_trial_id,
            "request_metadata": dict(self.request_metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepDispatchRequest":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepDispatchRequest payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "sweep_id",
                "trial_id",
                "trial_index",
                "requested_at",
                "run_uri",
                "provider_trial_id",
                "request_metadata",
            },
            object_name="SweepDispatchRequest",
        )
        return cls(
            schema_version=_non_negative_int(
                _required(data, "schema_version"), "schema_version"
            ),
            sweep_id=_text(_required(data, "sweep_id"), "sweep_id"),
            trial_id=_text(_required(data, "trial_id"), "trial_id"),
            trial_index=_non_negative_int(
                _required(data, "trial_index"), "trial_index"
            ),
            requested_at=_text(_required(data, "requested_at"), "requested_at"),
            run_uri=_optional_text(data.get("run_uri"), "run_uri"),
            provider_trial_id=_optional_text(
                data.get("provider_trial_id"),
                "provider_trial_id",
            ),
            request_metadata=_plain_mapping(
                data.get("request_metadata", {}), "request_metadata"
            ),
        )


@dataclass(frozen=True, slots=True)
class SweepDispatchResult:
    """Adapter-neutral sweep dispatch outcome."""

    request: SweepDispatchRequest
    status: SweepDispatchStatus
    schema_version: int = SWEEP_DISPATCH_SCHEMA_VERSION
    run_uri: str | None = None
    dispatched_at: str | None = None
    reason: str | None = None
    result_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_DISPATCH_SCHEMA_VERSION:
            raise SweepProtocolError(
                "SweepDispatchResult.schema_version must be 1"
            )
        if not isinstance(self.request, SweepDispatchRequest):
            raise SweepProtocolError("request must be a SweepDispatchRequest")
        object.__setattr__(
            self,
            "status",
            SweepDispatchStatus(self.status),
        )
        object.__setattr__(self, "run_uri", _optional_text(self.run_uri, "run_uri"))
        if self.dispatched_at is not None:
            object.__setattr__(
                self, "dispatched_at", _text(self.dispatched_at, "dispatched_at")
            )
        if self.reason is not None:
            object.__setattr__(self, "reason", _text(self.reason, "reason"))
        else:
            object.__setattr__(self, "reason", None)
        object.__setattr__(
            self,
            "result_metadata",
            _plain_mapping(self.result_metadata, "result_metadata"),
        )

    @property
    def sweep_id(self) -> str:
        return self.request.sweep_id

    @property
    def trial_id(self) -> str:
        return self.request.trial_id

    @property
    def trial_index(self) -> int:
        return self.request.trial_index

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "run_uri": self.run_uri,
            "dispatched_at": self.dispatched_at,
            "reason": self.reason,
            "result_metadata": dict(self.result_metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepDispatchResult":
        if not isinstance(data, Mapping):
            raise SweepProtocolError("SweepDispatchResult payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "request",
                "status",
                "run_uri",
                "dispatched_at",
                "reason",
                "result_metadata",
            },
            object_name="SweepDispatchResult",
        )
        request = data.get("request")
        if not isinstance(request, Mapping):
            raise SweepProtocolError("request must be a mapping")
        status = data.get("status")
        if status is None:
            raise SweepProtocolError("status is required")
        return cls(
            schema_version=_non_negative_int(
                _required(data, "schema_version"), "schema_version"
            ),
            request=SweepDispatchRequest.from_dict(request),
            status=cast_status(status, "status"),
            run_uri=_optional_text(data.get("run_uri"), "run_uri"),
            dispatched_at=_optional_text(data.get("dispatched_at"), "dispatched_at"),
            reason=_optional_text(data.get("reason"), "reason"),
            result_metadata=_plain_mapping(data.get("result_metadata", {}), "result_metadata"),
        )


def _normalize_results(values: Sequence[object], *, field: str) -> tuple[SweepDispatchResult, ...]:
    normalized: list[SweepDispatchResult] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepDispatchResult):
            normalized.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepProtocolError(f"{field}[{index}] must be a mapping or SweepDispatchResult")
        normalized.append(SweepDispatchResult.from_dict(value))
    return tuple(normalized)


def cast_status(value: object, field_name: str) -> SweepDispatchStatus:
    if isinstance(value, SweepDispatchStatus):
        return value
    if not isinstance(value, str):
        raise SweepProtocolError(f"{field_name} must be a SweepDispatchStatus")
    try:
        return SweepDispatchStatus(value)
    except ValueError as exc:
        raise SweepProtocolError(
            f"{field_name} must be a valid SweepDispatchStatus"
        ) from exc


__all__ = [
    "SWEEP_DISPATCH_SCHEMA_VERSION",
    "SweepDispatchRequest",
    "SweepDispatchResult",
    "SweepDispatchStatus",
]
