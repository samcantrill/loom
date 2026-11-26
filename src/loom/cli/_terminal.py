"""Plain-text layouts for bounded coordinator observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import shutil
import textwrap
from typing import Any

from loom.timestamps import parse_timestamp, utc_now


def cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple, Mapping)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    # Authored labels and error messages can contain line breaks and ANSI escapes.
    return "".join(c if c.isprintable() else ascii(c)[1:-1] for c in str(value))


def age(when: str | None, as_of: str | None = None) -> str:
    if not when:
        return "unknown"
    try:
        observed = parse_timestamp(as_of) if as_of else utc_now()
        seconds = int((observed - parse_timestamp(when)).total_seconds())
    except ValueError:
        return "unknown"
    if seconds < 0:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    wide: bool = False,
    continuation_column: int | None = None,
    priority_columns: Sequence[int] = (),
    row_details: Sequence[Sequence[str]] | None = None,
    empty: str,
) -> str:
    """Align one row per entity, followed by its optional explanatory lines."""
    if not rows:
        return empty
    body = [[cell(value) for value in row] for row in rows]
    widths = [
        max(len(header), *(len(row[i]) for row in body))
        for i, header in enumerate(headers)
    ]
    columns = shutil.get_terminal_size().columns

    def details(index: int) -> list[str]:
        lines = []
        if row_details is not None:
            for detail in row_details[index]:
                lines.extend(textwrap.wrap(cell(detail), width=max(columns, 8),
                                           initial_indent="  ", subsequent_indent="    "))
        return lines

    if not wide:
        # Give each column its heading, then share spare room among long values.
        budget = columns - 2 * (len(headers) - 1) - sum(map(len, headers))
        if budget < 0:
            # On a very narrow terminal the headings alone would overflow.
            records = []
            for index, row in enumerate(body):
                lines = []
                for header, value in zip(headers, row, strict=True):
                    lines.extend(
                        textwrap.wrap(
                            f"{header}: {value}",
                            width=max(8, columns),
                            subsequent_indent="  ",
                        )
                    )
                records.append("\n".join([*lines, *details(index)]))
            return "\n\n".join(records)
        fitted = list(map(len, headers))
        for index in priority_columns:
            extra = min(budget, widths[index] - fitted[index])
            fitted[index] += extra
            budget -= extra
        while budget and fitted != widths:
            for i, width in enumerate(widths):
                if budget and fitted[i] < width:
                    fitted[i] += 1
                    budget -= 1
        widths = fitted

    def line(values: Sequence[str]) -> str:
        return "  ".join(
            s.ljust(w) for s, w in zip(values, widths, strict=True)
        ).rstrip()

    lines = [line(headers)]
    for index, row in enumerate(body):
        extra = None
        for i, (value, width) in enumerate(zip(row, widths, strict=True)):
            if len(value) <= width:
                continue
            if i == continuation_column:
                extra = f"{headers[i].capitalize()}: {value}"
                row[i] = "↓"
            else:
                # Common prefixes make the distinguishing suffix of an ID valuable.
                start = width // 2
                end = width - start - 1
                row[i] = value[:start] + "…" + (value[-end:] if end else "")
        lines.append(line(row))
        if extra is not None:
            lines.extend(
                textwrap.wrap(
                    extra,
                    width=max(columns, 8),
                    initial_indent="  ",
                    subsequent_indent="    ",
                )
            )
        lines.extend(details(index))
    return "\n".join(lines)


def fields(
    payload: Mapping[str, Any], keys: Sequence[str], *, indent: str = "",
    literal_keys: bool = False,
) -> list[str]:
    """Present nested fields, preserving authored keys when requested."""
    lines = []
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        label = cell(key) if literal_keys else key.replace("_", " ")
        if isinstance(value, Mapping) and value:
            lines.append(f"{indent}{label}:")
            lines.extend(fields(value, tuple(value), indent=indent + "  ", literal_keys=literal_keys))
        elif isinstance(value, (list, tuple)) and any(
            isinstance(item, Mapping) for item in value
        ):
            lines.append(f"{indent}{label}:")
            for i, item in enumerate(value, 1):
                lines.append(f"{indent}  {i}.")
                if isinstance(item, Mapping):
                    lines.extend(fields(item, tuple(item), indent=indent + "    ", literal_keys=literal_keys))
                else:
                    lines.append(indent + "    " + cell(item))
        else:
            lines.append(f"{indent}{label}: {cell(value)}")
    return lines


def page_text(
    content: str, page: Mapping[str, Any], *, cursor_option: str = "--cursor"
) -> str:
    lines = [content]
    if page.get("coverage", {}).get("complete") is False:
        lines.append(
            f"Coverage incomplete ({cell(page.get('examined'))} candidates examined)."
        )
    for warning in page.get("warnings", []):
        code = warning.get("code", "unknown")
        detail = ", ".join(
            f"{k}={cell(v)}"
            for k, v in warning.items()
            if k != "code" and v is not None
        )
        lines.append(f"Warning: {cell(code)}" + (f" ({detail})" if detail else ""))
    if page.get("next_cursor"):
        lines.append(f"Continue with {cursor_option} {page['next_cursor']}")
    return "\n".join(lines)
