"""Implementation for ``loom prepared-run`` continuation commands."""

from __future__ import annotations

import argparse

from loom.cli.errors import CliError, ExitCode
from loom.cli.options import OutputFormat


class PreparedRunCliError(CliError):
    """Raised when prepared-run continuation cannot start safely."""

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
    """Register prepared-run continuation commands."""

    parser = subparsers.add_parser(
        "prepared-run",
        help="continue a prepared run from durable state",
    )
    prepared_subparsers = parser.add_subparsers(
        dest="prepared_run_command",
        metavar="COMMAND",
        required=True,
    )
    continue_parser = prepared_subparsers.add_parser(
        "continue",
        help="continue one prepared whole run",
    )
    continue_parser.add_argument(
        "--run-uri",
        required=True,
        metavar="URI",
        help="run URI",
    )
    continue_parser.add_argument(
        "--executor",
        required=True,
        metavar="NAME",
        help="continuation executor",
    )
    continue_parser.add_argument(
        "--format",
        dest="output_format",
        choices=[format.value for format in OutputFormat],
        default=OutputFormat.TEXT.value,
        help="output format",
    )
    continue_parser.add_argument(
        "--traceback",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show traceback details for errors",
    )
    continue_parser.set_defaults(handler=handle_continue)


def handle_continue(namespace: argparse.Namespace) -> int:
    """Handle ``loom prepared-run continue``."""

    from loom.pipeline.execution import (
        ContinuationStateError,
        PreparedRunContinueRequest,
        UnsupportedContinuationExecutorError,
        continue_prepared_run,
        create_authority_backed_serial_run_store,
    )

    try:
        continue_prepared_run(
            run_store=create_authority_backed_serial_run_store(
                "runs",
                owner_id="prepared-run",
            ),
            request=PreparedRunContinueRequest(
                run_uri=str(namespace.run_uri),
                executor=str(namespace.executor),
            ),
        )
    except UnsupportedContinuationExecutorError as exc:
        raise _cli_error_from_continuation(exc, exit_code=ExitCode.EXECUTOR) from exc
    except ContinuationStateError as exc:
        raise _cli_error_from_continuation(exc) from exc
    return int(ExitCode.SUCCESS)


def _cli_error_from_continuation(
    error: object,
    *,
    exit_code: ExitCode = ExitCode.RUN_STATE,
) -> PreparedRunCliError:
    to_dict = getattr(error, "to_dict", None)
    raw_payload = to_dict() if callable(to_dict) else {}
    payload: dict[str, object] = raw_payload if isinstance(raw_payload, dict) else {}
    context = payload.get("context", {})
    if not isinstance(context, dict):
        context = {}
    code = payload.get("code", "cli.prepared_run.continuation_state")
    return PreparedRunCliError(
        str(error),
        code=str(code),
        context=dict(context),
        exit_code=exit_code,
    )


__all__ = [
    "PreparedRunCliError",
    "handle_continue",
    "register_subparser",
]
