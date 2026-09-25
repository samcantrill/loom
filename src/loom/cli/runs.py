"""Implementation for ``loom runs`` catalog commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import (
    format_json_envelope,
    format_runs_export_text,
    format_runs_diff_text,
    format_runs_import_text,
    format_runs_index_text,
    format_runs_inspect_text,
    format_runs_list_text,
)
from loom.cli.options import OutputFormat, output_format_from_namespace
from loom.cli.results import CliWarning
from loom.serialization import PlainData

if TYPE_CHECKING:
    from loom.runs import (
        CatalogIndexResult,
        ListRunsResult,
        RunBundleExportOptions,
        RunBundleExportResult,
        RunBundleImportPolicy,
        RunBundleImportResult,
        RunBundleInspection,
        RunComparison,
        RunFilter,
    )


RUNS_INDEX_SCHEMA_VERSION = "loom.cli.runs.index.v1"
RUNS_LIST_SCHEMA_VERSION = "loom.cli.runs.list.v1"
RUNS_DIFF_SCHEMA_VERSION = "loom.cli.runs.diff.v1"
RUNS_EXPORT_SCHEMA_VERSION = "loom.cli.runs.export.v1"
RUNS_INSPECT_SCHEMA_VERSION = "loom.cli.runs.inspect.v1"
RUNS_IMPORT_SCHEMA_VERSION = "loom.cli.runs.import.v1"


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the runs command group."""

    parser = subparsers.add_parser("runs", help="inspect local run collections")
    actions = parser.add_subparsers(dest="runs_action", metavar="ACTION")
    actions.required = True

    from .queue import _add_client_connection_arguments

    for action in ("search", "submissions", "jobs", "fields", "tags"):
        query_parser = actions.add_parser(action, help="query native run discovery")
        _add_client_connection_arguments(query_parser)
        _add_output_options(query_parser)
        query_parser.add_argument("--query", default='{"schema_version":1}', help="structured query JSON object")
        query_parser.add_argument("--scope", choices=("managed", "collection"))
        query_parser.add_argument("--limit", type=int)
        query_parser.add_argument("--cursor")
        query_parser.add_argument("--tag", action="append", type=_required_key_value, default=[])
        query_parser.add_argument("--entity", choices=("runs", "submissions", "jobs"), default="runs")
        query_parser.add_argument("--key", help="literal tag key whose values to discover")
        query_parser.set_defaults(handler=handle_query)

    context_parser = actions.add_parser("context", help="read native submission context and annotations")
    context_parser.add_argument("run_uri")
    _add_client_connection_arguments(context_parser)
    _add_output_options(context_parser)
    context_parser.set_defaults(handler=handle_context)

    annotate = actions.add_parser("annotate", help="patch current annotations with an explicit revision and mutation ID")
    annotate.add_argument("run_uri")
    annotate.add_argument("--mutation-id", required=True)
    annotate.add_argument("--patch", required=True, help="JSON object including expected_revision and requested changes")
    _add_client_connection_arguments(annotate)
    _add_output_options(annotate)
    annotate.set_defaults(handler=handle_annotations)

    notes = actions.add_parser("notes", help="list notes or append an observation")
    notes.add_argument("run_uri")
    notes.add_argument("--text", help="append this text; requires --mutation-id")
    notes.add_argument("--mutation-id")
    notes.add_argument("--limit", type=int, default=50)
    notes.add_argument("--cursor")
    _add_client_connection_arguments(notes)
    _add_output_options(notes)
    notes.set_defaults(handler=handle_annotations)

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

    export_parser = actions.add_parser("export", help="export a completed run bundle")
    export_parser.add_argument("run_uri", metavar="RUN_URI", help="completed run URI")
    export_parser.add_argument("destination", metavar="DESTINATION", help="bundle archive path")
    export_parser.add_argument(
        "--include-payloads",
        action="store_true",
        help="include artifact payloads in the bundle",
    )
    export_parser.add_argument(
        "--include-logs",
        action="store_true",
        help="include stage log refs in the bundle",
    )
    export_parser.add_argument(
        "--include-workspace",
        action="store_true",
        help="include config, provenance, and worker handoff refs",
    )
    export_parser.add_argument(
        "--verify-checksums",
        action="store_true",
        help="verify materialized checksums while exporting",
    )
    export_parser.add_argument(
        "--max-payload-count",
        type=_positive_int,
        metavar="N",
        help="fail if payload selection exceeds this count",
    )
    _add_output_options(export_parser)
    export_parser.set_defaults(handler=handle_export)

    inspect_parser = actions.add_parser(
        "inspect",
        help="inspect a run bundle without extracting it",
    )
    inspect_parser.add_argument("bundle", metavar="BUNDLE", help="bundle archive path")
    inspect_parser.add_argument(
        "--verify-checksums",
        action="store_true",
        help="verify bundle member checksums during inspection",
    )
    _add_output_options(inspect_parser)
    inspect_parser.set_defaults(handler=handle_inspect)

    import_parser = actions.add_parser("import", help="import a run bundle")
    import_parser.add_argument("bundle", metavar="BUNDLE", help="bundle archive path")
    import_parser.add_argument(
        "target_collection",
        metavar="TARGET_COLLECTION",
        help="target local run collection path",
    )
    _add_output_options(import_parser)
    import_parser.set_defaults(handler=handle_import)


def handle_query(namespace: argparse.Namespace) -> int:
    """Translate JSON and simple literal tag conveniences to one native query."""
    import json
    from .queue import _daemon_client, _emit_daemon_payload, _queue_cli_error
    from loom.queue.errors import QueueError
    from loom.queue._coordinator_control import control_error

    operation = {"search": "search_runs", "submissions": "search_submissions", "jobs": "search_jobs", "fields": "query_fields", "tags": "tag_keys"}[namespace.runs_action]
    try:
        query = json.loads(namespace.query)
        if not isinstance(query, dict):
            raise ValueError("query must be an object")
        if namespace.scope:
            query["scope"] = {"kind": "managed"} if namespace.scope == "managed" else {"kind": "collection", "name": "run_store"}
        for key in ("limit", "cursor"):
            if getattr(namespace, key) is not None:
                query[key] = getattr(namespace, key)
        if namespace.tag:
            terms = [query.get("where", {"kind": "all", "terms": []})]
            terms.extend({"kind": "compare", "field": {"source": "tags", "path": [key]}, "op": "eq", "value": value} for key, value in namespace.tag)
            query["where"] = {"kind": "all", "terms": terms}
        payload = {"query": query}
        if namespace.runs_action == "fields":
            payload = {"entity": namespace.entity}
        elif namespace.runs_action == "tags":
            payload = {"scope": query.get("scope", {"kind": "managed"}), "limit": query.get("limit", 50), "cursor": query.get("cursor")}
            if namespace.key is not None:
                operation = "tag_values"
                payload["key"] = namespace.key
        with _daemon_client(namespace) as client:
            result = client._native_call(operation, payload, None)
    except (ValueError, TypeError) as exc:
        raise _queue_cli_error(control_error("invalid_request", operation, {})) from exc
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict() if hasattr(result, "to_dict") else result)


def handle_context(namespace: argparse.Namespace) -> int:
    """Read context through the existing native coordinator connection."""
    from .queue import _daemon_client, _emit_daemon_payload, _queue_cli_error
    from loom.queue.errors import QueueError

    try:
        with _daemon_client(namespace) as client:
            result = client.get_run_context(namespace.run_uri)
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


def handle_annotations(namespace: argparse.Namespace) -> int:
    """Keep CAS and receipt semantics at the native coordinator boundary."""
    import json
    from .queue import _daemon_client, _emit_daemon_payload, _queue_cli_error
    from loom.queue.errors import QueueError
    from loom.queue._coordinator_control import control_error

    operation = "patch_run_annotations" if namespace.runs_action == "annotate" else "append_run_note" if namespace.text is not None else "list_run_notes"
    payload: dict[str, PlainData] = {"run_uri": namespace.run_uri}
    try:
        if operation == "patch_run_annotations":
            payload.update(mutation_id=namespace.mutation_id, patch=json.loads(namespace.patch))
        elif operation == "append_run_note":
            payload.update(mutation_id=namespace.mutation_id, text=namespace.text)
        else:
            if namespace.mutation_id is not None:
                raise ValueError("--mutation-id requires --text")
            payload.update(limit=namespace.limit, cursor=namespace.cursor)
        with _daemon_client(namespace) as client:
            result = client._native_call(operation, payload, None)
    except (ValueError, TypeError) as exc:
        raise _queue_cli_error(control_error("invalid_request", operation, payload)) from exc
    except QueueError as exc:
        raise _queue_cli_error(exc) from exc
    return _emit_daemon_payload(namespace, result.to_dict())


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


def handle_export(namespace: argparse.Namespace) -> int:
    """Handle ``loom runs export``."""

    destination = Path(namespace.destination)
    options = export_options_from_namespace(namespace)
    result = build_runs_export_result(str(namespace.run_uri), destination, options)
    output_format = output_format_from_namespace(namespace)
    ok = _exchange_result_ok(result)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=RUNS_EXPORT_SCHEMA_VERSION,
                ok=ok,
                warnings=(),
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(
            format_runs_export_text(result, destination_path=destination) + "\n"
        )
    return int(ExitCode.SUCCESS if ok else ExitCode.RUN_STATE)


def handle_inspect(namespace: argparse.Namespace) -> int:
    """Handle ``loom runs inspect``."""

    bundle = Path(namespace.bundle)
    result = build_runs_inspect_result(
        bundle,
        verify_checksums=bool(namespace.verify_checksums),
    )
    output_format = output_format_from_namespace(namespace)
    ok = _exchange_result_ok(result)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=RUNS_INSPECT_SCHEMA_VERSION,
                ok=ok,
                warnings=(),
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_runs_inspect_text(result, bundle_path=bundle) + "\n")
    return int(ExitCode.SUCCESS if ok else ExitCode.RUN_STATE)


def handle_import(namespace: argparse.Namespace) -> int:
    """Handle ``loom runs import``."""

    bundle = Path(namespace.bundle)
    target_collection = Path(namespace.target_collection)
    policy = import_policy_from_namespace(namespace)
    result = build_runs_import_result(bundle, target_collection, policy)
    output_format = output_format_from_namespace(namespace)
    ok = _exchange_result_ok(result)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=RUNS_IMPORT_SCHEMA_VERSION,
                ok=ok,
                warnings=(),
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(
            format_runs_import_text(
                result,
                bundle_path=bundle,
                target_collection=target_collection,
            )
            + "\n"
        )
    return int(ExitCode.SUCCESS if ok else ExitCode.RUN_STATE)


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


def build_runs_export_result(
    run_uri: str,
    destination: Path,
    options: "RunBundleExportOptions",
) -> "RunBundleExportResult":
    """Export a local completed run bundle."""

    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.runs import export_run_bundle

    try:
        return export_run_bundle(
            SQLitePerRunAuthorityStore(run_uri),
            run_uri,
            destination,
            options=options,
        )
    except Exception as exc:
        raise _exchange_cli_error("export", exc) from exc


def build_runs_inspect_result(
    bundle: Path,
    *,
    verify_checksums: bool = False,
) -> "RunBundleInspection":
    """Inspect a local completed run bundle without extraction."""

    from loom.runs import inspect_run_bundle

    try:
        return inspect_run_bundle(bundle, verify_checksums=verify_checksums)
    except Exception as exc:
        raise _exchange_cli_error("inspect", exc) from exc


def build_runs_import_result(
    bundle: Path,
    target_collection: Path,
    policy: "RunBundleImportPolicy",
) -> "RunBundleImportResult":
    """Import a local completed run bundle into a target collection."""

    from loom.runs import import_run_bundle

    try:
        return import_run_bundle(bundle, target_collection, policy=policy)
    except Exception as exc:
        raise _exchange_cli_error("import", exc) from exc


def export_options_from_namespace(
    namespace: argparse.Namespace,
) -> "RunBundleExportOptions":
    """Build bundle export options from parsed CLI flags."""

    from loom.runs import RunBundleExportOptions

    return RunBundleExportOptions(
        include_payloads=bool(namespace.include_payloads),
        include_logs=bool(namespace.include_logs),
        include_workspace=bool(namespace.include_workspace),
        verify_checksums=bool(namespace.verify_checksums),
        max_payload_count=cast(int | None, namespace.max_payload_count),
    )


def import_policy_from_namespace(
    namespace: argparse.Namespace,
) -> "RunBundleImportPolicy":
    """Build the strict v12 bundle import policy from parsed CLI flags."""

    del namespace
    from loom.runs import RunBundleImportPolicy

    return RunBundleImportPolicy()


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


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


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


def _exchange_cli_error(operation: str, error: BaseException) -> CliError:
    return CliError(
        str(error),
        code=f"cli.runs.{operation}_error",
        context={
            "operation": operation,
            "error_type": type(error).__name__,
        },
        exit_code=ExitCode.RUN_STATE,
    )


def _exchange_result_ok(result: object) -> bool:
    status = getattr(getattr(result, "status", None), "value", None)
    if status is None:
        status = str(getattr(result, "status", ""))
    return str(status) == "succeeded"


__all__ = [
    "RUNS_DIFF_SCHEMA_VERSION",
    "RUNS_EXPORT_SCHEMA_VERSION",
    "RUNS_INDEX_SCHEMA_VERSION",
    "RUNS_IMPORT_SCHEMA_VERSION",
    "RUNS_INSPECT_SCHEMA_VERSION",
    "RUNS_LIST_SCHEMA_VERSION",
    "build_runs_diff_result",
    "build_runs_export_result",
    "build_runs_index_result",
    "build_runs_import_result",
    "build_runs_inspect_result",
    "build_runs_list_result",
    "catalog_warnings_for_cli",
    "export_options_from_namespace",
    "filters_from_namespace",
    "handle_export",
    "handle_diff",
    "handle_index",
    "handle_import",
    "handle_inspect",
    "handle_list",
    "import_policy_from_namespace",
    "register_subparser",
]
