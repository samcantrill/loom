"""Import-light entry point for the loom CLI."""

from __future__ import annotations

import argparse
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Sequence, TextIO

from loom import __version__
from loom.cli.errors import ExitCode, UnsupportedCommandError, exit_code_for, format_error
from loom.cli.options import OutputFormat, output_format_from_namespace


def _unsupported_command(namespace: argparse.Namespace) -> int:
    command = getattr(namespace, "command", "<unknown>")
    raise UnsupportedCommandError(str(command))


def _add_common_command_options(parser: argparse.ArgumentParser) -> None:
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


def _add_config_options(parser: argparse.ArgumentParser) -> None:
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


def _add_selector_options(parser: argparse.ArgumentParser) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI argument parser."""

    parser = argparse.ArgumentParser(prog="loom", description="Compose, run, and trace research pipelines.")
    parser.add_argument("--version", action="version", version=f"loom {__version__}")
    parser.add_argument("--traceback", action="store_true", help="show traceback details for errors")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    from loom.cli import validate as validate_command

    validate_command.register_subparser(subparsers)

    plan_parser = subparsers.add_parser("plan", help="plan a pipeline run")
    _add_config_options(plan_parser)
    _add_selector_options(plan_parser)
    plan_parser.add_argument("--run-uri", metavar="URI", help="explicit run URI")
    plan_parser.add_argument("--resume", action="store_true", help="resume an existing run")
    plan_parser.add_argument("--explain", dest="explain_stage", metavar="STAGE", help="explain a planned stage")
    _add_common_command_options(plan_parser)
    plan_parser.set_defaults(handler=_unsupported_command)

    run_parser = subparsers.add_parser("run", help="run a pipeline")
    _add_config_options(run_parser)
    _add_selector_options(run_parser)
    run_parser.add_argument("--run-uri", metavar="URI", help="explicit run URI")
    run_parser.add_argument("--executor", default="local", metavar="NAME", help="executor name")
    run_parser.add_argument("--resume", action="store_true", help="resume an existing run")
    run_parser.add_argument("--dry-run", action="store_true", help="plan without executing")
    _add_common_command_options(run_parser)
    run_parser.set_defaults(handler=_unsupported_command)

    return parser


def _dispatch(namespace: argparse.Namespace) -> int:
    handler = getattr(namespace, "handler", None)
    if handler is None:
        raise UnsupportedCommandError(str(getattr(namespace, "command", "<missing>")))
    return int(handler(namespace))


def _run(argv: Sequence[str] | None) -> int:
    parser = build_parser()
    try:
        namespace = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else int(ExitCode.OPERATION_FAILED)

    if getattr(namespace, "command", None) is None:
        parser.print_help()
        return int(ExitCode.SUCCESS)

    try:
        return _dispatch(namespace)
    except KeyboardInterrupt as exc:
        sys.stderr.write("interrupted\n")
        return int(exit_code_for(exc))
    except Exception as exc:
        output_format = output_format_from_namespace(namespace)
        traceback_enabled = bool(getattr(namespace, "traceback", False))
        warnings = tuple(getattr(exc, "cli_warnings", ()) or ())
        formatted = format_error(
            exc,
            traceback_enabled=traceback_enabled,
            output_format=output_format,
            warnings=warnings,
        )
        if output_format is OutputFormat.JSON:
            sys.stdout.write(formatted)
            if traceback_enabled:
                sys.stderr.write(format_error(exc, traceback_enabled=True, output_format=OutputFormat.TEXT))
        else:
            sys.stderr.write(formatted)
        return int(exit_code_for(exc))


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the CLI and return an integer exit code."""

    if stdout is None and stderr is None:
        return _run(argv)
    if stdout is None:
        with redirect_stderr(stderr):
            return _run(argv)
    if stderr is None:
        with redirect_stdout(stdout):
            return _run(argv)
    with redirect_stdout(stdout), redirect_stderr(stderr):
        return _run(argv)


__all__ = ["build_parser", "main"]
