"""Shared operation and evidence value objects for payload movement and verification."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import PlainData, ensure_plain_data, freeze_plain_data, thaw_plain_data


class OperationValidationError(ValueError):
    """Raised for malformed operation/evidence records."""


class OperationStatus(StrEnum):
    """High-level operation outcome for one operation call."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    NOT_IMPLEMENTED = "not_implemented"
    UNKNOWN = "unknown"


class OperationSupport(StrEnum):
    """Adapter capability support summary for an operation."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    NOT_IMPLEMENTED = "not_implemented"


class OperationDiagnosticSeverity(StrEnum):
    """Diagnostic severity classification."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class OperationEvidenceStatus(StrEnum):
    """Evidence outcome summary for operation checks."""

    PROVEN = "proven"
    UNPROVEN = "unproven"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    NOT_IMPLEMENTED = "not_implemented"


@dataclass(frozen=True, slots=True)
class OperationAdapterIdentity:
    """Adapter identity used by operation and evidence records."""

    name: str
    kind: str
    version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(self, "kind", _require_non_empty(self.kind, "kind"))
        if self.version is not None:
            object.__setattr__(
                self,
                "version",
                _require_non_empty(self.version, "version"),
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "name": self.name,
            "kind": self.kind,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: object) -> "OperationAdapterIdentity":
        payload = _as_mapping(data, "OperationAdapterIdentity")
        _reject_unknown(
            payload,
            {"name", "kind", "version"},
            "OperationAdapterIdentity",
        )
        _require_fields(payload, {"name", "kind", "version"}, "OperationAdapterIdentity")
        return cls(
            name=cast(str, payload["name"]),
            kind=cast(str, payload["kind"]),
            version=cast(str | None, payload["version"]),
        )


@dataclass(frozen=True, slots=True)
class OperationDiagnostic:
    """Record for one operation diagnostic item."""

    code: str
    message: str
    severity: OperationDiagnosticSeverity = OperationDiagnosticSeverity.ERROR
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_non_empty(self.code, "code"))
        object.__setattr__(self, "message", _require_non_empty(self.message, "message"))
        object.__setattr__(self, "severity", _coerce_operation_diagnostic_severity(self.severity))
        object.__setattr__(
            self,
            "details",
            freeze_plain_data(_sanitize_details(self.details), path="details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        severity = cast(OperationDiagnosticSeverity, self.severity)
        return {
            "code": self.code,
            "message": self.message,
            "severity": severity.value,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "OperationDiagnostic":
        payload = _as_mapping(data, "OperationDiagnostic")
        _reject_unknown(
            payload,
            {"code", "message", "severity", "details"},
            "OperationDiagnostic",
        )
        _require_fields(payload, {"code", "message"}, "OperationDiagnostic")
        return cls(
            code=cast(str, payload["code"]),
            message=cast(str, payload["message"]),
            severity=cast(
                OperationDiagnosticSeverity,
                payload.get("severity", OperationDiagnosticSeverity.ERROR),
            ),
            details=cast(Mapping[str, PlainData], payload.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class OperationEvidenceCheck:
    """Evidence check item for operation outcomes."""

    name: str
    status: OperationEvidenceStatus | str
    message: str
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_non_empty(self.name, "name"))
        object.__setattr__(
            self,
            "status",
            _coerce_operation_evidence_status(self.status, "status"),
        )
        object.__setattr__(self, "message", _require_non_empty(self.message, "message"))
        object.__setattr__(
            self,
            "details",
            freeze_plain_data(_sanitize_details(self.details), path="details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        status = cast(OperationEvidenceStatus, self.status)
        return {
            "name": self.name,
            "status": status.value,
            "message": self.message,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "OperationEvidenceCheck":
        payload = _as_mapping(data, "OperationEvidenceCheck")
        _reject_unknown(
            payload,
            {"name", "status", "message", "details"},
            "OperationEvidenceCheck",
        )
        _require_fields(payload, {"name", "status", "message"}, "OperationEvidenceCheck")
        return cls(
            name=cast(str, payload["name"]),
            status=cast(OperationEvidenceStatus | str, payload["status"]),
            message=cast(str, payload["message"]),
            details=cast(Mapping[str, PlainData], payload.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class OperationEvidenceRecord:
    """Proof bundle for checks associated with one operation."""

    status: OperationEvidenceStatus | str
    checks: Sequence[OperationEvidenceCheck] = ()
    adapter: OperationAdapterIdentity | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _coerce_operation_evidence_status(self.status, "status"),
        )
        object.__setattr__(
            self,
            "checks",
            _coerce_operation_evidence_checks(self.checks, "checks"),
        )
        if self.adapter is not None and not isinstance(self.adapter, OperationAdapterIdentity):
            raise OperationValidationError("adapter must be an OperationAdapterIdentity or None")
        object.__setattr__(
            self,
            "details",
            freeze_plain_data(_sanitize_details(self.details), path="details"),
        )

    def to_dict(self) -> dict[str, PlainData]:
        status = cast(OperationEvidenceStatus, self.status)
        return {
            "status": status.value,
            "checks": [check.to_dict() for check in self.checks],
            "adapter": self.adapter.to_dict() if self.adapter is not None else None,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "OperationEvidenceRecord":
        payload = _as_mapping(data, "OperationEvidenceRecord")
        _reject_unknown(
            payload,
            {"status", "checks", "adapter", "details"},
            "OperationEvidenceRecord",
        )
        _require_fields(payload, {"status", "checks", "details"}, "OperationEvidenceRecord")
        checks = _coerce_operation_evidence_checks_from_dict(
            payload.get("checks", ()),
            "checks",
        )
        adapter_data = payload.get("adapter")
        adapter = (
            None
            if adapter_data is None
            else OperationAdapterIdentity.from_dict(adapter_data)
        )
        return cls(
            status=cast(OperationEvidenceStatus | str, payload["status"]),
            checks=checks,
            adapter=adapter,
            details=cast(Mapping[str, PlainData], payload.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class OperationSupportRecord:
    """Capability summary for a single operation."""

    operation: str
    support: OperationSupport | str
    message: str
    diagnostics: Sequence[OperationDiagnostic] = ()
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _require_non_empty(self.operation, "operation"))
        object.__setattr__(
            self,
            "support",
            _coerce_operation_support(self.support, "support"),
        )
        object.__setattr__(self, "message", _require_non_empty(self.message, "message"))
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_operation_diagnostics(self.diagnostics, "diagnostics"),
        )
        object.__setattr__(
            self,
            "details",
            freeze_plain_data(_sanitize_details(self.details), path="details"),
        )

    @classmethod
    def unsupported(
        cls,
        operation: str,
        *,
        message: str | None = None,
        diagnostics: Sequence[OperationDiagnostic] | None = None,
        details: Mapping[str, PlainData] | None = None,
    ) -> "OperationSupportRecord":
        wanted = _require_non_empty(operation, "operation")
        resolved_message = (
            message
            if message is not None
            else f"operation {wanted!r} is not supported"
        )
        resolved_diagnostics = (
            _coerce_operation_diagnostics(
                (
                    OperationDiagnostic(
                        code="operation.support.unsupported",
                        message=resolved_message,
                        severity=OperationDiagnosticSeverity.ERROR,
                        details={
                            "operation": wanted,
                            **(details or {}),
                        },
                    ),
                ),
                "diagnostics",
            )
            if diagnostics is None
            else diagnostics
        )
        return cls(
            operation=wanted,
            support=OperationSupport.UNSUPPORTED,
            message=resolved_message,
            diagnostics=resolved_diagnostics,
            details=details or {},
        )

    @classmethod
    def not_implemented(
        cls,
        operation: str,
        *,
        message: str | None = None,
        diagnostics: Sequence[OperationDiagnostic] | None = None,
        details: Mapping[str, PlainData] | None = None,
    ) -> "OperationSupportRecord":
        wanted = _require_non_empty(operation, "operation")
        resolved_message = (
            message
            if message is not None
            else f"operation {wanted!r} is not implemented"
        )
        resolved_diagnostics = (
            _coerce_operation_diagnostics(
                (
                    OperationDiagnostic(
                        code="operation.support.not_implemented",
                        message=resolved_message,
                        severity=OperationDiagnosticSeverity.ERROR,
                        details={
                            "operation": wanted,
                            **(details or {}),
                        },
                    ),
                ),
                "diagnostics",
            )
            if diagnostics is None
            else diagnostics
        )
        return cls(
            operation=wanted,
            support=OperationSupport.NOT_IMPLEMENTED,
            message=resolved_message,
            diagnostics=resolved_diagnostics,
            details=details or {},
        )

    def to_dict(self) -> dict[str, PlainData]:
        support = cast(OperationSupport, self.support)
        return {
            "operation": self.operation,
            "support": support.value,
            "message": self.message,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "OperationSupportRecord":
        payload = _as_mapping(data, "OperationSupportRecord")
        _reject_unknown(
            payload,
            {"operation", "support", "message", "diagnostics", "details"},
            "OperationSupportRecord",
        )
        _require_fields(
            payload,
            {"operation", "support", "message"},
            "OperationSupportRecord",
        )
        diagnostics = _coerce_operation_diagnostics_from_dict(
            payload.get("diagnostics", ()),
            "diagnostics",
        )
        return cls(
            operation=cast(str, payload["operation"]),
            support=cast(OperationSupport | str, payload["support"]),
            message=cast(str, payload["message"]),
            diagnostics=diagnostics,
            details=cast(Mapping[str, PlainData], payload.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Shared envelope for one attempted operation and evidence."""

    operation: str
    status: OperationStatus | str
    adapter: OperationAdapterIdentity | None = None
    diagnostics: Sequence[OperationDiagnostic] = ()
    evidence: OperationEvidenceRecord | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _require_non_empty(self.operation, "operation"))
        object.__setattr__(
            self,
            "status",
            _coerce_operation_status(self.status, "status"),
        )
        if self.adapter is not None and not isinstance(self.adapter, OperationAdapterIdentity):
            raise OperationValidationError("adapter must be an OperationAdapterIdentity or None")
        object.__setattr__(
            self,
            "diagnostics",
            _coerce_operation_diagnostics(self.diagnostics, "diagnostics"),
        )
        if self.evidence is not None and not isinstance(
            self.evidence,
            OperationEvidenceRecord,
        ):
            raise OperationValidationError("evidence must be an OperationEvidenceRecord or None")
        object.__setattr__(
            self,
            "details",
            freeze_plain_data(_sanitize_details(self.details), path="details"),
        )

    @classmethod
    def unsupported(
        cls,
        operation: str,
        *,
        reason: str,
        adapter: OperationAdapterIdentity | None = None,
        diagnostics: Sequence[OperationDiagnostic] | None = None,
        checks: Sequence[OperationEvidenceCheck] | None = None,
        details: Mapping[str, PlainData] | None = None,
    ) -> "OperationResult":
        result_reason = _require_non_empty(reason, "reason")
        resolved_diagnostics = (
            _coerce_operation_diagnostics(
                (
                    OperationDiagnostic(
                        code="operation.unsupported",
                        message=result_reason,
                        severity=OperationDiagnosticSeverity.ERROR,
                        details={"operation": _require_non_empty(operation, "operation")},
                    ),
                ),
                "diagnostics",
            )
            if diagnostics is None
            else diagnostics
        )
        resolved_checks = (
            _coerce_operation_evidence_checks(checks, "checks")
            if checks is not None
            else ()
        )
        return cls(
            operation=_require_non_empty(operation, "operation"),
            status=OperationStatus.UNSUPPORTED,
            adapter=adapter,
            diagnostics=resolved_diagnostics,
            evidence=OperationEvidenceRecord(
                status=OperationEvidenceStatus.UNSUPPORTED,
                checks=resolved_checks,
                adapter=adapter,
                details={"reason": result_reason, **(_sanitize_details(details or {}))},
            ),
            details=_canonical_merge_details(
                details=details,
                operation=operation,
                reason=result_reason,
            ),
        )

    @classmethod
    def not_implemented(
        cls,
        operation: str,
        *,
        reason: str,
        adapter: OperationAdapterIdentity | None = None,
        diagnostics: Sequence[OperationDiagnostic] | None = None,
        checks: Sequence[OperationEvidenceCheck] | None = None,
        details: Mapping[str, PlainData] | None = None,
    ) -> "OperationResult":
        result_reason = _require_non_empty(reason, "reason")
        resolved_diagnostics = (
            _coerce_operation_diagnostics(
                (
                    OperationDiagnostic(
                        code="operation.not_implemented",
                        message=result_reason,
                        severity=OperationDiagnosticSeverity.ERROR,
                        details={"operation": _require_non_empty(operation, "operation")},
                    ),
                ),
                "diagnostics",
            )
            if diagnostics is None
            else diagnostics
        )
        resolved_checks = (
            _coerce_operation_evidence_checks(checks, "checks")
            if checks is not None
            else ()
        )
        return cls(
            operation=_require_non_empty(operation, "operation"),
            status=OperationStatus.NOT_IMPLEMENTED,
            adapter=adapter,
            diagnostics=resolved_diagnostics,
            evidence=OperationEvidenceRecord(
                status=OperationEvidenceStatus.NOT_IMPLEMENTED,
                checks=resolved_checks,
                adapter=adapter,
                details={"reason": result_reason, **(_sanitize_details(details or {}))},
            ),
            details=_canonical_merge_details(
                details=details,
                operation=operation,
                reason=result_reason,
            ),
        )

    def to_dict(self) -> dict[str, PlainData]:
        status = cast(OperationStatus, self.status)
        return {
            "operation": self.operation,
            "status": status.value,
            "adapter": self.adapter.to_dict() if self.adapter is not None else None,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "evidence": self.evidence.to_dict() if self.evidence is not None else None,
            "details": thaw_plain_data(self.details, path="details"),
        }

    @classmethod
    def from_dict(cls, data: object) -> "OperationResult":
        payload = _as_mapping(data, "OperationResult")
        _reject_unknown(
            payload,
            {"operation", "status", "adapter", "diagnostics", "evidence", "details"},
            "OperationResult",
        )
        _require_fields(payload, {"operation", "status"}, "OperationResult")
        diagnostics = _coerce_operation_diagnostics_from_dict(
            payload.get("diagnostics", ()),
            "diagnostics",
        )
        evidence_data = payload.get("evidence")
        evidence = (
            None
            if evidence_data is None
            else OperationEvidenceRecord.from_dict(evidence_data)
        )
        adapter_data = payload.get("adapter")
        adapter = (
            None
            if adapter_data is None
            else OperationAdapterIdentity.from_dict(adapter_data)
        )
        return cls(
            operation=cast(str, payload["operation"]),
            status=cast(OperationStatus | str, payload["status"]),
            adapter=adapter,
            diagnostics=diagnostics,
            evidence=evidence,
            details=cast(Mapping[str, PlainData], payload.get("details", {})),
        )


_SENSITIVE_DETAIL_KEYS = {
    "token",
    "secret",
    "secret_key",
    "password",
    "api_key",
    "apikey",
    "credential",
    "client_secret",
    "access_token",
}

_SENSITIVE_URI_PATTERN = re.compile(r"(?i)([?&](?:token|access_token|api[_-]?key|secret|secret_key|password)=[^&]+)")


def _coerce_operation_status(
    value: OperationStatus | str,
    field: str,
) -> OperationStatus:
    if isinstance(value, OperationStatus):
        return value
    try:
        return OperationStatus(value)
    except ValueError as exc:
        raise OperationValidationError(f"{field} must be a valid operation status") from exc


def _coerce_operation_support(
    value: OperationSupport | str,
    field: str,
) -> OperationSupport:
    if isinstance(value, OperationSupport):
        return value
    try:
        return OperationSupport(value)
    except ValueError as exc:
        raise OperationValidationError(f"{field} must be a valid operation support value") from exc


def _coerce_operation_diagnostic_severity(
    value: OperationDiagnosticSeverity | str,
) -> OperationDiagnosticSeverity:
    if isinstance(value, OperationDiagnosticSeverity):
        return value
    try:
        return OperationDiagnosticSeverity(value)
    except ValueError as exc:
        raise OperationValidationError(
            "severity must be info, warning, or error"
        ) from exc


def _coerce_operation_evidence_status(
    value: OperationEvidenceStatus | str,
    field: str,
) -> OperationEvidenceStatus:
    if isinstance(value, OperationEvidenceStatus):
        return value
    try:
        return OperationEvidenceStatus(value)
    except ValueError as exc:
        raise OperationValidationError(f"{field} must be a valid evidence status") from exc


def _coerce_operation_diagnostics(
    value: Sequence[OperationDiagnostic],
    field: str,
) -> tuple[OperationDiagnostic, ...]:
    if isinstance(value, tuple):
        diagnostics = value
    elif isinstance(value, list):
        diagnostics = tuple(value)
    elif value == ():
        diagnostics = ()
    else:
        raise OperationValidationError(f"{field} must be a sequence of OperationDiagnostic")
    normalized: list[OperationDiagnostic] = []
    for index, item in enumerate(diagnostics):
        if not isinstance(item, OperationDiagnostic):
            raise OperationValidationError(
                f"{field}[{index}] must be an OperationDiagnostic"
            )
        normalized.append(item)
    return tuple(normalized)


def _coerce_operation_evidence_checks(
    value: Sequence[OperationEvidenceCheck],
    field: str,
) -> tuple[OperationEvidenceCheck, ...]:
    if isinstance(value, tuple):
        checks = value
    elif isinstance(value, list):
        checks = tuple(value)
    elif value == ():
        checks = ()
    else:
        raise OperationValidationError(f"{field} must be a sequence of OperationEvidenceCheck")
    normalized: list[OperationEvidenceCheck] = []
    for index, item in enumerate(checks):
        if not isinstance(item, OperationEvidenceCheck):
            raise OperationValidationError(
                f"{field}[{index}] must be an OperationEvidenceCheck"
            )
        normalized.append(item)
    return tuple(normalized)


def _coerce_operation_evidence_checks_from_dict(
    value: object,
    field: str,
) -> tuple[OperationEvidenceCheck, ...]:
    if isinstance(value, tuple):
        payload = value
    elif isinstance(value, list):
        payload = tuple(value)
    else:
        raise OperationValidationError(f"{field} must be a sequence")
    normalized: list[OperationEvidenceCheck] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise OperationValidationError(
                f"{field}[{index}] must be a mapping for OperationEvidenceCheck"
            )
        normalized.append(OperationEvidenceCheck.from_dict(item))
    return tuple(normalized)


def _coerce_operation_diagnostics_from_dict(
    value: object,
    field: str,
) -> tuple[OperationDiagnostic, ...]:
    if isinstance(value, tuple):
        payload = value
    elif isinstance(value, list):
        payload = tuple(value)
    else:
        raise OperationValidationError(f"{field} must be a sequence")
    normalized: list[OperationDiagnostic] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise OperationValidationError(
                f"{field}[{index}] must be a mapping for OperationDiagnostic"
            )
        normalized.append(OperationDiagnostic.from_dict(item))
    return tuple(normalized)


def _reject_unknown(
    payload: Mapping[str, object],
    allowed: set[str],
    owner: str,
) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise OperationValidationError(
            f"{owner} has unknown fields: {', '.join(sorted(unknown))}"
        )


def _require_fields(payload: Mapping[str, object], required: set[str], owner: str) -> None:
    missing = required - set(payload)
    if missing:
        raise OperationValidationError(
            f"{owner} is missing required field(s): {', '.join(sorted(missing))}"
        )


def _as_mapping(data: object, owner: str) -> dict[str, object]:
    if not isinstance(data, Mapping):
        raise OperationValidationError(f"{owner}.from_dict expects a mapping")
    keys = set(data.keys())
    if not all(isinstance(key, str) for key in keys):
        raise OperationValidationError(f"{owner}.from_dict received non-string keys")
    return cast(dict[str, object], dict(data))


def _sanitize_details(value: Mapping[str, PlainData]) -> dict[str, PlainData]:
    details = dict(value)
    sanitized: dict[str, PlainData] = {}
    for key, item in details.items():
        sanitized[key] = cast(PlainData, _sanitize_detail_value(key, item))
    return sanitized


def _sanitize_detail_value(key: str, value: object) -> PlainData:
    sanitized_key = key.lower()
    if sanitized_key in _SENSITIVE_DETAIL_KEYS:
        return "<redacted>"
    try:
        safe = ensure_plain_data(_coerce_plain_data_value(value), path=f"details[{key}]")
    except Exception as exc:
        raise OperationValidationError(
            f"details[{key}] must be plain data"
        ) from exc
    if isinstance(safe, str):
        if _is_sensitive_uri(safe):
            return "<redacted>"
        return cast(PlainData, _mask_query_secret(safe))
    if isinstance(safe, dict):
        return {
            child_key: cast(PlainData, _sanitize_detail_value(str(child_key), child_value))
            for child_key, child_value in safe.items()
        }
    if isinstance(safe, list):
        return [
            cast(PlainData, _sanitize_detail_value(f"{key}[{index}]", item))
            for index, item in enumerate(safe)
        ]
    return cast(PlainData, safe)


def _coerce_plain_data_value(value: object) -> object:
    # preserve compatibility with detail-only payloads and keep failures local
    if isinstance(value, tuple):
        return list(value)
    return value


def _mask_query_secret(value: str) -> str:
    return _SENSITIVE_URI_PATTERN.sub(
        lambda match: match.group(0).split("=")[0] + "=<redacted>",
        value,
    )


def _is_sensitive_uri(value: str) -> bool:
    return "://" in value and "@" in value


def _require_non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or value == "":
        raise OperationValidationError(f"{field} must be a non-empty string")
    return value


def _canonical_merge_details(
    *,
    details: Mapping[str, PlainData] | None,
    operation: str,
    reason: str,
) -> dict[str, PlainData]:
    merged: dict[str, PlainData] = {"operation": operation, "reason": reason}
    if details is not None:
        for key, value in details.items():
            if key in merged:
                continue
            merged[key] = cast(PlainData, value)
    return merged


__all__ = [
    "OperationValidationError",
    "OperationStatus",
    "OperationSupport",
    "OperationDiagnosticSeverity",
    "OperationEvidenceStatus",
    "OperationAdapterIdentity",
    "OperationDiagnostic",
    "OperationEvidenceCheck",
    "OperationEvidenceRecord",
    "OperationSupportRecord",
    "OperationResult",
]
