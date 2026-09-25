"""Metadata-only query projections from existing local and authority owners."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.errors import StoreError
from loom.timestamps import utc_timestamp

from .query import QueryRecord, RunQuery, UNAVAILABLE
from ._extract import _first_string


def needs_notes(query: RunQuery) -> bool:
    def contains(node: Any) -> bool:
        return (
            node.get("field", {}).get("source") == "notes"
            or any(contains(term) for term in node.get("terms", ()))
            or ("term" in node and contains(node["term"]))
        )

    return any(selected.source == "notes" for selected in query.select) or contains(
        query.where
    )


def acquire_run(
    root: Path, run_uri: str, authority: Any = None, *, include_notes: bool = False
) -> QueryRecord:
    """Read detached facts; do not infer event times from revision timestamps."""
    store = LocalRunStore(root)
    native: dict[str, Any] = {"run_uri": run_uri}
    record = QueryRecord(
        {"native": native}, observation={"observed_at": utc_timestamp()}
    )
    try:
        document = store.read_run_document(run_uri)
        native["created_at"] = document.get("created_at", UNAVAILABLE)
        runtime = store.read_runtime_metadata(run_uri) or {}
        composition = store.read_composition_manifest(run_uri) or {}
        plan = store.read_plan(run_uri) or {}
        git = store.read_provenance_document(run_uri, "git") or {}
        native.update(
            config_fingerprint=_first_string(
                composition,
                "config_fingerprint",
                "fingerprint",
                "artifact_fingerprint",
                "content_fingerprint",
            )
            or UNAVAILABLE,
            pipeline_fingerprint=_first_string(
                plan, "pipeline_fingerprint", "fingerprint", "plan_fingerprint"
            )
            or UNAVAILABLE,
            git_repository=git.get("remote_url")
            or git.get("repository_root", UNAVAILABLE),
            git_commit=_first_string(git, "commit", "sha", "head_commit", "revision")
            or UNAVAILABLE,
            git_dirty=git.get("is_dirty", UNAVAILABLE),
            executor=runtime.get("executor", UNAVAILABLE),
            backend=runtime.get("backend", UNAVAILABLE),
        )
        if authority is None:
            record.warnings.append(
                {"code": "authority_unavailable", "run_uri": run_uri}
            )
            for key in ("status", "started_at", "finished_at"):
                native[key] = UNAVAILABLE
            return record
        snapshot = authority.open_run(run_uri)
        native["status"] = snapshot.status.value
        # Authority snapshots retain lifecycle status but do not retain exact
        # run start/finish instants. Revision and preparation times are different facts.
        native["started_at"] = native["finished_at"] = UNAVAILABLE
        record.observation.update(
            state_source="authoritative", revision=snapshot.revision.to_dict()
        )
        stages = []
        for stage in snapshot.stages:
            latest = stage.attempts[-1] if stage.attempts else None
            commit = stage.latest_commit
            own_terminal_commit = (
                commit is not None
                and latest is not None
                and stage.status.value == "SUCCEEDED"
                and commit.run_uri == run_uri
                and commit.stage_name == stage.stage_name
                and commit.attempt_id == latest.attempt_id
            )
            stages.append(
                QueryRecord(
                    {
                        "native": {
                            "name": stage.stage_name,
                            "status": stage.status.value,
                            "attempt": latest.attempt if latest else UNAVAILABLE,
                            "created_at": latest.created_at if latest else UNAVAILABLE,
                            "started_at": UNAVAILABLE,
                            "finished_at": commit.committed_at
                            if own_terminal_commit and commit is not None
                            else UNAVAILABLE,
                        }
                    }
                )
            )
        record.stages = tuple(stages)
        annotations = authority.read_run_annotations(run_uri)
        if annotations is not None:
            record.sources.update(
                tags=dict(annotations.tags),
                metadata=dict(annotations.metadata),
                description=annotations.description,
            )
            native.update(
                operation_id=annotations.initializer_operation_id or UNAVAILABLE,
                coordinator_id=annotations.initializer_coordinator_id or UNAVAILABLE,
            )
            record.observation["annotation_revision"] = annotations.revision
        else:
            from .context import SubmissionContext

            legacy_context = SubmissionContext(tags=cast(Any, runtime.get("tags", {})))
            record.sources.update(
                tags=dict(legacy_context.tags), metadata={}, description=None
            )
        if not include_notes:
            return record
        # Notes remain at their authority paging owner; no artifact payloads or
        # application objects participate in text acquisition.
        notes: list[Any] = []
        cursor = None
        while True:
            legacy = runtime.get("notes", ())
            if not isinstance(legacy, (list, tuple)) or any(
                not isinstance(note, str) for note in legacy
            ):
                raise ValueError("legacy notes unavailable")
            page = authority.list_run_notes(
                run_uri, 50, cursor, tuple(cast(list[str], legacy))
            )
            notes.extend(note.to_dict() for note in page.notes)
            cursor = page.next_cursor
            if cursor is None:
                record.sources["notes"] = notes
                break
    except (ValueError, OSError, LookupError, StoreError) as exc:
        record.warnings.append(
            {
                "code": "record_unavailable",
                "run_uri": run_uri,
                "reason": type(exc).__name__,
            }
        )
    return record
