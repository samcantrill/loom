"""Ordinary run delegates to the shared deployment/native run composition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import cast
from uuid import uuid4

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.cli.options import OutputFormat, RunCliOptions, SelectorCliOptions
from loom.serialization import PlainData

RUN_RESULT_SCHEMA_VERSION = "loom.cli.run.v3"


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("run", help="run through a selected deployment")
    parser.add_argument(
        "config",
        metavar="CONFIG",
        help="config relative to the selected preparation project",
    )
    parser.add_argument("--deployment", required=True, metavar="PATH")
    parser.add_argument("--overlay", action="append", default=None)
    parser.add_argument("--set", dest="override", action="append", default=None)
    parser.add_argument(
        "--operation-id", help="replay exactly this accepted operation identity"
    )
    parser.add_argument("--queue-item-id", help="exact native admission queue identity")
    parser.add_argument("--run-name", help="new prepared run name")
    parser.add_argument("--context", type=Path, help="JSON file containing submission description, tags and metadata")
    parser.add_argument("--reconcile", action="store_true", help="resolve the canonical target using the installed project")
    parser.add_argument("--retry-failed", action="store_true", help="with --reconcile, retry one observed eligible failed revision")
    parser.add_argument("--fresh-stage", action="append", default=None,
                        help="request a fresh realization of this node without changing its settings")
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--profile")
    parser.add_argument("--max-parallel-stages", type=int)
    parser.add_argument(
        "--failure-policy", choices=["stop-on-first-failure", "continue-independent"]
    )
    parser.add_argument("--tag", action="append", default=None)
    parser.add_argument("--note", action="append", default=None)
    parser.add_argument("--from-stage")
    for name in ("only", "force", "skip"):
        parser.add_argument(f"--{name}-stage", action="append", default=None)
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=[item.value for item in OutputFormat],
        default="text",
    )
    parser.add_argument("--traceback", action="store_true", default=argparse.SUPPRESS)
    parser.set_defaults(handler=handle)


def handle(namespace: argparse.Namespace) -> int:
    from loom.coordinator import CoordinatorClientError
    from loom._run import run
    from loom.deployment import load_deployment
    from loom.queue.errors import QueueError
    from loom.queue.preparation import PrepareRunRequest
    from loom.queue.run import RunRequest
    from loom.runs import SubmissionContext

    try:
        from loom.queue.errors import QueueConfigError

        reconcile = getattr(namespace, "reconcile", False)
        retry = getattr(namespace, "retry_failed", False)
        if (reconcile and (namespace.run_name or namespace.queue_item_id)) or (retry and not reconcile):
            raise QueueConfigError("--reconcile requires an unresolved target; --retry-failed requires --reconcile")
        selection = load_deployment(namespace.deployment)
        identity = namespace.operation_id or "run-" + uuid4().hex
        context_path = getattr(namespace, "context", None)
        context = None
        if context_path is not None:
            try:
                context = SubmissionContext.from_dict(json.loads(context_path.read_text(encoding="utf-8")))
            except (ValueError, TypeError, OSError) as exc:
                raise QueueConfigError(f"invalid submission context: {exc}") from exc
        request = RunRequest(
            PrepareRunRequest(
                identity,
                None if reconcile else namespace.run_name or identity,
                selection.source,
                namespace.config,
                selection.preparation_profile,
                tuple(namespace.overlay or ()),
                tuple(namespace.override or ()),
                cast(
                    dict[str, PlainData],
                    RunCliOptions.from_namespace(namespace).to_runtime_source(
                        selectors=SelectorCliOptions.from_namespace(namespace)
                    ),
                ),
                context=context,
            ),
            None if reconcile else namespace.queue_item_id or identity,
            mode="reconcile" if reconcile else "exact",
            retry_policy="one_observed_failure" if retry else "never",
            fresh_stages=tuple(getattr(namespace, "fresh_stage", None) or ()),
        )
        result = run(
            request,
            deployment=selection.path,
            wait=not namespace.detach,
            timeout_seconds=namespace.timeout_seconds,
        )
    except QueueError as exc:
        raise CliError(
            str(exc),
            code="cli.run.coordinator",
            exit_code=ExitCode.RUN_STATE,
            details={"coordinator": exc.to_dict()}
            if isinstance(exc, CoordinatorClientError)
            else None,
        ) from exc
    observation = result.observation
    failed = (
        observation.operation is not None
        and observation.operation.state in {"failed", "conflict", "cancelled"}
    ) or (
        observation.admission is not None
        and observation.admission.state.value in {"FAILED", "CANCELLED", "BLOCKED"}
    )
    if namespace.output_format == "json":
        sys.stdout.write(
            format_json_envelope(
                schema_version=RUN_RESULT_SCHEMA_VERSION,
                ok=not failed,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        state = (
            observation.admission.state.value
            if observation.admission is not None
            else observation.operation.state
            if observation.operation is not None
            else "accepted"
        )
        sys.stdout.write(f"run {observation.operation_id}: {state}\n")
        for role, cleanup in result.cleanup.items():
            sys.stdout.write(f"{role}: {cleanup}\n")
    return int(ExitCode.RUN_FAILED if failed else ExitCode.SUCCESS)
