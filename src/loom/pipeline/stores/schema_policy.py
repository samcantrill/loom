"""Loud-fail schema policy for v9 authoritative active state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .capabilities import DiagnosticSeverity, StoreDiagnostic


AUTHORITY_SCHEMA_VERSION = 6


class AuthoritySchemaError(ValueError):
    """Raised when authoritative active-state schema policy is violated."""


class AuthoritySchemaFailureKind(StrEnum):
    MISSING = "missing"
    INVALID = "invalid"
    UNSUPPORTED_OLDER = "unsupported_older"
    UNSUPPORTED_NEWER = "unsupported_newer"


@dataclass(frozen=True, slots=True)
class AuthoritySchemaFailure:
    kind: AuthoritySchemaFailureKind
    message: str
    found_version: int | None = None
    current_version: int = AUTHORITY_SCHEMA_VERSION
    detail: Mapping[str, PlainData] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_kind(self.kind, field="kind"))
        object.__setattr__(self, "message", _non_empty_string(self.message, "message"))
        if self.found_version is not None:
            object.__setattr__(
                self,
                "found_version",
                _positive_int(self.found_version, "found_version"),
            )
        object.__setattr__(
            self,
            "current_version",
            _positive_int(self.current_version, "current_version"),
        )
        object.__setattr__(self, "detail", _plain_mapping(self.detail, "detail"))

    def to_diagnostic(self) -> StoreDiagnostic:
        detail: dict[str, PlainData] = {
            "kind": self.kind.value,
            "current_version": self.current_version,
            **dict(self.detail),
        }
        if self.found_version is not None:
            detail["found_version"] = self.found_version
        return StoreDiagnostic(
            code=f"authority_schema_{self.kind.value}",
            message=self.message,
            severity=DiagnosticSeverity.ERROR,
            detail=detail,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "found_version": self.found_version,
            "current_version": self.current_version,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthoritySchemaFailure":
        mapping = _mapping(data, "AuthoritySchemaFailure")
        _reject_unknown(
            mapping,
            {"kind", "message", "found_version", "current_version", "detail"},
            "AuthoritySchemaFailure",
        )
        return cls(
            kind=_coerce_kind(_required(mapping, "kind"), field="kind"),
            message=_non_empty_string(_required(mapping, "message"), "message"),
            found_version=_optional_positive_int(
                mapping.get("found_version"), "found_version"
            ),
            current_version=_positive_int(
                mapping.get("current_version", AUTHORITY_SCHEMA_VERSION),
                "current_version",
            ),
            detail=_plain_mapping(mapping.get("detail", {}), "detail"),
        )


@dataclass(frozen=True, slots=True)
class AuthoritySchemaCheck:
    current_version: int = AUTHORITY_SCHEMA_VERSION
    found_version: int | None = AUTHORITY_SCHEMA_VERSION
    failure: AuthoritySchemaFailure | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "current_version",
            _positive_int(self.current_version, "current_version"),
        )
        if self.found_version is not None:
            object.__setattr__(
                self,
                "found_version",
                _positive_int(self.found_version, "found_version"),
            )
        if self.failure is not None and not isinstance(
            self.failure, AuthoritySchemaFailure
        ):
            raise AuthoritySchemaError(
                "failure must be an AuthoritySchemaFailure or None"
            )

    @property
    def supported(self) -> bool:
        return self.failure is None

    def raise_for_failure(self) -> None:
        if self.failure is not None:
            raise AuthoritySchemaError(self.failure.message)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "current_version": self.current_version,
            "found_version": self.found_version,
            "supported": self.supported,
            "failure": None if self.failure is None else self.failure.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> "AuthoritySchemaCheck":
        mapping = _mapping(data, "AuthoritySchemaCheck")
        _reject_unknown(
            mapping,
            {"current_version", "found_version", "supported", "failure"},
            "AuthoritySchemaCheck",
        )
        failure_data = mapping.get("failure")
        check = cls(
            current_version=_positive_int(
                mapping.get("current_version", AUTHORITY_SCHEMA_VERSION),
                "current_version",
            ),
            found_version=_optional_positive_int(
                mapping.get("found_version"), "found_version"
            ),
            failure=None
            if failure_data is None
            else AuthoritySchemaFailure.from_dict(failure_data),
        )
        if "supported" in mapping and mapping["supported"] != check.supported:
            raise AuthoritySchemaError("supported does not match failure")
        return check


def check_authority_schema_version(
    data: object,
    *,
    current_version: int = AUTHORITY_SCHEMA_VERSION,
    field: str = "schema_version",
) -> AuthoritySchemaCheck:
    if not isinstance(data, Mapping):
        return AuthoritySchemaCheck(
            current_version=current_version,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.INVALID,
                message="authoritative state document must be a mapping",
                found_version=None,
                current_version=current_version,
            ),
        )
    if field not in data:
        return AuthoritySchemaCheck(
            current_version=current_version,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.MISSING,
                message=f"{field} is required for authoritative active state",
                current_version=current_version,
            ),
        )
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return AuthoritySchemaCheck(
            current_version=current_version,
            found_version=None,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.INVALID,
                message=f"{field} must be a positive integer",
                current_version=current_version,
            ),
        )
    if value < current_version:
        return AuthoritySchemaCheck(
            current_version=current_version,
            found_version=value,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.UNSUPPORTED_OLDER,
                message=(
                    f"unsupported older authoritative active-state schema {value}; "
                    f"expected {current_version}"
                ),
                found_version=value,
                current_version=current_version,
            ),
        )
    if value > current_version:
        return AuthoritySchemaCheck(
            current_version=current_version,
            found_version=value,
            failure=AuthoritySchemaFailure(
                kind=AuthoritySchemaFailureKind.UNSUPPORTED_NEWER,
                message=(
                    f"unsupported newer authoritative active-state schema {value}; "
                    f"this Loom version supports {current_version}"
                ),
                found_version=value,
                current_version=current_version,
            ),
        )
    return AuthoritySchemaCheck(
        current_version=current_version,
        found_version=value,
        failure=None,
    )


def _coerce_kind(value: object, *, field: str) -> AuthoritySchemaFailureKind:
    if isinstance(value, AuthoritySchemaFailureKind):
        return value
    if not isinstance(value, str):
        raise AuthoritySchemaError(f"{field} must be a string")
    try:
        return AuthoritySchemaFailureKind(value)
    except ValueError as exc:
        raise AuthoritySchemaError(f"invalid {field} {value!r}") from exc


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthoritySchemaError(f"{field} must be a positive integer")
    return value


def _optional_positive_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field)


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthoritySchemaError(f"{field} must be a non-empty string")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthoritySchemaError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthoritySchemaError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _required(mapping: Mapping[str, object], field: str) -> object:
    if field not in mapping:
        raise AuthoritySchemaError(f"{field} is required")
    return mapping[field]


def _reject_unknown(
    mapping: Mapping[str, object], allowed: set[str], field: str
) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise AuthoritySchemaError(
            f"{field} contains unknown field(s): {', '.join(sorted(unknown))}"
        )


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    try:
        normalized = ensure_plain_data(value, path=field)
    except PlainDataError as exc:
        raise AuthoritySchemaError(
            f"{field} must be plain-data-compatible: {exc}"
        ) from exc
    if not isinstance(normalized, Mapping):
        raise AuthoritySchemaError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], normalized)


__all__ = [
    "AUTHORITY_SCHEMA_VERSION",
    "AuthoritySchemaError",
    "AuthoritySchemaFailureKind",
    "AuthoritySchemaFailure",
    "AuthoritySchemaCheck",
    "check_authority_schema_version",
]
