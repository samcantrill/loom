"""Config-domain errors for phase-4 composition."""

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
    """Error for recipe-related behavior not yet implemented in Phase 4."""


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
]
