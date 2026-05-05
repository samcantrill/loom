"""Unit tests for phase-4 config errors."""

from typing import Any

import pytest

from loom.errors import ConfigError
from loom.config.errors import (
    ConfigErrorContext,
    ConfigInterpolationError,
    ConfigIncludeResolutionError,
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
from loom.serialization import PlainDataError


def test_config_error_shapes() -> None:
    assert issubclass(ConfigLoadError, ConfigError)
    assert issubclass(ConfigMergeError, ConfigError)
    assert issubclass(ConfigIncludeResolutionError, ConfigError)
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
    details = payload["details"]
    assert isinstance(details, dict)
    assert details["path"] == "$.model"
    assert ConfigErrorContext.from_dict(payload) == context

    error = ConfigLoadError("unsupported directive", context=context)
    serialized = error.to_dict()
    assert serialized["context"]["code"] == "unsupported_directive"


def test_config_error_context_normalizes_plain_data_at_construction() -> None:
    expected: Any = ("mapping", "plain")
    actual: Any = {"items": ("tuple",)}
    details: Any = {"paths": ("$.model", "$.dataset")}

    context = ConfigErrorContext(
        code="shape_error",
        source_kind="base",
        source_order=0,
        source_path="/tmp/base.yaml",
        expected=expected,
        actual=actual,
        details=details,
    )

    assert context.expected == ["mapping", "plain"]
    assert context.actual == {"items": ["tuple"]}
    assert context.details == {"paths": ["$.model", "$.dataset"]}


def test_config_error_context_rejects_invalid_details_at_construction() -> None:
    with pytest.raises(TypeError, match="details must be a mapping"):
        ConfigErrorContext(
            code="shape_error",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
            details=["not", "a", "mapping"],  # type: ignore[arg-type]
        )

    with pytest.raises(PlainDataError, match="set-like values"):
        ConfigErrorContext(
            code="shape_error",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
            details={"bad": {1, 2}},  # type: ignore[dict-item]
        )


def test_config_error_context_rejects_invalid_expected_actual_at_construction() -> None:
    with pytest.raises(PlainDataError, match="set-like values"):
        ConfigErrorContext(
            code="shape_error",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
            expected={"bad": {1, 2}},  # type: ignore[dict-item]
        )

    with pytest.raises(PlainDataError, match="set-like values"):
        ConfigErrorContext(
            code="shape_error",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
            actual={"bad": {1, 2}},  # type: ignore[dict-item]
        )
