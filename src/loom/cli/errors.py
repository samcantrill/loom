"""CLI error normalization, formatting, and exit codes."""

from __future__ import annotations

import traceback
from enum import IntEnum
from typing import Mapping

from loom.cli.formatting import CLI_ERROR_SCHEMA_VERSION, format_json_envelope
from loom.cli.options import OutputFormat
from loom.cli.results import CliWarning, PlainCliData, to_plain_cli_data
from loom.errors import ConfigError, ExecutionError, LoomError, PipelineError


class ExitCode(IntEnum):
    """Conventional CLI exit codes."""

    SUCCESS = 0
    OPERATION_FAILED = 1
    USAGE = 2
    CONFIG = 3
    PIPELINE = 4
    RUN_FAILED = 5
    RUN_STATE = 6
    EXECUTOR = 7
    INTERRUPTED = 130


class CliError(LoomError):
    """Base class for CLI-owned operational errors."""

    code = "cli.error"
    exit_code = ExitCode.OPERATION_FAILED

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        hint: str | None = None,
        context: Mapping[str, object] | None = None,
        details: Mapping[str, object] | None = None,
        exit_code: ExitCode | int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code if code is not None else self.code
        self.hint = hint
        self.context = dict(context or {})
        self.details = dict(details or {})
        self.exit_code = ExitCode(exit_code) if exit_code is not None else self.exit_code

    def to_dict(self) -> dict[str, object]:
        """Return a structured error payload."""

        return {
            "message": str(self),
            "code": self.code,
            "context": self.context,
            "hint": self.hint,
            "details": self.details,
        }


class UnsupportedCommandError(CliError):
    """Error raised for registered commands not implemented in this phase."""

    def __init__(self, command: str) -> None:
        super().__init__(
            f"`loom {command}` is not implemented in this build.",
            code="cli.unsupported_command",
            hint="This command is registered by the CLI foundation and implemented in a later phase.",
            context={"command": command},
        )


def exit_code_for(error: BaseException) -> ExitCode:
    """Map an exception to a CLI exit code."""

    if isinstance(error, KeyboardInterrupt):
        return ExitCode.INTERRUPTED
    if isinstance(error, CliError):
        return error.exit_code
    if isinstance(error, ConfigError):
        return ExitCode.CONFIG
    if isinstance(error, PipelineError):
        return ExitCode.PIPELINE
    if isinstance(error, ExecutionError):
        return ExitCode.RUN_FAILED
    return ExitCode.OPERATION_FAILED


def _structured_payload(error: BaseException) -> dict[str, PlainCliData]:
    payload: dict[str, object] = {}
    to_dict = getattr(error, "to_dict", None)
    if callable(to_dict):
        raw_payload = to_dict()
        if isinstance(raw_payload, Mapping):
            payload.update(dict(raw_payload))

    message = payload.get("message", str(error))
    context = to_plain_cli_data(payload.get("context", {}))
    details = to_plain_cli_data(payload.get("details", {}))
    if not isinstance(context, dict):
        context = {"value": context}
    if not isinstance(details, dict):
        details = {"value": details}

    details_payload: dict[str, PlainCliData] = dict(details)
    error_payload: dict[str, PlainCliData] = {
        "type": type(error).__name__,
        "message": str(message),
        "code": str(payload.get("code", _default_error_code(error))),
        "context": context,
        "hint": _optional_str(payload.get("hint")),
        "details": details_payload,
    }

    for key, value in payload.items():
        if key not in {"message", "code", "context", "hint", "details"}:
            details_payload[str(key)] = to_plain_cli_data(value)

    return error_payload


def _default_error_code(error: BaseException) -> str:
    if isinstance(error, CliError):
        return error.code
    if isinstance(error, ConfigError):
        return "config.error"
    if isinstance(error, PipelineError):
        return "pipeline.error"
    if isinstance(error, ExecutionError):
        return "execution.error"
    if isinstance(error, LoomError):
        return "loom.error"
    return "internal.error"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def error_payload(
    error: BaseException,
    *,
    traceback_enabled: bool = False,
) -> dict[str, PlainCliData]:
    """Return the CLI JSON payload for an error."""

    payload = _structured_payload(error)
    if traceback_enabled:
        details = payload["details"]
        if not isinstance(details, dict):
            details = {"value": details}
            payload["details"] = details
        details["traceback"] = list(traceback.format_exception(type(error), error, error.__traceback__))
    return payload


def format_text_error(error: BaseException, *, traceback_enabled: bool) -> str:
    """Format an error for text mode."""

    if traceback_enabled:
        return "".join(traceback.format_exception(type(error), error, error.__traceback__))

    if isinstance(error, LoomError):
        return f"error: {error}\n"
    return f"internal error: {error}. Re-run with --traceback for details.\n"


def format_json_error(
    error: BaseException,
    *,
    traceback_enabled: bool,
    warnings: tuple[CliWarning | Mapping[str, object], ...] = (),
) -> str:
    """Format an error JSON envelope."""

    return format_json_envelope(
        schema_version=CLI_ERROR_SCHEMA_VERSION,
        ok=False,
        warnings=warnings,
        payload_name="error",
        payload=error_payload(error, traceback_enabled=traceback_enabled),
    )


def format_error(
    error: BaseException,
    *,
    traceback_enabled: bool,
    output_format: OutputFormat,
) -> str:
    """Format an error for the requested output format."""

    if output_format is OutputFormat.JSON:
        return format_json_error(error, traceback_enabled=traceback_enabled)
    return format_text_error(error, traceback_enabled=traceback_enabled)


__all__ = [
    "CliError",
    "ExitCode",
    "UnsupportedCommandError",
    "error_payload",
    "exit_code_for",
    "format_error",
    "format_json_error",
    "format_text_error",
]
