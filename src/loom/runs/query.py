"""Inert structured discovery queries and their authoritative typed semantics.

Fields use literal path segments. Only TRUE selects a record; unavailable and
incompatible values remain UNKNOWN, including beneath NOT. No query imports
application code or opens payloads.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from functools import cmp_to_key
import math
import re
from typing import Any
from loom._output_identity import QueryError


QUERY_CAPABILITY = "run-query-v1"
QUERY_LIMITS = {
    "results": 200,
    "nodes": 64,
    "depth": 8,
    "in_values": 100,
    "candidates": 500,
    "response_bytes": 768 * 1024,
}
_COMMON = {
    "run_uri",
    "status",
    "created_at",
    "submitted_at",
    "started_at",
    "finished_at",
    "operation_id",
    "principal_id",
    "coordinator_id",
    "config_fingerprint",
    "pipeline_fingerprint",
    "git_repository",
    "git_commit",
    "git_dirty",
    "executor",
    "backend",
}
_EXTRA = {
    "runs": set(),
    "submissions": {"state", "accepted_at", "queue_item_id", "kind"},
    "jobs": {
        "admission_id",
        "queue_item_id",
        "state",
        "accepted_at",
        "execution_owner",
    },
}
_STAGE = {"name", "status", "attempt", "created_at", "started_at", "finished_at"}
_COMPARE = {
    "eq",
    "in",
    "lt",
    "lte",
    "gt",
    "gte",
    "semver_eq",
    "semver_lt",
    "semver_lte",
    "semver_gt",
    "semver_gte",
}
_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)


class InvalidCursorError(QueryError):
    """Continuation does not belong to this query, scope, or coordinator."""


class Truth(Enum):
    FALSE = 0
    TRUE = 1
    UNKNOWN = 2


class _Absent(Enum):
    MISSING = 0
    UNAVAILABLE = 1


MISSING = _Absent.MISSING
UNAVAILABLE = _Absent.UNAVAILABLE


def timestamp(value: object) -> tuple[datetime, Decimal]:
    """Parse a timezone-aware RFC3339 instant, normalizing to UTC."""
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)", value
    ):
        raise QueryError("timestamps require timezone-aware RFC3339 instants")
    try:
        instant = datetime.fromisoformat(
            value.upper().replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        fraction = re.search(r":\d\d\.(\d+)", value)
        return instant.replace(microsecond=0), Decimal(
            "0." + fraction[1]
        ) if fraction else Decimal(0)
    except ValueError as exc:
        raise QueryError("invalid timestamp") from exc


def _version(value: object) -> tuple[tuple[int, ...], tuple[str, ...]]:
    match = _SEMVER.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise QueryError("expected strict SemVer 2.0.0")
    pre = tuple((match[4] or "").split(".")) if match[4] else ()
    if any(
        part.isascii() and part.isdigit() and len(part) > 1 and part[0] == "0"
        for part in pre
    ):
        raise QueryError("numeric prerelease identifiers cannot have leading zeroes")
    return (int(match[1]), int(match[2]), int(match[3])), pre


def compare_semver(left: str, right: str) -> int:
    """Compare strict SemVer precedence; build metadata has no ordering effect."""
    a, ap = _version(left)
    b, bp = _version(right)
    if a != b:
        return (a > b) - (a < b)
    if not ap or not bp:
        return bool(bp) - bool(ap)
    for x, y in zip(ap, bp):
        if x == y:
            continue
        if x.isdigit() and y.isdigit():
            return (int(x) > int(y)) - (int(x) < int(y))
        if x.isdigit() != y.isdigit():
            return -1 if x.isdigit() else 1
        return (x > y) - (x < y)
    return (len(ap) > len(bp)) - (len(ap) < len(bp))


@dataclass(frozen=True)
class Field:
    """A source and literal segments; dotted tag keys remain one segment."""

    source: str
    path: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "path": list(self.path)}


@dataclass(frozen=True)
class Compare:
    field: Field
    op: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "compare",
            "field": self.field.to_dict(),
            "op": self.op,
            "value": self.value,
        }


@dataclass(frozen=True)
class AllOf:
    terms: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "all", "terms": [_plain(term) for term in self.terms]}


@dataclass(frozen=True)
class AnyOf(AllOf):
    def to_dict(self) -> dict[str, Any]:
        return {"kind": "any", "terms": [_plain(term) for term in self.terms]}


@dataclass(frozen=True)
class Not:
    term: Any

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "not", "term": _plain(self.term)}


@dataclass(frozen=True)
class AnyStage(Not):
    def to_dict(self) -> dict[str, Any]:
        return {"kind": "any_stage", "term": _plain(self.term)}


@dataclass(frozen=True)
class Exists:
    field: Field

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "exists", "field": self.field.to_dict()}


@dataclass(frozen=True)
class Missing(Exists):
    def to_dict(self) -> dict[str, Any]:
        return {"kind": "missing", "field": self.field.to_dict()}


@dataclass(frozen=True)
class IsNull(Exists):
    def to_dict(self) -> dict[str, Any]:
        return {"kind": "is_null", "field": self.field.to_dict()}


@dataclass(frozen=True)
class ContainsText:
    field: Field
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "contains_text",
            "field": self.field.to_dict(),
            "text": self.text,
        }


@dataclass(frozen=True)
class ManagedScope:
    def to_dict(self) -> dict[str, str]:
        return {"kind": "managed"}


@dataclass(frozen=True)
class CollectionScope:
    name: str = "run_store"

    def to_dict(self) -> dict[str, str]:
        return {"kind": "collection", "name": self.name}


@dataclass(frozen=True)
class Order:
    field: str
    descending: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "descending": self.descending}


def _plain(value: Any) -> Any:
    return value.to_dict() if hasattr(value, "to_dict") else value


def _scalar(value: Any) -> bool:
    return (
        value is None
        or type(value) in (str, bool, int)
        or (type(value) is float and math.isfinite(value))
    )


def _numeric(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def identity_field(entity: str) -> str:
    return {"runs": "run_uri", "submissions": "operation_id", "jobs": "admission_id"}[
        entity
    ]


def query_fields(entity: str = "runs") -> dict[str, Any]:
    """Return finite native capabilities, never private database introspection."""
    if entity not in _EXTRA:
        raise QueryError("unsupported query entity")
    native = sorted(_COMMON | _EXTRA[entity])
    return {
        "schema_version": 1,
        "entity": entity,
        "native_fields": native,
        "stage_fields": sorted(_STAGE),
        "sources": [
            "native",
            "tags",
            "metadata",
            "submission.context",
            "description",
            "notes",
        ],
        "operators": sorted(
            _COMPARE | {"exists", "missing", "is_null", "contains_text"}
        ),
        "sort_fields": sorted(
            {identity_field(entity)}
            | (
                {"created_at", "submitted_at"}
                if entity == "runs"
                else {"accepted_at", "submitted_at"}
                if entity == "submissions"
                else {"accepted_at"}
            )
        ),
        "limits": dict(QUERY_LIMITS),
        "consistency": "live_keyset",
    }


def _field(
    value: Any, entity: str, stage: bool = False, *, projection: bool = False
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"source", "path"}:
        raise QueryError("invalid field")
    source, path = value["source"], value["path"]
    if not isinstance(path, (list, tuple)) or any(not isinstance(p, str) for p in path):
        raise QueryError("invalid literal field path")
    if source == "native":
        if len(path) != 1 or path[0] not in (
            _STAGE if stage else _COMMON | _EXTRA[entity]
        ):
            raise QueryError("unsupported native field")
    elif source == "tags":
        if len(path) != 1 and not (projection and not path):
            raise QueryError("tags require one literal key")
    elif source == "metadata":
        if not path and not projection:
            raise QueryError("metadata requires a path")
    elif source == "submission.context":
        if not path or path[0] not in {"description", "tags", "metadata"}:
            raise QueryError("unsupported submission context field")
    elif source == "description":
        if path:
            raise QueryError("description has no nested fields")
    elif source == "notes":
        if path != ["text"] and path != ("text",):
            raise QueryError("notes support the text field")
    else:
        raise QueryError("unsupported field source")
    if stage and source != "native":
        raise QueryError("any_stage only accepts stage native fields")
    return {"source": source, "path": list(path)}


def _predicate(
    value: Any, entity: str, count: list[int], depth: int = 1, stage: bool = False
) -> dict[str, Any]:
    count[0] += 1
    if depth > 8 or count[0] > 64 or not isinstance(value, Mapping):
        raise QueryError("predicate exceeds limits or is not an object")
    kind = value.get("kind")
    if kind in ("all", "any"):
        if set(value) != {"kind", "terms"} or not isinstance(
            value["terms"], (list, tuple)
        ):
            raise QueryError("invalid boolean terms")
        return {
            "kind": kind,
            "terms": [
                _predicate(v, entity, count, depth + 1, stage) for v in value["terms"]
            ],
        }
    if kind in ("not", "any_stage"):
        if set(value) != {"kind", "term"} or (stage and kind == "any_stage"):
            raise QueryError("invalid scoped predicate")
        return {
            "kind": kind,
            "term": _predicate(
                value["term"], entity, count, depth + 1, stage or kind == "any_stage"
            ),
        }
    keys = {"kind", "field"} | (
        {"op", "value"}
        if kind == "compare"
        else {"text"}
        if kind == "contains_text"
        else set()
    )
    if (
        kind not in {"compare", "exists", "missing", "is_null", "contains_text"}
        or set(value) != keys
    ):
        raise QueryError("unsupported predicate")
    result = {**value, "field": _field(value["field"], entity, stage)}
    if result["field"]["source"] == "notes" and kind != "contains_text":
        raise QueryError("notes require existential contains_text")
    if kind == "contains_text":
        if not isinstance(value["text"], str):
            raise QueryError("invalid text operand")
    if kind == "compare":
        op, operand = value["op"], value["value"]
        if op not in _COMPARE:
            raise QueryError("unsupported comparison")
        operands = operand if op == "in" else [operand]
        if (
            not isinstance(operands, (list, tuple))
            or len(operands) > 100
            or not all(_scalar(v) for v in operands)
        ):
            raise QueryError("comparison requires finite JSON scalars")
        is_time = result["field"]["source"] == "native" and result["field"]["path"][
            0
        ].endswith("_at")
        if is_time:
            if op.startswith("semver"):
                raise QueryError("timestamps are not semantic versions")
            for v in operands:
                timestamp(v)
        elif op in {"lt", "lte", "gt", "gte"} and not _numeric(operand):
            raise QueryError("ordinary ordering requires a finite numeric operand")
        elif op.startswith("semver"):
            _version(operand)
    return result


@dataclass(frozen=True)
class RunQuery:
    """Bounded live query. Missing sort times are last in either direction.

    ``select`` contains Field values; omission returns bounded source summaries.
    Cursors bind to the complete query, deployment and ordering, never grant access.
    """

    scope: Any = field(default_factory=ManagedScope)
    where: Any = field(default_factory=AllOf)
    order_by: tuple[Order, ...] = ()
    select: tuple[Field, ...] = ()
    limit: int = 50
    cursor: str | None = None

    @property
    def entity(self) -> str:
        return "runs"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "scope": _plain(self.scope),
            "where": _plain(self.where),
            "order_by": [_plain(v) for v in self.order_by],
            "select": [_plain(v) for v in self.select],
            "limit": self.limit,
            "cursor": self.cursor,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RunQuery:
        if (
            not isinstance(value, Mapping)
            or set(value)
            - {
                "schema_version",
                "scope",
                "where",
                "order_by",
                "select",
                "limit",
                "cursor",
            }
            or value.get("schema_version") != 1
            or type(value.get("schema_version")) is not int
        ):
            raise QueryError("invalid query schema")
        instance = cls(
            scope=value.get("scope", {"kind": "managed"}),
            where=value.get("where", {"kind": "all", "terms": []}),
            order_by=tuple(value.get("order_by", ())),
            select=tuple(value.get("select", ())),
            limit=value.get("limit", 50),
            cursor=value.get("cursor"),
        )
        return instance.checked()

    def checked(self) -> RunQuery:
        scope = _plain(self.scope)
        if scope not in (
            {"kind": "managed"},
            {"kind": "collection", "name": "run_store"},
        ):
            raise QueryError("unsupported scope")
        if type(self.limit) is not int or not 1 <= self.limit <= 200:
            raise QueryError("limit must be an integer from 1 to 200")
        if self.cursor is not None and (
            not isinstance(self.cursor, str) or len(self.cursor) > 16384
        ):
            raise InvalidCursorError("invalid_cursor")
        where = _predicate(_plain(self.where), self.entity, [0])
        if len(self.select) > 64:
            raise QueryError("too many selected fields")
        select = tuple(
            Field(**_field(_plain(v), self.entity, projection=True))
            for v in self.select
        )
        order: list[Order] = []
        for item in self.order_by:
            raw = _plain(item)
            if (
                not isinstance(raw, Mapping)
                or set(raw) != {"field", "descending"}
                or type(raw["descending"]) is not bool
                or raw["field"] not in query_fields(self.entity)["sort_fields"]
            ):
                raise QueryError("unsupported ordering")
            if raw["field"] in {o.field for o in order}:
                raise QueryError("duplicate sort field")
            order.append(Order(**raw))
        identity = identity_field(self.entity)
        if identity not in {o.field for o in order}:
            order.append(Order(identity))
        return type(self)(scope, where, tuple(order), select, self.limit, self.cursor)


@dataclass(frozen=True)
class SubmissionQuery(RunQuery):
    @property
    def entity(self) -> str:
        return "submissions"


@dataclass(frozen=True)
class JobQuery(RunQuery):
    @property
    def entity(self) -> str:
        return "jobs"


@dataclass
class QueryRecord:
    """Detached owning facts; an absent source is unavailable, an absent key missing."""

    sources: dict[str, Any]
    stages: tuple[QueryRecord, ...] | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    observation: dict[str, Any] = field(default_factory=dict)
    eligible: bool = True


def field_value(record: QueryRecord, selected: Mapping[str, Any]) -> Any:
    value = record.sources.get(selected["source"], UNAVAILABLE)
    if selected["source"] == "notes" and value is not UNAVAILABLE:
        return [
            {"note_id": note["note_id"], **_excerpt(note["text"], "")} for note in value
        ]
    for segment in selected["path"]:
        if isinstance(value, _Absent):
            return value
        if not isinstance(value, Mapping) or segment not in value:
            return UNAVAILABLE if selected["source"] == "native" else MISSING
        value = value[segment]
    return value


def _truth(value: bool) -> Truth:
    return Truth.TRUE if value else Truth.FALSE


def _combine(values: Sequence[Truth], *, every: bool) -> Truth:
    deciding = Truth.FALSE if every else Truth.TRUE
    if deciding in values:
        return deciding
    if Truth.UNKNOWN in values:
        return Truth.UNKNOWN
    return Truth.TRUE if every else Truth.FALSE


def _excerpt(value: str, needle: str) -> dict[str, Any]:
    folded_offset = value.casefold().find(needle.casefold())
    consumed = position = 0
    for character in value:
        if consumed >= folded_offset:
            break
        consumed += len(character.casefold())
        position += 1
    start = max(0, position - 80)
    return {
        "excerpt": value[start : start + 512],
        "offset": start,
        "truncated": start > 0 or len(value) > start + 512,
    }


def evaluate(
    predicate: Mapping[str, Any],
    record: QueryRecord,
    *,
    diagnostics: set[str] | None = None,
    matches: list[dict[str, Any]] | None = None,
) -> Truth:
    """Evaluate a checked tree using Kleene three-valued logic on recorded facts."""
    diagnostics = diagnostics if diagnostics is not None else set()
    matches = matches if matches is not None else []
    kind = predicate["kind"]
    if kind in {"all", "any"}:
        return _combine(
            [
                evaluate(p, record, diagnostics=diagnostics, matches=matches)
                for p in predicate["terms"]
            ],
            every=kind == "all",
        )
    if kind == "not":
        result = evaluate(
            predicate["term"], record, diagnostics=diagnostics, matches=matches
        )
        return result if result is Truth.UNKNOWN else _truth(result is Truth.FALSE)
    if kind == "any_stage":
        if record.stages is None:
            diagnostics.add("source_unavailable")
            return Truth.UNKNOWN
        return _combine(
            [
                evaluate(
                    predicate["term"], stage, diagnostics=diagnostics, matches=matches
                )
                for stage in record.stages
            ],
            every=False,
        )
    selected = predicate["field"]
    if selected["source"] == "notes":
        notes = record.sources.get("notes", UNAVAILABLE)
        if notes is UNAVAILABLE:
            diagnostics.add("source_unavailable")
            return Truth.UNKNOWN
        matched = False
        for note in notes:
            if predicate["text"].casefold() in note["text"].casefold():
                matched = True
                if len(matches) < 10:
                    matches.append(
                        {
                            "source": "notes",
                            "note_id": note["note_id"],
                            **_excerpt(note["text"], predicate["text"]),
                        }
                    )
        return _truth(matched)
    value = field_value(record, selected)
    if value is UNAVAILABLE:
        diagnostics.add("source_unavailable")
        return Truth.UNKNOWN
    if kind == "exists":
        return _truth(value is not MISSING)
    if kind == "missing":
        return _truth(value is MISSING)
    if value is MISSING:
        return Truth.UNKNOWN
    if kind == "is_null":
        return _truth(value is None)
    if kind == "contains_text":
        if not isinstance(value, str):
            diagnostics.add("type_mismatch")
            return Truth.UNKNOWN
        found = predicate["text"].casefold() in value.casefold()
        if found and len(matches) < 10:
            matches.append(
                {
                    "source": selected["source"],
                    "path": selected["path"],
                    **_excerpt(value, predicate["text"]),
                }
            )
        return _truth(found)
    op, operand = predicate["op"], predicate["value"]
    if not _scalar(value):
        diagnostics.add("type_mismatch")
        return Truth.UNKNOWN
    if op == "in":
        return _combine(
            [
                evaluate(
                    {**predicate, "op": "eq", "value": v},
                    record,
                    diagnostics=diagnostics,
                )
                for v in operand
            ],
            every=False,
        )
    is_time = selected["source"] == "native" and selected["path"][0].endswith("_at")
    try:
        if is_time:
            a, b = timestamp(value), timestamp(operand)
            comparison = (a > b) - (a < b)
        elif op.startswith("semver"):
            comparison = compare_semver(value, operand)
            op = op.removeprefix("semver_")
        elif op == "eq":
            same = type(value) is type(operand) or (
                type(value) in (int, float) and type(operand) in (int, float)
            )
            return _truth(same and value == operand)
        else:
            if not _numeric(value):
                raise QueryError("type mismatch")
            comparison = (value > operand) - (value < operand)
    except (QueryError, TypeError, ValueError):
        diagnostics.add("type_mismatch")
        return Truth.UNKNOWN
    return _truth(
        {
            "eq": comparison == 0,
            "lt": comparison < 0,
            "lte": comparison <= 0,
            "gt": comparison > 0,
            "gte": comparison >= 0,
        }[op]
    )


def compare_keys(
    left: Sequence[Any], right: Sequence[Any], ordering: Sequence[Order]
) -> int:
    for a, b, order in zip(left, right, ordering):
        if a is None or b is None:
            difference = (a is None) - (b is None)
        else:
            if order.field.endswith("_at"):
                a, b = timestamp(a), timestamp(b)
            difference = ((a > b) - (a < b)) * (-1 if order.descending else 1)
        if difference:
            return difference
    return 0


def sorted_keys(
    keys: Sequence[tuple[Any, ...]], ordering: Sequence[Order]
) -> list[tuple[Any, ...]]:
    return sorted(keys, key=cmp_to_key(lambda a, b: compare_keys(a, b, ordering)))
