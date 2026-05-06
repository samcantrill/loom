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
    lines: list[str]
    if result.run_uri is None:
        lines = [f"OK plan {result.config_path}: {suffix}"]
    else:
        lines = [f"OK plan {result.config_path}: {suffix}, run_uri={result.run_uri}"]

    for stage_action in result.stage_actions:
        stage_name = str(stage_action.get("stage", "<unknown>"))
        action = str(stage_action.get("action", "<unknown>"))
        reason_codes = stage_action.get("reason_codes", ())
        if isinstance(reason_codes, Sequence) and not isinstance(reason_codes, str):
            reasons = ", ".join(str(code) for code in reason_codes) or "NO_REASONS"
        else:
            reasons = str(reason_codes) if reason_codes else "NO_REASONS"
        lines.append(f"{stage_name}: {action} [{reasons}]")

    if result.explanation is not None:
        stage_name = str(result.explanation.get("stage", "<unknown>"))
        lines.append(f"explain {stage_name}:")
        explanation_reasons = result.explanation.get("reasons", ())
        if not isinstance(explanation_reasons, Sequence) or isinstance(explanation_reasons, str):
            explanation_reasons = ()
        for reason in explanation_reasons:
            if not isinstance(reason, Mapping):
                continue
            code = str(reason.get("code", "reason"))
            message = str(reason.get("message", ""))
            lines.append(f"  {code}: {message}")

    return "\n".join(lines)


def format_run_text(result: RunCliResult) -> str:
    """Format a concise run result."""

    prefix = "OK" if result.status == "SUCCEEDED" else "FAILED"
    lines = [f"{prefix} run {result.run_uri}: {result.status}"]
    for stage in result.stage_summaries:
        stage_name = str(stage.get("stage", "<unknown>"))
        action = str(stage.get("action", "<unknown>"))
        status = str(stage.get("status", "<none>"))
        lines.append(f"{stage_name}: {action} -> {status}")
    if result.failure_summary is not None:
        stage_name = result.failure_summary.get("stage", "<unknown>")
        message = result.failure_summary.get("message", "")
        lines.append(f"failure {stage_name}: {message}")
    return "\n".join(lines)


__all__ = [
    "CLI_ERROR_SCHEMA_VERSION",
    "CLI_RESULT_SCHEMA_VERSION",
    "format_json_envelope",
    "format_plan_text",
    "format_run_text",
    "format_validation_text",
]
