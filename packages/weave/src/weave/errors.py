"""Config-owned error primitives and structured error payload helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PlainData = None | bool | int | float | str | list["PlainData"] | dict[str, "PlainData"]


class SerializationError(Exception):
    """Error raised when structured config payloads cannot be serialized or decoded."""


class DeserializationError(SerializationError):
    """Error raised for config payload input parse failures."""


class PlainDataError(SerializationError):
    """Error raised when a value is not plain structured data."""


class ConfigError(Exception):
    """Base config-domain error."""


class DeserializationContextError(ConfigError):
    """Error for deserialization failures that include structured context."""


@dataclass(frozen=True, slots=True)
class ConfigErrorContext:
    """Machine-readable context for config errors."""

    code: str
    source_kind: str
    source_order: int
    source_path: str
    config_path: str | None = None
    expected: PlainData | None = None
    actual: PlainData | None = None
    directive: str | None = None
    remediation: str | None = None
    details: dict[str, PlainData] | None = None

    def __post_init__(self) -> None:
        from .plain import ensure_plain_data

        if self.expected is not None:
            object.__setattr__(self, "expected", ensure_plain_data(self.expected))
        if self.actual is not None:
            object.__setattr__(self, "actual", ensure_plain_data(self.actual))
        if self.config_path is not None and not isinstance(self.config_path, str):
            raise ValueError(f"config_path must be a string: {self.config_path!r}")
        if self.details is not None:
            normalized = ensure_plain_data(self.details)
            if not isinstance(normalized, dict):
                raise ValueError("Config error details must be a mapping")
            object.__setattr__(self, "details", normalized)

    def to_dict(self) -> dict[str, PlainData | None]:
        from .plain import to_plain_data

        return {
            "code": self.code,
            "source_kind": self.source_kind,
            "source_order": self.source_order,
            "source_path": self.source_path,
            "config_path": self.config_path,
            "expected": to_plain_data(self.expected) if self.expected is not None else None,
            "actual": to_plain_data(self.actual) if self.actual is not None else None,
            "directive": self.directive,
            "remediation": self.remediation,
            "details": to_plain_data(self.details or {}),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConfigErrorContext":
        if not isinstance(value, dict):
            raise ValueError("ConfigErrorContext payload must be a mapping")

        for field in ("code", "source_kind", "source_order", "source_path"):
            if field not in value:
                raise ValueError(f"Missing required context field: {field}")

        code = value["code"]
        source_kind = value["source_kind"]
        source_order = value["source_order"]
        source_path = value["source_path"]
        if not isinstance(code, str):
            raise ValueError(f"Invalid context code: {code!r}")
        if not isinstance(source_kind, str):
            raise ValueError(f"Invalid context source kind: {source_kind!r}")
        if not isinstance(source_order, int):
            raise ValueError(f"Invalid source order: {source_order!r}")
        if not isinstance(source_path, str):
            raise ValueError(f"Invalid source path: {source_path!r}")

        config_path = value.get("config_path")
        if config_path is not None and not isinstance(config_path, str):
            raise ValueError(f"Invalid config_path: {config_path!r}")

        directive = value.get("directive")
        if directive is not None and not isinstance(directive, str):
            raise ValueError(f"Invalid directive: {directive!r}")

        remediation = value.get("remediation")
        if remediation is not None and not isinstance(remediation, str):
            raise ValueError(f"Invalid remediation: {remediation!r}")

        details = value.get("details")
        if details is not None and not isinstance(details, dict):
            raise ValueError(f"Invalid details: {details!r}")

        return cls(
            code=code,
            source_kind=source_kind,
            source_order=source_order,
            source_path=source_path,
            config_path=config_path,
            expected=value.get("expected"),
            actual=value.get("actual"),
            directive=directive,
            remediation=remediation,
            details=details,
        )


class _ConfigError(ConfigError):
    """Base config-domain error with optional structured context."""

    def __init__(self, message: str, *, context: ConfigErrorContext | None = None) -> None:
        super().__init__(message)
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": str(self)}
        if self.context is not None:
            payload["context"] = self.context.to_dict()
        return payload


class ConfigLoadError(_ConfigError):
    """Error while loading config payloads or user-authored files."""


class ConfigMergeError(_ConfigError):
    """Error while merging multiple config sources."""


class OverrideParseError(_ConfigError):
    """Error while parsing CLI overrides."""


class OverrideApplyError(_ConfigError):
    """Error while applying overrides to a config mapping."""


class ConfigValidationError(_ConfigError):
    """Error while validating config ownership and required fields."""


class ConfigProvenanceError(_ConfigError):
    """Error while deriving provenance metadata."""


class ConfigRedactionError(_ConfigError):
    """Error while redacting resolved config values."""


class UnsupportedRecipeError(_ConfigError):
    """Error for recipe behavior not yet supported by this package baseline."""


class RecipeRegistrationError(_ConfigError):
    """Error registering a recipe implementation."""


class DuplicateRecipeError(UnsupportedRecipeError):
    """Error when a recipe name is already registered."""


class UnknownRecipeError(_ConfigError):
    """Error when a recipe name is not known."""


class ConfigInterpolationError(_ConfigError):
    """Error resolving interpolation expressions."""


class ConfigUnsupportedResolverError(_ConfigError, NotImplementedError):
    """Error for unsupported config interpolators."""


class ConfigIncludeResolutionError(ConfigValidationError):
    """Error while resolving include files."""


class ConfigIncludeExpansionError(_ConfigError):
    """Error while expanding include directives."""


class RecipeExpansionError(_ConfigError):
    """Error while expanding recipe directives."""


class InvalidRecipeOutputError(RecipeExpansionError):
    """Error when recipe output is not valid plain data."""


class ReservedConfigKeyError(ConfigValidationError):
    """Error when config uses reserved keys."""


class TargetImportError(_ConfigError):
    """Error while resolving `_target_` import paths."""


class TargetInstantiationError(_ConfigError):
    """Error while instantiating target-backed config nodes."""


class RuntimeInjectionError(TargetInstantiationError):
    """Error resolving `_inject_` references."""


class MissingConfigDependencyError(_ConfigError):
    """Error when optional config dependencies are not installed."""


class UnsupportedConfigDirectiveError(ConfigLoadError):
    """Error for supported-but-disabled config directives."""


@dataclass(frozen=True, slots=True)
class ParsedDigest:
    """Parsed digest metadata for hash checks."""

    algorithm: str
    hexdigest: str


class UnsupportedHashAlgorithmError(ConfigError):
    """Error for unsupported digest hash algorithms."""


class InvalidDigestError(ConfigError):
    """Error for malformed digest strings."""


class FingerprintInputError(ConfigError):
    """Error for invalid inputs to hashing helpers."""


__all__ = [
    "SerializationError",
    "DeserializationError",
    "PlainDataError",
    "ConfigError",
    "DeserializationContextError",
    "ConfigErrorContext",
    "_ConfigError",
    "ConfigLoadError",
    "ConfigMergeError",
    "OverrideParseError",
    "OverrideApplyError",
    "ConfigValidationError",
    "ConfigProvenanceError",
    "ConfigRedactionError",
    "UnsupportedRecipeError",
    "RecipeRegistrationError",
    "DuplicateRecipeError",
    "UnknownRecipeError",
    "ConfigInterpolationError",
    "ConfigUnsupportedResolverError",
    "ConfigIncludeResolutionError",
    "ConfigIncludeExpansionError",
    "RecipeExpansionError",
    "InvalidRecipeOutputError",
    "ReservedConfigKeyError",
    "TargetImportError",
    "TargetInstantiationError",
    "RuntimeInjectionError",
    "MissingConfigDependencyError",
    "UnsupportedConfigDirectiveError",
    "ParsedDigest",
    "UnsupportedHashAlgorithmError",
    "InvalidDigestError",
    "FingerprintInputError",
]
