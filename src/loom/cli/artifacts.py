"""Implementation for ``loom artifacts`` diagnostics commands."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import (
    format_artifact_show_text,
    format_artifacts_list_text,
    format_json_envelope,
)
from loom.cli.options import OutputFormat, output_format_from_namespace

if TYPE_CHECKING:
    from loom.diagnostics.inspection import ArtifactDetailSummary, RunArtifactsSummary


ARTIFACTS_LIST_SCHEMA_VERSION = "loom.cli.artifacts.list.v3"
ARTIFACTS_SHOW_SCHEMA_VERSION = "loom.cli.artifacts.show.v3"


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the artifacts command group."""

    parser = subparsers.add_parser("artifacts", help="inspect local run artifacts")
    actions = parser.add_subparsers(dest="artifact_action", metavar="ACTION")
    actions.required = True

    list_parser = actions.add_parser("list", help="list recorded artifact metadata")
    list_parser.add_argument("run_uri", metavar="RUN_URI", help="run URI to inspect")
    _add_output_options(list_parser)
    list_parser.set_defaults(handler=handle_list)

    show_parser = actions.add_parser("show", help="show one artifact metadata record")
    show_parser.add_argument("run_uri", metavar="RUN_URI", help="run URI to inspect")
    show_parser.add_argument(
        "artifact_id",
        metavar="ARTIFACT_ID",
        help="artifact ID to inspect",
    )
    _add_output_options(show_parser)
    show_parser.set_defaults(handler=handle_show)


def handle_list(namespace: argparse.Namespace) -> int:
    """Handle ``loom artifacts list``."""

    output_format = output_format_from_namespace(namespace)
    result = build_artifacts_list_result(str(namespace.run_uri))
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=ARTIFACTS_LIST_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_artifacts_list_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def handle_show(namespace: argparse.Namespace) -> int:
    """Handle ``loom artifacts show``."""

    output_format = output_format_from_namespace(namespace)
    result = build_artifact_show_result(
        str(namespace.run_uri),
        str(namespace.artifact_id),
    )
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=ARTIFACTS_SHOW_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_artifact_show_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def build_artifacts_list_result(run_uri: str) -> "RunArtifactsSummary":
    """Build an artifact list summary."""

    try:
        from loom.diagnostics.inspection import inspect_run_artifacts

        return inspect_run_artifacts(run_uri)
    except Exception as exc:
        raise _run_state_error(exc) from exc


def build_artifact_show_result(
    run_uri: str,
    artifact_id: str,
) -> "ArtifactDetailSummary":
    """Build a single-artifact detail summary."""

    try:
        from loom.diagnostics.inspection import inspect_run_artifact

        return inspect_run_artifact(run_uri, artifact_id)
    except Exception as exc:
        raise _run_state_error(exc) from exc


def _add_output_options(parser: argparse.ArgumentParser) -> None:
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


def _run_state_error(error: BaseException) -> CliError:
    return CliError(
        str(error),
        code="cli.artifacts.run_state_error",
        context={"error_type": type(error).__name__},
        exit_code=ExitCode.RUN_STATE,
    )


__all__ = [
    "ARTIFACTS_LIST_SCHEMA_VERSION",
    "ARTIFACTS_SHOW_SCHEMA_VERSION",
    "build_artifact_show_result",
    "build_artifacts_list_result",
    "handle_list",
    "handle_show",
    "register_subparser",
]
