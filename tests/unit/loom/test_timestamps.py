"""Unit tests for loom timestamp helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from loom.timestamps import parse_timestamp, safe_timestamp_for_path, utc_now, utc_timestamp


def test_utc_now_returns_aware_utc_datetime() -> None:
    now = utc_now()
    assert now.tzinfo == timezone.utc
    assert now >= datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_utc_timestamp_formats_with_supported_precision() -> None:
    source = datetime(2026, 5, 3, 12, 34, 56, 123456, tzinfo=timezone.utc)
    assert utc_timestamp(source, timespec="seconds") == "2026-05-03T12:34:56Z"
    assert utc_timestamp(source, timespec="milliseconds") == "2026-05-03T12:34:56.123Z"
    assert utc_timestamp(source, timespec="microseconds") == "2026-05-03T12:34:56.123456Z"


def test_utc_timestamp_normalizes_to_utc() -> None:
    source = datetime(2026, 5, 3, 14, 0, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert utc_timestamp(source, timespec="seconds") == "2026-05-03T12:00:00Z"


def test_utc_timestamp_rejects_invalid_timespec() -> None:
    with pytest.raises(ValueError, match="Unsupported timespec"):
        utc_timestamp(datetime(2026, 5, 3, tzinfo=timezone.utc), timespec="minutes")  # type: ignore[arg-type]


def test_safe_timestamp_for_path_is_path_safe_and_precise() -> None:
    source = datetime(2026, 5, 3, 12, 34, 56, 123456, tzinfo=timezone.utc)
    assert safe_timestamp_for_path(source, timespec="seconds") == "20260503T123456Z"
    assert safe_timestamp_for_path(source, timespec="milliseconds") == "20260503T123456123Z"
    assert safe_timestamp_for_path(source, timespec="microseconds") == "20260503T123456123456Z"
    for value in [
        safe_timestamp_for_path(source, timespec="seconds"),
        safe_timestamp_for_path(source, timespec="milliseconds"),
        safe_timestamp_for_path(source, timespec="microseconds"),
    ]:
        assert ":" not in value
        assert " " not in value


def test_safe_timestamp_for_path_rejects_invalid_timespec() -> None:
    with pytest.raises(ValueError, match="Unsupported timespec"):
        safe_timestamp_for_path(datetime(2026, 1, 1, tzinfo=timezone.utc), timespec="minutes")  # type: ignore[arg-type]


def test_parse_timestamp_accepts_z_and_utc_offsets() -> None:
    utc = utc_timestamp(datetime(2026, 5, 3, 12, 34, 56, 500000, tzinfo=timezone.utc), timespec="microseconds")
    parsed_from_z = parse_timestamp(utc)
    parsed_from_offset = parse_timestamp("2026-05-03T12:34:56.500000+00:00")

    assert parsed_from_z.tzinfo == timezone.utc
    assert parsed_from_offset == parsed_from_z


def test_parse_timestamp_rejects_naive_or_non_utc_strings() -> None:
    with pytest.raises(ValueError, match="naive"):
        parse_timestamp("2026-05-03T12:34:56.123456")
    with pytest.raises(ValueError, match="Only UTC"):
        parse_timestamp("2026-05-03T12:34:56+01:00")
