"""Implementation for ``loom queue`` operational commands."""

from __future__ import annotations
import argparse
from collections.abc import Mapping
import json
import math
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING
from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.cli.options import OutputFormat, output_format_from_namespace
from loom.queue.errors import QueueConfigError, QueueError, QueueServiceError
from loom.serialization import PlainData

if TYPE_CHECKING:
    from collections.abc import Mapping
    from loom.coordinator import CoordinatorClient
QUEUE_PREFLIGHT_SCHEMA_VERSION = "loom.cli.queue.preflight.v1"
QUEUE_STATUS_SCHEMA_VERSION = "loom.cli.queue.status.v1"
QUEUE_CANCEL_SCHEMA_VERSION = "loom.cli.queue.cancel.v1"
QUEUE_DRAIN_SCHEMA_VERSION = "loom.cli.queue.drain.v1"
QUEUE_SLURM_DRIVE_SCHEMA_VERSION = "loom.cli.queue.slurm-drive.v1"
LOCAL_DAEMON_SCHEMA_VERSION = "loom.cli.queue.local-daemon.v5"
_AGENT_RELOAD_RECEIPT_WAIT_SECONDS = 10.0
_AGENT_RELOAD_RECEIPT_POLL_SECONDS = 0.05


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the queue command group."""
    parser = subparsers.add_parser("queue", help="operate a configured queue service")
    queue_subparsers = parser.add_subparsers(
        dest="queue_command", metavar="QUEUE_COMMAND"
    )
    daemon_check = queue_subparsers.add_parser(
        "daemon-check", help="validate one protected coordinator role configuration"
    )
    _add_role_config_arguments(daemon_check)
    daemon_check.add_argument(
        "--probe-io",
        action="store_true",
        help="probe writes only in existing execution-owned roots",
    )
    daemon_check.add_argument(
        "--probe-gpu",
        action="store_true",
        help="run an owned GPU test on an initialized, stopped local agent",
    )
    _add_output_options(daemon_check)
    daemon_check.set_defaults(handler=handle_daemon_check)
    daemon_init = queue_subparsers.add_parser(
        "daemon-init", help="initialize one protected coordinator deployment bundle"
    )
    _add_role_config_arguments(daemon_init)
    _add_output_options(daemon_init)
    daemon_init.set_defaults(handler=handle_daemon_init)
    daemon_upgrade = queue_subparsers.add_parser(
        "daemon-upgrade", help="offline upgrade a stopped coordinator root"
    )
    _add_role_config_arguments(daemon_upgrade)
    _add_output_options(daemon_upgrade)
    daemon_upgrade.set_defaults(handler=handle_daemon_upgrade)
    daemon_serve = queue_subparsers.add_parser(
        "daemon-serve", help="serve one initialized coordinator deployment bundle"
    )
    _add_role_config_arguments(daemon_serve)
    _add_output_options(daemon_serve)
    daemon_serve.set_defaults(handler=handle_daemon_serve)
    agent_check = queue_subparsers.add_parser(
        "agent-check", help="validate one protected outbound-agent role configuration"
    )
    _add_role_config_arguments(agent_check)
    agent_check.add_argument(
        "--probe-io",
        action="store_true",
        help="probe writes only in existing execution-owned roots",
    )
    agent_check.add_argument(
        "--probe-gpu",
        action="store_true",
        help="run an owned GPU test on an initialized, stopped agent",
    )
    _add_output_options(agent_check)
    agent_check.set_defaults(handler=handle_agent_check)
    agent_init = queue_subparsers.add_parser(
        "agent-init", help="initialize one protected outbound-agent root"
    )
    _add_role_config_arguments(agent_init)
    _add_output_options(agent_init)
    agent_init.set_defaults(handler=handle_agent_init)
    reboot = queue_subparsers.add_parser("agent-recover-reboot", help="prove retained local launches contained after a Linux reboot")
    _add_role_config_arguments(reboot)
    reboot.add_argument("--operation-id", required=True)
    _add_output_options(reboot)
    reboot.set_defaults(handler=handle_agent_recover_reboot)
    agent_serve = queue_subparsers.add_parser(
        "agent-serve", help="serve one initialized outbound-agent root"
    )
    _add_role_config_arguments(agent_serve)
    _add_output_options(agent_serve)
    agent_serve.set_defaults(handler=handle_agent_serve)
    for command, help_text, handler in (
        ("daemon-submit", "submit one persisted run", handle_daemon_submit),
        ("daemon-status", "inspect daemon status", handle_daemon_status),
        ("daemon-wait", "wait for one admitted run", handle_daemon_wait),
        ("daemon-cancel", "cancel one admitted run", handle_daemon_cancel),
    ):
        daemon_client = queue_subparsers.add_parser(command, help=help_text)
        _add_client_connection_arguments(daemon_client)
        if command != "daemon-status":
            daemon_client.add_argument("queue_item_id", metavar="QUEUE_ITEM_ID")
        if command == "daemon-submit":
            daemon_client.add_argument("run_uri", metavar="RUN_URI")
        if command == "daemon-wait":
            daemon_client.add_argument("--timeout", type=float, default=None)
        _add_output_options(daemon_client)
        daemon_client.set_defaults(handler=handler)
    prepare = queue_subparsers.add_parser(
        "daemon-prepare", help="durably accept one shared preparation request"
    )
    _add_client_connection_arguments(prepare)
    prepare.add_argument("--request", type=Path, required=True, metavar="PATH")
    _add_output_options(prepare)
    prepare.set_defaults(handler=handle_daemon_prepare)
    cancel_preparation = queue_subparsers.add_parser(
        "daemon-cancel-preparation", help="request cancellation of one preparation"
    )
    _add_client_connection_arguments(cancel_preparation)
    cancel_preparation.add_argument("operation_id", metavar="OPERATION_ID")
    _add_output_options(cancel_preparation)
    cancel_preparation.set_defaults(handler=handle_daemon_cancel_preparation)
    start_run = queue_subparsers.add_parser(
        "daemon-start-run", help="durably accept preparation and exact target admission"
    )
    _add_client_connection_arguments(start_run)
    start_run.add_argument("--request", type=Path, required=True, metavar="PATH")
    _add_output_options(start_run)
    start_run.set_defaults(handler=handle_daemon_start_run)
    cancel_run = queue_subparsers.add_parser(
        "daemon-cancel-run", help="explicitly cancel a durable run operation"
    )
    _add_client_connection_arguments(cancel_run)
    cancel_run.add_argument("operation_id", metavar="OPERATION_ID")
    _add_output_options(cancel_run)
    cancel_run.set_defaults(handler=handle_daemon_cancel_run)
    admissions = queue_subparsers.add_parser(
        "daemon-admissions", help="list bounded managed admissions"
    )
    _add_client_connection_arguments(admissions)
    admissions.add_argument("--limit", type=int, default=100)
    admissions.add_argument("--cursor")
    admissions.set_defaults(handler=handle_daemon_admissions)
    _add_output_options(admissions)
    admission = queue_subparsers.add_parser(
        "daemon-admission", help="inspect one managed admission"
    )
    _add_client_connection_arguments(admission)
    admission.add_argument("admission_id")
    admission.set_defaults(handler=handle_daemon_admission)
    _add_output_options(admission)
    agents = queue_subparsers.add_parser("daemon-agents", help="list bounded agents")
    _add_client_connection_arguments(agents)
    agents.add_argument("--limit", type=int, default=100)
    agents.add_argument("--cursor")
    agents.set_defaults(handler=handle_daemon_agents)
    _add_output_options(agents)
    agent = queue_subparsers.add_parser(
        "daemon-agent", help="inspect one managed agent"
    )
    _add_client_connection_arguments(agent)
    agent.add_argument("agent_id")
    agent.set_defaults(handler=handle_daemon_agent)
    _add_output_options(agent)
    operation = queue_subparsers.add_parser(
        "daemon-operation", help="inspect one durable operation"
    )
    _add_client_connection_arguments(operation)
    operation.add_argument("operation_id")
    operation.set_defaults(handler=handle_daemon_operation)
    _add_output_options(operation)
    operation_wait = queue_subparsers.add_parser(
        "daemon-operation-wait", help="wait for one durable operation"
    )
    _add_client_connection_arguments(operation_wait)
    operation_wait.add_argument("operation_id")
    operation_wait.add_argument("--timeout", type=float, default=None)
    operation_wait.set_defaults(handler=handle_daemon_operation_wait)
    _add_output_options(operation_wait)
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


def handle_daemon_check(namespace: argparse.Namespace) -> int:
    """Report coordinator and optional local-agent readiness without initialization."""
    return _handle_role_check(namespace, "coordinator")


def handle_daemon_init(namespace: argparse.Namespace) -> int:
    """Atomically initialize one complete coordinator deployment bundle."""
    from loom.queue import LocalDaemon
    from loom.queue.deployment import load_coordinator_service_config

    try:
        service = load_coordinator_service_config(
            namespace.config, env_file=namespace.env_file
        )
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
    """Run the shared foreground coordinator composition."""
    from threading import Event
    from loom.queue.deployment import load_coordinator_service_config
    from loom.service_runtime import serve_coordinator

    try:
        service = load_coordinator_service_config(
            namespace.config, env_file=namespace.env_file
        )

        def ready(status, port):
            _emit_daemon_payload(
                namespace,
                {
                    "operation": "serve",
                    "endpoint": str(service.daemon.endpoint),
                    "agent_port": port,
                    "coordinator_id": status.coordinator_id,
                    "coordinator_epoch": status.coordinator_epoch,
                },
            )

        serve_coordinator(service, stop=Event(), ready=ready)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return int(ExitCode.SUCCESS)


def handle_agent_check(namespace: argparse.Namespace) -> int:
    """Report outbound-agent readiness without initializing its root."""
    return _handle_role_check(namespace, "agent")


def _handle_role_check(namespace: argparse.Namespace, role: str) -> int:
    from typing import cast
    from loom.diagnostics.models import PreflightStatus
    from loom.queue.preflight import run_role_preflight

    result = run_role_preflight(
        namespace.config,
        role=role,
        env_file=namespace.env_file,
        probe_io=namespace.probe_io,
        probe_gpu=namespace.probe_gpu,
    )
    ok = result.status is not PreflightStatus.FAIL
    payload = result.to_dict()
    payload["operation"] = "check" if role == "coordinator" else "agent-check"
    capacity = next(
        (check for check in result.checks if check.check_id == "resources.capacity"),
        None,
    )
    payload["effective_capacity"] = (
        None
        if capacity is None
        else cast("Mapping[str, PlainData]", capacity.details["evidence"]).get(
            "effective_capacity"
        )
    )
    if output_format_from_namespace(namespace) is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=LOCAL_DAEMON_SCHEMA_VERSION,
                ok=ok,
                warnings=[],
                payload_name="result",
                payload=payload,
            )
        )
    else:
        for check in result.checks:
            sys.stdout.write(
                f"{check.status.value:4}  {check.check_id}  {check.message}\n"
            )
            if check.status.value == "FAIL":
                sys.stdout.write(f"      Repair: {check.details['repair']}\n")
    return int(ExitCode.SUCCESS if ok else ExitCode.CONFIG)


def handle_agent_init(namespace: argparse.Namespace) -> int:
    """Atomically initialize one complete outbound-agent role root."""
    from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
    from loom.queue.deployment import load_outbound_agent_service_config

    try:
        service = load_outbound_agent_service_config(
            namespace.config, env_file=namespace.env_file
        )
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


def handle_agent_recover_reboot(namespace: argparse.Namespace) -> int:
    """Persist native reboot containment without starting or releasing work."""
    from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
    from loom.queue.deployment import load_outbound_agent_service_config

    try:
        service = load_outbound_agent_service_config(
            namespace.config, env_file=namespace.env_file
        )
        result = LocalDaemonAgentHttpClient.recover_reboot(
            service.client, namespace.operation_id
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result)


def handle_agent_serve(namespace: argparse.Namespace) -> int:
    """Run one foreground outbound agent with bounded reconnect."""
    from threading import Event
    from loom.queue.deployment import (
        load_outbound_agent_service_config,
        run_outbound_agent_service,
    )

    stop = Event()
    handled_signals = (signal.SIGINT, signal.SIGTERM)
    previous_handlers = {
        handled_signal: signal.getsignal(handled_signal)
        for handled_signal in handled_signals
    }

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    try:
        for handled_signal in handled_signals:
            signal.signal(handled_signal, request_stop)
        service = load_outbound_agent_service_config(
            namespace.config, env_file=namespace.env_file
        )
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
            stop=stop,
            trusted_config_loader=lambda: load_outbound_agent_service_config(
                service.source_path, env_file=service.environment_path
            ),
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    finally:
        for handled_signal, previous_handler in previous_handlers.items():
            signal.signal(handled_signal, previous_handler)
    return int(ExitCode.SUCCESS)


def handle_daemon_submit(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemonAdmissionRequest

    try:
        result = _daemon_client(namespace).submit(
            LocalDaemonAdmissionRequest(namespace.queue_item_id, namespace.run_uri)
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_upgrade(namespace: argparse.Namespace) -> int:
    from loom.queue import LocalDaemon
    from loom.queue.deployment import load_coordinator_service_config

    try:
        service = load_coordinator_service_config(
            namespace.config, env_file=namespace.env_file, _allow_unready=True
        )
        coordinator_id, schema_version = LocalDaemon.upgrade_coordinator_root(
            service.daemon
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(
        namespace, {"coordinator_id": coordinator_id, "schema_version": schema_version}
    )


def handle_daemon_prepare(namespace: argparse.Namespace) -> int:
    from loom.queue.preparation import PrepareRunRequest

    try:
        raw = json.loads(namespace.request.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise QueueServiceError("prepare request must be a JSON object")
        result = _daemon_client(namespace).prepare_run(PrepareRunRequest.from_dict(raw))
    except (OSError, json.JSONDecodeError) as exc:
        raise _queue_cli_error(
            QueueServiceError("prepare request file is unavailable or invalid JSON")
        ) from exc
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_cancel_preparation(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).cancel_preparation(namespace.operation_id)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_start_run(namespace: argparse.Namespace) -> int:
    from loom.coordinator import RunRequest

    try:
        raw = json.loads(namespace.request.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise QueueServiceError("run request must be a JSON object")
        request = RunRequest.from_dict(raw)
        result = _daemon_client(namespace).start_run(request)
    except (OSError, json.JSONDecodeError) as exc:
        raise _queue_cli_error(
            QueueServiceError("run request file is unavailable or invalid JSON")
        ) from exc
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_cancel_run(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).cancel_run_operation(namespace.operation_id)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def _daemon_client(namespace: argparse.Namespace) -> CoordinatorClient:
    """Select the unified native client for every coordinator client command."""
    from loom.coordinator import CoordinatorClient

    if namespace.connection is not None:
        return CoordinatorClient.from_connection_file(
            namespace.connection,
            expected_coordinator_id=namespace.expected_coordinator_id,
        )
    return CoordinatorClient.from_unix_socket(
        namespace.endpoint, expected_coordinator_id=namespace.expected_coordinator_id
    )


def handle_daemon_status(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).status()
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_admissions(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).admissions(
            limit=namespace.limit, cursor=namespace.cursor
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_admission(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).admission(namespace.admission_id)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_admission_payload(namespace, result.to_dict())


def handle_daemon_agents(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).agents(
            limit=namespace.limit, cursor=namespace.cursor
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_agent(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).agent(namespace.agent_id)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_operation(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).operation(namespace.operation_id)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_operation_wait(namespace: argparse.Namespace) -> int:
    try:
        if namespace.timeout is not None and (
            not math.isfinite(namespace.timeout) or namespace.timeout < 0
        ):
            raise QueueServiceError("operation wait timeout is invalid")
        client = _daemon_client(namespace)
        deadline = (
            None if namespace.timeout is None else time.monotonic() + namespace.timeout
        )
        while True:
            duration = (
                25.0
                if deadline is None
                else max(0.0, min(25.0, deadline - time.monotonic()))
            )
            result = client.wait_operation(
                namespace.operation_id, timeout_seconds=duration
            )
            if result.kind.value != "TIMEOUT" or (
                deadline is not None and time.monotonic() >= deadline
            ):
                break
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_wait(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).wait(
            namespace.queue_item_id, timeout_seconds=namespace.timeout
        )
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_cancel(namespace: argparse.Namespace) -> int:
    try:
        result = _daemon_client(namespace).cancel(namespace.queue_item_id)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_daemon_agent_control(namespace: argparse.Namespace) -> int:
    from loom.queue import AgentControl, LocalDaemonSocketClient

    try:
        control = AgentControl(
            operation_id=namespace.operation_id,
            kind=namespace.agent_control,
            agent_id=namespace.agent_id,
            expected_session_id=namespace.session_id,
            expected_config_revision=namespace.config_revision,
            pool=namespace.pool,
            cancel_active=bool(namespace.cancel_active),
            reason=namespace.reason,
        )
        client = LocalDaemonSocketClient(namespace.endpoint)
        result = client.control_agent(control)
        if namespace.agent_control == "reload":
            deadline = time.monotonic() + _AGENT_RELOAD_RECEIPT_WAIT_SECONDS
            while (
                result.get("state") in {"pending_delivery", "applying"}
                and time.monotonic() < deadline
            ):
                time.sleep(_AGENT_RELOAD_RECEIPT_POLL_SECONDS)
                result = client.control_agent(control)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    exit_code = _emit_daemon_payload(namespace, result)
    return (
        int(ExitCode.PIPELINE)
        if result.get("code") == "reload_rejected"
        or (namespace.agent_control == "reload" and result.get("state") != "applied")
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
        if result.get("code") == "reload_rejected" or result.get("state") != "applied"
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


def _emit_daemon_admission_payload(
    namespace: argparse.Namespace, payload: Mapping[str, PlainData]
) -> int:
    """Present an admission while preserving its generic JSON envelope."""
    if output_format_from_namespace(namespace) is OutputFormat.JSON:
        return _emit_daemon_payload(namespace, payload)
    result = _emit_daemon_payload(namespace, payload)
    diagnostic = _admission_diagnostic_failure(payload)
    if diagnostic is not None:
        sys.stdout.write("  run-result diagnostic failure:\n")
        for line in diagnostic.splitlines():
            sys.stdout.write(f"    {line}\n")
    for line in _admission_execution_failure_lines(payload):
        sys.stdout.write(f"  {line}\n")
    return result


def _admission_execution_failure_lines(payload: Mapping[str, PlainData]) -> list[str]:
    """Render portable Loom wrapper chains without interpreting domain payloads."""
    from collections.abc import Mapping, Sequence
    from loom.diagnostics import render_diagnostic_failure

    owners = payload.get("owners")
    if not isinstance(owners, Mapping):
        return []
    owner = owners.get("run_result")
    if not isinstance(owner, Mapping) or owner.get("availability") != "available":
        return []
    failures = owner.get("failures", ())
    if not isinstance(failures, Sequence) or isinstance(failures, str):
        return []
    lines: list[str] = []
    for failure in failures:
        indent = ""
        while isinstance(failure, Mapping):
            lines.append(
                f"{indent}stage {failure.get('stage_name')!r} failure: {failure.get('message')}"
            )
            details = failure.get("details")
            if not isinstance(details, Mapping):
                break
            diagnostic = details.get("diagnostic_failure")
            if diagnostic is not None:
                lines.extend(
                    (
                        indent + "  " + line
                        for line in render_diagnostic_failure(diagnostic).splitlines()
                    )
                )
            traceback_text = details.get("traceback")
            if isinstance(traceback_text, str):
                lines.extend(
                    (indent + "  " + line for line in traceback_text.splitlines())
                )
            failure = details.get("worker_failure")
            indent += "  "
    return lines


def _admission_diagnostic_failure(payload: Mapping[str, PlainData]) -> str | None:
    owners = payload.get("owners")
    if not isinstance(owners, Mapping):
        return None
    run_result = owners.get("run_result")
    if not isinstance(run_result, Mapping):
        return None
    if run_result.get("availability") != "unavailable":
        return None
    detail = run_result.get("diagnostic_failure")
    if detail is None:
        return "diagnostic failure detail not provided"
    from loom.diagnostics import render_diagnostic_failure

    return render_diagnostic_failure(detail)


def _enum_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("config", metavar="CONFIG", help="queue config path")


def _add_role_config_arguments(parser: argparse.ArgumentParser) -> None:
    _add_config_argument(parser)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="owner-protected dotenv file used only for this role configuration",
    )


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


def _add_client_connection_arguments(parser: argparse.ArgumentParser) -> None:
    connection = parser.add_mutually_exclusive_group(required=True)
    connection.add_argument("--endpoint", type=Path)
    connection.add_argument("--connection", type=Path)
    parser.add_argument("--expected-coordinator-id")


__all__ = [
    "QUEUE_CANCEL_SCHEMA_VERSION",
    "QUEUE_DRAIN_SCHEMA_VERSION",
    "QUEUE_SLURM_DRIVE_SCHEMA_VERSION",
    "QUEUE_PREFLIGHT_SCHEMA_VERSION",
    "QUEUE_STATUS_SCHEMA_VERSION",
    "LOCAL_DAEMON_SCHEMA_VERSION",
    "handle_agent_init",
    "handle_agent_recover_reboot",
    "handle_agent_check",
    "handle_agent_serve",
    "handle_daemon_cancel",
    "handle_daemon_cancel_preparation",
    "handle_daemon_start_run",
    "handle_daemon_cancel_run",
    "handle_daemon_admission",
    "handle_daemon_admissions",
    "handle_daemon_agent",
    "handle_daemon_agents",
    "handle_daemon_agent_control",
    "handle_daemon_init",
    "handle_daemon_upgrade",
    "handle_daemon_check",
    "handle_daemon_serve",
    "handle_daemon_status",
    "handle_daemon_operation",
    "handle_daemon_operation_wait",
    "handle_daemon_scheduling_reload",
    "handle_daemon_time_recover",
    "handle_daemon_replace_agent_session",
    "handle_daemon_recover_unknown",
    "handle_daemon_submit",
    "handle_daemon_prepare",
    "handle_daemon_wait",
]
