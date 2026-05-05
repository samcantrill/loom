"""Unit tests for phase-4 config errors."""

from loom.errors import ConfigError
from loom.config.errors import (
    ConfigErrorContext,
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


def test_config_error_context_serializes_and_round_trips() -> None:
    context = ConfigErrorContext(
        code="unsupported_directive",
        source_kind="base",
        source_order=0,
        source_path="/tmp/base.yaml",
        config_path="$.model._copy_",
        expected="no deferred directives",
        actual="_copy_",
        directive="_copy_",
        remediation="Use replacement semantics available in v1 or a later phase for copy support.",
        details={"path": "$.model", "kind": "directive"},
    )
    payload = context.to_dict()
    assert payload["code"] == context.code
    assert payload["source_kind"] == context.source_kind
    assert payload["source_path"] == context.source_path
    assert payload["directive"] == context.directive
    assert payload["details"]["path"] == "$.model"
    assert ConfigErrorContext.from_dict(payload) == context

    error = ConfigLoadError("unsupported directive", context=context)
    serialized = error.to_dict()
    assert serialized["context"]["code"] == "unsupported_directive"
