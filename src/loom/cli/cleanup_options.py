"""Shared cleanup CLI parsing and safety helpers."""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loom.cli.errors import CliError, ExitCode
from loom.serialization import PlainData
from loom.timestamps import utc_timestamp

if TYPE_CHECKING:
    from loom.pipeline.cleanup import (
        CleanupDeleteIntent,
        CleanupManagedRoot,
        CleanupReport,
        CleanupSelector,
        CollectionCleanupReport,
    )
    from loom.pipeline.stores import AuthorityConfig, PerRunAuthorityStore


def add_cleanup_selector_options(parser: argparse.ArgumentParser) -> None:
    """Add bounded cleanup selector flags to a command parser."""

    parser.add_argument(
        "--older-than",
        type=parse_duration_seconds,
        metavar="DURATION",
        help="select candidates recorded at least this long ago, for example 7d",
    )
    parser.add_argument(
        "--recorded-before",
        metavar="TIMESTAMP",
        help="select candidates recorded before a UTC timestamp",
    )
    parser.add_argument(
        "--recorded-after",
        metavar="TIMESTAMP",
        help="select candidates recorded after a UTC timestamp",
    )
    parser.add_argument(
        "--candidate-kind",
        action="append",
        default=None,
        metavar="KIND",
        help="select candidates by cleanup candidate kind",
    )
    parser.add_argument(
        "--reason",
        dest="reason_code",
        action="append",
        default=None,
        metavar="CODE",
        help="select candidates by cleanup reason code",
    )
    parser.add_argument(
        "--retention-mode",
        action="append",
        default=None,
        metavar="MODE",
        help="select candidates by retention mode hint",
    )
    parser.add_argument(
        "--stage",
        dest="stage_name",
        action="append",
        default=None,
        metavar="STAGE",
        help="select candidates by stage name metadata",
    )
    parser.add_argument(
        "--artifact-id",
        action="append",
        default=None,
        metavar="ID",
        help="select candidates by artifact id metadata",
    )
    parser.add_argument(
        "--artifact-type",
        action="append",
        default=None,
        metavar="TYPE",
        help="select candidates by artifact type metadata",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        metavar="TAG",
        help="select candidates by tag metadata",
    )
    parser.add_argument(
        "--metadata",
        action="append",
        default=None,
        type=_required_key_value,
        metavar="KEY=VALUE",
        help="select candidates by exact string metadata value",
    )


def add_cleanup_delete_options(parser: argparse.ArgumentParser) -> None:
    """Add shared cleanup mutation flags."""

    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete selected cleanup targets after confirmation",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm deletion without an interactive prompt",
    )
    parser.add_argument(
        "--delete-reason",
        default=None,
        metavar="TEXT",
        help="reason recorded in cleanup delete intent",
    )


def add_cleanup_output_options(parser: argparse.ArgumentParser) -> None:
    """Add standard cleanup output options."""

    from loom.cli.options import OutputFormat

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


def cleanup_selector_from_namespace(namespace: argparse.Namespace) -> "CleanupSelector":
    """Build a cleanup selector from parsed CLI flags."""

    from loom.pipeline.cleanup import CleanupSelector

    return CleanupSelector(
        older_than_seconds=cast(int | None, namespace.older_than),
        recorded_before=cast(str | None, namespace.recorded_before),
        recorded_after=cast(str | None, namespace.recorded_after),
        candidate_kinds=_strings(namespace, "candidate_kind"),
        reason_codes=_strings(namespace, "reason_code"),
        retention_modes=_strings(namespace, "retention_mode"),
        stage_names=_strings(namespace, "stage_name"),
        artifact_ids=_strings(namespace, "artifact_id"),
        artifact_types=_strings(namespace, "artifact_type"),
        tags=_strings(namespace, "tag"),
        metadata_equals=dict(_metadata_pairs(namespace)),
    )


def parse_duration_seconds(value: str) -> int:
    """Parse a compact positive duration into seconds."""

    text = value.strip().lower()
    if not text:
        raise argparse.ArgumentTypeError("duration must not be empty")
    unit = text[-1]
    if unit in {"s", "m", "h", "d"}:
        number_text = text[:-1]
        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    else:
        number_text = text
        multiplier = 1
    try:
        number = int(number_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "duration must be a positive integer optionally suffixed with s, m, h, or d"
        ) from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("duration must be positive")
    return number * multiplier


def create_cleanup_authority_store(
    authority_config: "AuthorityConfig | None",
    *,
    owner_id: str,
) -> "PerRunAuthorityStore":
    """Create the authority store used by cleanup commands."""

    from loom.pipeline.execution import create_authority_backed_serial_run_store

    run_store = create_authority_backed_serial_run_store(
        "runs",
        authority_config=authority_config,
        owner_id=owner_id,
    )
    authority_store = getattr(run_store, "authority_store", None)
    if authority_store is None:
        raise CliError(
            "cleanup requires an authority-backed run store",
            code="cli.cleanup.authority_required",
            exit_code=ExitCode.RUN_STATE,
        )
    return cast("PerRunAuthorityStore", authority_store)


def managed_roots_for_run(run_uri: str) -> tuple["CleanupManagedRoot", ...]:
    """Return trusted local managed roots derived from the run URI."""

    from loom.pipeline.cleanup import CleanupManagedRoot
    from loom.pipeline.stores import path_to_run_uri, run_uri_to_path

    try:
        run_path = run_uri_to_path(run_uri)
    except Exception:
        return ()
    return (
        CleanupManagedRoot(
            root_id="run-root",
            uri=path_to_run_uri(Path(run_path)),
            metadata={"loom_owned": True, "source": "run_uri"},
        ),
    )


def selected_candidate_ids(report: "CleanupReport") -> tuple[str, ...]:
    """Return candidate ids selected by a per-run dry-run report."""

    from loom.pipeline.cleanup import CleanupReportEntryStatus

    return tuple(
        entry.candidate_id
        for entry in report.entries
        if entry.status is CleanupReportEntryStatus.SELECTED
    )


def selected_collection_candidate_ids(
    report: "CollectionCleanupReport",
) -> tuple[str, ...]:
    """Return selected candidate ids across a collection dry-run report."""

    from loom.pipeline.cleanup import CleanupReportEntryStatus

    return tuple(
        entry.candidate_id
        for run_report in report.reports
        for entry in run_report.entries
        if entry.status is CleanupReportEntryStatus.SELECTED
    )


def cleanup_delete_intent(
    *,
    candidate_ids: Sequence[str],
    reason: str,
    action: str,
) -> CleanupDeleteIntent:
    """Build a structured CLI delete intent."""

    from loom.pipeline.cleanup import CleanupDeleteIntent

    return CleanupDeleteIntent(
        intent_id=f"cleanup-cli-{uuid.uuid4().hex}",
        requested_by="loom-cli",
        requested_at=utc_timestamp(),
        reason=reason,
        candidate_ids=tuple(candidate_ids),
        metadata={"cli_action": action},
    )


def confirm_cleanup_delete(*, label: str, selected_count: int) -> bool:
    """Prompt for destructive cleanup confirmation."""

    sys.stderr.write(
        f"Delete {selected_count} selected cleanup target(s) for {label}? "
        "Type 'yes' to continue: "
    )
    sys.stderr.flush()
    return sys.stdin.readline().strip().lower() == "yes"


def require_delete_confirmation(
    *,
    yes: bool,
    label: str,
    selected_count: int,
) -> None:
    """Require either --yes or an affirmative prompt before deletion."""

    if yes:
        return
    if confirm_cleanup_delete(label=label, selected_count=selected_count):
        return
    raise CliError(
        "cleanup deletion was not confirmed",
        code="cli.cleanup.delete_not_confirmed",
        hint="Use --yes or answer yes at the confirmation prompt.",
        context={"selected_count": selected_count},
        exit_code=ExitCode.OPERATION_FAILED,
    )


def _strings(namespace: argparse.Namespace, attr: str) -> tuple[str, ...]:
    return tuple(str(value) for value in (getattr(namespace, attr, None) or ()))


def _metadata_pairs(namespace: argparse.Namespace) -> tuple[tuple[str, PlainData], ...]:
    pairs = cast(
        "list[tuple[str, str]] | tuple[tuple[str, str], ...] | None",
        getattr(namespace, "metadata", None),
    )
    return tuple((key, value) for key, value in (pairs or ()))


def _required_key_value(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    key, item = value.split("=", 1)
    if not key or not item:
        raise argparse.ArgumentTypeError("expected KEY=VALUE with non-empty parts")
    return key, item


__all__ = [
    "add_cleanup_delete_options",
    "add_cleanup_output_options",
    "add_cleanup_selector_options",
    "cleanup_delete_intent",
    "cleanup_selector_from_namespace",
    "confirm_cleanup_delete",
    "create_cleanup_authority_store",
    "managed_roots_for_run",
    "parse_duration_seconds",
    "require_delete_confirmation",
    "selected_candidate_ids",
    "selected_collection_candidate_ids",
]
