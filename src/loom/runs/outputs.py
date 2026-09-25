"""Inert exact output identities and bounded metadata selection requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from loom.artifacts import ArtifactRef
from loom.serialization import thaw_plain_data
from .query import ManagedScope, QueryError, RunQuery, _plain


@dataclass(frozen=True)
class OutputLocator:
    """Address an original producer's immutable commit, without granting access."""

    run_uri: str
    stage_name: str
    commit_id: str
    output_name: str

    def __post_init__(self) -> None:
        for value in self.to_dict().values():
            if not isinstance(value, str) or not value or len(value.encode()) > 4096:
                raise QueryError(
                    "output locator fields must be bounded nonempty strings"
                )

    def to_dict(self) -> dict[str, str]:
        return {
            name: getattr(self, name)
            for name in ("run_uri", "stage_name", "commit_id", "output_name")
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OutputLocator:
        if not isinstance(value, Mapping) or set(value) != {
            "run_uri",
            "stage_name",
            "commit_id",
            "output_name",
        }:
            raise QueryError("invalid output locator")
        return cls(**value)


@dataclass(frozen=True)
class SelectedOutput:
    """Committed metadata with distinct producer and matched consumer identities.

    Availability is deliberately unchecked. Checksum/fingerprint fields in the
    artifact and retained binding verification describe recorded evidence only.
    """

    locator: OutputLocator
    artifact: ArtifactRef
    matched_run_uri: str
    matched_stage_name: str
    observation: Mapping[str, Any] = field(default_factory=dict)
    verification: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": "selected",
            "locator": self.locator.to_dict(),
            "artifact": self.artifact.to_dict(),
            "matched_run_uri": self.matched_run_uri,
            "matched_stage_name": self.matched_stage_name,
            "observation": dict(self.observation),
            "verification": dict(self.verification),
            "availability": "not_checked",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SelectedOutput:
        if (
            value.get("outcome") != "selected"
            or value.get("availability") != "not_checked"
        ):
            raise QueryError("invalid selected output")
        return cls(
            OutputLocator.from_dict(value["locator"]),
            ArtifactRef.from_dict(value["artifact"]),
            value["matched_run_uri"],
            value["matched_stage_name"],
            value["observation"],
            value["verification"],
        )


@dataclass(frozen=True)
class OutputSelection:
    """Select explicit runs/stages, one exact locator, or a bounded run query.

    Metadata filters compare literal top-level keys with typed JSON equality.
    Scope authorizes both matched runs and original producers. Pages are live;
    follow ``next_cursor`` while retaining warnings and per-selector outcomes.
    ``history='all'`` includes retained local commits and the current reuse
    association; it does not invent historical adoption records.
    """

    run_uris: tuple[str, ...] = ()
    stage_names: tuple[str, ...] = ()
    query: RunQuery | None = None
    locator: OutputLocator | None = None
    scope: Any = field(default_factory=ManagedScope)
    history: str = "current"
    output_name: str | None = None
    artifact_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 50
    cursor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_uris": list(self.run_uris),
            "stage_names": list(self.stage_names),
            "query": self.query.to_dict() if self.query else None,
            "locator": self.locator.to_dict() if self.locator else None,
            "scope": _plain(self.scope),
            "history": self.history,
            "output_name": self.output_name,
            "artifact_type": self.artifact_type,
            "metadata": thaw_plain_data(self.metadata),
            "limit": self.limit,
            "cursor": self.cursor,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OutputSelection:
        if not isinstance(value, Mapping):
            raise QueryError("output selection must be an object")
        defaults = cls().to_dict()
        if (set(value) - set(defaults) or value.get("schema_version", 1) != 1
                or type(value.get("schema_version", 1)) is not int):
            raise QueryError("invalid output selection fields")
        raw = {**defaults, **value}
        raw.pop("schema_version")
        for key in ("run_uris", "stage_names"):
            values = raw[key]
            if (
                not isinstance(values, (tuple, list))
                or len(values) > 200
                or any(
                    not isinstance(v, str) or not v or len(v.encode()) > 4096
                    for v in values
                )
                or len(set(values)) != len(values)
            ):
                raise QueryError("invalid explicit selectors")
            raw[key] = tuple(values)
        scope = RunQuery(
            scope=raw["scope"], limit=raw["limit"], cursor=raw["cursor"]
        ).checked()
        raw["scope"] = scope.scope
        if raw["history"] not in ("current", "all"):
            raise QueryError("history must be current or all")
        for key in ("output_name", "artifact_type"):
            if raw[key] is not None and (
                not isinstance(raw[key], str)
                or not raw[key]
                or len(raw[key].encode()) > 4096
            ):
                raise QueryError("invalid output filter")
        from loom.serialization import freeze_plain_data

        if not isinstance(raw["metadata"], Mapping) or len(raw["metadata"]) > 64:
            raise QueryError("invalid metadata filter")
        raw["metadata"] = freeze_plain_data(raw["metadata"])
        if raw["query"] is not None:
            raw["query"] = RunQuery.from_dict(raw["query"])
            if raw["query"].scope != raw["scope"] or raw["query"].cursor is not None:
                raise QueryError("query scope must agree; use the output continuation")
        if raw["locator"] is not None:
            raw["locator"] = OutputLocator.from_dict(raw["locator"])
        if sum(bool(raw[k]) for k in ("run_uris", "query", "locator")) != 1:
            raise QueryError("choose explicit runs, a query, or an exact locator")
        if raw["locator"] is not None and raw["stage_names"]:
            raise QueryError("exact locator already selects its stage")
        return cls(**raw)

    def checked(self) -> OutputSelection:
        return self.from_dict(self.to_dict())
