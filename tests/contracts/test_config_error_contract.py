"""Contract tests for config structured error context payloads."""

import pytest

from loom.config.errors import (
    ConfigErrorContext,
    ConfigValidationError,
    ConfigUnsupportedResolverError,
    ConfigIncludeExpansionError,
    ConfigIncludeResolutionError,
    ConfigLoadError,
)
from loom.serialization import PlainDataError


def test_config_error_context_round_trip() -> None:
    context = ConfigErrorContext(
        code="unsupported_directive",
        source_kind="base",
        source_order=0,
        source_path="/tmp/base.yaml",
        config_path="$.pipeline._copy_",
        directive="_copy_",
        expected="supported directive",
        actual="_copy_",
        remediation="Use supported phase-2 directives only.",
        details={"reason": "deferred", "path": "$.pipeline"},
    )

    payload = context.to_dict()
    assert payload["code"] == "unsupported_directive"
    assert payload["source_kind"] == "base"
    assert payload["source_path"] == "/tmp/base.yaml"
    assert payload["config_path"] == "$.pipeline._copy_"
    assert payload["directive"] == "_copy_"
    details = payload["details"]
    assert isinstance(details, dict)
    assert details["reason"] == "deferred"
    assert "raw_source_bytes" not in payload

    assert ConfigErrorContext.from_dict(payload) == context


def test_config_load_error_serializes_context_for_machine_inspection() -> None:
    error = ConfigLoadError(
        "unsupported directive",
        context=ConfigErrorContext(
            code="unsupported_directive",
            source_kind="overlay",
            source_order=2,
            source_path="/tmp/overlay.yaml",
            config_path="$.model[0]._copy_",
            directive="_copy_",
            details={"message": "ignored"},
        ),
    )

    payload = error.to_dict()
    assert payload["message"] == "unsupported directive"
    assert payload["context"]["code"] == "unsupported_directive"
    assert payload["context"]["source_order"] == 2
    assert payload["context"]["config_path"] == "$.model[0]._copy_"


def test_config_error_context_rejects_non_plain_details_before_serialization() -> None:
    with pytest.raises(PlainDataError, match="set-like values"):
        ConfigErrorContext(
            code="non_plain_context",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
            details={"bad": {1, 2}},  # type: ignore[dict-item]
        )


def test_config_error_context_rejects_non_mapping_details_before_serialization() -> (
    None
):
    with pytest.raises(TypeError, match="details must be a mapping"):
        ConfigErrorContext(
            code="non_plain_context",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
            details=["not", "a", "mapping"],  # type: ignore[arg-type]
        )


def test_config_include_resolution_error_serializes_structured_context() -> None:
    error = ConfigIncludeResolutionError(
        "cannot resolve include target",
        context=ConfigErrorContext(
            code="target_not_found",
            source_kind="base",
            source_order=0,
            source_path="/tmp/config.yaml",
            config_path="$.model._include_",
            expected="existing regular file",
            actual="missing",
            details={
                "authored_target": "missing.yaml",
                "include_site_path": ["model", "_include_"],
                "candidate_path": "/tmp/model/missing.yaml",
                "target_kind": "explicit_relative",
                "explicit_escape": True,
            },
        ),
    )

    payload = error.to_dict()
    assert payload["context"]["code"] == "target_not_found"
    assert payload["context"]["source_path"] == "/tmp/config.yaml"
    assert payload["context"]["config_path"] == "$.model._include_"
    context_details = payload["context"]["details"]
    assert isinstance(context_details, dict)
    assert context_details["authored_target"] == "missing.yaml"
    assert context_details["candidate_path"] == "/tmp/model/missing.yaml"
    assert context_details["target_kind"] == "explicit_relative"
    assert context_details["explicit_escape"] is True
    assert ConfigErrorContext.from_dict(payload["context"]) == error.context


def test_config_include_expansion_error_serializes_structured_context() -> None:
    error = ConfigIncludeExpansionError(
        "cannot expand include",
        context=ConfigErrorContext(
            code="included_root_not_mapping",
            source_kind="overlay",
            source_order=1,
            source_path="/tmp/overlay.yaml",
            config_path="$.pipeline.model._include_",
            directive="_include_",
            details={
                "include_site_path": ["pipeline", "model", "_include_"],
                "authored_target": "./model.yaml",
                "resolved_path": "/tmp/model.yaml",
                "source_order": 1,
                "target_kind": "explicit_relative",
                "explicit_escape": True,
                "resolved_path_type": "dict",
            },
        ),
    )

    payload = error.to_dict()
    assert payload["context"]["code"] == "included_root_not_mapping"
    assert payload["context"]["source_order"] == 1
    assert payload["context"]["source_path"] == "/tmp/overlay.yaml"
    assert payload["context"]["directive"] == "_include_"
    context_details = payload["context"]["details"]
    assert isinstance(context_details, dict)
    assert context_details["include_site_path"] == ["pipeline", "model", "_include_"]
    assert context_details["resolved_path"] == "/tmp/model.yaml"
    assert ConfigErrorContext.from_dict(payload["context"]) == error.context


def test_config_unsupported_resolver_error_serializes_structured_context() -> None:
    error = ConfigUnsupportedResolverError(
        "unsupported resolver",
        context=ConfigErrorContext(
            code="unsupported_resolver",
            source_kind="base",
            source_order=0,
            source_path="/tmp/config.yaml",
            config_path="$.pipeline.value",
            directive="interpolation",
            expected="oc.env",
            actual="env",
            remediation="Phase 8 only allows oc.env.",
            details={
                "resolver_expression_count": 1,
                "unsupported_resolver": "env",
            },
        ),
    )

    payload = error.to_dict()
    assert payload["context"]["code"] == "unsupported_resolver"
    assert payload["context"]["source_path"] == "/tmp/config.yaml"
    assert payload["context"]["config_path"] == "$.pipeline.value"
    assert payload["context"]["directive"] == "interpolation"
    assert payload["context"]["details"]["unsupported_resolver"] == "env"
    assert ConfigErrorContext.from_dict(payload["context"]) == error.context


def test_config_validation_error_can_carry_structured_context() -> None:
    context = ConfigErrorContext(
        code="invalid_project_schema_boundary",
        source_kind="base",
        source_order=0,
        source_path="/tmp/base.yaml",
        config_path="$.pipeline",
        expected="project-owned key map",
        actual="integer",
        directive="_schema_",
        remediation="Keep schema metadata in external project tooling; composition does not inspect `_schema_`.",
        details={"boundary": "compose"},
    )
    error = ConfigValidationError("Invalid config boundary", context=context)

    payload = error.to_dict()
    assert payload["message"] == "Invalid config boundary"
    assert payload["context"]["code"] == "invalid_project_schema_boundary"
    assert payload["context"]["source_kind"] == "base"
    assert payload["context"]["directive"] == "_schema_"
    assert payload["context"]["details"]["boundary"] == "compose"
    assert ConfigErrorContext.from_dict(payload["context"]) == error.context
