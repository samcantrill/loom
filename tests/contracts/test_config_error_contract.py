"""Contract tests for config structured error context payloads."""

import pytest

from loom.config.errors import ConfigErrorContext, ConfigLoadError
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


def test_config_error_context_rejects_non_mapping_details_before_serialization() -> None:
    with pytest.raises(TypeError, match="details must be a mapping"):
        ConfigErrorContext(
            code="non_plain_context",
            source_kind="base",
            source_order=0,
            source_path="/tmp/base.yaml",
            details=["not", "a", "mapping"],  # type: ignore[arg-type]
        )
