"""Inert coordinator projection of retained submissions and authority annotations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import TYPE_CHECKING, cast

from loom.runs.context import RunAnnotations, RunContext
from loom.serialization import PlainData

if TYPE_CHECKING:
    from .local_daemon import LocalDaemon


def annotation_operation(daemon: LocalDaemon, operation: str, value: Mapping[str, object], principal: str) -> object:
    """Use coordinator-authorized authority ownership, retaining legacy evidence."""
    from loom.pipeline.stores.local_runs import LocalRunStore
    from loom.runs.context import SubmissionContext

    run_uri = cast(str, value["run_uri"])
    context = get_run_context(daemon, run_uri, None)  # Includes the existing ownership check.
    factory = daemon.config.coordinator_authority_factory
    if factory is None:
        raise OSError("annotation authority unavailable")
    authority = factory(run_uri)
    runtime = LocalRunStore(daemon.config.run_store_root).read_runtime_metadata(run_uri) or {}
    notes = runtime.get("notes", ())
    if not isinstance(notes, (list, tuple)) or any(not isinstance(note, str) for note in notes):
        raise ValueError("legacy runtime notes are unrepresentable")
    legacy_notes = cast(tuple[str, ...], tuple(notes))
    if operation == "list_run_notes":
        return authority.list_run_notes(run_uri, cast(int, value["limit"]), cast(str | None, value["cursor"]), legacy_notes)
    legacy = SubmissionContext(tags=cast(Mapping[str, str], runtime.get("tags", {}))) if context.annotations is None or context.annotations.revision == 0 else SubmissionContext()
    change = cast(Mapping[str, object], value["patch"]) if operation == "patch_run_annotations" else {"text": value["text"]}
    return authority.mutate_run_annotations(run_uri, principal, cast(str, value["mutation_id"]), operation, change, legacy, legacy_notes)


def get_run_context(
    daemon: LocalDaemon,
    run_uri: str,
    inspect_run: Callable[[str], Mapping[str, PlainData]] | None,
) -> RunContext:
    from .local_daemon import AdmissionNotFoundError

    with daemon._connection() as conn:
        rows = conn.execute(
            "SELECT operation_id, principal_id, accepted_at, state, request_json, result_json FROM preparation_operations "
            "WHERE json_extract(result_json, '$.prepared_run.run_uri') = ? ORDER BY rowid",
            (run_uri,),
        ).fetchall()
    if not rows:
        # Preserve the existing coordinator ownership boundary for arbitrary URIs.
        daemon.admission_for_run_uri(run_uri)
    unavailable: list[str] = []
    annotations = None
    factory = daemon.config.coordinator_authority_factory
    try:
        if factory is None:
            raise LookupError("authority unavailable")
        annotations = factory(run_uri).read_run_annotations(run_uri)
        if annotations is None:
            unavailable.append("annotations_unknown")
    except (ValueError, OSError, LookupError):
        unavailable.append("authority_unavailable")
    if "annotations_unknown" in unavailable:
        from loom.pipeline.stores.local_runs import LocalRunStore

        try:
            runtime = LocalRunStore(daemon.config.run_store_root).read_runtime_metadata(
                run_uri
            )
            if runtime is not None:
                annotations = RunAnnotations(
                    run_uri,
                    0,
                    None,
                    cast(Mapping[str, str], runtime.get("tags", {})),
                    {},
                )
                unavailable.append("legacy_runtime_annotations")
        except ValueError:
            unavailable.append("legacy_runtime_annotations_unrepresentable")
        except (OSError, LookupError):
            unavailable.append("legacy_runtime_unavailable")
    links: list[Mapping[str, PlainData]] = []
    original = None
    for row in rows:
        link = {
            "operation_id": str(row["operation_id"]),
            "accepted_at": row["accepted_at"],
            "state": str(row["state"]),
        }
        if len(links) < 20:
            links.append(link)
        if (
            annotations is not None
            and annotations.initializer_coordinator_id == daemon._require_started()
            and annotations.initializer_operation_id == row["operation_id"]
        ):
            original = {
                **link,
                "principal_id": str(row["principal_id"]),
                "context": json.loads(str(row["request_json"])).get("context"),
            }
    if original is None:
        unavailable.append("original_submission_unknown")
    inspection = None
    if inspect_run is not None:
        try:
            inspection = inspect_run(run_uri)
        except (ValueError, OSError, LookupError, AdmissionNotFoundError):
            unavailable.append("inspection_unavailable")
    else:
        unavailable.append("inspection_unavailable")
    return RunContext(
        run_uri,
        annotations,
        original,
        tuple(links),
        len(rows),
        inspection,
        tuple(unavailable),
    )
