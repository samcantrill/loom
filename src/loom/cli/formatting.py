"""Shared CLI text and JSON formatting helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast

from loom.cli.results import (
    CliWarning,
    PlanCliResult,
    PlainCliData,
    RunCliResult,
    SlurmDryRunCliResult,
    ValidationCliResult,
    to_plain_cli_data,
)

CLI_ERROR_SCHEMA_VERSION = "loom.cli.error.v2"
CLI_RESULT_SCHEMA_VERSION = "loom.cli.result.v2"


def _warning_to_dict(
    warning: Mapping[str, object] | CliWarning,
) -> dict[str, PlainCliData]:
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
        if not isinstance(explanation_reasons, Sequence) or isinstance(
            explanation_reasons, str
        ):
            explanation_reasons = ()
        for reason in explanation_reasons:
            if not isinstance(reason, Mapping):
                continue
            code = str(reason.get("code", "reason"))
            message = str(reason.get("message", ""))
            lines.append(f"  {code}: {message}")

    return "\n".join(lines)


def format_preflight_text(result: object, *, config_path: object) -> str:
    """Format a concise preflight result."""

    status = _enum_value(getattr(result, "status"))
    prefix = {
        "PASS": "OK",
        "WARN": "WARN",
        "FAIL": "FAILED",
        "SKIP": "SKIP",
    }.get(status, status)
    lines = [f"{prefix} preflight {config_path}: {status}"]
    for check in getattr(result, "checks", ()):
        check_status = _enum_value(getattr(check, "status"))
        check_id = str(getattr(check, "check_id"))
        message = str(getattr(check, "message"))
        lines.append(f"{check_status} {check_id}: {message}")
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
        for label, key in (
            ("attempt", "attempt"),
            ("executor", "executor"),
            ("exit_code", "exit_code"),
            ("signal", "signal"),
            ("failure_record", "failure_path"),
            ("stdout", "stdout_path"),
            ("stderr", "stderr_path"),
            ("traceback", "traceback_path"),
        ):
            value = result.failure_summary.get(key)
            if value is not None:
                lines.append(f"  {label}: {value}")
    return "\n".join(lines)


def format_slurm_dry_run_text(result: SlurmDryRunCliResult) -> str:
    """Format a concise SLURM dry-run artifact summary."""

    suffix = (
        "1 script" if result.script_count == 1 else f"{result.script_count} scripts"
    )
    lines = [
        f"OK slurm dry-run {result.run_uri}: {result.mode}",
        f"planning_id: {result.planning_id}",
        f"manifest: {result.manifest_path}",
        f"plan: {result.plan_path}",
        f"scripts: {suffix}"
        + ("" if result.script_directory is None else f" in {result.script_directory}"),
        f"logs: {_slurm_log_summary(result.log_paths)}",
        f"jobs: {result.job_count}",
        f"dependencies: {result.dependency_count}",
    ]
    if result.preflight_warnings:
        warning_suffix = (
            "1 warning"
            if len(result.preflight_warnings) == 1
            else f"{len(result.preflight_warnings)} warnings"
        )
        lines.append(f"warnings: {warning_suffix}")
        for warning in result.preflight_warnings:
            code = str(warning.get("code", "warning"))
            message = str(warning.get("message", ""))
            lines.append(f"  {code}: {message}")
    return "\n".join(lines)


def _slurm_log_summary(log_paths: Sequence[Mapping[str, object]]) -> str:
    if not log_paths:
        return "none"
    first = log_paths[0]
    stdout = str(first.get("stdout_relative_path", ""))
    stderr = str(first.get("stderr_relative_path", ""))
    if len(log_paths) == 1:
        return f"stdout={stdout}, stderr={stderr}"
    parent = stdout.rsplit("/", 1)[0] if "/" in stdout else stdout
    return f"{len(log_paths)} job log pairs under {parent}"


def format_stage_worker_text(result: object) -> str:
    """Format one direct worker result."""

    status = _enum_value(getattr(result, "status"))
    prefix = "OK" if status == "SUCCEEDED" else "FAILED"
    run_uri = str(getattr(result, "run_uri"))
    stage_name = str(getattr(result, "stage_name"))
    attempt = int(getattr(result, "attempt"))
    lines = [f"{prefix} stage run {run_uri} {stage_name} attempt {attempt}: {status}"]
    failure = getattr(result, "failure")
    if failure is not None:
        message = str(getattr(failure, "message", ""))
        failure_type = str(getattr(failure, "failure_type", "failure"))
        lines.append(f"failure {failure_type}: {message}")
    return "\n".join(lines)


def format_stage_job_text(result: object) -> str:
    """Format one self-finalizing stage-job result."""

    status = _enum_value(getattr(result, "status"))
    run_status = _enum_value(getattr(result, "run_status"))
    prefix = "OK" if status == "SUCCEEDED" else "FAILED"
    run_uri = str(getattr(result, "run_uri"))
    stage_name = str(getattr(result, "stage_name"))
    attempt = int(getattr(result, "attempt"))
    lines = [
        f"{prefix} stage-job run {run_uri} {stage_name} attempt {attempt}: {status}",
        f"run: {run_status}",
    ]
    failure = getattr(result, "failure")
    if failure is not None:
        message = str(getattr(failure, "message", ""))
        failure_type = str(getattr(failure, "failure_type", "failure"))
        lines.append(f"failure {failure_type}: {message}")
    return "\n".join(lines)


def format_prepared_run_continue_text(error: object) -> str:
    """Format a prepared-run continuation failure."""

    return f"FAILED prepared-run continue: {error}"


def format_status_text(result: object) -> str:
    """Format a concise run status summary."""

    run_uri = str(getattr(result, "run_uri"))
    status = getattr(result, "status")
    status_text = "<unknown>" if status is None else str(status)
    lines = [f"status {run_uri}: {status_text}"]
    submitted_operations = cast(
        Sequence[object], getattr(result, "submitted_operations", ())
    )
    if submitted_operations:
        lines.append("submitted operations:")
        for operation in submitted_operations:
            active_suffix = " active" if bool(getattr(operation, "active")) else ""
            lines.append(
                "  "
                f"{getattr(operation, 'submission_id')}: "
                f"{getattr(operation, 'backend')}/{getattr(operation, 'mode')} "
                f"{getattr(operation, 'state')}{active_suffix} "
                f"manifest={getattr(operation, 'manifest_relative_path')}"
            )
    for stage in getattr(result, "stages", ()):
        stage_name = str(getattr(stage, "stage_name"))
        stage_status = getattr(stage, "status")
        stage_status_text = "<missing>" if stage_status is None else str(stage_status)
        output_count = int(getattr(stage, "output_count"))
        suffix = (
            f"{output_count} output" if output_count == 1 else f"{output_count} outputs"
        )
        lines.append(f"{stage_name}: {stage_status_text} ({suffix})")
        failure = getattr(stage, "failure")
        if isinstance(failure, Mapping):
            message = failure.get("message")
            if message:
                lines.append(f"  failure: {message}")
    lines.append(f"artifacts: {getattr(result, 'artifact_count')}")
    return "\n".join(lines)


def format_logs_text(result: object) -> str:
    """Format bounded stage log content."""

    run_uri = str(getattr(result, "run_uri"))
    stage_name = str(getattr(result, "stage_name"))
    lines = [f"logs {run_uri} {stage_name}:"]
    for stream in getattr(result, "streams", ()):
        stream_name = str(getattr(stream, "stream"))
        path = str(getattr(stream, "path"))
        available = bool(getattr(stream, "available"))
        lines.append(f"{stream_name}: {path}")
        content = getattr(stream, "content", None)
        if content is not None:
            lines.append(str(content).rstrip("\n"))
        elif not available:
            lines.append("  <missing>")
    return "\n".join(lines)


def format_artifacts_list_text(result: object) -> str:
    """Format artifact metadata summaries."""

    run_uri = str(getattr(result, "run_uri"))
    artifact_count = int(getattr(result, "artifact_count"))
    suffix = "1 artifact" if artifact_count == 1 else f"{artifact_count} artifacts"
    lines = [f"artifacts {run_uri}: {suffix}"]
    for artifact in getattr(result, "artifacts", ()):
        key = str(getattr(artifact, "key"))
        artifact_id = str(getattr(artifact, "artifact_id"))
        artifact_type = str(getattr(artifact, "artifact_type"))
        uri = str(getattr(artifact, "uri"))
        lines.append(f"{key}: {artifact_id} ({artifact_type}) {uri}")
    return "\n".join(lines)


def format_artifact_show_text(result: object) -> str:
    """Format one artifact metadata summary."""

    artifact = getattr(result, "artifact")
    key = str(getattr(artifact, "key"))
    artifact_id = str(getattr(artifact, "artifact_id"))
    lines = [f"artifact {artifact_id} ({key})"]
    lines.append(f"uri: {getattr(artifact, 'uri')}")
    lines.append(f"type: {getattr(artifact, 'artifact_type')}")
    codec_key = getattr(artifact, "codec_key")
    if codec_key is not None:
        lines.append(f"codec: {codec_key}")
    checksum = getattr(artifact, "checksum")
    if checksum is not None:
        lines.append(f"checksum: {checksum}")
    producer_stage = getattr(artifact, "producer_stage")
    if producer_stage is not None:
        lines.append(f"producer: {producer_stage}")
    metadata = getattr(artifact, "metadata")
    if isinstance(metadata, Mapping) and metadata:
        keys = ", ".join(sorted(str(key) for key in metadata))
        lines.append(f"metadata: {keys}")
    provenance = getattr(result, "stage_provenance")
    if isinstance(provenance, Mapping) and provenance:
        keys = ", ".join(sorted(str(key) for key in provenance))
        lines.append(f"stage_provenance: {keys}")
    elif provenance is None:
        lines.append("stage_provenance: <missing>")
    return "\n".join(lines)


def _enum_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value)


__all__ = [
    "CLI_ERROR_SCHEMA_VERSION",
    "CLI_RESULT_SCHEMA_VERSION",
    "format_artifact_show_text",
    "format_artifacts_list_text",
    "format_json_envelope",
    "format_plan_text",
    "format_preflight_text",
    "format_slurm_dry_run_text",
    "format_stage_worker_text",
    "format_logs_text",
    "format_run_text",
    "format_status_text",
    "format_validation_text",
]
