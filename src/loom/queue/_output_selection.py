"""Authorized metadata-only projection of existing output commits and bindings."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import replace
import hashlib
import json
from typing import Any, cast

from loom.pipeline.stores.authority import AuthorityStoreError
from loom.pipeline.stores.errors import StoreError
from loom.runs._query_page import QueryPage, _bytes
from loom.runs.outputs import OutputLocator, OutputSelection, SelectedOutput
from loom.runs.query import InvalidCursorError
from loom.timestamps import utc_timestamp
from loom.serialization import thaw_plain_data

OUTPUT_OPERATIONS = frozenset({"select_outputs", "list_output_commits"})
_READ_ERRORS = (OSError, ValueError, LookupError, StoreError, AuthorityStoreError)


def validate_output_request(operation: str, payload: Any) -> dict[str, Any]:
    if set(payload) != {"selection"}:
        raise ValueError("output query requires selection")
    selection = OutputSelection.from_dict(payload["selection"])
    if operation == "list_output_commits":
        selection = replace(selection, history="all")
    return {"selection": selection}


def authorized_run(daemon: Any, uri: str, scope: Any) -> bool:
    """Apply existing managed membership or configured collection containment.

    A binding is never a capability: its producer must independently pass this
    check before either its metadata or location is disclosed.
    """
    if scope["kind"] == "managed":
        from ._run_queries import _journal

        operations, admissions = _journal(daemon)
        return any(row["run_uri"] == uri for row in (*operations, *admissions))
    from loom.io.uris import uri_to_path

    try:
        path = uri_to_path(uri)
        root = daemon.config.run_store_root.resolve()
        return path.resolve().parent == root and path.as_uri() == uri
    except (ValueError, OSError):
        return False


def _authority(daemon: Any, uri: str) -> Any:
    factory = daemon.config.coordinator_authority_factory
    if factory is not None:
        return factory(uri)
    from loom.io.uris import uri_to_path
    from loom.pipeline.stores import LocalRunStore
    from loom.runs._scan import _authority_scan_context, _authority_store_for_candidate

    authority, _ = _authority_store_for_candidate(
        uri,
        uri_to_path(uri),
        LocalRunStore(daemon.config.run_store_root),
        _authority_scan_context(),
    )
    if authority is None:
        raise OSError("authority unavailable")
    return authority


def _outcome(uri: str, stage: str | None, code: str) -> dict[str, Any]:
    return {"outcome": code, "matched_run_uri": uri, "matched_stage_name": stage}


def _matches(selection: OutputSelection, fact: Any) -> bool:
    if (
        selection.output_name is not None
        and fact.artifact_name != selection.output_name
    ):
        return False
    if (
        selection.artifact_type is not None
        and fact.artifact.artifact_type != selection.artifact_type
    ):
        return False
    return all(
        key in fact.artifact.metadata and _equal(fact.artifact.metadata[key], value)
        for key, value in selection.metadata.items()
    )


def _equal(left: Any, right: Any) -> bool:
    """Extend discovery's typed scalar equality to literal JSON containers."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            _equal(left[k], right[k]) for k in left
        )
    if (
        isinstance(left, Sequence)
        and not isinstance(left, str)
        and isinstance(right, Sequence)
        and not isinstance(right, str)
    ):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right)
        )
    same = type(left) is type(right) or (
        type(left) in (int, float) and type(right) in (int, float)
    )
    return same and left == right


def _rows(
    daemon: Any, selection: OutputSelection, uri: str, *, commits: bool
) -> list[dict[str, Any]]:
    requested_names = selection.stage_names or (
        (selection.locator.stage_name,) if selection.locator else (None,)
    )
    if not authorized_run(daemon, uri, selection.scope):
        return [_outcome(uri, name, "run_not_found") for name in requested_names]
    try:
        authority = _authority(daemon, uri)
        snapshot = authority.open_run(uri)
    except _READ_ERRORS:
        return [
            _outcome(uri, name, "authority_unavailable") for name in requested_names
        ]
    stages = {stage.stage_name: stage for stage in snapshot.stages}
    names = selection.stage_names or (
        (selection.locator.stage_name,) if selection.locator else tuple(stages)
    )
    result: list[dict[str, Any]] = []
    for name in sorted(names):
        stage = stages.get(name)
        if stage is None:
            result.append(_outcome(uri, name, "no_matching_output"))
            continue
        try:
            versions = []
            if selection.history == "all" or selection.locator is not None:
                versions = list(authority.list_output_commits(uri, stage_name=name))
            if (
                selection.locator is None
                and stage.latest_commit is not None
                and (selection.history == "current" or stage.result_binding is not None)
            ):
                from loom.pipeline.stores.authority import OutputCommit

                versions.append(OutputCommit(stage.latest_commit, stage.artifact_facts))
            found = False
            seen = set()
            for version in versions:
                commit = version.commit
                if (
                    selection.locator is not None
                    and commit.commit_id != selection.locator.commit_id
                ):
                    continue
                if commit.commit_id in seen:
                    continue
                seen.add(commit.commit_id)
                verification: dict[str, Any] = {}
                producer_revision = snapshot.revision.to_dict()
                if commit.run_uri != uri or commit.stage_name != name:
                    if not authorized_run(daemon, commit.run_uri, selection.scope):
                        result.append(_outcome(uri, name, "producer_restricted"))
                        found = True
                        continue
                    try:
                        producer = _authority(daemon, commit.run_uri)
                        producer_revision = producer.open_run(
                            commit.run_uri
                        ).revision.to_dict()
                        original = next(
                            (
                                v
                                for v in producer.list_output_commits(
                                    commit.run_uri, stage_name=commit.stage_name
                                )
                                if v.commit.commit_id == commit.commit_id
                            ),
                            None,
                        )
                        if original is None:
                            raise LookupError("original commit unavailable")
                        version = original
                        commit = original.commit
                    except _READ_ERRORS:
                        result.append(_outcome(uri, name, "producer_unavailable"))
                        found = True
                        continue
                    if stage.result_binding is not None:
                        verification = cast(
                            dict[str, Any],
                            thaw_plain_data(stage.result_binding.verification),
                        )
                selected = []
                for fact in version.artifact_facts:
                    if (
                        selection.locator is not None
                        and fact.artifact_name != selection.locator.output_name
                    ):
                        continue
                    if not _matches(selection, fact):
                        continue
                    locator = OutputLocator(
                        commit.run_uri,
                        commit.stage_name,
                        commit.commit_id,
                        fact.artifact_name,
                    )
                    selected.append(
                        SelectedOutput(
                            locator,
                            fact.artifact,
                            uri,
                            name,
                            {
                                "state_source": "authoritative",
                                "revision": snapshot.revision.to_dict(),
                                "producer_revision": producer_revision,
                                "commit": commit.to_dict(),
                                "run_status": snapshot.status.value,
                                "history": "exact"
                                if selection.locator
                                else selection.history,
                            },
                            verification,
                        ).to_dict()
                    )
                if selected or (
                    commits
                    and not commit.output_names
                    and selection.locator is None
                    and selection.output_name is None
                    and selection.artifact_type is None
                    and not selection.metadata
                ):
                    found = True
                    if commits:
                        result.append(
                            {
                                "outcome": "selected",
                                "matched_run_uri": uri,
                                "matched_stage_name": name,
                                "commit": commit.to_dict(),
                                "outputs": selected,
                                "availability": "not_checked",
                            }
                        )
                    else:
                        result.extend(selected)
            if not found:
                result.append(_outcome(uri, name, "no_matching_output"))
        except _READ_ERRORS:
            result.append(_outcome(uri, name, "authority_unavailable"))
    return result or [_outcome(uri, None, "no_matching_output")]


def _key(row: dict[str, Any]) -> tuple[str, ...]:
    locator = row.get("locator", {})
    commit = row.get("commit", {})
    return (
        row["matched_stage_name"] or "",
        locator.get("commit_id", commit.get("commit_id", "")),
        locator.get("output_name", ""),
        row["outcome"],
    )


def output_operation(daemon: Any, operation: str, value: dict[str, Any]) -> QueryPage:
    """Page one run's expansion at a time, carrying the nested discovery cursor."""
    selection: OutputSelection = value["selection"]
    owner = daemon._require_started()
    raw = selection.to_dict()
    raw.pop("cursor")
    digest = hashlib.sha256(_bytes([operation, owner, raw])).hexdigest()
    state: dict[str, Any] = {"run": 0, "query": None, "after": None}
    if selection.cursor:
        try:
            encoded = json.loads(
                base64.b64decode(selection.cursor, altchars=b"-_", validate=True)
            )
            if not isinstance(encoded, dict):
                raise ValueError("invalid cursor envelope")
            if encoded.pop("digest") != digest or set(encoded) != set(state):
                raise ValueError("cursor mismatch")
            if (
                type(encoded["run"]) is not int
                or encoded["run"] < 0
                or (
                    encoded["query"] is not None
                    and not isinstance(encoded["query"], str)
                )
            ):
                raise ValueError("invalid cursor state")
            if encoded["after"] is not None and (
                not isinstance(encoded["after"], list)
                or len(encoded["after"]) != 4
                or any(not isinstance(v, str) for v in encoded["after"])
            ):
                raise ValueError("invalid output key")
            state = encoded
        except (ValueError, KeyError, TypeError) as exc:
            raise InvalidCursorError("invalid_cursor") from exc
    warnings: list[Any] = []
    complete = True
    next_state = None
    if selection.query is not None:
        from ._run_queries import search

        page = search(daemon, replace(selection.query, limit=1, cursor=state["query"]))
        warnings.extend(page.warnings)
        complete = page.complete
        uri = page.items[0]["identity"] if page.items else None
        if page.next_cursor:
            next_state = {"run": 0, "query": page.next_cursor, "after": None}
    else:
        uris = selection.run_uris or (
            selection.locator.run_uri if selection.locator else "",
        )
        if state["run"] >= len(uris):
            raise InvalidCursorError("invalid_cursor")
        uri = uris[state["run"]]
        if state["run"] + 1 < len(uris):
            next_state = {"run": state["run"] + 1, "query": None, "after": None}
    rows = (
        sorted(
            _rows(daemon, selection, uri, commits=operation == "list_output_commits"),
            key=_key,
        )
        if uri
        else []
    )
    if state["after"] is not None:
        rows = [r for r in rows if _key(r) > tuple(state["after"])]
    items = []
    size = len(_bytes(warnings))
    for index, row in enumerate(rows):
        cost = len(_bytes(row))
        if cost > 512 * 1024:
            row = {
                **_outcome(
                    row["matched_run_uri"],
                    row["matched_stage_name"],
                    "metadata_too_large",
                ),
                "selection_key": list(_key(row)),
            }
            cost = len(_bytes(row))
        if items and (len(items) == selection.limit or size + cost > 640 * 1024):
            next_state = {**state, "after": list(_key(rows[index - 1]))}
            break
        items.append(row)
        size += cost
        if row["outcome"] not in {"selected", "no_matching_output", "run_not_found"}:
            complete = False
            warnings.append({"code": row["outcome"], "run_uri": uri})
    cursor = (
        None
        if next_state is None
        else base64.urlsafe_b64encode(_bytes({"digest": digest, **next_state})).decode()
    )
    return QueryPage(
        tuple(items),
        cursor,
        selection.scope,
        owner,
        utc_timestamp(),
        tuple(warnings),
        complete,
        1 if uri else 0,
    )
