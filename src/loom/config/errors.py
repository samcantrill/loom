"""Config-domain errors for trusted config composition and instantiation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loom.errors import ConfigError
from loom.serialization import PlainData, ensure_plain_data, to_plain_data


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


class ConfigMergeError(ConfigError):
    """Error while merging multiple config sources."""


class OverrideParseError(ConfigError):
    """Error while parsing CLI overrides."""


class OverrideApplyError(ConfigError):
    """Error while applying overrides to a config mapping."""


class ConfigInterpolationError(ConfigError):
    """Error while resolving config-node interpolation."""


class ConfigValidationError(ConfigError):
    """Error while validating config ownership and required fields."""


class ConfigRedactionError(ConfigError):
    """Error while redacting resolved config values."""


class ConfigProvenanceError(ConfigError):
    """Error while constructing config provenance metadata."""


class UnsupportedRecipeError(ConfigError):
    """Error for recipe-related behavior that is not supported by this phase."""


class RecipeRegistrationError(ConfigError):
    """Error registering a recipe implementation."""


class DuplicateRecipeError(RecipeRegistrationError):
    """Error when a recipe name is already registered."""


class UnknownRecipeError(ConfigError):
    """Error when a recipe name is not registered."""


class RecipeExpansionError(ConfigError):
    """Error while expanding a configured recipe block."""


class InvalidRecipeOutputError(RecipeExpansionError):
    """Error when a recipe expansion output is invalid for config composition."""


class ReservedConfigKeyError(ConfigValidationError):
    """Error for invalid use of reserved config directive keys."""


class TargetImportError(ConfigError):
    """Error while resolving `_target_` import paths."""


class TargetInstantiationError(ConfigError):
    """Error while constructing objects from `_target_` config nodes."""


class RuntimeInjectionError(TargetInstantiationError):
    """Error resolving runtime injection references for `_inject_`."""


class MissingConfigDependencyError(ConfigError):
    """Error raised when optional config dependencies are missing."""


class UnsupportedConfigDirectiveError(ConfigLoadError):
    """Error for a supported-but-disabled config directive."""


__all__ = [
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
