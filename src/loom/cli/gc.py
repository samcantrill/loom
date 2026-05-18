"""Implementation for ``loom gc`` collection cleanup."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loom.cli.authority import add_authority_options, authority_config_from_namespace
from loom.cli.cleanup_options import (
    add_cleanup_delete_options,
    add_cleanup_output_options,
    add_cleanup_selector_options,
    cleanup_delete_intent,
    cleanup_selector_from_namespace,
    create_cleanup_authority_store,
    managed_roots_for_run,
    require_delete_confirmation,
    selected_collection_candidate_ids,
)
from loom.cli.errors import CliError, ExitCode
from loom.cli.formatting import format_json_envelope
from loom.cli.options import OutputFormat, output_format_from_namespace
from loom.cli.results import CliWarning
from loom.serialization import PlainData

if TYPE_CHECKING:
    from loom.pipeline.cleanup import (
        CollectionCleanupReport,
        CollectionCleanupResult,
        CleanupSelector,
    )
    from loom.pipeline.stores import AuthorityConfig, PerRunAuthorityStore


GC_RESULT_SCHEMA_VERSION = "loom.cli.gc.v1"


@dataclass(frozen=True, slots=True)
class GcCliResult:
    """CLI-facing collection cleanup result."""

    collection: str
    action: str
    dry_run: bool
    report: "CollectionCleanupReport"
    result: "CollectionCleanupResult | None" = None
    warnings: tuple[CliWarning, ...] = ()

    @property
    def ok(self) -> bool:
        if self.result is None:
            return True
        return _summary_int(self.result.summary, "failed") == 0

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "collection": self.collection,
            "action": self.action,
            "dry_run": self.dry_run,
            "summary": _summary_for_output(self),
            "report": self.report.to_dict(),
            "result": None if self.result is None else self.result.to_dict(),
        }


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the gc subcommand."""

    parser = subparsers.add_parser("gc", help="preview or delete collection cleanup candidates")
    parser.add_argument("collection", metavar="COLLECTION", help="run collection path")
    add_cleanup_selector_options(parser)
    add_cleanup_delete_options(parser)
    add_authority_options(parser)
    add_cleanup_output_options(parser)
    parser.set_defaults(handler=handle)


def handle(namespace: argparse.Namespace) -> int:
    """Handle ``loom gc``."""

    selector = cleanup_selector_from_namespace(namespace)
    result = build_gc_result(
        Path(namespace.collection),
        selector=selector,
        delete=bool(namespace.delete),
        yes=bool(namespace.yes),
        delete_reason=namespace.delete_reason,
        authority_config=authority_config_from_namespace(namespace),
    )
    warnings = tuple(warning.to_dict() for warning in result.warnings)
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=GC_RESULT_SCHEMA_VERSION,
                ok=result.ok,
                warnings=warnings,
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_gc_text(result) + "\n")
    return int(ExitCode.SUCCESS if result.ok else ExitCode.RUN_STATE)


def build_gc_result(
    collection: Path,
    *,
    selector: "CleanupSelector | Mapping[str, PlainData] | None" = None,
    delete: bool = False,
    yes: bool = False,
    delete_reason: str | None = None,
    authority_config: "AuthorityConfig | None" = None,
    authority_store: "PerRunAuthorityStore | None" = None,
) -> GcCliResult:
    """Build a collection cleanup preview or deletion result."""

    store = authority_store or create_cleanup_authority_store(
        authority_config,
        owner_id="cleanup-gc-cli",
    )
    try:
        from loom.pipeline.cleanup import execute_collection_gc, plan_collection_gc

        targets, warnings = _collection_cleanup_targets(collection, store)
        report = plan_collection_gc(
            targets,
            selector=selector,
            metadata={"cli_action": "gc", "collection": str(collection)},
        )
        if not delete:
            return GcCliResult(
                collection=str(collection),
                action="dry_run",
                dry_run=True,
                report=report,
                warnings=warnings,
            )
        candidate_ids = selected_collection_candidate_ids(report)
        require_delete_confirmation(
            yes=yes,
            label=str(collection),
            selected_count=len(candidate_ids),
        )
        intent = cleanup_delete_intent(
            candidate_ids=candidate_ids,
            reason=delete_reason or "loom gc --delete",
            action="gc",
        )
        result = execute_collection_gc(
            targets,
            report,
            intent,
            metadata={"cli_action": "gc", "collection": str(collection)},
        )
    except CliError:
        raise
    except Exception as exc:
        raise CliError(
            str(exc),
            code="cli.gc.run_state_error",
            context={"collection": str(collection), "error_type": type(exc).__name__},
            exit_code=ExitCode.RUN_STATE,
        ) from exc
    return GcCliResult(
        collection=str(collection),
        action="delete",
        dry_run=False,
        report=report,
        result=result,
        warnings=warnings,
    )


def format_gc_text(result: GcCliResult) -> str:
    """Format a concise human-readable collection cleanup result."""

    summary = _summary_for_output(result)
    if result.result is None:
        lines = [
            (
                f"OK gc {result.collection}: dry-run runs={summary['runs']} "
                f"candidates={summary['candidates']} selected={summary['selected']} "
                f"skipped={summary['skipped']} rejected={summary['rejected']}"
            )
        ]
        for warning in result.warnings:
            lines.append(f"warning {warning.code}: {warning.message}")
        for run_report in result.report.reports:
            for entry in run_report.entries:
                lines.append(
                    f"{entry.status.value} {run_report.run_uri} {entry.candidate_id}: "
                    f"{entry.reason_code} {entry.target.uri}"
                )
        return "\n".join(lines)

    failed = _summary_int(summary, "failed")
    prefix = "OK" if failed == 0 else "WARN"
    lines = [
        (
            f"{prefix} gc {result.collection}: delete runs={summary['runs']} "
            f"deleted={summary['deleted']} skipped={summary['skipped']} "
            f"rejected={summary['rejected']} failed={summary['failed']}"
        )
    ]
    for warning in result.warnings:
        lines.append(f"warning {warning.code}: {warning.message}")
    for fact in result.result.results:
        for entry in fact.result.entries:
            lines.append(
                f"{entry.outcome.value} {fact.result.run_uri} {entry.candidate_id}: "
                f"{entry.reason_code} {entry.target.uri}"
            )
    return "\n".join(lines)


def _collection_cleanup_targets(
    collection: Path,
    store: "PerRunAuthorityStore",
):
    from loom.cli.runs import catalog_warnings_for_cli
    from loom.pipeline.cleanup import CollectionCleanupTarget
    from loom.runs import RunCatalog

    listing = RunCatalog.open(collection).list()
    warnings = catalog_warnings_for_cli(listing.warnings)
    targets = tuple(
        CollectionCleanupTarget(
            run_uri=summary.run_uri,
            store=store,
            managed_roots=managed_roots_for_run(summary.run_uri),
            metadata={"collection": str(collection)},
        )
        for summary in listing.summaries
    )
    return targets, warnings


def _summary_for_output(result: GcCliResult) -> dict[str, PlainData]:
    if result.result is None:
        return dict(result.report.summary)
    return {
        **dict(result.report.summary),
        **dict(result.result.summary),
    }


def _summary_int(summary: Mapping[str, PlainData], key: str) -> int:
    value = summary.get(key, 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


__all__ = [
    "GC_RESULT_SCHEMA_VERSION",
    "GcCliResult",
    "build_gc_result",
    "format_gc_text",
    "handle",
    "register_subparser",
]
