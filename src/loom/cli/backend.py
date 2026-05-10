"""Implementation for ``loom backend`` diagnostics commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from loom.cli.authority import add_authority_options, authority_config_from_namespace
from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.cli.options import OutputFormat, output_format_from_namespace

if TYPE_CHECKING:
    from loom.diagnostics.backend import (
        BackendCapabilitiesResult,
        BackendInspectionResult,
    )


BACKEND_INSPECT_SCHEMA_VERSION = "loom.cli.backend.inspect.v1"
BACKEND_CAPABILITIES_SCHEMA_VERSION = "loom.cli.backend.capabilities.v1"


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the backend diagnostics command group."""

    parser = subparsers.add_parser(
        "backend", help="inspect authoritative backend state"
    )
    backend_subparsers = parser.add_subparsers(
        dest="backend_command", metavar="BACKEND_COMMAND"
    )

    inspect = backend_subparsers.add_parser(
        "inspect", help="inspect one authoritative run backend"
    )
    inspect.add_argument("run_uri", metavar="RUN_URI", help="run URI to inspect")
    inspect.add_argument("--stage", metavar="STAGE", help="include one stage only")
    inspect.add_argument(
        "--verify-materialization",
        action="store_true",
        help="verify materialized reference existence and checksums",
    )
    inspect.add_argument(
        "--projection-revision",
        metavar="SEQUENCE:TOKEN",
        help="compare against read-only projection revision evidence",
    )
    add_authority_options(inspect)
    _add_output_options(inspect)
    inspect.set_defaults(handler=handle_inspect)

    capabilities = backend_subparsers.add_parser(
        "capabilities", help="inspect backend capabilities"
    )
    capabilities.add_argument("run_uri", metavar="RUN_URI", help="run URI to inspect")
    capabilities.add_argument(
        "--require-shared-filesystem",
        action="store_true",
        help="fail if shared-filesystem safety is not proven",
    )
    capabilities.add_argument(
        "--require-remote",
        action="store_true",
        help="fail if remote coordination is not supported",
    )
    add_authority_options(capabilities)
    _add_output_options(capabilities)
    capabilities.set_defaults(handler=handle_capabilities)


def handle_inspect(namespace: argparse.Namespace) -> int:
    """Handle ``loom backend inspect``."""

    from loom.diagnostics.backend import BackendDiagnosticsError, inspect_backend

    output_format = output_format_from_namespace(namespace)
    try:
        result = inspect_backend(
            str(namespace.run_uri),
            stage_name=getattr(namespace, "stage", None),
            verify_materialization=bool(
                getattr(namespace, "verify_materialization", False)
            ),
            projection_revision=getattr(namespace, "projection_revision", None),
            authority_config=authority_config_from_namespace(namespace),
        )
    except BackendDiagnosticsError as exc:
        raise _backend_error(exc) from exc
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=BACKEND_INSPECT_SCHEMA_VERSION,
                ok=True,
                warnings=_warning_envelope(result.warnings),
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(_format_inspect_text(result) + "\n")
    return int(ExitCode.SUCCESS)


def handle_capabilities(namespace: argparse.Namespace) -> int:
    """Handle ``loom backend capabilities``."""

    from loom.diagnostics.backend import (
        BackendDiagnosticsError,
        inspect_backend_capabilities,
    )

    output_format = output_format_from_namespace(namespace)
    try:
        result = inspect_backend_capabilities(
            str(namespace.run_uri),
            require_shared_filesystem=bool(
                getattr(namespace, "require_shared_filesystem", False)
            ),
            require_remote=bool(getattr(namespace, "require_remote", False)),
            authority_config=authority_config_from_namespace(namespace),
        )
    except BackendDiagnosticsError as exc:
        raise _backend_error(exc) from exc
    if result.has_error_diagnostics:
        raise CliError(
            _capability_failure_message(result),
            code="cli.backend.unsupported_capability",
            context={"result": result.to_dict()},
            exit_code=ExitCode.RUN_STATE,
        )
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=BACKEND_CAPABILITIES_SCHEMA_VERSION,
                ok=True,
                warnings=_warning_envelope(result.diagnostics),
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(_format_capabilities_text(result) + "\n")
    return int(ExitCode.SUCCESS)


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


def _backend_error(error: object) -> CliError:
    to_dict = getattr(error, "to_dict", None)
    payload = to_dict() if callable(to_dict) else {}
    context = payload.get("context", {}) if isinstance(payload, Mapping) else {}
    diagnostics = (
        payload.get("diagnostics", ()) if isinstance(payload, Mapping) else ()
    )
    if not isinstance(context, Mapping):
        context = {}
    return CliError(
        str(error),
        code=str(getattr(error, "code", "cli.backend.error")),
        context={**dict(context), "diagnostics": tuple(diagnostics)},
        exit_code=ExitCode.RUN_STATE,
    )


def _format_inspect_text(result: "BackendInspectionResult") -> str:
    counts = dict(result.counts)
    lines = [
        f"backend inspect {result.run_uri}: {result.status}",
        f"backend: {result.backend_name}",
        (
            "revision: "
            f"{result.revision.get('sequence')}:{result.revision.get('token')}"
        ),
        (
            "counts: "
            f"stages={counts.get('stages', 0)} "
            f"attempts={counts.get('attempts', 0)} "
            f"leases={counts.get('active_leases', 0)} "
            f"commits={counts.get('commits', 0)} "
            f"artifacts={counts.get('artifact_facts', 0)}"
        ),
    ]
    for stage in result.stages:
        lines.append(
            "stage "
            f"{stage.get('stage_name')}: {stage.get('status')} "
            f"attempts={stage.get('attempt_count', 0)} "
            f"artifacts={stage.get('artifact_count', 0)}"
        )
    _extend_warning_lines(lines, result.warnings)
    return "\n".join(lines)


def _format_capabilities_text(result: "BackendCapabilitiesResult") -> str:
    supported = sum(
        1 for capability in result.capabilities
        if capability.get("support") == "supported"
    )
    lines = [
        f"backend capabilities {result.run_uri}: {result.backend_name}",
        f"capabilities: {supported} supported of {len(result.capabilities)}",
    ]
    for capability in result.capabilities:
        suffix = ""
        if capability.get("message"):
            suffix = f" - {capability.get('message')}"
        lines.append(
            "  "
            f"{capability.get('scope')}.{capability.get('capability')}: "
            f"{capability.get('support')}{suffix}"
        )
    _extend_warning_lines(lines, result.diagnostics)
    return "\n".join(lines)


def _capability_failure_message(result: "BackendCapabilitiesResult") -> str:
    diagnostics = [
        f"{diagnostic.get('code')}: {diagnostic.get('message')}"
        for diagnostic in result.diagnostics
        if diagnostic.get("severity") == "error"
    ]
    message = "backend capabilities do not satisfy requested requirements"
    if diagnostics:
        message = f"{message}: {'; '.join(diagnostics)}"
    return message


def _extend_warning_lines(
    lines: list[str], warnings: Sequence[Mapping[str, object]]
) -> None:
    if not warnings:
        return
    lines.append("warnings:")
    for warning in warnings:
        lines.append(f"  {warning.get('code')}: {warning.get('message')}")


def _warning_envelope(
    warnings: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "code": str(warning.get("code", "backend.warning")),
            "message": str(warning.get("message", "")),
            "details": warning.get("detail", warning.get("details", {})),
        }
        for warning in warnings
    )


__all__ = [
    "BACKEND_CAPABILITIES_SCHEMA_VERSION",
    "BACKEND_INSPECT_SCHEMA_VERSION",
    "handle_capabilities",
    "handle_inspect",
    "register_subparser",
]
