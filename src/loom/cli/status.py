"""Implementation for ``loom status``."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from loom.cli.authority import add_authority_options, authority_config_from_namespace
from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import (
    format_json_envelope,
    format_status_jobs_text,
    format_status_text,
)
from loom.cli.options import OutputFormat, output_format_from_namespace

if TYPE_CHECKING:
    from loom.diagnostics.inspection import RunStatusSummary
    from loom.pipeline.executors.slurm.commands import SlurmCommandRunner
    from loom.pipeline.executors.slurm.status import SlurmJobsStatusReport
    from loom.pipeline.stores import AuthorityConfig
    from loom.pipeline.stores.run_store import LegacyRunStore as RunStore


STATUS_RESULT_SCHEMA_VERSION = "loom.cli.status.v3"
STATUS_JOBS_RESULT_SCHEMA_VERSION = "loom.cli.status.jobs.v1"


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the status subcommand."""

    parser = subparsers.add_parser("status", help="inspect a local run")
    parser.add_argument("run_uri", metavar="RUN_URI", help="run URI to inspect")
    parser.add_argument(
        "--jobs",
        action="store_true",
        help="include submitted scheduler job status for the latest operation",
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
    """Handle ``loom status``."""

    output_format = output_format_from_namespace(namespace)
    authority_config = authority_config_from_namespace(namespace)
    if bool(getattr(namespace, "jobs", False)):
        result = build_status_jobs_result(
            str(namespace.run_uri),
            authority_config=authority_config,
        )
        warnings = [warning.to_dict() for warning in result.warnings]
        if output_format is OutputFormat.JSON:
            sys.stdout.write(
                format_json_envelope(
                    schema_version=STATUS_JOBS_RESULT_SCHEMA_VERSION,
                    ok=True,
                    warnings=warnings,
                    payload_name="result",
                    payload=result.to_dict(),
                )
            )
        else:
            sys.stdout.write(format_status_jobs_text(result) + "\n")
        return int(ExitCode.SUCCESS)

    result = build_status_result(
        str(namespace.run_uri),
        authority_config=authority_config,
    )
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


def build_status_result(
    run_uri: str,
    *,
    authority_config: "AuthorityConfig | None" = None,
) -> "RunStatusSummary":
    """Build a run status summary."""

    try:
        from loom.diagnostics.inspection import inspect_run_status

        return inspect_run_status(
            run_uri,
            run_store=_create_status_run_store(authority_config=authority_config),
        )
    except Exception as exc:
        raise _run_state_error(exc) from exc


def build_status_jobs_result(
    run_uri: str,
    *,
    authority_config: "AuthorityConfig | None" = None,
) -> "SlurmJobsStatusReport":
    """Build a scheduler-aware run status summary."""

    from loom.pipeline.executors.slurm.status import (
        SlurmStatusInspectionError,
        inspect_slurm_job_status,
    )

    try:
        return inspect_slurm_job_status(
            run_uri,
            run_store=_create_status_run_store(
                authority_config=authority_config,
                owner_id="slurm-status",
            ),
            command_runner=_build_slurm_status_command_runner(),
        )
    except SlurmStatusInspectionError as exc:
        raise CliError(
            str(exc),
            code=exc.code,
            context=exc.context,
            exit_code=ExitCode.RUN_STATE,
        ) from exc
    except Exception as exc:
        raise _run_state_error(exc) from exc


def _build_slurm_status_command_runner() -> "SlurmCommandRunner":
    from loom.pipeline.executors.slurm.status import default_slurm_status_command_runner

    return default_slurm_status_command_runner()


def _create_status_run_store(
    *,
    authority_config: "AuthorityConfig | None",
    owner_id: str = "status",
) -> "RunStore":
    from loom.pipeline.execution import create_authority_backed_serial_run_store

    return create_authority_backed_serial_run_store(
        "runs",
        authority_config=authority_config,
        owner_id=owner_id,
    )


def _run_state_error(error: BaseException) -> CliError:
    return CliError(
        str(error),
        code="cli.status.run_state_error",
        context={"error_type": type(error).__name__},
        exit_code=ExitCode.RUN_STATE,
    )


__all__ = [
    "STATUS_JOBS_RESULT_SCHEMA_VERSION",
    "STATUS_RESULT_SCHEMA_VERSION",
    "build_status_jobs_result",
    "build_status_result",
    "handle",
    "register_subparser",
]
