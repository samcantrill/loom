"""Implementation for ``loom queue`` operational commands."""

from __future__ import annotations

import argparse
import json
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
from loom.serialization import PlainData

if TYPE_CHECKING:
    from collections.abc import Mapping

    from loom.pipeline.stores import AuthorityConfig
    from loom.queue import QueueDrainResult, QueueForegroundDriveResult, QueueService
    from loom.queue.controller import (
        QueueDispatchAdapter,
        QueueInspectableDispatchAdapter,
    )
    from loom.queue.preflight import QueuePreflightResult
    from loom.queue.status import QueueOperationalStatus


QUEUE_PREFLIGHT_SCHEMA_VERSION = "loom.cli.queue.preflight.v1"
QUEUE_STATUS_SCHEMA_VERSION = "loom.cli.queue.status.v1"
QUEUE_CANCEL_SCHEMA_VERSION = "loom.cli.queue.cancel.v1"
QUEUE_DRAIN_SCHEMA_VERSION = "loom.cli.queue.drain.v1"
QUEUE_SLURM_DRIVE_SCHEMA_VERSION = "loom.cli.queue.slurm-drive.v1"
LOCAL_DAEMON_SCHEMA_VERSION = "loom.cli.queue.local-daemon.v4"


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
        "--pool",
        dest="pool_name",
        metavar="POOL",
        help="selected pool summary with redacted active-attempt facts",
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

    slurm_drive = queue_subparsers.add_parser(
        "drive-slurm-foreground",
        help="submit and reconcile prepared SLURM runs without a persistent service",
    )
    _add_config_argument(slurm_drive)
    slurm_drive.add_argument("--pool", dest="pool_name", metavar="POOL")
    slurm_drive.add_argument(
        "--once",
        action="store_true",
        help="run one bounded controller cycle instead of driving to local quiescence",
    )
    slurm_drive.add_argument(
        "--run-root",
        default="runs",
        metavar="PATH",
        help="shared local root containing prepared run state and SLURM artifacts",
    )
    add_authority_options(slurm_drive)
    _add_output_options(slurm_drive)
    slurm_drive.set_defaults(handler=handle_drive_slurm_foreground)

    daemon_init = queue_subparsers.add_parser(
        "daemon-init",
        help="initialize one protected coordinator deployment bundle",
    )
    _add_config_argument(daemon_init)
    _add_output_options(daemon_init)
    daemon_init.set_defaults(handler=handle_daemon_init)

    daemon_serve = queue_subparsers.add_parser(
        "daemon-serve",
        help="serve one initialized coordinator deployment bundle",
    )
    _add_config_argument(daemon_serve)
    _add_output_options(daemon_serve)
    daemon_serve.set_defaults(handler=handle_daemon_serve)

    agent_init = queue_subparsers.add_parser(
        "agent-init",
        help="initialize one protected outbound-agent root",
    )
    _add_config_argument(agent_init)
    _add_output_options(agent_init)
    agent_init.set_defaults(handler=handle_agent_init)

    agent_serve = queue_subparsers.add_parser(
        "agent-serve",
        help="serve one initialized outbound-agent root",
    )
    _add_config_argument(agent_serve)
    _add_output_options(agent_serve)
    agent_serve.set_defaults(handler=handle_agent_serve)

    for command, help_text, handler in (
        ("daemon-submit", "submit one persisted run", handle_daemon_submit),
        ("daemon-status", "inspect daemon status", handle_daemon_status),
        ("daemon-wait", "wait for one admitted run", handle_daemon_wait),
        ("daemon-cancel", "cancel one admitted run", handle_daemon_cancel),
    ):
        daemon_client = queue_subparsers.add_parser(command, help=help_text)
        daemon_client.add_argument("--endpoint", required=True, type=Path)
        if command != "daemon-status":
            daemon_client.add_argument("queue_item_id", metavar="QUEUE_ITEM_ID")
        if command == "daemon-submit":
            daemon_client.add_argument("run_uri", metavar="RUN_URI")
        if command == "daemon-wait":
            daemon_client.add_argument("--timeout", type=float, default=None)
        _add_output_options(daemon_client)
        daemon_client.set_defaults(handler=handler)

    for kind in ("drain", "resume", "reload"):
        control = queue_subparsers.add_parser(
            f"daemon-agent-{kind}", help=f"{kind} one managed agent"
        )
        control.add_argument("--endpoint", required=True, type=Path)
        control.add_argument("--operation-id", required=True)
        control.add_argument("--agent-id", required=True)
        control.add_argument("--session-id", required=True)
        control.add_argument("--config-revision", required=True)
        control.add_argument("--pool")
        control.add_argument("--cancel-active", action="store_true")
        control.add_argument("--reason", default=f"cli-{kind}")
        control.set_defaults(handler=handle_daemon_agent_control, agent_control=kind)
        _add_output_options(control)

    scheduling_reload = queue_subparsers.add_parser(
        "daemon-scheduling-reload",
        help="reload protected coordinator scheduling configuration",
    )
    scheduling_reload.add_argument("--endpoint", required=True, type=Path)
    scheduling_reload.add_argument("--operation-id", required=True)
    scheduling_reload.add_argument("--expected-scheduling-epoch", required=True)
    scheduling_reload.add_argument("--reason", default="cli-scheduling-reload")
    scheduling_reload.set_defaults(handler=handle_daemon_scheduling_reload)
    _add_output_options(scheduling_reload)

    time_recovery = queue_subparsers.add_parser(
        "daemon-time-recover",
        help="recover one exact degraded coordinator time revision",
    )
    time_recovery.add_argument("--endpoint", required=True, type=Path)
    time_recovery.add_argument("--operation-id", required=True)
    time_recovery.add_argument("--expected-time-revision", required=True, type=int)
    time_recovery.add_argument("--expected-coordinator-epoch", required=True)
    time_recovery.add_argument("--reason", default="cli-time-recovery")
    time_recovery.set_defaults(handler=handle_daemon_time_recover)
    _add_output_options(time_recovery)

    replacement = queue_subparsers.add_parser(
        "daemon-replace-agent-session",
        help="fence one completely classified lost agent session before re-registration",
    )
    replacement.add_argument("--endpoint", required=True, type=Path)
    replacement.add_argument("--operation-id", required=True)
    replacement.add_argument("--agent-id", required=True)
    replacement.add_argument("--reason", default="cli-session-replacement")
    replacement.set_defaults(handler=handle_daemon_replace_agent_session)
    _add_output_options(replacement)

    recovery = queue_subparsers.add_parser(
        "daemon-recover-unknown",
        help="close one exact unknown assignment from a guarded request",
    )
    recovery.add_argument("--endpoint", required=True, type=Path)
    recovery.add_argument("--request", required=True, type=Path)
    recovery.set_defaults(handler=handle_daemon_recover_unknown)
    _add_output_options(recovery)


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
        ExitCode.PIPELINE if _enum_value(result.status) == "FAIL" else ExitCode.SUCCESS
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
        pool_name=namespace.pool_name,
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


def handle_drive_slurm_foreground(namespace: argparse.Namespace) -> int:
    """Handle bounded service-less prepared-run SLURM driving."""

    result = build_slurm_drive_result(
        namespace.config,
        pool_name=namespace.pool_name,
        run_root=namespace.run_root,
        authority_config=authority_config_from_namespace(namespace),
        until_quiescent=not bool(namespace.once),
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=QUEUE_SLURM_DRIVE_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        dispatched = result.to_dict()["dispatched_count"]
        sys.stdout.write(
            "SLURM foreground drive: "
            f"cycles={len(result.cycles)} "
            f"dispatched={dispatched} "
            f"quiescent={str(result.quiescent).lower()}\n"
        )
    return int(ExitCode.SUCCESS)


def handle_daemon_init(namespace: argparse.Namespace) -> int:
    """Atomically initialize one complete coordinator deployment bundle."""

    from loom.queue import LocalDaemon
    from loom.queue.deployment import load_coordinator_service_config

    try:
        service = load_coordinator_service_config(namespace.config)
        LocalDaemon.initialize_deployment(service.daemon)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(
        namespace,
        {
            "operation": "initialize",
            "deployment_root": str(service.daemon.deployment_root),
            "coordinator_root": str(service.daemon.coordinator_root),
            "agent_root": str(service.daemon.agent_root),
            "run_store_root": str(service.daemon.run_store_root),
        },
    )


def handle_daemon_serve(namespace: argparse.Namespace) -> int:
    """Run the persistent coordinator and its configured endpoints."""

    from threading import Event

    from loom.queue import LocalDaemon, LocalDaemonSocketServer
    from loom.queue.agent_session_transport import LocalDaemonAgentHttpServer
    from loom.queue.deployment import load_coordinator_service_config

    try:
        service = load_coordinator_service_config(namespace.config)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    config = service.daemon
    daemon = LocalDaemon(
        config,
        trusted_scheduling_loader=lambda: load_coordinator_service_config(
            service.source_path
        ).daemon,
    )
    server = LocalDaemonSocketServer(daemon, config.endpoint)
    agent_server = (
        None
        if service.agent_server is None
        else LocalDaemonAgentHttpServer(daemon, service.agent_server)
    )
    try:
        status = daemon.start()
        server.start()
        if agent_server is not None:
            agent_server.start()
        _emit_daemon_payload(
            namespace,
            {
                "operation": "serve",
                "endpoint": str(config.endpoint),
                "agent_port": None if agent_server is None else agent_server.port,
                "coordinator_id": status.coordinator_id,
                "coordinator_epoch": status.coordinator_epoch,
            },
        )
        Event().wait()
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    finally:
        if agent_server is not None:
            agent_server.stop()
        server.stop()
        daemon.stop()
    return int(ExitCode.SUCCESS)


def handle_agent_init(namespace: argparse.Namespace) -> int:
    """Atomically initialize one complete outbound-agent role root."""

    from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
    from loom.queue.deployment import load_outbound_agent_service_config

    try:
        service = load_outbound_agent_service_config(namespace.config)
        LocalDaemonAgentHttpClient.initialize_agent_root(service.client)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(
        namespace,
        {
            "operation": "agent-initialize",
            "agent_root": str(service.client.agent_root),
            "coordinator_url": service.client.url,
        },
    )


def handle_agent_serve(namespace: argparse.Namespace) -> int:
    """Run one foreground outbound agent with bounded reconnect."""

    from threading import Event

    from loom.queue.deployment import (
        load_outbound_agent_service_config,
        run_outbound_agent_service,
    )

    try:
        service = load_outbound_agent_service_config(namespace.config)
        _emit_daemon_payload(
            namespace,
            {
                "operation": "agent-serve",
                "agent_root": str(service.client.agent_root),
                "coordinator_url": service.client.url,
            },
        )
        run_outbound_agent_service(
            service,
            stop=Event(),
            trusted_config_loader=lambda: load_outbound_agent_service_config(
                service.source_path
            ),
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return int(ExitCode.SUCCESS)


def handle_daemon_submit(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemonAdmissionRequest, LocalDaemonSocketClient

    try:
        result = LocalDaemonSocketClient(namespace.endpoint).submit(
            LocalDaemonAdmissionRequest(namespace.queue_item_id, namespace.run_uri)
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_status(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemonSocketClient

    try:
        result = LocalDaemonSocketClient(namespace.endpoint).status()
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_wait(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemonSocketClient

    try:
        result = LocalDaemonSocketClient(namespace.endpoint).wait(
            namespace.queue_item_id, timeout_seconds=namespace.timeout
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_cancel(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemonSocketClient

    try:
        result = LocalDaemonSocketClient(namespace.endpoint).cancel(
            namespace.queue_item_id
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_agent_control(namespace: argparse.Namespace) -> int:
    from loom.queue import AgentControl, LocalDaemonSocketClient

    try:
        result = LocalDaemonSocketClient(namespace.endpoint).control_agent(
            AgentControl(
                operation_id=namespace.operation_id,
                kind=namespace.agent_control,
                agent_id=namespace.agent_id,
                expected_session_id=namespace.session_id,
                expected_config_revision=namespace.config_revision,
                pool=namespace.pool,
                cancel_active=bool(namespace.cancel_active),
                reason=namespace.reason,
            )
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    exit_code = _emit_daemon_payload(namespace, result)
    return (
        int(ExitCode.PIPELINE)
        if result.get("code") == "reload_rejected"
        else exit_code
    )


def handle_daemon_scheduling_reload(namespace: argparse.Namespace) -> int:
    from loom.queue import CoordinatorSchedulingReload, LocalDaemonSocketClient

    try:
        result = LocalDaemonSocketClient(namespace.endpoint).reload_scheduling(
            CoordinatorSchedulingReload(
                operation_id=namespace.operation_id,
                expected_scheduling_epoch=namespace.expected_scheduling_epoch,
                reason=namespace.reason,
            )
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    exit_code = _emit_daemon_payload(namespace, result)
    return (
        int(ExitCode.PIPELINE)
        if result.get("code") == "reload_rejected"
        else exit_code
    )


def handle_daemon_time_recover(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemonSocketClient, TimeRecoveryRequest

    try:
        result = LocalDaemonSocketClient(namespace.endpoint).recover_time(
            TimeRecoveryRequest(
                operation_id=namespace.operation_id,
                expected_time_revision=namespace.expected_time_revision,
                expected_coordinator_epoch=namespace.expected_coordinator_epoch,
                reason=namespace.reason,
            )
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_replace_agent_session(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemonSocketClient, SessionReplacementRequest

    try:
        result = LocalDaemonSocketClient(namespace.endpoint).replace_agent_session(
            SessionReplacementRequest(
                operation_id=namespace.operation_id,
                agent_id=namespace.agent_id,
                reason=namespace.reason,
            )
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result)


def handle_daemon_recover_unknown(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemonSocketClient, RecoverUnknownAssignment

    try:
        raw = json.loads(namespace.request.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(
            "guarded recovery request is unreadable",
            code="cli.queue.recovery_request_invalid",
            exit_code=ExitCode.USAGE,
        ) from exc
    if not isinstance(raw, dict):
        raise CliError(
            "guarded recovery request must be a JSON object",
            code="cli.queue.recovery_request_invalid",
            exit_code=ExitCode.USAGE,
        )
    try:
        result = LocalDaemonSocketClient(namespace.endpoint).recover_unknown(
            RecoverUnknownAssignment.from_dict(raw)
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result)


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
    pool_name: str | None = None,
    refresh_adapters: bool = False,
) -> "QueueOperationalStatus":
    """Build queue service or item status."""

    service = _started_service(config_path)
    adapters = _default_refresh_adapters() if refresh_adapters else None
    return build_queue_operational_status(
        service,
        queue_item_id=queue_item_id,
        pool_name=pool_name,
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


def build_slurm_drive_result(
    config_path: str | Path,
    *,
    pool_name: str | None,
    run_root: str | Path,
    authority_config: "AuthorityConfig | None",
    until_quiescent: bool,
) -> "QueueForegroundDriveResult":
    """Compose the one foreground driver with project-owned run storage."""

    from loom.pipeline.execution import create_authority_backed_serial_run_store
    from loom.queue.controller import QueueController
    from loom.queue.slurm import SLURM_QUEUE_ADAPTER_NAME, SlurmQueueDispatchAdapter

    service = _started_service(config_path)
    selected_pool = pool_name or service.spec.controller.default_pool_name
    if selected_pool is None:
        raise CliError(
            "SLURM foreground drive requires --pool or controller.default_pool_name",
            code="cli.queue.slurm_drive_pool_required",
            exit_code=ExitCode.USAGE,
        )
    try:
        run_store = create_authority_backed_serial_run_store(
            run_root,
            authority_config=authority_config,
            owner_id="queue-slurm-foreground",
        )
        return QueueController(
            service,
            adapters={
                SLURM_QUEUE_ADAPTER_NAME: SlurmQueueDispatchAdapter(
                    run_store=run_store
                )
            },
        ).drive_foreground(
            pool_name=selected_pool,
            until_quiescent=until_quiescent,
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
    exit_code = (
        ExitCode.CONFIG if isinstance(error, QueueConfigError) else ExitCode.RUN_STATE
    )
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


def _emit_daemon_payload(
    namespace: argparse.Namespace, payload: "Mapping[str, PlainData]"
) -> int:
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=LOCAL_DAEMON_SCHEMA_VERSION,
                ok=True,
                warnings=[],
                payload_name="result",
                payload=payload,
            )
        )
    else:
        sys.stdout.write("local daemon:\n")
        for key, value in payload.items():
            sys.stdout.write(f"  {key}: {value}\n")
    return int(ExitCode.SUCCESS)


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
    "QUEUE_SLURM_DRIVE_SCHEMA_VERSION",
    "QUEUE_PREFLIGHT_SCHEMA_VERSION",
    "QUEUE_STATUS_SCHEMA_VERSION",
    "LOCAL_DAEMON_SCHEMA_VERSION",
    "build_queue_cancel_result",
    "build_queue_drain_result",
    "build_slurm_drive_result",
    "build_queue_preflight_result",
    "build_queue_status_result",
    "handle_agent_init",
    "handle_agent_serve",
    "handle_cancel",
    "handle_drain_foreground",
    "handle_drive_slurm_foreground",
    "handle_daemon_cancel",
    "handle_daemon_agent_control",
    "handle_daemon_init",
    "handle_daemon_serve",
    "handle_daemon_status",
    "handle_daemon_scheduling_reload",
    "handle_daemon_time_recover",
    "handle_daemon_replace_agent_session",
    "handle_daemon_recover_unknown",
    "handle_daemon_submit",
    "handle_daemon_wait",
    "handle_preflight",
    "handle_start",
    "handle_status",
    "register_subparser",
]
