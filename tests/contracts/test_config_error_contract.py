"""Contract tests for config structured error context payloads."""

from loom.config.errors import ConfigErrorContext, ConfigLoadError


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
