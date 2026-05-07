"""Implementation for ``loom status``."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope, format_status_text
from loom.cli.options import OutputFormat, output_format_from_namespace

if TYPE_CHECKING:
    from loom.diagnostics.inspection import RunStatusSummary


STATUS_RESULT_SCHEMA_VERSION = "loom.cli.status.v3"


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the status subcommand."""

    parser = subparsers.add_parser("status", help="inspect a local run")
    parser.add_argument("run_uri", metavar="RUN_URI", help="run URI to inspect")
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
    """Handle ``loom status``."""

    output_format = output_format_from_namespace(namespace)
    result = build_status_result(str(namespace.run_uri))
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=STATUS_RESULT_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_status_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def build_status_result(run_uri: str) -> "RunStatusSummary":
    """Build a run status summary."""

    try:
        from loom.diagnostics.inspection import inspect_run_status

        return inspect_run_status(run_uri)
    except Exception as exc:
        raise _run_state_error(exc) from exc


def _run_state_error(error: BaseException) -> CliError:
    return CliError(
        str(error),
        code="cli.status.run_state_error",
        context={"error_type": type(error).__name__},
        exit_code=ExitCode.RUN_STATE,
    )


__all__ = ["STATUS_RESULT_SCHEMA_VERSION", "build_status_result", "handle", "register_subparser"]
