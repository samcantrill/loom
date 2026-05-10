"""Implementation for ``loom preflight``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loom.cli.authority import add_authority_options, authority_config_from_namespace
from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope, format_preflight_text
from loom.cli.options import (
    ConfigCliOptions,
    OutputFormat,
    PreflightCliOptions,
    SelectorCliOptions,
    output_format_from_namespace,
)

if TYPE_CHECKING:
    from loom.diagnostics import PreflightRequest, PreflightResult
    from loom.pipeline.stores import AuthorityConfig


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
        "--profile",
        dest="runtime_profile",
        metavar="NAME",
        help="runtime profile to select",
    )
    parser.add_argument(
        "--executor",
        dest="runtime_executor",
        default=None,
        metavar="NAME",
        help="executor name",
    )
    parser.add_argument("--dry-run", action="store_true", help="mark runtime options as dry-run")
    parser.add_argument("--resume", action="store_true", help="mark runtime options as resume")
    parser.add_argument("--from-stage", metavar="STAGE", help="start at a stage")
    parser.add_argument(
        "--only-stage",
        action="append",
        default=None,
        metavar="STAGE",
        help="include only a selected stage",
    )
    parser.add_argument(
        "--force-stage",
        action="append",
        default=None,
        metavar="STAGE",
        help="force a selected stage",
    )
    parser.add_argument(
        "--skip-stage",
        action="append",
        default=None,
        metavar="STAGE",
        help="skip a selected stage",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="runtime tag; may be repeated",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=None,
        metavar="TEXT",
        help="runtime note; may be repeated",
    )
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
    add_authority_options(parser)
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
    selector_options = SelectorCliOptions.from_namespace(namespace)
    output_format = output_format_from_namespace(namespace)

    result = build_preflight_result(
        config_options=config_options,
        preflight_options=preflight_options,
        selector_options=selector_options,
        authority_config=authority_config_from_namespace(namespace),
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
    selector_options: SelectorCliOptions | None = None,
    authority_config: "AuthorityConfig | None" = None,
) -> "PreflightResult":
    """Run preflight diagnostics and return the diagnostics result."""

    from loom.diagnostics import PreflightError

    try:
        request = _build_preflight_request(
            config_options=config_options,
            preflight_options=preflight_options,
            selector_options=selector_options,
            authority_config=authority_config,
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
    selector_options: SelectorCliOptions | None,
    authority_config: "AuthorityConfig | None",
) -> "PreflightRequest":
    from loom.diagnostics import PreflightRequest

    groups = preflight_options.check_groups if preflight_options.check_groups else None
    runtime_source = preflight_options.to_runtime_source(selectors=selector_options)
    return PreflightRequest(
        config_path=config_options.config_path,
        groups=groups,
        run_uri=preflight_options.run_uri,
        cwd=Path.cwd(),
        overlays=config_options.overlays,
        overrides=config_options.overrides,
        selectors=None if selector_options is None else selector_options.to_runtime_source(),
        runtime_options=runtime_source or None,
        authority_config=authority_config,
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
