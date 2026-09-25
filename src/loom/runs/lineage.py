"""Bounded, metadata-only traversal requests over retained native lineage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .outputs import OutputLocator
from .query import ManagedScope, QueryError, RunQuery, _plain


@dataclass(frozen=True)
class LineageQuery:
    """Trace declared, bound or acknowledged-start input relationships.

    ``start`` contains a run_uri and optionally stage_name, attempt_id, or the
    complete OutputLocator fields. Filters select result nodes after traversal;
    intermediate nodes and connecting edges remain visible. Observations are live.
    """

    start: Mapping[str, str] = field(default_factory=dict)
    direction: str = "upstream"
    relations: tuple[str, ...] = ("consumed_input", "reused_output")
    history: str = "current"
    scope: Any = field(default_factory=ManagedScope)
    max_depth: int = 10
    limit: int = 200
    cursor: str | None = None
    artifact_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "start": dict(self.start),
            "direction": self.direction,
            "relations": list(self.relations),
            "history": self.history,
            "scope": _plain(self.scope),
            "max_depth": self.max_depth,
            "limit": self.limit,
            "cursor": self.cursor,
            "artifact_type": self.artifact_type,
        }

    @classmethod
    def from_dict(cls, value: Any) -> LineageQuery:
        if not isinstance(value, Mapping) or set(value) - set(cls().to_dict()):
            raise QueryError("invalid lineage query fields")
        raw = {**cls().to_dict(), **value}
        if (
            type(raw.pop("schema_version")) is not int
            or value.get("schema_version", 1) != 1
        ):
            raise QueryError("invalid lineage schema")
        start = raw["start"]
        if (
            not isinstance(start, Mapping)
            or set(start)
            not in (
                {"run_uri"},
                {"run_uri", "stage_name"},
                {"run_uri", "stage_name", "attempt_id"},
                {"run_uri", "stage_name", "commit_id", "output_name"},
            )
            or any(
                not isinstance(v, str) or not v or len(v.encode()) > 4096
                for v in start.values()
            )
        ):
            raise QueryError("invalid lineage start identity")
        if "commit_id" in start:
            OutputLocator.from_dict(start)
        if raw["direction"] not in {"upstream", "downstream"} or raw["history"] not in {
            "current",
            "all",
        }:
            raise QueryError("invalid lineage direction or history")
        relations = raw["relations"]
        if (
            not isinstance(relations, (tuple, list))
            or not relations
            or any(
                v
                not in {
                    "declared_dependency",
                    "bound_input",
                    "consumed_input",
                    "reused_output",
                }
                for v in relations
            )
            or len(relations) != len(set(relations))
        ):
            raise QueryError("invalid lineage relations")
        raw["relations"] = tuple(relations)
        if type(raw["max_depth"]) is not int or not 0 <= raw["max_depth"] <= 100:
            raise QueryError("lineage depth must be between 0 and 100")
        query = RunQuery(
            scope=raw["scope"], limit=raw["limit"], cursor=raw["cursor"]
        ).checked()
        raw["scope"] = query.scope
        if raw["artifact_type"] is not None and (
            not isinstance(raw["artifact_type"], str) or not raw["artifact_type"]
        ):
            raise QueryError("invalid artifact type filter")
        return cls(**raw)

    def checked(self) -> LineageQuery:
        return self.from_dict(self.to_dict())
