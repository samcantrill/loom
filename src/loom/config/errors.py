"""Config-domain errors for trusted config composition and instantiation."""

from __future__ import annotations

from loom.errors import ConfigError


class ConfigLoadError(ConfigError):
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
    "RecipeRegistrationError",
    "DuplicateRecipeError",
    "UnknownRecipeError",
    "RecipeExpansionError",
    "InvalidRecipeOutputError",
    "ReservedConfigKeyError",
    "TargetImportError",
    "TargetInstantiationError",
    "RuntimeInjectionError",
]
