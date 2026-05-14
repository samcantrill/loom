"""Implementation for ``loom queue`` operational commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loom.cli.authority import add_authority_options, authority_config_from_namespace
from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import (
    format_json_envelope,
    format_queue_cancel_text,
    format_queue_drain_text,
    format_queue_preflight_text,
    format_queue_status_text,
)
from loom.cli.options import OutputFormat, output_format_from_namespace
from loom.queue.errors import QueueConfigError, QueueError, QueueServiceError
from loom.queue.status import (
    QueueCancellationStatus,
    build_queue_operational_status,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from loom.pipeline.stores import AuthorityConfig
    from loom.queue import QueueDrainResult, QueueService
    from loom.queue.controller import QueueDispatchAdapter, QueueInspectableDispatchAdapter
    from loom.queue.preflight import QueuePreflightResult
    from loom.queue.status import QueueOperationalStatus


QUEUE_PREFLIGHT_SCHEMA_VERSION = "loom.cli.queue.preflight.v1"
QUEUE_STATUS_SCHEMA_VERSION = "loom.cli.queue.status.v1"
QUEUE_CANCEL_SCHEMA_VERSION = "loom.cli.queue.cancel.v1"
QUEUE_DRAIN_SCHEMA_VERSION = "loom.cli.queue.drain.v1"


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the queue command group."""

    parser = subparsers.add_parser(
        "queue",
        help="operate a configured queue service",
    )
    queue_subparsers = parser.add_subparsers(
        dest="queue_command",
        metavar="QUEUE_COMMAND",
    )

    preflight = queue_subparsers.add_parser(
        "preflight",
        help="run queue service preflight checks",
    )
    _add_config_argument(preflight)
    _add_output_options(preflight)
    add_authority_options(preflight)
    preflight.set_defaults(handler=handle_preflight)

    start = queue_subparsers.add_parser(
        "start",
        help="validate and start the in-process queue service for this command",
    )
    _add_config_argument(start)
    _add_output_options(start)
    start.set_defaults(handler=handle_start)

    status = queue_subparsers.add_parser(
        "status",
        help="inspect queue service or item status",
    )
    _add_config_argument(status)
    status.add_argument(
        "--item",
        dest="queue_item_id",
        metavar="QUEUE_ITEM_ID",
        help="queue item id to inspect",
    )
    status.add_argument(
        "--refresh-adapters",
        action="store_true",
        help="ask known delegated adapters for active status evidence",
    )
    _add_output_options(status)
    status.set_defaults(handler=handle_status)

    cancel = queue_subparsers.add_parser(
        "cancel",
        help="cancel a queue item",
    )
    _add_config_argument(cancel)
    cancel.add_argument("queue_item_id", metavar="QUEUE_ITEM_ID")
    cancel.add_argument(
        "--requested-by",
        default="queue-cli",
        help="operator identity recorded in the cancellation record",
    )
    cancel.add_argument(
        "--reason",
        default="cli-requested",
        help="operator reason recorded in the cancellation record",
    )
    cancel.add_argument(
        "--adapter-cancel",
        action="store_true",
        help="call known active adapters before recording queue cancellation",
    )
    _add_output_options(cancel)
    cancel.set_defaults(handler=handle_cancel)

    drain = queue_subparsers.add_parser(
        "drain-foreground",
        help="run a foreground queue controller loop",
    )
    _add_config_argument(drain)
    drain.add_argument("--pool", dest="pool_name", metavar="POOL")
    drain.add_argument("--max-items", type=int, default=None, metavar="N")
    drain.add_argument(
        "--poll-interval",
        type=float,
        default=0.1,
        metavar="SECONDS",
        help="sleep interval while foreground work remains active",
    )
    drain.add_argument(
        "--slurm",
        action="store_true",
        help="enable the built-in SLURM delegated adapter",
    )
    _add_output_options(drain)
    drain.set_defaults(handler=handle_drain_foreground)


def handle_preflight(namespace: argparse.Namespace) -> int:
    """Handle ``loom queue preflight``."""

    result = build_queue_preflight_result(
        namespace.config,
        authority_config=_explicit_authority_config_from_namespace(namespace),
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=QUEUE_PREFLIGHT_SCHEMA_VERSION,
                ok=result.ok,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_queue_preflight_text(result) + "\n")
    return int(
        ExitCode.PIPELINE
        if _enum_value(result.status) == "FAIL"
        else ExitCode.SUCCESS
    )


def handle_start(namespace: argparse.Namespace) -> int:
    """Handle ``loom queue start``."""

    result = build_queue_status_result(namespace.config)
    return _emit_status_result(result, namespace)


def handle_status(namespace: argparse.Namespace) -> int:
    """Handle ``loom queue status``."""

    result = build_queue_status_result(
        namespace.config,
        queue_item_id=namespace.queue_item_id,
        refresh_adapters=bool(namespace.refresh_adapters),
    )
    return _emit_status_result(result, namespace)


def handle_cancel(namespace: argparse.Namespace) -> int:
    """Handle ``loom queue cancel``."""

    result = build_queue_cancel_result(
        namespace.config,
        namespace.queue_item_id,
        requested_by=namespace.requested_by,
        reason=namespace.reason,
        adapter_cancel=bool(namespace.adapter_cancel),
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=QUEUE_CANCEL_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_queue_cancel_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def handle_drain_foreground(namespace: argparse.Namespace) -> int:
    """Handle ``loom queue drain-foreground``."""

    result = build_queue_drain_result(
        namespace.config,
        pool_name=namespace.pool_name,
        max_items=namespace.max_items,
        poll_interval_seconds=namespace.poll_interval,
        enable_slurm=bool(namespace.slurm),
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=QUEUE_DRAIN_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_queue_drain_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def build_queue_preflight_result(
    config_path: str | Path,
    *,
    authority_config: "AuthorityConfig | None" = None,
) -> "QueuePreflightResult":
    """Build queue preflight diagnostics for the CLI."""

    from loom.queue.preflight import run_queue_preflight

    try:
        return run_queue_preflight(
            config_path,
            authority_config=authority_config,
            workspace_id=getattr(authority_config, "workspace_id", None),
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc


def build_queue_status_result(
    config_path: str | Path,
    *,
    queue_item_id: str | None = None,
    refresh_adapters: bool = False,
) -> "QueueOperationalStatus":
    """Build queue service or item status."""

    service = _started_service(config_path)
    adapters = _default_refresh_adapters() if refresh_adapters else None
    return build_queue_operational_status(
        service,
        queue_item_id=queue_item_id,
        adapters=adapters,
    )


def build_queue_cancel_result(
    config_path: str | Path,
    queue_item_id: str,
    *,
    requested_by: str,
    reason: str,
    adapter_cancel: bool = False,
) -> QueueCancellationStatus:
    """Cancel one queue item through the queue service."""

    service = _started_service(config_path)
    if adapter_cancel:
        from loom.queue.controller import QueueController

        step = QueueController(
            service,
            adapters=_default_dispatch_adapters(enable_slurm=True),
        ).cancel_item(
            queue_item_id,
            requested_by=requested_by,
            reason=reason,
        )
        if step.item is None:
            raise CliError(
                "queue cancellation did not return an item",
                code="cli.queue.cancel_missing_item",
                exit_code=ExitCode.RUN_STATE,
            )
        return QueueCancellationStatus(item=step.item)
    try:
        item = service.cancel_item(
            queue_item_id,
            requested_by=requested_by,
            reason=reason,
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return QueueCancellationStatus(item=item)


def build_queue_drain_result(
    config_path: str | Path,
    *,
    pool_name: str | None = None,
    max_items: int | None = None,
    poll_interval_seconds: float = 0.1,
    enable_slurm: bool = False,
) -> "QueueDrainResult":
    """Run the foreground queue controller loop."""

    service = _started_service(config_path)
    from loom.queue.controller import QueueController

    try:
        return QueueController(
            service,
            adapters=_default_dispatch_adapters(enable_slurm=enable_slurm),
        ).drain_foreground(
            pool_name=pool_name,
            max_items=max_items,
            poll_interval_seconds=poll_interval_seconds,
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc


def _emit_status_result(
    result: "QueueOperationalStatus",
    namespace: argparse.Namespace,
) -> int:
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=QUEUE_STATUS_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_queue_status_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def _started_service(config_path: str | Path) -> "QueueService":
    from loom.queue import QueueService, load_queue_spec

    try:
        service = QueueService.from_spec(load_queue_spec(config_path))
        service.start()
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return service


def _default_refresh_adapters() -> "Mapping[str, QueueInspectableDispatchAdapter]":
    from loom.queue.slurm import SLURM_QUEUE_ADAPTER_NAME, SlurmQueueDispatchAdapter

    return {
        SLURM_QUEUE_ADAPTER_NAME: SlurmQueueDispatchAdapter(),
    }


def _default_dispatch_adapters(
    *,
    enable_slurm: bool,
) -> "Mapping[str, QueueDispatchAdapter]":
    from loom.queue.controller import FakeQueueDispatchAdapter

    adapters: dict[str, QueueDispatchAdapter] = {
        "fake": FakeQueueDispatchAdapter(),
    }
    if enable_slurm:
        from loom.queue.slurm import SLURM_QUEUE_ADAPTER_NAME, SlurmQueueDispatchAdapter

        adapters[SLURM_QUEUE_ADAPTER_NAME] = SlurmQueueDispatchAdapter()
    return adapters


def _queue_cli_error(error: QueueError) -> CliError:
    exit_code = ExitCode.CONFIG if isinstance(error, QueueConfigError) else ExitCode.RUN_STATE
    code = (
        "cli.queue.config_error"
        if isinstance(error, QueueConfigError)
        else "cli.queue.operation_error"
    )
    if isinstance(error, QueueServiceError):
        code = "cli.queue.service_error"
    return CliError(
        str(error),
        code=code,
        context={"error_type": type(error).__name__},
        exit_code=exit_code,
    )


def _explicit_authority_config_from_namespace(
    namespace: argparse.Namespace,
) -> "AuthorityConfig | None":
    option_names = (
        "authority_backend",
        "authority_profile",
        "authority_endpoint",
        "authority_workspace",
        "authority_state",
        "authority_reference",
        "authority_metadata_json",
    )
    if not any(getattr(namespace, name, None) is not None for name in option_names):
        return None
    return authority_config_from_namespace(namespace)


def _enum_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("config", metavar="CONFIG", help="queue config path")


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


__all__ = [
    "QUEUE_CANCEL_SCHEMA_VERSION",
    "QUEUE_DRAIN_SCHEMA_VERSION",
    "QUEUE_PREFLIGHT_SCHEMA_VERSION",
    "QUEUE_STATUS_SCHEMA_VERSION",
    "build_queue_cancel_result",
    "build_queue_drain_result",
    "build_queue_preflight_result",
    "build_queue_status_result",
    "handle_cancel",
    "handle_drain_foreground",
    "handle_preflight",
    "handle_start",
    "handle_status",
    "register_subparser",
]
