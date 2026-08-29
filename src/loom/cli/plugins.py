"""Implementation for ``loom plugins`` commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.cli.options import OutputFormat, output_format_from_namespace
from loom.plugins import (
    KNOWN_PLUGIN_GROUPS,
    PluginDiagnosticResult,
    PluginRecord,
    PluginSelection,
    check_plugin_records,
    list_entry_points,
    plugin_group_readiness,
    summarize_plugin_records,
)
from loom.plugins.entrypoints import EntryPointProvider

PLUGINS_LIST_SCHEMA_VERSION = "loom.cli.plugins.list.v2"
PLUGINS_CHECK_SCHEMA_VERSION = "loom.cli.plugins.check.v2"

_entry_point_provider: EntryPointProvider | None = None


def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the plugin inspection command group."""

    parser = subparsers.add_parser("plugins", help="inspect installed loom plugins")
    action_subparsers = parser.add_subparsers(dest="plugins_action", metavar="ACTION")

    list_parser = action_subparsers.add_parser("list", help="list advertised plugin entry points")
    _add_selection_options(list_parser)
    list_parser.add_argument(
        "--load",
        action="store_true",
        help="explicitly import selected recipe/codec plugin targets",
    )
    _add_output_options(list_parser)
    list_parser.set_defaults(handler=handle_list)

    check_parser = action_subparsers.add_parser("check", help="check selected plugin entry points")
    _add_selection_options(check_parser)
    _add_output_options(check_parser)
    check_parser.set_defaults(handler=handle_check)

    parser.set_defaults(handler=_missing_action)


def handle_list(namespace: argparse.Namespace) -> int:
    """Handle ``loom plugins list``."""

    selection = _selection_from_namespace(namespace)
    load_requested = bool(getattr(namespace, "load", False))
    if load_requested and selection.is_empty:
        raise CliError(
            "`loom plugins list --load` requires at least one plugin selector.",
            code="cli.plugins.load_requires_selector",
            hint="Use --group, --name, or --package to select trusted plugins to import.",
            exit_code=ExitCode.USAGE,
        )

    records = _list_records(groups=selection.groups or None)
    result = (
        check_plugin_records(records, selection=selection, load=True)
        if load_requested
        else summarize_plugin_records(records, selection=selection)
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=PLUGINS_LIST_SCHEMA_VERSION,
                ok=result.ok,
                warnings=[],
                payload_name="result",
                payload=_diagnostic_summary(result),
            )
        )
    else:
        sys.stdout.write(_format_list_text(result) + "\n")
    return int(ExitCode.SUCCESS if result.ok else ExitCode.PIPELINE)


def handle_check(namespace: argparse.Namespace) -> int:
    """Handle ``loom plugins check``."""

    selection = _selection_from_namespace(namespace)
    if selection.is_empty:
        raise CliError(
            "`loom plugins check` requires at least one plugin selector.",
            code="cli.plugins.check_requires_selector",
            hint="Use --group, --name, or --package to select trusted plugins to check.",
            exit_code=ExitCode.USAGE,
        )

    records = _list_records(groups=selection.groups or None)
    result = check_plugin_records(records, selection=selection, load=True)
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=PLUGINS_CHECK_SCHEMA_VERSION,
                ok=result.ok,
                warnings=[],
                payload_name="result",
                payload=_diagnostic_summary(result),
            )
        )
    else:
        sys.stdout.write(_format_check_text(result) + "\n")
    return int(ExitCode.SUCCESS if result.ok else ExitCode.PIPELINE)


def _add_selection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--group",
        dest="plugin_group",
        action="append",
        default=None,
        metavar="GROUP",
        help="plugin entry point group; may be repeated",
    )
    parser.add_argument(
        "--name",
        dest="plugin_name",
        action="append",
        default=None,
        metavar="NAME",
        help="plugin entry point name; may be repeated",
    )
    parser.add_argument(
        "--package",
        dest="plugin_package",
        action="append",
        default=None,
        metavar="PACKAGE",
        help="plugin distribution package; may be repeated",
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


def _selection_from_namespace(namespace: argparse.Namespace) -> PluginSelection:
    return PluginSelection(
        groups=tuple(getattr(namespace, "plugin_group", ()) or ()),
        names=tuple(getattr(namespace, "plugin_name", ()) or ()),
        packages=tuple(getattr(namespace, "plugin_package", ()) or ()),
    )


def _list_records(*, groups: Iterable[str] | None) -> tuple[PluginRecord, ...]:
    if _entry_point_provider is None:
        return list_entry_points(groups=groups)
    return list_entry_points(groups=groups, provider=_entry_point_provider)


def _format_list_text(result: PluginDiagnosticResult) -> str:
    prefix = "OK" if result.ok else "FAILED"
    suffix = "1 plugin" if len(result.records) == 1 else f"{len(result.records)} plugins"
    lines = [f"{prefix} plugins list: {suffix}"]
    lines.extend(_record_lines(result))
    lines.extend(_diagnostic_lines(result))
    return "\n".join(lines)


def _format_check_text(result: PluginDiagnosticResult) -> str:
    prefix = "OK" if result.ok else "FAILED"
    suffix = "1 plugin" if len(result.records) == 1 else f"{len(result.records)} plugins"
    lines = [f"{prefix} plugins check: {suffix}"]
    lines.extend(_record_lines(result))
    lines.extend(_diagnostic_lines(result))
    return "\n".join(lines)


def _record_lines(result: PluginDiagnosticResult) -> list[str]:
    summaries = result.to_summary()["records"]
    if not isinstance(summaries, list):
        return []
    lines: list[str] = []
    for item in summaries:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "metadata"))
        group = str(item.get("group", "<unknown>"))
        name = str(item.get("name", "<unknown>"))
        value = str(item.get("value", "<unknown>"))
        readiness = str(item.get("readiness", "listing-only"))
        package = item.get("package")
        package_suffix = "" if package is None else f" package={package}"
        lines.append(f"{status} {group} {name}: {value} [{readiness}]{package_suffix}")
    return lines


def _diagnostic_summary(result: PluginDiagnosticResult) -> dict[str, object]:
    """Return the v2 CLI payload while keeping Python result summaries compatible."""

    return {
        **result.to_summary(),
        "group_readiness": [
            plugin_group_readiness(group).to_summary() for group in KNOWN_PLUGIN_GROUPS
        ],
    }


def _diagnostic_lines(result: PluginDiagnosticResult) -> list[str]:
    lines: list[str] = []
    for name in KNOWN_PLUGIN_GROUPS:
        facets = plugin_group_readiness(name).to_summary()["facets"]
        if not isinstance(facets, dict):
            continue
        for facet, detail in facets.items():
            if not isinstance(detail, dict):
                continue
            lines.append(
                f"readiness {name} {facet}: {detail.get('status')} "
                f"{detail.get('evidence')}"
            )
    for missing in result.missing:
        lines.append(f"missing {missing.field}: {missing.value}")
    for group in result.unsupported_groups:
        lines.append(f"listing-only {group}: no Stage 14 registry loader")
    for duplicate in result.duplicates:
        lines.append(f"duplicate {duplicate.group} {duplicate.name}: {len(duplicate.records)} records")
    for failure in result.failures:
        lines.append(
            f"failed {failure.record.group} {failure.record.name}: "
            f"{failure.operation} {failure.error_type}: {failure.message}"
        )
    return lines


def _missing_action(_namespace: argparse.Namespace) -> int:
    raise CliError(
        "`loom plugins` requires an action.",
        code="cli.plugins.missing_action",
        hint="Use `loom plugins list` or `loom plugins check`.",
        exit_code=ExitCode.USAGE,
    )


__all__ = [
    "PLUGINS_CHECK_SCHEMA_VERSION",
    "PLUGINS_LIST_SCHEMA_VERSION",
    "handle_check",
    "handle_list",
    "register_subparser",
]
