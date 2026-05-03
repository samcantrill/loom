"""Unit tests for phase-4 config errors."""

from loom.errors import ConfigError
from loom.config.errors import (
    ConfigInterpolationError,
    ConfigLoadError,
    ConfigMergeError,
    ConfigProvenanceError,
    ConfigRedactionError,
    ConfigValidationError,
    OverrideApplyError,
    OverrideParseError,
    UnsupportedRecipeError,
)


def test_config_error_shapes() -> None:
    assert issubclass(ConfigLoadError, ConfigError)
    assert issubclass(ConfigMergeError, ConfigError)
    assert issubclass(OverrideParseError, ConfigError)
    assert issubclass(OverrideApplyError, ConfigError)
    assert issubclass(ConfigInterpolationError, ConfigError)
    assert issubclass(ConfigValidationError, ConfigError)
    assert issubclass(ConfigProvenanceError, ConfigError)
    assert issubclass(ConfigRedactionError, ConfigError)
    assert issubclass(UnsupportedRecipeError, ConfigError)
