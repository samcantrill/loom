"""Bounded live page assembly shared by local and native discovery."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any

from loom.timestamps import utc_timestamp

from .query import (
    InvalidCursorError,
    MISSING,
    UNAVAILABLE,
    QUERY_LIMITS,
    QueryRecord,
    RunQuery,
    Truth,
    compare_keys,
    evaluate,
    field_value,
    identity_field,
    timestamp,
)


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True
    ).encode()


@dataclass(frozen=True)
class QueryPage:
    """One live observation, including coverage even for empty continuing pages."""

    items: tuple[Mapping[str, Any], ...]
    next_cursor: str | None
    scope: Mapping[str, Any]
    coordinator_id: str
    observed_at: str
    warnings: tuple[Mapping[str, Any], ...] = ()
    complete: bool = True
    examined: int = 0
    consistency: str = "live_keyset"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "items": list(self.items),
            "next_cursor": self.next_cursor,
            "scope": dict(self.scope),
            "coordinator_id": self.coordinator_id,
            "observed_at": self.observed_at,
            "warnings": list(self.warnings),
            "coverage": {"complete": self.complete},
            "examined": self.examined,
            "consistency": self.consistency,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> QueryPage:
        if (
            set(value)
            != {
                "schema_version",
                "items",
                "next_cursor",
                "scope",
                "coordinator_id",
                "observed_at",
                "warnings",
                "coverage",
                "examined",
                "consistency",
            }
            or value["schema_version"] != 1
            or value["consistency"] != "live_keyset"
        ):
            raise ValueError("invalid query page")
        if (
            not isinstance(value["items"], list)
            or len(value["items"]) > 200
            or any(not isinstance(v, Mapping) for v in value["items"])
        ):
            raise ValueError("invalid query items")
        if value["next_cursor"] is not None and not isinstance(
            value["next_cursor"], str
        ):
            raise ValueError("invalid page cursor")
        if (
            type(value["coverage"].get("complete")) is not bool
            or type(value["examined"]) is not int
            or not 0 <= value["examined"] <= 500
        ):
            raise ValueError("invalid page coverage")
        timestamp(value["observed_at"])
        return cls(
            tuple(value["items"]),
            value["next_cursor"],
            value["scope"],
            value["coordinator_id"],
            value["observed_at"],
            tuple(value["warnings"]),
            value["coverage"]["complete"],
            value["examined"],
        )


@dataclass(frozen=True)
class QueryCollection:
    """Collected exact selections plus retained warnings and live-page observations."""

    items: tuple[Mapping[str, Any], ...]
    pages: tuple[QueryPage, ...]

    @property
    def complete(self) -> bool:
        return all(page.complete for page in self.pages) and (
            not self.pages or self.pages[-1].next_cursor is None
        )

    @property
    def warnings(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(warning for page in self.pages for warning in page.warnings)


def collect_pages(
    search: Callable[[RunQuery], QueryPage], query: RunQuery
) -> QueryCollection:
    """Follow every continuation, retaining incomplete empty pages and observations."""
    pages: list[QueryPage] = []
    items: list[Mapping[str, Any]] = []
    while True:
        page = search(query)
        pages.append(page)
        items.extend(page.items)
        if page.next_cursor is None:
            return QueryCollection(tuple(items), tuple(pages))
        query = replace(query, cursor=page.next_cursor)


def cursor_context(query: RunQuery, owner: str) -> dict[str, Any]:
    raw = query.to_dict()
    raw.pop("cursor")
    return {
        "schema_version": 1,
        "scope": raw["scope"],
        "coordinator_id": owner,
        "entity": query.entity,
        "digest": hashlib.sha256(_bytes(raw)).hexdigest(),
        "ordering": raw["order_by"],
    }


def after_cursor(query: RunQuery, owner: str) -> tuple[Any, ...] | None:
    if query.cursor is None:
        return None
    try:
        value = json.loads(
            base64.b64decode(query.cursor, altchars=b"-_", validate=True)
        )
        last = value.pop("last")
        if (
            value != cursor_context(query, owner)
            or not isinstance(last, list)
            or len(last) != len(query.order_by)
        ):
            raise ValueError("cursor binding mismatch")
        for value, order in zip(last, query.order_by):
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError("cursor key type")
                if order.field.endswith("_at"):
                    timestamp(value)
            elif not order.field.endswith("_at"):
                raise ValueError("missing identity")
        return tuple(last)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InvalidCursorError("invalid_cursor") from exc


def _cursor(query: RunQuery, owner: str, last: Sequence[Any]) -> str:
    return base64.urlsafe_b64encode(
        _bytes({**cursor_context(query, owner), "last": list(last)})
    ).decode()


def _safe(value: Any) -> Any:
    if value is MISSING or value is UNAVAILABLE:
        return None
    if isinstance(value, Mapping):
        return {
            k: _safe(v)
            for k, v in value.items()
            if v is not MISSING and v is not UNAVAILABLE
        }
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    return value


def search_page(
    query: RunQuery,
    owner: str,
    candidates: Sequence[tuple[tuple[Any, ...], Any]],
    acquire: Callable[[Any], QueryRecord],
    *,
    warnings: Sequence[Mapping[str, Any]] = (),
) -> QueryPage:
    """Acquire at most 500 ordered candidates outside owner write transactions."""
    last = after_cursor(query, owner)
    pending = [
        (key, candidate)
        for key, candidate in candidates
        if last is None or compare_keys(key, last, query.order_by) > 0
    ]
    items: list[Mapping[str, Any]] = []
    reports: list[Mapping[str, Any]] = list(warnings[:100])
    suppressed = max(0, len(warnings) - 100)
    complete = not warnings
    diagnostics: set[str] = set()
    examined = 0
    budget = 0
    more = False
    for key, candidate in pending[: QUERY_LIMITS["candidates"]]:
        record = acquire(candidate)
        complete = complete and not record.warnings
        retained = record.warnings[: max(0, 100 - len(reports))]
        reports.extend(retained)
        suppressed += len(record.warnings) - len(retained)
        matches: list[dict[str, Any]] = []
        result = evaluate(query.where, record, diagnostics=diagnostics, matches=matches)
        item: dict[str, Any] | None = None
        if result is Truth.TRUE and record.eligible:
            native = record.sources.get("native", {})
            item = {
                "identity": native[identity_field(query.entity)],
                "native": _safe(native),
                "observation": record.observation,
                "matches": matches,
            }
            if query.select:
                item["fields"] = [
                    {
                        "field": f.to_dict(),
                        "availability": "unavailable"
                        if (v := field_value(record, f.to_dict())) is UNAVAILABLE
                        else "missing"
                        if v is MISSING
                        else "present",
                        "value": _safe(v),
                    }
                    for f in query.select
                ]
            else:
                item["sources"] = _safe(
                    {
                        k: v
                        for k, v in record.sources.items()
                        if k not in {"native", "notes"}
                    }
                )
            size = len(_bytes(item))
            # A vocabulary projection must retain a valid 48 KiB annotation
            # document even when JSON escaping expands its Unicode strings.
            tags_only = (
                len(query.select) == 1
                and query.select[0].source == "tags"
                and not query.select[0].path
            )
            record_limit = 320 * 1024 if tags_only else 64 * 1024
            if size > record_limit:
                item = {
                    "identity": item["identity"],
                    "truncated": True,
                    "diagnostic": "oversize_record",
                    "reference": {
                        k: _safe(native[k])
                        for k in (identity_field(query.entity), "run_uri")
                        if k in native
                    },
                }
                size = len(_bytes(item))
            if budget + size > 640 * 1024 and items:
                more = True
                break
            budget += size
            items.append(item)
        examined += 1
        last = key
        if len(items) >= query.limit:
            break
    more = more or examined < len(pending)
    if "source_unavailable" in diagnostics:
        complete = False
    reports.extend({"code": code, "aggregate": True} for code in sorted(diagnostics))
    while len(_bytes(reports)) > 64 * 1024:
        reports.pop()
        suppressed += 1
    if suppressed:
        reports.append({"code": "warnings_truncated", "suppressed": suppressed})
    return QueryPage(
        tuple(items),
        _cursor(query, owner, last) if more and last is not None else None,
        query.scope,
        owner,
        utc_timestamp(),
        tuple(reports),
        complete,
        examined,
    )
