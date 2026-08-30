"""Implementation for ``loom inspect-run``."""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.cli.options import OutputFormat, output_format_from_namespace

if TYPE_CHECKING:
    from loom.diagnostics import RunInspectionResponse

INSPECT_RUN_RESULT_SCHEMA_VERSION = "loom.cli.inspect_run.v1"


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "inspect-run", help="inspect one run without reading content"
    )
    parser.add_argument(
        "run_uri", metavar="RUN_URI", help="canonical run URI to inspect"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--direct", action="store_true", help="inspect local owners directly"
    )
    source.add_argument(
        "--endpoint", metavar="SOCKET", help="owner-only local daemon socket"
    )
    parser.add_argument(
        "--queue-config",
        metavar="CONFIG",
        help="optional direct-only queue configuration",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=[item.value for item in OutputFormat],
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
    if namespace.endpoint is not None and namespace.queue_config is not None:
        raise CliError(
            "--queue-config is only valid with --direct",
            code="cli.inspect_run.invalid_source",
            exit_code=ExitCode.CONFIG,
        )
    result = build_inspect_run_result(
        str(namespace.run_uri), endpoint=namespace.endpoint, queue_config=namespace.queue_config
    )
    if output_format_from_namespace(namespace) is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=INSPECT_RUN_RESULT_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_inspect_run_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def build_inspect_run_result(
    run_uri: str, *, endpoint: str | None = None, queue_config: str | Path | None = None
) -> "RunInspectionResponse":
    try:
        from loom.diagnostics.run_inspection import (
            decode_run_inspection_response,
            inspect_run,
        )

        if endpoint is None:
            if queue_config is None:
                return inspect_run(run_uri)
            from loom.cli.sweep import _started_queue_service
            return inspect_run(run_uri, queue_service=_started_queue_service(queue_config))
        from loom.queue import LocalDaemonSocketClient

        return decode_run_inspection_response(
            LocalDaemonSocketClient(Path(endpoint)).inspect_run(run_uri)
        )
    except Exception as exc:
        raise CliError(
            "run inspection failed",
            code="cli.inspect_run.failed",
            context={"error_type": type(exc).__name__},
            exit_code=ExitCode.RUN_STATE,
        ) from exc


def format_inspect_run_text(result: "RunInspectionResponse") -> str:
    from loom.diagnostics.run_inspection import RunInspectionFailure

    if isinstance(result, RunInspectionFailure):
        return f"inspection: {result.code.value}"
    lines = [f"run: {result.run_uri}", f"summary: {result.summary}"]
    lines.extend(
        f"{axis.name.value}: {axis.state} ({axis.availability})" for axis in result.axes
    )
    return "\n".join(lines)


__all__ = [
    "INSPECT_RUN_RESULT_SCHEMA_VERSION",
    "build_inspect_run_result",
    "format_inspect_run_text",
    "handle",
    "register_subparser",
]
