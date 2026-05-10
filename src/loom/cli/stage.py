"""Implementation for ``loom stage`` worker commands."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from loom.cli.errors import CliError, ExitCode
from loom.cli.authority import add_authority_options, authority_config_from_namespace
from loom.cli.formatting import format_json_envelope, format_stage_worker_text
from loom.cli.options import OutputFormat, output_format_from_namespace

if TYPE_CHECKING:
    from loom.pipeline.execution import StageWorkerResult
    from loom.pipeline.stores import AuthorityConfig

STAGE_WORKER_RESULT_SCHEMA_VERSION = "loom.cli.stage.run.v1"


class StageWorkerCliError(CliError):
    """Raised when direct worker state cannot be reconstructed."""

    def __init__(self, message: str, *, context: dict[str, object] | None = None) -> None:
        super().__init__(
            message,
            code="cli.stage.worker_state",
            context=context,
            exit_code=ExitCode.CONFIG,
        )


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the stage worker subcommands."""

    parser = subparsers.add_parser("stage", help="run stage worker commands")
    stage_subparsers = parser.add_subparsers(
        dest="stage_command",
        metavar="COMMAND",
        required=True,
    )
    run_parser = stage_subparsers.add_parser(
        "run",
        help="run one prepared stage attempt",
    )
    run_parser.add_argument("--run-uri", required=True, metavar="URI", help="run URI")
    run_parser.add_argument("--stage", required=True, metavar="STAGE", help="stage name")
    run_parser.add_argument(
        "--attempt",
        type=_positive_attempt,
        metavar="N",
        help="exact prepared attempt number",
    )
    run_parser.add_argument(
        "--format",
        dest="output_format",
        choices=[format.value for format in OutputFormat],
        default=OutputFormat.TEXT.value,
        help="output format",
    )
    add_authority_options(run_parser)
    run_parser.add_argument(
        "--traceback",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show traceback details for errors",
    )
    run_parser.set_defaults(handler=handle_run)


def handle_run(namespace: argparse.Namespace) -> int:
    """Handle ``loom stage run``."""

    from loom.pipeline.execution import StageWorkerStateError
    from loom.pipeline.status import StageStatus

    output_format = output_format_from_namespace(namespace)
    try:
        result = _run_stage_worker(
            run_uri=str(namespace.run_uri),
            stage_name=str(namespace.stage),
            attempt=namespace.attempt,
            authority_config=authority_config_from_namespace(namespace),
        )
    except StageWorkerStateError as exc:
        raise StageWorkerCliError(
            str(exc),
            context={
                "run_uri": str(namespace.run_uri),
                "stage": str(namespace.stage),
                "attempt": namespace.attempt,
            },
        ) from exc

    ok = result.status == StageStatus.SUCCEEDED
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
                ok=ok,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_stage_worker_text(result) + "\n")
    return 0 if ok else 1


def _run_stage_worker(
    *,
    run_uri: str,
    stage_name: str,
    attempt: int | None,
    authority_config: "AuthorityConfig | None" = None,
) -> "StageWorkerResult":
    from loom.pipeline.execution import (
        StageWorkerRunRequest,
        create_authority_backed_serial_run_store,
        run_stage_worker,
    )

    return run_stage_worker(
        run_store=create_authority_backed_serial_run_store(
            "runs",
            authority_config=authority_config,
            owner_id="stage-worker",
        ),
        request=StageWorkerRunRequest(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
        ),
    )


def _positive_attempt(value: str) -> int:
    try:
        attempt = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("attempt must be a positive integer") from exc
    if attempt <= 0:
        raise argparse.ArgumentTypeError("attempt must be a positive integer")
    return attempt


__all__ = [
    "STAGE_WORKER_RESULT_SCHEMA_VERSION",
    "StageWorkerCliError",
    "handle_run",
    "register_subparser",
]
