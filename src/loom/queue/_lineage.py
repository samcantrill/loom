"""Authorized live lineage acquisition and bounded breadth-first traversal."""

from __future__ import annotations

import base64
from collections import defaultdict, deque
from collections.abc import Mapping
import hashlib
import json
from typing import Any

from loom.runs._query_page import QueryPage, _bytes
from loom.runs.lineage import LineageQuery
from loom.runs.outputs import OutputLocator
from loom.runs.query import InvalidCursorError, QueryError
from loom.timestamps import utc_timestamp

from ._output_selection import _authority, _READ_ERRORS, authorized_run


def validate_lineage_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {"query"}:
        raise QueryError("lineage requires query")
    return {"query": LineageQuery.from_dict(payload["query"])}


def _key(identity: Mapping[str, Any]) -> str:
    return _bytes(identity).decode()


def lineage_operation(daemon: Any, query: LineageQuery) -> QueryPage:
    """Return exact identities, connecting evidence, and explicit coverage limits.

    Output nodes refer to their producing attempt. Those ownership links are
    zero-depth joins, not data consumption edges. Every input edge names a port.
    """
    owner = daemon._require_started()
    raw = query.to_dict()
    raw.pop("cursor")
    digest = hashlib.sha256(_bytes([owner, raw])).hexdigest()
    after = None
    if query.cursor:
        try:
            state = json.loads(
                base64.b64decode(query.cursor, altchars=b"-_", validate=True)
            )
            if (
                set(state) != {"digest", "after"}
                or state["digest"] != digest
                or not isinstance(state["after"], str)
            ):
                raise ValueError("cursor mismatch")
            after = state["after"]
        except (ValueError, TypeError, KeyError) as exc:
            raise InvalidCursorError("invalid_cursor") from exc
    warnings: list[dict[str, Any]] = []
    if not authorized_run(daemon, query.start["run_uri"], query.scope):
        return QueryPage(
            (),
            None,
            query.scope,
            owner,
            utc_timestamp(),
            ({"code": "run_not_found"},),
            False,
        )
    if query.scope["kind"] == "managed":
        from ._run_queries import _journal

        operations, admissions = _journal(daemon)
        uris = {row["run_uri"] for row in (*operations, *admissions) if row["run_uri"]}
    else:
        try:
            uris = {
                p.resolve().as_uri()
                for p in daemon.config.run_store_root.iterdir()
                if p.is_dir() and (p / "run.json").exists()
            }
        except OSError:
            uris = set()
            warnings.append({"code": "scope_unavailable"})
    uris.add(query.start["run_uri"])
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    joins: dict[str, set[str]] = defaultdict(set)
    seeds: set[str] = set()
    issues: dict[str, list[dict[str, Any]]] = defaultdict(list)
    attempts: list[tuple[Any, str]] = []
    limited = False
    examined = 0

    def add_node(identity: dict[str, Any], **data: Any) -> str:
        nonlocal limited
        key = _key(identity)
        if key not in nodes and len(nodes) >= 2000:
            limited = True
            return key
        nodes[key] = {"kind": "node", "identity": identity, **data}
        return key

    def add_edge(source: str, target: str, relation: str, **data: Any) -> None:
        edge = {
            "kind": "edge",
            "source": json.loads(source),
            "target": json.loads(target),
            "relation": relation,
            **data,
        }
        edges[_key(edge)] = edge

    for uri in sorted(uris):
        if examined >= 500 or limited:
            limited = True
            break
        if not authorized_run(daemon, uri, query.scope):
            continue
        examined += 1
        try:
            authority = _authority(daemon, uri)
            snapshot = authority.open_run(uri)
            for stage in snapshot.stages:
                if limited:
                    break
                stage_id = {"run_uri": uri, "stage_name": stage.stage_name}
                stage_key = add_node(stage_id, entity="stage")
                matches_stage = (
                    uri == query.start["run_uri"]
                    and query.start.get("stage_name", stage.stage_name)
                    == stage.stage_name
                )
                if (
                    matches_stage
                    and ("declared_dependency" in query.relations or (
                        stage.result_binding is not None
                        and "reused_output" in query.relations
                    ))
                    and len(query.start) <= 2
                ):
                    seeds.add(stage_key)
                for attempt in stage.attempts:
                    if limited:
                        break
                    identity = {**stage_id, "attempt_id": attempt.attempt_id}
                    key = add_node(
                        identity,
                        entity="attempt",
                        start_confirmed=attempt.start_confirmed,
                        start_confirmed_at=attempt.start_confirmed_at,
                    )
                    attempts.append((attempt, key))
                    if identity == query.start:
                        seeds.add(key)
                    if attempt.input_bindings is None:
                        issues[key].append(
                            {"code": "input_evidence_unknown", "identity": identity}
                        )
                    if attempt.start_confirmed is None:
                        issues[key].append(
                            {"code": "start_evidence_unknown", "identity": identity}
                        )
                versions = list(
                    authority.list_output_commits(uri, stage_name=stage.stage_name)
                )
                if stage.result_binding is not None:
                    from loom.pipeline.stores.authority import OutputCommit

                    versions.append(
                        OutputCommit(
                            stage.result_binding.commit,
                            stage.result_binding.artifact_facts,
                        )
                    )
                for version in versions:
                    if limited:
                        break
                    commit = version.commit
                    if not authorized_run(daemon, commit.run_uri, query.scope):
                        issues[stage_key].append({"code": "restricted_source"})
                        continue
                    if commit.run_uri != uri:
                        try:
                            original = _authority(daemon, commit.run_uri)
                            if not any(
                                v == version
                                for v in original.list_output_commits(
                                    commit.run_uri, stage_name=commit.stage_name
                                )
                            ):
                                raise ValueError("original source unavailable")
                        except _READ_ERRORS:
                            issues[stage_key].append({"code": "source_unavailable"})
                            continue
                    attempt_identity = {
                        "run_uri": commit.run_uri,
                        "stage_name": commit.stage_name,
                        "attempt_id": commit.attempt_id,
                    }
                    attempt_key = _key(attempt_identity)
                    for fact in version.artifact_facts:
                        if limited:
                            break
                        identity = OutputLocator(
                            commit.run_uri,
                            commit.stage_name,
                            commit.commit_id,
                            fact.artifact_name,
                        ).to_dict()
                        key = add_node(
                            identity,
                            entity="output",
                            artifact=fact.artifact.to_dict(),
                            producer_attempt=attempt_identity,
                            selected=query.artifact_type is None
                            or query.artifact_type == fact.artifact.artifact_type,
                        )
                        if query.direction == "upstream":
                            joins[key].add(attempt_key)
                        else:
                            joins[attempt_key].add(key)
                        if identity == query.start or (
                            matches_stage
                            and len(query.start) <= 2
                            and (
                                query.history == "all" or stage.latest_commit == commit
                            )
                        ):
                            seeds.add(key)
                        if (
                            stage.result_binding is not None
                            and stage.result_binding.commit == commit
                        ):
                            add_edge(key, stage_key, "reused_output")
            if "declared_dependency" in query.relations:
                from loom.pipeline.stores import LocalRunStore
                from loom.pipeline.planning import ExecutionPlan

                plan = LocalRunStore(daemon.config.run_store_root).read_plan(uri)
                if plan is None:
                    warnings.append(
                        {"code": "declared_evidence_unknown", "run_uri": uri}
                    )
                else:
                    for stage_plan in ExecutionPlan.from_dict(plan).stage_plans:
                        if limited:
                            break
                        target = add_node(
                            {"run_uri": uri, "stage_name": stage_plan.stage_name},
                            entity="stage",
                        )
                        if (
                            uri == query.start["run_uri"]
                            and len(query.start) <= 2
                            and query.start.get("stage_name", stage_plan.stage_name)
                            == stage_plan.stage_name
                        ):
                            seeds.add(target)
                        for source in stage_plan.upstream_stages:
                            if limited:
                                break
                            source_key = add_node(
                                {"run_uri": uri, "stage_name": source}, entity="stage"
                            )
                            add_edge(source_key, target, "declared_dependency")
        except _READ_ERRORS:
            warnings.append({"code": "authority_unavailable", "run_uri": uri})

    for attempt, target in attempts:
        for binding in attempt.input_bindings or ():
            if binding.producer is None:
                source = add_node(
                    {
                        "external_input": binding.input_name,
                        "consumer": json.loads(target),
                    },
                    entity="external",
                    source_kind=binding.source_kind,
                    artifact=binding.artifact.to_dict(),
                )
                issues[target].append(
                    {
                        "code": "external_boundary",
                        "identity": json.loads(target),
                        "input_name": binding.input_name,
                    }
                )
            elif not authorized_run(daemon, binding.producer.run_uri, query.scope):
                issues[target].append(
                    {"code": "restricted_source", "input_name": binding.input_name}
                )
                continue
            else:
                source = _key(binding.producer.to_dict())
                if source not in nodes:
                    issues[target].append(
                        {"code": "source_unavailable", "input_name": binding.input_name}
                    )
                    continue
            relation = (
                "consumed_input" if attempt.start_confirmed is True else "bound_input"
            )
            if "bound_input" in query.relations and relation == "consumed_input":
                add_edge(
                    source,
                    target,
                    "bound_input",
                    input_name=binding.input_name,
                    start_evidence="confirmed",
                )
            add_edge(
                source,
                target,
                relation,
                input_name=binding.input_name,
                start_evidence="unknown"
                if attempt.start_confirmed is None
                else "confirmed"
                if attempt.start_confirmed
                else "not_confirmed",
            )

    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, edge in edges.items():
        # Unknown/unstarted bindings remain visible in result-oriented traces.
        if edge["relation"] not in query.relations and not (
            edge["relation"] == "bound_input" and "consumed_input" in query.relations
        ):
            continue
        source, target = _key(edge["source"]), _key(edge["target"])
        if query.direction == "upstream":
            source, target = target, source
        adjacency[source].append((key, target))
    frontier = deque((key, 0) for key in sorted(seeds))
    visited: set[str] = set()
    emitted: dict[str, dict[str, Any]] = {}
    while frontier:
        key, depth = frontier.popleft()
        if key in visited:
            continue
        if len(visited) == 2000:
            limited = True
            break
        visited.add(key)
        warnings.extend(issues.get(key, ()))
        if key not in nodes:
            warnings.append({"code": "attempt_evidence_unknown"})
            continue
        emitted["node:" + key] = nodes[key]
        for joined in sorted(joins.get(key, ())):
            frontier.appendleft((joined, depth))
        neighbors = sorted(adjacency.get(key, ()))
        if depth == query.max_depth:
            if neighbors:
                warnings.append({"code": "depth_limit", "max_depth": query.max_depth})
            continue
        for edge_key, target in neighbors:
            emitted["edge:" + edge_key] = edges[edge_key]
            frontier.append((target, depth + 1))
    if limited:
        warnings.append(
            {
                "code": "traversal_limit",
                "guidance": "narrow the scope or starting entity",
                "visited_limit": 2000,
                "scope_run_limit": 500,
            }
        )
    if not seeds:
        warnings.append({"code": "no_matching_start"})
    rows = [
        (key, row)
        for key, row in sorted(emitted.items())
        if after is None or key > after
    ]
    items: list[dict[str, Any]] = []
    size = 0
    last = after
    for key, row in rows:
        cost = len(_bytes(row))
        if cost > 512 * 1024:
            warnings.append({"code": "metadata_too_large"})
            last = key
            continue
        if len(items) == query.limit or (items and size + cost > 512 * 1024):
            break
        items.append(row)
        size += cost
        last = key
    cursor = None
    if not limited and last is not None and rows and last != rows[-1][0]:
        cursor = base64.urlsafe_b64encode(
            _bytes({"digest": digest, "after": last})
        ).decode()
    unique_warnings = list({_key(w): w for w in warnings}.values())
    warnings = []
    warning_size = 0
    for warning in unique_warnings:
        cost = len(_bytes(warning))
        if warning_size + cost > 128 * 1024:
            warnings.append(
                {"code": "additional_evidence_gaps", "guidance": "narrow the query"}
            )
            break
        warnings.append(warning)
        warning_size += cost
    return QueryPage(
        tuple(items),
        cursor,
        query.scope,
        owner,
        utc_timestamp(),
        tuple(warnings),
        not any(w["code"] != "no_matching_start" for w in warnings),
        examined,
    )
