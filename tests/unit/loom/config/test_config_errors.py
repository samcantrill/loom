"""Unit tests for phase-4 config errors."""

from loom.errors import ConfigError
from loom.config.errors import (
    ConfigInterpolationError,
    ConfigLoadError,
    ConfigMergeError,
    DuplicateRecipeError,
    InvalidRecipeOutputError,
    RecipeExpansionError,
    ConfigProvenanceError,
    ConfigRedactionError,
    ConfigValidationError,
    RecipeRegistrationError,
    ReservedConfigKeyError,
    RuntimeInjectionError,
    TargetImportError,
    TargetInstantiationError,
    OverrideApplyError,
    OverrideParseError,
    UnsupportedRecipeError,
    UnknownRecipeError,
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
    assert issubclass(RecipeRegistrationError, ConfigError)
    assert issubclass(DuplicateRecipeError, RecipeRegistrationError)
    assert issubclass(UnknownRecipeError, ConfigError)
    assert issubclass(RecipeExpansionError, ConfigError)
    assert issubclass(InvalidRecipeOutputError, RecipeExpansionError)
    assert issubclass(ReservedConfigKeyError, ConfigValidationError)
    assert issubclass(RuntimeInjectionError, TargetInstantiationError)
    assert issubclass(TargetImportError, ConfigError)
    assert issubclass(TargetInstantiationError, ConfigError)
