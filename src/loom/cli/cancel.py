"""Implementation for ``loom cancel``."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from loom.cli.authority import add_authority_options, authority_config_from_namespace
from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_cancel_jobs_text, format_json_envelope
from loom.cli.options import OutputFormat, output_format_from_namespace

if TYPE_CHECKING:
    from loom.pipeline.executors.slurm.cancellation import SlurmCancellationResult
    from loom.pipeline.executors.slurm.commands import SlurmCommandRunner
    from loom.pipeline.stores import AuthorityConfig
    from loom.pipeline.stores.run_store import LegacyRunStore


CANCEL_JOBS_RESULT_SCHEMA_VERSION = "loom.cli.cancel.jobs.v1"


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the cancel subcommand."""

    parser = subparsers.add_parser("cancel", help="cancel submitted jobs")
    parser.add_argument("run_uri", metavar="RUN_URI", help="run URI to cancel")
    parser.add_argument(
        "--jobs",
        action="store_true",
        help="cancel submitted scheduler jobs for the latest active submission",
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
    """Handle ``loom cancel``."""

    if not bool(getattr(namespace, "jobs", False)):
        raise CliError(
            "`loom cancel` currently requires --jobs",
            code="cli.cancel.jobs_required",
            hint="Use `loom cancel RUN_URI --jobs` to cancel submitted scheduler jobs.",
            exit_code=ExitCode.USAGE,
        )

    output_format = output_format_from_namespace(namespace)
    result = build_cancel_jobs_result(
        str(namespace.run_uri),
        authority_config=authority_config_from_namespace(namespace),
    )
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=CANCEL_JOBS_RESULT_SCHEMA_VERSION,
                ok=result.ok,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_cancel_jobs_text(result) + "\n")
    return int(ExitCode.SUCCESS if result.ok else ExitCode.RUN_FAILED)


def build_cancel_jobs_result(
    run_uri: str,
    *,
    authority_config: "AuthorityConfig | None" = None,
) -> "SlurmCancellationResult":
    """Build a submitted-job cancellation result."""

    from loom.pipeline.executors.slurm.cancellation import (
        SlurmCancellationError,
        cancel_slurm_jobs,
    )

    try:
        return cancel_slurm_jobs(
            run_uri,
            run_store=_create_cancel_run_store(authority_config=authority_config),
            command_runner=_build_slurm_cancel_command_runner(),
        )
    except SlurmCancellationError as exc:
        raise CliError(
            str(exc),
            code=exc.code,
            context=exc.context,
            exit_code=ExitCode.RUN_STATE,
        ) from exc
    except Exception as exc:
        raise CliError(
            str(exc),
            code="cli.cancel.run_state_error",
            context={"error_type": type(exc).__name__},
            exit_code=ExitCode.RUN_STATE,
        ) from exc


def _build_slurm_cancel_command_runner() -> "SlurmCommandRunner":
    from loom.pipeline.executors.slurm.cancellation import (
        default_slurm_cancel_command_runner,
    )

    return default_slurm_cancel_command_runner()


def _create_cancel_run_store(
    *,
    authority_config: "AuthorityConfig | None",
) -> "LegacyRunStore":
    from loom.pipeline.execution import create_authority_backed_serial_run_store

    return create_authority_backed_serial_run_store(
        "runs",
        authority_config=authority_config,
        owner_id="slurm-cancellation",
    )


__all__ = [
    "CANCEL_JOBS_RESULT_SCHEMA_VERSION",
    "build_cancel_jobs_result",
    "handle",
    "register_subparser",
]
