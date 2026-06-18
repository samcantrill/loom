"""Unit tests for CLI error handling."""

from __future__ import annotations

import json

import pytest

from loom.cli.errors import (
    CliError,
    ExitCode,
    UnsupportedCommandError,
    error_payload,
    exit_code_for,
    format_error,
    format_json_error,
    format_text_error,
)
from loom.cli.options import OutputFormat
from loom.errors import ConfigError, ExecutionError, PipelineError


pytestmark = pytest.mark.unit


class StructuredFailure(Exception):
    def to_dict(self) -> dict[str, object]:
        return {
            "message": "structured failure",
            "code": "structured.failure",
            "context": {"path": "pipeline.stages[0]"},
            "hint": "fix it",
            "details": {"value": 1},
            "extra": "preserved",
        }


def test_exit_code_mapping() -> None:
    assert exit_code_for(CliError("failed", exit_code=ExitCode.RUN_STATE)) is ExitCode.RUN_STATE
    assert exit_code_for(ConfigError("bad config")) is ExitCode.CONFIG
    assert exit_code_for(PipelineError("bad pipeline")) is ExitCode.PIPELINE
    assert exit_code_for(ExecutionError("failed run")) is ExitCode.RUN_FAILED
    assert exit_code_for(ValueError("unexpected")) is ExitCode.OPERATION_FAILED
    assert exit_code_for(KeyboardInterrupt()) is ExitCode.INTERRUPTED


def test_structured_error_payload_preserves_fields() -> None:
    payload = error_payload(StructuredFailure())

    assert payload["type"] == "StructuredFailure"
    assert payload["message"] == "structured failure"
    assert payload["code"] == "structured.failure"
    assert payload["context"] == {"path": "pipeline.stages[0]"}
    assert payload["hint"] == "fix it"
    assert payload["details"] == {"value": 1, "extra": "preserved"}


def test_traceback_details_are_optional() -> None:
    try:
        raise StructuredFailure()
    except StructuredFailure as exc:
        without_traceback = error_payload(exc)
        with_traceback = error_payload(exc, traceback_enabled=True)

    without_details = without_traceback["details"]
    with_details = with_traceback["details"]
    assert isinstance(without_details, dict)
    assert isinstance(with_details, dict)
    assert "traceback" not in without_details
    traceback_lines = with_details["traceback"]
    assert isinstance(traceback_lines, list)
    assert "StructuredFailure" in "".join(str(line) for line in traceback_lines)


def test_error_formatting_supports_text_and_json() -> None:
    error = UnsupportedCommandError("validate")

    assert format_text_error(error, traceback_enabled=False).startswith("error: `loom validate`")

    rendered = format_json_error(error, traceback_enabled=False)
    payload = json.loads(rendered)
    assert payload["schema_version"] == "loom.cli.error.v2"
    assert payload["ok"] is False
    assert payload["warnings"] == []
    assert payload["error"]["code"] == "cli.unsupported_command"
    assert payload["error"]["context"] == {"command": "validate"}

    assert json.loads(
        format_error(error, traceback_enabled=False, output_format=OutputFormat.JSON)
    ) == payload
