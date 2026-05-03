"""Timestamp helpers for loom metadata."""

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

_TIMESPEC = Literal["seconds", "milliseconds", "microseconds"]
_METADATA_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)"
)


def utc_now() -> datetime:
    """Return the current UTC datetime."""

    return datetime.now(timezone.utc)


def utc_timestamp(value: datetime | None = None, *, timespec: _TIMESPEC = "seconds") -> str:
    """Format a UTC timestamp as ISO-8601 with ``Z`` suffix."""

    dt = _to_utc_datetime(value)
    if timespec == "seconds":
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    if timespec == "milliseconds":
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if timespec == "microseconds":
        return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
    raise ValueError(f"Unsupported timespec '{timespec}'. Expected seconds, milliseconds, or microseconds.")


def safe_timestamp_for_path(value: datetime | None = None, *, timespec: _TIMESPEC = "seconds") -> str:
    """Return a path-safe UTC timestamp string."""

    dt = _to_utc_datetime(value)
    if timespec == "seconds":
        return f"{dt:%Y%m%dT%H%M%S}Z"
    if timespec == "milliseconds":
        milliseconds = dt.microsecond // 1000
        return f"{dt:%Y%m%dT%H%M%S}{milliseconds:03d}Z"
    if timespec == "microseconds":
        return f"{dt:%Y%m%dT%H%M%S}{dt.microsecond:06d}Z"
    raise ValueError(f"Unsupported timespec '{timespec}'. Expected seconds, milliseconds, or microseconds.")


def parse_timestamp(value: str) -> datetime:
    """Parse loom-authored UTC timestamps into UTC datetime objects."""

    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Unable to parse loom timestamp: {value}") from exc

    if parsed.tzinfo is None:
        raise ValueError(f"Unable to parse loom timestamp: naive datetime {value!r} is not supported")
    if parsed.tzinfo.utcoffset(parsed) != timedelta(0):
        raise ValueError("Only UTC loom timestamps are supported")
    if _METADATA_TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError(f"Unable to parse loom timestamp: expected extended UTC metadata form {value!r}")
    return parsed.astimezone(timezone.utc)


def _to_utc_datetime(value: datetime | None = None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        raise ValueError("Expected timezone-aware datetime in UTC or with offset.")
    return value.astimezone(timezone.utc)
