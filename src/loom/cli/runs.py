"""Implementation for ``loom runs`` catalog commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import (
    format_json_envelope,
    format_runs_diff_text,
    format_runs_index_text,
    format_runs_list_text,
)
from loom.cli.options import OutputFormat, output_format_from_namespace
from loom.cli.results import CliWarning

if TYPE_CHECKING:
    from loom.runs import CatalogIndexResult, ListRunsResult, RunComparison, RunFilter


RUNS_INDEX_SCHEMA_VERSION = "loom.cli.runs.index.v1"
RUNS_LIST_SCHEMA_VERSION = "loom.cli.runs.list.v1"
RUNS_DIFF_SCHEMA_VERSION = "loom.cli.runs.diff.v1"


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the runs command group."""

    parser = subparsers.add_parser("runs", help="inspect local run collections")
    actions = parser.add_subparsers(dest="runs_action", metavar="ACTION")
    actions.required = True

    index_parser = actions.add_parser("index", help="rebuild a run catalog index")
    index_parser.add_argument("collection", metavar="COLLECTION", help="run collection path")
    _add_output_options(index_parser)
    index_parser.set_defaults(handler=handle_index)

    list_parser = actions.add_parser("list", help="list current run summaries")
    list_parser.add_argument("collection", metavar="COLLECTION", help="run collection path")
    list_parser.add_argument("--status", action="append", default=None, metavar="STATUS")
    list_parser.add_argument(
        "--tag",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        type=_required_key_value,
        help="filter by tag key/value",
    )
    list_parser.add_argument(
        "--config-fingerprint",
        action="append",
        default=None,
        metavar="VALUE",
    )
    list_parser.add_argument(
        "--pipeline-fingerprint",
        action="append",
        default=None,
        metavar="VALUE",
    )
    list_parser.add_argument("--commit", action="append", default=None, metavar="VALUE")
    list_parser.add_argument(
        "--stage-status",
        action="append",
        default=None,
        metavar="[STAGE=]STATUS",
        type=_optional_key_value,
    )
    list_parser.add_argument(
        "--artifact",
        action="append",
        default=None,
        metavar="[NAME=]ARTIFACT_ID",
        type=_optional_key_value,
    )
    list_parser.add_argument(
        "--artifact-checksum",
        action="append",
        default=None,
        metavar="[NAME=]CHECKSUM",
        type=_optional_key_value,
    )
    list_parser.add_argument("--executor", action="append", default=None, metavar="VALUE")
    list_parser.add_argument("--backend", action="append", default=None, metavar="VALUE")
    _add_output_options(list_parser)
    list_parser.set_defaults(handler=handle_list)

    diff_parser = actions.add_parser("diff", help="compare two runs by metadata")
    diff_parser.add_argument("collection", metavar="COLLECTION", help="run collection path")
    diff_parser.add_argument("left_run_uri", metavar="LEFT_RUN_URI", help="left run URI")
    diff_parser.add_argument("right_run_uri", metavar="RIGHT_RUN_URI", help="right run URI")
    _add_output_options(diff_parser)
    diff_parser.set_defaults(handler=handle_diff)


def handle_index(namespace: argparse.Namespace) -> int:
    """Handle ``loom runs index``."""

    collection = Path(namespace.collection)
    result = build_runs_index_result(collection)
    warnings = catalog_warnings_for_cli(result.warnings)
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=RUNS_INDEX_SCHEMA_VERSION,
                ok=True,
                warnings=warnings,
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(
            format_runs_index_text(
                result,
                collection_path=collection,
                warnings=warnings,
            )
            + "\n"
        )
    return int(ExitCode.SUCCESS)


def handle_list(namespace: argparse.Namespace) -> int:
    """Handle ``loom runs list``."""

    collection = Path(namespace.collection)
    filters = filters_from_namespace(namespace)
    result = build_runs_list_result(collection, filters)
    warnings = catalog_warnings_for_cli(result.warnings)
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=RUNS_LIST_SCHEMA_VERSION,
                ok=True,
                warnings=warnings,
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(
            format_runs_list_text(
                result,
                collection_path=collection,
                warnings=warnings,
            )
            + "\n"
        )
    return int(ExitCode.SUCCESS)


def handle_diff(namespace: argparse.Namespace) -> int:
    """Handle ``loom runs diff``."""

    collection = Path(namespace.collection)
    result = build_runs_diff_result(
        collection,
        str(namespace.left_run_uri),
        str(namespace.right_run_uri),
    )
    warnings = catalog_warnings_for_cli(result.warnings)
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=RUNS_DIFF_SCHEMA_VERSION,
                ok=True,
                warnings=warnings,
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_runs_diff_text(result, warnings=warnings) + "\n")
    return int(ExitCode.SUCCESS)


def build_runs_index_result(collection: Path) -> "CatalogIndexResult":
    """Rebuild the catalog sidecar for a collection."""

    from loom.runs import CatalogError, RunCatalog

    try:
        return RunCatalog.open(collection).rebuild()
    except CatalogError as exc:
        raise _catalog_cli_error(exc) from exc


def build_runs_list_result(
    collection: Path,
    filters: tuple["RunFilter", ...],
) -> "ListRunsResult":
    """List current run summaries for a collection."""

    from loom.runs import CatalogError, RunCatalog

    try:
        return RunCatalog.open(collection).list(filters=filters)
    except CatalogError as exc:
        raise _catalog_cli_error(exc) from exc


def build_runs_diff_result(
    collection: Path,
    left_run_uri: str,
    right_run_uri: str,
) -> "RunComparison":
    """Compare two runs from a collection."""

    from loom.runs import CatalogError, RunCatalog

    try:
        return RunCatalog.open(collection).compare(left_run_uri, right_run_uri)
    except CatalogError as exc:
        raise _catalog_cli_error(exc) from exc


def filters_from_namespace(namespace: argparse.Namespace) -> tuple["RunFilter", ...]:
    """Build run catalog filters from parsed CLI options."""

    from loom.runs import RunFilter, RunFilterKind

    filters: list[RunFilter] = []
    filters.extend(
        RunFilter(RunFilterKind.RUN_STATUS, value)
        for value in _string_values(namespace, "status")
    )
    filters.extend(
        RunFilter(RunFilterKind.TAG, value, key=key)
        for key, value in _key_value_pairs(namespace, "tag")
    )
    filters.extend(
        RunFilter(RunFilterKind.CONFIG_FINGERPRINT, value)
        for value in _string_values(namespace, "config_fingerprint")
    )
    filters.extend(
        RunFilter(RunFilterKind.PIPELINE_FINGERPRINT, value)
        for value in _string_values(namespace, "pipeline_fingerprint")
    )
    filters.extend(
        RunFilter(RunFilterKind.GIT_COMMIT, value)
        for value in _string_values(namespace, "commit")
    )
    filters.extend(
        RunFilter(RunFilterKind.STAGE_STATUS, value, key=key)
        for key, value in _key_value_pairs(namespace, "stage_status")
    )
    filters.extend(
        RunFilter(RunFilterKind.ARTIFACT_IDENTITY, value, key=key)
        for key, value in _key_value_pairs(namespace, "artifact")
    )
    filters.extend(
        RunFilter(RunFilterKind.ARTIFACT_CHECKSUM, value, key=key)
        for key, value in _key_value_pairs(namespace, "artifact_checksum")
    )
    filters.extend(
        RunFilter(RunFilterKind.EXECUTOR, value)
        for value in _string_values(namespace, "executor")
    )
    filters.extend(
        RunFilter(RunFilterKind.BACKEND, value)
        for value in _string_values(namespace, "backend")
    )
    return tuple(filters)


def catalog_warnings_for_cli(warnings: object) -> tuple[CliWarning, ...]:
    """Convert catalog warnings into CLI warning payloads."""

    raw_warnings = cast("list[object] | tuple[object, ...] | None", warnings)
    output: list[CliWarning] = []
    for warning in tuple(raw_warnings or ()):
        code = getattr(getattr(warning, "code", "warning"), "value", None)
        if code is None:
            code = str(getattr(warning, "code", "warning"))
        details = dict(getattr(warning, "details", {}) or {})
        run_uri = getattr(warning, "run_uri", None)
        path = getattr(warning, "path", None)
        if run_uri is not None:
            details["run_uri"] = run_uri
        if path is not None:
            details["path"] = path
        output.append(
            CliWarning(
                code=str(code),
                message=str(getattr(warning, "message", "")),
                details=details,
            )
        )
    return tuple(output)


def _string_values(namespace: argparse.Namespace, attr: str) -> tuple[str, ...]:
    return tuple(str(value) for value in (getattr(namespace, attr, None) or ()))


def _key_value_pairs(
    namespace: argparse.Namespace, attr: str
) -> tuple[tuple[str | None, str], ...]:
    values = cast(
        "list[tuple[str | None, str]] | tuple[tuple[str | None, str], ...] | None",
        getattr(namespace, attr, None),
    )
    return tuple(values or ())


def _required_key_value(value: str) -> tuple[str, str]:
    key, item = _split_key_value(value)
    if key is None:
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    return key, item


def _optional_key_value(value: str) -> tuple[str | None, str]:
    return _split_key_value(value)


def _split_key_value(value: str) -> tuple[str | None, str]:
    if "=" not in value:
        if not value:
            raise argparse.ArgumentTypeError("value must not be empty")
        return None, value
    key, item = value.split("=", 1)
    if not key or not item:
        raise argparse.ArgumentTypeError("expected KEY=VALUE with non-empty parts")
    return key, item


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


def _catalog_cli_error(error: BaseException) -> CliError:
    return CliError(
        str(error),
        code="cli.runs.catalog_error",
        context={"error_type": type(error).__name__},
        exit_code=ExitCode.RUN_STATE,
    )


__all__ = [
    "RUNS_DIFF_SCHEMA_VERSION",
    "RUNS_INDEX_SCHEMA_VERSION",
    "RUNS_LIST_SCHEMA_VERSION",
    "build_runs_diff_result",
    "build_runs_index_result",
    "build_runs_list_result",
    "catalog_warnings_for_cli",
    "filters_from_namespace",
    "handle_diff",
    "handle_index",
    "handle_list",
    "register_subparser",
]
