"""Implementation for ``loom clean``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from dataclasses import dataclass
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
    selected_candidate_ids,
)
from loom.cli.errors import CliError, ExitCode
from loom.cli.options import OutputFormat, output_format_from_namespace
from loom.cli.formatting import format_json_envelope
from loom.serialization import PlainData

if TYPE_CHECKING:
    from loom.pipeline.cleanup import CleanupReport, CleanupSelector
    from loom.pipeline.stores import (
        AuthorityConfig,
        CleanupResultFact,
        PerRunAuthorityStore,
    )


CLEAN_RESULT_SCHEMA_VERSION = "loom.cli.clean.v1"


@dataclass(frozen=True, slots=True)
class CleanCliResult:
    """CLI-facing cleanup result for one run."""

    run_uri: str
    action: str
    dry_run: bool
    report: "CleanupReport"
    result: "CleanupResultFact | None" = None

    @property
    def ok(self) -> bool:
        if self.result is None:
            return True
        return _summary_int(self.result.result.summary, "failed") == 0

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "run_uri": self.run_uri,
            "action": self.action,
            "dry_run": self.dry_run,
            "summary": _summary_for_output(self),
            "report": self.report.to_dict(),
            "result": None if self.result is None else self.result.to_dict(),
        }


def register_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the clean subcommand."""

    parser = subparsers.add_parser("clean", help="preview or delete cleanup candidates")
    parser.add_argument("run_uri", metavar="RUN_URI", help="run URI to clean")
    add_cleanup_selector_options(parser)
    add_cleanup_delete_options(parser)
    add_authority_options(parser)
    add_cleanup_output_options(parser)
    parser.set_defaults(handler=handle)


def handle(namespace: argparse.Namespace) -> int:
    """Handle ``loom clean``."""

    selector = cleanup_selector_from_namespace(namespace)
    result = build_clean_result(
        str(namespace.run_uri),
        selector=selector,
        delete=bool(namespace.delete),
        yes=bool(namespace.yes),
        delete_reason=namespace.delete_reason,
        authority_config=authority_config_from_namespace(namespace),
    )
    output_format = output_format_from_namespace(namespace)
    if output_format is OutputFormat.JSON:
        sys.stdout.write(
            format_json_envelope(
                schema_version=CLEAN_RESULT_SCHEMA_VERSION,
                ok=result.ok,
                warnings=(),
                payload_name="result",
                payload=result.to_dict(),
            )
        )
    else:
        sys.stdout.write(format_clean_text(result) + "\n")
    return int(ExitCode.SUCCESS if result.ok else ExitCode.RUN_STATE)


def build_clean_result(
    run_uri: str,
    *,
    selector: "CleanupSelector | Mapping[str, PlainData] | None" = None,
    delete: bool = False,
    yes: bool = False,
    delete_reason: str | None = None,
    authority_config: "AuthorityConfig | None" = None,
    authority_store: "PerRunAuthorityStore | None" = None,
) -> CleanCliResult:
    """Build a cleanup preview or deletion result for one run."""

    store = authority_store or create_cleanup_authority_store(
        authority_config,
        owner_id="cleanup-cli",
    )
    roots = managed_roots_for_run(run_uri)
    try:
        from loom.pipeline.cleanup import execute_cleanup, plan_cleanup

        report = plan_cleanup(
            store,
            run_uri,
            selector=selector,
            managed_roots=roots,
            metadata={"cli_action": "clean"},
        )
        if not delete:
            return CleanCliResult(
                run_uri=run_uri,
                action="dry_run",
                dry_run=True,
                report=report,
            )
        candidate_ids = selected_candidate_ids(report)
        require_delete_confirmation(
            yes=yes,
            label=run_uri,
            selected_count=len(candidate_ids),
        )
        intent = cleanup_delete_intent(
            candidate_ids=candidate_ids,
            reason=delete_reason or "loom clean --delete",
            action="clean",
        )
        result = execute_cleanup(
            store,
            run_uri,
            report,
            intent,
            managed_roots=roots,
            metadata={"cli_action": "clean"},
        )
    except CliError:
        raise
    except Exception as exc:
        raise CliError(
            str(exc),
            code="cli.clean.run_state_error",
            context={"run_uri": run_uri, "error_type": type(exc).__name__},
            exit_code=ExitCode.RUN_STATE,
        ) from exc
    return CleanCliResult(
        run_uri=run_uri,
        action="delete",
        dry_run=False,
        report=report,
        result=result,
    )


def format_clean_text(result: CleanCliResult) -> str:
    """Format a concise human-readable cleanup result."""

    summary = _summary_for_output(result)
    if result.result is None:
        prefix = "OK"
        lines = [
            (
                f"{prefix} clean {result.run_uri}: dry-run "
                f"candidates={summary['candidates']} selected={summary['selected']} "
                f"skipped={summary['skipped']} rejected={summary['rejected']}"
            )
        ]
        for entry in result.report.entries:
            lines.append(
                f"{entry.status.value} {entry.candidate_id}: "
                f"{entry.reason_code} {entry.target.uri}"
            )
        return "\n".join(lines)

    failed = _summary_int(summary, "failed")
    prefix = "OK" if failed == 0 else "WARN"
    lines = [
        (
            f"{prefix} clean {result.run_uri}: delete "
            f"deleted={summary['deleted']} skipped={summary['skipped']} "
            f"rejected={summary['rejected']} failed={summary['failed']}"
        )
    ]
    for entry in result.result.result.entries:
        lines.append(
            f"{entry.outcome.value} {entry.candidate_id}: "
            f"{entry.reason_code} {entry.target.uri}"
        )
    return "\n".join(lines)


def _summary_for_output(result: CleanCliResult) -> dict[str, PlainData]:
    if result.result is None:
        return dict(result.report.summary)
    return {
        **dict(result.report.summary),
        **dict(result.result.result.summary),
    }


def _summary_int(summary: Mapping[str, PlainData], key: str) -> int:
    value = summary.get(key, 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


__all__ = [
    "CLEAN_RESULT_SCHEMA_VERSION",
    "CleanCliResult",
    "build_clean_result",
    "format_clean_text",
    "handle",
    "register_subparser",
]
