"""Implementation for ``loom stage-job`` continuation commands."""

from __future__ import annotations

import argparse
import sys

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope, format_stage_job_text
from loom.cli.options import OutputFormat, output_format_from_namespace

STAGE_JOB_RESULT_SCHEMA_VERSION = "loom.cli.stage_job.run.v1"


class StageJobCliError(CliError):
    """Raised when stage-job continuation cannot start safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        context: dict[str, object] | None = None,
        exit_code: ExitCode = ExitCode.RUN_STATE,
    ) -> None:
        super().__init__(
            message,
            code=code,
            context=context,
            exit_code=exit_code,
        )


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the stage-job subcommands."""

    parser = subparsers.add_parser(
        "stage-job",
        help="run self-finalizing stage job commands",
    )
    stage_job_subparsers = parser.add_subparsers(
        dest="stage_job_command",
        metavar="COMMAND",
        required=True,
    )
    run_parser = stage_job_subparsers.add_parser(
        "run",
        help="run and finalize one prepared stage job",
    )
    run_parser.add_argument("--run-uri", required=True, metavar="URI", help="run URI")
    run_parser.add_argument("--stage", required=True, metavar="STAGE", help="stage name")
    run_parser.add_argument(
        "--executor",
        required=True,
        metavar="NAME",
        help="continuation executor",
    )
    run_parser.add_argument(
        "--attempt",
        type=_positive_attempt,
        metavar="N",
        help="exact prepared attempt number",
    )
    run_parser.add_argument(
        "--authority-attempt-id",
        metavar="ID",
        help="authority attempt id for fenced finalization",
    )
    run_parser.add_argument(
        "--authority-lease-id",
        metavar="ID",
        help="authority lease id for fenced finalization",
    )
    run_parser.add_argument(
        "--authority-owner-id",
        metavar="ID",
        help="authority owner id for fenced finalization",
    )
    run_parser.add_argument(
        "--authority-fencing-token",
        metavar="TOKEN",
        help="authority fencing token for fenced finalization",
    )
    run_parser.add_argument(
        "--format",
        dest="output_format",
        choices=[format.value for format in OutputFormat],
        default=OutputFormat.TEXT.value,
        help="output format",
    )
    run_parser.add_argument(
        "--traceback",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show traceback details for errors",
    )
    run_parser.set_defaults(handler=handle_run)


def handle_run(namespace: argparse.Namespace) -> int:
    """Handle ``loom stage-job run``."""

    from loom.pipeline.execution import (
        ContinuationStateError,
        StageJobRunRequest,
        UnsupportedContinuationExecutorError,
        create_authority_backed_serial_run_store,
        run_stage_job,
    )
    from loom.pipeline.status import StageStatus

    output_format = output_format_from_namespace(namespace)
    try:
        result = run_stage_job(
            run_store=create_authority_backed_serial_run_store(
                "runs",
                owner_id="stage-job",
            ),
            request=StageJobRunRequest(
                run_uri=str(namespace.run_uri),
                stage_name=str(namespace.stage),
                executor=str(namespace.executor),
                attempt=namespace.attempt,
                authority_attempt_id=namespace.authority_attempt_id,
                authority_lease_id=namespace.authority_lease_id,
                authority_owner_id=namespace.authority_owner_id,
                authority_fencing_token=namespace.authority_fencing_token,
            ),
        )
    except UnsupportedContinuationExecutorError as exc:
        raise _cli_error_from_continuation(exc, exit_code=ExitCode.EXECUTOR) from exc
    except ContinuationStateError as exc:
        raise _cli_error_from_continuation(exc) from exc

    ok = result.status == StageStatus.SUCCEEDED
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=STAGE_JOB_RESULT_SCHEMA_VERSION,
                ok=ok,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_stage_job_text(result) + "\n")
    return int(ExitCode.SUCCESS if ok else ExitCode.RUN_FAILED)


def _cli_error_from_continuation(
    error: object,
    *,
    exit_code: ExitCode = ExitCode.RUN_STATE,
) -> StageJobCliError:
    to_dict = getattr(error, "to_dict", None)
    raw_payload = to_dict() if callable(to_dict) else {}
    payload: dict[str, object] = raw_payload if isinstance(raw_payload, dict) else {}
    context = payload.get("context", {})
    if not isinstance(context, dict):
        context = {}
    code = payload.get("code", "cli.stage_job.continuation_state")
    return StageJobCliError(
        str(error),
        code=str(code),
        context=dict(context),
        exit_code=exit_code,
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
    "STAGE_JOB_RESULT_SCHEMA_VERSION",
    "StageJobCliError",
    "handle_run",
    "register_subparser",
]
