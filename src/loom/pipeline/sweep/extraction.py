"""Extraction contracts for sweep trials and unsupported adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from loom.serialization import PlainData, PlainDataError, ensure_plain_data

from .errors import SweepExtractionError


class SweepExtractionStatus(StrEnum):
    """Extraction result status for a sweep trial."""

    UNSUPPORTED = "unsupported"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"


SWEEP_EXTRACTION_SCHEMA_VERSION = 1


def _required(mapping: Mapping[str, object], field_name: str) -> object:
    if field_name not in mapping:
        raise SweepExtractionError(f"missing required field {field_name!r}")
    return mapping[field_name]


def _reject_unknown(mapping: Mapping[str, object], allowed: set[str], *, object_name: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise SweepExtractionError(
            f"{object_name} payload has unknown field(s): {fields}"
        )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SweepExtractionError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SweepExtractionError(f"{field_name} must be a string when set")
    if not value:
        raise SweepExtractionError(f"{field_name} must be a non-empty string when set")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SweepExtractionError(f"{field_name} must be a non-negative integer")
    return value


def _schema_version(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SweepExtractionError(f"{field_name} must be an integer")
    if value <= 0:
        raise SweepExtractionError(f"{field_name} must be a positive integer")
    return value


def _plain_mapping(value: object, field_name: str) -> dict[str, PlainData]:
    if not isinstance(value, Mapping):
        raise SweepExtractionError(f"{field_name} must be a mapping")
    try:
        normalized = ensure_plain_data(value, path=field_name)
    except (PlainDataError, TypeError) as exc:
        raise SweepExtractionError(f"{field_name} must contain plain data") from exc
    if not isinstance(normalized, dict):
        raise SweepExtractionError(f"{field_name} must be a mapping")
    return dict(normalized)


def _to_diagnostics(values: Sequence[object], field: str) -> tuple["SweepExtractionDiagnostic", ...]:
    diagnostics: list[SweepExtractionDiagnostic] = []
    for index, value in enumerate(values):
        if isinstance(value, SweepExtractionDiagnostic):
            diagnostics.append(value)
            continue
        if not isinstance(value, Mapping):
            raise SweepExtractionError(
                f"{field}[{index}] must be a mapping or SweepExtractionDiagnostic"
            )
        diagnostics.append(SweepExtractionDiagnostic.from_dict(value))
    return tuple(diagnostics)


def _coerce_status(value: object, field_name: str) -> SweepExtractionStatus:
    if isinstance(value, SweepExtractionStatus):
        return value
    if not isinstance(value, str):
        raise SweepExtractionError(f"{field_name} must be a SweepExtractionStatus")
    try:
        return SweepExtractionStatus(value)
    except ValueError as exc:
        raise SweepExtractionError(
            f"{field_name} must be a valid SweepExtractionStatus"
        ) from exc


@dataclass(frozen=True, slots=True)
class SweepExtractionRequest:
    """Extraction request facts for one trial."""

    sweep_id: str
    trial_id: str
    trial_index: int
    requested_at: str
    schema_version: int = SWEEP_EXTRACTION_SCHEMA_VERSION
    run_uri: str | None = None
    request_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_EXTRACTION_SCHEMA_VERSION:
            raise SweepExtractionError("SweepExtractionRequest.schema_version must be 1")
        object.__setattr__(self, "sweep_id", _required_text(self.sweep_id, "sweep_id"))
        object.__setattr__(self, "trial_id", _required_text(self.trial_id, "trial_id"))
        object.__setattr__(
            self,
            "trial_index",
            _non_negative_int(self.trial_index, "trial_index"),
        )
        object.__setattr__(
            self, "requested_at", _required_text(self.requested_at, "requested_at")
        )
        object.__setattr__(self, "run_uri", _optional_text(self.run_uri, "run_uri"))
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
            "request_metadata": dict(self.request_metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepExtractionRequest":
        if not isinstance(data, Mapping):
            raise SweepExtractionError("SweepExtractionRequest payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "sweep_id",
                "trial_id",
                "trial_index",
                "requested_at",
                "run_uri",
                "request_metadata",
            },
            object_name="SweepExtractionRequest",
        )
        return cls(
            schema_version=_schema_version(
                _required(data, "schema_version"), "schema_version"
            ),
            sweep_id=_required_text(_required(data, "sweep_id"), "sweep_id"),
            trial_id=_required_text(_required(data, "trial_id"), "trial_id"),
            trial_index=_non_negative_int(
                _required(data, "trial_index"), "trial_index"
            ),
            requested_at=_required_text(_required(data, "requested_at"), "requested_at"),
            run_uri=_optional_text(data.get("run_uri"), "run_uri"),
            request_metadata=_plain_mapping(data.get("request_metadata", {}), "request_metadata"),
        )


@dataclass(frozen=True, slots=True)
class SweepExtractionDiagnostic:
    """Machine-readable extraction diagnostic."""

    code: str
    message: str
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "code"))
        object.__setattr__(self, "message", _required_text(self.message, "message"))
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepExtractionDiagnostic":
        if not isinstance(data, Mapping):
            raise SweepExtractionError("SweepExtractionDiagnostic payload must be a mapping")
        _reject_unknown(
            data,
            {"code", "message", "detail"},
            object_name="SweepExtractionDiagnostic",
        )
        return cls(
            code=_required_text(_required(data, "code"), "code"),
            message=_required_text(_required(data, "message"), "message"),
            detail=_plain_mapping(data.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class SweepExtractionResult:
    """Extraction outcome record for one sweep trial."""

    request: SweepExtractionRequest
    status: SweepExtractionStatus
    schema_version: int = SWEEP_EXTRACTION_SCHEMA_VERSION
    extracted_payload: Mapping[str, PlainData] | None = None
    diagnostics: tuple[SweepExtractionDiagnostic, ...] = ()
    extraction_metadata: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SWEEP_EXTRACTION_SCHEMA_VERSION:
            raise SweepExtractionError("SweepExtractionResult.schema_version must be 1")
        if not isinstance(self.request, SweepExtractionRequest):
            raise SweepExtractionError("request must be a SweepExtractionRequest")
        object.__setattr__(
            self,
            "status",
            SweepExtractionStatus(self.status),
        )
        if self.extracted_payload is not None:
            object.__setattr__(
                self,
                "extracted_payload",
                _plain_mapping(self.extracted_payload, "extracted_payload"),
            )
        object.__setattr__(
            self,
            "diagnostics",
            _to_diagnostics(self.diagnostics, "diagnostics"),
        )
        object.__setattr__(
            self,
            "extraction_metadata",
            _plain_mapping(self.extraction_metadata, "extraction_metadata"),
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
            "extracted_payload": (
                None
                if self.extracted_payload is None
                else dict(self.extracted_payload)
            ),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "extraction_metadata": dict(self.extraction_metadata),
        }

    @classmethod
    def from_dict(cls, data: object) -> "SweepExtractionResult":
        if not isinstance(data, Mapping):
            raise SweepExtractionError("SweepExtractionResult payload must be a mapping")
        _reject_unknown(
            data,
            {
                "schema_version",
                "request",
                "status",
                "extracted_payload",
                "diagnostics",
                "extraction_metadata",
            },
            object_name="SweepExtractionResult",
        )
        request = data.get("request")
        if not isinstance(request, Mapping):
            raise SweepExtractionError("request must be a mapping")
        status = _required(data, "status")
        return cls(
            schema_version=_schema_version(
                _required(data, "schema_version"), "schema_version"
            ),
            request=SweepExtractionRequest.from_dict(request),
            status=_coerce_status(status, "status"),
            extracted_payload=_plain_mapping(
                data.get("extracted_payload", {}),
                "extracted_payload",
            )
            if data.get("extracted_payload") is not None
            else None,
            diagnostics=_to_diagnostics(
                list(data.get("diagnostics", ())), "diagnostics"
            ),
            extraction_metadata=_plain_mapping(
                data.get("extraction_metadata", {}), "extraction_metadata"
            ),
        )


def unsupported_extraction(
    request: SweepExtractionRequest,
    *,
    message: str = "extraction is not implemented",
    detail: Mapping[str, PlainData] | None = None,
) -> SweepExtractionResult:
    """Create an explicit unsupported-result record."""

    return SweepExtractionResult(
        request=request,
        status=SweepExtractionStatus.UNSUPPORTED,
        diagnostics=(
            SweepExtractionDiagnostic(
                code="unsupported_extraction",
                message=message,
                detail=_plain_mapping(detail or {}, "detail"),
            ),
        ),
    )


__all__ = [
    "SWEEP_EXTRACTION_SCHEMA_VERSION",
    "SweepExtractionDiagnostic",
    "SweepExtractionRequest",
    "SweepExtractionResult",
    "SweepExtractionStatus",
    "unsupported_extraction",
]
