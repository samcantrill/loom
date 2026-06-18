"""CLI authority configuration helpers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loom.authority.supervisor import AuthoritySupervisorCommandResult
    from loom.pipeline.stores import AuthorityConfig
    from loom.pipeline.stores import AuthorityResolutionMode
    from loom.serialization import PlainData

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.cli.options import OutputFormat, output_format_from_namespace


_AUTHORITY_BACKEND_CHOICES = (
    "co_located_service",
    "managed_service",
    "allocation_scoped_service",
    "direct_database",
    "deferred_finalization",
    "test_fake",
)
_AUTHORITY_PROFILE_CHOICES = (
    "co_located",
    "managed_service",
    "allocation_scoped",
    "direct_database",
    "deferred_finalization",
)
_AUTHORITY_MODE_CHOICES = ("online_mutation", "offline_first")
AUTHORITY_LIFECYCLE_SCHEMA_VERSION = "loom.cli.authority.lifecycle.v1"
AUTHORITY_OFFLINE_IMPORT_SCHEMA_VERSION = "loom.cli.authority.offline_import.v1"


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register explicit authority supervisor lifecycle commands."""

    parser = subparsers.add_parser(
        "authority",
        help="manage an explicit local authority supervisor",
    )
    authority_subparsers = parser.add_subparsers(
        dest="authority_command",
        metavar="AUTHORITY_COMMAND",
    )

    start = authority_subparsers.add_parser(
        "start",
        help="start a local authority supervisor",
    )
    _add_supervisor_location_options(start, state_required=True)
    _add_process_options(start)
    _add_output_options(start)
    start.set_defaults(handler=handle_start)

    status = authority_subparsers.add_parser(
        "status",
        help="inspect local authority supervisor status",
    )
    _add_supervisor_location_options(status, state_required=False)
    _add_output_options(status)
    status.set_defaults(handler=handle_status)

    doctor = authority_subparsers.add_parser(
        "doctor",
        help="verify local authority supervisor readiness and registry state",
    )
    _add_supervisor_location_options(doctor, state_required=False)
    _add_output_options(doctor)
    doctor.set_defaults(handler=handle_doctor)

    stop = authority_subparsers.add_parser(
        "stop",
        help="stop a local authority supervisor",
    )
    _add_supervisor_location_options(stop, state_required=False)
    stop.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="seconds to wait for process termination",
    )
    _add_output_options(stop)
    stop.set_defaults(handler=handle_stop)

    restart = authority_subparsers.add_parser(
        "restart",
        help="restart a local authority supervisor with a new generation",
    )
    _add_supervisor_location_options(restart, state_required=True)
    _add_process_options(restart)
    _add_output_options(restart)
    restart.set_defaults(handler=handle_restart)

    import_offline = authority_subparsers.add_parser(
        "import-offline",
        help="import a v10 offline evidence manifest",
    )
    import_offline.add_argument("manifest", metavar="MANIFEST", help="manifest path")
    add_authority_options(import_offline)
    _add_output_options(import_offline)
    import_offline.set_defaults(handler=handle_import_offline)


def handle_start(namespace: argparse.Namespace) -> int:
    """Handle ``loom authority start``."""

    from loom.authority.supervisor import (
        AuthoritySupervisorError,
        start_authority_supervisor,
    )

    try:
        result = start_authority_supervisor(
            state_dir=namespace.state_dir,
            use_workspace_default=namespace.use_workspace_default,
            workspace_root=namespace.workspace_root,
            workspace_id=namespace.workspace_id,
            host=namespace.host,
            port=namespace.port,
            timeout_seconds=namespace.timeout,
        )
    except AuthoritySupervisorError as exc:
        raise _supervisor_cli_error(exc) from exc
    return _emit_result(result, namespace)


def handle_status(namespace: argparse.Namespace) -> int:
    """Handle ``loom authority status``."""

    from loom.authority.supervisor import inspect_authority_supervisor

    result = inspect_authority_supervisor(
        state_dir=namespace.state_dir,
        use_workspace_default=namespace.use_workspace_default,
        workspace_root=namespace.workspace_root,
        workspace_id=namespace.workspace_id,
        command="status",
    )
    return _emit_result(result, namespace)


def handle_doctor(namespace: argparse.Namespace) -> int:
    """Handle ``loom authority doctor``."""

    from loom.authority.supervisor import inspect_authority_supervisor

    result = inspect_authority_supervisor(
        state_dir=namespace.state_dir,
        use_workspace_default=namespace.use_workspace_default,
        workspace_root=namespace.workspace_root,
        workspace_id=namespace.workspace_id,
        command="doctor",
    )
    if not result.ok:
        raise CliError(
            "authority supervisor doctor found unhealthy state",
            code="cli.authority.doctor_failed",
            context={"result": result.to_dict()},
            exit_code=ExitCode.RUN_STATE,
        )
    return _emit_result(result, namespace)


def handle_stop(namespace: argparse.Namespace) -> int:
    """Handle ``loom authority stop``."""

    from loom.authority.supervisor import stop_authority_supervisor

    result = stop_authority_supervisor(
        state_dir=namespace.state_dir,
        use_workspace_default=namespace.use_workspace_default,
        workspace_root=namespace.workspace_root,
        workspace_id=namespace.workspace_id,
        timeout_seconds=namespace.timeout,
    )
    return _emit_result(result, namespace)


def handle_restart(namespace: argparse.Namespace) -> int:
    """Handle ``loom authority restart``."""

    from loom.authority.supervisor import (
        AuthoritySupervisorError,
        restart_authority_supervisor,
    )

    try:
        result = restart_authority_supervisor(
            state_dir=namespace.state_dir,
            use_workspace_default=namespace.use_workspace_default,
            workspace_root=namespace.workspace_root,
            workspace_id=namespace.workspace_id,
            host=namespace.host,
            port=namespace.port,
            timeout_seconds=namespace.timeout,
        )
    except AuthoritySupervisorError as exc:
        raise _supervisor_cli_error(exc) from exc
    return _emit_result(result, namespace)


def handle_import_offline(namespace: argparse.Namespace) -> int:
    """Handle ``loom authority import-offline``."""

    from pathlib import Path

    from loom.pipeline.offline_evidence import OfflineEvidenceError
    from loom.pipeline.offline_evidence import read_offline_evidence_manifest
    from loom.pipeline.stores import create_authority_client

    authority_config = authority_config_from_namespace(namespace)
    try:
        manifest = read_offline_evidence_manifest(Path(namespace.manifest))
    except OfflineEvidenceError as exc:
        cause = exc.__cause__
        raise CliError(
            "offline evidence manifest is invalid"
            if not isinstance(cause, OSError)
            else "offline evidence manifest is unreadable",
            code=(
                "cli.authority.offline_import_manifest_unreadable"
                if isinstance(cause, OSError)
                else "cli.authority.offline_import_manifest_invalid"
            ),
            context={
                "manifest": str(namespace.manifest),
                "error": str(exc),
            },
            exit_code=ExitCode.CONFIG,
        ) from exc
    client = create_authority_client(authority_config)
    response = client.import_offline_evidence(
        manifest.to_dict(),
        workspace_id=authority_config.workspace_id,
        imported_by="loom-authority-cli",
    )
    if not response.accepted or response.result is None:
        rejection = response.rejection
        raise CliError(
            "offline evidence import was rejected"
            if rejection is None
            else rejection.message,
            code="cli.authority.offline_import_rejected"
            if rejection is None
            else rejection.code,
            context={}
            if rejection is None
            else {
                "category": rejection.category.value,
                "detail": rejection.detail,
            },
            exit_code=ExitCode.RUN_STATE,
        )
    result = response.result.body.get("offline_import", {})
    if not isinstance(result, Mapping):
        result = {}
    return _emit_offline_import_result(result, namespace)


def add_authority_options(
    parser: argparse.ArgumentParser,
    *,
    include_resolution_mode: bool = False,
) -> None:
    """Add shared authority-selection options to a command parser."""

    parser.add_argument(
        "--authority-backend",
        choices=_AUTHORITY_BACKEND_CHOICES,
        help="authority backend kind",
    )
    parser.add_argument(
        "--authority-profile",
        choices=_AUTHORITY_PROFILE_CHOICES,
        help="authority deployment profile",
    )
    parser.add_argument(
        "--authority-endpoint",
        metavar="ENDPOINT",
        help="authority service endpoint",
    )
    parser.add_argument(
        "--authority-workspace",
        metavar="ID",
        help="authority workspace identifier",
    )
    parser.add_argument(
        "--authority-state",
        metavar="PATH",
        help="authority state reference",
    )
    parser.add_argument(
        "--authority-reference",
        metavar="ID",
        help="authority reference id",
    )
    parser.add_argument(
        "--authority-metadata-json",
        metavar="JSON",
        help=argparse.SUPPRESS,
    )
    if include_resolution_mode:
        parser.add_argument(
            "--authority-mode",
            choices=_AUTHORITY_MODE_CHOICES,
            help=argparse.SUPPRESS,
        )
        parser.add_argument(
            "--offline-first",
            action="store_true",
            help=argparse.SUPPRESS,
        )


def authority_config_from_namespace(namespace: Any) -> "AuthorityConfig":
    """Resolve authority config from CLI options and environment."""

    from loom.pipeline.stores import AuthorityConfigError, authority_config_from_mapping

    try:
        return authority_config_from_mapping(
            backend_kind=getattr(namespace, "authority_backend", None),
            deployment_profile=getattr(namespace, "authority_profile", None),
            endpoint=getattr(namespace, "authority_endpoint", None),
            workspace_id=getattr(namespace, "authority_workspace", None),
            state_path=getattr(namespace, "authority_state", None),
            reference_id=getattr(namespace, "authority_reference", None),
            metadata_json=getattr(namespace, "authority_metadata_json", None),
        )
    except AuthorityConfigError as exc:
        from loom.cli.errors import CliError, ExitCode

        raise CliError(
            f"authority configuration is invalid: {exc}",
            code="cli.authority.invalid_config",
            context={"error": str(exc)},
            exit_code=ExitCode.CONFIG,
        ) from exc


def authority_config_to_worker_args(config: "AuthorityConfig") -> tuple[str, ...]:
    """Return CLI args for worker/submitted-job handoff commands."""

    from loom.pipeline.stores import authority_config_to_cli_args

    return authority_config_to_cli_args(config)


def authority_resolution_mode_from_namespace(namespace: Any) -> "AuthorityResolutionMode":
    """Resolve authority mode from optional CLI namespace fields."""

    from loom.pipeline.stores import authority_resolution_mode_from_mapping

    return authority_resolution_mode_from_mapping(
        authority_mode=getattr(namespace, "authority_mode", None),
        offline_first=getattr(namespace, "offline_first", None),
    )


def authority_metadata_summary(config: "AuthorityConfig") -> "Mapping[str, PlainData]":
    """Return a redacted metadata summary for CLI result contexts."""

    return config.redacted_dict()


def _add_supervisor_location_options(
    parser: argparse.ArgumentParser,
    *,
    state_required: bool,
) -> None:
    parser.add_argument(
        "--state-dir",
        required=False,
        help="explicit authority supervisor state directory",
    )
    parser.add_argument(
        "--use-workspace-default",
        action="store_true",
        help=(
            "use <workspace-root>/.loom/authority/service as the explicit "
            "supervisor state directory"
        ),
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="workspace root for .loom/authority registry records",
    )
    parser.add_argument(
        "--workspace-id",
        help="workspace identifier to record in authority readiness and registry facts",
    )


def _add_process_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="host interface")
    parser.add_argument("--port", type=int, default=8765, help="port to bind")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="seconds to wait for readiness",
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


def _emit_result(
    result: "AuthoritySupervisorCommandResult",
    namespace: argparse.Namespace,
) -> int:
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=AUTHORITY_LIFECYCLE_SCHEMA_VERSION,
                ok=result.ok,
                warnings=(),
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(_format_supervisor_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def _emit_offline_import_result(
    result: "Mapping[str, PlainData]",
    namespace: argparse.Namespace,
) -> int:
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=AUTHORITY_OFFLINE_IMPORT_SCHEMA_VERSION,
                ok=True,
                warnings=(),
                payload_name="result",
                payload=result,
            )
        )
    else:
        sys.stdout.write(_format_offline_import_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def _format_offline_import_text(result: "Mapping[str, PlainData]") -> str:
    run_uri = result.get("run_uri", "<unknown>")
    status = result.get("status", "<unknown>")
    revision = result.get("revision_sequence", "<unknown>")
    stages = result.get("imported_stage_count", 0)
    artifacts = result.get("imported_artifact_count", 0)
    return (
        f"OK authority import-offline {run_uri}: {status} "
        f"revision={revision} stages={stages} artifacts={artifacts}"
    )


def _format_supervisor_text(result: "AuthoritySupervisorCommandResult") -> str:
    status = "OK" if result.ok else "WARN"
    lines = [f"{status} authority {result.command}: {result.readiness.value}"]
    if result.endpoint is not None:
        lines.append(f"endpoint: {result.endpoint}")
    if result.state_dir is not None:
        lines.append(f"state_dir: {result.state_dir}")
    if result.pid is not None:
        lines.append(f"pid: {result.pid} ({result.process_state.value})")
    lines.append(f"repository: {result.repository_state.value}")
    if result.registry_status is not None:
        lines.append(f"registry: {result.registry_status.value}")
    if result.service_generation is not None:
        lines.append(f"service_generation: {result.service_generation}")
    if result.generation_matches is not None:
        lines.append(f"generation_matches: {result.generation_matches}")
    for diagnostic in result.diagnostics:
        lines.append(f"{diagnostic.get('severity')}: {diagnostic.get('code')}: {diagnostic.get('message')}")
    return "\n".join(lines)


def _supervisor_cli_error(error: Exception) -> CliError:
    code = getattr(error, "code", "cli.authority.error")
    context = getattr(error, "context", {})
    if not isinstance(context, dict):
        context = {}
    exit_code = (
        ExitCode.USAGE
        if code
        in {
            "authority_supervisor.state_dir_required",
            "authority_supervisor.state_dir_conflict",
        }
        else ExitCode.RUN_STATE
    )
    return CliError(
        str(error),
        code=str(code).replace("authority_supervisor.", "cli.authority."),
        context=context,
        exit_code=exit_code,
    )


__all__ = [
    "AUTHORITY_LIFECYCLE_SCHEMA_VERSION",
    "AUTHORITY_OFFLINE_IMPORT_SCHEMA_VERSION",
    "add_authority_options",
    "authority_config_from_namespace",
    "authority_config_to_worker_args",
    "authority_metadata_summary",
    "authority_resolution_mode_from_namespace",
    "handle_doctor",
    "handle_restart",
    "handle_import_offline",
    "handle_start",
    "handle_status",
    "handle_stop",
    "register_subparser",
]
