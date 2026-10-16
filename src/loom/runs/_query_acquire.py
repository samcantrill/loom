"""Metadata-only query projections from existing local and authority owners."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.errors import StoreError
from loom.timestamps import utc_timestamp

from .query import QueryRecord, RunQuery, UNAVAILABLE
from ._extract import (
    _composition_fingerprint,
    _stage_finished_at,
    _stage_started_at,
    _string_or_none,
)


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
        git = store.read_provenance_document(run_uri, "git") or {}
        native.update(
            config_fingerprint=_composition_fingerprint(composition) or UNAVAILABLE,
            git_repository=git.get("remote_url")
            or git.get("repository_root", UNAVAILABLE),
            git_commit=_string_or_none(git.get("commit")) or UNAVAILABLE,
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
        native["started_at"] = (
            snapshot.started_at if snapshot.started_at_known else UNAVAILABLE
        )
        native["finished_at"] = snapshot.finished_at or UNAVAILABLE
        record.observation.update(
            state_source="authoritative", revision=snapshot.revision.to_dict()
        )
        stages = []
        for stage in snapshot.stages:
            latest = stage.attempts[-1] if stage.attempts else None
            stages.append(
                QueryRecord(
                    {
                        "native": {
                            "name": stage.stage_name,
                            "status": stage.status.value,
                            "attempt": latest.attempt if latest else UNAVAILABLE,
                            "created_at": latest.created_at if latest else UNAVAILABLE,
                            "started_at": _stage_started_at(stage) or UNAVAILABLE,
                            "finished_at": _stage_finished_at(stage, run_uri)
                            or UNAVAILABLE,
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
        if not include_notes:
            return record
        # Notes remain at their authority paging owner; no artifact payloads or
        # application objects participate in text acquisition.
        notes: list[Any] = []
        cursor = None
        while True:
            page = authority.list_run_notes(run_uri, 50, cursor)
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
