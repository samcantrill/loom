"""Per-page distinct vocabulary observations over bounded native run pages."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from loom.timestamps import utc_timestamp
from ._query_page import QueryPage, _bytes
from .query import Field, InvalidCursorError, RunQuery


def vocabulary_page(
    search: Callable[[RunQuery], QueryPage],
    operation: str,
    request: Mapping[str, Any],
    owner: str,
) -> QueryPage:
    """Re-read pending annotations; cursor values never replace owning facts."""
    binding = {
        "schema_version": 1,
        "coordinator_id": owner,
        "operation": operation,
        "scope": request["scope"],
        "limit": request["limit"],
        "key": request.get("key"),
    }
    digest = hashlib.sha256(_bytes(binding)).hexdigest()
    before = pending = after = None
    if request["cursor"] is not None:
        try:
            token = json.loads(
                base64.b64decode(request["cursor"], altchars=b"-_", validate=True)
            )
            if (
                set(token) != {"binding", "before", "pending", "after"}
                or token["binding"] != digest
            ):
                raise ValueError("cursor binding")
            before, pending, after = token["before"], token["pending"], token["after"]
            if any(
                v is not None and not isinstance(v, str)
                for v in (before, pending, after)
            ) or (pending is None) != (after is None):
                raise ValueError("cursor fields")
        except (ValueError, TypeError, KeyError) as exc:
            raise InvalidCursorError("invalid_cursor") from exc
    values: set[str] = set()
    warnings: list[Mapping[str, Any]] = []
    complete = True
    examined = suppressed = 0
    continuation = None
    value_bytes = 0
    byte_limit = False

    def cursor(
        run_before: str | None, run: str | None = None, value: str | None = None
    ) -> str:
        return base64.urlsafe_b64encode(
            _bytes(
                {
                    "binding": digest,
                    "before": run_before,
                    "pending": run,
                    "after": value,
                }
            )
        ).decode()

    while examined < 500:
        page = search(
            RunQuery(
                scope=request["scope"], select=(Field("tags"),), limit=1, cursor=before
            ).checked()
        )
        examined += page.examined
        complete = complete and page.complete
        retained = page.warnings[: max(0, 100 - len(warnings))]
        warnings.extend(retained)
        suppressed += len(page.warnings) - len(retained)
        if page.items:
            item = page.items[0]
            fields = item.get("fields", [])
            tags = (
                fields[0].get("value")
                if fields and fields[0].get("availability") == "present"
                else None
            )
            if not isinstance(tags, Mapping):
                complete = False
                if len(warnings) < 100:
                    warnings.append(
                        {"code": "annotations_unavailable", "run_uri": item["identity"]}
                    )
                else:
                    suppressed += 1
                observed: list[str] = []
            elif operation == "tag_keys":
                observed = sorted(tags)
            else:
                observed = [tags[request["key"]]] if request["key"] in tags else []
            start_after = after if item["identity"] == pending else None
            remaining = [v for v in observed if start_after is None or v > start_after]
            for index, value in enumerate(remaining):
                size = len(_bytes(value)) + 32 if value not in values else 0
                if value_bytes + size > 640 * 1024:
                    previous = remaining[index - 1] if index else start_after
                    continuation = (
                        cursor(before, item["identity"], previous)
                        if previous is not None
                        else cursor(before)
                    )
                    byte_limit = True
                    break
                value_bytes += size
                values.add(value)
                if len(values) == request["limit"]:
                    continuation = (
                        cursor(before, item["identity"], value)
                        if index + 1 < len(remaining)
                        else cursor(page.next_cursor)
                        if page.next_cursor is not None
                        else None
                    )
                    break
            if byte_limit or len(values) == request["limit"]:
                break
        if page.next_cursor is None:
            break
        before, pending, after = page.next_cursor, None, None
        if examined >= 500:
            continuation = cursor(before)
            break
    while len(_bytes(warnings)) > 64 * 1024:
        warnings.pop()
        suppressed += 1
    if suppressed:
        warnings.append({"code": "warnings_truncated", "suppressed": suppressed})
    label = "key" if operation == "tag_keys" else "value"
    return QueryPage(
        tuple({label: value} for value in sorted(values)),
        continuation,
        request["scope"],
        owner,
        utc_timestamp(),
        tuple(warnings),
        complete,
        examined,
    )


@dataclass(frozen=True)
class VocabularyCollection:
    """Unique observed strings plus every page's coverage and observation evidence."""

    values: tuple[str, ...]
    pages: tuple[QueryPage, ...]

    @property
    def complete(self) -> bool:
        return all(page.complete for page in self.pages) and (
            not self.pages or self.pages[-1].next_cursor is None
        )

    @property
    def warnings(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(warning for page in self.pages for warning in page.warnings)


def collect_vocabulary(
    fetch: Callable[[str | None], QueryPage],
) -> VocabularyCollection:
    """Union key/value observations; ``fetch(cursor)`` must retain one scope/query."""
    pages: list[QueryPage] = []
    values: set[str] = set()
    cursor = None
    while True:
        page = fetch(cursor)
        pages.append(page)
        for item in page.items:
            values.add(item["key"] if "key" in item else item["value"])
        cursor = page.next_cursor
        if cursor is None:
            return VocabularyCollection(tuple(sorted(values)), tuple(pages))
