"""Package tests for config error helpers."""

import pytest

from weave.errors import (
    ConfigErrorContext,
    ConfigIncludeResolutionError,
    ConfigLoadError,
    ConfigValidationError,
    DuplicateRecipeError,
    PlainDataError,
    RecipeRegistrationError,
)


pytestmark = pytest.mark.package


def test_error_context_round_trips() -> None:
    context = ConfigErrorContext(
        code="unsupported_directive",
        source_kind="base",
        source_order=0,
        source_path="/tmp/base.yaml",
        expected=("a", "b"),
        actual={"x": 1},
        config_path="$.pipeline",
        directive="_target_",
        remediation="Use a supported directive",
        details={"kind": "directive"},
    )

    payload = context.to_dict()
    restored = ConfigErrorContext.from_dict(payload)
    assert restored == context


def test_error_context_rejects_non_plain_details() -> None:
    with pytest.raises(PlainDataError):
        ConfigErrorContext(
            code="shape_error",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
            details={"bad": {1, 2}},
        )


def test_config_errors_have_payloads() -> None:
    error = ConfigLoadError(
        "unsupported directive",
        context=ConfigErrorContext(
            code="unsupported",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
        ),
    )
    payload = error.to_dict()
    assert payload["message"] == "unsupported directive"
    assert payload["context"]["code"] == "unsupported"


def test_error_inheritance_surface() -> None:
    assert issubclass(ConfigLoadError, Exception)
    assert issubclass(DuplicateRecipeError, RecipeRegistrationError)
    assert issubclass(ConfigValidationError, Exception)
    assert issubclass(ConfigIncludeResolutionError, Exception)
    assert not issubclass(ConfigIncludeResolutionError, ConfigValidationError)
