"""Shared CLI text and JSON formatting helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from loom.cli.results import (
    CliWarning,
    PlanCliResult,
    PlainCliData,
    RunCliResult,
    ValidationCliResult,
    to_plain_cli_data,
)

CLI_ERROR_SCHEMA_VERSION = "loom.cli.error.v2"
CLI_RESULT_SCHEMA_VERSION = "loom.cli.result.v2"


def _warning_to_dict(warning: Mapping[str, object] | CliWarning) -> dict[str, PlainCliData]:
    if isinstance(warning, CliWarning):
        return warning.to_dict()

    code = warning.get("code", "warning")
    message = warning.get("message", "")
    details = to_plain_cli_data(warning.get("details", {}))
    if not isinstance(details, dict):
        details = {}
    return {
        "code": str(code),
        "message": str(message),
        "details": details,
    }


def format_json_envelope(
    *,
    schema_version: str,
    ok: bool,
    warnings: Sequence[Mapping[str, object] | CliWarning],
    payload_name: str,
    payload: Mapping[str, object],
) -> str:
    """Format a stable JSON envelope with top-level warnings."""

    if payload_name not in {"result", "error"}:
        raise ValueError(f"Unsupported JSON envelope payload name: {payload_name!r}")

    envelope: dict[str, PlainCliData] = {
        "schema_version": schema_version,
        "ok": ok,
        "warnings": [_warning_to_dict(warning) for warning in warnings],
        payload_name: to_plain_cli_data(dict(payload)),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n"


def format_validation_text(result: ValidationCliResult) -> str:
    """Format a concise validation result."""

    if result.stage_count is None:
        stage_summary = "unknown stages"
    elif result.stage_count == 1:
        stage_summary = "1 stage"
    else:
        stage_summary = f"{result.stage_count} stages"
    return f"OK validate {result.config_path}: {stage_summary}"


def format_plan_text(result: PlanCliResult) -> str:
    """Format a concise plan result."""

    action_count = len(result.stage_actions)
    suffix = "1 stage action" if action_count == 1 else f"{action_count} stage actions"
    if result.run_uri is None:
        return f"OK plan {result.config_path}: {suffix}"
    return f"OK plan {result.config_path}: {suffix}, run_uri={result.run_uri}"


def format_run_text(result: RunCliResult) -> str:
    """Format a concise run result."""

    return f"OK run {result.run_uri}: {result.status}"


__all__ = [
    "CLI_ERROR_SCHEMA_VERSION",
    "CLI_RESULT_SCHEMA_VERSION",
    "format_json_envelope",
    "format_plan_text",
    "format_run_text",
    "format_validation_text",
]
