"""Config-domain errors for trusted config composition and instantiation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PlainData = None | bool | int | float | str | list["PlainData"] | dict[str, "PlainData"]


class ConfigError(Exception):
    """Base exception for package-owned config failures."""


class PlainDataError(ConfigError):
    """Error for invalid plain-data values."""


class SerializationError(ConfigError):
    """Error raised when structured config payloads cannot be serialized or decoded."""


class DeserializationError(ConfigError):
    """Error while decoding structured inputs."""


class DeserializationContextError(ConfigError):
    """Error for deserialization failures that include structured context."""


class FingerprintError(ConfigError):
    """Error while parsing or comparing fingerprint values."""


class FingerprintInputError(FingerprintError):
    """Error for invalid fingerprint input."""


class InvalidDigestError(FingerprintError):
    """Error for malformed digest strings."""


class UnsupportedHashAlgorithmError(FingerprintError):
    """Error for unsupported hash algorithms."""


class FingerprintComparisonError(FingerprintError):
    """Error while comparing digests."""


@dataclass(frozen=True, slots=True)
class ConfigErrorContext:
    """Machine-readable context for structured config errors."""

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
        """Normalize plain-data fields when callers construct contexts directly."""

        from .plain import ensure_plain_data

        if self.expected is not None:
            object.__setattr__(self, "expected", ensure_plain_data(self.expected))
        if self.actual is not None:
            object.__setattr__(self, "actual", ensure_plain_data(self.actual))
        if self.details is None:
            return

        details = ensure_plain_data(self.details)
        if not isinstance(details, dict):
            raise TypeError("Config error context details must be a mapping")
        object.__setattr__(self, "details", details)

    def to_dict(self) -> dict[str, PlainData]:
        """Serialize the context as plain data."""

        from .plain import to_plain_data

        return {
            "code": self.code,
            "source_kind": self.source_kind,
            "source_order": self.source_order,
            "source_path": self.source_path,
            "config_path": self.config_path if self.config_path is not None else None,
            "expected": self.expected,
            "actual": self.actual,
            "directive": self.directive,
            "remediation": self.remediation,
            "details": to_plain_data(self.details if self.details is not None else {}),
        }

    @classmethod
    def from_dict(cls, value: object) -> "ConfigErrorContext":
        """Rebuild a context from plain serialized payload."""

        from .plain import ensure_plain_data

        payload = ensure_plain_data(value)
        if not isinstance(payload, dict):
            raise ValueError("ConfigErrorContext payload must be a mapping")

        code = payload.get("code")
        source_kind = payload.get("source_kind")
        source_order = payload.get("source_order")
        source_path = payload.get("source_path")
        config_path = payload.get("config_path")
        expected = payload.get("expected")
        actual = payload.get("actual")
        directive = payload.get("directive")
        remediation = payload.get("remediation")
        details = payload.get("details")

        if not isinstance(code, str):
            raise ValueError(f"Invalid context code: {code!r}")
        if not isinstance(source_kind, str):
            raise ValueError(f"Invalid context source kind: {source_kind!r}")
        if not isinstance(source_order, int):
            raise ValueError(f"Invalid context source order: {source_order!r}")
        if not isinstance(source_path, str):
            raise ValueError(f"Invalid context source path: {source_path!r}")
        if config_path is not None and not isinstance(config_path, str):
            raise ValueError(f"Invalid context config path: {config_path!r}")
        if directive is not None and not isinstance(directive, str):
            raise ValueError(f"Invalid context directive: {directive!r}")
        if remediation is not None and not isinstance(remediation, str):
            raise ValueError(f"Invalid context remediation: {remediation!r}")
        if not (details is None or isinstance(details, dict)):
            raise ValueError(f"Invalid context details: {details!r}")

        return cls(
            code=code,
            source_kind=source_kind,
            source_order=source_order,
            source_path=source_path,
            config_path=config_path,
            expected=expected,
            actual=actual,
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
    """Error while loading YAML config sources."""


class ConfigMergeError(_ConfigError):
    """Error while merging multiple config sources."""


class OverrideParseError(_ConfigError):
    """Error while parsing CLI overrides."""


class OverrideApplyError(_ConfigError):
    """Error while applying overrides to a config mapping."""


class ConfigInterpolationError(_ConfigError):
    """Error while resolving config-node interpolation."""


class ConfigUnsupportedResolverError(_ConfigError, NotImplementedError):
    """Error for unsupported OmegaConf resolver execution."""


class ConfigValidationError(_ConfigError):
    """Error while validating config ownership and required fields."""


class ConfigRedactionError(_ConfigError):
    """Error while redacting resolved config values."""


class ConfigProvenanceError(_ConfigError):
    """Error while constructing config provenance metadata."""

    def __init__(self, message: str, *, context: ConfigErrorContext | None = None) -> None:
        if context is None:
            context = ConfigErrorContext(
                code="config_provenance_error",
                source_kind="provenance",
                source_order=0,
                source_path="<config-provenance>",
                details={"stage": "config_provenance"},
            )
        super().__init__(message, context=context)


class ConfigIncludeResolutionError(ConfigValidationError):
    """Error while resolving include targets to concrete local files."""


class ConfigIncludeExpansionError(_ConfigError):
    """Error while expanding file-authored include directives."""


class UnsupportedRecipeError(_ConfigError):
    """Error for recipe-related behavior that is not supported by this phase."""


class RecipeRegistrationError(_ConfigError):
    """Error registering a recipe implementation."""


class DuplicateRecipeError(UnsupportedRecipeError):
    """Error when a recipe name is already registered."""


class UnknownRecipeError(_ConfigError):
    """Error when a recipe name is not registered."""


class RecipeExpansionError(_ConfigError):
    """Error while expanding a configured recipe block."""


class InvalidRecipeOutputError(RecipeExpansionError):
    """Error when a recipe expansion output is invalid for config composition."""


class ReservedConfigKeyError(ConfigValidationError):
    """Error for invalid use of reserved config directive keys."""


class TargetImportError(_ConfigError):
    """Error while resolving `_target_` import paths."""


class TargetInstantiationError(_ConfigError):
    """Error while constructing objects from `_target_` config nodes."""


class RuntimeInjectionError(TargetInstantiationError):
    """Error resolving runtime injection references for `_inject_`."""


class MissingConfigDependencyError(_ConfigError):
    """Error raised when optional config dependencies are missing."""


class UnsupportedConfigDirectiveError(ConfigLoadError):
    """Error for a supported-but-disabled config directive."""


__all__ = [
    "ConfigError",
    "PlainDataError",
    "SerializationError",
    "DeserializationError",
    "DeserializationContextError",
    "FingerprintError",
    "FingerprintInputError",
    "InvalidDigestError",
    "UnsupportedHashAlgorithmError",
    "FingerprintComparisonError",
    "ConfigLoadError",
    "ConfigMergeError",
    "OverrideParseError",
    "OverrideApplyError",
    "ConfigInterpolationError",
    "ConfigValidationError",
    "ConfigRedactionError",
    "ConfigProvenanceError",
    "UnsupportedRecipeError",
    "UnsupportedConfigDirectiveError",
    "ConfigErrorContext",
    "ConfigIncludeResolutionError",
    "ConfigIncludeExpansionError",
    "ConfigUnsupportedResolverError",
    "RecipeRegistrationError",
    "DuplicateRecipeError",
    "UnknownRecipeError",
    "RecipeExpansionError",
    "InvalidRecipeOutputError",
    "ReservedConfigKeyError",
    "TargetImportError",
    "TargetInstantiationError",
    "RuntimeInjectionError",
    "MissingConfigDependencyError",
]
