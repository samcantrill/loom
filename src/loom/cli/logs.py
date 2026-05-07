"""Implementation for ``loom logs``."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope, format_logs_text
from loom.cli.options import OutputFormat, output_format_from_namespace

if TYPE_CHECKING:
    from loom.diagnostics.inspection import StageLogsSummary


LOGS_RESULT_SCHEMA_VERSION = "loom.cli.logs.v3"
DEFAULT_LOG_TAIL_LINES = 100


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the logs subcommand."""

    parser = subparsers.add_parser("logs", help="inspect local stage logs")
    parser.add_argument("run_uri", metavar="RUN_URI", help="run URI to inspect")
    parser.add_argument("stage", metavar="STAGE", help="stage name to inspect")
    parser.add_argument(
        "--stream",
        choices=["stdout", "stderr", "both"],
        default="both",
        help="log stream to display",
    )
    parser.add_argument(
        "--tail",
        type=_positive_int,
        default=DEFAULT_LOG_TAIL_LINES,
        metavar="N",
        help="maximum lines to display per stream",
    )
    parser.add_argument("--paths", action="store_true", help="show log paths without content")
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
    """Handle ``loom logs``."""

    output_format = output_format_from_namespace(namespace)
    result = build_logs_result(
        str(namespace.run_uri),
        str(namespace.stage),
        stream=str(namespace.stream),
        tail=int(namespace.tail),
        paths_only=bool(namespace.paths),
    )
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=LOGS_RESULT_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_logs_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def build_logs_result(
    run_uri: str,
    stage_name: str,
    *,
    stream: str,
    tail: int,
    paths_only: bool,
) -> "StageLogsSummary":
    """Build a bounded stage logs summary."""

    try:
        from loom.diagnostics.inspection import inspect_stage_logs

        streams = ("stdout", "stderr") if stream == "both" else (stream,)
        return inspect_stage_logs(
            run_uri,
            stage_name,
            streams=streams,
            tail=tail,
            paths_only=paths_only,
        )
    except Exception as exc:
        raise _run_state_error(exc) from exc


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--tail must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--tail must be a positive integer")
    return parsed


def _run_state_error(error: BaseException) -> CliError:
    return CliError(
        str(error),
        code="cli.logs.run_state_error",
        context={"error_type": type(error).__name__},
        exit_code=ExitCode.RUN_STATE,
    )


__all__ = ["LOGS_RESULT_SCHEMA_VERSION", "build_logs_result", "handle", "register_subparser"]
