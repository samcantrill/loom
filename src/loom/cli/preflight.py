"""Implementation for ``loom preflight``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope, format_preflight_text
from loom.cli.options import (
    ConfigCliOptions,
    OutputFormat,
    PreflightCliOptions,
    output_format_from_namespace,
)

if TYPE_CHECKING:
    from loom.diagnostics import PreflightRequest, PreflightResult


PREFLIGHT_RESULT_SCHEMA_VERSION = "loom.cli.preflight.v3"


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the preflight subcommand."""

    parser = subparsers.add_parser("preflight", help="run local preflight diagnostics")
    parser.add_argument("config", metavar="CONFIG", help="pipeline config path")
    parser.add_argument(
        "--overlay",
        action="append",
        default=None,
        metavar="PATH",
        help="additional config overlay path",
    )
    parser.add_argument(
        "--set",
        dest="override",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="config override expression",
    )
    parser.add_argument("--run-uri", metavar="URI", help="run URI for run-path checks")
    parser.add_argument(
        "--check",
        dest="check_group",
        action="append",
        default=None,
        metavar="GROUP",
        help="preflight check group to run; may be repeated",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat preflight warnings as failures",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=[format.value for format in OutputFormat],
        default=OutputFormat.TEXT.value,
        help="output format",
    )
    parser.add_argument(
        "--traceback",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show traceback details for errors",
    )
    parser.set_defaults(handler=handle)


def handle(namespace: argparse.Namespace) -> int:
    """Handle ``loom preflight``."""

    config_options = ConfigCliOptions.from_namespace(namespace)
    preflight_options = PreflightCliOptions.from_namespace(namespace)
    output_format = output_format_from_namespace(namespace)

    result = build_preflight_result(
        config_options=config_options,
        preflight_options=preflight_options,
    )
    exit_code = exit_code_for_preflight(result, strict=preflight_options.strict)
    ok = exit_code is ExitCode.SUCCESS
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=PREFLIGHT_RESULT_SCHEMA_VERSION,
                ok=ok,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_preflight_text(result, config_path=config_options.config_path) + "\n")
    return int(exit_code)


def build_preflight_result(
    *,
    config_options: ConfigCliOptions,
    preflight_options: PreflightCliOptions,
) -> "PreflightResult":
    """Run preflight diagnostics and return the diagnostics result."""

    from loom.diagnostics import PreflightError

    try:
        request = _build_preflight_request(
            config_options=config_options,
            preflight_options=preflight_options,
        )
        return _run_diagnostics_preflight(request)
    except PreflightError as exc:
        raise _preflight_usage_error(exc) from exc


def exit_code_for_preflight(result: "PreflightResult", *, strict: bool) -> ExitCode:
    """Return the process exit code for a preflight result."""

    status = _status_value(result)
    if status == "FAIL":
        return ExitCode.PIPELINE
    if status == "WARN" and strict:
        return ExitCode.PIPELINE
    return ExitCode.SUCCESS


def _build_preflight_request(
    *,
    config_options: ConfigCliOptions,
    preflight_options: PreflightCliOptions,
) -> "PreflightRequest":
    from loom.diagnostics import PreflightRequest

    groups = preflight_options.check_groups if preflight_options.check_groups else None
    return PreflightRequest(
        config_path=config_options.config_path,
        groups=groups,
        run_uri=preflight_options.run_uri,
        cwd=Path.cwd(),
        overlays=config_options.overlays,
        overrides=config_options.overrides,
    )


def _run_diagnostics_preflight(request: "PreflightRequest") -> "PreflightResult":
    from loom.diagnostics import run_preflight

    return run_preflight(request)


def _preflight_usage_error(error: BaseException) -> CliError:
    return CliError(
        str(error),
        code="cli.preflight.invalid_check_group",
        hint="Use --check with a known local preflight group.",
        context={"error": str(error)},
        exit_code=ExitCode.USAGE,
    )


def _status_value(result: "PreflightResult") -> str:
    return str(getattr(getattr(result, "status"), "value", getattr(result, "status")))


__all__ = [
    "PREFLIGHT_RESULT_SCHEMA_VERSION",
    "build_preflight_result",
    "exit_code_for_preflight",
    "handle",
    "register_subparser",
]
